# LocalCast

ローカルネットワーク内でPCの画面と音声を共有するWebアプリです。個人利用目的で作成しました。

## 使い方

### セットアップ

```bash
# 仮想環境を作成
python -m venv venv

# 仮想環境を有効化
venv\Scripts\activate

# 依存パッケージをインストール
pip install -r requirements.txt
npm install
npm run build
```

### 起動

```bash
python server.py
```

### ホスト（配信側）

1. `http://localhost:5000` にアクセス
2. 「共有を開始」をクリック
3. モニターまたはウィンドウを選択
4. 「共有を開始」で配信開始

### クライアント（視聴側）

1. `http://<サーバーIP>:5000` にアクセス
2. 画面が自動表示される
3. 音声が出ない場合はページをクリック

## 技術スタック

### バックエンド
- Python 3.8+
- Flask / Flask-SocketIO
- mss（画面キャプチャ）
- OpenCV（画像エンコード）
- pyaudiowpatch（WASAPI音声キャプチャ）
- pywin32（ウィンドウ操作）

### フロントエンド
- React 18
- Vite
- Socket.IO Client

## 動作環境

- Windows 10/11
- Node.js 16+
- モダンブラウザ（Chrome, Edge, Firefox）

## ライセンス

MIT
