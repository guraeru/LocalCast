#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高速画面キャプチャモジュール v5.1 - H.264シンプル版

機能:
- 正確なウィンドウキャプチャ（PrintWindow API使用）
- 高速モニターキャプチャ（mss使用）
- H.264エンコード（FFmpeg NVENC、raw H.264出力）
- JPEGフォールバック
"""

import threading
import time
import numpy as np
import cv2
import base64
import mss
import subprocess
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
    encoder_type: str = "jpeg"


class H264Encoder:
    """
    H.264エンコーダー - シンプル版
    raw H.264 (Annex B) 形式で出力、jmuxerでデコード
    """
    
    def __init__(self, width: int, height: int, fps: int = 30, bitrate: str = "20M"):
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate = bitrate
        self.process: Optional[subprocess.Popen] = None
        self.encoder_type = "unknown"
        self.is_running = False
        self._lock = threading.Lock()
        self._output_buffer = bytearray()
        self._reader_thread: Optional[threading.Thread] = None
        
    def start(self, nvenc_available: dict = None) -> bool:
        """エンコーダーを開始"""
        ffmpeg_path = get_ffmpeg_path()
        nvenc_status = nvenc_available or {'h264_nvenc': False}
        
        # 画質安定化: 短いGOP間隔（全フレームI-frame品質に近づける）
        # keyintは短めにして定期的な画質劣化を防止
        gop_size = self.fps  # 1秒ごとにキーフレーム
        
        # ビットレートを数値に変換（バッファサイズ計算用）
        bitrate_num = self.bitrate.rstrip('MmKk')
        try:
            if 'M' in self.bitrate.upper():
                bufsize = f"{int(float(bitrate_num) * 2)}M"  # ビットレートの2倍
            else:
                bufsize = f"{int(float(bitrate_num) * 2)}K"
        except:
            bufsize = self.bitrate
        
        if nvenc_status['h264_nvenc']:
            # NVENC: 古いFFmpegとの互換性を考慮
            encoder_args = [
                '-c:v', 'h264_nvenc',
                '-preset', 'hq',          # High Quality（ノイズ軽減）
                '-rc', 'vbr_hq',          # VBR High Quality（品質優先）
                '-cq', '20',              # 品質レベル（20=安定、ノイズ少ない）
                '-b:v', self.bitrate,
                '-maxrate', self.bitrate,
                '-bufsize', bufsize,      # 十分なバッファ
                '-profile:v', 'high',
                '-g', str(gop_size),
                '-bf', '0',               # Bフレームなし（低遅延）
                '-zerolatency', '1',
            ]
            self.encoder_type = 'h264_nvenc'
        else:
            encoder_args = [
                '-c:v', 'libx264',
                '-preset', 'fast',        # fast（より高品質）
                '-tune', 'zerolatency',
                '-crf', '20',             # 品質優先（20=安定、ノイズ少ない）
                '-b:v', self.bitrate,
                '-maxrate', self.bitrate,
                '-bufsize', bufsize,
                '-profile:v', 'high',
                '-g', str(gop_size),
                '-bf', '0',
            ]
            self.encoder_type = 'libx264'
        
        cmd = [
            ffmpeg_path,
            '-hide_banner',
            '-loglevel', 'error',
            # 入力
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{self.width}x{self.height}',
            '-r', str(self.fps),
            '-i', 'pipe:0',
            # 出力ピクセルフォーマット
            '-pix_fmt', 'yuv420p',
            # エンコード設定
            *encoder_args,
            # 出力: raw H.264 (Annex B形式)
            '-f', 'h264',
            'pipe:1'
        ]
        
        # コマンド短縮版を出力（デバッグ用）
        print(f"[H264] エンコーダー起動: {self.encoder_type} @ {self.width}x{self.height} {self.fps}fps")
        
        try:
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            self.is_running = True
            
            # 出力読み取りスレッド
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()
            
            # エラー読み取りスレッド
            threading.Thread(target=self._read_errors, daemon=True).start()
            
            print(f"[H264] ✅ エンコーダー開始: {self.encoder_type}")
            return True
            
        except Exception as e:
            print(f"[H264] ❌ エンコーダー開始失敗: {e}")
            return False
    
    def _read_output(self):
        """FFmpeg出力を即座に読み取る"""
        try:
            while self.is_running and self.process:
                chunk = self.process.stdout.read(65536)  # より大きいチャンク
                if chunk:
                    with self._lock:
                        self._output_buffer.extend(chunk)
                elif self.process.poll() is not None:
                    break
        except:
            pass
    
    def _read_errors(self):
        """FFmpegエラーを読み取る"""
        try:
            while self.is_running and self.process:
                line = self.process.stderr.readline()
                if line:
                    print(f"[H264/FFmpeg] {line.decode('utf-8', errors='ignore').strip()}")
                elif self.process.poll() is not None:
                    break
        except:
            pass
    
    def encode_frame(self, frame: np.ndarray) -> Optional[bytes]:
        """フレームをエンコード"""
        if not self.is_running or not self.process:
            return None
        
        if self.process.poll() is not None:
            self.is_running = False
            return None
        
        try:
            h, w = frame.shape[:2]
            if w != self.width or h != self.height:
                frame = cv2.resize(frame, (self.width, self.height))
            
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame)
            
            self.process.stdin.write(frame.tobytes())
            self.process.stdin.flush()
            
            # 出力を取得
            with self._lock:
                if len(self._output_buffer) > 0:
                    result = bytes(self._output_buffer)
                    self._output_buffer.clear()
                    return result
            
            return None
            
        except Exception as e:
            print(f"[H264] エンコードエラー: {e}")
            self.is_running = False
            return None
    
    def stop(self):
        """エンコーダーを停止"""
        self.is_running = False
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass
            self.process = None
        print("[H264] ⏹️ 停止")


class WindowCapture:
    """ウィンドウキャプチャ（PrintWindow API）"""
    
    def __init__(self):
        if not HAS_WIN32:
            raise RuntimeError("pywin32が必要です")
        self.PW_RENDERFULLCONTENT = 2
    
    def capture(self, hwnd: int) -> Optional[np.ndarray]:
        if not win32gui.IsWindow(hwnd):
            return None
        
        hwndDC = None
        mfcDC = None
        saveDC = None
        saveBitMap = None
        
        try:
            rect = win32gui.GetWindowRect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            
            if w <= 0 or h <= 0:
                return None
            
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
            saveDC.SelectObject(saveBitMap)
            
            result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), self.PW_RENDERFULLCONTENT)
            if result == 0:
                saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)
            
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            
            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img = img.reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
            return img
            
        except:
            return None
        finally:
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
    """画面キャプチャエンジン v5.1"""
    
    def __init__(self,
                 target_fps: int = 30,
                 jpeg_quality: int = 85,
                 resolution_limit: str = "fullhd",
                 use_h264: bool = True,
                 h264_bitrate: str = "6M",
                 nvenc_available: dict = None,
                 **kwargs):
        
        self.target_fps = target_fps
        self.jpeg_quality = jpeg_quality
        self.use_h264 = use_h264
        self.h264_bitrate = h264_bitrate
        self.nvenc_available = nvenc_available or {'h264_nvenc': True}  # デフォルトでNVENC有効
        
        # 解像度上限
        limit_map = {
            'hd': ResolutionLimit.HD,
            'fullhd': ResolutionLimit.FULL_HD,
            'qhd': ResolutionLimit.QHD,
            '4k': ResolutionLimit.UHD_4K,
            'native': ResolutionLimit.NATIVE,
        }
        self.resolution_limit = limit_map.get(resolution_limit.lower(), ResolutionLimit.FULL_HD)
        self.max_width, self.max_height = RESOLUTION_LIMITS[self.resolution_limit]
        
        # 状態
        self.is_running = False
        self.capture_thread: Optional[threading.Thread] = None
        self.frame_callback: Optional[Callable] = None
        
        # 統計
        self.stats = FrameStats()
        self.stats_lock = threading.Lock()
        
        # キャプチャ設定
        self.capture_type = 'monitor'
        self.monitor_id = 1
        self.window_handle = None
        
        # エンコーダー
        self._window_capture: Optional[WindowCapture] = None
        self._h264_encoder: Optional[H264Encoder] = None
        self._using_h264 = False
    
    def start(self,
              capture_type: str = 'monitor',
              monitor_id: int = 1,
              window_handle: int = None,
              frame_callback: Callable = None) -> bool:
        
        if self.is_running:
            self.stop()
        
        self.capture_type = capture_type
        self.monitor_id = monitor_id
        self.window_handle = window_handle
        self.frame_callback = frame_callback
        
        if capture_type == 'window' and window_handle:
            if not HAS_WIN32:
                return False
            self._window_capture = WindowCapture()
        
        self._using_h264 = self.use_h264
        self._h264_encoder = None
        
        self.is_running = True
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()
        
        print(f"[Capture] ✅ 開始 ({capture_type}, fps={self.target_fps}, H.264={self.use_h264})")
        return True
    
    def stop(self):
        self.is_running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=3)
        if self._h264_encoder:
            self._h264_encoder.stop()
            self._h264_encoder = None
        self._window_capture = None
        print("[Capture] ⏹️ 停止")
    
    def _capture_loop(self):
        sct = mss.mss() if self.capture_type == 'monitor' else None
        frame_interval = 1.0 / self.target_fps
        
        frame_count = 0
        dropped = 0
        last_report = time.time()
        report_frame_count = 0
        encoder_init = False
        
        while self.is_running:
            loop_start = time.perf_counter()
            
            try:
                # キャプチャ
                t1 = time.perf_counter()
                if self.capture_type == 'window' and self._window_capture:
                    raw_img = self._window_capture.capture(self.window_handle)
                else:
                    raw_img = self._grab_monitor(sct)
                
                if raw_img is None:
                    time.sleep(0.05)
                    continue
                
                capture_ms = (time.perf_counter() - t1) * 1000
                
                # リサイズ
                img = self._resize_to_limit(raw_img)
                h, w = img.shape[:2]
                
                # エンコード
                t2 = time.perf_counter()
                img_bytes = None
                codec = 'jpeg'
                encoder = 'jpeg'
                
                # H.264エンコーダー初期化
                if self._using_h264 and not encoder_init:
                    self._h264_encoder = H264Encoder(w, h, self.target_fps, self.h264_bitrate)
                    if self._h264_encoder.start(nvenc_available=self.nvenc_available):
                        encoder_init = True
                        encoder = self._h264_encoder.encoder_type
                    else:
                        self._using_h264 = False
                        self._h264_encoder = None
                
                # H.264エンコード（必須）
                if self._using_h264 and self._h264_encoder and self._h264_encoder.is_running:
                    encoded = self._h264_encoder.encode_frame(img)
                    if encoded and len(encoded) > 0:
                        img_bytes = encoded
                        codec = 'h264'
                        encoder = self._h264_encoder.encoder_type
                    else:
                        # H.264エンコード失敗時は再試行
                        continue
                else:
                    # H.264が有効でない場合はスキップ
                    continue
                
                encode_ms = (time.perf_counter() - t2) * 1000
                total_ms = capture_ms + encode_ms
                
                # フレームドロップ判定
                if total_ms > frame_interval * 1000 * 2:
                    dropped += 1
                
                # コールバック
                if self.frame_callback and img_bytes:
                    frame_data = {
                        'image': base64.b64encode(img_bytes).decode('utf-8'),
                        'width': w,
                        'height': h,
                        'size': len(img_bytes),
                        'timestamp': time.time(),
                        'codec': codec,
                        'encoder': encoder,
                    }
                    try:
                        self.frame_callback(frame_data)
                        frame_count += 1
                    except:
                        pass
                
                # 統計（時間ベースの正確なFPS計算）
                now = time.time()
                report_frame_count += 1
                
                if now - last_report >= 3:
                    elapsed_report = now - last_report
                    actual_fps = report_frame_count / elapsed_report if elapsed_report > 0 else 0
                    report_frame_count = 0
                    
                    with self.stats_lock:
                        self.stats.fps = actual_fps
                        self.stats.capture_time_ms = capture_ms
                        self.stats.encode_time_ms = encode_ms
                        self.stats.total_time_ms = total_ms
                        self.stats.frame_size_kb = len(img_bytes) / 1024 if img_bytes else 0
                        self.stats.dropped_frames = dropped
                        self.stats.resolution = f"{w}x{h}"
                        self.stats.encoder_type = encoder
                    
                    print(f"[Capture] 📊 FPS: {actual_fps:.1f}, {w}x{h}, "
                          f"{len(img_bytes)/1024:.0f}KB, {encoder}"
                          f"{f', drop:{dropped}' if dropped > 0 else ''}")
                    last_report = now
                
                # フレーム間隔調整（最小待機）
                elapsed = time.perf_counter() - loop_start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(max(sleep_time, 0.0001))
                    
            except Exception as e:
                print(f"[Capture] エラー: {e}")
                time.sleep(0.1)
        
        if sct:
            sct.close()
    
    def _grab_monitor(self, sct) -> Optional[np.ndarray]:
        try:
            monitors = sct.monitors
            if self.monitor_id >= len(monitors):
                self.monitor_id = 1
            monitor = monitors[self.monitor_id]
            screenshot = sct.grab(monitor)
            img = np.array(screenshot, dtype=np.uint8)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except:
            return None
    
    def _resize_to_limit(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        if w <= self.max_width and h <= self.max_height:
            return img
        scale = min(self.max_width / w, self.max_height / h)
        new_w, new_h = int(w * scale), int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    
    def get_stats(self) -> FrameStats:
        with self.stats_lock:
            return FrameStats(
                capture_time_ms=self.stats.capture_time_ms,
                encode_time_ms=self.stats.encode_time_ms,
                total_time_ms=self.stats.total_time_ms,
                frame_size_kb=self.stats.frame_size_kb,
                fps=self.stats.fps,
                dropped_frames=self.stats.dropped_frames,
                resolution=self.stats.resolution,
                encoder_type=self.stats.encoder_type,
            )
    
    def update_settings(self, fps=None, quality=None, resolution_limit=None, **kwargs):
        if fps:
            self.target_fps = fps
        if quality:
            self.jpeg_quality = quality


# ユーティリティ

def get_ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except:
        return 'ffmpeg'


# エイリアス（互換性）
HighPerformanceCapture = ScreenCapture
QualityController = type('QualityController', (), {'__init__': lambda self, *a, **k: None})
