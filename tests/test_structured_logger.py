"""StructuredLogger のテスト"""

import json
import tempfile
from pathlib import Path

import pytest

from smartestiroid.utils.structured_logger import (
    StructuredLogger,
    SLog,
    LogCategory,
    LogEvent,
)


class TestStructuredLogger:
    """StructuredLogger の単体テスト"""

    def test_log_creates_jsonl_file(self):
        """JSONLファイルが正しく作成されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            SLog.init("TEST_0001", output_dir)

            try:
                SLog.log(
                    category=LogCategory.STEP,
                    event=LogEvent.START,
                    data={"step": "click_element"},
                    message="テストステップ開始"
                )

                log_file = SLog.get_log_file()
                assert log_file is not None
                assert log_file.exists()
                assert log_file.suffix == ".jsonl"
                assert "TEST_0001" in log_file.name
            finally:
                SLog.close()

    def test_log_entry_format(self):
        """ログエントリが正しいフォーマットであること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            SLog.init("TEST_0002", output_dir)

            try:
                SLog.log(
                    category=LogCategory.TOOL,
                    event=LogEvent.COMPLETE,
                    data={"tool": "click_element", "duration_ms": 140},
                    message="ツール完了"
                )

                log_file = SLog.get_log_file()
                assert log_file is not None

                # ファイル内容を確認
                content = log_file.read_text(encoding="utf-8")
                lines = [line for line in content.strip().split("\n") if line]

                # 最後のエントリを検証（最初はSESSION.START）
                last_entry = json.loads(lines[-1])
                assert "ts" in last_entry
                assert last_entry["lvl"] == "INFO"
                assert last_entry["cat"] == "TOOL"
                assert last_entry["evt"] == "COMPLETE"
                assert last_entry["data"]["tool"] == "click_element"
                assert last_entry["data"]["duration_ms"] == 140
            finally:
                SLog.close()

    def test_log_levels(self):
        """各ログレベルが正しく記録されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            SLog.init("TEST_0003", output_dir)

            try:
                SLog.info(LogCategory.STEP, LogEvent.START, message="INFO")
                SLog.warn(LogCategory.SCREEN, LogEvent.INCONSISTENCY_DETECTED, message="WARN")
                SLog.error(LogCategory.ERROR, LogEvent.FAIL, message="ERROR")
                SLog.debug(LogCategory.LLM, LogEvent.REQUEST, data={"prompt": "test"})

                log_file = SLog.get_log_file()
                assert log_file is not None

                content = log_file.read_text(encoding="utf-8")
                lines = [line for line in content.strip().split("\n") if line]

                # ログレベルを確認
                levels = [json.loads(line)["lvl"] for line in lines]
                assert "INFO" in levels
                assert "WARN" in levels
                assert "ERROR" in levels
                assert "DEBUG" in levels
            finally:
                SLog.close()

    def test_console_output_has_icon(self, capsys):
        """コンソール出力にアイコンが付くこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            SLog.init("TEST_0004", output_dir)

            try:
                SLog.log(
                    category=LogCategory.STEP,
                    event=LogEvent.COMPLETE,
                    message="ステップ完了"
                )

                captured = capsys.readouterr()
                # ✅ アイコンが含まれていること
                assert "✅" in captured.out
                assert "ステップ完了" in captured.out
            finally:
                SLog.close()

    def test_log_category_prefix(self, capsys):
        """コンソール出力にカテゴリプレフィックスが付くこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            SLog.init("TEST_0005", output_dir)

            try:
                SLog.log(
                    category=LogCategory.TOOL,
                    event=LogEvent.START,
                    message="ツール開始"
                )

                captured = capsys.readouterr()
                assert "[TOOL]" in captured.out
            finally:
                SLog.close()

    def test_set_enabled(self):
        """ログ出力の有効/無効が切り替えられること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            SLog.init("TEST_0006", output_dir)

            try:
                # ログを無効化
                SLog.set_enabled(False)
                SLog.log(
                    category=LogCategory.STEP,
                    event=LogEvent.START,
                    data={"disabled": True},
                    message="これは出力されない"
                )

                # ログを有効化
                SLog.set_enabled(True)
                SLog.log(
                    category=LogCategory.STEP,
                    event=LogEvent.END,
                    data={"enabled": True},
                    message="これは出力される"
                )

                log_file = SLog.get_log_file()
                assert log_file is not None

                content = log_file.read_text(encoding="utf-8")
                assert '"disabled": true' not in content
                assert '"enabled": true' in content
            finally:
                SLog.set_enabled(True)  # 元に戻す
                SLog.close()

    def test_alias_slog(self):
        """SLogエイリアスが正しく動作すること"""
        assert SLog is StructuredLogger

    def test_log_categories_defined(self):
        """LogCategoryの定数が定義されていること"""
        assert LogCategory.TEST == "TEST"
        assert LogCategory.STEP == "STEP"
        assert LogCategory.TOOL == "TOOL"
        assert LogCategory.LLM == "LLM"
        assert LogCategory.SCREEN == "SCREEN"

    def test_log_events_defined(self):
        """LogEventの定数が定義されていること"""
        assert LogEvent.START == "START"
        assert LogEvent.END == "END"
        assert LogEvent.COMPLETE == "COMPLETE"
        assert LogEvent.FAIL == "FAIL"
        assert LogEvent.INCONSISTENCY_DETECTED == "INCONSISTENCY_DETECTED"
