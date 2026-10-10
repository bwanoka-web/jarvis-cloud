# ==============================================================================
# J.A.R.V.I.S. Cloud Deployment Dockerfile
# Base: Python 3.11 slim (Debian bookworm)
# ==============================================================================

FROM python:3.11-slim

# 1. タイムゾーンおよびロケール環境変数の設定
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOME=/home/appuser

# 2. 必要なシステムパッケージのインストール（最小構成）
# supervisor: マルチプロセス管理
# curl: ヘルスチェックおよび疎通確認
# ca-certificates: HTTPS通信・API暗号化通信の証明書検証
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 3. セキュリティのための非rootグループ・ユーザーの作成
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m -s /bin/bash appuser

# 4. 作業ディレクトリの設定
WORKDIR /app

# 5. 依存関係定義ファイルの先行コピーとインストール（ビルドキャッシュ最適化）
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 6. アプリケーションコード全体のコピー（appuser所有権を付与）
COPY --chown=appuser:appuser . .

# 7. 必要なディレクトリの作成と権限設定
# workspace/requests: リクエストメッセージキュー
# workspace/reports: 生成レポート格納先
# /var/log/supervisor: supervisordログ出力先
# /tmp: 一時ファイルおよびsupervisordのpid/sock出力先
RUN mkdir -p /app/workspace/requests \
             /app/workspace/reports \
             /var/log/supervisor \
             /tmp && \
    chown -R appuser:appuser /app /var/log/supervisor /tmp

# 8. entrypoint.sh のパーミッション設定およびWindows CRLF改行コードのLF変換
RUN chmod +x /app/entrypoint.sh && \
    sed -i 's/\r$//' /app/entrypoint.sh

# 9. 非rootユーザーへの切り替え
USER appuser

# 10. コンテナが公開するデフォルトポート
EXPOSE 8000

# 11. ヘルスチェック定義
# 起動から10秒後に初回チェック、以降30秒間隔でFastAPIのエンドポイントを監視
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/docs || exit 1

# 12. entrypoint スクリプトの実行
ENTRYPOINT ["/app/entrypoint.sh"]
