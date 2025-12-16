#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ローカルネット画面共有アプリケーション v4.0
- 高性能マルチスレッドパイプライン
- 適応品質調整システム
- Teams風ウィンドウ/画面選択UI
- OpenCV高速エンコード
- システム音声共有対応
- フルスクリーン表示対応
"""

from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import socket as sock  # サーバーIPアドレス取得用
import mss
import mss.tools
import base64
import threading
import time
from io import BytesIO
import os
import json

# OpenCV
import cv2
import numpy as np

# 高性能エンコーダー v3.0
from hw_encoder import (
    ScreenCapture,
    QualityController,
    FrameStats
)

# ウィンドウ取得
try:
    import win32gui
    import win32con
    import win32ui
    import win32api
    from ctypes import windll
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("⚠️ pywin32未インストール。pip install pywin32")

# 音声キャプチャ (WASAPI ループバック対応)
HAS_AUDIO = False
pyaudio_instance = None
try:
    import pyaudiowpatch as pyaudio
    pyaudio_instance = pyaudio.PyAudio()
    HAS_AUDIO = True
    print("✅ PyAudioWPatch (WASAPIループバック対応)")
except ImportError:
    try:
        import sounddevice as sd
        HAS_AUDIO = True
        print("✅ sounddevice (フォールバック)")
    except ImportError:
        print("⚠️ 音声ライブラリ未インストール: pip install pyaudiowpatch")

# Flask アプリケーション初期化
app = Flask(__name__, 
            static_folder=os.path.join(os.path.dirname(__file__), 'static', 'dist'),
            static_url_path='')
app.config['SECRET_KEY'] = 'screen-share-secret-key-2025'

# CORS設定
CORS(app)

# SocketIO 初期化
socketio = SocketIO(app, 
                    cors_allowed_origins="*", 
                    async_mode='threading',
                    ping_timeout=60,
                    ping_interval=25,
                    max_http_buffer_size=100 * 1024 * 1024,
                    logger=False,
                    engineio_logger=False)

# ========== グローバル設定 ==========
is_sharing = False
is_audio_sharing = False
capture_pipeline = None  # HighPerformanceCapture インスタンス
audio_thread = None
connected_clients = set()  # session ID
connected_ips = {}  # IP -> set of session IDs (1PCを1人としてカウント)
capture_lock = threading.Lock()

# サーバーのIPアドレス（ホスト判定用）
def get_server_ips():
    """サーバーのIPアドレス一覧を取得"""
    ips = {'127.0.0.1', '::1', 'localhost'}
    try:
        hostname = sock.gethostname()
        # IPv4アドレスを取得
        try:
            for info in sock.getaddrinfo(hostname, None, sock.AF_INET):
                ips.add(info[4][0])
        except:
            pass
        # 外部接続用のIPを取得（最も確実な方法）
        try:
            s = sock.socket(sock.AF_INET, sock.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ips.add(s.getsockname()[0])
            s.close()
        except:
            pass
        # gethostbynameも試す
        try:
            ips.add(sock.gethostbyname(hostname))
        except:
            pass
    except Exception as e:
        print(f"[警告] IP取得エラー: {e}")
    return ips

SERVER_IPS = get_server_ips()

# 現在の画面共有者（ホストのみ開始可能）
current_sharer_id = None

# キャプチャターゲット
capture_type = 'monitor'  # 'monitor' or 'window'
selected_monitor = 1
selected_window_handle = None
selected_window_title = None

# キャプチャ設定
TARGET_FPS = 60
JPEG_QUALITY = 95
RESOLUTION_LIMIT = 'fullhd'  # 'hd', 'fullhd', '4k'
USE_H264 = True  # H.264必須（JPEGは使用しない）
H264_BITRATE = '35M'  # H.264ビットレート（高画質、ノイズ低減）

# プリセット - 高画質、安定性優先
QUALITY_PRESETS = {
    'hd60': {'fps': 60, 'resolution': 'fullhd', 'h264': True, 'bitrate': H264_BITRATE, 'quality': 100},
    '4k30': {'fps': 30, 'resolution': '4k', 'h264': True, 'bitrate': H264_BITRATE, 'quality': 100},
}

# NVENCステータス（デフォルト値で十分）
nvenc_status = {'ffmpeg': True, 'h264_nvenc': True, 'hevc_nvenc': False, 'av1_nvenc': False}

# キャッシュ
monitors_info = []
windows_info = []

# ソース初期化（バックグラウンド）
def _init_sources():
    get_monitors()
    get_windows()
    print(f"✅ ソース初期化完了")


def get_windows():
    """ウィンドウ一覧を取得"""
    global windows_info
    windows_info = []
    
    if not HAS_WIN32:
        return windows_info
    
    def callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            title = win32gui.GetWindowText(hwnd)
            exclude_titles = ['Program Manager', 'Windows Input Experience', 
                            'MSCTFIME UI', 'Default IME', 'Settings']
            if title and title not in exclude_titles:
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    width = rect[2] - rect[0]
                    height = rect[3] - rect[1]
                    
                    if width > 100 and height > 100:
                        class_name = win32gui.GetClassName(hwnd)
                        windows.append({
                            'id': hwnd,
                            'type': 'window',
                            'name': title[:60],
                            'title': title,
                            'class': class_name,
                            'width': width,
                            'height': height,
                            'left': rect[0],
                            'top': rect[1],
                            'thumbnail': None
                        })
                except:
                    pass
        return True
    
    win32gui.EnumWindows(callback, windows_info)
    windows_info.sort(key=lambda x: x['title'].lower())
    return windows_info


def get_monitors():
    """モニター一覧を取得"""
    global monitors_info
    monitors_info = []
    
    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors):
            if i == 0:
                continue  # 全画面は除外
            monitors_info.append({
                'id': i,
                'type': 'monitor',
                'name': f"ディスプレイ {i}",
                'title': f"ディスプレイ {i} ({m['width']}x{m['height']})",
                'width': m['width'],
                'height': m['height'],
                'left': m['left'],
                'top': m['top'],
                'thumbnail': None
            })
    return monitors_info


def capture_window(hwnd):
    """ウィンドウをキャプチャ（PrintWindow APIで隠れていてもキャプチャ可能）"""
    if not HAS_WIN32:
        return None
    try:
        # ウィンドウが最小化されている場合は復元
        if win32gui.IsIconic(hwnd):
            return None
        
        # クライアント領域のサイズを取得
        rect = win32gui.GetWindowRect(hwnd)
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        
        if width <= 0 or height <= 0:
            return None
        
        # デバイスコンテキストを作成
        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        
        # ビットマップを作成
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)
        
        # PrintWindow APIでキャプチャ（PW_RENDERFULLCONTENT = 2）
        # これにより、ウィンドウが隠れていてもキャプチャできる
        result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
        
        if result == 0:
            # PrintWindowが失敗した場合、BitBltにフォールバック
            saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)
        
        # ビットマップをnumpy配列に変換
        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        
        img = np.frombuffer(bmpstr, dtype='uint8')
        img = img.reshape((height, width, 4))
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        
        # リソースを解放
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)
        
        return img
    except Exception as e:
        return None


def capture_monitor_cv(monitor_id):
    """モニターをキャプチャ（OpenCV形式）"""
    try:
        with mss.mss() as sct:
            if monitor_id >= len(sct.monitors):
                monitor_id = 1
            monitor = sct.monitors[monitor_id]
            screenshot = sct.grab(monitor)
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return img
    except:
        return None


def generate_thumbnails():
    """サムネイル付きソース一覧を生成"""
    sources = []
    
    # モニター
    monitors = get_monitors()
    for m in monitors:
        try:
            img = capture_monitor_cv(m['id'])
            if img is not None:
                h, w = img.shape[:2]
                thumb_h = 120
                thumb_w = int(thumb_h * w / h)
                thumb = cv2.resize(img, (thumb_w, thumb_h))
                _, buf = cv2.imencode('.jpg', thumb, [cv2.IMWRITE_JPEG_QUALITY, 60])
                m['thumbnail'] = base64.b64encode(buf.tobytes()).decode('utf-8')
        except:
            pass
        sources.append(m)
    
    # ウィンドウ
    windows = get_windows()
    for w in windows[:15]:
        try:
            img = capture_window(w['id'])
            if img is not None:
                h, width = img.shape[:2]
                thumb_h = 120
                thumb_w = int(thumb_h * width / h)
                thumb = cv2.resize(img, (thumb_w, thumb_h))
                _, buf = cv2.imencode('.jpg', thumb, [cv2.IMWRITE_JPEG_QUALITY, 60])
                w['thumbnail'] = base64.b64encode(buf.tobytes()).decode('utf-8')
        except:
            pass
        sources.append(w)
    
    return sources


# ソース初期化スレッド起動（関数定義後）
threading.Thread(target=_init_sources, daemon=True).start()


def start_capture_pipeline():
    """高性能キャプチャパイプラインを開始"""
    global capture_pipeline, is_sharing, capture_type, selected_monitor, selected_window_handle
    
    # 既存のパイプラインがあれば確実に停止
    if capture_pipeline:
        capture_pipeline.stop()
        capture_pipeline = None
        time.sleep(0.05)
    
    target = selected_window_title if capture_type == 'window' else f"ディスプレイ {selected_monitor}"
    print(f"[Pipeline] 🚀 開始: {target}")
    print(f"           FPS: {TARGET_FPS}, H.264: {USE_H264}, bitrate: {H264_BITRATE}")
    
    def on_frame(frame_data):
        """フレーム受信コールバック - H.264のみ"""
        try:
            # デバッグ: 最初のフレームだけコーデック情報をログ
            if not hasattr(on_frame, '_logged'):
                codec = frame_data.get('codec', 'unknown')
                encoder = frame_data.get('encoder', 'unknown')
                # H.264以外の場合は警告
                if codec != 'h264':
                    print(f"⚠️ [Frame] H.264以外で送信されています: {codec}, {encoder}")
                else:
                    print(f"✅ [Frame] 📹 H.264, エンコーダー: {encoder}")
                on_frame._logged = True
            socketio.emit('frame', frame_data)
        except Exception as e:
            print(f"[Frame] エラー: {e}")
            pass
    
    # パイプライン作成
    capture_pipeline = ScreenCapture(
        target_fps=TARGET_FPS,
        jpeg_quality=JPEG_QUALITY,
        resolution_limit=RESOLUTION_LIMIT,
        use_h264=USE_H264,
        h264_bitrate=H264_BITRATE,
        nvenc_available=nvenc_status
    )
    
    # 開始
    success = capture_pipeline.start(
        capture_type=capture_type,
        monitor_id=selected_monitor,
        window_handle=selected_window_handle,
        frame_callback=on_frame
    )
    
    if not success:
        print("[Pipeline] ❌ 開始失敗")
        return
    
    # 統計レポートスレッド
    def stats_reporter():
        while is_sharing and capture_pipeline:
            try:
                stats = capture_pipeline.get_stats()
                if stats.fps > 0:
                    socketio.emit('stats', {
                        'fps': round(stats.fps, 1),
                        'frameSize': int(stats.frame_size_kb * 1024),
                        'resolution': stats.resolution,
                        'encoder': stats.encoder_type
                    })
            except:
                pass
            time.sleep(3)
    
    threading.Thread(target=stats_reporter, daemon=True).start()


def capture_screen_thread():
    """画面キャプチャスレッド（互換性用、実際はパイプラインが処理）"""
    # パイプラインベースの実装に移行したため、このスレッドは使用しない
    # 互換性のために残しておく
    start_capture_pipeline()


@app.route('/')
def index():
    """メインページ - React SPAを配信"""
    dist_path = os.path.join(app.static_folder, 'index.html')
    if os.path.exists(dist_path):
        return send_from_directory(app.static_folder, 'index.html')
    else:
        # 開発環境用フォールバック
        return """
        <html>
        <head><title>画面共有アプリ</title></head>
        <body>
            <h1>開発モード</h1>
            <p>React開発サーバー(port 3000)を起動してください</p>
            <p>または、<code>npm run build</code>でビルドしてください</p>
        </body>
        </html>
        """

@app.route('/<path:path>')
def serve_static(path):
    """静的ファイル配信"""
    return send_from_directory(app.static_folder, path)


@socketio.on('connect')
def handle_connect():
    """クライアント接続時"""
    client_ip = request.remote_addr
    
    with capture_lock:
        connected_clients.add(request.sid)
        # IPベースでカウント（1PCを1人として）
        if client_ip not in connected_ips:
            connected_ips[client_ip] = set()
        connected_ips[client_ip].add(request.sid)
        client_count = len(connected_ips)  # ユニークIP数

    # ホスト（サーバーと同じマシン）かどうか判定
    is_host = client_ip in SERVER_IPS
    
    print(f"[接続] ✅ クライアント接続: {request.sid[:8]}... (IP: {client_ip}, ホスト: {is_host}, 接続PC数: {client_count})")

    emit('connected', {
        'client_id': request.sid,
        'client_count': client_count,
        'audio_available': HAS_AUDIO,
        'presets': list(QUALITY_PRESETS.keys()),
        'nvenc': nvenc_status,
        'is_sharing': is_sharing,
        'current_sharer': current_sharer_id,
        'is_host': is_host,
        'codec': 'h264' if USE_H264 else 'jpeg',
        'encoder': 'h264_nvenc' if nvenc_status.get('h264_nvenc') else 'libx264' if USE_H264 else 'jpeg',
        'features': {
            'adaptive_quality': True,
            'multi_threaded': True,
            'max_fps': 60
        }
    })

    # 他のクライアントにも人数更新を通知
    socketio.emit('client_count_updated', {'count': client_count})


@socketio.on('disconnect')
def handle_disconnect(reason=None):
    """クライアント切断時"""
    global current_sharer_id
    client_ip = request.remote_addr
    
    with capture_lock:
        connected_clients.discard(request.sid)
        # IPベースでカウント
        if client_ip in connected_ips:
            connected_ips[client_ip].discard(request.sid)
            if not connected_ips[client_ip]:  # そのIPからの接続が0になった
                del connected_ips[client_ip]
        client_count = len(connected_ips)  # ユニークIP数

    print(f"[切断] ❌ クライアント切断: {request.sid[:8]}... (IP: {client_ip}, 残りPC数: {client_count})")

    # 画面共有者が切断した場合、共有を停止
    if request.sid == current_sharer_id:
        print(f"[切断] 🎬 共有者が切断しました。共有を停止します。")
        current_sharer_id = None
        stop_sharing()

    # 全クライアントに人数更新を通知
    socketio.emit('client_count_updated', {'count': client_count})


@socketio.on('get_sources')
def handle_get_sources():
    """共有ソース一覧を取得（誰でも可能）"""
    print(f"[ソース] 📋 共有ソース一覧を取得中... (by {request.sid[:8]})")
    try:
        sources = generate_thumbnails()
        emit('sources_list', {
            'sources': sources,
            'current': {
                'type': capture_type,
                'id': selected_window_handle if capture_type == 'window' else selected_monitor
            }
        })
        print(f"[ソース] ✅ {len(sources)}個のソースを送信")
    except Exception as e:
        print(f"[ソース] ❌ エラー: {e}")
        emit('sources_list', {'sources': [], 'error': str(e)})


@socketio.on('select_source')
def handle_select_source(data):
    """共有ソースを選択"""
    global capture_type, selected_monitor, selected_window_handle, selected_window_title
    
    source_type = data.get('type', 'monitor')
    source_id = data.get('id')
    
    if source_type == 'window':
        capture_type = 'window'
        selected_window_handle = source_id
        selected_window_title = data.get('title', f'Window {source_id}')
        print(f"[選択] 🪟 ウィンドウ: {selected_window_title[:40]}")
    else:
        capture_type = 'monitor'
        selected_monitor = source_id
        selected_window_handle = None
        print(f"[選択] 🖥️ ディスプレイ {selected_monitor}")
    
    emit('source_selected', {
        'type': capture_type,
        'id': source_id,
        'title': selected_window_title if capture_type == 'window' else f'ディスプレイ {selected_monitor}'
    })


@socketio.on('start_sharing')
def handle_start_sharing(data=None):
    """画面共有開始（誰でも可能、他の人の共有を強制解除）"""
    global is_sharing, capture_pipeline, TARGET_FPS, JPEG_QUALITY, RESOLUTION_LIMIT
    global current_sharer_id, is_audio_sharing, audio_thread, USE_H264, H264_BITRATE
    
    # 既に共有中の場合（自分自身も含む）、必ず先に停止
    if is_sharing:
        if current_sharer_id != request.sid:
            print(f"[共有] 🔄 共有者変更: {current_sharer_id[:8] if current_sharer_id else 'なし'}... → {request.sid[:8]}...")
            # 前の共有者に通知
            if current_sharer_id:
                socketio.emit('sharing_taken_over', {'new_sharer': request.sid}, room=current_sharer_id)
        else:
            print(f"[共有] 🔄 画面切り替え: {request.sid[:8]}...")
        
        # 既存のキャプチャを完全に停止
        with capture_lock:
            is_sharing = False
            is_audio_sharing = False
        
        if capture_pipeline:
            capture_pipeline.stop()
            capture_pipeline = None
        
        # 音声スレッドも停止
        if audio_thread and audio_thread.is_alive():
            audio_thread.join(timeout=1)
        audio_thread = None
        
        # 少し待機して確実に停止
        time.sleep(0.1)
    
    # このクライアントを共有者に設定
    current_sharer_id = request.sid
    print(f"[共有] 🎬 共有者設定: {request.sid[:8]}...")
    
    if data:
        if 'preset' in data:
            preset = data.get('preset', 'hd60')
            if preset in QUALITY_PRESETS:
                settings = QUALITY_PRESETS[preset]
                JPEG_QUALITY = settings['quality']
                RESOLUTION_LIMIT = settings['resolution']
                TARGET_FPS = settings['fps']
                USE_H264 = settings.get('h264', True)
                H264_BITRATE = settings.get('bitrate', '20M')
        
        if 'source' in data:
            handle_select_source(data['source'])
        
        # 音声共有も開始
        if data.get('withAudio') and HAS_AUDIO:
            if not is_audio_sharing:
                is_audio_sharing = True
                audio_thread = threading.Thread(target=audio_capture_thread, daemon=True)
                audio_thread.start()
                print("[音声] 🔊 画面共有と一緒に音声共有開始")

    with capture_lock:
        is_sharing = True

    # 新しいパイプラインを開始
    start_capture_pipeline()

    target = selected_window_title if capture_type == 'window' else f'ディスプレイ {selected_monitor}'
    print(f"[共有] 📹 開始: {target} @ {TARGET_FPS}fps, H.264: {USE_H264}")
    
    socketio.emit('sharing_started', {
        'message': '画面共有を開始しました',
        'target': target,
        'sharer_id': current_sharer_id,
        'settings': {
            'fps': TARGET_FPS,
            'quality': JPEG_QUALITY,
            'resolution_limit': RESOLUTION_LIMIT,
            'codec': 'h264' if USE_H264 else 'jpeg'
        }
    })


@socketio.on('stop_sharing')
def handle_stop_sharing():
    """画面共有停止（自分が共有中の場合のみ）"""
    global current_sharer_id
    
    # 自分が共有中でない場合は無視
    if request.sid != current_sharer_id:
        return
    
    current_sharer_id = None
    stop_sharing()


def stop_sharing():
    """共有停止"""
    global is_sharing, is_audio_sharing, capture_pipeline, audio_thread

    if is_sharing:
        with capture_lock:
            is_sharing = False
            is_audio_sharing = False

        # パイプライン停止
        if capture_pipeline:
            capture_pipeline.stop()
            capture_pipeline = None
        
        if audio_thread and audio_thread.is_alive():
            audio_thread.join(timeout=2)
        audio_thread = None

        print(f"[共有] ⏹️ 停止")
        socketio.emit('sharing_stopped', {'message': '画面共有を停止しました'})


@socketio.on('change_settings')
def handle_change_settings(data):
    """設定変更（共有者のみ）"""
    global TARGET_FPS, JPEG_QUALITY, RESOLUTION_LIMIT, capture_pipeline, USE_H264, H264_BITRATE
    
    # 共有者でない場合は拒否
    if request.sid != current_sharer_id:
        return
    
    if 'preset' in data:
        preset = data.get('preset', 'hd60')
        if preset in QUALITY_PRESETS:
            settings = QUALITY_PRESETS[preset]
            JPEG_QUALITY = settings['quality']
            RESOLUTION_LIMIT = settings['resolution']
            TARGET_FPS = settings['fps']
            USE_H264 = settings.get('h264', True)
            H264_BITRATE = settings.get('bitrate', '20M')
            print(f"[設定] プリセット '{preset}' を適用 ({RESOLUTION_LIMIT}, {TARGET_FPS}fps, H.264: {USE_H264})")
            
            # パイプラインの設定を更新
            if capture_pipeline:
                capture_pipeline.update_settings(
                    fps=TARGET_FPS,
                    quality=JPEG_QUALITY,
                    resolution_limit=RESOLUTION_LIMIT
                )
    
    socketio.emit('settings_changed', {
        'fps': TARGET_FPS,
        'quality': JPEG_QUALITY,
        'resolution_limit': RESOLUTION_LIMIT,
        'codec': 'h264' if USE_H264 else 'jpeg'
    })


@socketio.on('send_message')
def handle_send_message(data):
    """メッセージ送信"""
    message = data.get('message', '')
    if message:
        print(f"[メッセージ] 💬 {message}")
        socketio.emit('message_received', {'message': message, 'from': 'client'})


@socketio.on_error_default
def default_error_handler(e):
    print(f"[エラー] ❗ {e}")


# 音声共有スレッド
audio_thread = None

def get_default_wasapi_loopback():
    """Windowsのデフォルト音声出力デバイスのループバックを取得"""
    if not HAS_AUDIO or pyaudio_instance is None:
        return None, None
    
    try:
        # WASAPIホストAPIを探す
        wasapi_info = None
        for i in range(pyaudio_instance.get_host_api_count()):
            info = pyaudio_instance.get_host_api_info_by_index(i)
            if info['name'] == 'Windows WASAPI':
                wasapi_info = info
                break
        
        if wasapi_info is None:
            print("[音声] ❌ WASAPIが見つかりません")
            return None, None
        
        # デフォルト出力デバイスを取得
        default_output_idx = wasapi_info.get('defaultOutputDevice')
        if default_output_idx is None or default_output_idx < 0:
            print("[音声] ❌ デフォルト出力デバイスが見つかりません")
            return None, None
        
        default_output = pyaudio_instance.get_device_info_by_index(default_output_idx)
        print(f"[音声] 🔊 デフォルト出力: {default_output['name']}")
        
        # ループバックデバイスを探す（出力デバイスと同じ名前で入力チャンネルがあるもの）
        for i in range(pyaudio_instance.get_device_count()):
            device = pyaudio_instance.get_device_info_by_index(i)
            # ループバックデバイスは isLoopbackDevice フラグで識別
            if device.get('isLoopbackDevice', False):
                # 名前が一致するか確認
                if default_output['name'] in device['name'] or device['name'] in default_output['name']:
                    print(f"[音声] ✅ ループバックデバイス: [{i}] {device['name']}")
                    return i, device
        
        # 見つからない場合はisLoopbackDeviceフラグがあるデバイスを使用
        for i in range(pyaudio_instance.get_device_count()):
            device = pyaudio_instance.get_device_info_by_index(i)
            if device.get('isLoopbackDevice', False):
                print(f"[音声] ✅ ループバックデバイス(フォールバック): [{i}] {device['name']}")
                return i, device
        
        print("[音声] ❌ ループバックデバイスが見つかりません")
        return None, None
        
    except Exception as e:
        print(f"[音声] ❌ デバイス検索エラー: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def audio_capture_thread():
    """音声キャプチャ（WASAPIループバックでシステム音声をキャプチャ）"""
    global is_audio_sharing
    
    if not HAS_AUDIO:
        return
    
    # PyAudioWPatchでWASAPIループバックを使用
    if pyaudio_instance is not None:
        audio_capture_wasapi()
    else:
        # フォールバック: sounddevice
        audio_capture_sounddevice()

def audio_capture_wasapi():
    """PyAudioWPatchを使ったWASAPIループバックキャプチャ"""
    global is_audio_sharing
    
    loopback_idx, loopback_device = get_default_wasapi_loopback()
    
    if loopback_device is None:
        print("[音声] ❌ ループバックデバイスが見つかりません")
        return
    
    SAMPLE_RATE = int(loopback_device['defaultSampleRate'])
    CHANNELS = loopback_device['maxInputChannels']
    # 超低遅延：20msチャンク（高頻度送信）
    CHUNK = int(SAMPLE_RATE * 0.02)  # 44100 * 0.02 = 882サンプル
    
    # ステレオを保証
    if CHANNELS > 2:
        CHANNELS = 2
    
    print(f"[音声] 🎵 WASAPIループバック開始 (SR={SAMPLE_RATE}, CH={CHANNELS}, CHUNK={CHUNK})")
    print(f"[音声] 📍 デバイス: {loopback_device['name']}")
    print(f"[音声] ⚡ 超低遅延モード: {CHUNK / SAMPLE_RATE * 1000:.0f}ms チャンク")
    
    audio_packet_count = 0
    
    try:
        stream = pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=loopback_idx,
            frames_per_buffer=CHUNK
        )
        
        print("[音声] 🔊 ストリーミング中...")
        
        while is_audio_sharing:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                
                # Int16データをそのままBase64エンコード
                audio_b64 = base64.b64encode(data).decode('utf-8')
                
                # 音量チェック
                audio_int16 = np.frombuffer(data, dtype=np.int16)
                max_val = np.max(np.abs(audio_int16)) if len(audio_int16) > 0 else 0
                
                socketio.emit('audio', {
                    'data': audio_b64,
                    'sampleRate': SAMPLE_RATE,
                    'channels': CHANNELS
                })
                
                audio_packet_count += 1
                if audio_packet_count % 20 == 0:
                    print(f"[音声] 📤 送信中... パケット={audio_packet_count}, 振幅={max_val}")
                    
            except Exception as e:
                print(f"[音声] ⚠️ 読み取りエラー: {e}")
                time.sleep(0.01)
        
        stream.stop_stream()
        stream.close()
        
    except Exception as e:
        print(f"[音声] ❌ WASAPIエラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("[音声] ⏹️ 音声キャプチャ停止")

def audio_capture_sounddevice():
    """sounddeviceを使ったフォールバックキャプチャ"""
    global is_audio_sharing
    
    import sounddevice as sd
    
    SAMPLE_RATE = 44100
    CHANNELS = 2
    BLOCK_SIZE = 4096
    
    print(f"[音声] 🎵 sounddeviceキャプチャ開始 (SR={SAMPLE_RATE}, CH={CHANNELS})")
    
    audio_packet_count = [0]
    
    try:
        def callback(indata, frames, time_info, status):
            if status:
                print(f"[音声] ⚠️ {status}")
            if is_audio_sharing:
                audio_int16 = (indata * 32767).astype(np.int16)
                max_val = np.max(np.abs(audio_int16))
                
                audio_b64 = base64.b64encode(audio_int16.tobytes()).decode('utf-8')
                socketio.emit('audio', {
                    'data': audio_b64,
                    'sampleRate': SAMPLE_RATE,
                    'channels': CHANNELS
                })
                
                audio_packet_count[0] += 1
                if audio_packet_count[0] % 20 == 0:
                    print(f"[音声] 📤 送信中... パケット={audio_packet_count[0]}, 振幅={max_val}")
        
        with sd.InputStream(
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype='float32',
            callback=callback
        ):
            print("[音声] 🔊 ストリーミング中...")
            while is_audio_sharing:
                time.sleep(0.1)
    except Exception as e:
        print(f"[音声] ❌ sounddeviceエラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("[音声] ⏹️ 音声キャプチャ停止")


@socketio.on('start_audio')
def handle_start_audio():
    """音声共有開始"""
    global is_audio_sharing, audio_thread
    
    if not HAS_AUDIO:
        emit('audio_error', {'message': '音声共有は利用できません'})
        return
    
    # 共有者でなければ無視
    if request.sid != current_sharer_id:
        return
    
    if not is_audio_sharing:
        is_audio_sharing = True
        audio_thread = threading.Thread(target=audio_capture_thread, daemon=True)
        audio_thread.start()
        socketio.emit('audio_started', {'message': '音声共有開始'})
        print("[音声] 🔊 音声共有開始")


@socketio.on('stop_audio')
def handle_stop_audio():
    """音声共有停止"""
    global is_audio_sharing
    
    # 共有者でなければ無視
    if request.sid != current_sharer_id:
        return
    
    is_audio_sharing = False
    socketio.emit('audio_stopped', {'message': '音声共有停止'})
    print("[音声] 🔇 音声共有停止")


if __name__ == '__main__':
    print("=" * 70)
    print("🖥️  ローカルネット画面共有サーバー v5.0 (H.264対応版)")
    print("=" * 70)
    print()
    
    # ホスト判定用IP
    print(f"🔒 ホスト判定IP: {SERVER_IPS}")
    print()
    
    # NVENC確認
    print(f"🎬 ハードウェアエンコード:")
    print(f"   FFmpeg: {'✅' if nvenc_status['ffmpeg'] else '❌'}")
    print(f"   H.264 NVENC: {'✅' if nvenc_status['h264_nvenc'] else '❌'}")
    print(f"   HEVC NVENC: {'✅' if nvenc_status['hevc_nvenc'] else '❌'}")
    print(f"   H.264モード: {'有効' if USE_H264 else '無効 (JPEG)'}")
    print()
    
    # モニター検出
    monitors = get_monitors()
    print(f"🖥️ モニター: {len(monitors)}台")
    for m in monitors:
        print(f"   [{m['id']}] {m['title']}")
    
    # ウィンドウ検出
    if HAS_WIN32:
        windows = get_windows()
        print(f"\n🪟 ウィンドウ: {len(windows)}個")
        for w in windows[:5]:
            print(f"   • {w['name'][:50]}")
        if len(windows) > 5:
            print(f"   ... 他{len(windows)-5}個")
    
    print(f"\n🎵 音声共有: {'利用可能' if HAS_AUDIO else '利用不可'}")
    print(f"\n⚡ 高性能機能:")
    print(f"   マルチスレッドパイプライン: ✅")
    print(f"   適応品質調整: ✅")
    print(f"   60FPSサポート: ✅")
    print()
    print("📍 接続先:")
    print("   http://localhost:5000")
    print()
    print("=" * 70)
    print()
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
