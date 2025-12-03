"""
Data models for SmartestiRoid test framework.

This module contains all Pydantic models and TypedDict definitions used throughout
the test execution workflow.
"""

import operator
from typing import Annotated, List, Tuple, Union, Optional, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


# --- State Definition ---
class PlanExecute(TypedDict):
    """State definition for Plan-and-Execute workflow.
    
    Attributes:
        input: User's task input
        plan: List of planned steps
        past_steps: History of executed steps (tuples of step and result)
        response: Final response from the agent
        replan_count: Number of times the plan has been revised
    """
    input: str
    plan: List[str]
    past_steps: Annotated[List[Tuple], operator.add]
    response: str
    replan_count: int


# --- Plan Model ---
class Plan(BaseModel):
    """Plan model containing a list of executable steps.
    
    Attributes:
        steps: List of steps to execute in order
        reasoning: Optional reasoning for why this plan was chosen
    """
    steps: List[str] = Field(description="実行すべき手順の一覧（順序通りに並べる）")
    reasoning: Optional[str] = Field(default=None, description="このステップ列を選択した根拠の要約（100〜400文字程度）")


# --- Response Model ---
class Response(BaseModel):
    """Response model for final agent output.
    
    Attributes:
        status: Result status (RESULT_PASS or RESULT_FAIL)
        reason: Detailed reasoning for the evaluation
    """
    status: Literal["RESULT_PASS", "RESULT_FAIL"] = Field(description="判定結果ステータス")
    reason: str = Field(description="詳細な判定理由（100〜600文字程度。根拠要素/手順対応/不足点/改善提案を含め可）")


class Act(BaseModel):
    """Action model that can be either a Response or a Plan.
    
    Attributes:
        action: Either a Response (to answer user) or Plan (to execute more steps)
        state_analysis: Optional state analysis result from replanner
    """
    action: Union[Response, Plan] = Field(
        description="実行するアクション。ユーザーに応答する場合はResponse、さらにツールを使用してタスクを実行する場合はPlanを使用してください。"
    )
    state_analysis: Optional[str] = Field(
        default=None,
        description="リプランナーによる状態分析結果"
    )


# --- Decision Model ---
class DecisionResult(BaseModel):
    """Decision result for determining next action type.
    
    Attributes:
        decision: Type of next action (PLAN or RESPONSE)
        reason: Reasoning for the decision
    """
    decision: Literal["PLAN", "RESPONSE"] = Field(description="次に返すべきアクション種別 (PLAN|RESPONSE)")
    reason: str = Field(description="判断理由（1〜200文字程度）")


# --- Evaluation Model ---
class EvaluationResult(BaseModel):
    """Test result evaluation model.
    
    Attributes:
        status: Result status (RESULT_PASS, RESULT_SKIP, or RESULT_FAIL)
        reason: Detailed reasoning for the evaluation
    """
    status: Literal["RESULT_PASS", "RESULT_SKIP", "RESULT_FAIL"] = Field(description="判定結果ステータス")
    reason: str = Field(description="詳細な判定理由（100〜600文字程度。根拠要素/手順対応/不足点/改善提案を含め可）")


# --- Step Execution Tracking Models ---
class ToolCallRecord(BaseModel):
    """Individual tool call record within a step execution.
    
    Attributes:
        tool_name: Name of the tool called
        input: Input parameters for the tool
        output: Output from the tool (if successful)
        error: Error message (if failed)
        start_time: Timestamp when tool started
        end_time: Timestamp when tool ended
    """
    tool_name: str
    input: str
    output: Optional[str] = None
    error: Optional[str] = None
    start_time: float
    end_time: Optional[float] = None


class StepExecutionRecord(BaseModel):
    """Record of a single plan step execution.
    
    One plan step may contain multiple tool calls.
    This model tracks the relationship between plan steps and tool executions.
    
    Attributes:
        step_index: Index of the step in the plan (0-based)
        step_text: Text description of the step
        tool_calls: List of tool calls made during this step
        status: Current status of the step execution
        started_at: Timestamp when step execution started
        completed_at: Timestamp when step execution completed
        agent_response: Final response from the agent for this step
    """
    step_index: int
    step_text: str
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    agent_response: Optional[str] = None


