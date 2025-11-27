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
# 環境変数 USE_MINI_MODEL=1 を設定すると自動的にminiモデルに切り替わります
MODEL_STANDARD = "gpt-4.1"              # 標準モデル（高精度）
MODEL_MINI = "gpt-4.1-mini"             # Miniモデル（高速・低コスト）
MODEL_EVALUATION = "gpt-5"              # 評価用モデル（標準時）
MODEL_EVALUATION_MINI = "gpt-5-mini"    # 評価用モデル（Mini時）

# Environment-based model selection
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
RESULT_NG = "RESULT_NG"


# --- Default Knowhow Information ---
KNOWHOW_INFO = """
重要な前提条件:
* 事前に appium とは接続されています
* アプリ起動時にプライバシーポリシーが表示された場合、同意操作を行ってください
* アプリ起動時にディスクリーマーポリシーが表示された場合、同意操作を行ってください
* 必要に応じてスクロール操作でポリシーを全文表示させてから同意してください
* アプリ起動時に初期設定ダイアログが表示された場合、適切に対応してください
* アプリ起動時に広告ダイアログが表示された場合、閉じる操作を行ってください

ツール使用のルール - 必ず守ること:
* アプリの操作は、必ずツールを使用して行いなさい
* アプリの起動や終了も、必ずツールを使用して行いなさい
* アプリ実行/起動: activate_app を使用せよ (但し、既に指定のアプリが起動している場合はスキップ処理で良い)
* アプリ終了: terminate_app を使用せよ
* 入力確定: press_keycode で <Enter> を使用せよ

禁止事項:
* アカウント情報の入力やログイン操作は行わないでください
* 新しいアカウントの作成や登録は行わないでください
"""
