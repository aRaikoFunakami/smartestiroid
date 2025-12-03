"""
Simple planner for SmartestiRoid test framework.

This module provides a plan-and-execute agent with multi-stage replanning.
"""

from typing import Optional
from pydantic import BaseModel, Field
from colorama import Fore
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import allure

from ..models import (
    PlanExecute, Plan, Response, Act,
    ObjectiveStep, ObjectiveProgress, ObjectiveStepResult, ParsedObjectiveSteps
)
from ..config import (
    OPENAI_TIMEOUT, OPENAI_MAX_RETRIES,
    MODEL_STANDARD, KNOWHOW_INFO, RESULT_PASS
)
from .multi_stage_replanner import MultiStageReplanner
from ..utils.allure_logger import log_openai_error_to_allure


class ScreenAnalysis(BaseModel):
    """画面分析結果のモデル"""
    screen_type: str = Field(description="画面の種類（例：ホーム画面、設定画面、ダイアログ表示中など）")
    main_elements: str = Field(description="画面上の主要なUI要素の説明")
    blocking_dialogs: Optional[str] = Field(default=None, description="目標達成を妨げるダイアログやオーバーレイがある場合、その内容と閉じ方")
    current_state: str = Field(description="現在の画面状態の要約（目標達成に向けた現在位置）")
    available_actions: str = Field(description="この画面で実行可能な主要なアクション")


class SimplePlanner:
    """テスト用のシンプルなプランナー（Multi-stage replanモード）"""

    def __init__(self, knowhow: str = KNOWHOW_INFO, model_name: str = MODEL_STANDARD, token_callback=None):
        callbacks = [token_callback] if token_callback else []
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0,
            timeout=OPENAI_TIMEOUT,
            max_retries=OPENAI_MAX_RETRIES,
            callbacks=callbacks if callbacks else None
        )
        self.knowhow = knowhow  # ノウハウ情報を保持
        self.model_name = model_name
        self.token_callback = token_callback  # track_query()用に保持
        
        # Multi-stage用のreplanner初期化（token_callbackを渡す）
        self.replanner = MultiStageReplanner(self.llm, knowhow, token_callback)
        print(Fore.CYAN + f"🔀 Multi-stage replan モード有効 (model: {model_name})")

    async def analyze_screen(
        self, locator: str, image_url: str, goal: str = ""
    ) -> ScreenAnalysis:
        """画面を分析して現在の状態を把握する（Stage 1）
        
        Args:
            locator: 画面のロケーター情報（XML）
            image_url: 画面のスクリーンショット（base64）
            goal: 目標（オプション、分析の参考情報として使用）
            
        Returns:
            ScreenAnalysis: 画面分析結果
        """
        system_prompt = """あなたは画面分析のエキスパートです。
提供された画像とロケーター情報から、現在の画面状態を正確に分析してください。

【分析の観点】
1. 画面の種類: 何の画面か（ホーム、設定、検索結果、ダイアログなど）
2. 主要なUI要素: ボタン、入力欄、リスト、アイコンなど
3. 障害物の有無: 目標達成を妨げるダイアログやオーバーレイ
   - 初期設定ダイアログ（プライバシーポリシー、チュートリアルなど）
   - 広告ダイアログ（バナー、全画面広告など）
   - 通知/位置情報許可ダイアログ
   - Cookie同意バナー
   - その他のオーバーレイ
4. 現在の状態: 目標に向けてどの段階にいるか
5. 実行可能なアクション: この画面で何ができるか

【重要】
- 画像とロケーター情報の両方を突き合わせて分析すること
- 障害物がある場合は、それを閉じる方法（ボタンのテキストやXPath）を具体的に示すこと
"""

        goal_context = f"\n\n【参考】目標: {goal}" if goal else ""
        
        human_message = f"""この画面を分析してください。{goal_context}

【ロケーター情報】
{locator}
"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[
                {"type": "text", "text": human_message},
                {"type": "image_url", "image_url": {"url": image_url}}
            ])
        ]
        
        try:
            structured_llm = self.llm.with_structured_output(ScreenAnalysis)
            
            with self.token_callback.track_query():
                analysis = await structured_llm.ainvoke(messages)
            
            print(Fore.CYAN + f"[analyze_screen] 画面分析完了: {analysis.screen_type}")
            return analysis
            
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[analyze_screen] Exception: {err_type}: {e}")
            # フォールバック: 基本的な分析結果を返す
            return ScreenAnalysis(
                screen_type="不明",
                main_elements="分析エラーのため不明",
                blocking_dialogs=None,
                current_state="分析エラー",
                available_actions="不明"
            )

    async def parse_objective_steps(self, user_input: str) -> ObjectiveProgress:
        """ユーザーの自然言語目標から個別のObjectiveStepを抽出する
        
        Args:
            user_input: ユーザーが入力した目標（テストシートの手順）
            
        Returns:
            ObjectiveProgress: 目標進捗管理オブジェクト
        """
        prompt = f"""以下のテスト目標からステップを抽出してください。

