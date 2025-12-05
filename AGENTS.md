# AGENTS.md - SmartestiRoid 開発ガイド

このドキュメントはAIエージェント（GitHub Copilot、Claude等）がこのプロジェクトで作業する際のガイドラインです。

---

## 📁 プロジェクト構成

```
smartestiroid/
├── src/
│   └── smartestiroid/            # メインパッケージ
│       ├── __init__.py           # パッケージエクスポート
│       ├── conftest.py           # pytest設定・フィクスチャ
│       ├── test_android_app.py   # メインテストファイル
│       ├── config.py             # 設定（モデル、knowhow等）
│       ├── models.py             # データモデル定義
│       ├── workflow.py           # ワークフロー定義
│       ├── appium_tools/         # Appium操作ツール群
│       ├── agents/               # プランナー/リプランナー
│       └── utils/                # ユーティリティ
├── tests/                        # 単体テスト
│   ├── conftest.py               # テスト用フィクスチャ
│   ├── test_appium_tools_session.py      # セッション・基本操作テスト
│   ├── test_appium_tools_element.py      # 要素操作テスト
│   ├── test_appium_tools_navigation.py   # ナビゲーションテスト
│   ├── test_appium_tools_app.py          # アプリ管理テスト
│   ├── test_appium_tools_device.py       # デバイス状態テスト
│   └── test_appium_tools_token_counter.py # トークンカウンターテスト
├── testsheet.csv                 # テストケース定義（日本語）
├── testsheet_en.csv              # テストケース定義（英語）
├── capabilities.json             # Appium設定
├── pytest.ini                    # pytest設定
└── pyproject.toml                # プロジェクト設定
```

---

## 🔧 パッケージ管理（uv）

このプロジェクトは **uv** を使用してパッケージを管理します。

### 依存ライブラリの追加

```bash
# 新しいライブラリを追加
uv add <package-name>

# 開発用ライブラリを追加
uv add --dev <package-name>

# 例
uv add requests
uv add --dev pytest-cov
```

### 依存関係の同期

```bash
uv sync
```

### コマンドの実行

すべてのPythonコマンドは `uv run` を使用して実行します：

```bash
# pytest実行
uv run pytest

# Python スクリプト実行
uv run python script.py

# 特定のモジュール実行
uv run python -m module_name
```

---

## 🧪 テスト

### テストファイルの配置

- **単体テスト**: `tests/` ディレクトリに配置
- **統合テスト（メインテスト）**: `src/smartestiroid/test_android_app.py`

### テストファイル命名規則

```
tests/
├── conftest.py                           # 共通フィクスチャ
├── test_appium_tools_session.py          # セッション・基本操作テスト（最小限）
├── test_appium_tools_element.py          # 要素操作テスト
├── test_appium_tools_navigation.py       # ナビゲーション・スクロールテスト
├── test_appium_tools_app.py              # アプリ管理テスト
├── test_appium_tools_device.py           # デバイス状態テスト
├── test_appium_tools_token_counter.py    # トークンカウンターテスト（Android不要）
└── test_xml_compressor.py                # XML圧縮テスト（Android不要）
```

### テスト実行

```bash
# 全テスト実行
uv run pytest

# tests/ のみ実行
uv run pytest tests/

# 最小限のテスト（セッション・基本操作のみ）
uv run pytest tests/test_appium_tools_session.py

# 要素操作テスト
uv run pytest tests/test_appium_tools_element.py

# ナビゲーションテスト
uv run pytest tests/test_appium_tools_navigation.py

# アプリ管理テスト
uv run pytest tests/test_appium_tools_app.py

# デバイス状態テスト
uv run pytest tests/test_appium_tools_device.py

# トークンカウンターテスト（Android不要）
uv run pytest tests/test_appium_tools_token_counter.py

# XML圧縮テスト（Android不要）
uv run pytest tests/test_xml_compressor.py

# 特定のテストを実行
uv run pytest tests/test_appium_tools_session.py -k "test_take_screenshot"

# 詳細出力
uv run pytest tests/ -v

# メインテスト（Android接続必要）
uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001"

# 高速モードで実行
uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001" --mini-model
```

---

## ⚠️ xml_compressor 更新時の必須事項

`src/smartestiroid/appium_tools/xml_compressor.py` を更新した場合：

1. **テスト実行必須**: `uv run pytest tests/test_xml_compressor.py -v` で100%パス
2. **基本方針**: 「削除するものだけを明確に指定」（未知の属性・クラスは削除しない）
3. **属性定義の参照**: UIAutomator2の公式属性定義を参照してDELETE_ATTRIBUTESを更新すること
   - https://github.com/appium/appium-uiautomator2-server/blob/master/app/src/main/java/io/appium/uiautomator2/utils/Attribute.java
4. **詳細**: アルゴリズムの詳細は `xml_compressor.py` 冒頭のコメントを参照

---

## ⚠️ appium_tools 更新時の必須事項

`src/smartestiroid/appium_tools/` を更新した場合は、**必ず以下を実行**してください：

### 1. 関連テストの追加・更新

新しい関数を追加した場合、適切なテストファイルにテストを追加：

