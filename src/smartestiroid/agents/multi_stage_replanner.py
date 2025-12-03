"""
Multi-stage replanner for SmartestiRoid test framework.

This module provides a 3-stage replanning process for mini models.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from colorama import Fore
from langchain_core.messages import HumanMessage
import allure

from ..models import Plan, Response, DecisionResult, ObjectiveStep, ObjectiveProgress
from ..config import RESULT_PASS, RESULT_FAIL


class ObjectiveEvaluation(BaseModel):
    """個別の目標ステップの達成評価"""
    step_index: int = Field(description="目標ステップのインデックス")
    description: str = Field(description="目標ステップの説明")
    achieved: bool = Field(description="達成されているかどうか")
    evidence: str = Field(description="達成/未達成の根拠")


class StateAnalysis(BaseModel):
    """リプラン時の画面状態分析結果"""
    screen_changes: str = Field(description="前ステップからの画面変化と差分（UI要素の追加/削除/変更）")
    current_screen_type: str = Field(description="現在の画面の種類（例：ホーム画面、検索結果、設定画面など）")
    main_elements: str = Field(description="画面上の主要UI要素の説明")
    blocking_dialogs: Optional[str] = Field(default=None, description="目標達成を妨げるダイアログやオーバーレイがある場合、その内容と閉じ方")
    test_progress: str = Field(description="テスト進捗の評価（定量的または定性的）")
    problems_detected: Optional[str] = Field(default=None, description="異常挙動・エラー・予期しない遷移がある場合、その詳細")
    
    # 目標ステップ単位の評価（新規追加）
    current_objective_achieved: bool = Field(description="現在の目標ステップが達成されているかどうか")
    current_objective_evidence: str = Field(description="現在の目標ステップの達成/未達成の根拠")
    
    # 従来のフィールド（互換性維持）
    goal_achieved: bool = Field(description="全体の目標が達成されているかどうか")
    goal_achievement_reason: str = Field(description="目標達成/未達成の判断根拠（ロケーター情報や画面状態に基づく）")
    suggested_next_action: Optional[str] = Field(default=None, description="次に実行すべきアクションの提案（任意）")


class MultiStageReplanner:
    """3段階に分けてreplanを実行するクラス（miniモデル用）"""
    
    def __init__(self, llm, knowhow: str, token_callback=None):
        self.llm = llm
        self.knowhow = knowhow
        self.model_name = llm.model_name if hasattr(llm, 'model_name') else "unknown"
        self.token_callback = token_callback  # track_query()用に保持
    
    async def analyze_state(
        self,
        goal: str,
        original_plan: list,
        past_steps: list,
        locator: str,
        previous_image_url: str = "",
        current_image_url: str = "",
        objective_progress: Optional[ObjectiveProgress] = None
    ) -> StateAnalysis:
        """ステージ1: 画像（前回/現在）とロケーターから現状を把握

        画像がある場合はLLMへマルチモーダルで渡し、差分言及を促す。
        構造化されたStateAnalysisオブジェクトを返す。
        
        Args:
            goal: 全体の目標
            original_plan: 元の実行計画
            past_steps: 完了済みステップ
            locator: 画面のロケーター情報
            previous_image_url: 前回のスクリーンショット
            current_image_url: 現在のスクリーンショット
            objective_progress: 目標進捗管理オブジェクト（新規追加）
        """
        # 進捗情報を計算
        total_steps = len(original_plan)
        completed_steps = len(past_steps)
        remaining_steps = max(total_steps - completed_steps, 0)
        
        # 目標ステップ情報を構築
        objective_info = ""
        current_objective = ""
        if objective_progress:
            current_step = objective_progress.get_current_step()
            if current_step:
                current_objective = current_step.description
            
            # 全目標ステップの一覧
            objective_list = []
            for step in objective_progress.objective_steps:
                status_icon = {
                    "completed": "✅",
                    "in_progress": "🔄",
                    "pending": "⏳",
                    "failed": "❌",
                    "skipped": "⏭️"
                }.get(step.status, "?")
                type_label = "🎯" if step.step_type == "objective" else "🔧"
                objective_list.append(f"  {status_icon} {type_label} [{step.index}] {step.description}")
            
            objective_info = f"""
