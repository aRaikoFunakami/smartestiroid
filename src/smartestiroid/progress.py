"""
進捗管理モジュール

テスト実行の進捗を追跡・管理するためのモデルを提供します。
- ExecutionProgress: LLM実行計画の進捗追跡
- ObjectiveProgress: ユーザー目標ステップの進捗追跡
- ObjectiveStep: 個別の目標ステップ
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


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
    
    def update_plan_after_replan(self, new_remaining_steps: List[str]) -> None:
        """リプラン後に計画を更新する
        
        リプランで新しい残りステップが生成された場合、
        original_planを「完了済みステップ + 新しい残りステップ」に更新する。
        これにより進捗表示が正確になる。
        
        Args:
            new_remaining_steps: リプラン後の新しい残りステップリスト
        """
        # 完了済みステップのテキストを取得
        completed_steps = [r.step_text for r in self.step_records if r.status == "completed"]
        
        # 新しいoriginal_planを構築
        self.original_plan = completed_steps + new_remaining_steps
    
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
        
        # 残りのステップを表示
        if completed < total:
            summary_lines.append("")
            summary_lines.append("【残りのステップ】")
            for i in range(completed, total):
                summary_lines.append(f"⏳ ステップ{i + 1}: {self.original_plan[i][:50]}...")
        
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
    timestamp: float = Field(default_factory=lambda: __import__('time').time(), description="実行時刻（Unix timestamp）")
    success: bool = Field(default=True, description="成功したかどうか")


class ObjectiveStepResult(BaseModel):
    """目標ステップの達成評価結果
    
    LLMが目標ステップの達成を評価した結果を格納する。
    
    Attributes:
        achieved: 目標が達成されたかどうか
        evidence: 判断根拠の説明
    """
    achieved: bool = Field(description="目標が達成されたかどうか")
    evidence: str = Field(description="判断根拠の説明（画面要素やロケーター情報に基づく）")
    
    def to_log_dict(self) -> dict:
        """ログ出力用の辞書を返す"""
        return {
            "achieved": self.achieved,
            "evidence": self.evidence
        }
    
    def to_allure_text(self) -> str:
        """Allure表示用の整形されたテキストを返す"""
        status_icon = "✅" if self.achieved else "❌"
        return f"""## {status_icon} 目標ステップ評価: {'達成' if self.achieved else '未達成'}

