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
        prompt = f"""以下のテスト目標から、個別の検証ステップを抽出してください。

【テスト目標】
{user_input}

【指示】
- 目標を達成するために確認すべき個別ステップを抽出する
- 各ステップは「何が達成されるべきか」という目標レベルで記述
- 具体的なUI操作ではなく、期待される状態や結果を記述
- 順序を保持すること
- 1つのステップは1つの検証可能な目標に対応すること

【出力例】
入力: "1. Chromeを起動 2. yahoo.co.jpに移動 3. 星マークをクリック"
出力: ["Chromeが起動している", "yahoo.co.jpに移動している", "星マークがクリックされている"]

入力: "設定画面を開いてWi-FiをONにする"
出力: ["設定画面が開いている", "Wi-FiがONになっている"]
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
        image_url: str = ""
    ) -> list[str]:
        """特定のObjectiveStepに対するExecution Planを生成する
        
        Args:
            objective_step: 達成すべき目標ステップ
            screen_analysis: 現在の画面分析結果
            locator: 画面のロケーター情報
            image_url: 画面のスクリーンショット
            
        Returns:
            list[str]: 実行計画（アクションのリスト）
        """
        # ブロッキングダイアログがある場合は先にそれを処理するステップを含める
        blocking_context = ""
        if screen_analysis.blocking_dialogs:
            blocking_context = f"""
【重要】画面上に障害物があります:
{screen_analysis.blocking_dialogs}

まずこの障害物を閉じるアクションを最初に含めてください。
"""

        prompt = f"""以下の目標ステップを達成するための実行計画を作成してください。

【達成すべき目標】
{objective_step.description}

【現在の画面状態】
- 画面タイプ: {screen_analysis.screen_type}
- 主要要素: {screen_analysis.main_elements}
- 現在の状態: {screen_analysis.current_state}
- 実行可能なアクション: {screen_analysis.available_actions}
{blocking_context}

【ロケーター情報】
{locator[:3000] if locator else "なし"}

【ノウハウ】
{self.knowhow}

【指示】
- 目標を達成するために必要な具体的なアクションを列挙
- 各アクションはAppiumツールで実行可能な単位
- 不要なステップは含めない
- 画面状態を考慮して最適なアクション順序を決定
- 関連する連続操作は1つのステップにまとめること

【禁止事項】
- アカウント作成
- 自動ログイン
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
            
            return plan.steps
            
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[create_execution_plan_for_objective] Exception: {err_type}: {e}")
            return [f"目標「{objective_step.description}」を達成するアクションを実行"]

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

【ロケーター情報】
{locator[:3000] if locator else "なし"}

【指示】
- 画面のロケーター情報とスクリーンショットから目標達成を判断
- 達成/未達成の根拠を明確に示す
- 部分的な達成は「未達成」として扱う
- 曖昧な場合は「未達成」として扱う
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
{locator[:3000] if locator else "なし"}

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

    async def create_plan(
        self, user_input: str, locator: str = "", image_url: str = ""
    ) -> Plan:
        """目標達成のための計画を作成する（2段階処理）
        
        Stage 1: 画面分析（analyze_screen）
        Stage 2: プランニング（本メソッド）
        """
        
        # Stage 1: 画面分析
        screen_analysis = None
        if locator and image_url:
            print(Fore.CYAN + f"[create_plan] Stage 1: 画面分析開始")
            screen_analysis = await self.analyze_screen(locator, image_url, user_input)
            
            # 分析結果をAllureに添付
            analysis_text = f"""【画面種類】{screen_analysis.screen_type}

【主要UI要素】
{screen_analysis.main_elements}

【障害物（ダイアログ等）】
{screen_analysis.blocking_dialogs or "なし"}

【現在の状態】
{screen_analysis.current_state}

【実行可能なアクション】
{screen_analysis.available_actions}
"""
            allure.attach(
                analysis_text,
                name=f"🔍 Screen Analysis [model: {self.model_name}]",
                attachment_type=allure.attachment_type.TEXT
            )
            print(Fore.CYAN + f"[create_plan] Stage 1 完了")
        
        # Stage 2: プランニング
        print(Fore.CYAN + f"[create_plan] Stage 2: プランニング開始")
        
        system_prompt = f"""あなたは効率的なテスト計画を作成するエキスパートです。

【計画作成のルール】

1. ステップの効率化:
   - 関連する連続操作は1つのステップにまとめる
   - 例: 「検索ボックスをタップし、'キーワード'を入力して検索ボタンを押す」
   - NG例: 1.ボックスタップ 2.入力 3.ボタン押下（分割しすぎ）

2. ステップを分割すべきケース:
   - 画面遷移を伴う場合
   - 待機が必要な場合
   - 結果の検証が必要な場合

3. 障害物（ダイアログ等）の処理:
   - 障害物がある場合は、最初のステップで回避する
   - 回避方法: 「閉じる」「スキップ」「後で」「許可しない」等をタップ

4. 禁止事項:
   - アカウント作成は禁止
   - 自動ログインは禁止
   - 不要・重複・曖昧なステップは入れない

{self.knowhow}
"""

        # 画面分析結果がある場合はそれを含める
        if screen_analysis:
            human_message = f"""【目標】
{user_input}

【現在の画面分析結果】
- 画面種類: {screen_analysis.screen_type}
- 主要UI要素: {screen_analysis.main_elements}
- 障害物: {screen_analysis.blocking_dialogs or "なし"}
- 現在の状態: {screen_analysis.current_state}
- 実行可能なアクション: {screen_analysis.available_actions}

【指示】
上記の画面分析結果に基づき、目標達成のための計画を作成してください。
障害物がある場合は、最初のステップでそれを閉じる操作を含めてください。
"""
        else:
            human_message = f"""【目標】
{user_input}

【指示】
目標達成のための計画を作成してください。
"""

        messages = [SystemMessage(content=system_prompt)]
        
        if image_url:
            messages.append(HumanMessage(content=[
                {"type": "text", "text": human_message},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]))
        else:
            messages.append(HumanMessage(content=human_message))

        try:
            structured_llm = self.llm.with_structured_output(Plan)
            
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
            
            print(Fore.CYAN + f"[create_plan] Stage 2 完了: {len(plan.steps)}ステップ")
            return plan
        
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[create_plan] Exception: {err_type}: {e}")
            allure.attach(
                f"Exception Type: {err_type}\nLocation: SimplePlanner.create_plan\nMessage: {e}",
                name="❌ create_plan Exception",
                attachment_type=allure.attachment_type.TEXT
            )
            log_openai_error_to_allure(
                error_type=err_type,
                location="SimplePlanner.create_plan",
                model=self.llm.model_name,
                error=e
            )
            raise

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
                response = await self.replanner.build_response(
                    goal=state["input"],
                    past_steps=state["past_steps"],
                    state_analysis=state_analysis,
                    objective_progress=objective_progress
                )
                print(Fore.GREEN + f"✅ Response生成完了: [{response.status}] {response.reason[:100]}...")
                return Act(action=response, state_analysis=state_summary)
            else:
                plan = await self.replanner.build_plan(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    state_analysis=state_analysis
                )
                print(Fore.YELLOW + f"📋 Plan生成完了: {len(plan.steps)}ステップ")
                return Act(action=plan, state_analysis=state_summary)
        
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
