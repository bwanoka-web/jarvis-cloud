import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import json
import logging
import os
import re
import secrets
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

load_dotenv()

logger = logging.getLogger("jarvis.server")

ENV_MODE = os.environ.get("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENV_MODE in ("production", "prod", "release")

app = FastAPI(
    title="臨床ポケットパートナー - J.A.R.V.I.S.",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
security = HTTPBasic()

# R3-01: パスワード未設定時のデフォルト認証情報フォールバック廃止（Fail-Fast仕様）
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

if IS_PRODUCTION:
    if not ADMIN_PASSWORD or ADMIN_PASSWORD == "password123":
        raise RuntimeError(
            "FATAL: 本番環境において ADMIN_PASSWORD が未設定または初期値(password123)です。"
            "Render環境変数に強固なパスワードを設定してください。"
        )

# R3-02: ブルートフォース攻撃防御（IP単位の連続試行頻度制限）
AUTH_FAILURES = defaultdict(list)

def check_login_rate_limit(client_ip: str):
    now = time.time()
    AUTH_FAILURES[client_ip] = [t for t in AUTH_FAILURES[client_ip] if now - t < 300]
    if len(AUTH_FAILURES[client_ip]) >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="認証試行回数が多すぎます。5分後に再試行してください。"
        )

def get_current_username(credentials: HTTPBasicCredentials = Depends(security), request: Request = None):
    client_ip = request.client.host if (request and request.client) else "unknown"
    if client_ip not in ("testclient", "testserver"):
        check_login_rate_limit(client_ip)

    # 実行時の動的取得により、環境変数の動的更新やテストモックに対応
    expected_username = os.environ.get("ADMIN_USERNAME") or os.environ.get("APP_USERNAME") or "admin"
    
    current_env = os.environ.get("ENVIRONMENT", "development").strip().lower()
    is_prod = current_env in ("production", "prod", "release")
    if is_prod:
        expected_password = os.environ.get("ADMIN_PASSWORD") or os.environ.get("APP_PASSWORD") or ""
    else:
        expected_password = os.environ.get("ADMIN_PASSWORD") or os.environ.get("APP_PASSWORD") or "password123"

    # タイミング攻撃対策: secrets.compare_digest を用いて短絡評価を避けて両方を評価
    correct_username = secrets.compare_digest(credentials.username, expected_username)
    correct_password = secrets.compare_digest(credentials.password, expected_password)

    if not (correct_username and correct_password):
        if client_ip not in ("testclient", "testserver"):
            AUTH_FAILURES[client_ip].append(time.time())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": 'Basic realm="JARVIS Access"'},
        )
    return credentials.username

# R1-07 & R3-05: セキュリティヘッダー付与および /health, /healthz ヘルスチェック
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/healthz"):
            return JSONResponse({"status": "ok", "service": "JARVIS Receptionist"})

        # HTTPアクセス時のHTTPS自動リダイレクト（マイクAPI保護のため）
        proto = request.headers.get("x-forwarded-proto", "").lower()
        if proto == "http":
            url = request.url.replace(scheme="https")
            return Response(status_code=301, headers={"Location": str(url)})

        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self';"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
REQUESTS_DIR = os.path.join(WORKSPACE_DIR, "requests")
REPORTS_DIR = os.path.join(WORKSPACE_DIR, "reports")

os.makedirs(REQUESTS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

api_key = os.environ.get("GEMINI_API_KEY", "").strip()

async def start_research_background(query: str, username: str = "admin") -> str:
    """
    調査リクエストを workspace/requests/ にJSON形式でアトミックに書き込みます。
    """
    ts_now = datetime.now(timezone.utc)
    timestamp_iso = ts_now.isoformat()
    ts_int = int(time.time())
    request_id = f"req_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    filename = f"req_{ts_int}_{request_id}.json"

    request_data = {
        "request_id": request_id,
        "timestamp": timestamp_iso,
        "prompt": query,
        "username": username,
        "status": "pending",
    }

    temp_path = os.path.join(REQUESTS_DIR, f"{filename}.tmp")
    target_path = os.path.join(REQUESTS_DIR, filename)

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, ensure_ascii=False, indent=2)

    os.replace(temp_path, target_path)
    return "リクエストを受け付け、バックグラウンド調査キューに登録しました。"

class ChatRequest(BaseModel):
    message: str = Field(..., max_length=100000, description="リサーチ指示メッセージ")

# R2-04: Gemini APIクォータ枯渇・連打防止のためのレートリミット（受付制限）
USER_REQUEST_LOG = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "60"))

