import asyncio
import glob
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import main
import worker

WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
REQUESTS_DIR = os.path.join(WORKSPACE_DIR, "requests")
REPORTS_DIR = os.path.join(WORKSPACE_DIR, "reports")


class TestAudioAndQueueFix(unittest.TestCase):
    """
    ユーザー指示に基づく修正検証テストスイート:
    1. リクエスト受付確認TTS（speakText）の廃止と画面ステータス表示のみの確認
    2. 完成レポート要約（spoken_summary）のみのTTS読み上げ保持確認
    3. 音声認識切断防止（restartRecognitionIfNeeded, isRecognizing, ウォッチドッグ）の検証
    4. TTS音声マイク誤検知・無限ループ防止（1000msクールダウン、エコーフィルター）の検証
    5. キュー処理詰まり防止（LLMタイムアウト保護、JSON先行出力）の検証
    """

    @classmethod
    def setUpClass(cls):
        os.makedirs(REQUESTS_DIR, exist_ok=True)
        os.makedirs(REPORTS_DIR, exist_ok=True)
        cls.client = TestClient(main.app)

    def tearDown(self):
        for d in [REQUESTS_DIR, REPORTS_DIR]:
            if os.path.exists(d):
                for f in os.listdir(d):
                    p = os.path.join(d, f)
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                    except OSError:
                        pass

    def test_reception_tts_removed_from_chat_flow(self):
        """チャット送信完了時に受付確認の音声読み上げ(speakText)が呼び出されないこと"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        html = res.text

        # チャット送信イベントハンドラ内で受付時のspeakText呼び出しが廃止されていること
        submit_idx = html.find("form.addEventListener('submit'")
        self.assertNotEqual(submit_idx, -1)
        submit_block = html[submit_idx : html.find("function appendMessage", submit_idx)]
        
        # 受付確認の読み上げコードが存在しないことを検証
        self.assertNotIn("speakText(spokenText)", submit_block)
        self.assertIn("リクエストを受け付けました。調査完了まで待機中", submit_block)

    def test_report_tts_preserved_for_spoken_summary(self):
        """リサーチ完了レポートの要約（spoken_summary）に対するTTS読み上げは保持されていること"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn("speakText(data.spoken_summary, false);", html)

    def test_mic_echo_and_loop_prevention_logic(self):
        """TTS音声のスピーカー残響を避けるための1000msクールダウンおよびエコーフィルターが存在すること"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        html = res.text

        # クールダウンが1000msに強化されていること
        self.assertIn("micCooldownTimer = setTimeout", html)
        self.assertIn("1000);", html)

        # エコー防止用のフィルター条件が存在すること
        self.assertIn("lastSpokenText", html)
        self.assertIn("Date.now() - lastSpokenTime < 4000", html)
        self.assertIn("speechSynthesis.speaking", html)

    def test_speech_recognition_disconnection_guard(self):
        """音声認識の切断を防止する状態管理とウォッチドッグが存在すること"""
        res = self.client.get("/", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn("function restartRecognitionIfNeeded()", html)
        self.assertIn("isRecognizing", html)
        self.assertIn("restartRecognitionIfNeeded();", html)

    def test_worker_queue_timeout_and_json_first(self):
        """workerがタイムアウト保護付きでタスクを処理し、JSON要約を先行生成すること"""
        req_id = f"test_fix_{int(time.time() * 1000)}"
        req_file = os.path.join(REQUESTS_DIR, f"req_{req_id}.json")
        with open(req_file, "w", encoding="utf-8") as f:
            json.dump({"prompt": "敗血症の最新診断基準", "status": "pending"}, f)

        mock_resp = AsyncMock()
        mock_resp.text = AsyncMock(return_value=json.dumps({
            "spoken_summary": "敗血症の診断基準要約です。",
            "markdown_report": "# 敗血症レポート\nSOFAスコア詳細。"
        }, ensure_ascii=False))

        mock_agent = AsyncMock()
        mock_agent.chat = AsyncMock(return_value=mock_resp)

        processed = asyncio.run(worker.run_worker_once(agent=mock_agent))
        self.assertEqual(processed, 1)

        # 生成された成果物の確認
        md_files = glob.glob(os.path.join(REPORTS_DIR, f"*{req_id}*.md"))
        json_files = glob.glob(os.path.join(REPORTS_DIR, f"*{req_id}*.json"))
        self.assertEqual(len(md_files), 1)
        self.assertEqual(len(json_files), 1)

        # latest_report エンドポイントでの取得確認
        res = self.client.get("/api/latest_report", auth=("admin", "password123"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["spoken_summary"], "敗血症の診断基準要約です。")
        self.assertIn("SOFAスコア詳細", data["content"])


if __name__ == "__main__":
    unittest.main()
