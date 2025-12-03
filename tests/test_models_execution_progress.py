"""
ExecutionProgress と関連モデルのテスト
"""

import pytest
import time
from smartestiroid.models import (
    ToolCallRecord,
    StepExecutionRecord,
    ExecutionProgress,
)


class TestToolCallRecord:
    """ToolCallRecordのテスト"""
    
    def test_create_tool_call_record(self):
        """ToolCallRecordの作成"""
        record = ToolCallRecord(
            tool_name="tap_element",
            input='{"selector": "//button[@text=\\"OK\\"]"}',
            output="タップ成功",
            start_time=time.time(),
            end_time=time.time() + 0.5,
        )
        assert record.tool_name == "tap_element"
        assert record.error is None
        assert record.output == "タップ成功"
    
    def test_tool_call_with_error(self):
        """エラーを含むToolCallRecord"""
        record = ToolCallRecord(
            tool_name="tap_element",
            input='{"selector": "//invalid"}',
            error="Element not found",
            start_time=time.time(),
        )
        assert record.error == "Element not found"
        assert record.output is None


class TestStepExecutionRecord:
    """StepExecutionRecordのテスト"""
    
    def test_create_step_record(self):
        """StepExecutionRecordの作成"""
        record = StepExecutionRecord(
            step_index=0,
            step_text="OKボタンをタップする",
        )
        assert record.step_index == 0
        assert record.step_text == "OKボタンをタップする"
        assert record.status == "pending"
        assert len(record.tool_calls) == 0
    
    def test_step_with_multiple_tool_calls(self):
        """複数ツール呼び出しを含むステップ"""
        record = StepExecutionRecord(
            step_index=1,
            step_text="テキストを入力してボタンをタップする",
            status="completed",
            tool_calls=[
                ToolCallRecord(
                    tool_name="send_keys",
                    input='{"text": "hello"}',
                    output="入力成功",
                    start_time=time.time(),
                ),
                ToolCallRecord(
                    tool_name="tap_element",
                    input='{"selector": "//button"}',
                    output="タップ成功",
                    start_time=time.time(),
                ),
            ],
        )
        assert record.status == "completed"
        assert len(record.tool_calls) == 2
        assert record.tool_calls[0].tool_name == "send_keys"
        assert record.tool_calls[1].tool_name == "tap_element"


class TestExecutionProgress:
    """ExecutionProgressのテスト"""
    
    def test_create_empty_progress(self):
        """空のExecutionProgress作成"""
        progress = ExecutionProgress()
        assert len(progress.original_plan) == 0
        assert len(progress.step_records) == 0
        assert progress.current_step_index == 0
    
    def test_create_with_plan(self):
        """計画を含むExecutionProgress作成"""
        plan = [
            "アプリを起動する",
            "ログインボタンをタップする",
            "認証情報を入力する",
        ]
        progress = ExecutionProgress(original_plan=plan)
        assert len(progress.original_plan) == 3
        assert progress.original_plan[0] == "アプリを起動する"
    
    def test_get_completed_count(self):
        """完了ステップ数の取得"""
        progress = ExecutionProgress(
            original_plan=["Step 1", "Step 2", "Step 3"],
            step_records=[
                StepExecutionRecord(step_index=0, step_text="Step 1", status="completed"),
                StepExecutionRecord(step_index=1, step_text="Step 2", status="completed"),
                StepExecutionRecord(step_index=2, step_text="Step 3", status="in_progress"),
            ],
        )
        assert progress.get_completed_count() == 2
    
    def test_get_total_tool_calls(self):
        """ツール呼び出し総数の取得"""
        progress = ExecutionProgress(
            original_plan=["Step 1", "Step 2"],
            step_records=[
                StepExecutionRecord(
                    step_index=0,
                    step_text="Step 1",
                    status="completed",
                    tool_calls=[
                        ToolCallRecord(tool_name="tool1", input="{}", start_time=time.time()),
                        ToolCallRecord(tool_name="tool2", input="{}", start_time=time.time()),
                    ],
                ),
                StepExecutionRecord(
                    step_index=1,
                    step_text="Step 2",
                    status="completed",
                    tool_calls=[
                        ToolCallRecord(tool_name="tool3", input="{}", start_time=time.time()),
                    ],
                ),
            ],
        )
        assert progress.get_total_tool_calls() == 3
    
    def test_get_progress_summary(self):
        """進捗サマリーの取得"""
        progress = ExecutionProgress(
            original_plan=["OKボタンをタップ", "次へボタンをタップ"],
            step_records=[
                StepExecutionRecord(
                    step_index=0,
                    step_text="OKボタンをタップ",
                    status="completed",
                    tool_calls=[
                        ToolCallRecord(
                            tool_name="tap_element",
                            input='{"selector": "OK"}',
                            output="成功",
                            start_time=time.time(),
                        ),
                    ],
                ),
                StepExecutionRecord(
                    step_index=1,
                    step_text="次へボタンをタップ",
                    status="in_progress",
                    tool_calls=[],
                ),
            ],
        )
        summary = progress.get_progress_summary()
        
        assert "計画ステップ: 1/2 完了" in summary
        assert "ツール呼び出し合計: 1回" in summary
        assert "✅ ステップ1:" in summary
        assert "🔄 ステップ2:" in summary
        assert "tap_element" in summary
    
    def test_empty_progress_summary(self):
        """空の進捗サマリー"""
        progress = ExecutionProgress(original_plan=[])
        summary = progress.get_progress_summary()
        assert "計画ステップ: 0/0 完了" in summary
    
    def test_step_status_icons(self):
        """ステータスアイコンの確認"""
        progress = ExecutionProgress(
            original_plan=["A", "B", "C", "D"],
            step_records=[
                StepExecutionRecord(step_index=0, step_text="A", status="completed"),
                StepExecutionRecord(step_index=1, step_text="B", status="failed"),
                StepExecutionRecord(step_index=2, step_text="C", status="in_progress"),
                StepExecutionRecord(step_index=3, step_text="D", status="pending"),
            ],
        )
        summary = progress.get_progress_summary()
        
        assert "✅ ステップ1:" in summary  # completed
        assert "❌ ステップ2:" in summary  # failed
        assert "🔄 ステップ3:" in summary  # in_progress
        assert "⏳ ステップ4:" in summary  # pending
    
    def test_tool_call_success_and_failure_markers(self):
        """ツール呼び出しの成功/失敗マーカー"""
        progress = ExecutionProgress(
            original_plan=["混合ステップ"],
            step_records=[
                StepExecutionRecord(
                    step_index=0,
                    step_text="混合ステップ",
                    status="completed",
                    tool_calls=[
                        ToolCallRecord(
                            tool_name="success_tool",
                            input="{}",
                            output="OK",
                            start_time=time.time(),
                        ),
                        ToolCallRecord(
                            tool_name="failed_tool",
                            input="{}",
                            error="Something went wrong",
                            start_time=time.time(),
                        ),
                    ],
                ),
            ],
        )
        summary = progress.get_progress_summary()
        
        assert "[✓] success_tool" in summary
        assert "[✗] failed_tool" in summary