【テスト目標】
{user_input}

【絶対に守るべきルール】

1. **ステップの意味を変えない**
   - ユーザーの意図を正確に反映すること
   - 勝手に操作を追加しない（スクロール、ボタンタップなど）
   - 勝手にステップを詳細化・分解しない

2. **ステップ数は元の数に合わせる**
   - 入力に2ステップあれば、出力も2ステップ
   - 「1. ○○ 2. ○○」なら2ステップ
   - 番号がない連続した文でも、複数の操作があれば分割する

3. **確認項目・期待結果は除外**
   - 「〇〇が表示されること」「〇〇であること」等は除外

4. **★重要★ ステップは「指示形」で書く**
   - ステップはLLMへの指示であり、結果の確認ではない
   - 「〇〇する」「〇〇を開く」「〇〇をONにする」のように動作指示形にすること
   - ❌NG: 「設定画面が開いている」「Wi-FiがONになっている」（これは結果確認）
   - ✅OK: 「設定画面を開く」「Wi-FiをONにする」（これは動作指示）

【出力例】
入力: "1. アプリを起動する 2. 利用規約ダイアログを確認する"
出力: ["アプリを起動する", "利用規約ダイアログを確認する"]
（※ 2ステップのまま。詳細化しない）

入力: "設定画面を開いてWi-FiをONにする"
出力: ["設定画面を開く", "Wi-FiをONにする"]
（※ 1文に2つの操作があるので2ステップ。動作指示形で書く）

入力: "1. Chromeを起動 2. yahoo.co.jpに移動 確認項目: ページが表示されること"
出力: ["Chromeを起動する", "yahoo.co.jpに移動する"]
（※ 確認項目は除外、動作指示形で書く）
"""
        
        try:
            structured_llm = self.llm.with_structured_output(ParsedObjectiveSteps)
            
            with self.token_callback.track_query():
                result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
            
            print(Fore.CYAN + f"[parse_objective_steps] 目標ステップ解析完了: {len(result.steps)}ステップ")
            for i, step in enumerate(result.steps):
                print(Fore.CYAN + f"  [{i}] {step}")
            
            # ObjectiveProgressを構築
            objective_steps = [
                ObjectiveStep(
                    index=i,
                    description=step,
                    step_type="objective",
                    status="pending"
                )
                for i, step in enumerate(result.steps)
            ]
            
            progress = ObjectiveProgress(
                original_input=user_input,
                objective_steps=objective_steps,
                current_step_index=0
            )
            
            # 最初のステップをin_progressに
            if progress.objective_steps:
                progress.objective_steps[0].status = "in_progress"
            
            return progress
            
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[parse_objective_steps] Exception: {err_type}: {e}")
            # フォールバック: 入力全体を1つの目標として扱う
            return ObjectiveProgress(
                original_input=user_input,
                objective_steps=[
                    ObjectiveStep(
                        index=0,
                        description=user_input,
                        step_type="objective",
                        status="in_progress"
                    )
                ],
                current_step_index=0
            )

    async def create_execution_plan_for_objective(
        self,
        objective_step: ObjectiveStep,
        screen_analysis: ScreenAnalysis,
        locator: str = "",
        image_url: str = "",
        all_objective_steps: list = None  # 未使用だが互換性のため残す
    ) -> Plan:
        """特定のObjectiveStepに対するExecution Planを生成する
        
        Args:
            objective_step: 達成すべき目標ステップ
            screen_analysis: 現在の画面分析結果
            locator: 画面のロケーター情報
            image_url: 画面のスクリーンショット
            all_objective_steps: 未使用（互換性のため残す）
            
        Returns:
            Plan: 実行計画
        """
        prompt = f"""目標を達成するための実行計画を1ステップで作成してください。

