"""
記憶管理モジュール (memory_manager.py)

workspace/memory/president_memory.json に対し、
社長の思考ルール、好み、業務方針を永続化し、
対話や指示から自動抽出・更新・参照するロジックを提供します。
"""

from datetime import datetime, timezone
import json
import logging
import os
import re

logger = logging.getLogger("jarvis.memory")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "workspace", "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "president_memory.json")

DEFAULT_MEMORY = {
    "version": "1.0",
    "updated_at": "",
    "core_rules": [
        "回答は結論ファーストとし、無駄な前置きを省く",
        "医療・臨床と物販自動化の双方でスピードとレバレッジを最重要視する",
        "車内での壁打ちは1〜2文（80〜120文字）のテンポ良い音声回答とする",
        "抽象論ではなく、即座に着手可能な具体的アクションを提示する"
    ],
    "preferences": {
        "communication_style": "敬体（〜です・〜ます）、簡潔、結論先行",
        "decision_criteria": "データと事実に基づく合理性、ROIと再現性",
        "focus_areas": [
            "臨床ポケットパートナーの開発と現場導入推進",
            "BUYMA等物販自動化パイプラインの安定運用とレバレッジ拡大"
        ]
    },
    "custom_memories": []
}

def ensure_memory_dir() -> str:
    """記憶ディレクトリを確実に作成する"""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    return MEMORY_DIR

def get_memory_file_path() -> str:
    """記憶ファイルの絶対パスを返す"""
    return MEMORY_FILE

def load_memory() -> dict:
    """
    記憶ファイル（president_memory.json）を安全に読み込みます。
    ファイルが存在しないか破損している場合はデフォルト記憶を返します。
    """
    ensure_memory_dir()
    if not os.path.exists(MEMORY_FILE):
        init_mem = dict(DEFAULT_MEMORY)
        init_mem["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_memory(init_mem)
        return init_mem

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("記憶ファイルのルート要素が辞書ではありません。デフォルトを使用します。")
            return dict(DEFAULT_MEMORY)
    except Exception as e:
        logger.error("記憶ファイル読み込みエラー: %s", e)
        return dict(DEFAULT_MEMORY)

def save_memory(memory_data: dict) -> bool:
    """
    記憶データをアトミック（一時ファイル置換）に永続保存します。
    """
    ensure_memory_dir()
    memory_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp_path = MEMORY_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, MEMORY_FILE)
        return True
    except Exception as e:
        logger.error("記憶ファイル保存エラー: %s", e)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

def add_rule(rule_text: str) -> bool:
    """コア思考ルールを追加する"""
    clean_rule = rule_text.strip()
    if not clean_rule:
        return False
    data = load_memory()
    rules = data.setdefault("core_rules", [])
    if clean_rule not in rules:
        rules.append(clean_rule)
        return save_memory(data)
    return True

def add_memory_item(category: str, item_text: str) -> bool:
    """カスタム記憶項目を追加する"""
    clean_item = item_text.strip()
    if not clean_item:
        return False
    data = load_memory()
    custom_list = data.setdefault("custom_memories", [])
    record = {
        "category": category,
        "content": clean_item,
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }
    # 重複回避
    for existing in custom_list:
        if existing.get("content") == clean_item:
            return True
    custom_list.append(record)
    return save_memory(data)

def get_formatted_memory_context() -> str:
    """
    LLMプロンプト注入用にフォーマットした記憶テキストを返します。
    """
    data = load_memory()
    lines = ["【社長の思考ルール・嗜好・蓄積記憶】"]
    
    rules = data.get("core_rules", [])
    if rules:
        lines.append("・基本思考ルール:")
        for r in rules:
            lines.append(f"  - {r}")
            
    prefs = data.get("preferences", {})
    if prefs:
        lines.append(f"・対話スタイル: {prefs.get('communication_style', '')}")
        lines.append(f"・判断基準: {prefs.get('decision_criteria', '')}")
        focus = prefs.get("focus_areas", [])
        if focus:
            lines.append(f"・注力テーマ: {', '.join(focus)}")
            
    customs = data.get("custom_memories", [])
    if customs:
        lines.append("・対話から抽出された社長の指示・価値観:")
        for c in customs[-10:]:  # 直近10件
            lines.append(f"  - [{c.get('category', 'メモ')}] {c.get('content', '')}")
            
    return "\n".join(lines)

# 社長の嗜好や方針表明を検知する正規表現パターン
MEMORY_EXTRACTION_PATTERNS = [
    (r"(?:今後は|これからは|次からは|常に|必ず)(.+?)(?:にして|として|でいこう|で頼む|でいく)", "行動・指示ルール"),
    (r"(?:私の考えは|私の方針は|方針として|俺の考えは|僕の考えは)(.+?)(?:だ|です|とする|と考えている)", "経営・判断方針"),
    (r"(?:覚えておいて|記憶して|メモしておいて)(?:ほしい)?[:：]?\s*(.+)", "個別記憶"),
    (r"(.+?)(?:を優先して|を最優先に|を重視して)", "優先順位"),
]

def extract_and_update_memory(text: str) -> list[str]:
    """
    対話テキストから社長の思考ルールや好みを検知し、自動的に記憶ファイルに反映します。
    新しく追加された項目のリストを返します。
    """
    if not text:
        return []
    
    clean_text = text.strip()
    extracted_items = []
    
    for pattern, category in MEMORY_EXTRACTION_PATTERNS:
        matches = re.finditer(pattern, clean_text)
        for m in matches:
            content = m.group(1).strip()
            # 短すぎるか長すぎるものは除外
            if 4 <= len(content) <= 150:
                if add_memory_item(category, content):
                    extracted_items.append(f"{category}: {content}")
                    
    return extracted_items
