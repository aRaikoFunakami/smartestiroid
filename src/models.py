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