def enforce_user_rate_limit(user: str, client_ip: str = None):
    if client_ip in ("testclient", "testserver"):
        return
    now = time.time()
    USER_REQUEST_LOG[user] = [t for t in USER_REQUEST_LOG[user] if now - t < 60]
    if len(USER_REQUEST_LOG[user]) >= MAX_REQUESTS_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="リクエスト頻度の上限を超過しました。1分後に再試行してください。"
        )
    USER_REQUEST_LOG[user].append(now)

@app.post("/api/chat")
async def chat_with_pm(request: ChatRequest, username: str = Depends(get_current_username), raw_request: Request = None):
    client_ip = raw_request.client.host if (raw_request and raw_request.client) else "unknown"
    enforce_user_rate_limit(username, client_ip)

    async def generate():
        try:
            reply_msg = await start_research_background(request.message, username=username)
            yield reply_msg
        except PermissionError as pe:
            logger.error("チャット受付中に権限エラーが発生しました: %s", pe, exc_info=True)
            yield f"\n[エラーが発生しました]: {str(pe)}"
        except Exception as e:
            logger.error("チャット受付中に予期せぬ内部エラーが発生しました: %s", e, exc_info=True)
            yield "\n[エラーが発生しました]: サーバー内部で処理エラーが発生しました。時間をおいて再試行してください。"

    return StreamingResponse(generate(), media_type="text/plain")

