import { Wifi, WifiOff, Users } from 'lucide-react'
import './Header.css'

function Header({ isConnected, clientCount, clientId }) {
  return (
    <header className="header">
      <div className="header-content">
        <div className="header-left">
          <h1 className="header-title">🖥️ ローカルネット画面共有</h1>
          <p className="header-subtitle">リアルタイム画面共有アプリケーション</p>
        </div>
        <div className="header-right">
          <div className={`connection-badge ${isConnected ? 'connected' : 'disconnected'}`}>
            {isConnected ? (
              <>
                <Wifi size={16} />
                <span>接続中</span>
              </>
            ) : (
              <>
                <WifiOff size={16} />
                <span>未接続</span>
              </>
            )}
          </div>
          <div className="client-badge">
            <Users size={16} />
            <span>{clientCount} 人</span>
          </div>
        </div>
      </div>
      {clientId && (
        <div className="client-id">
          <span>Client ID: {clientId.substring(0, 8)}...</span>
        </div>
      )}
    </header>
  )
}

export default Header
