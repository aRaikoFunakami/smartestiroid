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
KNOWHOW_INFO = """
重要な前提条件:
* 事前に appium とは接続されています

ツール使用のルール - 必ず守ること:
* アプリの操作は、必ずツールを使用して行いなさい
* アプリ実行/起動: activate_app を使用せよ (但し、既に指定のアプリが起動している場合はスキップ処理で良い)
* アプリ終了: terminate_app を使用せよ
* URLバー等での入力確定: press_keycode で入力した文字列を press_keycode で <Enter> キーで確定せよ

補助ルール:
* プライバシーポリシーが表示された場合、同意操作を行え
* ディスクリーマーポリシーが表示された場合、同意操作を行え
* 初期設定ダイアログが表示された場合はデフォルト設定で対応せよ
* 広告ダイアログが表示された場合は閉じる操作を行え

ロケーター戦略の制約 (必ず守ること)
* Androidでは accessibility_id は使用禁止
* 要素を指定する際は必ず 'id' (resource-id), 'xpath', または 'uiautomator' を使用せよ
* 例: {'by': 'id', 'value': 'com.android.chrome:id/menu_button'}
* 例: {'by': 'xpath', 'value': '//android.widget.Button[@content-desc="More options"]'}

厳格ルール:
* アカウント情報の入力禁止
* パスワードの入力禁止
* ログイン操作は禁止
* アカウントの作成禁止
"""
