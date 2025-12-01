# Release Notes

## v0.0.2 (2025-12-01)

前回リリース v0.0.1 (2025-09-23) からの変更点をまとめています。

---

### 🚀 主な新機能

#### 外部ライブラリとしての利用対応
- smartestiroid を Python パッケージとして外部プロジェクト（GUIアプリなど）から利用可能に
- `uv add --editable` でのインストールをサポート
- パッケージエクスポート (`TEST_FILE`, `CONFTEST_FILE`, `PACKAGE_DIR`, `PROJECT_ROOT`)

#### プロジェクト構成の大幅リファクタリング
- `src/` レイアウトへの移行
- `appium-tools` を本体に統合
- テストファイルを機能別に分割 (`test_appium_tools_*.py`)

#### LLM 課金状況の可視化
- テスト実行全体のコスト確認機能を追加
- `token-usage-YYYYMMDDHHMMSS.csv` に統計データを保存
- Allure レポートの `environment.properties` にサマリを追記

#### エラーハンドリングの改善
- `find_element` 失敗時は例外ではなくエラー文字列を返却（LLMがリプラン可能に）
- `scroll_to_element` の返り値を詳細化（スクロール回数、移動距離を含む）
- Appiumセッション切断時の例外処理とテストスキップ対応

---

### ✨ 機能追加

- **GUI連携**: テスト進捗をGUI側で表示させるためのログを追加
- **AGENTS.md**: AIエージェント向け開発ガイドを追加
- **LLMモデル選択**: `--mini-model` オプションで GPT-4.1-mini を使用可能に
- **カスタム knowhow**: `--knowhow` / `--knowhow-text` オプションでツール使用ルールをカスタマイズ可能
- **カスタム capabilities**: `--capabilities` オプションでデバイス設定ファイルを指定可能
- **noReset サポート**: testsheet.csv で `noReset` を設定可能に
- **Allure 改善**: step の内容を見やすく、英語対応、ツールコールの保存

---

### 🔧 改善・修正

- プロンプトのチューニング（初期計画の具体化、ログインなどの禁止事項の厳格化）
- `conftest.py` のリファクタリング
- `appium:dontStopAppOnReset` 対応（アプリの強制 terminate 処理）
- ツール呼び出し処理時のウェイト追加（画面更新待ち）
- `custom_knowhow_sample.txt` のアップデート
- ドキュメント（README.md）の更新

---

### 🗑️ 削除

- 課金状況を詳細表示する機能（シンプル化のため削除）
- Criteria（testsheet.csv から削除）
- 古いLLMロジック

---

### 📦 依存関係

- langchain v1 に対応
- `jarvis-appium-sse` から `appium_tools` に移行

---

### 📁 プロジェクト構成

```
smartestiroid/
├── src/
│   └── smartestiroid/
│       ├── __init__.py
│       ├── config.py
│       ├── conftest.py
│       ├── test_android_app.py
│       ├── models.py
│       ├── workflow.py
│       ├── appium_tools/
│       ├── agents/
│       └── utils/
├── tests/
├── AGENTS.md
├── README.md
├── testsheet.csv
├── testsheet_en.csv
├── capabilities.json
└── pyproject.toml
```

---

### 🔗 関連コミット

<details>
<summary>全コミット一覧（クリックで展開）</summary>

| コミット | 説明 |
|----------|------|
| 53bae91 | テスト進捗をGUI側で表示させるためのログを追加 |
| 07b4d8f | scroll_to_element の返り値を詳細にした |
| 2716e46 | find_element に失敗したときは見つからなかったエラーを文字列で返し、例外は発生させない |
| 969d790 | ログ出力の修正 |
| 0d91e86 | custom_knowhow_sample.txt をアップデート |
| 9374005 | 外部プロジェクトからの利用で構文間違いを修正 |
| 1dcab84 | 外部ライブラリとして利用できるように修正 |
| c7fc499 | testsheet.csv のパスをプロジェクトルートからの相対パスとして解決するように修正 |
| 1920731 | AGENTS.md を追加 |
| e5073be | テストファイルを分割 |
| 67b5d1b | Restructure to src/ layout with integrated appium-tools |
| 1a67c5f | appium-tools を取り込んだ、構成を大きく変更 |
| 6dea42d | テスト実行全体のコスト確認機能を追加 |
| a900d7b | 課金状況がわかる機能を追加 |
| e725b06 | プロンプトのチューニング |
| 2bcb56d | Appiumサーバーとのセッション切断時の例外処理 |
| 9a5b601 | 使用するLLMモデルの指定を明確にした |
| 6387ede | appium:dontStopAppOnReset に対応 |

</details>

---

### 📝 アップグレード手順

```bash
# 依存関係の同期
uv sync

# テスト実行（動作確認）
uv run pytest tests/ -v

# 実機テスト
uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001"
```

---

## v0.0.1 (2025-09-23)

初回リリース
