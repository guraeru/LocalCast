import { useRef, useEffect, memo, useState } from 'react'
import { Monitor, Loader2, Activity, X, Volume2 } from 'lucide-react'
import JMuxer from 'jmuxer'
import './ScreenView.css'

// H.264画面表示コンポーネント
const ScreenView = memo(function ScreenView({ 
  currentFrame, 
  isSharing, 
  isConnected, 
  fps, 
  frameInfo, 
  isFullscreen,
  onToggleFullscreen,
  selectedSource,
  audioUnlocked,
  onUnlockAudio,
  currentSharerId,
  clientId
}) {
  const videoRef = useRef(null)
  const jmuxerRef = useRef(null)
  const [isH264Ready, setIsH264Ready] = useState(false)
  const frameCountRef = useRef(0)
  
  const isSharer = currentSharerId && currentSharerId === clientId

  // jmuxer初期化（フレーム受信時に遅延初期化）
  useEffect(() => {
    // 共有中でフレームが来たらjmuxerを初期化
    if (isSharing && currentFrame && videoRef.current && !jmuxerRef.current) {
      console.log('🎬 jmuxer初期化開始')
      try {
        jmuxerRef.current = new JMuxer({
          node: videoRef.current,
          mode: 'video',
          flushingTime: 0,
          fps: 60,
          debug: false,
          onReady: () => {
            console.log('✅ jmuxer準備完了')
            setIsH264Ready(true)
          },
          onError: (e) => {
            console.error('❌ jmuxer エラー:', e)
          }
        })
        setIsH264Ready(true)  // 即座に準備完了とする
      } catch (e) {
        console.error('jmuxer初期化エラー:', e)
      }
    }
  }, [isSharing, currentFrame])

  // 共有停止時にクリーンアップ
  useEffect(() => {
    if (!isSharing) {
      if (jmuxerRef.current) {
        console.log('🧹 jmuxerクリーンアップ')
        try {
          jmuxerRef.current.destroy()
        } catch (e) {}
        jmuxerRef.current = null
      }
      setIsH264Ready(false)
      frameCountRef.current = 0
    }
  }, [isSharing])

  // フレーム描画（H.264）
  useEffect(() => {
    if (!currentFrame || !currentFrame.image) return
    if (!jmuxerRef.current) return
    
    try {
      const binaryString = atob(currentFrame.image)
      const bytes = new Uint8Array(binaryString.length)
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }
      jmuxerRef.current.feed({ video: bytes })
      
      // デバッグ: 最初の数フレームだけログ
      frameCountRef.current++
      if (frameCountRef.current <= 3) {
        console.log(`📹 フレーム ${frameCountRef.current}: ${bytes.length} bytes`)
      }
    } catch (e) {
      console.error('H.264フィードエラー:', e)
    }
  }, [currentFrame])

  return (
    <div className={`screen-area ${isFullscreen ? 'fullscreen-mode' : ''}`}>
      {!isConnected && (
        <div className="status-message">
          <Loader2 size={48} className="icon-spin" />
          <p>サーバーに接続中...</p>
        </div>
      )}

      {isConnected && !isSharing && (
        <div className="status-message">
          <Monitor size={48} className="icon-pulse" />
          <p>画面共有を開始してください</p>
          <small>右側のパネルから「共有を開始」をクリック</small>
        </div>
      )}

      {isSharing && !currentFrame && (
        <div className="status-message">
          <Loader2 size={48} className="icon-spin" />
          <p>画面データを受信中...</p>
        </div>
      )}

      {currentFrame && (
        <div className="screen-frame">
          {/* H.264 Video */}
          <video 
            ref={videoRef}
            className={`${isFullscreen ? 'fullscreen-canvas' : 'normal-canvas'}`}
            autoPlay
            muted
            playsInline
          />
          
          {/* 情報オーバーレイ */}
          <div className={`info-overlay ${isFullscreen ? 'fullscreen-overlay' : ''}`}>
            <div className="fps-indicator">
              <Activity size={14} />
              <span>{fps} FPS</span>
            </div>
            {!isFullscreen && selectedSource && (
              <div className="source-indicator">
                <Monitor size={14} />
                <span>{selectedSource.title?.substring(0, 30)}</span>
              </div>
            )}
            <div className="resolution-indicator">
              {frameInfo.width}x{frameInfo.height}
            </div>
            {!isFullscreen && (
              <>
                <div className="size-indicator">
                  {(frameInfo.size / 1024).toFixed(0)} KB
                </div>
                <div className="codec-indicator h264">
                  H.264
                </div>
              </>
            )}
          </div>

          {/* フルスクリーン終了ボタン */}
          {isFullscreen && (
            <button className="exit-fullscreen-btn" onClick={onToggleFullscreen}>
              <X size={24} />
              <span>ESCで終了</span>
            </button>
          )}

          {/* 音声有効化オーバーレイ */}
          {!audioUnlocked && !isSharer && (
            <div className="audio-unlock-overlay" onClick={onUnlockAudio}>
              <div className="audio-unlock-content">
                <Volume2 size={48} />
                <p>クリックして音声を有効化</p>
                <small>ブラウザのポリシーにより、操作が必要です</small>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
})

export default ScreenView
