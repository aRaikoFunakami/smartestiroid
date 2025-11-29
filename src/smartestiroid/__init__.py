"""
SmartestiRoid - AI-powered Android app testing framework

This package provides automated testing capabilities for Android applications
using LLM-powered agents and Appium.
"""

import os

# パッケージのルートディレクトリ
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

# テストファイルのパス
ANDROID_TEST_FILE = os.path.join(PACKAGE_DIR, "test_android_app.py")
TEST_FILE = ANDROID_TEST_FILE  # 後方互換性のためのエイリアス

# conftest.pyのパス
CONFTEST_FILE = os.path.join(PACKAGE_DIR, "conftest.py")

# プロジェクトルート（pyproject.tomlがある場所）
PROJECT_ROOT = os.path.dirname(os.path.dirname(PACKAGE_DIR))

# 主要なクラスとフィクスチャをエクスポート
from .config import (
    MODEL_STANDARD,
    MODEL_MINI,
    MODEL_EVALUATION,
    KNOWHOW_INFO,
    RESULT_PASS,
    RESULT_FAIL,
    RESULT_SKIP,
)

from .models import (
    PlanExecute,
    Plan,
    Response,
    Act,
)

__version__ = "0.1.0"

__all__ = [
    "PACKAGE_DIR",
    "ANDROID_TEST_FILE",
    "TEST_FILE",  # 後方互換性のためのエイリアス
    "CONFTEST_FILE",
    "PROJECT_ROOT",
    "MODEL_STANDARD",
    "MODEL_MINI",
    "MODEL_EVALUATION",
    "KNOWHOW_INFO",
    "RESULT_PASS",
    "RESULT_FAIL",
    "RESULT_SKIP",
    "PlanExecute",
    "Plan",
    "Response",
    "Act",
]
