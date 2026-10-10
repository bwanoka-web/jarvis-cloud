# Project: J.A.R.V.I.S. クラウドサーバー環境デプロイおよび堅牢化

## Architecture
- モジュール境界とデータフロー:
  - クライアント: スマートフォン（iOS Safari / Android Chrome）およびデスクトップWebブラウザ
  - Webサーバー（main.py）: FastAPIによるHTTP/WebSocket、Basic認証、静的ファイル配信、APIエンドポイント（/api/chat, /api/latest_report）
  - メッセージキュー（workspace/requests/）: ファイルドロップによるステートレスコンテナ内非同期キュー
  - バックグラウンドワーカー（worker.py）: リクエスト検知、Gemini API（google.antigravity）呼び出し、レポート生成（workspace/reports/）
  - プロセス管理（supervisord）: 単一Dockerコンテナ内でFastAPIとworker.pyを常時稼働・監視
  - クラウド基盤: Render / Railway 等のPaaS（HTTPS自動終端、PORT環境変数バインディング）

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---|---|---|---|
| 1 | Dockerコンテナ化 | LinuxベースのPythonコンテナ定義（Dockerfile） | M1 | survey |
| 2 | 依存関係定義 | Linux環境で確実にビルド可能な依存ライブラリ一覧（requirements.txt） | M1 | survey |
| 3 | クラウドインフラ設定 | Render用Blueprint定義（render.yaml） | M1 | survey |
| 4 | マルチプロセス管理 | supervisordおよび起動スクリプト（entrypoint.sh, supervisord.conf） | M1 | survey |
| 5 | キューキーの互換性修正 | worker.pyでのprompt/query両対応 | M2 | survey |
| 6 | worker実行関数のシグネチャ互換 | run_worker_once(agent=None)への対応 | M2 | survey |
| 7 | ステートレスキュー堅牢化 | アトミック処理、例外リカバリ、クリーンアップ | M2 | survey |
| 8 | 動的Basic認証 | main.pyにおける環境変数ベースの認証情報設定 | M3 | survey |
| 9 | プロキシ・ポート追従 | PORT環境変数対応およびリバースプロキシヘッダー処理 | M3 | survey |
| 10 | スマホ対応UI最適化 | 縦画面レスポンシブ表示およびiOS音声制御対応 | M3 | survey |
| 11 | E2E自動テスト実行 | 全単体・統合テストのパス確認 | M4 | survey |
| 12 | セキュリティおよび整合性監査 | Forensic Auditorによる真正性検証 | M4 | survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| M1 | クラウドデプロイ設定 | Dockerfile, requirements.txt, render.yaml, supervisord.conf, entrypoint.sh | none | DONE |
| M2 | バックグラウンドタスク・キュー堅牢化 | worker.py改修（prompt/query対応、run_worker_once引数対応）、test_queue.py通過 | none | DONE |
| M3 | セキュリティ・認証およびクラウド対応 | main.py改修（Basic認証環境変数化、PORT/プロキシ対応、UIレスポンシブ） | M1, M2 | DONE |
| M4 | E2E総合検証および完全性監査 | 全機能テスト、音声/テキスト/レポート描画検証、セキュリティ検証、監査 | M1, M2, M3 | DONE |

## Interface Contracts
### main.py ↔ workspace/requests/
- 出力ファイル形式: workspace/requests/<request_id>.json
- JSONスキーマ:
  - request_id: string (UUIDまたはミリ秒タイムスタンプ)
  - timestamp: string (ISO 8601)
  - prompt: string (ユーザーの入力指示文)
  - username: string (認証済みユーザー名)
  - status: "pending"

### worker.py ↔ workspace/requests/ ↔ workspace/reports/
- 入力: workspace/requests/<request_id>.json (読み込み時 .processing にアトミックリネーム)
- プロンプト抽出優先順位: data.get("prompt") -> data.get("query") -> raw content
- 出力: workspace/reports/<timestamp>_<request_id>.md
  - 構成: YAML Frontmatter (spoken_summary, timestamp, request_id) + Markdown本文 (markdown_report)

### クライアント ↔ main.py
- Basic認証: Authorization: Basic <base64(user:pass)>
- /api/chat: POST { "message": string } -> { "status": "accepted", "request_id": string }
- /api/latest_report: GET -> { "filename": string, "content": string, "spoken_summary": string }

## Code Layout
- Dockerfile: プロジェクトルート
- requirements.txt: プロジェクトルート
- render.yaml: プロジェクトルート
- supervisord.conf: プロジェクトルート
- entrypoint.sh: プロジェクトルート
- main.py: プロジェクトルート
- worker.py: プロジェクトルート
- test_queue.py: プロジェクトルート
- workspace/requests/: リクエストキューディレクトリ
- workspace/reports/: レポート成果物ディレクトリ