| 機能カテゴリ | テストファイル |
|-------------|---------------|
| セッション・基本操作 | `test_appium_tools_session.py` |
| 要素操作 | `test_appium_tools_element.py` |
| ナビゲーション・スクロール | `test_appium_tools_navigation.py` |
| アプリ管理 | `test_appium_tools_app.py` |
| デバイス状態 | `test_appium_tools_device.py` |
| トークンカウンター | `test_appium_tools_token_counter.py` |
| XML圧縮 | `test_xml_compressor.py` |

```python
@pytest.mark.asyncio
async def test_new_function(driver_session):
    """新しい関数のテスト"""
    result = await new_function(param)
    assert result is not None
```

### 2. テストの実行

```bash
# 最小限のテスト（まずこれを実行）
uv run pytest tests/test_appium_tools_session.py -v

# 変更した機能に関連するテストを実行
uv run pytest tests/test_appium_tools_<カテゴリ>.py -v

# または全テスト
uv run pytest tests/ -v
```

### 3. 動作確認

```bash
# インポートテスト
uv run python -c "from smartestiroid.appium_tools import appium_driver; print('OK')"

# 実機テスト（Android接続時）
uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001"
```

---

## 📝 コーディング規約

### インポート順序

```python
# 1. 標準ライブラリ
import asyncio
import os

# 2. サードパーティ
import pytest
from langchain_openai import ChatOpenAI

# 3. ローカルモジュール（パッケージ内では相対インポート）
from .appium_tools import appium_driver
from .config import MODEL_STANDARD

# または外部からの利用時は絶対インポート
from smartestiroid.appium_tools import appium_driver
from smartestiroid.config import MODEL_STANDARD
```

### 型ヒント

```python
from typing import Dict, Any, Optional

async def example_function(
    param1: str,
    param2: Optional[int] = None
) -> Dict[str, Any]:
    ...
```

### ⚠️ 必須オブジェクトと互換性に関するルール

開発中のプロジェクトであるため、**無駄な互換性コードは書かない**ことを心がける。

1. **ObjectiveProgressは必須**
   - `ObjectiveProgress`は進捗管理の核となるオブジェクト
   - 全ての`analyze_state`, `decide_action`, `build_plan`, `build_response`, `replan`で必須
   - `Optional[ObjectiveProgress] = None`やフォールバックコードは禁止
   
   ```python
   # ❌ 悪い例（フォールバック付き）
   def build_plan(objective_progress: Optional[ObjectiveProgress] = None):
       if objective_progress:
           remaining = objective_progress.get_current_remaining_plan()
       else:
           remaining = original_plan[len(past_steps):]  # フォールバック
   
   # ✅ 良い例（必須）
   def build_plan(objective_progress: ObjectiveProgress):
       remaining = objective_progress.get_current_remaining_plan()
   ```

2. **フォールバックコードは不具合の温床**
   - 「なくても動く」コードは、本来のロジックが正しく動作しているか検証できない
   - 問題が発覚したとき、どちらのコードパスで問題が起きているか分からなくなる

3. **cleanなコードを優先**
   - 開発中は互換性より、正しく動作するシンプルなコードを優先する
   - 後方互換性が必要になったら、その時点で対応する

### ⚠️ SLog（StructuredLogger）の使用ルール

`SLog.error` / `SLog.warn` / `SLog.info` / `SLog.debug` は**すべて同じ引数順序**です：

```python
SLog.error(category, event, data, message)
SLog.warn(category, event, data, message)
SLog.info(category, event, data, message)
```

**最初の2引数（category, event）は必須です。**

```python
# ✅ 正しい使い方
except Exception as e:
    SLog.error(
        LogCategory.PLAN,           # 1. category（必須）
        LogEvent.FAIL,              # 2. event（必須）
        {"error": str(e)},          # 3. data（オプション）
        f"計画生成失敗: {e}"          # 4. message（オプション）
    )

# ❌ 間違い - categoryとeventが欠落
SLog.error({"error": str(e)}, "エラーメッセージ")

# ❌ 間違い - dataをcategory位置に渡している
SLog.warn({"key": "value"}, "警告メッセージ")
```

---

## 🚀 よく使うコマンド

```bash
# 依存関係の同期
uv sync

# テスト実行
uv run pytest tests/ -v

# メインテスト実行（Android接続必要）
uv run pytest src/smartestiroid/test_android_app.py

# Allureレポート表示
allure serve allure-results

# インポート確認
uv run python -c "from smartestiroid.appium_tools import appium_driver; print('OK')"
```

---

## 📦 外部プロジェクトからの利用

smartestiroid は editable インストールで外部プロジェクトから利用できます。

```bash
# 外部プロジェクトで依存関係として追加
uv add smartestiroid --path /path/to/smartestiroid --editable
```

**注意点**:
- editable モードでは、smartestiroid のソース変更が即座に反映されます
- `uv sync --reinstall-package smartestiroid` は不要です
- 相対パス（`./testsheet.csv` など）は実行時のカレントディレクトリ基準で解決されます

---

## 📋 チェックリスト

コードを変更した際は、以下を確認してください：

- [ ] `uv sync` で依存関係が正しく同期されている
- [ ] `uv run pytest tests/` でテストがパスする
- [ ] appium_tools を変更した場合、関連テストを追加・実行した
- [ ] 新しい依存ライブラリは `uv add` で追加した
- [ ] パッケージ内のインポートは相対インポート（`from .config import ...`）を使用している
