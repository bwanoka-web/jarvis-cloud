# J.A.R.V.I.S. 開発プロジェクト・資産カタログ

作成日時: 2026-10-12 13:25:59
合計ファイル数: 945 ファイル
合計サイズ: 113.72 MB

## プロジェクト構造と分類一覧

| カテゴリ | プロジェクト名 | 状態 | ファイル数 | サイズ (MB) | ソース元パス |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 01_active | buyma-project | COPIED | 133 | 43.49 MB | `C:\Users\user\buyma-project` |
| 01_active | BUYMA_Automation_System | COPIED | 205 | 57.60 MB | `C:\Users\user\OneDrive\Desktop\BUYMA_Automation_System` |
| 02_tools | buyma_scraping | COPIED | 9 | 0.39 MB | `C:\Users\user\buyma_scraping` |
| 02_tools | buyma_system_v2 | COPIED | 16 | 0.42 MB | `C:\Users\user\buyma_system_v2` |
| 02_tools | buyma_auto_selector | COPIED | 19 | 0.01 MB | `C:\Users\user\OneDrive\Desktop\buyma_auto_selector` |
| 02_tools | BUYMA | COPIED | 414 | 2.15 MB | `C:\Users\user\OneDrive\Desktop\BUYMA` |
| 03_archive | BUYMA_Project | COPIED | 19 | 5.08 MB | `C:\Users\user\BUYMA_Project` |
| 03_archive | BUYMA_PROJECT4 | COPIED | 38 | 1.14 MB | `C:\Users\user\BUYMA_PROJECT4` |
| 03_archive | BUYMA5 | COPIED | 5 | 0.03 MB | `C:\Users\user\BUYMA5` |
| 03_archive | UEC | COPIED | 6 | 0.02 MB | `C:\Users\user\UEC` |
| 03_archive | BUYMA_PROJECT3 | COPIED | 12 | 1.39 MB | `C:\Users\user\BUYMA_PROJECT3` |
| 03_archive | buyma_system | COPIED | 49 | 1.89 MB | `C:\Users\user\buyma_system` |
| 03_archive | buyma-poc | COPIED | 19 | 0.11 MB | `C:\Users\user\buyma-poc` |
| 03_archive | BUYMA自動化_実行環境 | COPIED | 1 | 0.01 MB | `C:\Users\user\OneDrive\Desktop\BUYMA自動化_実行環境` |

## 各レイヤーの役割
- `01_active/`: 現在稼働中・主力開発中のメインプロジェクト（buyma-project, BUYMA_Automation_System）
- `02_tools/`: 単機能スクレイパー、自動選択ツール、補助自動化群（buyma_scraping, buyma_system_v2, buyma_auto_selector, BUYMA）
- `03_archive/`: 過去の実験・旧バージョン・PoC・蓄積ノウハウ（BUYMA_Project, BUYMA_PROJECT4, BUYMA5, UEC, BUYMA_PROJECT3, buyma_system, buyma-poc, BUYMA自動化_実行環境）

## セキュリティと保護方針
- `.gitignore` および `.dockerignore` に `projects/` を追加し、クラウドレポジトリおよびDockerイメージへの混入を遮断。
- 仮想環境(`.venv`, `venv`, `venv_ai`)、`node_modules`、ブラウザキャッシュ・プロファイル、画像キャッシュは除外して軽量ソースコードのみを維持。