【ユーザー目標ステップ】（これらが達成されたかを評価する基準）
{chr(10).join(objective_list)}

【現在評価中の目標ステップ】
{current_objective}

【目標進捗】
{objective_progress.get_completed_objectives_count()}/{objective_progress.get_total_objectives_count()} 目標完了
"""
        
        prompt_text = f"""
あなたは画面状態を分析するエキスパートです。

【全体の目標】
{goal}
{objective_info}

【LLM実行計画の進捗】（参考情報：目標達成のために生成された実行手順）
計画ステップ数: {total_steps}
完了ステップ数: {completed_steps}
残りステップ数: {remaining_steps}
最後の完了ステップ: {past_steps[-1][0] if past_steps else "(なし)"}

【重要】評価基準について
- LLM実行計画の進捗ではなく、「ユーザー目標ステップ」が達成されたかで判断すること
- 実行計画が全て完了しても、目標ステップが未達成なら「未達成」と判断すること
- 現在評価中の目標ステップ「{current_objective or goal}」が達成されているかを特に評価すること

【分析指示】
1. 前ステップからの画面変化と差分（UI要素の追加/削除/変更）
2. 現在の画面の種類（例：ホーム画面、検索結果、設定画面など）
3. 画面上の主要UI要素の説明
4. 目標達成を妨げるダイアログやオーバーレイの有無（重要：これがあればまず処理が必要）
5. 現在の目標ステップが達成されているかどうか
6. 現在の目標ステップの達成/未達成の根拠
7. 全体の目標が達成されているかどうか
8. 次に実行すべきアクションの提案

現在のロケーター情報:
{locator}

画面スクリーンショット（前回の画面と現在の画面):
"""

        content_blocks: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        if previous_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": previous_image_url}})
        if current_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": current_image_url}})

        # 構造化出力を使用
        structured_llm = self.llm.with_structured_output(StateAnalysis)
        
        # track_query()でクエリごとのトークン使用量を記録
        with self.token_callback.track_query():
            state_analysis: StateAnalysis = await structured_llm.ainvoke([HumanMessage(content=content_blocks)])
        
        print(Fore.MAGENTA + f"[MultiStageReplanner.analyze_state model: {self.model_name}] State analysis completed")
        print(Fore.CYAN + f"  - screen_type: {state_analysis.current_screen_type}")
        print(Fore.CYAN + f"  - current_objective_achieved: {state_analysis.current_objective_achieved}")
        print(Fore.CYAN + f"  - goal_achieved: {state_analysis.goal_achieved}")
        print(Fore.CYAN + f"  - blocking_dialogs: {state_analysis.blocking_dialogs or 'None'}")
        return state_analysis

    
    async def decide_action(
        self, 
        goal: str, 
        original_plan: list, 
        past_steps: list, 
        state_analysis: StateAnalysis,
        objective_progress: Optional[ObjectiveProgress] = None
    ) -> tuple:
        """ステージ2: Plan/Responseどちらを返すべきか判断（構造化出力）
        
        Args:
            goal: テスト目標
            original_plan: 元の計画
            past_steps: 完了済みステップ
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト（新規追加）
        """
        remaining_steps = max(len(original_plan) - len(past_steps), 0)

        # 目標ステップの進捗情報を構築
        objective_info = ""
        all_objectives_completed = False
        if objective_progress:
            all_objectives_completed = objective_progress.is_all_objectives_completed()
            completed_count = objective_progress.get_completed_objectives_count()
            total_count = objective_progress.get_total_objectives_count()
            
            objective_info = f"""
