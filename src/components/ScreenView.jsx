import { useRef, useEffect, useCallback, memo } from 'react'
import { Monitor, Loader2, Activity, X } from 'lucide-react'
import './ScreenView.css'

// 高速Canvas描画コンポーネント
const ScreenView = memo(function ScreenView({ 
  currentFrame, 
  isSharing, 
  isConnected, 
  fps, 
  frameInfo, 
  isFullscreen,
  onToggleFullscreen,
  selectedSource
}) {
  const canvasRef = useRef(null)
  const frameRequestRef = useRef(null)

  // 画像を非同期でデコードしてCanvasに描画
  const renderFrame = useCallback((frameData) => {
    if (!canvasRef.current || !frameData) return

    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d', { 
      alpha: false,
      desynchronized: true  // 低レイテンシモード
    })
    
    // テキストを鮮明に表示するための設定
    ctx.imageSmoothingEnabled = false

    // 毎回新しいImageオブジェクトを作成（確実に描画するため）
    const img = new Image()
    img.onload = function() {
      // Canvas サイズを画像に合わせる
      if (canvas.width !== this.width || canvas.height !== this.height) {
        canvas.width = this.width
        canvas.height = this.height
      }
      // 描画
      ctx.drawImage(this, 0, 0)
    }
    img.src = frameData
  }, [])

  // フレーム更新時にrequestAnimationFrameで描画
  useEffect(() => {
    if (currentFrame) {
      // 次のフレームで描画
      frameRequestRef.current = requestAnimationFrame(() => {
        renderFrame(currentFrame)
      })
    }

    return () => {
      if (frameRequestRef.current) {
        cancelAnimationFrame(frameRequestRef.current)
      }
    }
  }, [currentFrame, renderFrame])

  // 共有状態が変わった時にCanvasをクリア
  useEffect(() => {
    if (!isSharing) {
      // Canvasをクリア
      if (canvasRef.current) {
        const ctx = canvasRef.current.getContext('2d')
        ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height)
      }
    }
  }, [isSharing])

  // クリーンアップ
  useEffect(() => {
    return () => {
      if (frameRequestRef.current) {
        cancelAnimationFrame(frameRequestRef.current)
      }
    }
  }, [])

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
          <canvas 
            ref={canvasRef}
            className={isFullscreen ? 'fullscreen-canvas' : 'normal-canvas'}
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
              <div className="size-indicator">
                {(frameInfo.size / 1024).toFixed(0)} KB
              </div>
            )}
          </div>

          {/* フルスクリーン終了ボタン */}
          {isFullscreen && (
            <button className="exit-fullscreen-btn" onClick={onToggleFullscreen}>
              <X size={24} />
              <span>ESCで終了</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
})

export default ScreenView