【目標】
{objective_step.description}

【画面状態】
{screen_analysis.screen_type} 

【現在の画面状態の要約】
{screen_analysis.current_state}

【厳格ルール】
- 目標の意味を変えない、拡大解釈しない
- 「確認する」が目標なら確認のみ（操作は不要）
- 「起動する」が目標で既に起動済みなら「起動済みを確認」のみ
- 勝手にアクションを追加しない
"""

        messages = [HumanMessage(content=prompt)]
        
        # 画像がある場合はマルチモーダルで渡す
        if image_url:
            messages = [HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ])]
        
        try:
            structured_llm = self.llm.with_structured_output(Plan)
            
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
            
            print(Fore.CYAN + f"[create_execution_plan_for_objective] 実行計画生成完了: {len(plan.steps)}アクション")
            for i, step in enumerate(plan.steps):
                print(Fore.CYAN + f"  [{i}] {step}")
            
            return plan
            
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[create_execution_plan_for_objective] Exception: {err_type}: {e}")
            return Plan(steps=[f"目標「{objective_step.description}」を達成する"])

    async def evaluate_objective_completion(
        self,
        objective_step: ObjectiveStep,
        screen_analysis: ScreenAnalysis,
        locator: str = "",
        image_url: str = ""
    ) -> ObjectiveStepResult:
        """目標ステップが達成されているかを評価する
        
        Args:
            objective_step: 評価対象の目標ステップ
            screen_analysis: 現在の画面分析結果
            locator: 画面のロケーター情報
            image_url: 画面のスクリーンショット
            
        Returns:
            ObjectiveStepResult: 達成評価結果
        """
        prompt = f"""以下の目標ステップが達成されているか評価してください。

【評価対象の目標】
{objective_step.description}

【現在の画面状態】
- 画面タイプ: {screen_analysis.screen_type}
- 主要要素: {screen_analysis.main_elements}
- 現在の状態: {screen_analysis.current_state}

【重要な判定基準】
- 「アプリを起動する」目標の場合:
  - アプリの画面（ダイアログ含む）が表示されていれば「達成」
  - ダイアログはアプリの一部。ダイアログ表示中でも起動は完了している
  - ホーム画面に到達する必要はない

- 「〇〇を確認する」目標の場合:
  - 確認対象が画面に表示されていれば「達成」（表示されていることを確認できた）
  - 確認対象が画面に表示されていなくても「達成」（表示されていないことを確認できた）
  - 重要: 「確認する」とは「有無を確認する」こと。表示されていないことも確認の結果
  - 操作する必要はない

- 「〇〇ダイアログを確認する」目標の場合:
  - ダイアログが表示されていれば「達成」（表示を確認できた）
  - ダイアログが表示されていなければ「達成」（非表示を確認できた）
  - 重要: ダイアログの有無を確認すること自体が目標

- 目標の意味を拡大解釈しない
"""

        messages = [HumanMessage(content=prompt)]
        
        # 画像がある場合はマルチモーダルで渡す
        if image_url:
            messages = [HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ])]
        
        try:
            structured_llm = self.llm.with_structured_output(ObjectiveStepResult)
            
            with self.token_callback.track_query():
                result = await structured_llm.ainvoke(messages)
            
            status_icon = "✅" if result.achieved else "❌"
            print(Fore.CYAN + f"[evaluate_objective_completion] {status_icon} 目標「{objective_step.description[:30]}...」: {'達成' if result.achieved else '未達成'}")
            
            return result
            
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[evaluate_objective_completion] Exception: {err_type}: {e}")
            return ObjectiveStepResult(
                achieved=False,
                evidence=f"評価エラー: {e}"
            )

    async def create_recovery_plan(
        self,
        blocking_reason: str,
        screen_analysis: ScreenAnalysis,
        locator: str = "",
        image_url: str = ""
    ) -> tuple[str, list[str]]:
        """ブロック回避のためのRecovery Planを生成する
        
        Args:
            blocking_reason: ブロックの理由（ダイアログの内容など）
            screen_analysis: 現在の画面分析結果
            locator: 画面のロケーター情報
            image_url: 画面のスクリーンショット
            
        Returns:
            tuple[str, list[str]]: (recoveryステップの説明, 実行計画)
        """
        prompt = f"""画面上の障害物を回避するための計画を作成してください。

