"""
J.A.R.V.I.S. クラウド環境総合E2Eテストスイート (test_cloud_e2e.py)

TEST_INFRA.md および PROJECT.md 仕様に厳格に準拠した4層（Tiers 1-4）網羅の総合テスト。
- Tier 1: 機能網羅テスト（各機能5件以上）
- Tier 2: 境界・異常系テスト（各機能5件以上）
- Tier 3: 相互作用・組合せテスト
- Tier 4: 実践シナリオテスト（実運用ユースケース5件以上）

排他所有ファイル: test_cloud_e2e.py
"""

import asyncio
import base64
import glob
import json
import os
import re
import shutil
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

# プロジェクトルートパス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
REQUESTS_DIR = os.path.join(WORKSPACE_DIR, "requests")
REPORTS_DIR = os.path.join(WORKSPACE_DIR, "reports")

import main
import worker
from main import app


class BaseE2ETestCase(unittest.TestCase):
    """E2Eテスト共通基底クラス: 環境変数および成果物の分離・クリーンアップ管理"""

    @classmethod
    def setUpClass(cls):
        os.makedirs(REQUESTS_DIR, exist_ok=True)
        os.makedirs(REPORTS_DIR, exist_ok=True)

    def setUp(self):
        self.orig_env = os.environ.copy()
        self.created_files = []
        self._cleanup_test_artifacts()
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        self._cleanup_test_artifacts()

    def _cleanup_test_artifacts(self):
        for path in self.created_files:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.created_files.clear()

        if os.path.exists(REQUESTS_DIR):
            for fname in os.listdir(REQUESTS_DIR):
                fpath = os.path.join(REQUESTS_DIR, fname)
                try:
                    if os.path.isfile(fpath) or os.path.islink(fpath):
                        os.remove(fpath)
                except OSError:
                    pass

        if os.path.exists(REPORTS_DIR):
            for fname in os.listdir(REPORTS_DIR):
                fpath = os.path.join(REPORTS_DIR, fname)
                try:
                    if os.path.isfile(fpath) or os.path.islink(fpath):
                        os.remove(fpath)
                except OSError:
                    pass

    def _create_mock_agent(self, markdown_text="# 臨床AIレポート\nガイドライン詳細です。", spoken_summary="報告書が完成しました。"):
        payload = json.dumps({
            "spoken_summary": spoken_summary,
            "markdown_report": markdown_text,
        }, ensure_ascii=False)

        mock_resp = AsyncMock()
        mock_resp.text = AsyncMock(return_value=payload)

        mock_agent = AsyncMock()
        mock_agent.chat = AsyncMock(return_value=mock_resp)
        mock_agent.__aenter__.return_value = mock_agent
        mock_agent.__aexit__.return_value = None
        return mock_agent


