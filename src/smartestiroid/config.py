"""
Configuration constants for SmartestiRoid test framework.

This module contains all configuration constants including:
- LLM model settings
- OpenAI API settings
- Test result constants
- Default knowhow information
"""

import os


# --- OpenAI API Settings ---
OPENAI_TIMEOUT = 180.0  # 180秒
OPENAI_MAX_RETRIES = 1  # リトライ1回


# --- LLM Model Configuration ---
# 環境変数 USE_MINI_MODEL=1 または pytest --mini-model で自動的にminiモデルに切り替わります
#
# ⚠️ 重要: モデル変数の使用方法
# planner_model, execution_model, evaluation_model は pytest_configure で動的に変更されます。
# そのため、他のモジュールからは以下のように使用してください：
#
#   NG: from .config import planner_model  # インポート時の値が固定される
#   OK: from . import config as cfg; cfg.planner_model  # 常に最新値を参照
#
MODEL_STANDARD = "gpt-4.1"              # 標準モデル（高精度）
MODEL_MINI = "gpt-4.1-mini"             # Miniモデル（高速・低コスト）
MODEL_EVALUATION = "gpt-5"              # 評価用モデル（標準時）
MODEL_EVALUATION_MINI = "gpt-5-mini"    # 評価用モデル（Mini時）

# Environment-based model selection
# 注意: これらの変数は conftest.py の pytest_configure で --mini-model オプションに応じて更新されます
use_mini_model = os.environ.get("USE_MINI_MODEL", "0") == "1"
if use_mini_model:
    planner_model = MODEL_MINI
    execution_model = MODEL_MINI
    evaluation_model = MODEL_EVALUATION_MINI
else:
    planner_model = MODEL_STANDARD
    execution_model = MODEL_STANDARD
    evaluation_model = MODEL_EVALUATION


# --- Test Result Status Constants ---
RESULT_PASS = "RESULT_PASS"
RESULT_SKIP = "RESULT_SKIP"
RESULT_FAIL = "RESULT_FAIL"


# --- Default Knowhow Information ---
# デフォルトのノウハウ情報はcustom_knowhow_example.txtから読み込みます
# ツールの使い方に関する技術的なルール（send_keys vs press_keycodeなど）は
# conftest.pyのagent_executorプロンプトで定義しています
def _load_default_knowhow() -> str:
    """custom_knowhow_example.txtからデフォルトのノウハウ情報を読み込む"""
    from pathlib import Path
    
    # プロジェクトルートのcustom_knowhow_example.txtを探す
    config_dir = Path(__file__).parent  # src/smartestiroid/
    project_root = config_dir.parent.parent  # プロジェクトルート
    knowhow_file = project_root / "custom_knowhow_example.txt"
    
    if knowhow_file.exists():
        return knowhow_file.read_text(encoding="utf-8")
    else:
        # ファイルが見つからない場合のフォールバック
        return """
重要な前提条件:
* 事前に appium とは接続されています

ロケーター戦略の制約（必ず守ること）:
* Androidでは accessibility_id は使用禁止
* 要素を指定する際は 'id' (resource-id), 'xpath', または 'uiautomator' を使用

厳格ルール:
* アカウント情報の入力禁止
* パスワードの入力禁止
* ログイン操作は禁止
* アカウントの作成禁止
"""

KNOWHOW_INFO = _load_default_knowhow()