【障害物の内容】
{blocking_reason}

【現在の画面状態】
- 画面タイプ: {screen_analysis.screen_type}
- 主要要素: {screen_analysis.main_elements}
- 障害物詳細: {screen_analysis.blocking_dialogs}

【ロケーター情報】
{locator if locator else "なし"}

【指示】
- 障害物（ダイアログ、オーバーレイ等）を閉じるための具体的なアクションを列挙
- 最小限のアクションで障害物を除去すること
- 閉じるボタン、「OK」「Got it」「Skip」などのボタンを探す
- ボタンが見つからない場合は戻るボタンやタップで閉じる方法を検討
"""

        messages = [HumanMessage(content=prompt)]
        
        if image_url:
            messages = [HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ])]
        
        try:
            structured_llm = self.llm.with_structured_output(Plan)
            
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
            
            description = f"障害物を回避: {blocking_reason[:50]}..."
            print(Fore.YELLOW + f"[create_recovery_plan] Recovery計画生成: {len(plan.steps)}アクション")
            
            return description, plan.steps
            
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[create_recovery_plan] Exception: {err_type}: {e}")
            return f"障害物を回避: {blocking_reason[:30]}...", ["障害物を閉じる"]

    async def replan(
        self,
        state: PlanExecute,
        locator: str = "",
        image_url: str = "",
        previous_image_url: str = "",
        objective_progress: Optional[ObjectiveProgress] = None,
    ) -> Act:
        """実行結果を評価して計画を再調整する
        
        Args:
            state: 現在の実行状態
            locator: 画面のロケーター情報
            image_url: 現在のスクリーンショット
            previous_image_url: 前回のスクリーンショット
            objective_progress: 目標進捗管理オブジェクト（新規追加）
        """
        # Multi-stage replan処理
        try:
            print(Fore.CYAN + f"🔀 Multi-stage replan: STAGE 1（State Analysis）[model: {self.model_name}]")
            state_analysis = await self.replanner.analyze_state(
                goal=state["input"],
                original_plan=state["plan"],
                past_steps=state["past_steps"],
                locator=locator,
                previous_image_url=previous_image_url,
                current_image_url=image_url,
                objective_progress=objective_progress
            )
            # 構造化された状態分析結果をログ出力
            state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}
テスト進捗: {state_analysis.test_progress}
検出された問題: {state_analysis.problems_detected or "なし"}
アプリ不具合検出: {"Yes - " + (state_analysis.app_defect_reason or "詳細不明") if state_analysis.app_defect_detected else "No"}
スタック状態: {"Yes" if state_analysis.is_stuck else "No"}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
現在の目標ステップ根拠: {state_analysis.current_objective_evidence}
全体の目標達成: {"Yes" if state_analysis.goal_achieved else "No"}
達成判断理由: {state_analysis.goal_achievement_reason}
次のアクション提案: {state_analysis.suggested_next_action or "なし"}
"""
            print(Fore.CYAN + f"状態分析結果:\n{state_summary}")
            allure.attach(state_summary, name=f"🔍 State Analysis Results [model: {self.model_name}]", attachment_type=allure.attachment_type.TEXT)
            
            print(Fore.CYAN + "🔀 Multi-stage replan: STAGE 2（Action Decision）")
            decision, reason = await self.replanner.decide_action(
                goal=state["input"],
                original_plan=state["plan"],
                past_steps=state["past_steps"],
                state_analysis=state_analysis,
                objective_progress=objective_progress
            )
            print(Fore.CYAN + f"判定結果: {decision}\n理由: {reason}")
            allure.attach(f"DECISION: {decision}\n{reason}", name=f"⚖️ Action Decision [model: {self.model_name}]", attachment_type=allure.attachment_type.TEXT)
            
            print(Fore.CYAN + "🔀 Multi-stage replan: STAGE 3（Output Generation）")
            if decision == "RESPONSE":
                # RESPONSE判定 = テスト終了（成功または失敗）
                # ここで初めて目標達成を確定させる
                print(Fore.CYAN + "  → RESPONSE分岐に入りました。build_response()を呼び出します...")
                
                # 目標進捗を更新（RESPONSEが返される = 現在の目標が達成または終了）
                if state_analysis.current_objective_achieved and objective_progress:
                    current_step = objective_progress.get_current_step()
                    if current_step and current_step.status != "completed":
                        evidence = state_analysis.current_objective_evidence or "状態分析により達成確認"
                        print(Fore.GREEN + f"✅ [Planner] 目標ステップ完了: [{current_step.index}] {current_step.description[:50]}...")
                        objective_progress.mark_current_completed(evidence=evidence)
                
                try:
                    response = await self.replanner.build_response(
                        goal=state["input"],
                        past_steps=state["past_steps"],
                        state_analysis=state_analysis,
                        objective_progress=objective_progress
                    )
                    print(Fore.GREEN + f"✅ Response生成完了: [{response.status}] {response.reason[:100]}...")
                    allure.attach(
                        f"Status: {response.status}\n\nReason:\n{response.reason}",
                        name="📋 Build Response Result",
                        attachment_type=allure.attachment_type.TEXT
                    )
                    return Act(
                        action=response,
                        state_analysis=state_summary,
                        current_objective_achieved=state_analysis.current_objective_achieved,
                        current_objective_evidence=state_analysis.current_objective_evidence
                    )
                except Exception as build_err:
                    print(Fore.RED + f"❌ build_response()でエラー: {build_err}")
                    allure.attach(f"build_response error: {build_err}", name="❌ build_response Error", attachment_type=allure.attachment_type.TEXT)
                    raise
            else:
                # PLAN判定 = まだ継続が必要
                # 現在の目標ステップが達成されている場合は次の目標に進む
                if state_analysis.current_objective_achieved and objective_progress:
                    current_step = objective_progress.get_current_step()
                    if current_step and current_step.status != "completed":
                        evidence = state_analysis.current_objective_evidence or "状態分析により達成確認"
                        print(Fore.GREEN + f"✅ [Planner] 目標ステップ完了: [{current_step.index}] {current_step.description[:50]}...")
                        objective_progress.mark_current_completed(evidence=evidence)
                        
                        # 次の目標に進む
                        has_next = objective_progress.advance_to_next_objective()
                        if has_next:
                            next_objective = objective_progress.get_current_step()
                            print(Fore.CYAN + f"🎯 [Planner] 次の目標ステップに進みます: [{next_objective.index}] {next_objective.description[:50]}...")
                        # has_next=False の場合でも、decide_action() が PLAN を返したので計画を作成する
                        # （LLM の判断を尊重）
                
                # 現在の目標（または次の目標）に対する計画を作成
                plan = await self.replanner.build_plan(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    state_analysis=state_analysis,
                    objective_progress=objective_progress,
                    locator=locator  # ブロッキングダイアログ処理用にロケーター情報を渡す
                )
                print(Fore.YELLOW + f"📋 Plan生成完了: {len(plan.steps)}ステップ")
                return Act(
                    action=plan,
                    state_analysis=state_summary,
                    current_objective_achieved=state_analysis.current_objective_achieved,
                    current_objective_evidence=state_analysis.current_objective_evidence
                )
        
        except Exception as e:
            print(Fore.RED + f"⚠️ Multi-stage replan エラー: {e}")
            allure.attach(f"Multi-stage replan error: {e}", name="❌ Multi-stage error", attachment_type=allure.attachment_type.TEXT)
            # フォールバック: 残りのステップを返す
            remaining_steps = state["plan"][len(state["past_steps"]):]
            if remaining_steps:
                fallback_plan = Plan(steps=remaining_steps)
                print(Fore.YELLOW + f"🔄 フォールバック: 残り{len(remaining_steps)}ステップを返却")
                return Act(action=fallback_plan)
            else:
                fallback_response = Response(status=RESULT_PASS, reason=f"エラー発生のため処理を中断します: {e}")
                return Act(action=fallback_response)
