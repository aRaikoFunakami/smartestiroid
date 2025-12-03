"""ObjectiveProgress関連のテスト

このテストはAndroid実機不要で実行可能です。
"""

import pytest
from smartestiroid.models import (
    ObjectiveStep,
    ObjectiveProgress,
    ObjectiveStepResult,
    ParsedObjectiveSteps,
    ExecutedAction,
)


class TestObjectiveStep:
    """ObjectiveStepモデルのテスト"""

    def test_create_objective_step(self):
        """目標ステップの作成テスト"""
        step = ObjectiveStep(
            index=0,
            description="設定画面を開く",
            step_type="objective",
            status="pending",
            execution_plan=["1. 設定アイコンをタップ", "2. 設定画面の表示を確認"],
        )
        assert step.index == 0
        assert step.description == "設定画面を開く"
        assert step.step_type == "objective"
        assert step.status == "pending"
        assert len(step.execution_plan) == 2
        assert step.parent_index is None
        assert step.blocking_reason is None

    def test_create_recovery_step(self):
        """リカバリーステップの作成テスト"""
        step = ObjectiveStep(
            index=1,
            description="ダイアログを閉じる",
            step_type="recovery",
            status="in_progress",
            execution_plan=["1. OKボタンをタップ"],
            parent_index=0,
            blocking_reason="予期しないダイアログが表示された",
        )
        assert step.step_type == "recovery"
        assert step.parent_index == 0
        assert step.blocking_reason == "予期しないダイアログが表示された"