【ユーザー目標ステップの進捗】
完了: {completed_count}/{total_count}
全目標達成: {"Yes" if all_objectives_completed else "No"}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
"""

        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}
テスト進捗: {state_analysis.test_progress}
検出された問題: {state_analysis.problems_detected or "なし"}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
現在の目標ステップ根拠: {state_analysis.current_objective_evidence}
全体の目標達成: {"Yes" if state_analysis.goal_achieved else "No"}
達成判断理由: {state_analysis.goal_achievement_reason}
"""

        prompt = f"""あなたは次のアクションを厳密に判断するエキスパートです。

【目標】
{goal}
{objective_info}

【状態分析結果】
{state_summary}

【LLM実行計画の進捗】（参考）
計画ステップ総数: {len(original_plan)} / 完了: {len(past_steps)} / 残り: {remaining_steps}

【判断基準（厳格）】
★重要★ 判断基準は「ユーザー目標ステップ」の達成度です。LLM実行計画の進捗ではありません。

1. ブロッキングダイアログがある → decision=PLAN（まず障害物を処理）
2. 現在の目標ステップが未達成 → decision=PLAN
3. 現在の目標ステップが達成済みで、まだ次の目標ステップがある → decision=PLAN
4. 全ての目標ステップが達成済み → decision=RESPONSE

【出力仕様】
厳格なJSON
"""

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(DecisionResult)
        try:
            if self.token_callback:
                with self.token_callback.track_query():
                    result = await structured_llm.ainvoke(messages)
            else:
                result = await structured_llm.ainvoke(messages)
            
            print(Fore.MAGENTA + f"[MultiStageReplanner.decide_action model: {self.model_name}] Decision: {result.decision}")
            decision_norm = result.decision.strip().upper()
            if decision_norm not in ("PLAN", "RESPONSE"):
                decision_norm = "PLAN"  # 安全側フォールバック
            return decision_norm, result.reason.strip()
        except Exception as e:
            # 構造化出力失敗時は安全側でPLANを返す
            print(Fore.RED + f"Structured Output Error: {e}")
            allure.attach(str(e), name="❌ decide_action: Structured Output Error", attachment_type=allure.attachment_type.TEXT)
            return "PLAN", "構造化出力エラーのためフォールバック"
    
    async def build_plan(self, goal: str, original_plan: list, past_steps: list, state_analysis: StateAnalysis) -> Plan:
        """ステージ3a: 次のPlanを作成
        
        Args:
            goal: テスト目標
            original_plan: 元の計画
            past_steps: 完了済みステップ
            state_analysis: analyze_stateからの構造化された状態分析結果
        """
        remaining = original_plan[len(past_steps):]
        total_steps = len(original_plan)
        completed_steps = len(past_steps)
        remaining_count = len(remaining)
        
        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}
テスト進捗: {state_analysis.test_progress}
検出された問題: {state_analysis.problems_detected or "なし"}
目標達成: {"Yes" if state_analysis.goal_achieved else "No"}
達成判断理由: {state_analysis.goal_achievement_reason}
次のアクション提案: {state_analysis.suggested_next_action or "なし"}
"""
        
        prompt = f"""
あなたは実行計画を作成するエキスパートです。

目標
{goal}

現在の状態分析結果:
{state_summary}

【進捗状況】
計画総ステップ数: {total_steps}
完了済みステップ数: {completed_steps}
残りステップ数: {remaining_count}
進捗率: {(completed_steps / total_steps * 100) if total_steps > 0 else 0:.0f}%

残りの候補ステップ:
{remaining}

ノウハウ:   
{self.knowhow}

タスク:
目標達成のために必要な最適なステップ列を作成してください。以下を必ず守ること：
- ブロッキングダイアログがある場合は、まずそれを閉じるステップを最初に含めること
- ステップを実行できる状態でない場合は、現在の状態を考慮して最適なステップを再構築してください
- 可能なら既存未完了ステップを再利用し重複を避けること
- ステップを選択した根拠（進捗・画面要素・残り目標）を簡潔に言語化すること
- 現在の状態を考慮すること
- 不要なステップは追加しない
- 各ステップは具体的で実行可能なこと
- 目標の手順を踏まえた、目標を達成するための全てのステップ列がふくまれていること

