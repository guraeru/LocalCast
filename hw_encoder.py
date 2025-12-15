#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高速画面キャプチャモジュール v4.0

機能:
- 正確なウィンドウキャプチャ（PrintWindow API使用）
- 高速モニターキャプチャ（mss使用）
- 4K/HD解像度上限選択
- 高画質JPEG (品質90-95)
- 安定したフレームレート
"""

import threading
import time
import numpy as np
import cv2
import base64
import mss
from dataclasses import dataclass
from typing import Optional, Callable
from enum import Enum

# Windows API
try:
    import win32gui
    import win32ui
    import win32con
    import win32api
    from ctypes import windll
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("⚠️ pywin32未インストール: pip install pywin32")


class ResolutionLimit(Enum):
    """解像度上限"""
    HD = "hd"           # 1280x720
    FULL_HD = "fullhd"  # 1920x1080
    QHD = "qhd"         # 2560x1440
    UHD_4K = "4k"       # 3840x2160
    NATIVE = "native"   # 元の解像度


# 解像度上限の実際の値
RESOLUTION_LIMITS = {
    ResolutionLimit.HD: (1280, 720),
    ResolutionLimit.FULL_HD: (1920, 1080),
    ResolutionLimit.QHD: (2560, 1440),
    ResolutionLimit.UHD_4K: (3840, 2160),
    ResolutionLimit.NATIVE: (99999, 99999),
}


@dataclass 
class FrameStats:
    """フレーム統計"""
    capture_time_ms: float = 0
    encode_time_ms: float = 0
    total_time_ms: float = 0
    frame_size_kb: float = 0
    fps: float = 0
    dropped_frames: int = 0
    resolution: str = ""


class QualityController:
    """品質コントローラー"""
    
    def __init__(self, target_fps: int = 30, initial_quality: int = 90):
        self.target_fps = target_fps
        self.target_frame_time = 1000.0 / target_fps
        
        self.current_quality = initial_quality
        self.current_scale = 1.0
        self.min_quality = 70
        self.max_quality = 95
        
        self.frame_times = []
        self.cooldown = 0
    
    def update(self, frame_time_ms: float):
        """フレーム時間に基づいて調整"""
        self.frame_times.append(frame_time_ms)
        if len(self.frame_times) > 20:
            self.frame_times.pop(0)
        
        if self.cooldown > 0:
            self.cooldown -= 1
            return
        
        if len(self.frame_times) < 5:
            return
        
        avg_time = sum(self.frame_times) / len(self.frame_times)
        
        if avg_time > self.target_frame_time * 1.3:
            if self.current_quality > self.min_quality:
                self.current_quality = max(self.min_quality, self.current_quality - 5)
                self.cooldown = 15
        elif avg_time < self.target_frame_time * 0.6:
            if self.current_quality < self.max_quality:
                self.current_quality = min(self.max_quality, self.current_quality + 3)
                self.cooldown = 15
    
    def reset(self, quality: int = 90):
        self.current_quality = quality
        self.current_scale = 1.0
        self.frame_times.clear()
        self.cooldown = 0


class WindowCapture:
    """
    正確なウィンドウキャプチャ
    PrintWindow APIを使用して、他のウィンドウに隠れていても
    正しくウィンドウの内容をキャプチャする
    """
    
    def __init__(self):
        if not HAS_WIN32:
            raise RuntimeError("pywin32が必要です: pip install pywin32")
        
        # PrintWindow用のフラグ
        # PW_RENDERFULLCONTENT = 2 (Windows 8.1以降で全コンテンツをレンダリング)
        self.PW_RENDERFULLCONTENT = 2
    
    def capture(self, hwnd: int) -> Optional[np.ndarray]:
        """
        ウィンドウをキャプチャ（PrintWindow API使用）
        
        他のウィンドウに隠れていても、正しくウィンドウの内容を取得できる
        
        Args:
            hwnd: ウィンドウハンドル
            
        Returns:
            numpy配列 (BGR) または None
        """
        if not win32gui.IsWindow(hwnd):
            return None
        
        hwndDC = None
        mfcDC = None
        saveDC = None
        saveBitMap = None
        
        try:
            # ウィンドウサイズを取得（タイトルバーを含む）
            rect = win32gui.GetWindowRect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            
            if w <= 0 or h <= 0:
                return None
            
            # デバイスコンテキストを取得
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            
            # ビットマップ作成
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
            saveDC.SelectObject(saveBitMap)
            
            # PrintWindowでキャプチャ
            # これにより他のウィンドウに隠れていても正しくキャプチャできる
            result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), self.PW_RENDERFULLCONTENT)
            
            if result == 0:
                # PrintWindowが失敗した場合（古いウィンドウなど）はBitBltを試す
                saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)
            
            # ビットマップデータを取得
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            
            # numpy配列に変換
            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img = img.reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
            
            # BGRA -> BGR
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
            return img
            
        except Exception as e:
            return None
            
        finally:
            # 必ずリソースを解放
            try:
                if saveBitMap:
                    win32gui.DeleteObject(saveBitMap.GetHandle())
                if saveDC:
                    saveDC.DeleteDC()
                if mfcDC:
                    mfcDC.DeleteDC()
                if hwndDC:
                    win32gui.ReleaseDC(hwnd, hwndDC)
            except:
                pass


class ScreenCapture:
    """画面キャプチャエンジン v4.0"""
    
    def __init__(self,
                 target_fps: int = 30,
                 jpeg_quality: int = 90,
                 resolution_limit: str = "fullhd",
                 use_adaptive: bool = False):
        
        self.target_fps = target_fps
        self.jpeg_quality = jpeg_quality
        self.use_adaptive = use_adaptive
        
        # 解像度上限
        self._set_resolution_limit(resolution_limit)
        
        # 状態
        self.is_running = False
        self.capture_thread: Optional[threading.Thread] = None
        self.frame_callback: Optional[Callable] = None
        
        # 統計
        self.stats = FrameStats()
        self.stats_lock = threading.Lock()
        
        # 品質コントローラー
        self.quality_controller = QualityController(target_fps, jpeg_quality)
        
        # キャプチャ設定
        self.capture_type = 'monitor'
        self.monitor_id = 1
        self.window_handle = None
        
        # ウィンドウキャプチャ用
        self._window_capture: Optional[WindowCapture] = None
    
    def _set_resolution_limit(self, limit: str):
        """解像度上限を設定"""
        limit_map = {
            'hd': ResolutionLimit.HD,
            'fullhd': ResolutionLimit.FULL_HD,
            'qhd': ResolutionLimit.QHD,
            '4k': ResolutionLimit.UHD_4K,
            'native': ResolutionLimit.NATIVE,
        }
        self.resolution_limit = limit_map.get(limit.lower(), ResolutionLimit.FULL_HD)
        self.max_width, self.max_height = RESOLUTION_LIMITS[self.resolution_limit]
        print(f"[Capture] 解像度上限: {self.resolution_limit.value} ({self.max_width}x{self.max_height})")
    
    def set_resolution_limit(self, limit: str):
        """解像度上限を変更"""
        self._set_resolution_limit(limit)
    
    def start(self,
              capture_type: str = 'monitor',
              monitor_id: int = 1,
              window_handle: int = None,
              frame_callback: Callable = None) -> bool:
        """キャプチャ開始"""
        if self.is_running:
            self.stop()
        
        self.capture_type = capture_type
        self.monitor_id = monitor_id
        self.window_handle = window_handle
        self.frame_callback = frame_callback
        
        # ウィンドウキャプチャの場合は専用クラスを使用
        if capture_type == 'window' and window_handle:
            if not HAS_WIN32:
                print("[Capture] ❌ ウィンドウキャプチャにはpywin32が必要です")
                return False
            self._window_capture = WindowCapture()
            print(f"[Capture] ✅ 開始: type=window, hwnd={window_handle}, fps={self.target_fps}, quality={self.jpeg_quality}")
        else:
            print(f"[Capture] ✅ 開始: type=monitor, id={monitor_id}, fps={self.target_fps}, quality={self.jpeg_quality}")
        
        self.is_running = True
        
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="ScreenCaptureThread"
        )
        self.capture_thread.start()
        
        return True
    
    def stop(self):
        """キャプチャ停止"""
        self.is_running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=3)
        self.capture_thread = None
        self._window_capture = None
        print("[Capture] ⏹️ 停止")
    
    def _capture_loop(self):
        """メインキャプチャループ"""
        sct = mss.mss() if self.capture_type == 'monitor' else None
        frame_interval = 1.0 / self.target_fps
        
        frame_count = 0
        dropped = 0
        fps_samples = []
        last_report = time.time()
        
        print(f"[Capture] 🔄 ループ開始 (間隔={frame_interval*1000:.1f}ms)")
        
        while self.is_running:
            loop_start = time.perf_counter()
            
            try:
                # === 1. キャプチャ ===
                t1 = time.perf_counter()
                
                if self.capture_type == 'window' and self._window_capture:
                    raw_img = self._window_capture.capture(self.window_handle)
                else:
                    raw_img = self._grab_monitor(sct)
                
                if raw_img is None:
                    time.sleep(0.05)
                    continue
                
                capture_ms = (time.perf_counter() - t1) * 1000
                
                # === 2. リサイズ（解像度上限適用）===
                t2 = time.perf_counter()
                img = self._resize_to_limit(raw_img)
                resize_ms = (time.perf_counter() - t2) * 1000
                
                # === 3. JPEGエンコード ===
                t3 = time.perf_counter()
                
                quality = self.quality_controller.current_quality if self.use_adaptive else self.jpeg_quality
                
                # 高画質エンコード設定
                # JPEG_SAMPLING_FACTOR: 0x111111 = 4:4:4 (最高画質、色情報を間引かない)
                encode_params = [
                    cv2.IMWRITE_JPEG_QUALITY, quality,
                    cv2.IMWRITE_JPEG_OPTIMIZE, 1,
                    cv2.IMWRITE_JPEG_SAMPLING_FACTOR, 0x111111,  # 4:4:4 サブサンプリング
                ]
                success, buffer = cv2.imencode('.jpg', img, encode_params)
                
                if not success:
                    continue
                
                img_bytes = buffer.tobytes()
                encode_ms = (time.perf_counter() - t3) * 1000
                
                total_ms = capture_ms + resize_ms + encode_ms
                
                # === 4. 適応品質更新 ===
                if self.use_adaptive:
                    self.quality_controller.update(total_ms)
                
                # === 5. フレームドロップ判定 ===
                if total_ms > frame_interval * 1000 * 2:
                    dropped += 1
                
                # === 6. コールバック ===
                if self.frame_callback and img_bytes:
                    img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                    
                    frame_data = {
                        'image': img_b64,
                        'width': img.shape[1],
                        'height': img.shape[0],
                        'size': len(img_bytes),
                        'timestamp': time.time(),
                        'quality': quality,
                    }
                    
                    try:
                        self.frame_callback(frame_data)
                        frame_count += 1
                    except Exception as e:
                        print(f"[Capture] コールバックエラー: {e}")
                
                # === 7. 統計 ===
                fps_samples.append(total_ms)
                if len(fps_samples) > 30:
                    fps_samples.pop(0)
                
                now = time.time()
                if now - last_report >= 3:
                    avg_ms = sum(fps_samples) / len(fps_samples) if fps_samples else 0
                    actual_fps = 1000.0 / avg_ms if avg_ms > 0 else 0
                    
                    with self.stats_lock:
                        self.stats.fps = actual_fps
                        self.stats.capture_time_ms = capture_ms
                        self.stats.encode_time_ms = encode_ms
                        self.stats.total_time_ms = total_ms
                        self.stats.frame_size_kb = len(img_bytes) / 1024
                        self.stats.dropped_frames = dropped
                        self.stats.resolution = f"{img.shape[1]}x{img.shape[0]}"
                    
                    print(f"[Capture] 📊 FPS: {actual_fps:.1f}, "
                          f"解像度: {img.shape[1]}x{img.shape[0]}, "
                          f"サイズ: {len(img_bytes)/1024:.0f}KB, "
                          f"品質: {quality}%"
                          f"{f', ドロップ: {dropped}' if dropped > 0 else ''}")
                    last_report = now
                
                # === 8. フレーム間隔調整 ===
                elapsed = time.perf_counter() - loop_start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0.001:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                print(f"[Capture] エラー: {e}")
                time.sleep(0.1)
        
        if sct:
            sct.close()
        print(f"[Capture] 🏁 終了 (フレーム: {frame_count}, ドロップ: {dropped})")
    
    def _grab_monitor(self, sct) -> Optional[np.ndarray]:
        """モニターをキャプチャ（mss使用）"""
        try:
            monitors = sct.monitors
            if self.monitor_id >= len(monitors):
                self.monitor_id = 1
            
            monitor = monitors[self.monitor_id]
            screenshot = sct.grab(monitor)
            
            img = np.array(screenshot, dtype=np.uint8)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
            return img
        except Exception as e:
            print(f"[Capture] モニターキャプチャエラー: {e}")
            return None
    
    def _resize_to_limit(self, img: np.ndarray) -> np.ndarray:
        """解像度上限に合わせてリサイズ（テキスト品質優先）"""
        h, w = img.shape[:2]
        
        if w <= self.max_width and h <= self.max_height:
            return img
        
        scale_w = self.max_width / w
        scale_h = self.max_height / h
        scale = min(scale_w, scale_h)
        
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        # INTER_LANCZOS4: 高品質リサイズ（テキストの鮮明さを維持）
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        return resized
    
    def get_stats(self) -> FrameStats:
        """統計取得"""
        with self.stats_lock:
            return FrameStats(
                capture_time_ms=self.stats.capture_time_ms,
                encode_time_ms=self.stats.encode_time_ms,
                total_time_ms=self.stats.total_time_ms,
                frame_size_kb=self.stats.frame_size_kb,
                fps=self.stats.fps,
                dropped_frames=self.stats.dropped_frames,
                resolution=self.stats.resolution,
            )
    
    def update_settings(self,
                       fps: int = None,
                       quality: int = None,
                       resolution_limit: str = None,
                       use_adaptive: bool = None):
        """設定更新"""
        if fps is not None:
            self.target_fps = fps
            self.quality_controller.target_fps = fps
            self.quality_controller.target_frame_time = 1000.0 / fps
        
        if quality is not None:
            self.jpeg_quality = quality
            self.quality_controller.current_quality = quality
        
        if resolution_limit is not None:
            self._set_resolution_limit(resolution_limit)
        
        if use_adaptive is not None:
            self.use_adaptive = use_adaptive


# ========================================
# ユーティリティ
# ========================================

def get_ffmpeg_path() -> str:
    """FFmpegのパスを取得（imageio-ffmpegを優先）"""
    # まずimageio-ffmpegから取得を試みる
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path:
            return ffmpeg_path
    except ImportError:
        pass
    
    # フォールバック: システムのffmpeg
    return 'ffmpeg'


def check_nvenc_available() -> dict:
    """NVENC確認"""
    import subprocess
    result = {
        'ffmpeg': False,
        'h264_nvenc': False,
        'hevc_nvenc': False,
        'av1_nvenc': False
    }
    
    ffmpeg_path = get_ffmpeg_path()
    
    try:
        proc = subprocess.run([ffmpeg_path, '-version'],
                            capture_output=True, timeout=5)
        result['ffmpeg'] = proc.returncode == 0
        
        if result['ffmpeg']:
            proc = subprocess.run([ffmpeg_path, '-hide_banner', '-encoders'],
                                capture_output=True, text=True, timeout=5)
            output = proc.stdout
            result['h264_nvenc'] = 'h264_nvenc' in output
            result['hevc_nvenc'] = 'hevc_nvenc' in output
            result['av1_nvenc'] = 'av1_nvenc' in output
    except:
        pass
    
    return result


# 互換性エイリアス
HighPerformanceCapture = ScreenCapture
FastScreenCapture = ScreenCapture
AdaptiveQualityController = QualityController
FastAdaptiveController = QualityController


# ========================================
# テスト
# ========================================

if __name__ == '__main__':
    print("=" * 60)
    print("🎬 画面キャプチャテスト v4.0")
    print("=" * 60)
    
    frame_count = [0]
    def on_frame(data):
        frame_count[0] += 1
    
    # モニターキャプチャテスト
    print("\n🧪 モニターキャプチャテスト (5秒)...")
    capture = ScreenCapture(
        target_fps=30,
        jpeg_quality=90,
        resolution_limit="fullhd",
        use_adaptive=False
    )
    
    capture.start(
        capture_type='monitor',
        monitor_id=1,
        frame_callback=on_frame
    )
    
    time.sleep(5)
    
    stats = capture.get_stats()
    capture.stop()
    
    print(f"\n📊 結果:")
    print(f"   フレーム: {frame_count[0]}")
    print(f"   FPS: {stats.fps:.1f}")
    print(f"   解像度: {stats.resolution}")
    print(f"   サイズ: {stats.frame_size_kb:.0f}KB")
    
    # ウィンドウキャプチャテスト（pywin32がある場合）
    if HAS_WIN32:
        print("\n🧪 ウィンドウキャプチャテスト (PrintWindow API)...")
        
        # 最初に見つかったウィンドウをテスト
        def find_window():
            windows = []
            def callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title and len(title) > 5:
                        windows.append((hwnd, title))
                return True
            win32gui.EnumWindows(callback, None)
            return windows
        
        windows = find_window()
        if windows:
            hwnd, title = windows[0]
            print(f"   テスト対象: {title[:50]}")
            
            frame_count[0] = 0
            capture = ScreenCapture(
                target_fps=30,
                jpeg_quality=90,
                resolution_limit="fullhd"
            )
            
            capture.start(
                capture_type='window',
                window_handle=hwnd,
                frame_callback=on_frame
            )
            
            time.sleep(3)
            
            stats = capture.get_stats()
            capture.stop()
            
            print(f"   フレーム: {frame_count[0]}")
            print(f"   FPS: {stats.fps:.1f}")
            print(f"   解像度: {stats.resolution}")
