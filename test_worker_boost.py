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
        self.assertIn("projects/", inst)
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


if __name__ == "__main__":
    unittest.main()
