import asyncio
import glob
import inspect
import json
import os
import shutil
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# プロジェクトルートのパス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
REQUESTS_DIR = os.path.join(WORKSPACE_DIR, "requests")
REPORTS_DIR = os.path.join(WORKSPACE_DIR, "reports")

# アプリケーションおよびワーカーモジュールのインポート
try:
    import main
except ImportError:
    main = None

try:
    import worker
except ImportError:
    worker = None


class TestFileDropQueue(unittest.TestCase):
    """
    File-Drop Message Queue 受入および堅牢化テストスイート
    J.A.R.V.I.S. アーキテクチャ分離の妥当性、境界値耐性、例外リカバリを網羅的に検証する。
    """

    @classmethod
    def setUpClass(cls):
        """テスト実行前のディレクトリ初期化"""
        os.makedirs(REQUESTS_DIR, exist_ok=True)
        os.makedirs(REPORTS_DIR, exist_ok=True)

    def setUp(self):
        """各テストケース実行前のセットアップ"""
        self.created_test_files = []
        self._cleanup_test_artifacts()

    def tearDown(self):
        """各テストケース実行後のクリーンアップ"""
        self._cleanup_test_artifacts()

    def _cleanup_test_artifacts(self):
        """テスト用の成果物・リクエストファイルの確実なクリーンアップ"""
        for path in self.created_test_files:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

        if os.path.exists(REQUESTS_DIR):
            for pattern in ["test_*", "req_test_*", "*.tmp", "*.processing", "*.error", "*.failed"]:
                for filepath in glob.glob(os.path.join(REQUESTS_DIR, pattern)):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

        if os.path.exists(REPORTS_DIR):
            for pattern in [
                "test_report_*",
                "report_*test_*",
                "*corrupted*",
                "*empty*",
                "*missing*",
                "*fail*",
                "*succ*",
                "*explicit*",
            ]:
                for filepath in glob.glob(os.path.join(REPORTS_DIR, pattern)):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

    def _create_mock_agent(self, markdown_text="# テストレポート\n急性期の対応手順です。"):
        """モックエージェントを生成するヘルパー"""
        mock_response = AsyncMock()
        mock_response.text = AsyncMock(return_value=markdown_text)

        mock_agent_instance = AsyncMock()
        mock_agent_instance.chat = AsyncMock(return_value=mock_response)
        mock_agent_instance.__aenter__.return_value = mock_agent_instance
        mock_agent_instance.__aexit__.return_value = None
        return mock_agent_instance

    def _execute_worker_task(self, req_path=None, mock_agent=None, force_pass_agent=False):
        """
        worker.py のインターフェースに応じたタスク実行ヘルパー。
        force_pass_agent=True の場合は明示的に agent を渡す。
        """
        if hasattr(worker, "run_worker_once"):
            func = worker.run_worker_once
            if force_pass_agent and mock_agent is not None:
                res = func(agent=mock_agent)
            else:
                res = func()
            if asyncio.iscoroutine(res):
                return asyncio.run(res)
            return res
        elif hasattr(worker, "process_task"):
            func = worker.process_task
            sig = inspect.signature(func)
            if len(sig.parameters) >= 2:
                agent = mock_agent if mock_agent is not None else getattr(worker, "agent", None)
                res = func(agent, req_path)
            else:
                res = func(req_path)
            if asyncio.iscoroutine(res):
                return asyncio.run(res)
            return res
        elif hasattr(worker, "process_request"):
            func = worker.process_request
            res = func(req_path)
            if asyncio.iscoroutine(res):
                return asyncio.run(res)
            return res
        else:
            self.fail("worker.py に適切なタスク実行関数が定義されていません")

    # -------------------------------------------------------------------------
    # シナリオ 1: ユーザーリクエスト投入シミュレーション
    # -------------------------------------------------------------------------
    def test_simulate_user_request_drop(self):
        """ユーザーリクエストの投入とアトミック配置の検証"""
        request_id = f"test_{int(time.time() * 1000)}"
        timestamp_str = datetime.now(timezone.utc).isoformat()
        target_filename = f"req_{int(time.time())}_{request_id}.json"
        target_path = os.path.join(REQUESTS_DIR, target_filename)
        temp_path = f"{target_path}.tmp"

        self.created_test_files.extend([target_path, temp_path])

        request_data = {
            "request_id": request_id,
            "timestamp": timestamp_str,
            "prompt": "最新の臨床AI診断アシスタントの動向について調査してください。",
            "username": "admin",
            "status": "pending",
        }

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(request_data, f, ensure_ascii=False, indent=2)

        self.assertTrue(os.path.exists(temp_path), "一時ファイルが存在すること")
        self.assertFalse(os.path.exists(target_path), "リネーム前はターゲットファイルが存在しないこと")

        os.replace(temp_path, target_path)

        self.assertFalse(os.path.exists(temp_path), "リネーム後に一時ファイルが残っていないこと")
        self.assertTrue(os.path.exists(target_path), "アトミック配置後にターゲットファイルが存在すること")

        with open(target_path, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)

        self.assertEqual(loaded_data["request_id"], request_id)
        self.assertEqual(loaded_data["timestamp"], timestamp_str)
        self.assertEqual(loaded_data["prompt"], "最新の臨床AI診断アシスタントの動向について調査してください。")
        self.assertEqual(loaded_data["username"], "admin")
        self.assertEqual(loaded_data["status"], "pending")

        # TXTファイルの検証
        txt_filename = f"req_{int(time.time())}_{request_id}.txt"
        txt_path = os.path.join(REQUESTS_DIR, txt_filename)
        self.created_test_files.append(txt_path)
        txt_prompt = "救急医療におけるトリアージ支援プロトコルの概要をまとめてください。"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(txt_prompt)

        self.assertTrue(os.path.exists(txt_path), "TXTリクエストファイルが正しく配置されること")
        with open(txt_path, "r", encoding="utf-8") as f:
            read_prompt = f.read().strip()

        self.assertEqual(read_prompt, txt_prompt, "TXTファイルからプロンプトがUTF-8で正しく読み出せること")

    # -------------------------------------------------------------------------
    # シナリオ 2: ワーカーの検知・タスク処理・成果物出力・クリーンアップ
    # -------------------------------------------------------------------------
    def test_worker_detects_processes_and_cleans_up(self):
        """ワーカーの検知、プロンプト抽出、レポート出力、Frontmatter+JSON検証、クリーンアップの検証"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        req_id = f"test_worker_{int(time.time() * 1000)}"
        req_filename = f"req_test_{int(time.time())}_{req_id}.json"
        req_path = os.path.join(REQUESTS_DIR, req_filename)
        self.created_test_files.append(req_path)

        mock_prompt = "心不全急性期のガイドライン要約"
        request_payload = {
            "request_id": req_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": mock_prompt,
            "username": "admin",
            "status": "pending",
        }

        with open(req_path, "w", encoding="utf-8") as f:
            json.dump(request_payload, f, ensure_ascii=False)

        use_live_api = os.environ.get("USE_LIVE_API", "").lower() == "true" and bool(
            os.environ.get("GEMINI_API_KEY")
        )

        expected_markdown = (
            "# 心不全急性期 ガイドライン調査レポート\n\n"
            "## 概要\n急性心不全の初期対応プロトコルです。\n"
        )

        before_reports = set(os.listdir(REPORTS_DIR)) if os.path.exists(REPORTS_DIR) else set()

        if use_live_api:
            self._execute_worker_task(req_path)
        else:
            mock_agent_instance = self._create_mock_agent(expected_markdown)
            with patch("worker.Agent", return_value=mock_agent_instance):
                self._execute_worker_task(req_path, mock_agent=mock_agent_instance)

            # プロンプトが正しく抽出され、生JSONではなくプロンプト単体が渡されたことを検証
            mock_agent_instance.chat.assert_called_once_with(mock_prompt)

        # 元ファイルがクリーンアップされていること
        self.assertFalse(os.path.exists(req_path), "処理完了後にリクエストファイルが削除されること")

        after_reports = set(os.listdir(REPORTS_DIR)) if os.path.exists(REPORTS_DIR) else set()
        new_reports = after_reports - before_reports
        md_reports = [f for f in new_reports if f.endswith(".md")]
        json_reports = [f for f in new_reports if f.endswith(".json")]

        self.assertTrue(len(md_reports) > 0, "マークダウンレポートが生成されること")
        self.assertTrue(len(json_reports) > 0, "音声要約JSONが生成されること")

        generated_report_path = os.path.join(REPORTS_DIR, md_reports[0])
        self.created_test_files.append(generated_report_path)

        with open(generated_report_path, "r", encoding="utf-8") as f:
            report_content = f.read()

        self.assertTrue(len(report_content.strip()) > 0)
        # Frontmatterの検証
        self.assertIn("---", report_content)
        self.assertIn("spoken_summary:", report_content)

        if not use_live_api:
            self.assertIn("心不全急性期", report_content)

        # JSON側の検証
        generated_json_path = os.path.join(REPORTS_DIR, json_reports[0])
        self.created_test_files.append(generated_json_path)
        with open(generated_json_path, "r", encoding="utf-8") as jf:
            json_data = json.load(jf)
            self.assertIn("spoken_summary", json_data)
            self.assertIn("request_id", json_data)

    # -------------------------------------------------------------------------
    # シナリオ 3: バックエンド受付の非ブロッキング書き込み
    # -------------------------------------------------------------------------
    def test_main_backend_non_blocking_write(self):
        """main.py の非ブロッキングキュー書き込み検証"""
        if main is None:
            self.fail("main.py をインポートできませんでした。")

        client = TestClient(main.app)
        before_files = set(os.listdir(REQUESTS_DIR)) if os.path.exists(REQUESTS_DIR) else set()

        test_message = "抗不整脈薬の分類と適応に関するクイックリサーチ"
        start_time = time.time()

        response = client.post(
            "/api/chat",
            json={"message": test_message},
            auth=("admin", "password123"),
        )
        elapsed_time = time.time() - start_time

        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed_time, 3.0, "レスポンスは3秒未満で即時返却されること")

        after_files = set(os.listdir(REQUESTS_DIR)) if os.path.exists(REQUESTS_DIR) else set()
        new_files = after_files - before_files
        queue_files = [f for f in new_files if f.endswith(".json") or f.endswith(".txt")]

        self.assertTrue(len(queue_files) > 0, "workspace/requests/ にキューファイルが生成されること")
        created_file_path = os.path.join(REQUESTS_DIR, queue_files[0])
        self.created_test_files.append(created_file_path)

        with open(created_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("prompt", data)
        self.assertEqual(data["prompt"], test_message)
        self.assertEqual(data.get("username"), "admin")
        self.assertEqual(data.get("status"), "pending")

    # -------------------------------------------------------------------------
    # シナリオ 4: Deliverables Viewer レポート取得エンドポイント
    # -------------------------------------------------------------------------
    def test_deliverables_viewer_reports_endpoint(self):
        """GET /api/latest_report による最新レポート取得の検証"""
        if main is None:
            self.fail("main.py をインポートできませんでした。")

        client = TestClient(main.app)

        old_report_name = f"test_report_old_{int(time.time())}.md"
        new_report_name = f"test_report_new_{int(time.time())}.md"
        old_report_path = os.path.join(REPORTS_DIR, old_report_name)
        new_report_path = os.path.join(REPORTS_DIR, new_report_name)

        self.created_test_files.extend([old_report_path, new_report_path])

        old_content = "# 過去のレポート\nこれは古いレポートデータです。"
        new_content = "# 最新の臨床調査レポート\n最新のAIガイドラインの分析結果です。"

        with open(old_report_path, "w", encoding="utf-8") as f:
            f.write(old_content)
        past_time = time.time() - 100
        os.utime(old_report_path, (past_time, past_time))

        with open(new_report_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        current_time = time.time()
        os.utime(new_report_path, (current_time, current_time))

        response = client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["filename"], new_report_name)
        self.assertEqual(data["content"], new_content)

        # 認証エラーの検証
        unauth_response = client.get("/api/latest_report")
        self.assertEqual(unauth_response.status_code, 401)

    # -------------------------------------------------------------------------
    # シナリオ 5: 破損JSONの隔離耐性検証
    # -------------------------------------------------------------------------
    def test_worker_handles_corrupted_json(self):
        """構文破損したJSONファイルが投入された際、プロセスが停止せず.errorへ隔離されること"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        bad_req_path = os.path.join(REQUESTS_DIR, f"test_corrupted_{int(time.time())}.json")
        self.created_test_files.append(bad_req_path)

        with open(bad_req_path, "w", encoding="utf-8") as f:
            f.write('{"request_id": "bad", "prompt": "途中で途切れた構文')

        mock_agent_instance = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent_instance):
            self._execute_worker_task(mock_agent=mock_agent_instance)

        # 破損ファイルに対してLLM呼び出しは発生しないこと
        mock_agent_instance.chat.assert_not_called()

        # 元のファイルは残らず、.error に隔離されていること
        self.assertFalse(os.path.exists(bad_req_path))
        error_files = glob.glob(os.path.join(REQUESTS_DIR, f"*{os.path.basename(bad_req_path)}*.error"))
        self.assertTrue(len(error_files) > 0, "破損ファイルが .error として隔離されていること")
        for ef in error_files:
            self.created_test_files.append(ef)

    # -------------------------------------------------------------------------
    # シナリオ 6: 空ファイルおよび空白ファイルの耐性検証
    # -------------------------------------------------------------------------
    def test_worker_handles_empty_and_whitespace_requests(self):
        """0バイト空ファイルおよび空白のみファイルが投入された際、LLMを呼ばずに隔離されること"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        empty_path = os.path.join(REQUESTS_DIR, f"test_empty_{int(time.time())}.json")
        ws_path = os.path.join(REQUESTS_DIR, f"test_whitespace_{int(time.time())}.txt")
        self.created_test_files.extend([empty_path, ws_path])

        with open(empty_path, "w", encoding="utf-8") as f:
            f.write("")
        with open(ws_path, "w", encoding="utf-8") as f:
            f.write("   \n\t  ")

        mock_agent_instance = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent_instance):
            self._execute_worker_task(mock_agent=mock_agent_instance)

        # 空リクエストに対してLLM呼び出しは発生しないこと
        mock_agent_instance.chat.assert_not_called()
        self.assertFalse(os.path.exists(empty_path))
        self.assertFalse(os.path.exists(ws_path))

        # .error に隔離されたファイルのクリーンアップ登録
        for p in [empty_path, ws_path]:
            for ef in glob.glob(os.path.join(REQUESTS_DIR, f"*{os.path.basename(p)}*.error")):
                self.created_test_files.append(ef)

    # -------------------------------------------------------------------------
    # シナリオ 7: キー欠落JSONファイルの耐性検証
    # -------------------------------------------------------------------------
    def test_worker_handles_missing_keys_json(self):
        """promptもqueryも含まれないJSONが投入された際、LLMを呼ばずに隔離されること"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        missing_path = os.path.join(REQUESTS_DIR, f"test_missing_{int(time.time())}.json")
        self.created_test_files.append(missing_path)

        with open(missing_path, "w", encoding="utf-8") as f:
            json.dump({"request_id": "test_missing", "username": "admin", "other_key": 123}, f)

        mock_agent_instance = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent_instance):
            self._execute_worker_task(mock_agent=mock_agent_instance)

        mock_agent_instance.chat.assert_not_called()
        self.assertFalse(os.path.exists(missing_path))

        error_files = glob.glob(os.path.join(REQUESTS_DIR, f"*{os.path.basename(missing_path)}*.error"))
        self.assertTrue(len(error_files) > 0, "キー欠落JSONが .error として隔離されていること")
        for ef in error_files:
            self.created_test_files.append(ef)

    # -------------------------------------------------------------------------
    # シナリオ 8: キー互換性と優先順位の検証
    # -------------------------------------------------------------------------
    def test_worker_prompt_key_compatibility_and_priority(self):
        """promptキー優先、queryキーフォールバックが正しく動作すること"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        # 1. query キーのみの旧形式
        query_path = os.path.join(REQUESTS_DIR, f"test_query_only_{int(time.time())}.json")
        self.created_test_files.append(query_path)
        with open(query_path, "w", encoding="utf-8") as f:
            json.dump({"query": "旧式クエリのリサーチ依頼"}, f, ensure_ascii=False)

        mock_agent1 = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent1):
            self._execute_worker_task(mock_agent=mock_agent1)
        mock_agent1.chat.assert_called_once_with("旧式クエリのリサーチ依頼")

        # 2. prompt と query が両方存在する場合（prompt 優先）
        both_path = os.path.join(REQUESTS_DIR, f"test_both_keys_{int(time.time())}.json")
        self.created_test_files.append(both_path)
        with open(both_path, "w", encoding="utf-8") as f:
            json.dump({"prompt": "新仕様プロンプト優先", "query": "旧式クエリ"}, f, ensure_ascii=False)

        mock_agent2 = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent2):
            self._execute_worker_task(mock_agent=mock_agent2)
        mock_agent2.chat.assert_called_once_with("新仕様プロンプト優先")

    # -------------------------------------------------------------------------
    # シナリオ 9: LLM API例外発生時のリカバリ検証
    # -------------------------------------------------------------------------
    def test_worker_recovers_from_llm_exception(self):
        """LLM呼び出しで例外が発生してもプロセスが落ちず、後続タスクを継続できること"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        fail_path = os.path.join(REQUESTS_DIR, f"test_fail_req_{int(time.time())}.json")
        succ_path = os.path.join(REQUESTS_DIR, f"test_succ_req_{int(time.time())}.json")
        self.created_test_files.extend([fail_path, succ_path])

        with open(fail_path, "w", encoding="utf-8") as f:
            json.dump({"prompt": "失敗するリクエスト内容"}, f, ensure_ascii=False)
        with open(succ_path, "w", encoding="utf-8") as f:
            json.dump({"prompt": "成功するリクエスト内容"}, f, ensure_ascii=False)

        mock_resp = AsyncMock()
        mock_resp.text = AsyncMock(return_value="# 成功レポート本文")

        async def dynamic_chat(query):
            if "失敗" in query:
                raise RuntimeError("API Quota Exceeded")
            return mock_resp

        mock_agent_instance = AsyncMock()
        mock_agent_instance.chat = AsyncMock(side_effect=dynamic_chat)
        mock_agent_instance.__aenter__.return_value = mock_agent_instance
        mock_agent_instance.__aexit__.return_value = None

        with patch("worker.Agent", return_value=mock_agent_instance):
            self._execute_worker_task(mock_agent=mock_agent_instance)

        # 失敗リクエストは .error に退避されること
        self.assertFalse(os.path.exists(fail_path))
        error_files = glob.glob(os.path.join(REQUESTS_DIR, f"*{os.path.basename(fail_path)}*.error"))
        self.assertTrue(len(error_files) > 0)
        for ef in error_files:
            self.created_test_files.append(ef)

        # 成功リクエストは削除（クリーンアップ）されること
        self.assertFalse(os.path.exists(succ_path))

    # -------------------------------------------------------------------------
    # シナリオ 10: run_worker_once の引数明示渡しモード検証
    # -------------------------------------------------------------------------
    def test_run_worker_once_with_explicit_agent(self):
        """run_worker_once(agent=mock_agent) で明示的に渡されたエージェントを使用できること"""
        if worker is None or not hasattr(worker, "run_worker_once"):
            self.skipTest("worker.run_worker_once が存在しません")

        req_path = os.path.join(REQUESTS_DIR, f"test_explicit_{int(time.time())}.json")
        self.created_test_files.append(req_path)
        with open(req_path, "w", encoding="utf-8") as f:
            json.dump({"prompt": "引数明示テスト"}, f, ensure_ascii=False)

        mock_agent = self._create_mock_agent("# 明示エージェント結果")
        self._execute_worker_task(mock_agent=mock_agent, force_pass_agent=True)

        mock_agent.chat.assert_called_once_with("引数明示テスト")
        self.assertFalse(os.path.exists(req_path))

    # -------------------------------------------------------------------------
    # シナリオ 11: 書き込み中一時ファイル（.tmp）の除外検証
    # -------------------------------------------------------------------------
    def test_worker_ignores_in_flight_temporary_files(self):
        """書き込み中の .tmp ファイルをワーカーが誤って処理しないこと"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        tmp_path = os.path.join(REQUESTS_DIR, f"test_in_flight_{int(time.time())}.json.tmp")
        self.created_test_files.append(tmp_path)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write('{"prompt": "書き込み中の不完全データ"')

        mock_agent = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent):
            self._execute_worker_task(mock_agent=mock_agent)

        mock_agent.chat.assert_not_called()
        self.assertTrue(os.path.exists(tmp_path), ".tmp ファイルはそのまま残ること")

    # -------------------------------------------------------------------------
    # シナリオ 12: コールドスタートおよび孤立ファイルの復元検証
    # -------------------------------------------------------------------------
    def test_worker_cold_start_and_stale_recovery(self):
        """残留 .processing ファイルが正常に元のリクエストファイルに復元されること"""
        if worker is None:
            self.skipTest("worker.py がインポートできません")

        # 1. cold_start_recovery の検証
        stale_file = os.path.join(REQUESTS_DIR, f"test_stale_{int(time.time())}.json.processing")
        self.created_test_files.append(stale_file)
        with open(stale_file, "w", encoding="utf-8") as f:
            f.write('{"prompt": "コールドスタート復旧対象"}')

        restored_file = stale_file[:-11]
        self.created_test_files.append(restored_file)

        recovered = worker.cold_start_recovery()
        self.assertGreaterEqual(recovered, 1)
        self.assertFalse(os.path.exists(stale_file))
        self.assertTrue(os.path.exists(restored_file))

        # 2. recover_stale_processing_files の検証 (タイムアウト時間超過)
        stale_proc = os.path.join(REQUESTS_DIR, f"test_timeout_{int(time.time())}.json.processing")
        self.created_test_files.append(stale_proc)
        with open(stale_proc, "w", encoding="utf-8") as f:
            f.write('{"prompt": "タイムアウト復旧対象"}')

        restored_timeout = stale_proc[:-11]
        self.created_test_files.append(restored_timeout)

        # mtime を過去400秒前に設定
        past_mtime = time.time() - 400
        os.utime(stale_proc, (past_mtime, past_mtime))

        recovered_stale = worker.recover_stale_processing_files(timeout_seconds=300)
        self.assertGreaterEqual(recovered_stale, 1)
        self.assertFalse(os.path.exists(stale_proc))
        self.assertTrue(os.path.exists(restored_timeout))


if __name__ == "__main__":
    unittest.main()
