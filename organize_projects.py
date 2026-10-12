import os
import sys
import shutil
import fnmatch
from datetime import datetime

# UTF-8 出力設定
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_BASE_DIR = os.path.join(BASE_DIR, "projects")

CATEGORIES = {
    "01_active": [
        r"C:\Users\user\buyma-project",
        r"C:\Users\user\OneDrive\Desktop\BUYMA_Automation_System"
    ],
    "02_tools": [
        r"C:\Users\user\buyma_scraping",
        r"C:\Users\user\buyma_system_v2",
        r"C:\Users\user\buyma_auto_selector",
        r"C:\Users\user\OneDrive\Desktop\BUYMA"
    ],
    "03_archive": [
        r"C:\Users\user\BUYMA_Project",
        r"C:\Users\user\BUYMA_PROJECT4",
        r"C:\Users\user\BUYMA5",
        r"C:\Users\user\UEC",
        r"C:\Users\user\BUYMA_PROJECT3",
        r"C:\Users\user\buyma_system",
        r"C:\Users\user\buyma-poc",
        r"C:\Users\user\BUYMA自動化_実行環境"
    ]
}

EXCLUDE_DIR_PATTERNS = [
    ".*",
    "venv*",
    "*venv",
    "env",
    "ENV",
    "node_modules",
    "__pycache__",
    "*profile*",
    "*Profile*",
    "*Session*",
    "User_Data",
    "debug_screenshots",
    "Images",
    "hat_images*",
    "Product_Images*",
    "出品",
    "不要",
    "cache",
    "Code Cache",
    "blob_storage"
]

EXCLUDE_FILE_EXTS = {
    ".pyc", ".pyo", ".pyd", ".exe", ".dll", ".so", ".dylib", ".lib", ".a", ".bin", ".msi",
    ".log", ".tmp", ".bak", ".swp", ".swo", ".ds_store",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mp3", ".wav", ".zip", ".tar", ".gz", ".7z"
}


def is_dir_excluded(dirname: str) -> bool:
    dlow = dirname.lower()
    for pat in EXCLUDE_DIR_PATTERNS:
        if fnmatch.fnmatch(dlow, pat.lower()):
            return True
    return False


def is_file_included(filename: str) -> bool:
    flow = filename.lower()
    ext = os.path.splitext(flow)[1]
    if ext in EXCLUDE_FILE_EXTS:
        return False
    if flow in {"thumbs.db", ".ds_store"}:
        return False
    return True


def resolve_source_path(path: str) -> str | None:
    if os.path.exists(path):
        return path
    # Desktop 配下の同名フォルダーをフォールバック検索
    base_name = os.path.basename(path)
    desktop_candidate = os.path.join(r"C:\Users\user\OneDrive\Desktop", base_name)
    if os.path.exists(desktop_candidate):
        return desktop_candidate
    return None


def copy_project(src_dir: str, dest_dir: str) -> tuple[int, int]:
    copied_files = 0
    copied_bytes = 0

    for root, dirs, files in os.walk(src_dir):
        # 除外フォルダーをインプレースで排除
        dirs[:] = [d for d in dirs if not is_dir_excluded(d)]

        rel_path = os.path.relpath(root, src_dir)
        target_root = dest_dir if rel_path == "." else os.path.join(dest_dir, rel_path)

        for file in files:
            if not is_file_included(file):
                continue

            src_file = os.path.join(root, file)
            dest_file = os.path.join(target_root, file)

            try:
                os.makedirs(target_root, exist_ok=True)
                shutil.copy2(src_file, dest_file)
                copied_files += 1
                copied_bytes += os.path.getsize(src_file)
            except OSError as e:
                print(f"  [WARN] コピー失敗 ({src_file} -> {dest_file}): {e}")

    return copied_files, copied_bytes


def main():
    print(f"=== J.A.R.V.I.S. プロジェクト整理・安全コピー開始 ===")
    print(f"保存先: {TARGET_BASE_DIR}\n")

    os.makedirs(TARGET_BASE_DIR, exist_ok=True)
    summary_data = []

    for category, path_list in CATEGORIES.items():
        cat_dir = os.path.join(TARGET_BASE_DIR, category)
        os.makedirs(cat_dir, exist_ok=True)
        print(f"--- カテゴリ: {category} ---")

        for requested_path in path_list:
            resolved_path = resolve_source_path(requested_path)
            proj_name = os.path.basename(requested_path)
            dest_proj_dir = os.path.join(cat_dir, proj_name)

            if not resolved_path:
                print(f"  [MISSING] 対象が存在しません: {requested_path}")
                summary_data.append({
                    "category": category,
                    "name": proj_name,
                    "src": requested_path,
                    "status": "MISSING",
                    "files": 0,
                    "size_mb": 0.0
                })
                continue

            print(f"  [COPYING] {resolved_path} -> {dest_proj_dir}")
            files_cnt, bytes_cnt = copy_project(resolved_path, dest_proj_dir)
            size_mb = bytes_cnt / (1024 * 1024)
            print(f"    完了: {files_cnt} ファイル ({size_mb:.2f} MB)")

            summary_data.append({
                "category": category,
                "name": proj_name,
                "src": resolved_path,
                "status": "COPIED",
                "files": files_cnt,
                "size_mb": size_mb
            })

    # カタログ文書生成
    catalog_path = os.path.join(TARGET_BASE_DIR, "PROJECTS_CATALOG.md")
    total_files = sum(item["files"] for item in summary_data)
    total_size = sum(item["size_mb"] for item in summary_data)

    catalog_lines = [
        "# J.A.R.V.I.S. 開発プロジェクト・資産カタログ",
        "",
        f"作成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"合計ファイル数: {total_files} ファイル",
        f"合計サイズ: {total_size:.2f} MB",
        "",
        "## プロジェクト構造と分類一覧",
        "",
        "| カテゴリ | プロジェクト名 | 状態 | ファイル数 | サイズ (MB) | ソース元パス |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for item in summary_data:
        catalog_lines.append(
            f"| {item['category']} | {item['name']} | {item['status']} | {item['files']} | {item['size_mb']:.2f} MB | `{item['src']}` |"
        )

    catalog_lines.extend([
        "",
        "## 各レイヤーの役割",
        "- `01_active/`: 現在稼働中・主力開発中のメインプロジェクト（buyma-project, BUYMA_Automation_System）",
        "- `02_tools/`: 単機能スクレイパー、自動選択ツール、補助自動化群（buyma_scraping, buyma_system_v2, buyma_auto_selector, BUYMA）",
        "- `03_archive/`: 過去の実験・旧バージョン・PoC・蓄積ノウハウ（BUYMA_Project, BUYMA_PROJECT4, BUYMA5, UEC, BUYMA_PROJECT3, buyma_system, buyma-poc, BUYMA自動化_実行環境）",
        "",
        "## セキュリティと保護方針",
        "- `.gitignore` および `.dockerignore` に `projects/` を追加し、クラウドレポジトリおよびDockerイメージへの混入を遮断。",
        "- 仮想環境(`.venv`, `venv`, `venv_ai`)、`node_modules`、ブラウザキャッシュ・プロファイル、画像キャッシュは除外して軽量ソースコードのみを維持。",
        ""
    ])

    with open(catalog_path, "w", encoding="utf-8") as f:
        f.write("\n".join(catalog_lines))

    print(f"\n[CATALOG CREATED] {catalog_path}")
    print(f"=== 全プロジェクトコピー完了: 合計 {total_files} ファイル ({total_size:.2f} MB) ===")


if __name__ == "__main__":
    main()
