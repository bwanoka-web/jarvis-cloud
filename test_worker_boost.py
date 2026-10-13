import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import worker


class TestWorkerBoostSystem(unittest.TestCase):
    def test_system_instructions_has_boost_and_project_context(self):
        inst = worker.SYSTEM_INSTRUCTIONS
        # 常時ブースト・熟考モード
        self.assertIn("常時ブースト・熟考モード", inst)
        self.assertIn("多角的多段階思考", inst)
        self.assertIn("自己批判", inst)

        # プロジェクト把握能力
        self.assertIn("projects", inst)
        self.assertIn("01_active", inst)
        self.assertIn("02_tools", inst)
        self.assertIn("03_archive", inst)
        self.assertIn("buyma-project", inst)
        self.assertIn("BUYMA_Automation_System", inst)

        # 出力仕様（TTS音声要約と高密度Markdown）
        self.assertIn("spoken_summary", inst)
        self.assertIn("markdown_report", inst)
        self.assertIn("車内", inst)

    def test_worker_config_uses_upgraded_instructions(self):
        self.assertEqual(worker.worker_config.system_instructions, worker.SYSTEM_INSTRUCTIONS)

    def test_projects_dir_configured(self):
        self.assertTrue(hasattr(worker, "PROJECTS_DIR"))
        self.assertEqual(worker.PROJECTS_DIR, os.path.join(BASE_DIR, "projects"))

    def test_clean_and_parse_deliberate_response(self):
        sample_json = (
            '{\n'
            '  "spoken_summary": "BUYMA自動出品パイプラインの在庫監視モジュール改修案がまとまりました。01_activeの資産を活用して即時着手可能です。",\n'
            '  "markdown_report": "# 在庫監視モジュール改修計画\\n\\n## エグゼクティブサマリー\\n結論として現行基盤を拡張します。\\n\\n## 自己批判検証\\nAPIレート制限のリスクを回避する設計としました。"\n'
            '}'
        )
        md, spk = worker.clean_and_parse_llm_response(sample_json)
        self.assertIn("在庫監視モジュール改修計画", md)
        self.assertIn("エグゼクティブサマリー", md)
        self.assertIn("BUYMA自動出品パイプライン", spk)
        self.assertNotIn("#", spk)
        self.assertNotIn("*", spk)

    def test_spoken_summary_sanitization_removes_markdown(self):
        # LLMがspoken_summary内に**強調**や#、リンク等のMarkdown記号を含めて出力した場合のサニタイズ検証
        raw_json = (
            '{\n'
            '  "spoken_summary": "**速報**: [新モジュール](http://example.com) の設計が完了しました。`BUYMA`監視を#1方針で即時実行可能です。",\n'
            '  "markdown_report": "# 詳細レポート本文"\n'
            '}'
        )
        md, spk = worker.clean_and_parse_llm_response(raw_json)
        self.assertNotIn("*", spk)
        self.assertNotIn("#", spk)
        self.assertNotIn("`", spk)
        self.assertNotIn("[", spk)
        self.assertNotIn("]", spk)
        self.assertNotIn("http://", spk)
        self.assertIn("速報", spk)
        self.assertIn("新モジュール", spk)
        self.assertIn("設計が完了しました", spk)

    def test_projects_directory_structure_and_exclusion_safety(self):
        projects_dir = worker.PROJECTS_DIR
        self.assertTrue(os.path.exists(projects_dir))
        self.assertTrue(os.path.isdir(os.path.join(projects_dir, "01_active")))
        self.assertTrue(os.path.isdir(os.path.join(projects_dir, "02_tools")))
        self.assertTrue(os.path.isdir(os.path.join(projects_dir, "03_archive")))
        self.assertTrue(os.path.exists(os.path.join(projects_dir, "PROJECTS_CATALOG.md")))

        # 機密ファイル・ブラウザプロファイル・キャッシュの完全非存在を検証
        for root, dirs, files in os.walk(projects_dir):
            for d in dirs:
                d_low = d.lower()
                self.assertNotIn("mancini_final_gate", d_low)
                self.assertNotIn("crashpad", d_low)
                self.assertNotIn("shadercache", d_low)
                self.assertNotIn(".venv", d_low)
                self.assertNotIn("node_modules", d_low)
                self.assertNotIn("__pycache__", d_low)

            for f in files:
                f_low = f.lower()
                self.assertFalse(f_low.startswith(".env"))
                self.assertFalse(f_low.endswith(".pyc"))
                self.assertFalse(f_low.endswith(".db-journal"))
                self.assertFalse(f_low.endswith(".p"))
                self.assertNotIn(".log.", f_low)

    def test_ignore_files_protect_projects(self):
        gitignore_path = os.path.join(BASE_DIR, ".gitignore")
        dockerignore_path = os.path.join(BASE_DIR, ".dockerignore")

        with open(gitignore_path, "r", encoding="utf-8") as f:
            gi_content = f.read()
        self.assertIn("projects/", gi_content)

        with open(dockerignore_path, "r", encoding="utf-8") as f:
            di_content = f.read()
        self.assertIn("projects/", di_content)

    def test_clinical_pocket_partner_identity_and_targets(self):
        inst = worker.SYSTEM_INSTRUCTIONS
        self.assertIn("臨床ポケットパートナー（Clinical Pocket Partner）", inst)
        self.assertIn("一次ターゲット（主要顧客）", inst)
        self.assertIn("医療・臨床現場の従事者", inst)
        self.assertIn("二次ターゲット", inst)
        self.assertIn("車内・移動中のエグゼクティブ・経営者", inst)

    def test_fault_tolerant_voice_and_decoupling_boundaries(self):
        inst = worker.SYSTEM_INSTRUCTIONS
        self.assertIn("音声誤認識の文脈フォールトトレラント解釈", inst)
        self.assertIn("認証ポケットパートナー", inst)
        self.assertIn("輪唱", inst)
        self.assertIn("社内プロジェクト資産（BUYMA等）のこじつけ防止境界", inst)
        self.assertIn("無理にBUYMAや物販システムに結びつけて回答", inst)

    def test_concise_mode_flexibility(self):
        inst = worker.SYSTEM_INSTRUCTIONS
        self.assertIn("柔軟性の付与", inst)
        self.assertIn("短めで", inst)
        self.assertIn("80〜120文字", inst)

    def test_clinical_pocket_partner_document_exists(self):
        doc_path = os.path.join(BASE_DIR, "CLINICAL_POCKET_PARTNER.md")
        self.assertTrue(os.path.exists(doc_path))
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("臨床ポケットパートナー (Clinical Pocket Partner) 基盤定義書", content)
        self.assertIn("一次ターゲット（主要顧客）", content)
        self.assertIn("二次ターゲット", content)
        self.assertIn("フォールトトレランス仕様", content)

    def test_main_voice_normalization_logic(self):
        import main
        self.assertEqual(
            main.normalize_voice_query("認証ポケットパートナーのターゲットは？"),
            "臨床ポケットパートナーのターゲットは？"
        )
        self.assertEqual(
            main.normalize_voice_query("認証ポケットの機能について"),
            "臨床ポケットの機能について"
        )
        self.assertEqual(
            main.normalize_voice_query("輪唱ポケットパートナーの最新状況"),
            "臨床ポケットパートナーの最新状況"
        )
        self.assertEqual(
            main.normalize_voice_query("認承ポケットを教えて"),
            "臨床ポケットを教えて"
        )
        self.assertEqual(
            main.normalize_voice_query("臨終ポケットパートナーについて"),
            "臨床ポケットパートナーについて"
        )
        # 空白混入（半角・全角）パターンの正規化
        self.assertEqual(
            main.normalize_voice_query("認証 ポケット パートナーのターゲットは？"),
            "臨床ポケットパートナーのターゲットは？"
        )
        self.assertEqual(
            main.normalize_voice_query("認証　ポケット　パートナーのターゲットは？"),
            "臨床ポケットパートナーのターゲットは？"
        )
        # ひらがな・カタカナ誤認識パターンの正規化
        self.assertEqual(
            main.normalize_voice_query("にんしょうポケットパートナーのターゲットは？"),
            "臨床ポケットパートナーのターゲットは？"
        )
        self.assertEqual(
            main.normalize_voice_query("ニンショウポケットパートナーのターゲットは？"),
            "臨床ポケットパートナーのターゲットは？"
        )
        self.assertEqual(
            main.normalize_voice_query("認証パートナーについて教えて"),
            "臨床ポケットパートナーについて教えて"
        )
        # ユーザーの実発話シナリオ（短め指定付き）の正規化
        self.assertEqual(
            main.normalize_voice_query("認証ポケットパートナーのターゲットはどのように把握していますか短めでいいんで教えてください"),
            "臨床ポケットパートナーのターゲットはどのように把握していますか短めでいいんで教えてください"
        )
        # 影響のない文変数は維持される
        self.assertEqual(
            main.normalize_voice_query("BUYMAの在庫監視状況"),
            "BUYMAの在庫監視状況"
        )
        self.assertEqual(
            main.normalize_voice_query("認証テスト"),
            "認証テスト"
        )

    def test_worker_voice_normalization_logic(self):
        self.assertEqual(
            worker.normalize_voice_query("認証ポケットパートナーのターゲットは？短めで"),
            "臨床ポケットパートナーのターゲットは？短めで"
        )
        self.assertEqual(
            worker.normalize_voice_query("にんしょう ポケット パートナー"),
            "臨床ポケットパートナー"
        )


if __name__ == "__main__":
    unittest.main()

