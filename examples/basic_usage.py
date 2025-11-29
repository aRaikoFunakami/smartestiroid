#!/usr/bin/env python3
"""
smartestiroid 基本的な使用例

外部プロジェクトから smartestiroid を使用して
Android アプリのテストを実行するシンプルな例です。

使用方法:
    uv run python examples/basic_usage.py
"""

import subprocess
import sys

import smartestiroid


def main():
    """基本的なテスト実行"""
    cmd = [
        "uv", "run", "pytest",
        smartestiroid.ANDROID_TEST_FILE,
        "-k", "TEST_0001",
        "-v",
        "--tb=short",
        "--alluredir", "allure-results",
        "--testsheet", "testsheet.csv",
        "--mini-model",
    ]

    print(f"実行コマンド: {' '.join(cmd)}")
    print(f"テストファイル: {smartestiroid.ANDROID_TEST_FILE}")
    print(f"パッケージディレクトリ: {smartestiroid.PACKAGE_DIR}")
    print()

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