class ExecutionProgress(BaseModel):
    """Overall execution progress tracking.
    
    Tracks the relationship between planned steps and actual executions,
    allowing accurate progress reporting even when one step executes multiple tools.
    
    Attributes:
        original_plan: Original list of planned steps
        step_records: List of step execution records
        current_step_index: Index of the currently executing step
    """
    original_plan: List[str] = Field(default_factory=list)
    step_records: List[StepExecutionRecord] = Field(default_factory=list)
    current_step_index: int = 0
    
    def get_completed_count(self) -> int:
        """Get the number of completed steps."""
        return len([r for r in self.step_records if r.status == "completed"])
    
    def get_total_tool_calls(self) -> int:
        """Get the total number of tool calls across all steps."""
        return sum(len(r.tool_calls) for r in self.step_records)
    
    def get_progress_summary(self) -> str:
        """Generate a human-readable progress summary."""
        completed = self.get_completed_count()
        total = len(self.original_plan)
        tool_calls = self.get_total_tool_calls()
        
        summary_lines = [
            f"計画ステップ: {completed}/{total} 完了",
            f"ツール呼び出し合計: {tool_calls}回",
            "",
            "【実行済みステップ詳細】"
        ]
        
        for record in self.step_records:
            status_icon = {
                "completed": "✅",
                "failed": "❌", 
                "in_progress": "🔄",
                "pending": "⏳"
            }.get(record.status, "?")
            
            summary_lines.append(
                f"{status_icon} ステップ{record.step_index + 1}: {record.step_text[:50]}..."
            )
            
            for tc in record.tool_calls:
                tc_status = "✓" if tc.error is None else "✗"
                summary_lines.append(f"    [{tc_status}] {tc.tool_name}")
        
        return "\n".join(summary_lines)


# --- Objective Progress Tracking Models ---
class ExecutedAction(BaseModel):
    """実行されたアクションの記録
    
    Attributes:
        action: アクション内容
        tool_name: 使用したツール名（例: click_element, input_text）
        result: 実行結果
        timestamp: 実行時刻
        success: 成功したかどうか
    """
    action: str = Field(description="アクション内容")
    tool_name: str = Field(description="使用したツール名")
    result: str = Field(description="実行結果")
    timestamp: float = Field(description="実行時刻（Unix timestamp）")
    success: bool = Field(default=True, description="成功したかどうか")


class ObjectiveStep(BaseModel):
    """目標ステップ（通常目標 or 回避用）
    
    ユーザーが定義した目標の個別ステップ、または
    ブロック回避のための一時的なrecoveryステップを表す。
    
    Attributes:
        index: ステップのインデックス（0から開始）
        description: ステップの説明（例: "Chromeが起動している"）
        step_type: ステップの種類（objective: ユーザー定義, recovery: ブロック回避用）
        status: ステップの状態
        execution_plan: このステップを達成するための実行計画（LLMが生成）
        executed_actions: 実行済みアクションの履歴
        parent_index: recovery時のみ: 派生元のobjective stepのインデックス
        blocking_reason: recovery時のみ: ブロックされた理由
        completion_evidence: 完了時: 達成の根拠（画面要素やロケーター情報）
    """
    index: int = Field(description="ステップのインデックス（0から開始）")
    description: str = Field(description="ステップの説明")
    step_type: Literal["objective", "recovery"] = Field(
        default="objective",
        description="ステップの種類（objective: ユーザー定義目標, recovery: ブロック回避用）"
    )
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"] = Field(
        default="pending",
        description="ステップの状態"
    )
    execution_plan: List[str] = Field(
        default_factory=list,
        description="このステップを達成するための実行計画（LLMが生成）"
    )
    executed_actions: List[ExecutedAction] = Field(
        default_factory=list,
        description="実行済みアクションの履歴"
    )
    parent_index: Optional[int] = Field(
        default=None,
        description="recovery時のみ: 派生元のobjective stepのインデックス"
    )
    blocking_reason: Optional[str] = Field(
        default=None,
        description="recovery時のみ: ブロックされた理由"
    )
    completion_evidence: Optional[str] = Field(
        default=None,
        description="完了時: 達成の根拠（画面要素やロケーター情報）"
    )


class ObjectiveStepResult(BaseModel):
    """目標ステップの達成評価結果
    
    LLMが目標ステップの達成を評価した結果を格納する。
    
    Attributes:
        achieved: 目標が達成されたかどうか
        evidence: 判断根拠の説明
    """
    achieved: bool = Field(description="目標が達成されたかどうか")
    evidence: str = Field(description="判断根拠の説明（画面要素やロケーター情報に基づく）")


class ParsedObjectiveSteps(BaseModel):
    """ユーザー入力から解析された目標ステップリスト
    
    LLMがユーザーの自然言語入力を解析して生成する。
    
    Attributes:
        steps: 目標ステップの説明リスト
    """
    steps: List[str] = Field(description="目標を達成するために必要な個別ステップのリスト（順序付き）")


