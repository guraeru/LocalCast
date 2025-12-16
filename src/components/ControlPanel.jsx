import { Play, Square, Users, Activity, MessageSquare, Monitor, Maximize, Volume2, VolumeX, Cpu } from 'lucide-react'
import './ControlPanel.css'

function ControlPanel({ 
  isConnected, 
  isSharing, 
  isMySharing,
  isHost,
  onStartSharing, 
  onStopSharing, 
  clientCount, 
  fps, 
  messages, 
  preset,
  onChangePreset,
  frameInfo,
  selectedSource,
  onToggleFullscreen,
  isAudioEnabled,
  onToggleAudio,
  audioAvailable,
  codec,
  encoder
}) {
  // 品質プリセット（サーバーの設定と同期）
  const qualityOptions = [
    { id: 'hd60', label: 'HD 60fps', desc: 'Full HD / 低負荷' },
    { id: '4k30', label: '4K 30fps', desc: '高解像度 / 安定' },
  ]

  return (
    <div className="control-panel">
      {/* 画面共有ボタン - ホストのみ表示 */}
      <div className="control-section">
        <h3>📹 画面共有</h3>
        {isHost ? (
          <>
            <div className="button-group">
              <button
                className="btn btn-primary"
                onClick={onStartSharing}
                disabled={!isConnected}
              >
                <Play size={18} />
                <span>{isSharing && !isMySharing ? '共有を引き継ぐ' : '共有を開始'}</span>
              </button>
              <button
                className="btn btn-danger"
                onClick={onStopSharing}
                disabled={!isConnected || !isMySharing}
              >
                <Square size={18} />
                <span>共有を停止</span>
              </button>
            </div>
            
            {selectedSource && isMySharing && (
              <div className="current-source">
                <Monitor size={14} />
                <span>{selectedSource.title}</span>
              </div>
            )}
            
            {isSharing && !isMySharing && (
              <div className="sharing-info">
                <span>他のユーザーが画面共有中</span>
              </div>
            )}
          </>
        ) : (
          <div className="client-mode-info">
            <span className="client-mode-label">👀 視聴モード</span>
            {isSharing ? (
              <span className="client-mode-status">ホストの画面を視聴中</span>
            ) : (
              <span className="client-mode-status">画面共有待機中...</span>
            )}
          </div>
        )}
      </div>

      {/* 品質選択 - ホストのみ、共有中は変更不可 */}
      <div className="control-section">
        <h3>🎬 品質</h3>
        <div className="quality-options">
          {qualityOptions.map(opt => (
            <button
              key={opt.id}
              className={`quality-btn ${preset === opt.id ? 'active' : ''}`}
              onClick={() => onChangePreset(opt.id)}
              disabled={!isConnected || isSharing || !isHost}
            >
              <span className="quality-label">{opt.label}</span>
              <span className="quality-desc">{opt.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* フルスクリーン */}
      <div className="control-section">
        <button
          className="btn btn-fullscreen"
          onClick={onToggleFullscreen}
          disabled={!isSharing}
        >
          <Maximize size={18} />
          <span>フルスクリーン</span>
        </button>
      </div>

      {/* 音声共有 */}
      <div className="control-section">
        <h3>🔊 音声</h3>
        <button
          className={`btn ${isAudioEnabled ? 'btn-audio-on' : 'btn-audio-off'}`}
          onClick={onToggleAudio}
          disabled={!isConnected || !audioAvailable}
          title={!audioAvailable ? '音声共有は利用できません' : ''}
        >
          {isAudioEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
          <span>{isAudioEnabled ? '音声 ON' : '音声 OFF'}</span>
        </button>
        {!audioAvailable && (
          <div className="audio-unavailable">
            サーバーで音声共有が無効です
          </div>
        )}
      </div>

      {/* ステータス */}
      <div className="control-section">
        <h3>📊 ステータス</h3>
        <div className="stats-grid">
          <div className="stat-item">
            <span className="stat-label"><Users size={12} /> 接続数</span>
            <span className="stat-value">{clientCount}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label"><Activity size={12} /> FPS</span>
            <span className="stat-value">{fps}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">解像度</span>
            <span className="stat-value">{frameInfo.width}x{frameInfo.height}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">サイズ</span>
            <span className="stat-value">{(frameInfo.size / 1024).toFixed(0)}KB</span>
          </div>
          <div className="stat-item">
            <span className="stat-label"><Cpu size={12} /> コーデック</span>
            <span className={`stat-value ${codec === 'h264' ? 'codec-h264' : ''}`}>
              {codec === 'h264' ? 'H.264' : 'JPEG'}
            </span>
          </div>
          {encoder && (
            <div className="stat-item">
              <span className="stat-label">エンコーダー</span>
              <span className={`stat-value ${encoder?.includes('nvenc') ? 'encoder-nvenc' : ''}`}>
                {encoder?.includes('nvenc') ? 'NVENC' : encoder || '-'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ログ */}
      <div className="control-section">
        <h3><MessageSquare size={14} /> ログ</h3>
        <div className="message-box">
          {messages.length === 0 ? (
            <div className="no-messages">-</div>
          ) : (
            messages.slice(-5).map((msg, idx) => (
              <div key={idx} className={`message-item ${msg.type}`}>
                <span className="message-text">{msg.text}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

export default ControlPanel
