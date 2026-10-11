import asyncio
import gc
import glob
import json
import os
import re
import time
from datetime import datetime
from dotenv import load_dotenv
from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
REQUESTS_DIR = os.path.join(WORKSPACE_DIR, "requests")
REPORTS_DIR = os.path.join(WORKSPACE_DIR, "reports")

os.makedirs(REQUESTS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

api_key = os.environ.get("GEMINI_API_KEY", "").strip()

worker_config = LocalAgentConfig(
    api_key=api_key if api_key else None,
    system_instructions="あなたはJ.A.R.V.I.S.の裏側で稼働する自律リサーチエージェントです。与えられた依頼に対して、Web検索などを駆使して詳細な調査を行い、報告書を作成してください。出力は必ず以下のJSON形式とし、それ以外のテキストは含めないでください。\n{\"spoken_summary\": \"<TTSで読み上げるための2〜3文の短い要約>\", \"markdown_report\": \"<マークダウン形式の詳細な報告書本文>\"}",
    model="gemini-2.5-flash-lite",
    capabilities=CapabilitiesConfig(
        enabled_tools=["search_web", "read_url_content"]
    )
)


def extract_prompt_from_content(file_path: str, content: str) -> str:
    """ファイルパスと内容から優先順位に基づいてプロンプトを抽出する"""
    raw_content = content.strip()
    if not raw_content:
        raise ValueError("リクエスト内容が空または空白のみです。")

    if file_path.endswith(".json") or file_path.endswith(".json.processing"):
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"破損したJSONファイルです: {e}")

        if isinstance(data, dict):
            prompt = data.get("prompt")
            if prompt and isinstance(prompt, str) and prompt.strip():
                return prompt.strip()

            query = data.get("query")
            if query and isinstance(query, str) and query.strip():
                return query.strip()

            raise ValueError("JSON内に有効なpromptまたはqueryキーが存在しません。")
        else:
            raise ValueError("JSONルート要素が辞書形式ではありません。")

    return raw_content


