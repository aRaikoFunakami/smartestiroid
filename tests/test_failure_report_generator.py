"""
failure_report_generator のユニットテスト

Androidデバイス不要のテストです。
LLMはモックして、実際のAPI呼び出しは行いません。
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from smartestiroid.utils.failure_report_generator import (
    FailureReportGenerator,
    FailureAnalysis,
    FailedTestInfo,
    CATEGORY_DISPLAY,
)


# テスト用のJSONLデータ
SAMPLE_FAILED_TEST_JSONL = [
    {"ts": "2025-12-05 19:00:00", "cat": "TEST", "evt": "START", "data": {"test_id": "TEST_0001", "title": "ログイン画面テスト", "steps": "1. ログインボタンをタップ\n2. ユーザー名を入力", "expected": "ログインが成功する"}},
    {"ts": "2025-12-05 19:00:01", "cat": "SCREEN", "evt": "UPDATE", "data": {"image_path": "/path/to/img", "image_filename": "screen_001.png", "label": "initial_screen"}},
    {"ts": "2025-12-05 19:00:02", "cat": "STEP", "evt": "COMPLETE", "data": {"step": "ログインボタンをタップ", "success": True}},
    {"ts": "2025-12-05 19:00:03", "cat": "LLM", "evt": "VERIFY_RESPONSE", "data": {"phase": 1, "success": True, "reason": "ボタンが表示されている"}},
    {"ts": "2025-12-05 19:00:05", "cat": "STEP", "evt": "FAIL", "data": {"step": "ユーザー名を入力", "error": "NoSuchElementException: Element not found - input field"}},
    {"ts": "2025-12-05 19:00:06", "cat": "TEST", "evt": "FAIL", "data": {"error": "テスト失敗: 要素が見つかりません"}},
    {"ts": "2025-12-05 19:00:07", "cat": "SESSION", "evt": "END", "data": {}},
]

SAMPLE_SUCCESS_TEST_JSONL = [
    {"ts": "2025-12-05 19:00:00", "cat": "TEST", "evt": "START", "data": {"test_id": "TEST_0002", "title": "成功テスト", "steps": "1. ボタンをタップ", "expected": "成功する"}},
    {"ts": "2025-12-05 19:00:02", "cat": "STEP", "evt": "COMPLETE", "data": {"step": "ボタンをタップ", "success": True}},
    {"ts": "2025-12-05 19:00:03", "cat": "TEST", "evt": "COMPLETE", "data": {"result": "PASS"}},
    {"ts": "2025-12-05 19:00:04", "cat": "SESSION", "evt": "END", "data": {}},
]

SAMPLE_APPIUM_ERROR_JSONL = [
    {"ts": "2025-12-05 19:00:00", "cat": "TEST", "evt": "START", "data": {"test_id": "TEST_0003", "title": "Appiumエラーテスト", "steps": "1. スクロール", "expected": "動作する"}},
    {"ts": "2025-12-05 19:00:05", "cat": "STEP", "evt": "FAIL", "data": {"step": "スクロール", "error": "InvalidContextError: An unknown server-side error occurred - cannot be proxied to UiAutomator2 instrumentationprocess"}},
    {"ts": "2025-12-05 19:00:06", "cat": "TEST", "evt": "FAIL", "data": {}},
    {"ts": "2025-12-05 19:00:07", "cat": "SESSION", "evt": "END", "data": {}},
]


@pytest.fixture
def temp_log_dir():
    """一時ログディレクトリを作成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir) / "run_20251205_190000"
        log_dir.mkdir()
        yield log_dir


