"""
smartestiroid パッケージのインポートテスト

このテストは smartestiroid が editable モードで正しくインストールされ、
モジュールとして正常にインポートできることを確認します。
"""

import pytest


class TestSmartestiroidImport:
    """smartestiroid パッケージのインポートテスト"""

    def test_import_main_package(self):
        """メインパッケージのインポート"""
        import smartestiroid
        assert smartestiroid is not None

    def test_android_test_file_path(self):
        """ANDROID_TEST_FILE パスの取得"""
        from smartestiroid import ANDROID_TEST_FILE
        assert ANDROID_TEST_FILE is not None
        assert "test_android_app.py" in ANDROID_TEST_FILE

    def test_test_file_backward_compatibility(self):
        """TEST_FILE 後方互換性エイリアス"""
        from smartestiroid import TEST_FILE, ANDROID_TEST_FILE
        assert TEST_FILE == ANDROID_TEST_FILE

    def test_conftest_file_path(self):
        """CONFTEST_FILE パスの取得"""
        from smartestiroid import CONFTEST_FILE
        assert CONFTEST_FILE is not None
        assert "conftest.py" in CONFTEST_FILE

    def test_package_dir_path(self):
        """PACKAGE_DIR パスの取得"""
        from smartestiroid import PACKAGE_DIR
        import os
        assert PACKAGE_DIR is not None
        assert os.path.isdir(PACKAGE_DIR)

    def test_import_config_module(self):
        """config モジュールのインポート"""
        from smartestiroid.config import (
            MODEL_STANDARD,
            MODEL_MINI,
            MODEL_EVALUATION,
            MODEL_EVALUATION_MINI,
            RESULT_PASS,
            RESULT_FAIL,
            RESULT_SKIP,
        )
        assert MODEL_STANDARD == "gpt-4.1"
        assert MODEL_MINI == "gpt-4.1-mini"
        assert MODEL_EVALUATION == "gpt-5"
        assert MODEL_EVALUATION_MINI == "gpt-5-mini"
        assert RESULT_PASS == "RESULT_PASS"
        assert RESULT_FAIL == "RESULT_FAIL"
        assert RESULT_SKIP == "RESULT_SKIP"

    def test_import_models(self):
        """models モジュールのインポート"""
        from smartestiroid.models import PlanExecute, Plan, Response, Act
        assert PlanExecute is not None
        assert Plan is not None
        assert Response is not None
        assert Act is not None

    def test_import_appium_tools(self):
        """appium_tools モジュールのインポート"""
        from smartestiroid import appium_tools
        assert appium_tools is not None

    def test_import_appium_driver(self):
        """appium_driver モジュールのインポート"""
        from smartestiroid.appium_tools import appium_driver
        assert appium_driver is not None

    def test_import_workflow(self):
        """workflow モジュールのインポート"""
        from smartestiroid import workflow
        assert workflow is not None
        # create_workflow_functions 関数の存在確認
        assert hasattr(workflow, 'create_workflow_functions')

    def test_dynamic_model_config(self):
        """動的モデル設定の確認"""
        from smartestiroid import config as cfg
        # 初期状態ではMINIモードでない限り標準モデル
        assert cfg.planner_model in [cfg.MODEL_STANDARD, cfg.MODEL_MINI]
        assert cfg.execution_model in [cfg.MODEL_STANDARD, cfg.MODEL_MINI]
        assert cfg.evaluation_model in [cfg.MODEL_EVALUATION, cfg.MODEL_EVALUATION_MINI]