class TestObjectiveProgress:
    """ObjectiveProgressモデルのテスト"""

    def test_create_objective_progress(self):
        """目標進捗の作成テスト"""
        progress = ObjectiveProgress(
            original_input="設定画面でWiFiをオンにする",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="設定画面を開く",
                    step_type="objective",
                    status="pending",
                    execution_plan=[],
                ),
                ObjectiveStep(
                    index=1,
                    description="WiFiをオンにする",
                    step_type="objective",
                    status="pending",
                    execution_plan=[],
                ),
            ],
            current_step_index=0,
        )
        assert progress.original_input == "設定画面でWiFiをオンにする"
        assert len(progress.objective_steps) == 2
        assert progress.current_step_index == 0

    def test_get_current_step(self):
        """現在のステップ取得テスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="ステップ1",
                    step_type="objective",
                    status="in_progress",
                    execution_plan=[],
                ),
                ObjectiveStep(
                    index=1,
                    description="ステップ2",
                    step_type="objective",
                    status="pending",
                    execution_plan=[],
                ),
            ],
            current_step_index=0,
        )
        current = progress.get_current_step()
        assert current is not None
        assert current.description == "ステップ1"

    def test_get_current_step_returns_none_when_all_completed(self):
        """全ステップ完了時にNoneを返すテスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="ステップ1",
                    step_type="objective",
                    status="completed",
                    execution_plan=[],
                ),
            ],
            current_step_index=1,  # 範囲外
        )
        current = progress.get_current_step()
        assert current is None

    def test_insert_recovery_step(self):
        """リカバリーステップ挿入テスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="設定を開く",
                    step_type="objective",
                    status="in_progress",
                    execution_plan=[],
                ),
                ObjectiveStep(
                    index=1,
                    description="WiFiをオンにする",
                    step_type="objective",
                    status="pending",
                    execution_plan=[],
                ),
            ],
            current_step_index=0,
        )
        
        # リカバリーステップを挿入（実際のAPI仕様に合わせる）
        progress.insert_recovery_step(
            parent_index=0,
            description="ダイアログを閉じる",
            blocking_reason="予期しないダイアログ",
            execution_plan=["OKをタップ"],
        )
        
        # リカバリーステップが挿入されたことを確認
        assert len(progress.objective_steps) == 3
        recovery_step = progress.objective_steps[1]
        assert recovery_step.step_type == "recovery"
        assert recovery_step.description == "ダイアログを閉じる"
        assert recovery_step.parent_index == 0
        assert recovery_step.blocking_reason == "予期しないダイアログ"
        
        # 後続のステップのインデックスが更新されていることを確認
        assert progress.objective_steps[2].index == 2

    def test_advance_to_next_step(self):
        """次のステップへの進行テスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="ステップ1",
                    step_type="objective",
                    status="in_progress",
                    execution_plan=[],
                ),
                ObjectiveStep(
                    index=1,
                    description="ステップ2",
                    step_type="objective",
                    status="pending",
                    execution_plan=[],
                ),
            ],
            current_step_index=0,
        )
        
        # 次のステップへ進む
        result = progress.advance_to_next_step()
        
        # 進めたことを確認（戻り値がTrue）
        assert result is True
        # 次のステップが進行中になることを確認
        assert progress.objective_steps[1].status == "in_progress"
        assert progress.current_step_index == 1

    def test_mark_current_completed(self):
        """現在のステップを完了としてマークするテスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="ステップ1",
                    step_type="objective",
                    status="in_progress",
                    execution_plan=[],
                ),
            ],
            current_step_index=0,
        )
        
        # 完了としてマーク
        progress.mark_current_completed(evidence="画面に設定が表示された")
        
        assert progress.objective_steps[0].status == "completed"
        assert progress.objective_steps[0].completion_evidence == "画面に設定が表示された"

    def test_is_all_objectives_completed(self):
        """全ステップ完了判定テスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="ステップ1",
                    step_type="objective",
                    status="completed",
                    execution_plan=[],
                ),
                ObjectiveStep(
                    index=1,
                    description="ステップ2",
                    step_type="objective",
                    status="completed",
                    execution_plan=[],
                ),
            ],
            current_step_index=2,
        )
        assert progress.is_all_objectives_completed() is True

    def test_is_all_objectives_completed_returns_false(self):
        """未完了時のテスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="ステップ1",
                    step_type="objective",
                    status="completed",
                    execution_plan=[],
                ),
                ObjectiveStep(
                    index=1,
                    description="ステップ2",
                    step_type="objective",
                    status="in_progress",
                    execution_plan=[],
                ),
            ],
            current_step_index=1,
        )
        assert progress.is_all_objectives_completed() is False

    def test_get_progress_summary(self):
        """サマリー取得テスト"""
        progress = ObjectiveProgress(
            original_input="設定画面でWiFiをオンにする",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="設定を開く",
                    step_type="objective",
                    status="completed",
                    execution_plan=["設定アイコンをタップ"],
                ),
                ObjectiveStep(
                    index=1,
                    description="WiFiをオンにする",
                    step_type="objective",
                    status="in_progress",
                    execution_plan=["WiFiスイッチをタップ"],
                ),
            ],
            current_step_index=1,
        )
        
        summary = progress.get_progress_summary()
        assert "1/2" in summary  # 1つ完了/2つ中
        assert "設定を開く" in summary
        assert "WiFiをオンにする" in summary
        assert "✅" in summary  # completed

    def test_get_objective_steps_only(self):
        """objectiveステップのみ取得テスト"""
        progress = ObjectiveProgress(
            original_input="テスト",
            objective_steps=[
                ObjectiveStep(
                    index=0,
                    description="ステップ1",
                    step_type="objective",
                    status="completed",
                    execution_plan=[],
                ),
                ObjectiveStep(
                    index=1,
                    description="リカバリー",
                    step_type="recovery",
                    status="completed",
                    execution_plan=[],
                    parent_index=0,
                ),
                ObjectiveStep(
                    index=2,
                    description="ステップ2",
                    step_type="objective",
                    status="in_progress",
                    execution_plan=[],
                ),
            ],
            current_step_index=2,
        )
        
        objectives = progress.get_objective_steps_only()
        assert len(objectives) == 2
        assert all(s.step_type == "objective" for s in objectives)


class TestObjectiveStepResult:
    """ObjectiveStepResultモデルのテスト"""

    def test_create_achieved_result(self):
        """達成結果の作成テスト"""
        result = ObjectiveStepResult(
            achieved=True,
            evidence="設定画面が正常に表示されている",
        )
        assert result.achieved is True
        assert result.evidence == "設定画面が正常に表示されている"

    def test_create_not_achieved_result(self):
        """未達成結果の作成テスト"""
        result = ObjectiveStepResult(
            achieved=False,
            evidence="ダイアログが表示されて先に進めない",
        )
        assert result.achieved is False
        assert result.evidence == "ダイアログが表示されて先に進めない"


class TestParsedObjectiveSteps:
    """ParsedObjectiveStepsモデルのテスト"""

    def test_create_parsed_steps(self):
        """解析結果の作成テスト"""
        parsed = ParsedObjectiveSteps(
            steps=[
                "設定を開く",
                "WiFiをオンにする",
            ],
        )
        assert len(parsed.steps) == 2
        assert parsed.steps[0] == "設定を開く"


class TestExecutedAction:
    """ExecutedActionモデルのテスト"""

    def test_create_executed_action(self):
        """実行アクションの作成テスト"""
        import time
        action = ExecutedAction(
            action="設定アイコンをタップ",
            tool_name="click_element",
            result="クリック成功",
            timestamp=time.time(),
            success=True,
        )
        assert action.action == "設定アイコンをタップ"
        assert action.tool_name == "click_element"
        assert action.success is True

    def test_create_failed_action(self):
        """失敗アクションの作成テスト"""
        import time
        action = ExecutedAction(
            action="存在しないボタンをタップ",
            tool_name="click_element",
            result="要素が見つかりません",
            timestamp=time.time(),
            success=False,
        )
        assert action.success is False
        assert "見つかりません" in action.result