class ObjectiveProgress(BaseModel):
    """目標全体の進捗状態
    
    ユーザー目標の進捗を追跡し、objective/recoveryステップを管理する。
    
    Attributes:
        original_input: ユーザーの元の入力（テストシートの手順）
        objective_steps: 全ステップのリスト（objective + recovery）
        current_step_index: 現在実行中のステップのインデックス
    """
    original_input: str = Field(description="ユーザーの元の入力")
    objective_steps: List[ObjectiveStep] = Field(
        default_factory=list,
        description="全ステップのリスト（objective + recovery）"
    )
    current_step_index: int = Field(default=0, description="現在実行中のステップのインデックス")
    
    def get_current_step(self) -> Optional[ObjectiveStep]:
        """現在実行中のステップを取得"""
        if 0 <= self.current_step_index < len(self.objective_steps):
            return self.objective_steps[self.current_step_index]
        return None
    
    def get_objective_steps_only(self) -> List[ObjectiveStep]:
        """objectiveタイプのステップのみ取得（recoveryを除く）"""
        return [s for s in self.objective_steps if s.step_type == "objective"]
    
    def get_completed_objectives_count(self) -> int:
        """完了したobjectiveステップ数を取得"""
        return len([s for s in self.objective_steps 
                    if s.step_type == "objective" and s.status == "completed"])
    
    def get_total_objectives_count(self) -> int:
        """全objectiveステップ数を取得"""
        return len([s for s in self.objective_steps if s.step_type == "objective"])
    
    def insert_recovery_step(
        self, 
        parent_index: int, 
        description: str, 
        blocking_reason: str,
        execution_plan: List[str]
    ) -> int:
        """recovery_stepを現在位置の次に挿入し、そのindexを返す
        
        Args:
            parent_index: 派生元のobjective stepのインデックス
            description: recoveryステップの説明
            blocking_reason: ブロックされた理由
            execution_plan: 回避のための実行計画
            
        Returns:
            挿入されたrecovery stepのインデックス
        """
        insert_pos = self.current_step_index + 1
        recovery_step = ObjectiveStep(
            index=insert_pos,
            description=description,
            step_type="recovery",
            status="pending",
            execution_plan=execution_plan,
            parent_index=parent_index,
            blocking_reason=blocking_reason
        )
        self.objective_steps.insert(insert_pos, recovery_step)
        # 挿入位置以降のindexを更新
        for i in range(insert_pos + 1, len(self.objective_steps)):
            self.objective_steps[i].index = i
        return insert_pos
    
    def advance_to_next_step(self) -> bool:
        """次のステップに進む
        
        Returns:
            進めた場合True、終了の場合False
        """
        if self.current_step_index < len(self.objective_steps) - 1:
            self.current_step_index += 1
            self.objective_steps[self.current_step_index].status = "in_progress"
            return True
        return False
    
    def return_to_parent_objective(self) -> bool:
        """recovery完了後、親のobjectiveに戻る
        
        Returns:
            親に戻れた場合True、そうでない場合False
        """
        current = self.get_current_step()
        if current and current.step_type == "recovery" and current.parent_index is not None:
            # 親のobjectiveを再度in_progressに
            if current.parent_index < len(self.objective_steps):
                parent = self.objective_steps[current.parent_index]
                parent.status = "in_progress"
                self.current_step_index = current.parent_index
                return True
        return False
    
    def mark_current_completed(self, evidence: str = "") -> None:
        """現在のステップを完了としてマーク
        
        Args:
            evidence: 達成の根拠
        """
        current = self.get_current_step()
        if current:
            current.status = "completed"
            current.completion_evidence = evidence
    
    def mark_current_failed(self, reason: str = "") -> None:
        """現在のステップを失敗としてマーク
        
        Args:
            reason: 失敗の理由
        """
        current = self.get_current_step()
        if current:
            current.status = "failed"
            current.completion_evidence = reason
    
    def is_all_objectives_completed(self) -> bool:
        """全てのobjectiveステップが完了しているかチェック"""
        objectives = self.get_objective_steps_only()
        return all(s.status == "completed" for s in objectives) if objectives else False
    
    def get_progress_summary(self) -> str:
        """進捗サマリーを文字列で取得"""
        completed = self.get_completed_objectives_count()
        total = self.get_total_objectives_count()
        current = self.get_current_step()
        
        lines = [
            f"【目標進捗】 {completed}/{total} 完了 ({completed/total*100:.0f}%)" if total > 0 else "【目標進捗】 0/0",
        ]
        
        if current:
            lines.extend([
                f"【現在のステップ】 [{current.step_type}] {current.description}",
                f"【ステータス】 {current.status}",
            ])
            
            if current.step_type == "recovery":
                lines.append(f"【ブロック理由】 {current.blocking_reason}")
                lines.append(f"【親ステップ】 #{current.parent_index}")
        
        # 各ステップの状態を表示
        lines.append("")
        lines.append("【ステップ一覧】")
        for step in self.objective_steps:
            status_icon = {
                "completed": "✅",
                "failed": "❌", 
                "in_progress": "🔄",
                "pending": "⏳",
                "skipped": "⏭️"
            }.get(step.status, "?")
            
            type_label = "🎯" if step.step_type == "objective" else "🔧"
            current_marker = " ◀" if step.index == self.current_step_index else ""
            
            lines.append(
                f"  {status_icon} {type_label} [{step.index}] {step.description[:40]}...{current_marker}"
            )
        
        return "\n".join(lines)

