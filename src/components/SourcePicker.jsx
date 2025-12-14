import React, { useState, useEffect } from 'react';
import { Monitor, AppWindow, X, RefreshCw, Check } from 'lucide-react';
import './SourcePicker.css';

const SourcePicker = ({ sources, onSelect, onClose, onRefresh, isLoading }) => {
  const [selectedSource, setSelectedSource] = useState(null);
  const [activeTab, setActiveTab] = useState('all');

  const monitors = sources.filter(s => s.type === 'monitor');
  const windows = sources.filter(s => s.type === 'window');

  const filteredSources = activeTab === 'all' 
    ? sources 
    : activeTab === 'monitors' 
      ? monitors 
      : windows;

  const handleSelect = () => {
    if (selectedSource) {
      onSelect(selectedSource);
    }
  };

  return (
    <div className="source-picker-overlay">
      <div className="source-picker-modal">
        <div className="source-picker-header">
          <h2>共有するコンテンツを選択</h2>
          <button className="close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="source-picker-tabs">
          <button 
            className={`tab ${activeTab === 'all' ? 'active' : ''}`}
            onClick={() => setActiveTab('all')}
          >
            すべて ({sources.length})
          </button>
          <button 
            className={`tab ${activeTab === 'monitors' ? 'active' : ''}`}
            onClick={() => setActiveTab('monitors')}
          >
            <Monitor size={16} />
            画面 ({monitors.length})
          </button>
          <button 
            className={`tab ${activeTab === 'windows' ? 'active' : ''}`}
            onClick={() => setActiveTab('windows')}
          >
            <AppWindow size={16} />
            ウィンドウ ({windows.length})
          </button>
          <button className="refresh-btn" onClick={onRefresh} disabled={isLoading}>
            <RefreshCw size={16} className={isLoading ? 'spinning' : ''} />
          </button>
        </div>

        <div className="source-picker-grid">
          {isLoading ? (
            <div className="loading-state">
              <RefreshCw size={32} className="spinning" />
              <p>ソースを読み込み中...</p>
            </div>
          ) : filteredSources.length === 0 ? (
            <div className="empty-state">
              <p>共有可能なソースがありません</p>
            </div>
          ) : (
            filteredSources.map((source) => (
              <div
                key={`${source.type}-${source.id}`}
                className={`source-item ${selectedSource?.id === source.id && selectedSource?.type === source.type ? 'selected' : ''}`}
                onClick={() => setSelectedSource(source)}
              >
                <div className="source-thumbnail">
                  {source.thumbnail ? (
                    <img 
                      src={`data:image/jpeg;base64,${source.thumbnail}`} 
                      alt={source.name}
                    />
                  ) : (
                    <div className="no-thumbnail">
                      {source.type === 'monitor' ? <Monitor size={32} /> : <AppWindow size={32} />}
                    </div>
                  )}
                  {selectedSource?.id === source.id && selectedSource?.type === source.type && (
                    <div className="selected-overlay">
                      <Check size={24} />
                    </div>
                  )}
                </div>
                <div className="source-info">
                  <span className="source-type-icon">
                    {source.type === 'monitor' ? <Monitor size={14} /> : <AppWindow size={14} />}
                  </span>
                  <span className="source-name" title={source.title || source.name}>
                    {source.name}
                  </span>
                </div>
                <div className="source-resolution">
                  {source.width}×{source.height}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="source-picker-footer">
          <div className="selected-info">
            {selectedSource && (
              <span>
                選択中: {selectedSource.name}
              </span>
            )}
          </div>
          <div className="footer-buttons">
            <button className="cancel-btn" onClick={onClose}>
              キャンセル
            </button>
            <button 
              className="share-btn" 
              onClick={handleSelect}
              disabled={!selectedSource}
            >
              共有を開始
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SourcePicker;