### 判断根拠
{self.evidence}
"""


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
        execution_plan_index: 実行計画の現在位置（0から開始）
        executed_actions: 実行済みアクションの履歴
        parent_index: recovery時のみ: 派生元のobjective stepのインデックス
        blocking_reason: recovery時のみ: ブロックされた理由
        completion_evidence: 完了時: 達成の根拠（画面要素やロケーター情報）
        is_handling_dialog: ダイアログ処理モード中かどうか
        dialog_handling_count: ダイアログ処理で実行したステップ数（ログ用）
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
    execution_plan_index: int = Field(
        default=0,
        description="実行計画の現在位置（0から開始、completed数と同じ）"
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
    result: Optional["ObjectiveStepResult"] = Field(
        default=None,
        description="目標達成評価結果"
    )
    # ダイアログ処理モード関連
    is_handling_dialog: bool = Field(
        default=False,
        description="ダイアログ処理モード中かどうか（Trueの間はexecution_plan_indexを進めない）"
    )
    dialog_handling_count: int = Field(
        default=0,
        description="ダイアログ処理で実行したステップ数（ログ・デバッグ用）"
    )
    
    def get_remaining_plan(self) -> List[str]:
        """未実行の実行計画ステップを取得"""
        return self.execution_plan[self.execution_plan_index:]
    
    def get_completed_plan_count(self) -> int:
        """完了した実行計画ステップ数を取得"""
        return self.execution_plan_index
    
    def advance_execution_plan(self) -> bool:
        """実行計画を1ステップ進める
        
        Returns:
            進めた場合True、全完了の場合False
        """
        if self.execution_plan_index < len(self.execution_plan):
            self.execution_plan_index += 1
            return True
        return False
    
    def is_execution_plan_completed(self) -> bool:
        """実行計画が全て完了しているかチェック"""
        return self.execution_plan_index >= len(self.execution_plan)
    
    def format_execution_progress_for_llm(self) -> str:
        """LLM向けの実行プラン進捗フォーマットを生成
        
        Returns:
            フォーマットされた進捗文字列
        """
        if not self.execution_plan:
            return "(実行計画なし)"
        
        lines = []
        for i, step in enumerate(self.execution_plan):
            if i < self.execution_plan_index:
                lines.append(f"  ✅ [{i+1}] {step}")
            elif i == self.execution_plan_index:
                lines.append(f"  ▶️ [{i+1}] {step}  ← 現在位置")
            else:
                lines.append(f"  ⏳ [{i+1}] {step}")
        
        return "\n".join(lines)


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
    
    def advance_to_next_objective(self) -> bool:
        """次の未完了の目標ステップに進む
        
        Returns:
            次の目標ステップに進めた場合True、全て完了している場合False
        """
        # 現在のステップ以降で、未完了のobjectiveステップを探す
        for i, step in enumerate(self.objective_steps):
            if step.step_type == "objective" and step.status in ("pending", "in_progress"):
                if step.status == "pending":
                    step.status = "in_progress"
                self.current_step_index = i
                return True
        return False
    
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
    
    def is_all_objectives_completed_with_current(self, current_objective_achieved: bool) -> bool:
        """現在の目標の達成状態を考慮して、全目標が完了しているかチェック
        
        LLMが「現在の目標達成」と判定しているが、まだステータスが更新されていない場合に使用。
        
        Args:
            current_objective_achieved: 現在の目標が達成済みと判定されているか
            
        Returns:
            全ての目標が完了している（または完了とみなせる）場合True
        """
        # まず通常のチェック
        if self.is_all_objectives_completed():
            return True
        
        # 現在の目標が達成されていない場合は、通常のチェック結果を返す
        if not current_objective_achieved:
            return False
        
        # 現在の目標が達成されている場合、それを含めて全目標達成かを判定
        current_step = self.get_current_step()
        if current_step and current_step.status != "completed":
            # 現在のステップ以降に未完了の目標があるかチェック
            remaining_after_current = [
                s for s in self.objective_steps
                if s.index > current_step.index and s.status not in ("completed", "skipped")
            ]
            if not remaining_after_current:
                # 現在のステップ以降に未完了の目標がない → 全目標達成
                return True
        
        return False
    
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
    
    def format_for_llm(self, current_objective_achieved: bool = False) -> str:
        """LLM向けの包括的な進捗フォーマットを生成
        
        ユーザー目標ステップの進捗と、現在のステップの実行プラン進捗を含む。
        
        Args:
            current_objective_achieved: 現在の目標が達成済みとみなす場合True
                （LLMが達成と判定したが、まだステータス更新前の場合に使用）
        
        Returns:
            LLM向けにフォーマットされた進捗文字列
        """
        completed = self.get_completed_objectives_count()
        total = self.get_total_objectives_count()
        current = self.get_current_step()
        
        # ★重要★ 現在の目標が達成済みと判定されている場合、表示を調整
        display_completed = completed
        if current_objective_achieved and current and current.status != "completed":
            display_completed = completed + 1
        
        lines = [
            "【★重要★ 目標と実行プランの全体進捗】",
            "",
            f"■ ユーザー目標進捗: {display_completed}/{total} 完了",
        ]
        
        # 目標ステップ一覧
        lines.append("")
        lines.append("■ 目標ステップ一覧:")
        for step in self.objective_steps:
            # 現在のステップが達成済みと判定されている場合、アイコンを✅に
            if current_objective_achieved and step.index == self.current_step_index:
                status_icon = "✅"
            else:
                status_icon = {
                    "completed": "✅",
                    "failed": "❌", 
                    "in_progress": "🔄",
                    "pending": "⏳",
                    "skipped": "⏭️"
                }.get(step.status, "?")
            
            type_label = "🎯" if step.step_type == "objective" else "🔧"
            current_marker = " ← 現在の目標" if step.index == self.current_step_index else ""
            
            lines.append(
                f"  {status_icon} {type_label} [{step.index}] {step.description}{current_marker}"
            )
        
        # 現在のステップの実行プラン進捗
        if current and current.execution_plan:
            lines.append("")
            lines.append(f"■ 現在の目標「{current.description}」の実行プラン進捗:")
            lines.append(f"  進捗: {current.execution_plan_index}/{len(current.execution_plan)} ステップ完了")
            lines.append("")
            lines.append(current.format_execution_progress_for_llm())
            
            # 達成判断のヒント
            if current.is_execution_plan_completed():
                lines.append("")
                lines.append("  ★ 全ステップ完了: この目標は達成と判断してよい")
        
        return "\n".join(lines)
    
    def set_current_execution_plan(self, plan: List[str]) -> None:
        """現在のステップに実行計画をセット
        
        Args:
            plan: 実行計画のステップリスト
        """
        current = self.get_current_step()
        if current:
            current.execution_plan = plan
            current.execution_plan_index = 0
    
    def advance_current_execution_plan(self) -> bool:
        """現在のステップの実行計画を1つ進める
        
        Returns:
            進めた場合True、全完了の場合False
        """
        current = self.get_current_step()
        if current:
            return current.advance_execution_plan()
        return False
    
    def get_current_remaining_plan(self) -> List[str]:
        """現在のステップの残り実行計画を取得"""
        current = self.get_current_step()
        if current:
            return current.get_remaining_plan()
        return []
    
    def is_current_execution_completed(self) -> bool:
        """現在のステップの実行計画が全て完了しているかチェック"""
        current = self.get_current_step()
        if current:
            return current.is_execution_plan_completed()
        return True
    
    # ダイアログ処理モード関連メソッド
    def enter_dialog_handling_mode(self) -> None:
        """現在のステップをダイアログ処理モードに入れる（冪等）
        
        ダイアログ処理モード中は、ステップ成功時もexecution_plan_indexを進めない。
        これにより、ダイアログ処理後に元の計画位置から再開できる。
        """
        current = self.get_current_step()
        if current and not current.is_handling_dialog:
            current.is_handling_dialog = True
    
    def exit_dialog_handling_mode(self) -> None:
        """現在のステップのダイアログ処理モードを解除
        
        ダイアログが解消された後に呼び出す。
        dialog_handling_countはリセットしない（ログ用に保持）。
        """
        current = self.get_current_step()
        if current and current.is_handling_dialog:
            current.is_handling_dialog = False
    
    def is_handling_dialog(self) -> bool:
        """現在ダイアログ処理モード中かどうかを返す"""
        current = self.get_current_step()
        if current:
            return current.is_handling_dialog
        return False
    
    def increment_dialog_handling_count(self) -> None:
        """ダイアログ処理ステップを1つ完了としてカウント
        
        execution_plan_indexは進めない（ダイアログ処理はテスト本来のステップではないため）。
        """
        current = self.get_current_step()
        if current:
            current.dialog_handling_count += 1
    
    def get_dialog_handling_count(self) -> int:
        """現在のステップで実行したダイアログ処理ステップ数を取得"""
        current = self.get_current_step()
        if current:
            return current.dialog_handling_count
        return 0
