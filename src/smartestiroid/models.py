"""
Data models for SmartestiRoid test framework.

This module contains all Pydantic models and TypedDict definitions used throughout
the test execution workflow.

Progress-related models are defined in progress.py.
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
        current_objective_achieved: Whether current objective step was achieved
        current_objective_evidence: Evidence for objective achievement/non-achievement
    """
    action: Union[Response, Plan] = Field(
        description="実行するアクション。ユーザーに応答する場合はResponse、さらにツールを使用してタスクを実行する場合はPlanを使用してください。"
    )
    state_analysis: Optional[str] = Field(
        default=None,
        description="リプランナーによる状態分析結果"
    )
    current_objective_achieved: bool = Field(
        default=False,
        description="現在の目標ステップが達成されたかどうか"
    )
    current_objective_evidence: Optional[str] = Field(
        default=None,
        description="目標ステップの達成/未達成の根拠"
    )


# --- Step Execution Result Model ---
class StepExecutionResult(BaseModel):
    """ステップ実行結果の構造化出力モデル
    
    Executorがステップを実行した後、成功/失敗と理由を返すために使用。
    
    Attributes:
        success: ステップが成功したかどうか
        reason: 成功/失敗の判断理由
        executed_action: 実際に実行した操作の説明
        expected_screen_change: 操作後に期待される画面変化の説明
        no_page_source_change: page_sourceに影響がないツールのみを実行したか
    """
    success: bool = Field(description="ステップの実行が成功したかどうか。要素が見つからない、操作が失敗した場合はFalse")
    reason: str = Field(description="成功/失敗の判断理由（100〜300文字程度）。何を試みて何が起きたかを具体的に記述")
    executed_action: str = Field(description="実際に実行した操作の説明（例：'resource-id com.app:id/button をタップした'）")
    expected_screen_change: Optional[str] = Field(default=None, description="操作後に期待される画面変化の説明（例：'ホーム画面に遷移する'、'ダイアログが表示される'）。Executorは実行後の画面を確認できないため、期待値として記述する")
    no_page_source_change: bool = Field(default=False, description="page_sourceに影響を与えないツールのみを実行した場合はTrue。例：find_element, verify_screen_content, get_page_source, screenshot等の確認・取得系ツール")


class StepVerificationResult(BaseModel):
    """ステップ実行の検証結果モデル
    
    別の検証LLMがステップ実行結果を検証した結果。
    
    Attributes:
        verified: 検証の結果、ステップが正しく実行されたと判断されたか
        confidence: 判断の確信度（0.0〜1.0）
        reason: 検証結果の判断理由
        discrepancy: 矛盾点や疑問点がある場合の説明
    """
    verified: bool = Field(description="ステップが正しく実行されたと検証できたかどうか")
    confidence: float = Field(description="判断の確信度（0.0〜1.0）。0.7未満は要注意")
    reason: str = Field(description="検証結果の判断理由（100〜300文字程度）")
    discrepancy: Optional[str] = Field(default=None, description="矛盾点や疑問点がある場合の説明")


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


