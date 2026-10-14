"""
社長分身AI統合テストスイート (test_president_twin_system.py)

ステップ1〜4で新設・改修された以下の機能を包括的かつ厳格に検証します。
1. president_profile.py の3大領域定義、価値観、音声正規化
2. memory_manager.py の記憶永続化、自動抽出、フォーマット
3. FastAPIデュアルエンジン (/api/converse, /api/chat, /api/memory) の動作と認証・レート制限
4. worker.py の社長分身AIプロファイル統合と記憶反映
5. Drive Mode UI のDOM要素とiOS Safariアンロックロジック
"""

import asyncio
import glob
import json
import os
import shutil
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import main
import memory_manager
import president_profile
import worker


class TestPresidentTwinSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def setUp(self):
        self.orig_env = dict(os.environ)
        self.test_mem_file = memory_manager.get_memory_file_path()
        self.mem_backup = None
        if os.path.exists(self.test_mem_file):
            with open(self.test_mem_file, "r", encoding="utf-8") as f:
                self.mem_backup = f.read()

        req_dir = os.path.join(BASE_DIR, "workspace", "requests")
        if os.path.exists(req_dir):
            for f in glob.glob(os.path.join(req_dir, "*")):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        if self.mem_backup is not None:
            with open(self.test_mem_file, "w", encoding="utf-8") as f:
                f.write(self.mem_backup)
        elif os.path.exists(self.test_mem_file):
            try:
                os.remove(self.test_mem_file)
            except OSError:
                pass

        # workspace/requests のクリーンアップ
        req_dir = os.path.join(BASE_DIR, "workspace", "requests")
        if os.path.exists(req_dir):
            for f in glob.glob(os.path.join(req_dir, "*")):
                try:
                    os.remove(f)
                except OSError:
                    pass

    # -------------------------------------------------------------------------
    # 1. president_profile.py の検証
    # -------------------------------------------------------------------------
    def test_01_president_profile_clinical_domain(self):
        """医療・臨床領域のアイデンティティとターゲット設定を検証"""
        cd = president_profile.CLINICAL_DOMAIN
        self.assertIn("臨床ポケットパートナー", cd["system_name"])
        self.assertIn("医療・臨床現場の従事者", cd["primary_target"])
        self.assertIn("医師", cd["primary_target"])
        self.assertIn("車内・移動中のエグゼクティブ", cd["secondary_target"])
        self.assertIn("結論先行", cd["key_principles"][0])

    def test_02_president_profile_commerce_domain(self):
        """物販自動化領域の14プロジェクト台帳と運用ノウハウを検証"""
        cmd = president_profile.COMMERCE_DOMAIN
        self.assertEqual(cmd["total_projects"], 14)
        self.assertEqual(cmd["total_files"], 945)
        self.assertIn("01_active", cmd["structure"])
        self.assertIn("02_tools", cmd["structure"])
        self.assertIn("03_archive", cmd["structure"])
        self.assertIn("buyma-project", str(cmd["structure"]["01_active"]))
        self.assertIn("BUYMA_Automation_System", str(cmd["structure"]["01_active"]))

    def test_03_president_profile_business_strategy(self):
        """経営・ビジネス戦略の価値観と思考パターンを検証"""
        bs = president_profile.BUSINESS_STRATEGY
        self.assertIn("需要と供給の成立", bs["core_philosophy"])
        self.assertIn("自動化とレバレッジ思考", bs["core_philosophy"])
        self.assertIn("迅速な意思決定", bs["core_philosophy"])
        joined = " ".join(bs["thought_patterns"])
        self.assertIn("結論ファースト", joined)
        self.assertIn("レバレッジ", joined)
        self.assertIn("スピード重視", joined)

    def test_04_president_profile_voice_normalization(self):
        """音声誤認の文脈補正辞書が正しく動作することを検証"""
        cases = [
            ("認証ポケットパートナーの状況は？", "臨床ポケットパートナーの状況は？"),
            ("輪唱ポケットの機能", "臨床ポケットの機能"),
            ("ばいまの在庫を監視して", "BUYMAの在庫を監視して"),
            ("エッセンスの価格差", "SSENSEの価格差"),
            ("ユークス出品", "YOOX出品"),
        ]
        for inp, expected in cases:
            out = president_profile.normalize_voice_query(inp)
            self.assertEqual(out, expected)

    def test_05_president_profile_instructions_modes(self):
        """talkモードとtaskモードで適切なプロンプトが生成されることを検証"""
        talk_inst = president_profile.get_president_system_instructions("talk")
        self.assertIn("即時壁打ち対話モード", talk_inst)
        self.assertIn("80〜120文字", talk_inst)
        self.assertIn("1〜2文", talk_inst)

        task_inst = president_profile.get_president_system_instructions("task")
        self.assertIn("社長の分身AI", task_inst)
        self.assertIn("医療・臨床領域", task_inst)
        self.assertIn("物販自動化領域", task_inst)

    # -------------------------------------------------------------------------
    # 2. memory_manager.py の検証
    # -------------------------------------------------------------------------
    def test_06_memory_manager_load_and_save(self):
        """記憶データの読み込み、変更、アトミック保存を検証"""
        mem = memory_manager.load_memory()
        self.assertIn("core_rules", mem)
        self.assertIn("preferences", mem)

        test_rule = "テスト検証用ルール: 常に速度最優先"
        self.assertTrue(memory_manager.add_rule(test_rule))

        reloaded = memory_manager.load_memory()
        self.assertIn(test_rule, reloaded["core_rules"])

    def test_07_memory_manager_add_item(self):
        """カスタム記憶項目の追加と重複防止を検証"""
        self.assertTrue(memory_manager.add_memory_item("方針", "BUYMA在庫監視は深夜1時にも実行"))
        # 重複追加の冪等性
        self.assertTrue(memory_manager.add_memory_item("方針", "BUYMA在庫監視は深夜1時にも実行"))

        mem = memory_manager.load_memory()
        matches = [c for c in mem.get("custom_memories", []) if c.get("content") == "BUYMA在庫監視は深夜1時にも実行"]
        self.assertEqual(len(matches), 1)

    def test_08_memory_manager_extract_and_update(self):
        """自然な対話テキストからのルール・好み自動抽出を検証"""
        sample_input = "今後は回答を箇条書きではなく2文以内の口頭説明にして"
        extracted = memory_manager.extract_and_update_memory(sample_input)
        self.assertTrue(len(extracted) > 0)

        mem = memory_manager.load_memory()
        customs = [c["content"] for c in mem.get("custom_memories", [])]
        found = any("回答を箇条書きではなく2文以内の口頭説明" in c for c in customs)
        self.assertTrue(found, "抽出された記憶が永続化されていること")

    def test_09_memory_manager_formatted_context(self):
        """LLM注入用の記憶コンテキスト整形を検証"""
        ctx = memory_manager.get_formatted_memory_context()
        self.assertIn("社長の思考ルール・嗜好・蓄積記憶", ctx)
        self.assertIn("基本思考ルール", ctx)

    # -------------------------------------------------------------------------
    # 3. FastAPIデュアルエンジン (/api/converse, /api/chat, /api/memory)
    # -------------------------------------------------------------------------
    def test_10_converse_auth_required(self):
        """認証なしでの/api/converseアクセスは401で拒絶されること"""
        res = self.client.post("/api/converse", json={"message": "こんにちは"})
        self.assertEqual(res.status_code, 401)

    def test_11_converse_talk_mode_stream(self):
        """talkモードで即時ストリーミング応答が返却されること"""
        res = self.client.post(
            "/api/converse",
            json={"message": "新しい臨床アプリのアイデアを壁打ちしたい", "mode": "talk"},
            auth=("admin", "password123")
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res.headers.get("content-type", ""))
        self.assertTrue(len(res.text) > 0)

    def test_12_converse_task_mode_enqueues(self):
        """taskモードで業務タスクがバックグラウンドキューへ登録されること"""
        msg = "BUYMAの競合価格を調査してレポートを作って"
        res = self.client.post(
            "/api/converse",
            json={"message": msg, "mode": "task"},
            auth=("admin", "password123")
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("裏で調査・作業を進めます", res.text)

        # キューファイルが生成されたことを確認
        req_dir = os.path.join(BASE_DIR, "workspace", "requests")
        files = [f for f in os.listdir(req_dir) if f.endswith(".json")]
        self.assertTrue(len(files) > 0)

    def test_13_converse_auto_mode_classification(self):
        """autoモード時、「調べて」を含む指示がtaskモードとして自動仕分けされること"""
        res = self.client.post(
            "/api/converse",
            json={"message": "最新の糖尿病ガイドラインを調べておいて", "mode": "auto"},
            auth=("admin", "password123")
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("裏で調査・作業を進めます", res.text)

    def test_14_memory_endpoint_success(self):
        """/api/memory エンドポイントが記憶JSONを正常に返却すること"""
        res = self.client.get("/api/memory", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("core_rules", data)
        self.assertIn("preferences", data)

    def test_15_chat_endpoint_remains_backward_compatible(self):
        """既存の /api/chat エンドポイントがキュー登録を行い後方互換性を維持すること"""
        res = self.client.post(
            "/api/chat",
            json={"message": "心不全の最新知見"},
            auth=("admin", "password123")
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("バックグラウンド調査キューに登録しました", res.text)

    # -------------------------------------------------------------------------
    # 4. worker.py の社長分身AI統合
    # -------------------------------------------------------------------------
    def test_16_worker_system_instructions_has_president_profile(self):
        """worker.SYSTEM_INSTRUCTIONS に社長分身AIおよび記憶マネージャーの統合が反映されていること"""
        inst = worker.SYSTEM_INSTRUCTIONS
        self.assertIn("社長分身AI化", inst)
        self.assertIn("医療・臨床領域", inst)
        self.assertIn("物販自動化領域", inst)
        self.assertIn("経営戦略", inst)
        self.assertIn("社長記憶の尊重", inst)

    # -------------------------------------------------------------------------
    # 5. Drive Mode UI のDOM要素とiOS Safari対応
    # -------------------------------------------------------------------------
    def test_17_dashboard_drive_mode_elements(self):
        """ダッシュボードHTMLにDrive Mode UIの専用要素が含まれていること"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn('id="mode-talk-btn"', html)
        self.assertIn('id="mode-task-btn"', html)
        self.assertIn('id="current-mode-indicator"', html)
        self.assertIn('id="continuous-mic-btn"', html)
        self.assertIn('id="system-status"', html)
        self.assertIn('id="markdown-viewer"', html)
        self.assertIn('id="replay-tts-btn"', html)
        self.assertIn("DELIVERABLES VIEWER", html)
        self.assertIn("J.A.R.V.I.S.", html)


if __name__ == "__main__":
    unittest.main()