def clean_and_parse_llm_response(report_text: str) -> tuple[str, str]:
    """LLMの応答テキストから markdown_report と spoken_summary を安全に抽出する"""
    clean_text = report_text.strip() if report_text else ""
    if not clean_text:
        return "", "報告書が完成しました。"

    # ステップ1: テキスト全体の直接JSONパース試行
    try:
        result_json = json.loads(clean_text)
        if isinstance(result_json, dict):
            markdown_content = result_json.get("markdown_report", clean_text)
            spoken_summary = result_json.get("spoken_summary", "報告書が完成しました。")
            return markdown_content, spoken_summary
    except Exception:
        pass

    # ステップ2: マークダウンコードブロック内のJSON抽出試行
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
    if code_block_match:
        block_inner = code_block_match.group(1).strip()
        try:
            result_json = json.loads(block_inner)
            if isinstance(result_json, dict):
                markdown_content = result_json.get("markdown_report", clean_text)
                spoken_summary = result_json.get("spoken_summary", "報告書が完成しました。")
                return markdown_content, spoken_summary
        except Exception:
            pass

    # ステップ3: 最外郭の中括弧からのJSON抽出試行
    bracket_match = re.search(r"(\{[\s\S]*\})", clean_text)
    if bracket_match:
        bracket_inner = bracket_match.group(1).strip()
        try:
            result_json = json.loads(bracket_inner)
            if isinstance(result_json, dict):
                markdown_content = result_json.get("markdown_report", clean_text)
                spoken_summary = result_json.get("spoken_summary", "報告書が完成しました。")
                return markdown_content, spoken_summary
        except Exception:
            pass

    # ステップ4: サニタイズ要約フォールバック
    markdown_content = clean_text
    sanitized = re.sub(r"```[\s\S]*?```", "", clean_text)
    sanitized = re.sub(r"[#*`>{}\[\]\(\)]", " ", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    if sanitized:
        preview = sanitized[:80]
        period_pos = preview.rfind("。")
        if period_pos > 20:
            preview = preview[:period_pos + 1]
        spoken_summary = f"報告書が完成しました。{preview}"
    else:
        spoken_summary = "報告書が完成しました。"

    return markdown_content, spoken_summary


def recover_stale_processing_files(timeout_seconds: int = 300) -> int:
    """タイムアウトした孤立 .processing ファイルを検知して復旧し、古い残留 .tmp ファイルを清掃する"""
    now = time.time()
    recovered_count = 0
    for proc_file in glob.glob(os.path.join(REQUESTS_DIR, "*.processing")):
        try:
            if now - os.path.getmtime(proc_file) > timeout_seconds:
                orig_file = proc_file[:-11]  # 末尾の .processing を除去
                os.replace(proc_file, orig_file)
                print(f"孤立した処理中ファイルを復旧しました: {proc_file} -> {orig_file}")
                recovered_count += 1
        except OSError as e:
            print(f"ファイル復旧エラー ({proc_file}): {e}")

    # クラッシュや中断で放置された古い .tmp ファイルの清掃
    for tmp_file in glob.glob(os.path.join(REQUESTS_DIR, "*.tmp")):
        try:
            if now - os.path.getmtime(tmp_file) > 120:
                os.remove(tmp_file)
                print(f"放置された一時ファイルを整理しました: {tmp_file}")
        except OSError:
            pass

    return recovered_count


def cold_start_recovery() -> int:
    """起動時に残留している .processing ファイルを即座に復元する"""
    recovered_count = 0
    for proc_file in glob.glob(os.path.join(REQUESTS_DIR, "*.processing")):
        try:
            orig_file = proc_file[:-11]
            os.replace(proc_file, orig_file)
            print(f"コールドスタート復元を実行しました: {proc_file} -> {orig_file}")
            recovered_count += 1
        except OSError as e:
            print(f"コールドスタート復元エラー ({proc_file}): {e}")
    return recovered_count


async def _process_queue_with_agent(agent) -> int:
    """エージェントインスタンスを使用してキュー内のファイルを一括処理する"""
    req_files = glob.glob(os.path.join(REQUESTS_DIR, "*.json")) + glob.glob(os.path.join(REQUESTS_DIR, "*.txt"))
    # 一時ファイル、処理中ファイル、エラー隔離ファイルを除外
    req_files = [
        f for f in req_files
        if not f.endswith(".tmp")
        and not f.endswith(".processing")
        and not f.endswith(".error")
        and not f.endswith(".failed")
    ]
    # FIFO順（先入れ先出し）を保証するため作成時刻順にソート
    req_files.sort(key=lambda f: (os.path.getmtime(f), f))

    if not req_files:
        return 0

    count = 0
    for req_file in req_files:
        processing_file = req_file + ".processing"
        try:
            os.rename(req_file, processing_file)
        except OSError:
            # 他プロセスとの競合やファイル削除時はスキップ
            continue

        try:
            with open(processing_file, "r", encoding="utf-8") as f:
                content = f.read()

            query = extract_prompt_from_content(processing_file, content)

            # キュー詰まり防止のため180秒のタイムアウトを設定、モデル障害時はフォールバックを試行
            try:
                response = await asyncio.wait_for(agent.chat(query), timeout=180.0)
            except Exception as primary_err:
                # テスト用のモックオブジェクトやAPIキー未設定時は再送出
                if not hasattr(agent, '_config') or not api_key:
                    raise primary_err
                print(f"Primary model failed ({primary_err}). Attempting fallback model...")
                fallback_models = ["gemini-flash-lite-latest", "gemini-2.5-flash"]
                success_fb = False
                for fb_model in fallback_models:
                    if fb_model == getattr(getattr(agent, '_config', None), 'model', None):
                        continue
                    try:
                        print(f"Trying fallback model: {fb_model}")
                        fb_config = LocalAgentConfig(
                            api_key=api_key,
                            system_instructions=worker_config.system_instructions,
                            model=fb_model,
                            capabilities=CapabilitiesConfig(enabled_tools=["search_web", "read_url_content"])
                        )
                        async with Agent(fb_config) as fb_agent:
                            response = await asyncio.wait_for(fb_agent.chat(query), timeout=180.0)
                            success_fb = True
                            break
                    except Exception as fb_err:
                        print(f"Fallback model {fb_model} failed: {fb_err}")
                if not success_fb:
                    raise primary_err

            if hasattr(response, 'text'):
                if callable(response.text):
                    res_text = response.text()
                    if asyncio.iscoroutine(res_text):
                        report_text = await res_text
                    else:
                        report_text = res_text
                else:
                    report_text = response.text
            else:
                report_text = str(response)

            markdown_content, spoken_summary = clean_and_parse_llm_response(report_text)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            basename = os.path.basename(req_file).replace(".json", "").replace(".txt", "")

            # Frontmatter付きマークダウン本文の構築（ダブルクォートエスケープ対応）
            safe_summary = json.dumps(spoken_summary, ensure_ascii=False)
            full_markdown = (
                f"---\n"
                f"request_id: {basename}\n"
                f"timestamp: {timestamp}\n"
                f"spoken_summary: {safe_summary}\n"
                f"---\n\n"
                f"{markdown_content}\n"
            )

            # アトミック書き込みによる音声要約JSON生成（クライアントポーリングの整合性のためJSONを先に出力）
            report_json_filename = f"report_{timestamp}_{basename}.json"
            report_json_path = os.path.join(REPORTS_DIR, report_json_filename)
            temp_json_path = report_json_path + ".tmp"
            json_payload = {
                "request_id": basename,
                "timestamp": timestamp,
                "spoken_summary": spoken_summary,
            }
            with open(temp_json_path, "w", encoding="utf-8") as f:
                json.dump(json_payload, f, ensure_ascii=False, indent=2)
            os.replace(temp_json_path, report_json_path)

            # アトミック書き込みによるマークダウンレポート生成
            report_md_filename = f"report_{timestamp}_{basename}.md"
            report_md_path = os.path.join(REPORTS_DIR, report_md_filename)
            temp_md_path = report_md_path + ".tmp"
            with open(temp_md_path, "w", encoding="utf-8") as f:
                f.write(full_markdown)
            os.replace(temp_md_path, report_md_path)

            print(f"Generated reports: {report_md_path} and {report_json_path}")

            # 処理完了によりリクエストファイルを削除
            if os.path.exists(processing_file):
                os.remove(processing_file)

            count += 1
            gc.collect()

        except Exception as e:
            print(f"Error processing {req_file}: {e}")
            try:
                if os.path.exists(processing_file):
                    os.replace(processing_file, processing_file + ".error")
            except OSError as rename_err:
                print(f"エラーファイル隔離失敗 ({processing_file}): {rename_err}")

    return count


async def run_worker_once(agent=None) -> int:
    """
    単一サイクルのキュー処理を実行する。
    agent が渡された場合はそれを再利用し、None の場合は関数内で Agent を自動初期化してクリーンアップする。
    """
    if agent is None:
        async with Agent(worker_config) as managed_agent:
            return await _process_queue_with_agent(managed_agent)
    else:
        return await _process_queue_with_agent(agent)


async def run_worker():
    """バックグラウンド常駐ループ。アダプティブ・ポーリングとリソース管理を実行する。"""
    print(f"J.A.R.V.I.S. Worker started. Monitoring {REQUESTS_DIR}")

    # 起動時の孤立ファイル復旧
    cold_start_recovery()

    fast_interval = 0.1
    idle_interval = 2.0
    error_base_interval = 5.0
    max_error_interval = 30.0
    consecutive_errors = 0
    total_processed = 0

    while True:
        try:
            async with Agent(worker_config) as agent:
                while True:
                    recover_stale_processing_files()
                    processed = await run_worker_once(agent)

                    if processed > 0:
                        consecutive_errors = 0
                        total_processed += processed
                        print(f"Processed {processed} tasks (Total: {total_processed}).")
                        # 5タスク処理ごとにエージェントセッションを刷新して履歴蓄積を防止
                        if total_processed % 5 == 0:
                            break
                        await asyncio.sleep(fast_interval)
                    else:
                        consecutive_errors = 0
                        await asyncio.sleep(idle_interval)

        except Exception as e:
            consecutive_errors += 1
            backoff_time = min(error_base_interval * (2 ** (consecutive_errors - 1)), max_error_interval)
            print(f"Worker loop error ({consecutive_errors} consecutive): {e}. Backing off for {backoff_time:.1f}s")
            await asyncio.sleep(backoff_time)


if __name__ == "__main__":
    asyncio.run(run_worker())