def write_jsonl(log_dir: Path, entries: list, filename: str = "session.jsonl") -> Path:
    """JSONLファイルを書き込む"""
    log_file = log_dir / filename
    with open(log_file, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_file


class TestFailureAnalysisModel:
    """FailureAnalysis Pydanticモデルのテスト"""
    
    def test_valid_analysis(self):
        """正常なFailureAnalysisを作成できる"""
        analysis = FailureAnalysis(
            failure_category="ELEMENT_NOT_FOUND",
            summary="要素が見つかりませんでした",
            root_causes=["セレクターが間違っている"],
            recommendations=["XPathを確認する"],
            confidence="HIGH"
        )
        assert analysis.failure_category == "ELEMENT_NOT_FOUND"
        assert analysis.confidence == "HIGH"
    
    def test_invalid_category(self):
        """無効なカテゴリはエラーになる"""
        with pytest.raises(Exception):  # Pydantic ValidationError
            FailureAnalysis(
                failure_category="INVALID_CATEGORY",
                summary="test",
                root_causes=["test"],
                recommendations=["test"],
                confidence="HIGH"
            )
    
    def test_invalid_confidence(self):
        """無効な信頼度はエラーになる"""
        with pytest.raises(Exception):
            FailureAnalysis(
                failure_category="UNKNOWN",
                summary="test",
                root_causes=["test"],
                recommendations=["test"],
                confidence="VERY_HIGH"
            )


class TestFailedTestInfo:
    """FailedTestInfoデータクラスのテスト"""
    
    def test_basic_creation(self):
        """基本的なFailedTestInfoを作成できる"""
        info = FailedTestInfo(
            test_id="TEST_001",
            title="テスト",
            steps="1. ステップ1",
            expected="成功する"
        )
        assert info.test_id == "TEST_001"
        assert info.screenshots == []
        assert info.completed_steps == []


class TestFailureReportGenerator:
    """FailureReportGeneratorのテスト"""
    
    def test_load_log_entries(self, temp_log_dir):
        """JSONLログの読み込み"""
        write_jsonl(temp_log_dir, SAMPLE_FAILED_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        assert len(generator.entries) == len(SAMPLE_FAILED_TEST_JSONL)
    
    def test_extract_failed_test(self, temp_log_dir):
        """失敗テストの抽出"""
        write_jsonl(temp_log_dir, SAMPLE_FAILED_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        assert len(generator.failed_tests) == 1
        
        failed = generator.failed_tests[0]
        assert failed.test_id == "TEST_0001"
        assert failed.title == "ログイン画面テスト"
        assert failed.failed_step == "ユーザー名を入力"
        assert "NoSuchElementException" in (failed.error_message or "")
        assert failed.error_type == "NoSuchElementError"
    
    def test_no_failed_tests(self, temp_log_dir):
        """失敗テストがない場合"""
        write_jsonl(temp_log_dir, SAMPLE_SUCCESS_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        assert len(generator.failed_tests) == 0
    
    def test_appium_error_detection(self, temp_log_dir):
        """Appiumエラーの検出"""
        write_jsonl(temp_log_dir, SAMPLE_APPIUM_ERROR_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        assert len(generator.failed_tests) == 1
        
        failed = generator.failed_tests[0]
        assert failed.test_id == "TEST_0003"
        assert failed.error_type == "AppiumConnectionError"
    
    @patch.object(FailureReportGenerator, '_analyze_with_llm', return_value=None)
    @patch.object(FailureReportGenerator, '_analyze_failure_trends', return_value=None)
    def test_generate_report_no_failures(self, mock_trends, mock_llm, temp_log_dir):
        """失敗がない場合のレポート生成"""
        write_jsonl(temp_log_dir, SAMPLE_SUCCESS_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        report_path = generator.generate_report()
        
        assert report_path.exists()
        content = report_path.read_text()
        assert "すべてのテストが成功しました" in content
    
    @patch.object(FailureReportGenerator, '_analyze_with_llm', return_value=None)
    @patch.object(FailureReportGenerator, '_analyze_failure_trends', return_value=None)
    def test_generate_report_with_failures(self, mock_trends, mock_llm, temp_log_dir):
        """失敗がある場合のレポート生成（LLMはモック）"""
        write_jsonl(temp_log_dir, SAMPLE_FAILED_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        report_path = generator.generate_report()
        
        assert report_path.exists()
        assert report_path.name == "failure_report.md"
        
        content = report_path.read_text()
        
        # ヘッダーとサマリー
        assert "# テスト失敗レポート" in content
        assert "## テスト結果サマリー" in content
        assert "テスト総数" in content
        assert "成功率" in content
        
        # カテゴリ別サマリー
        assert "## 失敗カテゴリ別サマリー" in content
        
        # テスト詳細
        assert "TEST_0001" in content
        assert "ログイン画面テスト" in content
        assert "失敗概要" in content
        assert "原因詳細" in content
        assert "推奨対応" in content
    
    @patch.object(FailureReportGenerator, '_analyze_with_llm', return_value=None)
    @patch.object(FailureReportGenerator, '_analyze_failure_trends', return_value=None)
    def test_fallback_analysis_element_not_found(self, mock_trends, mock_llm, temp_log_dir):
        """フォールバック分析 - 要素が見つからない"""
        write_jsonl(temp_log_dir, SAMPLE_FAILED_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        # レポート生成（分析が実行される）
        generator.generate_report()
        
        failed = generator.failed_tests[0]
        assert failed.analysis is not None
        assert failed.analysis.failure_category == "ELEMENT_NOT_FOUND"
    
    @patch.object(FailureReportGenerator, '_analyze_with_llm', return_value=None)
    @patch.object(FailureReportGenerator, '_analyze_failure_trends', return_value=None)
    def test_fallback_analysis_appium_error(self, mock_trends, mock_llm, temp_log_dir):
        """フォールバック分析 - Appiumエラー"""
        write_jsonl(temp_log_dir, SAMPLE_APPIUM_ERROR_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        generator.generate_report()
        
        failed = generator.failed_tests[0]
        assert failed.analysis is not None
        assert failed.analysis.failure_category == "APPIUM_CONNECTION_ERROR"
    
    def test_screenshot_tracking(self, temp_log_dir):
        """スクリーンショットの追跡"""
        write_jsonl(temp_log_dir, SAMPLE_FAILED_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        failed = generator.failed_tests[0]
        assert len(failed.screenshots) == 1
        assert failed.screenshots[0]["filename"] == "screen_001.png"
    
    def test_completed_steps_tracking(self, temp_log_dir):
        """完了ステップの追跡"""
        write_jsonl(temp_log_dir, SAMPLE_FAILED_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        failed = generator.failed_tests[0]
        assert len(failed.completed_steps) == 1
        assert "ログインボタンをタップ" in failed.completed_steps[0]
    
    def test_verification_phase_tracking(self, temp_log_dir):
        """検証フェーズの追跡"""
        write_jsonl(temp_log_dir, SAMPLE_FAILED_TEST_JSONL)
        
        generator = FailureReportGenerator(log_dir=temp_log_dir)
        
        failed = generator.failed_tests[0]
        assert failed.verification_phase1 is not None
        assert failed.verification_phase1["success"] is True
    
    def test_no_jsonl_file_error(self, temp_log_dir):
        """JSONLファイルがない場合のエラー"""
        with pytest.raises(FileNotFoundError):
            FailureReportGenerator(log_dir=temp_log_dir)


class TestCategoryDisplay:
    """カテゴリ表示名のテスト"""
    
    def test_all_categories_have_display_names(self):
        """すべてのカテゴリに表示名がある"""
        expected_categories = [
            "APPIUM_CONNECTION_ERROR",
            "ELEMENT_NOT_FOUND",
            "VERIFICATION_FAILED",
            "TIMEOUT",
            "LLM_JUDGMENT_ERROR",
            "APP_CRASH",
            "SESSION_ERROR",
            "UNKNOWN",
        ]
        
        for cat in expected_categories:
            assert cat in CATEGORY_DISPLAY
            assert CATEGORY_DISPLAY[cat]  # 空文字でない