【重要】ステップの効率化:
関連する連続操作は**1つのステップにまとめること**。不必要に細かく分割しないこと。

◆ 典型パターン（これらは必ず1ステップにまとめる）:
- テキスト入力系: 「検索ボックスをタップし、'キーワード'を入力して検索ボタンを押す」
- ナビゲーション系: 「設定アイコンをタップし、Wi-Fi設定を開いてONに切り替える」
- 確認・検証系: 「ページをスクロールして目的の要素を探し、見つかったらタップする」
- ✗ 分割禁止例: 1.ボックスタップ 2.入力 3.ボタン押下

◆ 分割すべきケース（別ステップにする）:
- 画面遷移を伴う場合（ロケーターが変わる）
- 待機が必要な場合（ページ読み込み、処理完了待ち）
- 結果の検証が必要な場合（操作後の確認）
- 別アプリ/コンテキストに切り替わる場合

厳格ルール:
- アカウント作成は禁止
- 自動ログインは禁止

出力形式（JSON）:
厳密なJSON形式
"""
        
        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Plan)
        
        if self.token_callback:
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
        else:
            plan = await structured_llm.ainvoke(messages)
        
        print(Fore.MAGENTA + f"[MultiStageReplanner.build_plan model: {self.model_name}] Plan created with {len(plan.steps)} steps")
        return plan
    
    async def build_response(
        self, 
        goal: str, 
        past_steps: list, 
        state_analysis: StateAnalysis,
        objective_progress: Optional[ObjectiveProgress] = None
    ) -> Response:
        """ステージ3b: 完了Responseを作成
        
        Args:
            goal: テスト目標
            past_steps: 完了済みステップ
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト（新規追加）
        """
        completed_count = len(past_steps)
        
        # 完了したステップの一覧を作成
        completed_steps_list = "\n".join(
            f"{i+1}. {step[0]}" for i, step in enumerate(past_steps)
        ) if past_steps else "(なし)"
        
        # 目標ステップの進捗情報
        objective_summary = ""
        if objective_progress:
            objective_list = []
            for step in objective_progress.objective_steps:
                status_icon = "✅" if step.status == "completed" else "❌" if step.status == "failed" else "⏳"
                objective_list.append(f"  {status_icon} {step.description}")
            
            objective_summary = f"""
【ユーザー目標ステップの達成状況】
{chr(10).join(objective_list)}

完了: {objective_progress.get_completed_objectives_count()}/{objective_progress.get_total_objectives_count()}
"""
        
        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
テスト進捗: {state_analysis.test_progress}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
全体の目標達成: {"Yes" if state_analysis.goal_achieved else "No"}
達成判断理由: {state_analysis.goal_achievement_reason}
"""
        
        prompt = f"""あなたはタスク完了報告を作成するエキスパートです。

【目標】
{goal}
{objective_summary}

【現在の状態分析結果】
{state_summary}

【完了済み実行ステップ一覧】
{completed_steps_list}

【タスク】
タスクの完了を報告してください。以下を含めること：
1. status: {RESULT_PASS} または {RESULT_FAIL} のいずれかを設定
   - 全ての目標ステップが達成されている場合は RESULT_PASS
   - 目標ステップが未達成の場合は RESULT_FAIL
2. reason: 完了理由の詳細（100〜600文字程度）
   - 各目標ステップの達成状況
   - 達成の根拠（ロケーター情報や画面状態）
   - 未達成がある場合はその理由

出力形式:
厳格なJSON形式（status と reason フィールドを持つ）
"""
        
        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Response)
        
        if self.token_callback:
            with self.token_callback.track_query():
                resp = await structured_llm.ainvoke(messages)
        else:
            resp = await structured_llm.ainvoke(messages)
        
        print(Fore.MAGENTA + f"[MultiStageReplanner.build_response model: {self.model_name}] Response created: {resp.status}")
        return resp