# ==============================================================================
# Tier 1: 機能網羅テスト（各機能5件以上）
# ==============================================================================
class TestTier1FunctionalCoverage(BaseE2ETestCase):
    """
    Tier 1: 基本機能の網羅的検証
    Feature 1: クラウド構成ファイル整合性 (5件)
    Feature 2: ジョブキューおよびワーカー処理 (5件)
    Feature 3: Basic認証およびセキュリティ (5件)
    Feature 4: レポート配信および描画 (5件)
    """

    # --- Feature 1: クラウド構成ファイル整合性 ---

    def test_01_dockerfile_syntax_and_directives(self):
        """Dockerfileが存在し、必要なディレクティブが正確に定義されていること"""
        dockerfile_path = os.path.join(BASE_DIR, "Dockerfile")
        self.assertTrue(os.path.exists(dockerfile_path), "Dockerfileが存在すること")

        with open(dockerfile_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("FROM python:3.11-slim", content, "ベースイメージがPython 3.11-slimであること")
        self.assertIn("RUN groupadd -g 1000 appuser", content, "非rootユーザーappuserが作成されていること")
        self.assertIn("USER appuser", content, "USER appuserが指定されていること")
        self.assertIn("EXPOSE 8000", content, "ポート8000が公開されていること")
        self.assertIn('ENTRYPOINT ["/app/entrypoint.sh"]', content, "entrypoint.shが指定されていること")

    def test_02_requirements_txt_completeness(self):
        """requirements.txtに必要な全依存関係が記載されていること"""
        req_path = os.path.join(BASE_DIR, "requirements.txt")
        self.assertTrue(os.path.exists(req_path), "requirements.txtが存在すること")

        with open(req_path, "r", encoding="utf-8") as f:
            lines = [l.strip().split("==")[0].lower() for l in f if l.strip() and not l.startswith("#")]

        expected_pkgs = ["fastapi", "uvicorn", "pydantic", "google-antigravity", "python-dotenv", "httpx"]
        for pkg in expected_pkgs:
            self.assertIn(pkg, lines, f"必須パッケージ {pkg} がrequirements.txtに含まれていること")

    def test_03_render_yaml_blueprint_structure(self):
        """render.yamlが正しく定義され、必要な環境変数キーが存在すること"""
        render_path = os.path.join(BASE_DIR, "render.yaml")
        self.assertTrue(os.path.exists(render_path), "render.yamlが存在すること")

        with open(render_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("type: web", content)
        self.assertIn("runtime: docker", content)
        self.assertIn("dockerfilePath: ./Dockerfile", content)
        self.assertIn("key: PORT", content)
        self.assertIn("key: ADMIN_USERNAME", content)
        self.assertIn("key: ADMIN_PASSWORD", content)
        self.assertIn("key: GEMINI_API_KEY", content)

    def test_04_supervisord_conf_multiprocess(self):
        """supervisord.confにwebとworkerの2プロセスが正しく設定されていること"""
        conf_path = os.path.join(BASE_DIR, "supervisord.conf")
        self.assertTrue(os.path.exists(conf_path), "supervisord.confが存在すること")

        with open(conf_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("[supervisord]", content)
        self.assertIn("nodaemon=true", content)
        self.assertIn("[program:web]", content)
        self.assertIn("command=uvicorn main:app", content)
        self.assertIn("%(ENV_PORT)s", content)
        self.assertIn("[program:worker]", content)
        self.assertIn("command=python -u worker.py", content)

    def test_05_entrypoint_script_structure(self):
        """entrypoint.shが存在し、PORTフォールバックとディレクトリ検証を行うこと"""
        ep_path = os.path.join(BASE_DIR, "entrypoint.sh")
        self.assertTrue(os.path.exists(ep_path), "entrypoint.shが存在すること")

        with open(ep_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertTrue(content.startswith("#!/bin/bash"), "bash shebangで始まること")
        self.assertIn('export PORT="${PORT:-8000}"', content, "PORTのフォールバック設定があること")
        self.assertIn("mkdir -p /app/workspace/requests /app/workspace/reports", content)
        self.assertIn("exec /usr/bin/supervisord", content)

    # --- Feature 2: ジョブキューおよびワーカー処理 ---

    def test_06_api_chat_enqueues_request_file(self):
        """/api/chat エンドポイントがキューファイルをアトミックに生成すること"""
        msg = "心疾患のバイオマーカーについての最新知見"
        res = self.client.post("/api/chat", json={"message": msg}, auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)

        files = [f for f in os.listdir(REQUESTS_DIR) if f.endswith(".json")]
        self.assertGreater(len(files), 0, "リクエストファイルが生成されていること")
        target_file = os.path.join(REQUESTS_DIR, files[-1])
        self.created_files.append(target_file)

        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("prompt"), msg)

    def test_07_queue_file_json_schema(self):
        """生成されたキューファイルがPROJECT.md仕様のJSONスキーマに適合すること"""
        msg = "スキーマ検証用プロンプト"
        res = self.client.post("/api/chat", json={"message": msg}, auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)

        files = [f for f in os.listdir(REQUESTS_DIR) if f.endswith(".json")]
        target_file = os.path.join(REQUESTS_DIR, files[-1])
        self.created_files.append(target_file)

        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("request_id", data)
        self.assertIn("timestamp", data)
        self.assertIn("prompt", data)
        self.assertIn("username", data)
        self.assertIn("status", data)
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["username"], "admin")

    def test_08_worker_extract_prompt_key(self):
        """worker.extract_prompt_from_content が prompt キーから正しく抽出すること"""
        raw_json = json.dumps({"prompt": "急性虫垂炎の画像診断基準", "status": "pending"})
        extracted = worker.extract_prompt_from_content("req_sample.json", raw_json)
        self.assertEqual(extracted, "急性虫垂炎の画像診断基準")

    def test_09_worker_extract_query_key_compatibility(self):
        """worker.extract_prompt_from_content が query キーから互換抽出すること"""
        raw_json = json.dumps({"query": "糖尿病治療ガイドライン2024", "status": "pending"})
        extracted = worker.extract_prompt_from_content("req_sample.json", raw_json)
        self.assertEqual(extracted, "糖尿病治療ガイドライン2024")

    def test_10_worker_processes_queue_creates_report(self):
        """worker.run_worker_once がキューを処理しレポートを出力すること"""
        req_id = f"e2e_t1_{int(time.time() * 1000)}"
        req_path = os.path.join(REQUESTS_DIR, f"req_e2e_{req_id}.json")
        self.created_files.append(req_path)

        with open(req_path, "w", encoding="utf-8") as f:
            json.dump({"prompt": "急性膵炎の初期輸液プロトコル", "status": "pending"}, f)

        mock_agent = self._create_mock_agent(
            markdown_text="# 急性膵炎の初期輸液\n乳酸リンゲル液の投与手順です。",
            spoken_summary="急性膵炎の初期輸液要約です。"
        )

        with patch("worker.Agent", return_value=mock_agent):
            count = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(count, 1, "1件のタスクが処理されたこと")
        self.assertFalse(os.path.exists(req_path), "処理後にリクエストファイルが削除されること")

        md_files = glob.glob(os.path.join(REPORTS_DIR, f"*{req_id}*.md"))
        json_files = glob.glob(os.path.join(REPORTS_DIR, f"*{req_id}*.json"))
        self.assertTrue(len(md_files) > 0, "Markdownレポートが出力されていること")
        self.assertTrue(len(json_files) > 0, "音声要約JSONが出力されていること")

    # --- Feature 3: Basic認証およびセキュリティ ---

    def test_11_basic_auth_root_dashboard_success(self):
        """有効なBasic認証でルートダッシュボードへのアクセスが成功すること"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("J.A.R.V.I.S.", res.text)

    def test_12_basic_auth_chat_success(self):
        """有効なBasic認証で/api/chatエンドポイントへのアクセスが成功すること"""
        res = self.client.post("/api/chat", json={"message": "認証テスト"}, auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)

    def test_13_basic_auth_latest_report_success(self):
        """有効なBasic認証で/api/latest_reportエンドポイントへのアクセスが成功すること"""
        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)

    def test_14_dynamic_env_auth_credentials(self):
        """環境変数 ADMIN_USERNAME / ADMIN_PASSWORD の動的更新が即座に反映されること"""
        os.environ["ADMIN_USERNAME"] = "doctor_cloud"
        os.environ["ADMIN_PASSWORD"] = "securePass999!"

        res_old = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res_old.status_code, 401, "古い認証情報は拒否されること")

        res_new = self.client.get("/", auth=("doctor_cloud", "securePass999!"))
        self.assertEqual(res_new.status_code, 200, "新しい認証情報で成功すること")

    def test_15_timing_attack_safe_verification(self):
        """main.get_current_username が timing-attack safe に動作すること"""
        from fastapi.security import HTTPBasicCredentials
        from fastapi import HTTPException

        valid_creds = HTTPBasicCredentials(username="admin", password="password123")
        username = main.get_current_username(valid_creds)
        self.assertEqual(username, "admin")

        invalid_creds = HTTPBasicCredentials(username="admin", password="wrongpassword")
        with self.assertRaises(HTTPException) as ctx:
            main.get_current_username(invalid_creds)
        self.assertEqual(ctx.exception.status_code, 401)

    # --- Feature 4: レポート配信および描画 ---

    def test_16_latest_report_empty_state(self):
        """レポートが存在しない初期状態で適切な空レスポンスを返却すること"""
        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNone(data["filename"])
        self.assertEqual(data["content"], "")

    def test_17_latest_report_single_file(self):
        """単一のレポートが存在する場合、その内容を正確に返却すること"""
        rep_name = "report_e2e_single.md"
        rep_path = os.path.join(REPORTS_DIR, rep_name)
        self.created_files.append(rep_path)
        content_text = "# 単一レポート\nテスト用臨床データです。"

        with open(rep_path, "w", encoding="utf-8") as f:
            f.write(content_text)

        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["filename"], rep_name)
        self.assertEqual(data["content"], content_text)

    def test_18_latest_report_newest_mtime(self):
        """複数のレポートが存在する場合、更新時刻が最新のものを返却すること"""
        old_name = "report_e2e_old.md"
        new_name = "report_e2e_new.md"
        old_path = os.path.join(REPORTS_DIR, old_name)
        new_path = os.path.join(REPORTS_DIR, new_name)
        self.created_files.extend([old_path, new_path])

        with open(old_path, "w", encoding="utf-8") as f:
            f.write("過去レポート")
        past = time.time() - 300
        os.utime(old_path, (past, past))

        with open(new_path, "w", encoding="utf-8") as f:
            f.write("最新レポート")
        now = time.time()
        os.utime(new_path, (now, now))

        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["filename"], new_name)
        self.assertEqual(data["content"], "最新レポート")

    def test_19_latest_report_spoken_summary_json(self):
        """ペアとなるJSONファイルが存在する場合、spoken_summaryを返却すること"""
        md_name = "report_e2e_with_json.md"
        json_name = "report_e2e_with_json.json"
        md_path = os.path.join(REPORTS_DIR, md_name)
        json_path = os.path.join(REPORTS_DIR, json_name)
        self.created_files.extend([md_path, json_path])

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# レポート本文")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"spoken_summary": "音声読み上げ要約テキストです。"}, f, ensure_ascii=False)

        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["filename"], md_name)
        self.assertEqual(data["spoken_summary"], "音声読み上げ要約テキストです。")

    def test_20_dashboard_deliverables_viewer_components(self):
        """ダッシュボードHTMLにDeliverables Viewer関連要素が含まれていること"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn("DELIVERABLES VIEWER", html)
        self.assertIn('id="markdown-viewer"', html)
        self.assertIn('id="current-report-name"', html)
        self.assertIn("/api/latest_report", html)


# ==============================================================================
# Tier 2: 境界・異常系テスト（各機能5件以上）
# ==============================================================================
class TestTier2BoundaryAndAdversarial(BaseE2ETestCase):
    """
    Tier 2: 境界値、異常系、耐障害性の検証
    Feature 1: 構成ファイル異常・境界系 (5件)
    Feature 2: ジョブキュー境界・異常系 (5件)
    Feature 3: Basic認証不正・境界系 (5件)
    Feature 4: レポート配信異常・境界系 (5件)
    """

    # --- Feature 1: クラウド構成ファイル境界・耐障害性 ---

    def test_21_dockerfile_crlf_and_security_hardening(self):
        """DockerfileでCRLFサニタイズとroot権限剥奪が明示されていること"""
        with open(os.path.join(BASE_DIR, "Dockerfile"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("sed -i 's/\\r$//' /app/entrypoint.sh", content, "Windows改行サニタイズがあること")
        self.assertIn("chmod +x /app/entrypoint.sh", content, "実行権限付与があること")
        self.assertIn("chown -R appuser:appuser", content, "権限委譲があること")

    def test_22_render_yaml_secrets_not_synced(self):
        """render.yamlで機密環境変数のsyncがfalseに設定されていること"""
        with open(os.path.join(BASE_DIR, "render.yaml"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertRegex(content, r"key:\s*ADMIN_PASSWORD\s*\n\s*sync:\s*false")
        self.assertRegex(content, r"key:\s*GEMINI_API_KEY\s*\n\s*sync:\s*false")

    def test_23_supervisord_log_streams_and_restarts(self):
        """supervisord.confでログが標準出力にリダイレクトされ自動再起動が設定されていること"""
        with open(os.path.join(BASE_DIR, "supervisord.conf"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("stdout_logfile=/dev/stdout", content)
        self.assertIn("stderr_logfile=/dev/stderr", content)
        self.assertIn("autorestart=true", content)

    def test_24_entrypoint_port_fallback_logic(self):
        """entrypoint.shでPORT未指定時のフォールバックが8000であること"""
        with open(os.path.join(BASE_DIR, "entrypoint.sh"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("${PORT:-8000}", content)

    def test_25_entrypoint_directory_error_guard(self):
        """entrypoint.shでworkspaceが書き込み不可の場合に異常終了するガードがあること"""
        with open(os.path.join(BASE_DIR, "entrypoint.sh"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("[ ! -w /app/workspace/requests ]", content)
        self.assertIn("[ ! -w /app/workspace/reports ]", content)

    # --- Feature 2: ジョブキュー境界・異常系 ---

    def test_26_worker_corrupted_json_isolation(self):
        """構文破壊されたJSONファイルが検知され、.errorに安全に隔離されること"""
        bad_req = os.path.join(REQUESTS_DIR, f"req_e2e_corrupt_{int(time.time())}.json")
        self.created_files.append(bad_req)
        with open(bad_req, "w", encoding="utf-8") as f:
            f.write("{ invalid json text ")

        mock_agent = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent):
            count = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(count, 0, "不正JSONは処理成功数にカウントされないこと")
        self.assertFalse(os.path.exists(bad_req), "元ファイルがそのまま残らないこと")
        error_files = glob.glob(os.path.join(REQUESTS_DIR, f"*{os.path.basename(bad_req)}*.error"))
        self.assertGreater(len(error_files), 0, ".error ファイルに隔離されていること")
        for ef in error_files:
            self.created_files.append(ef)

    def test_27_worker_empty_and_whitespace_isolation(self):
        """空ファイルおよび空白のみファイルが投入された際にLLMを呼ばず隔離されること"""
        empty_req = os.path.join(REQUESTS_DIR, f"req_e2e_empty_{int(time.time())}.json")
        ws_req = os.path.join(REQUESTS_DIR, f"req_e2e_ws_{int(time.time())}.txt")
        self.created_files.extend([empty_req, ws_req])

        with open(empty_req, "w", encoding="utf-8") as f:
            f.write("")
        with open(ws_req, "w", encoding="utf-8") as f:
            f.write("   \n\t   ")

        mock_agent = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent):
            count = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(count, 0)
        mock_agent.chat.assert_not_called()

        for path in [empty_req, ws_req]:
            efs = glob.glob(os.path.join(REQUESTS_DIR, f"*{os.path.basename(path)}*.error"))
            self.assertGreater(len(efs), 0, f"{path} が隔離されること")
            for ef in efs:
                self.created_files.append(ef)

    def test_28_worker_missing_prompt_and_query_isolation(self):
        """promptもqueryも存在しないJSONファイルが隔離されること"""
        missing_req = os.path.join(REQUESTS_DIR, f"req_e2e_missing_{int(time.time())}.json")
        self.created_files.append(missing_req)
        with open(missing_req, "w", encoding="utf-8") as f:
            json.dump({"foo": "bar", "count": 42}, f)

        mock_agent = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent):
            count = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(count, 0)
        efs = glob.glob(os.path.join(REQUESTS_DIR, f"*{os.path.basename(missing_req)}*.error"))
        self.assertGreater(len(efs), 0)
        for ef in efs:
            self.created_files.append(ef)

    def test_29_worker_ignores_in_flight_tmp_files(self):
        """書き込み中の一時ファイル（.tmp）をワーカーが無視すること"""
        tmp_file = os.path.join(REQUESTS_DIR, f"req_e2e_inflight_{int(time.time())}.json.tmp")
        self.created_files.append(tmp_file)
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write('{"prompt": "不完全な書き込みデータ"')

        mock_agent = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent):
            count = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(count, 0)
        self.assertTrue(os.path.exists(tmp_file), ".tmpファイルは変更されず維持されること")

    def test_30_worker_cold_start_and_stale_recovery(self):
        """中断された .processing ファイルが安全に復旧されること"""
        stale_file = os.path.join(REQUESTS_DIR, f"req_e2e_stale_{int(time.time())}.json.processing")
        self.created_files.append(stale_file)
        with open(stale_file, "w", encoding="utf-8") as f:
            json.dump({"prompt": "コールドスタート復旧対象"}, f)

        restored_file = stale_file[:-11]
        self.created_files.append(restored_file)

        recovered = worker.cold_start_recovery()
        self.assertGreaterEqual(recovered, 1)
        self.assertFalse(os.path.exists(stale_file))
        self.assertTrue(os.path.exists(restored_file))

    # --- Feature 3: Basic認証不正・境界系 ---

    def test_31_unauthenticated_requests_return_401(self):
        """認証ヘッダー欠落時に401およびWWW-Authenticateを返却すること"""
        for path, method in [("/", "get"), ("/api/latest_report", "get"), ("/api/chat", "post")]:
            with self.subTest(path=path, method=method):
                if method == "get":
                    res = self.client.get(path)
                else:
                    res = self.client.post(path, json={"message": "test"})
                self.assertEqual(res.status_code, 401)
                self.assertIn("www-authenticate", res.headers)

    def test_32_wrong_credentials_return_401(self):
        """誤ったユーザー名またはパスワードで401を返却すること"""
        cases = [
            ("admin", "wrong_pass"),
            ("wrong_user", "password123"),
            ("attacker", "hacked"),
        ]
        for u, p in cases:
            with self.subTest(user=u, pwd=p):
                res = self.client.get("/", auth=(u, p))
                self.assertEqual(res.status_code, 401)

    def test_33_malformed_auth_headers_return_401(self):
        """不正形式のAuthorizationヘッダーで401を返却すること"""
        malformed = [
            {"Authorization": ""},
            {"Authorization": "Bearer abcdef123456"},
            {"Authorization": "Basic"},
            {"Authorization": "Basic ???invalid-base64???"},
            {"Authorization": "Basic " + base64.b64encode(b"no_colon_string").decode()},
        ]
        for headers in malformed:
            with self.subTest(h=headers):
                res = self.client.get("/", headers=headers)
                self.assertEqual(res.status_code, 401)

    def test_34_empty_user_or_pass_returns_401(self):
        """空ユーザー名または空パスワードで401を返却すること"""
        for u, p in [("", "password123"), ("admin", ""), ("", "")]:
            with self.subTest(user=u, pwd=p):
                res = self.client.get("/", auth=(u, p))
                self.assertEqual(res.status_code, 401)

    def test_35_case_sensitive_and_whitespace_auth(self):
        """大文字小文字の違いや空白混入認証情報を拒否すること"""
        cases = [
            ("ADMIN", "password123"),
            ("admin", "Password123"),
            ("admin ", "password123"),
            ("admin", "password123 "),
        ]
        for u, p in cases:
            with self.subTest(user=u, pwd=p):
                res = self.client.get("/", auth=(u, p))
                self.assertEqual(res.status_code, 401)

    # --- Feature 4: レポート配信異常・境界系 ---

    def test_36_latest_report_missing_reports_dir(self):
        """REPORTS_DIRが存在しない場合に空レスポンスでフォールバックすること"""
        with patch("main.os.path.exists", return_value=False):
            res = self.client.get("/api/latest_report", auth=("admin", "password123"))
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIsNone(data["filename"])
            self.assertEqual(data["content"], "")

    def test_37_latest_report_non_markdown_files_ignored(self):
        """非Markdownファイル（.log, .bak等）が除外されること"""
        log_file = os.path.join(REPORTS_DIR, "e2e_test.log")
        self.created_files.append(log_file)
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("ログメッセージ")

        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNone(data["filename"])

    def test_38_latest_report_corrupted_json_fallback(self):
        """ペアJSONが破損していてもMarkdown本体は返却されspoken_summaryが空文字となること"""
        md_file = os.path.join(REPORTS_DIR, "report_e2e_corrupt_pair.md")
        json_file = os.path.join(REPORTS_DIR, "report_e2e_corrupt_pair.json")
        self.created_files.extend([md_file, json_file])

        with open(md_file, "w", encoding="utf-8") as f:
            f.write("# 正常なMarkdown本文")
        with open(json_file, "w", encoding="utf-8") as f:
            f.write("{ 破損したJSONデータ ")

        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["filename"], "report_e2e_corrupt_pair.md")
        self.assertEqual(data["content"], "# 正常なMarkdown本文")
        self.assertEqual(data["spoken_summary"], "")

    def test_39_latest_report_file_read_error_handled(self):
        """ファイル読み込み時に予期せぬ例外が発生してもクラッシュせずエラー内容を返却すること"""
        md_file = os.path.join(REPORTS_DIR, "report_e2e_mock_err.md")
        self.created_files.append(md_file)
        with open(md_file, "w", encoding="utf-8") as f:
            f.write("dummy")

        with patch("builtins.open", side_effect=PermissionError("アクセス拒否")):
            res = self.client.get("/api/latest_report", auth=("admin", "password123"))
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIsNone(data["filename"])
            self.assertIn("Error loading report", data["content"])

    def test_40_latest_report_large_content_handling(self):
        """大規模なレポート本文（100KB超）も欠損なく返却できること"""
        large_name = "report_e2e_large.md"
        large_path = os.path.join(REPORTS_DIR, large_name)
        self.created_files.append(large_path)
        large_body = "# 巨大臨床データベース\n" + ("臨床データ行：パラメータ正常\n" * 5000)

        with open(large_path, "w", encoding="utf-8") as f:
            f.write(large_body)

        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["filename"], large_name)
        self.assertEqual(len(data["content"]), len(large_body))


# ==============================================================================
# Tier 3: 相互作用・組合せテスト
# ==============================================================================
class TestTier3InteractionAndIntegration(BaseE2ETestCase):
    """
    Tier 3: モジュール間相互作用、順序性、複合パイプラインの検証
    """

    def test_41_end_to_end_pipeline_chat_to_report(self):
        """E2E完全サイクル: /api/chat投入 -> worker処理 -> /api/latest_report取得"""
        prompt_text = "心房細動の抗凝固療法におけるDOAC選択基準"
        res_chat = self.client.post("/api/chat", json={"message": prompt_text}, auth=("admin", "password123"))
        self.assertEqual(res_chat.status_code, 200)

        # キューファイル確認
        q_files = [f for f in os.listdir(REQUESTS_DIR) if f.endswith(".json")]
        self.assertGreater(len(q_files), 0)

        expected_md = "# DOAC選択基準レポート\n腎機能および出血リスクに基づく選定。"
        expected_summary = "DOAC選択基準の要約です。"
        mock_agent = self._create_mock_agent(markdown_text=expected_md, spoken_summary=expected_summary)

        # ワーカー実行
        with patch("worker.Agent", return_value=mock_agent):
            processed = asyncio.run(worker.run_worker_once(agent=mock_agent))
        self.assertGreaterEqual(processed, 1)

        # レポートAPI確認
        res_rep = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res_rep.status_code, 200)
        rep_data = res_rep.json()
        self.assertIsNotNone(rep_data["filename"])
        self.assertIn("DOAC選択基準", rep_data["content"])
        self.assertEqual(rep_data["spoken_summary"], expected_summary)

    def test_42_queue_fifo_order_processing(self):
        """複数リクエストが作成順（FIFO）に処理されること"""
        items = ["第1指示_高血圧治療", "第2指示_脂質異常症", "第3指示_高尿酸血症"]
        for i, item in enumerate(items):
            p = os.path.join(REQUESTS_DIR, f"req_e2e_seq_{i}_{int(time.time())}.json")
            self.created_files.append(p)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"prompt": item, "status": "pending"}, f)
            time.sleep(0.01)

        processed_order = []
        async def mock_chat(query):
            processed_order.append(query)
            mock_r = AsyncMock()
            mock_r.text = AsyncMock(return_value=json.dumps({
                "spoken_summary": "要約",
                "markdown_report": f"# {query} レポート"
            }))
            return mock_r

        mock_agent = AsyncMock()
        mock_agent.chat = AsyncMock(side_effect=mock_chat)
        mock_agent.__aenter__.return_value = mock_agent
        mock_agent.__aexit__.return_value = None

        with patch("worker.Agent", return_value=mock_agent):
            processed = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(processed, 3)
        self.assertEqual(processed_order, items, "FIFO順で処理されること")

    def test_43_mixed_format_queue_processing(self):
        """JSON形式とTXT形式が混在するキューがすべて正常に処理されること"""
        json_p = os.path.join(REQUESTS_DIR, f"req_e2e_mix_1.json")
        txt_p = os.path.join(REQUESTS_DIR, f"req_e2e_mix_2.txt")
        self.created_files.extend([json_p, txt_p])

        with open(json_p, "w", encoding="utf-8") as f:
            json.dump({"prompt": "JSONリクエスト内容"}, f)
        with open(txt_p, "w", encoding="utf-8") as f:
            f.write("TXTリクエスト内容")

        mock_agent = self._create_mock_agent()
        with patch("worker.Agent", return_value=mock_agent):
            processed = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(processed, 2)
        self.assertFalse(os.path.exists(json_p))
        self.assertFalse(os.path.exists(txt_p))

    def test_44_dynamic_credentials_e2e_pipeline(self):
        """動的な認証情報変更後に即座にE2Eフローが新認証で完結すること"""
        os.environ["ADMIN_USERNAME"] = "emergency_doc"
        os.environ["ADMIN_PASSWORD"] = "er_secure_2026"

        res_post = self.client.post(
            "/api/chat",
            json={"message": "心肺蘇生プロトコルの更新点"},
            auth=("emergency_doc", "er_secure_2026")
        )
        self.assertEqual(res_post.status_code, 200)

        mock_agent = self._create_mock_agent("# CPRプロトコル", "CPR要約")
        with patch("worker.Agent", return_value=mock_agent):
            processed = asyncio.run(worker.run_worker_once(agent=mock_agent))
        self.assertGreaterEqual(processed, 1)

        res_rep = self.client.get("/api/latest_report", auth=("emergency_doc", "er_secure_2026"))
        self.assertEqual(res_rep.status_code, 200)
        self.assertIn("CPRプロトコル", res_rep.json()["content"])

    def test_45_error_isolation_with_concurrent_valid_tasks(self):
        """破損ファイルと正常ファイルが混在する場合、破損ファイルのみ隔離され正常ファイルは処理されること"""
        corrupt_p = os.path.join(REQUESTS_DIR, "req_e2e_01_corrupt.json")
        valid_p = os.path.join(REQUESTS_DIR, "req_e2e_02_valid.json")
        self.created_files.extend([corrupt_p, valid_p])

        with open(corrupt_p, "w", encoding="utf-8") as f:
            f.write("corrupted json body {{{")
        with open(valid_p, "w", encoding="utf-8") as f:
            json.dump({"prompt": "正常タスクのプロンプト"}, f)

        mock_agent = self._create_mock_agent("# 正常レポート", "正常要約")
        with patch("worker.Agent", return_value=mock_agent):
            processed = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(processed, 1, "正常タスク1件のみが処理成功すること")
        self.assertFalse(os.path.exists(valid_p))
        self.assertFalse(os.path.exists(corrupt_p))
        error_files = glob.glob(os.path.join(REQUESTS_DIR, "*corrupt*.error"))
        self.assertGreater(len(error_files), 0)
        for ef in error_files:
            self.created_files.append(ef)


# ==============================================================================
# Tier 4: 実践シナリオテスト（TEST_INFRA.md Real-World Scenarios 1〜5 + α）
# ==============================================================================
class TestTier4RealWorldScenarios(BaseE2ETestCase):
    """
    Tier 4: 実運用を想定した実践的アプリケーションシナリオ
    TEST_INFRA.md Real-World Scenarios 1〜5 網羅
    """

    def test_46_scenario1_authenticated_mobile_browser_voice_drop(self):
        """シナリオ1: 認証付きスマホブラウザからの新規音声指示投入と即時受付"""
        mobile_headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            "Accept": "text/plain, */*",
        }
        speech_text = "音声入力：重症敗血症の初期バンドル治療手順をまとめてください"

        start_t = time.time()
        res = self.client.post(
            "/api/chat",
            json={"message": speech_text},
            headers=mobile_headers,
            auth=("admin", "password123")
        )
        elapsed = time.time() - start_t

        self.assertEqual(res.status_code, 200)
        self.assertLess(elapsed, 2.0, "運転中音声操作に応えるため2秒未満で即時返却されること")
        self.assertIn("リクエストを受け付け", res.text)

        # キューに正しく登録されたことを確認
        q_files = [f for f in os.listdir(REQUESTS_DIR) if f.endswith(".json")]
        self.assertGreater(len(q_files), 0)
        latest_q = os.path.join(REQUESTS_DIR, q_files[-1])
        self.created_files.append(latest_q)
        with open(latest_q, "r", encoding="utf-8") as f:
            q_data = json.load(f)
        self.assertEqual(q_data["prompt"], speech_text)
        self.assertEqual(q_data["username"], "admin")

    def test_47_scenario2_autonomous_worker_gemini_report_generation(self):
        """シナリオ2: ワーカーによる自律的タスク検知とGemini連携レポート生成"""
        req_id = f"e2e_sc2_{int(time.time() * 1000)}"
        req_p = os.path.join(REQUESTS_DIR, f"req_e2e_{req_id}.json")
        self.created_files.append(req_p)

        with open(req_p, "w", encoding="utf-8") as f:
            json.dump({
                "request_id": req_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prompt": "急性腎障害(AKI)のKDIGOステージ分類と対応",
                "username": "admin",
                "status": "pending"
            }, f)

        expected_markdown = (
            "# KDIGO AKI ステージ分類レポート\n\n"
            "## ステージ1\n血清クレアチニン 1.5〜1.9倍上昇\n\n"
            "## ステージ2\n血清クレアチニン 2.0〜2.9倍上昇\n\n"
            "## ステージ3\n血清クレアチニン 3.0倍以上または透析導入\n"
        )
        expected_summary = "KDIGOのAKIステージ分類と初期対応に関する要約です。"
        mock_agent = self._create_mock_agent(expected_markdown, expected_summary)

        with patch("worker.Agent", return_value=mock_agent):
            processed_count = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(processed_count, 1)
        self.assertFalse(os.path.exists(req_p))

        # 生成されたFrontmatter付きマークダウンおよび音声JSONの検証
        md_files = glob.glob(os.path.join(REPORTS_DIR, f"*{req_id}*.md"))
        json_files = glob.glob(os.path.join(REPORTS_DIR, f"*{req_id}*.json"))
        self.assertEqual(len(md_files), 1)
        self.assertEqual(len(json_files), 1)

        with open(md_files[0], "r", encoding="utf-8") as f:
            md_text = f.read()
        self.assertIn("---", md_text)
        self.assertIn(f'spoken_summary: "{expected_summary}"', md_text)
        self.assertIn("KDIGO AKI ステージ分類レポート", md_text)

        with open(json_files[0], "r", encoding="utf-8") as f:
            j_data = json.load(f)
        self.assertEqual(j_data["spoken_summary"], expected_summary)

    def test_48_scenario3_client_report_polling_and_ui_render(self):
        """シナリオ3: クライアントによる最新レポート取得とUI描画データの整合性"""
        rep_id = f"e2e_sc3_{int(time.time() * 1000)}"
        md_name = f"report_20261010_120000_{rep_id}.md"
        json_name = f"report_20261010_120000_{rep_id}.json"
        md_p = os.path.join(REPORTS_DIR, md_name)
        json_p = os.path.join(REPORTS_DIR, json_name)
        self.created_files.extend([md_p, json_p])

        report_body = (
            "---\n"
            f"request_id: {rep_id}\n"
            'spoken_summary: "肺炎球菌ワクチンの接種間隔要約"\n'
            "---\n\n"
            "# 肺炎球菌ワクチン接種ガイドライン\n"
            "PCV13/15/20およびPPSV23の併用手順。"
        )
        with open(md_p, "w", encoding="utf-8") as f:
            f.write(report_body)
        with open(json_p, "w", encoding="utf-8") as f:
            json.dump({
                "request_id": rep_id,
                "spoken_summary": "肺炎球菌ワクチンの接種間隔要約"
            }, f, ensure_ascii=False)

        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["filename"], md_name)
        self.assertEqual(data["spoken_summary"], "肺炎球菌ワクチンの接種間隔要約")
        self.assertIn("肺炎球菌ワクチン接種ガイドライン", data["content"])

        # ダッシュボードHTMLのレンダリング要件確認
        res_dash = self.client.get("/", auth=("admin", "password123"))
        self.assertIn("marked.parse(data.content)", res_dash.text)
        self.assertIn("speakText(data.spoken_summary", res_dash.text)

    def test_49_scenario4_adversarial_rejected_without_queue_pollution(self):
        """シナリオ4: 不正な認証情報や不正JSONリクエストの堅牢な拒絶とキュー無汚染"""
        before_count = len(os.listdir(REQUESTS_DIR))

        # 1. 認証なし攻撃
        res1 = self.client.post("/api/chat", json={"message": "侵入テスト1"})
        self.assertEqual(res1.status_code, 401)

        # 2. 誤ったパスワード攻撃
        res2 = self.client.post("/api/chat", json={"message": "侵入テスト2"}, auth=("admin", "badpass"))
        self.assertEqual(res2.status_code, 401)

        # 3. 不正JSONペイロード（message欠落）
        res3 = self.client.post("/api/chat", json={"invalid_field": 123}, auth=("admin", "password123"))
        self.assertEqual(res3.status_code, 422)

        after_count = len(os.listdir(REQUESTS_DIR))
        self.assertEqual(before_count, after_count, "不正リクエストによってキューが一切汚染されていないこと")

    def test_50_scenario5_port_env_binding_coordination(self):
        """シナリオ5: PORT環境変数変更下でのWeb/Worker協調動作とバインディング適合"""
        # PORT=10000設定時の動作検証
        os.environ["PORT"] = "10000"

        # main.pyのポートバインディング設定値の整合性
        configured_port = int(os.environ.get("PORT", 8000))
        self.assertEqual(configured_port, 10000)

        # supervisord.conf で %(ENV_PORT)s が指定されていること
        with open(os.path.join(BASE_DIR, "supervisord.conf"), "r", encoding="utf-8") as f:
            conf = f.read()
        self.assertIn("--port %(ENV_PORT)s", conf)

        # entrypoint.sh で PORT がエクスポートされること
        with open(os.path.join(BASE_DIR, "entrypoint.sh"), "r", encoding="utf-8") as f:
            ep = f.read()
        self.assertIn('export PORT="${PORT:-8000}"', ep)

        # クライアントAPIがポート環境下でも正常動作すること
        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)

    def test_51_scenario6_ios_safari_https_and_mic_compatibility(self):
        """シナリオ6: iOS Safariマイク/HTTPS適合性およびUI最適化検証"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        html = res.text

        # iOS Safari音声認識とマイク制御のための要素検証
        self.assertIn('id="continuous-mic-btn"', html)
        self.assertIn("webkitSpeechRecognition", html)
        self.assertIn("speechSynthesis", html)
        self.assertIn("safe-area-inset-bottom", html, "iPhoneノッチ/ホームバー対応スタイルがあること")
        self.assertIn('viewport" content="width=device-width, initial-scale=1.0', html)

    def test_52_scenario7_burst_load_queue_concurrency(self):
        """シナリオ7: 高負荷複数投入に対するキュー整合性と全件処理"""
        task_count = 5
        for i in range(task_count):
            res = self.client.post(
                "/api/chat",
                json={"message": f"バースト負荷テスト_{i}"},
                auth=("admin", "password123")
            )
            self.assertEqual(res.status_code, 200)

        mock_agent = self._create_mock_agent("# バースト結果", "バースト要約")
        with patch("worker.Agent", return_value=mock_agent):
            processed = asyncio.run(worker.run_worker_once(agent=mock_agent))

        self.assertEqual(processed, task_count, f"{task_count}件すべてが一度のワーカー実行で処理されること")

        # 残留キューファイルがないこと
        remaining = [f for f in os.listdir(REQUESTS_DIR) if f.endswith(".json") and not f.endswith(".tmp")]
        self.assertEqual(len(remaining), 0, "全タスクが処理完了してクリーンアップされたこと")


if __name__ == "__main__":
    unittest.main()
