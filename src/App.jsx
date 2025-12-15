import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { io } from 'socket.io-client'
import Header from './components/Header'
import ScreenView from './components/ScreenView'
import ControlPanel from './components/ControlPanel'
import SourcePicker from './components/SourcePicker'
import './App.css'

function App() {
  const [socket, setSocket] = useState(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isSharing, setIsSharing] = useState(false)
  const [currentFrame, setCurrentFrame] = useState(null)
  const [clientCount, setClientCount] = useState(0)
  const [clientId, setClientId] = useState('')
  const [fps, setFps] = useState(0)
  const [messages, setMessages] = useState([])
  const [preset, setPreset] = useState('hd60')
  const [frameInfo, setFrameInfo] = useState({ width: 0, height: 0, size: 0 })
  const [isFullscreen, setIsFullscreen] = useState(false)
  
  // ソース選択
  const [showSourcePicker, setShowSourcePicker] = useState(false)
  const [sources, setSources] = useState([])
  const [selectedSource, setSelectedSource] = useState(null)
  const [isLoadingSources, setIsLoadingSources] = useState(false)
  
  // 現在の共有者ID
  const [currentSharerId, setCurrentSharerId] = useState(null)
  
  // ホストかどうか（サーバーと同じマシン）
  const [isHost, setIsHost] = useState(false)
  
  // 音声共有
  const [isAudioEnabled, setIsAudioEnabled] = useState(true)
  const [audioAvailable, setAudioAvailable] = useState(false)
  const [audioUnlocked, setAudioUnlocked] = useState(false)  // ユーザーが音声を有効化したか
  const audioContextRef = useRef(null)
  const nextPlayTimeRef = useRef(0)  // 次の再生開始時刻
  const audioBufferQueueRef = useRef([])  // バッファキュー
  const isAudioEnabledRef = useRef(true)  // クロージャ問題回避用
  const playAudioChunkRef = useRef(null)   // 関数ref
  const currentSharerIdRef = useRef(null)  // 共有者ID ref
  const clientIdRef = useRef('')           // 自分のID ref
  const audioInitializedRef = useRef(false)  // 初期バッファリング完了フラグ

  // FPS計算用 - useRefで高速化
  const fpsCounterRef = useRef({ count: 0, lastTime: Date.now() })
  const frameInfoRef = useRef({ width: 0, height: 0, size: 0 })
  
  const containerRef = useRef(null)

  // Socket.IO 接続
  useEffect(() => {
    // 現在のページのホストに接続（他のPCからも動作するように）
    const serverUrl = window.location.origin
    console.log('🔌 接続先:', serverUrl)
    
    const newSocket = io(serverUrl, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionAttempts: 10
    })

    newSocket.on('connect', () => {
      console.log('✅ サーバーに接続しました')
      setIsConnected(true)
    })

    newSocket.on('disconnect', () => {
      console.log('❌ サーバーから切断されました')
      setIsConnected(false)
      setIsSharing(false)
    })

    newSocket.on('connected', (data) => {
      setClientId(data.client_id)
      clientIdRef.current = data.client_id  // refも更新
      setClientCount(data.client_count)
      setCurrentSharerId(data.current_sharer)
      currentSharerIdRef.current = data.current_sharer  // refも更新
      setAudioAvailable(data.audio_available || false)
      setIsHost(data.is_host || false)
      if (data.is_sharing) {
        setIsSharing(true)
      }
      addMessage(data.is_host ? '接続しました (ホスト)' : '接続しました (クライアント)', 'info')
    })

    newSocket.on('client_count_updated', (data) => {
      setClientCount(data.count)
    })

    newSocket.on('sources_list', (data) => {
      setSources(data.sources || [])
      setIsLoadingSources(false)
    })

    newSocket.on('source_selected', (data) => {
      setSelectedSource(data)
      addMessage(`選択: ${data.title}`, 'info')
    })

    newSocket.on('frame', (data) => {
      // 直接Data URLを設定（最速）
      setCurrentFrame(`data:image/jpeg;base64,${data.image}`)
      
      // frameInfoはrefで管理し、UIには遅延更新
      frameInfoRef.current = {
        width: data.width || 0,
        height: data.height || 0,
        size: data.size || 0
      }
      
      // FPSカウント（毎秒1回だけUIを更新）
      const counter = fpsCounterRef.current
      counter.count++
      const now = Date.now()
      const elapsed = now - counter.lastTime
      
      if (elapsed >= 1000) {
        const currentFps = Math.round(counter.count * 1000 / elapsed)
        setFps(currentFps)
        setFrameInfo({ ...frameInfoRef.current })
        counter.count = 0
        counter.lastTime = now
      }
    })

    newSocket.on('stats', (data) => {
      // サーバーからのFPSも使用
      if (data.fps) setFps(data.fps)
    })

    newSocket.on('sharing_started', (data) => {
      setIsSharing(true)
      setShowSourcePicker(false)
      setCurrentSharerId(data.sharer_id)
      currentSharerIdRef.current = data.sharer_id  // refも更新
      setCurrentFrame(null)  // 前のフレームをクリア
      addMessage(`共有開始: ${data.target || ''}`, 'success')
    })

    newSocket.on('sharing_stopped', (data) => {
      setIsSharing(false)
      setCurrentFrame(null)
      setCurrentSharerId(null)
      currentSharerIdRef.current = null  // refもリセット
      addMessage('共有停止', 'warning')
    })
    
    newSocket.on('sharing_taken_over', (data) => {
      // 自分の共有が他の人に引き継がれた
      addMessage('他のユーザーが共有を開始しました', 'info')
    })
    
    newSocket.on('error', (data) => {
      addMessage(data.message, 'error')
    })

    newSocket.on('settings_changed', (data) => {
      addMessage(`設定変更: ${data.resolution_limit || ''} ${data.fps}fps`, 'info')
    })

    // 音声データ受信（配信者は再生しない - 自分のPCで既に聞こえている）
    newSocket.on('audio', (data) => {
      if (!isAudioEnabledRef.current) return
      // 自分が配信者なら再生しない（二重再生防止）
      if (currentSharerIdRef.current === clientIdRef.current) return
      playAudioChunkRef.current?.(data)
    })

    newSocket.on('audio_started', (data) => {
      console.log('🔊 サーバーから audio_started 受信')
      addMessage('音声共有開始', 'success')
    })

    newSocket.on('audio_stopped', (data) => {
      addMessage('音声共有停止', 'warning')
    })

    newSocket.on('audio_error', (data) => {
      addMessage(data.message, 'error')
    })

    setSocket(newSocket)

    return () => {
      newSocket.close()
    }
  }, [])

  const addMessage = (text, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString('ja-JP')
    setMessages(prev => [...prev, { text, type, timestamp }].slice(-50))
  }

  // 音声再生関数（超低遅延・高音質版）
  const playAudioChunk = useCallback((data) => {
    try {
      // AudioContextが未初期化またはロック解除されていない場合はスキップ
      if (!audioContextRef.current || audioContextRef.current.state !== 'running') {
        return
      }
      
      const ctx = audioContextRef.current
      
      // Base64デコード
      const binaryString = atob(data.data)
      const len = binaryString.length
      const bytes = new Uint8Array(len)
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }
      
      // Int16からFloat32に変換
      const int16 = new Int16Array(bytes.buffer)
      const float32 = new Float32Array(int16.length)
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0
      }
      
      // AudioBufferを作成
      const channels = data.channels || 2
      const sampleRate = data.sampleRate || 44100
      const frameCount = Math.floor(float32.length / channels)
      
      if (frameCount <= 0) {
        return
      }
      
      const audioBuffer = ctx.createBuffer(channels, frameCount, sampleRate)
      
      // チャンネルにデータをコピー
      for (let ch = 0; ch < channels; ch++) {
        const channelData = audioBuffer.getChannelData(ch)
        for (let i = 0; i < frameCount; i++) {
          channelData[i] = float32[i * channels + ch]
        }
      }
      
      // 超低遅延：最小バッファ（50ms）
      const BUFFER_TIME = 0.05
      const currentTime = ctx.currentTime
      
      // 次の再生時刻を計算
      let startTime = nextPlayTimeRef.current
      
      // 初回または再生が追いついた場合
      if (!audioInitializedRef.current || startTime < currentTime) {
        startTime = currentTime + BUFFER_TIME
        audioInitializedRef.current = true
      }
      
      // 遅延が溜まりすぎた場合はリセット（200ms以上）
      if (startTime > currentTime + 0.2) {
        startTime = currentTime + BUFFER_TIME
      }
      
      // 再生
      const source = ctx.createBufferSource()
      source.buffer = audioBuffer
      source.connect(ctx.destination)
      source.start(startTime)
      
      // 次の再生時刻を更新
      nextPlayTimeRef.current = startTime + audioBuffer.duration
      
    } catch (e) {
      console.error('音声再生エラー:', e)
    }
  }, [])

  // playAudioChunkをrefに格納
  useEffect(() => {
    playAudioChunkRef.current = playAudioChunk
  }, [playAudioChunk])

  // 音声をロック解除（ユーザーインタラクション時に呼び出す）
  const unlockAudio = useCallback(() => {
    console.log('🔓 音声ロック解除試行')
    
    try {
      // AudioContextを作成
      if (!audioContextRef.current) {
        audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 44100,
          latencyHint: 'interactive'
        })
        nextPlayTimeRef.current = 0
        audioBufferQueueRef.current = []
        audioInitializedRef.current = false
        console.log('🔊 AudioContext作成')
      }
      
      const ctx = audioContextRef.current
      
      // suspendedならresume
      if (ctx.state === 'suspended') {
        ctx.resume().then(() => {
          console.log('🔊 AudioContext再開成功 - 状態:', ctx.state)
          if (ctx.state === 'running') {
            setAudioUnlocked(true)
          }
        }).catch(e => {
          console.error('🔊 AudioContext再開失敗:', e)
        })
      } else if (ctx.state === 'running') {
        setAudioUnlocked(true)
        console.log('🔊 AudioContext既に実行中')
      }
    } catch (e) {
      console.error('AudioContextエラー:', e)
    }
  }, [])

  // 音声共有のトグル
  const toggleAudio = useCallback(() => {
    if (!socket || !isConnected) return
    
    if (isAudioEnabled) {
      // 音声を無効化
      setIsAudioEnabled(false)
      isAudioEnabledRef.current = false
      // 自分が共有者なら音声配信停止
      if (currentSharerId === clientId) {
        socket.emit('stop_audio')
      }
      // AudioContextをクリーンアップ
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      // 再生時刻とフラグをリセット
      nextPlayTimeRef.current = 0
      audioBufferQueueRef.current = []
      audioInitializedRef.current = false
    } else {
      // 音声を有効化
      setIsAudioEnabled(true)
      isAudioEnabledRef.current = true
      
      // AudioContextを事前に初期化（ユーザーインタラクション中に行う必要がある）
      if (!audioContextRef.current) {
        audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 44100
        })
        nextPlayTimeRef.current = 0
        audioInitializedRef.current = false
        console.log('🔊 AudioContext初期化')
      }
      if (audioContextRef.current.state === 'suspended') {
        audioContextRef.current.resume()
        console.log('🔊 AudioContext再開')
      }
      
      // 自分が共有者なら音声配信開始
      if (currentSharerId === clientId) {
        socket.emit('start_audio')
      }
      
      addMessage('音声を有効にしました', 'success')
    }
  }, [socket, isConnected, isAudioEnabled, currentSharerId, clientId])

  // ソース選択ダイアログを開く
  const openSourcePicker = useCallback(() => {
    setShowSourcePicker(true)
    setIsLoadingSources(true)
    if (socket && isConnected) {
      socket.emit('get_sources')
    }
  }, [socket, isConnected])

  // ソース一覧を更新
  const refreshSources = useCallback(() => {
    setIsLoadingSources(true)
    if (socket && isConnected) {
      socket.emit('get_sources')
    }
  }, [socket, isConnected])

  // ソースを選択して共有開始
  const handleSelectSource = useCallback((source) => {
    if (socket && isConnected) {
      socket.emit('start_sharing', {
        preset: preset,
        source: {
          type: source.type,
          id: source.id,
          title: source.title || source.name
        },
        withAudio: isAudioEnabled  // 音声も一緒に開始
      })
    }
  }, [socket, isConnected, preset, isAudioEnabled])

  const handleStopSharing = () => {
    if (socket && isConnected) {
      socket.emit('stop_sharing')
    }
  }

  const handleChangePreset = (newPreset) => {
    setPreset(newPreset)
    if (socket && isConnected) {
      socket.emit('change_settings', { preset: newPreset })
    }
  }

  // フルスクリーン切り替え
  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen()
      setIsFullscreen(true)
    } else {
      document.exitFullscreen()
      setIsFullscreen(false)
    }
  }, [])

  // フルスクリーン状態の監視
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement)
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  return (
    <div className={`container ${isFullscreen ? 'fullscreen' : ''}`} ref={containerRef}>
      {!isFullscreen && (
        <Header 
          isConnected={isConnected}
          clientCount={clientCount}
          clientId={clientId}
        />
      )}
      <div className="content">
        <ScreenView 
          currentFrame={currentFrame}
          isSharing={isSharing}
          isConnected={isConnected}
          fps={fps}
          frameInfo={frameInfo}
          isFullscreen={isFullscreen}
          onToggleFullscreen={toggleFullscreen}
          selectedSource={selectedSource}
          audioUnlocked={audioUnlocked}
          onUnlockAudio={unlockAudio}
          isHost={isHost}
          currentSharerId={currentSharerId}
          clientId={clientId}
        />
        {!isFullscreen && (
          <ControlPanel
            isConnected={isConnected}
            isSharing={isSharing}
            isMySharing={currentSharerId === clientId}
            isHost={isHost}
            onStartSharing={openSourcePicker}
            onStopSharing={handleStopSharing}
            clientCount={clientCount}
            fps={fps}
            messages={messages}
            preset={preset}
            onChangePreset={handleChangePreset}
            frameInfo={frameInfo}
            selectedSource={selectedSource}
            onToggleFullscreen={toggleFullscreen}
            isAudioEnabled={isAudioEnabled}
            onToggleAudio={toggleAudio}
            audioAvailable={audioAvailable}
          />
        )}
      </div>
      
      {showSourcePicker && (
        <SourcePicker
          sources={sources}
          onSelect={handleSelectSource}
          onClose={() => setShowSourcePicker(false)}
          onRefresh={refreshSources}
          isLoading={isLoadingSources}
        />
      )}
    </div>
  )
}

export default App
