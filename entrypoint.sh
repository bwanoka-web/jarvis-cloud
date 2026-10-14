#!/bin/bash
# ==============================================================================
# J.A.R.V.I.S. Container Entrypoint Script
# Handles PORT binding, directory verification, and supervisord PID 1 handoff
# ==============================================================================

set -euo pipefail

# 1. PORT環境変数の動的検証とフォールバック
export PORT="${PORT:-8000}"
echo "[entrypoint] Initializing J.A.R.V.I.S. container..."
echo "[entrypoint] Active PORT: ${PORT}"
echo "[entrypoint] Running as user: $(whoami) (UID: $(id -u), GID: $(id -g))"

# 2. workspaceディレクトリの存在確認と自動作成
mkdir -p /app/workspace/requests /app/workspace/reports /app/workspace/memory

# 3. 書き込み権限の自己検証
if [ ! -w /app/workspace/requests ]; then
    echo "[entrypoint] ERROR: /app/workspace/requests is not writable by $(whoami)" >&2
    exit 1
fi

if [ ! -w /app/workspace/reports ]; then
    echo "[entrypoint] ERROR: /app/workspace/reports is not writable by $(whoami)" >&2
    exit 1
fi

if [ ! -w /app/workspace/memory ]; then
    echo "[entrypoint] ERROR: /app/workspace/memory is not writable by $(whoami)" >&2
    exit 1
fi

# 4. supervisord設定ファイルの存在確認
SUPERVISOR_CONF="/etc/supervisor/conf.d/supervisord.conf"
if [ ! -f "${SUPERVISOR_CONF}" ]; then
    if [ -f "/app/supervisord.conf" ]; then
        SUPERVISOR_CONF="/app/supervisord.conf"
    else
        echo "[entrypoint] ERROR: supervisord.conf not found at /etc/supervisor/conf.d/supervisord.conf or /app/supervisord.conf" >&2
        exit 1
    fi
fi
echo "[entrypoint] Using supervisor configuration: ${SUPERVISOR_CONF}"

# 5. 引数の処理と実行（execによるPID 1置換）
# 引数が渡されていない場合は、supervisordをフォアグラウンド(-n)でexec起動
if [ $# -eq 0 ]; then
    echo "[entrypoint] Launching supervisord process manager..."
    exec /usr/bin/supervisord -n -c "${SUPERVISOR_CONF}"
else
    # 任意のカスタムコマンド（デバッグやテスト実行など）が渡された場合
    echo "[entrypoint] Executing custom command: $@"
    exec "$@"
fi