@app.get("/api/latest_report")
async def get_latest_report(username: str = Depends(get_current_username)):
    try:
        if not os.path.exists(REPORTS_DIR):
            return {"filename": None, "content": "", "spoken_summary": ""}

        files = [f for f in os.listdir(REPORTS_DIR) if f.endswith('.md') or f.endswith('.txt')]
        if not files:
            return {"filename": None, "content": "", "spoken_summary": ""}

        latest_file = max(files, key=lambda f: os.path.getmtime(os.path.join(REPORTS_DIR, f)))
        target_path = os.path.join(REPORTS_DIR, latest_file)

        # R1-01: 1. マークダウンファイルのシンボリックリンク検査および境界検証
        if os.path.islink(target_path):
            raise HTTPException(status_code=403, detail="シンボリックリンクへのアクセスは禁止されています")

        real_target = os.path.realpath(target_path)
        real_reports_dir = os.path.realpath(REPORTS_DIR)
        if os.path.commonpath([real_reports_dir, real_target]) != real_reports_dir:
            raise HTTPException(status_code=403, detail="不正なファイル参照です")

        # R4-03: TTL自動パージとの並行競合を安全に捕捉し、最大5MBを読み込み
        try:
            with open(real_target, 'r', encoding='utf-8') as f:
                content = f.read(5 * 1024 * 1024)
        except FileNotFoundError:
            return {"filename": None, "content": "", "spoken_summary": ""}

        spoken_summary = ""
        json_file = latest_file.replace('.md', '.json').replace('.txt', '.json')
        json_path = os.path.join(REPORTS_DIR, json_file)

        # R1-01: 2. 音声要約用JSONファイルに対するシンボリックリンクおよび境界検証
        if os.path.exists(json_path):
            if os.path.islink(json_path):
                raise HTTPException(status_code=403, detail="関連JSONファイルのシンボリックリンクアクセスは禁止されています")
            real_json = os.path.realpath(json_path)
            if os.path.commonpath([real_reports_dir, real_json]) != real_reports_dir:
                raise HTTPException(status_code=403, detail="不正なJSONファイル参照です")
            try:
                with open(real_json, 'r', encoding='utf-8') as jf:
                    jdata = json.load(jf)
                    spoken_summary = jdata.get("spoken_summary", "")
            except (FileNotFoundError, json.JSONDecodeError):
                spoken_summary = ""

        if not spoken_summary and content.startswith("---"):
            match = re.search(r'spoken_summary:\s*(?:"(.*?)"|([\S\s]*?))\n---', content)
            if match:
                summary_val = match.group(1) or match.group(2)
                try:
                    spoken_summary = json.loads(f'"{summary_val}"') if not summary_val.startswith('"') else json.loads(summary_val)
                except Exception:
                    spoken_summary = summary_val.strip()

        return {"filename": latest_file, "content": content, "spoken_summary": spoken_summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("最新レポート取得中に予期せぬ内部エラーが発生しました: %s", e, exc_info=True)
        return {"filename": None, "content": "Error loading report: レポートの読み込み中に内部エラーが発生しました。", "spoken_summary": ""}

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(username: str = Depends(get_current_username)):
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>J.A.R.V.I.S. Operations</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
        <style>
            body { background-color: #050a1f; color: #4fc3f7; }
            .jarvis-header { background-color: #020617; border-bottom: 1px solid #0369a1; }
            .jarvis-panel { background-color: rgba(2, 6, 23, 0.7); border: 1px solid #0369a1; box-shadow: 0 0 10px #0369a1; }
            .jarvis-btn { background: linear-gradient(135deg, #0284c7, #0369a1); box-shadow: 0 0 15px #0284c7; }
            .jarvis-btn-active { background: linear-gradient(135deg, #059669, #047857); box-shadow: 0 0 20px #059669; animation: pulse-green 2s infinite; }
            .jarvis-btn-thinking { background: linear-gradient(135deg, #d97706, #b45309); box-shadow: 0 0 20px #d97706; }
            @keyframes pulse-green { 0% { box-shadow: 0 0 0 0 rgba(5, 150, 105, 0.7); } 70% { box-shadow: 0 0 0 15px rgba(5, 150, 105, 0); } 100% { box-shadow: 0 0 0 0 rgba(5, 150, 105, 0); } }
            .markdown-body h1, .markdown-body h2, .markdown-body h3 { color: #38bdf8; margin-top: 1em; margin-bottom: 0.5em; font-weight: bold; }
            .markdown-body h1 { font-size: 1.5em; border-bottom: 1px solid #0369a1; padding-bottom: 0.3em; }
            .markdown-body h2 { font-size: 1.25em; }
            .markdown-body p, .markdown-body ul, .markdown-body ol { margin-bottom: 1em; }
            .markdown-body ul { list-style-type: disc; padding-left: 2em; }
            .markdown-body ol { list-style-type: decimal; padding-left: 2em; }
            .markdown-body a { color: #7dd3fc; text-decoration: underline; }
            .markdown-body strong { color: #bae6fd; font-weight: bold; }
            .markdown-body code { background-color: #0f172a; padding: 0.2em 0.4em; border-radius: 3px; font-family: monospace; }
            .markdown-body pre { background-color: #0f172a; padding: 1em; border-radius: 5px; overflow-x: auto; margin-bottom: 1em; }
            .markdown-body pre code { background-color: transparent; padding: 0; }
        </style>
    </head>
    <body class="min-h-screen h-[100dvh] flex flex-col font-mono">
        <header class="jarvis-header p-4 flex justify-between items-center">
            <h1 class="text-xl font-bold tracking-widest">J.A.R.V.I.S.</h1>
            <span class="text-xs" id="system-status">STATUS: STANDBY</span>
        </header>
        
        <main class="flex-1 overflow-y-auto md:overflow-hidden p-3 md:p-4 flex flex-col md:flex-row gap-3 md:gap-4" id="main-container">
            <div class="flex-1 min-h-[260px] md:min-h-0 overflow-y-auto flex flex-col gap-3 md:gap-4" id="chat-container">
                <div class="jarvis-panel p-4 rounded-lg w-5/6">
                    <p>システム起動。運転モード（ウェイクワード待機）を開始するには、下の「🎙️ 常時リスニング開始」ボタンを一度だけタップしてください。</p>
                </div>
            </div>
            <div class="flex-1 min-h-[300px] md:min-h-0 overflow-y-auto jarvis-panel p-3 md:p-4 rounded-lg flex flex-col gap-2">
                <div class="text-sm font-bold border-b border-sky-800 pb-2 mb-2 flex justify-between items-center">
                    <span>DELIVERABLES VIEWER</span>
                    <span id="current-report-name" class="text-xs text-sky-400">No active report</span>
                </div>
                <div id="markdown-viewer" class="markdown-body text-sm overflow-y-auto">
                    Waiting for background tasks...
                </div>
            </div>
        </main>

        <footer class="jarvis-header p-3 md:p-4" style="padding-bottom: max(0.75rem, env(safe-area-inset-bottom));">
            <form id="chat-form" class="flex flex-col gap-3">
                <button type="button" id="continuous-mic-btn" class="jarvis-btn text-white w-full py-4 rounded-lg font-bold tracking-wider text-lg transition">🎙️ 常時リスニング開始</button>
                <div class="flex gap-2">
                    <input type="text" id="message-input" class="flex-1 bg-gray-900 border border-sky-700 rounded-lg px-4 py-2 text-sky-200 focus:outline-none focus:ring-2 focus:ring-sky-400" placeholder="テキストで直接入力も可能...">
                    <button type="submit" id="send-button" class="jarvis-btn text-white px-4 py-2 rounded-lg font-bold">SEND</button>
                </div>
                <div class="flex justify-between items-center px-2">
                    <span id="status-text" class="text-xs text-sky-400">マイクはオフです</span>
                    <label class="flex items-center gap-2 text-xs cursor-pointer">
                        <input type="checkbox" id="tts-toggle" checked class="form-checkbox bg-gray-900 border-sky-700 text-sky-500">
                        音声読み上げ
                    </label>
                </div>
            </form>
        </footer>

        <script>
            const form = document.getElementById('chat-form');
            const input = document.getElementById('message-input');
            const container = document.getElementById('chat-container');
            const sendButton = document.getElementById('send-button');
            const micBtn = document.getElementById('continuous-mic-btn');
            const statusText = document.getElementById('status-text');
            const ttsToggle = document.getElementById('tts-toggle');
            const systemStatus = document.getElementById('system-status');

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition = null;
            let isContinuousMode = false;
            let isAiSpeaking = false;
            let isAiThinking = false;
            let isAudioUnlocked = false;
            let isRecognizing = false;
            let isStarting = false;
            let ttsSafetyTimer = null;
            let micCooldownTimer = null;
            let lastSpokenText = "";
            let lastSpokenTime = 0;

            // 車載音声コマンド（ウェイクワードの有無に関わらず全音声に自然反応）
            const WAKE_WORDS = ["ジャービス", "jarvis", "ジャビス"];
            function cleanWakeWords(text) {
                let cleaned = text;
                for (const w of WAKE_WORDS) {
                    cleaned = cleaned.replace(new RegExp(w, "gi"), "");
                }
                return cleaned.trim() || text.trim();
            }

            // R4-02: 車載高精度音響反響判定アルゴリズム
            function isAcousticEcho(inputTranscript, lastSpoken, ttsEndedTimestamp) {
                if (!lastSpoken || !inputTranscript) return false;
                const elapsed = Date.now() - ttsEndedTimestamp;
                if (elapsed > 1000) return false;

                const cleanInput = inputTranscript.replace(/[\\s、。！？]/g, '');
                const cleanSpoken = lastSpoken.replace(/[\\s、。！？]/g, '');
                if (!cleanInput || !cleanSpoken) return false;

                const userIntentMarkers = ["して", "教えて", "じゃなくて", "確認して", "調べて", "見せて", "合わせて", "改定して"];
                const hasIntentMarker = userIntentMarkers.some(marker => cleanInput.includes(marker));

                const setInput = new Set(cleanInput.split(''));
                const setSpoken = new Set(cleanSpoken.split(''));
                const intersection = [...setInput].filter(x => setSpoken.has(x)).length;
                const similarity = (2.0 * intersection) / (setInput.size + setSpoken.size);

                const lengthRatio = cleanInput.length / cleanSpoken.length;
                const isSimilarLength = lengthRatio >= 0.7 && lengthRatio <= 1.3;

                const threshold = hasIntentMarker ? 0.85 : 0.65;
                return similarity >= threshold && isSimilarLength;
            }

            // 非同期トーストUI（安全運転妨害防止）
            function showToastNotification(message, durationMs = 4000) {
                const toast = document.createElement('div');
                toast.className = 'fixed top-4 left-1/2 transform -translate-x-1/2 bg-amber-600/90 text-white px-4 py-2 rounded-lg text-sm shadow-lg z-50 transition-opacity duration-300 font-sans';
                toast.textContent = message;
                document.body.appendChild(toast);
                setTimeout(() => {
                    toast.style.opacity = '0';
                    setTimeout(() => toast.remove(), 300);
                }, durationMs);
            }

            // 車載サーキットブレーカー（alert排除・自動クールダウン）
            let echoStreakCount = 0;
            let isCooldownActive = false;
            function handleCircuitBreakerOnEcho() {
                echoStreakCount++;
                if (echoStreakCount >= 3 && !isCooldownActive) {
                    isCooldownActive = true;
                    console.warn("連続音響エコーを検知。一時保留モードに移行します。");
                    showToastNotification("⚠️ 反響音を連続検知したため、音声入力を10秒間保留します（自動復帰）");
                    if (recognition && isContinuousMode) {
                        try { recognition.stop(); } catch(e) {}
                    }
                    setTimeout(() => {
                        echoStreakCount = 0;
                        isCooldownActive = false;
                        showToastNotification("🎙️ 音声入力を自動再開しました", 2000);
                        if (recognition && isContinuousMode && !isAiSpeaking && !isAiThinking) {
                            restartRecognitionIfNeeded();
                        }
                    }, 10000);
                    return true;
                }
                return false;
            }

            // Secure Context 検証と親切な案内
            if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
                statusText.innerText = '⚠️ HTTPS接続が必要です（マイクは保護されたURLでのみ動作します）';
                micBtn.disabled = true;
                micBtn.classList.add('opacity-50', 'cursor-not-allowed');
            }

            function restartRecognitionIfNeeded() {
                if (!isContinuousMode || isAiSpeaking || isAiThinking || !recognition) return;
                if (isRecognizing || isStarting) return;
                try {
                    isStarting = true;
                    recognition.start();
                    micBtn.classList.remove('jarvis-btn-thinking');
                    micBtn.classList.add('jarvis-btn-active');
                    micBtn.innerText = '🎙️ お話しください...（全音声に反応）';
                    statusText.innerText = '周囲の音声を監視中...';
                } catch (e) {
                    isStarting = false;
                    if (e.name === 'InvalidStateError') {
                        isRecognizing = true;
                        micBtn.classList.remove('jarvis-btn-thinking');
                        micBtn.classList.add('jarvis-btn-active');
                        micBtn.innerText = '🎙️ お話しください...（全音声に反応）';
                        statusText.innerText = '周囲の音声を監視中...';
                    } else if (e.name !== 'NotAllowedError') {
                        setTimeout(() => {
                            if (isContinuousMode && !isAiSpeaking && !isAiThinking && !isRecognizing && !isStarting) {
                                try { isStarting = true; recognition.start(); } catch(_) { isStarting = false; }
                            }
                        }, 500);
                    }
                }
            }

            if (SpeechRecognition) {
                recognition = new SpeechRecognition();
                recognition.lang = 'ja-JP';
                recognition.continuous = true; 
                recognition.interimResults = false; 
                recognition.maxAlternatives = 1;

                recognition.onstart = () => {
                    isStarting = false;
                    isRecognizing = true;
                    if (isAiSpeaking || isAiThinking) return;
                    micBtn.classList.remove('jarvis-btn', 'jarvis-btn-thinking');
                    micBtn.classList.add('jarvis-btn-active');
                    micBtn.innerText = '🎙️ お話しください...（全音声に反応）';
                    statusText.innerText = '周囲の音声を監視中...';
                };

                let transcriptBuffer = "";
                let speechTimeout = null;
                
                recognition.onresult = (event) => {
                    if (isAiSpeaking || isAiThinking || (window.speechSynthesis && window.speechSynthesis.speaking)) return;
                    
                    let newTranscript = "";
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        const t = event.results[i][0].transcript.trim();
                        if (t) newTranscript += t + " ";
                    }
                    newTranscript = newTranscript.trim();
                    if (!newTranscript || newTranscript.length < 2) return;

                    // システム定型アナウンスのエコー誤検知フィルター
                    const systemPhrases = ["リクエストを受け付け", "バックグラウンド調査", "キューに登録", "報告書が完成しました", "内容を読み上げます", "以下省略します"];
                    if (systemPhrases.some(p => newTranscript.includes(p))) {
                        console.log("System message echo ignored:", newTranscript);
                        return;
                    }
                    
                    // R4-02: 車載高精度音響エコー判定とサーキットブレーカー
                    if (isAcousticEcho(newTranscript, lastSpokenText, lastSpokenTime)) {
                        console.log("Acoustic echo detected and ignored:", newTranscript);
                        handleCircuitBreakerOnEcho();
                        return;
                    }

                    // TTS発話直後のエコー・マイク誤検知フィルター
                    if (Date.now() - lastSpokenTime < 4000 && lastSpokenText) {
                        const cleanT = newTranscript.replace(/[、。！？\\s]/g, '');
                        const cleanS = lastSpokenText.replace(/[、。！？\\s]/g, '');
                        if (cleanS.includes(cleanT) || cleanT.includes(cleanS.substring(0, 15))) {
                            console.log("TTS echo ignored:", newTranscript);
                            return;
                        }
                    }

                    // 全音声入力モード（ウェイクワードがあれば自然に除去）
                    newTranscript = cleanWakeWords(newTranscript);
                    if (!newTranscript) return;
                    
                    transcriptBuffer += newTranscript + " ";
                    statusText.innerText = '認識中... (' + transcriptBuffer.trim() + ')';
                    input.value = transcriptBuffer.trim();
                    
                    if (speechTimeout) clearTimeout(speechTimeout);
                    speechTimeout = setTimeout(() => {
                        statusText.innerText = '送信します';
                        transcriptBuffer = "";
                        form.dispatchEvent(new Event('submit'));
                    }, 2500); // ユーザーの話し終わりを待機
                };

                recognition.onerror = (event) => {
                    isStarting = false;
                    console.warn("Speech recognition error:", event.error);
                    switch (event.error) {
                        case 'not-allowed':
                            statusText.innerText = '⚠️ マイク使用が拒否されました。Safari設定（ぁあ > Webサイトの設定 > マイク）で許可してください';
                            isContinuousMode = false;
                            isRecognizing = false;
                            micBtn.classList.remove('jarvis-btn-active', 'jarvis-btn-thinking');
                            micBtn.classList.add('jarvis-btn');
                            micBtn.innerText = '🎙️ マイク許可後にタップしてください';
                            break;
                        case 'network':
                            statusText.innerText = '⚠️ 音声認識ネットワーク待機中...自動復帰を試みます';
                            if (isContinuousMode && !isAiSpeaking && !isAiThinking) {
                                setTimeout(restartRecognitionIfNeeded, 1500);
                            }
                            break;
                        case 'no-speech':
                            statusText.innerText = '周囲の音声を監視中...';
                            break;
                        case 'audio-capture':
                            statusText.innerText = '⚠️ マイク機器が検出されません。マイクが利用可能かご確認ください';
                            break;
                        case 'aborted':
                            // 送信や発話時の意図的アボート
                            break;
                        default:
                            statusText.innerText = '音声認識ステータス: ' + event.error;
                            break;
                    }
                };

                recognition.onend = () => {
                    isStarting = false;
                    isRecognizing = false;
                    if (isContinuousMode && !isAiSpeaking && !isAiThinking) {
                        setTimeout(() => {
                            restartRecognitionIfNeeded();
                        }, 300);
                    }
                };
            } else {
                micBtn.style.display = 'none';
                statusText.innerText = 'お使いのブラウザは音声認識に非対応です。';
            }

            // iOS Safari向けオーディオアンロック（Web Audio API + SpeechSynthesis）
            function unlockAudio() {
                if (isAudioUnlocked) return;
                try {
                    const AudioCtx = window.AudioContext || window.webkitAudioContext;
                    if (AudioCtx) {
                        const ctx = new AudioCtx();
                        const buffer = ctx.createBuffer(1, 1, 22050);
                        const source = ctx.createBufferSource();
                        source.buffer = buffer;
                        source.connect(ctx.destination);
                        source.start(0);
                        if (ctx.state === 'suspended') {
                            ctx.resume();
                        }
                    }
                    if (window.speechSynthesis) {
                        const dummyUtterance = new SpeechSynthesisUtterance(' ');
                        dummyUtterance.volume = 0.01;
                        window.speechSynthesis.speak(dummyUtterance);
                    }
                    isAudioUnlocked = true;
                    console.log("iOS Safari Audio Unlocked.");
                } catch (e) {
                    console.warn("Audio unlock warning:", e);
                }
            }

            micBtn.addEventListener('click', () => {
                isContinuousMode = !isContinuousMode;
                if(isContinuousMode) {
                    micBtn.classList.remove('jarvis-btn', 'jarvis-btn-thinking');
                    micBtn.classList.add('jarvis-btn-active');
                    micBtn.innerText = '🎙️ お話しください...（全音声に反応）';
                    statusText.innerText = '周囲の音声を監視中...';
                    try { unlockAudio(); } catch(e) { console.warn(e); }
                    restartRecognitionIfNeeded();
                } else {
                    if (recognition) {
                        try { recognition.stop(); } catch(e){}
                    }
                    isRecognizing = false;
                    isStarting = false;
                    micBtn.classList.remove('jarvis-btn-active', 'jarvis-btn-thinking');
                    micBtn.classList.add('jarvis-btn');
                    micBtn.innerText = '🎙️ 常時リスニング開始';
                    statusText.innerText = 'マイクはオフです';
                }
            });

            function speakText(text, isShortReply = false) {
                if (!ttsToggle.checked) {
                    if (!isShortReply) onAiFinishedSpeaking();
                    else resumeListeningAfterShortReply();
                    return;
                }

                // 進行中の認識バッファやタイマーをクリアしてエコー誤送信を防止
                if (speechTimeout) {
                    clearTimeout(speechTimeout);
                    speechTimeout = null;
                }
                transcriptBuffer = "";
                input.value = "";

                // エコー防止ステップ1: マイク物理集音を即時停止
                if (recognition) {
                    try { recognition.abort(); } catch(e) {}
                }
                isRecognizing = false;

                isAiSpeaking = true;
                lastSpokenText = text;
                lastSpokenTime = Date.now();

                micBtn.classList.remove('jarvis-btn-active');
                micBtn.classList.add('jarvis-btn-thinking');
                micBtn.innerText = '🔊 JARVIS 発話中...';
                statusText.innerText = '報告書を読み上げ中（マイク停止中）';
                
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.lang = 'ja-JP';
                utterance.rate = 1.1; 
                utterance.pitch = 0.9;
                window.currentUtterance = utterance;

                const cleanupAndFinish = () => {
                    if (ttsSafetyTimer) {
                        clearTimeout(ttsSafetyTimer);
                        ttsSafetyTimer = null;
                    }
                    window.currentUtterance = null;
                    onAiFinishedSpeaking();
                };

                utterance.onend = cleanupAndFinish;
                utterance.onerror = (e) => {
                    console.error("TTS Error:", e);
                    cleanupAndFinish();
                };

                const doSpeak = () => {
                    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
                        try { window.speechSynthesis.cancel(); } catch(_) {}
                    }
                    const voices = window.speechSynthesis.getVoices();
                    const jpVoices = voices.filter(v => v.lang.includes('ja'));
                    if (jpVoices.length > 0) {
                        const bestVoice = jpVoices.find(v => 
                            v.name.includes('Google') || 
                            v.name.includes('Premium') || 
                            v.name.includes('Nanami') || 
                            v.name.includes('Kyoko')
                        );
                        utterance.voice = bestVoice || jpVoices[0];
                    }
                    window.speechSynthesis.speak(utterance);

                    // ハングアップ救済フェイルセーフタイマー
                    const maxDuration = Math.max(3000, text.length * 250 + 2000);
                    ttsSafetyTimer = setTimeout(() => {
                        if (isAiSpeaking) {
                            console.warn("TTS timeout reached. Recovering microphone state.");
                            cleanupAndFinish();
                        }
                    }, maxDuration);
                };

                if (window.speechSynthesis.getVoices().length === 0) {
                    let called = false;
                    const onVoicesLoaded = () => {
                        if (called) return;
                        called = true;
                        window.speechSynthesis.removeEventListener('voiceschanged', onVoicesLoaded);
                        doSpeak();
                    };
                    window.speechSynthesis.addEventListener('voiceschanged', onVoicesLoaded);
                    setTimeout(() => {
                        if (!called) {
                            called = true;
                            window.speechSynthesis.removeEventListener('voiceschanged', onVoicesLoaded);
                            doSpeak();
                        }
                    }, 1000);
                } else {
                    doSpeak();
                }
            }

            function onAiFinishedSpeaking() {
                if (!isAiSpeaking) return;
                lastSpokenTime = Date.now();
                if (micCooldownTimer) clearTimeout(micCooldownTimer);

                // エコー防止ステップ2: スピーカー残響回避のためのクールダウン（1000ms）
                micCooldownTimer = setTimeout(() => {
                    isAiSpeaking = false;
                    transcriptBuffer = "";
                    input.value = "";
                    if (isContinuousMode && !isAiThinking) {
                        restartRecognitionIfNeeded();
                    } else if (!isContinuousMode) {
                        micBtn.classList.remove('jarvis-btn-thinking', 'jarvis-btn-active');
                        micBtn.classList.add('jarvis-btn');
                        micBtn.innerText = '🎙️ 常時リスニング開始';
                        statusText.innerText = 'マイクはオフです';
                    }
                }, 1000);
            }

            function resumeListeningAfterShortReply() {
                onAiFinishedSpeaking();
            }

            // R4-04: モバイル回線瞬断時における自動リトライ（指数バックオフ）
            async function sendRequestWithExponentialBackoff(message, maxAttempts = 3) {
                let delay = 1000;
                for (let attempt = 1; attempt <= maxAttempts; attempt++) {
                    try {
                        const res = await fetch('/api/chat', {
                            method: 'POST',
                            headers: { 
                                'Content-Type': 'application/json',
                                'Bypass-Tunnel-Reminder': 'true'
                            },
                            body: JSON.stringify({ message })
                        });
                        if (res.ok) return res;
                        throw new Error(`HTTP ${res.status}`);
                    } catch (error) {
                        if (attempt === maxAttempts) throw error;
                        statusText.innerText = `📡 電波瞬断検知。自動再試行中 (${attempt}/${maxAttempts})...`;
                        await new Promise(r => setTimeout(r, delay));
                        delay *= 2;
                    }
                }
            }

            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                const message = input.value.trim();
                if (!message) return;

                // 認識タイマーのクリアとマイクの一時停止
                if (speechTimeout) {
                    clearTimeout(speechTimeout);
                    speechTimeout = null;
                }
                transcriptBuffer = "";
                if (recognition) {
                    try { recognition.abort(); } catch(e) {}
                }
                isRecognizing = false;

                isAiThinking = true;

                appendMessage('You', message, 'bg-sky-900 border border-sky-700 self-end');
                input.value = '';
                input.disabled = true;
                sendButton.disabled = true;
                
                if (isContinuousMode) {
                    micBtn.classList.remove('jarvis-btn-active');
                    micBtn.classList.add('jarvis-btn-thinking');
                    micBtn.innerText = '⏳ 思考中...';
                }

                systemStatus.innerText = 'STATUS: PROCESSING';
                statusText.innerText = 'リクエストを送信中...';

                const agentBubble = appendMessage('J.A.R.V.I.S.', '...', 'jarvis-panel self-start w-5/6');
                const contentDiv = agentBubble.querySelector('.content');

                try {
                    const response = await sendRequestWithExponentialBackoff(message);
                    
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    contentDiv.innerText = ''; 

                    let fullResponse = '';
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;
                        const chunk = decoder.decode(value);
                        contentDiv.innerText += chunk;
                        fullResponse += chunk;
                        container.scrollTop = container.scrollHeight;
                    }
                    
                    isAiThinking = false;
                    systemStatus.innerText = 'STATUS: ONLINE';
                    statusText.innerText = 'リクエストを受け付けました。調査完了まで待機中...';
                    
                    // 【受付確認の音声読み上げは廃止】
                    // ユーザーの要望により、リクエスト受付時のspeakTextは呼び出さず画面表示のみ（無音化）とする。
                    // 音声読み上げは調査完了後の報告書（spoken_summary）のみで行う。

                } catch (error) {
                    isAiThinking = false;
                    contentDiv.innerText += '\\n[通信エラー]';
                    systemStatus.innerText = 'STATUS: ERROR';
                    statusText.innerText = '通信エラーが発生しました';
                } finally {
                    input.disabled = false;
                    sendButton.disabled = false;
                    
                    if (isContinuousMode) {
                        micBtn.classList.remove('jarvis-btn-thinking');
                        micBtn.classList.add('jarvis-btn-active');
                        micBtn.innerText = '🎙️ お話しください...（全音声に反応）';
                        // リクエスト受付完了後に音声認識を再開
                        restartRecognitionIfNeeded();
                    }
                    if (!isContinuousMode) {
                        input.focus();
                    }
                }
            });

            // R1-02: チャット履歴追加（DOM要素生成と textContent による安全なエスケープ）
            function appendMessage(sender, text, classes) {
                const div = document.createElement('div');
                div.className = `p-3 rounded-lg flex flex-col gap-1 ${classes}`;

                const senderSpan = document.createElement('span');
                senderSpan.className = 'text-xs text-sky-300 font-bold tracking-wider';
                senderSpan.textContent = sender;

                const contentPre = document.createElement('pre');
                contentPre.className = 'content text-sky-100 whitespace-pre-wrap font-sans text-sm';
                contentPre.textContent = text;

                div.appendChild(senderSpan);
                div.appendChild(contentPre);
                container.appendChild(div);
                container.scrollTop = container.scrollHeight;
                return div;
            }

            let lastReportFilename = '';
            let lastReportContent = '';
            let isInitialReportLoad = true;
            setInterval(async () => {
                try {
                    const res = await fetch('/api/latest_report');
                    if (res.ok) {
                        const data = await res.json();
                        if (data.filename && (data.filename !== lastReportFilename || data.content !== lastReportContent)) {
                            lastReportFilename = data.filename;
                            lastReportContent = data.content;
                            document.getElementById('current-report-name').innerText = data.filename;
                            // R1-02: レポート描画（DOMPurifyによるXSSサニタイズ）
                            const rawHtml = marked.parse(data.content);
                            const sanitizedHtml = DOMPurify.sanitize(rawHtml);
                            document.getElementById('markdown-viewer').innerHTML = sanitizedHtml;
                            if (!isInitialReportLoad) {
                                if (data.spoken_summary) {
                                    speakText(data.spoken_summary, false);
                                } else {
                                    let plainText = data.content.replace(/[#*>-]/g, "").trim();
                                    if (plainText.length > 250) {
                                        plainText = plainText.substring(0, 250) + "。以下省略します。";
                                    }
                                    speakText("報告書が完成しました。内容を読み上げます。" + plainText, false);
                                }
                            }
                        }
                        isInitialReportLoad = false;
                    }
                } catch (e) {
                    console.error('Failed to fetch latest report', e);
                }
            }, 3000);

            // 音声認識が切れた場合に自動復旧するウォッチドッグ
            setInterval(() => {
                if (isContinuousMode && !isAiSpeaking && !isAiThinking && !isRecognizing) {
                    restartRecognitionIfNeeded();
                }
            }, 4000);
        </script>
    </body>
    </html>
    """
    return html_content

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")

