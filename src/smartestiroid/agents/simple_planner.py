"""
Simple planner for SmartestiRoid test framework.

This module provides a plan-and-execute agent with multi-stage replanning.
"""

import pytest
from typing import Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import allure

from ..models import PlanExecute, Plan, Response, Act
from ..progress import ObjectiveStep, ObjectiveProgress, ObjectiveStepResult, ParsedObjectiveSteps
from ..config import (
    OPENAI_TIMEOUT, OPENAI_MAX_RETRIES,
    MODEL_STANDARD, KNOWHOW_INFO, RESULT_PASS, RESULT_FAIL,
)
from .multi_stage_replanner import MultiStageReplanner
from ..utils.allure_logger import log_openai_error_to_allure
from ..utils.structured_logger import SLog, LogCategory, LogEvent
import smartestiroid.appium_tools as appium_tools


class ScreenAnalysis(BaseModel):
    """画面分析結果のモデル"""
    app_package: Optional[str] = Field(default=None, description="アプリのパッケージ名")
    screen_type: str = Field(description="画面の種類（例：ホーム画面、設定画面、ダイアログ表示中など）")
    main_elements: str = Field(description="画面上の主要なUI要素の説明")
    blocking_dialogs: Optional[str] = Field(default=None, description="目標達成を妨げるダイアログやオーバーレイがある場合、その内容と閉じ方")
    current_state: str = Field(description="現在の画面状態の要約（目標達成に向けた現在位置）")
    available_actions: str = Field(description="この画面で実行可能な主要なアクション")
    
    def to_log_dict(self) -> dict:
        """ログ出力用の辞書を返す"""
        return {
            "app_package": self.app_package,
            "screen_type": self.screen_type,
            "main_elements": self.main_elements,
            "blocking_dialogs": self.blocking_dialogs,
            "current_state": self.current_state,
            "available_actions": self.available_actions
        }
    
    def to_allure_text(self) -> str:
        """Allure表示用の整形されたテキストを返す"""
        lines = [
            "## 📱 画面分析結果",
            f"**アプリのパッケージ名:** {self.app_package}",
            f"**画面タイプ:** {self.screen_type}",
            "",
            "### 現在の状態",
            self.current_state,
            "",
            "### 主要要素",
            self.main_elements,
            "",
            "### 実行可能なアクション",
            self.available_actions,
        ]
        
        if self.blocking_dialogs:
            lines.extend([
                "",
                "### ⚠️ ブロッキングダイアログ",
                f"```",
                self.blocking_dialogs,
                f"```"
            ])
        
        return "\n".join(lines)


class SimplePlanner:
    """テスト用のシンプルなプランナー（Multi-stage replanモード）"""

    def __init__(self, knowhow: str = KNOWHOW_INFO, model_name: str = MODEL_STANDARD, app_package_info: str = "", token_callback=None):
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
        self.app_package_info = app_package_info # アプリ情報を保持
        
        # Multi-stage用のreplanner初期化（token_callbackを渡す）
        self.replanner = MultiStageReplanner(self.llm, self.app_package_info,knowhow, token_callback)
        SLog.log(LogCategory.CONFIG, LogEvent.START, {
            "model": model_name
        }, "🔀 Multi-stage replan モード有効")

    async def analyze_screen(
        self, locator: str, image_url: str, goal: str = "", objective_steps: list[str] = None
    ) -> ScreenAnalysis:
        """画面を分析して現在の状態を把握する（Stage 1）
        
        Args:
            locator: 画面のロケーター情報（XML）
            image_url: 画面のスクリーンショット（base64）
            goal: 目標（オプション、分析の参考情報として使用）
            objective_steps: 目標ステップ一覧（オプション、ダイアログ判定に使用）
            
        Returns:
            ScreenAnalysis: 画面分析結果
        """

        # appium_tools_for_prompt()は通常の関数（awaitは不要）
        tools_info = appium_tools.appium_tools_for_prompt()
        
        # 現在のアプリ情報を取得（LangChainツールとして呼び出し）
        current_app_info = await appium_tools.get_current_app.ainvoke({})

        system_prompt = f"""あなたは画面分析のエキスパートです。
提供された画像とロケーター情報から、現在の画面状態を正確に分析してください。

【目標ステップ】
{objective_steps}

【分析の観点】
0. アプリの種類: どのアプリか（例：Chrome、設定、カメラなど）
1. 画面の種類: 何の画面か（ホーム、設定、検索結果、ダイアログなど）
2. 主要なUI要素: ボタン、入力欄、リスト、アイコンなど
3. 障害物の有無: 目標達成を妨げるダイアログやオーバーレイ
   - 初期設定ダイアログ（プライバシーポリシー、チュートリアルなど）
   - 広告ダイアログ（バナー、全画面広告など）
   - 通知/位置情報許可ダイアログ
   - Cookie同意バナー
   - その他のオーバーレイ
   ★重要: ただし、目標ステップにダイアログ操作が含まれている場合は、そのダイアログはブロッキングダイアログとして扱わない
   （例：目標に「利用規約ダイアログを確認する」があれば、利用規約ダイアログは障害物ではない）
4. 現在の状態: 目標に向けてどの段階にいるか
5. 実行可能なアクション: 目標に向けてこの画面で何ができるか

【厳格ルール】
目標ステップにダイアログ操作が含まれている場合は、そのダイアログはブロッキングダイアログとして扱わない
（例：目標に「利用規約ダイアログを確認する」があれば、利用規約ダイアログは障害物ではない）

【重要】
- 画像とロケーター情報の両方を突き合わせて分析すること
- 障害物がある場合は、それを閉じる方法（ボタンのテキストやXPath）を具体的に示すこと
- 目標ステップにダイアログ操作が含まれている場合、そのダイアログは意図的なものなので障害物として扱わない
"""

        goal_context = f"\n\n【参考】目標: {goal}" if goal else ""
        
        # 目標ステップ情報を追加
        objective_steps_context = ""
        if objective_steps:
            steps_list = "\n".join([f"{i+1}. {step}" for i, step in enumerate(objective_steps)])
            objective_steps_context = f"\n\n【目標ステップ一覧】\n{steps_list}\n※上記ステップにダイアログ操作が含まれている場合、そのダイアログはブロッキングダイアログとして扱わないでください"
        
        human_message = f"""この画面を分析してください。
{goal_context}{objective_steps_context}

{self.app_package_info}

{current_app_info}

【利用可能なツール一覧】
{tools_info}

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
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "analyze_screen",
            "model": self.model_name,
            "system_prompt": system_prompt,
            "user_prompt": human_message
        }, "LLMプロンプト送信: analyze_screen", attach_to_allure=True)

        try:
            structured_llm = self.llm.with_structured_output(ScreenAnalysis)
            
            with self.token_callback.track_query():
                analysis = await structured_llm.ainvoke(messages)
            
            SLog.log(LogCategory.SCREEN, LogEvent.COMPLETE,
                analysis.to_log_dict(),
                "画面分析完了"
            )
            SLog.attach_text(analysis.to_allure_text(), "💡 LLM Response: Screen Analysis")
            return analysis
            
        except Exception as e:
            err_type = type(e).__name__
            SLog.error(LogCategory.ANALYZE, LogEvent.FAIL, {"error_type": err_type, "error": str(e)}, "analyze_screen Exception")
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

2. **★最重要★ ステップ数は元の数に厳密に合わせる**
   - 入力に6ステップあれば、出力も6ステップ
   - 「1. ○○ 2. ○○ 3. ○○」なら3ステップ
   - **番号付きステップの粒度を尊重する**
     - 「2. yahoo.co.jp をURLバーに入力してエンターキーで確定する」→ これは1ステップ（分割禁止）
     - 「2. 設定画面を開く 3. Wi-FiをONにする」→ これは2ステップ（番号が分かれている）
   - **複数のステップを統合してはいけない**（例: 「確認する」と「押す」を「押す」だけにまとめない）

3. **期待結果（確認項目）のみ除外**
   - 「〇〇が表示されること」「〇〇であること」等の**期待結果の記述**は除外（別途処理される）
   - ただし、手順の「〇〇を確認する」というステップは**残す**（操作として必要）
   - ❌NG除外: 「1. ダイアログを確認する 2. ボタンを押す」→「ボタンを押す」（統合は禁止）
   - ✅OK除外: 「1. ボタンを押す 確認項目: ダイアログが閉じること」→「ボタンを押す」（期待結果は除外）

4. **★重要★ ステップは「指示形」で書く**
   - ステップはLLMへの指示であり、結果の確認ではない
   - 「〇〇する」「〇〇を開く」「〇〇をONにする」のように動作指示形にすること
   - ❌NG: 「設定画面が開いている」「Wi-FiがONになっている」（これは結果確認）
   - ✅OK: 「設定画面を開く」「Wi-FiをONにする」（これは動作指示）

5. **「選択する」は「クリックする」「タップする」に置き換える**
   - 「選択する」は曖昧なので、具体的な操作に変換すること
   - 「〇〇を選択する」→「〇〇をクリックする」または「〇〇をタップする」
   - 例: 「メニューアイコンを選択する」→「メニューアイコンをクリックする」

【出力例】
入力: "1. アプリを起動する 2. 利用規約ダイアログを確認する 3. 同意ボタンを押す"
出力: ["アプリを起動する", "利用規約ダイアログを確認する", "同意ボタンを押す"]
（※ 3ステップのまま。統合しない）

入力: "1. Chromeを起動 2. yahoo.co.jpをURLバーに入力してエンターキーで確定する"
出力: ["Chromeを起動する", "yahoo.co.jpをURLバーに入力してエンターキーで確定する"]
（※ 2ステップ。「入力してエンターキーで確定」は1つの操作として扱う。分割禁止）

入力: "1. Chromeを起動 2. yahoo.co.jpに移動 確認項目: ページが表示されること"
出力: ["Chromeを起動する", "yahoo.co.jpに移動する"]
（※ 期待結果「確認項目」は除外、動作指示形で書く）
"""
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "parse_objective_steps",
            "model": self.model_name,
            "prompt": prompt
        }, "LLMプロンプト送信: parse_objective_steps", attach_to_allure=True)

        try:
            structured_llm = self.llm.with_structured_output(ParsedObjectiveSteps)
            
            with self.token_callback.track_query():
                result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
            
            SLog.log(LogCategory.OBJECTIVE, LogEvent.COMPLETE, {
                "step_count": len(result.steps),
                "steps": result.steps
            }, f"目標ステップ解析完了: {len(result.steps)}ステップ")
            
            # Allure用に整形されたテキストを添付
            steps_text = "\n".join([f"{i+1}. {step}" for i, step in enumerate(result.steps)])
            SLog.attach_text(f"## 🎯 目標ステップ ({len(result.steps)}ステップ)\n\n{steps_text}", "💡 LLM Response: Objective Steps")
            
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
            SLog.error(LogCategory.PLAN, LogEvent.FAIL, {"error_type": err_type, "error": str(e)}, "parse_objective_steps Exception")
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
        prompt = f"""目標を達成するための実行計画を作成してください。

与えられた目標に対して、シンプルかつ必要最小限のステップバイステップ計画を作成してください。
この計画は、正しく実行されれば期待結果を得られる個別のタスクで構成される必要があります。
不要・重複・曖昧・推測的なステップは入れないでください。最終ステップの結果が最終的な答えとなります。
また、なぜそのステップ列が最適かを短く根拠説明してください。

【ステップ分離の禁止ルール】
- 同一要素に対して「見つける/探す/特定する」と「クリックする/タップする/選択する」を別ステップに分離しないでください
- 要素への操作は「〇〇をクリックする」「〇〇をタップする」「〇〇に△△を入力する」のように、1ステップで完結させてください
- ただし「〇〇が表示されていることを確認する」「〇〇のテキストを検証する」など、確認・検証が目的のステップは許可されます
- 悪い例: 「メニューアイコンを見つける」→「メニューアイコンをクリックする」（2ステップに分離）
- 良い例: 「メニューアイコンをクリックする」（1ステップで完結）

【目標】
{objective_step.description}

{self.app_package_info}

【画面状態】
{screen_analysis.app_package}
{screen_analysis.screen_type} 

【現在の画面状態の要約】
{screen_analysis.current_state}

【厳格ルール】
- 目標の意味を変えない、拡大解釈しない
- 「確認する」が目標なら確認のみ（操作は不要）
- 「起動する」が目標で既に起動済みの場合でも必ずツールを使って起動する
- 勝手にアクションを追加しない
- ステップは具体的に、かつ簡潔に自然言語で記述し、ツール名や id や xpath を含めてはならない

【ノウハウ集】
{self.knowhow}
- 再起動の場合は再起動ツールを使用すること

【利用可能なツール一覧】
{appium_tools.appium_tools_for_prompt()}
"""

        messages = [HumanMessage(content=prompt)]
        
        # 画像がある場合はマルチモーダルで渡す
        if image_url:
            messages = [HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ])]
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "create_execution_plan_for_objective",
            "model": self.model_name,
            "prompt": prompt,
            "has_image": bool(image_url)
        }, "LLMプロンプト送信: create_execution_plan_for_objective", attach_to_allure=True)

        try:
            structured_llm = self.llm.with_structured_output(Plan)
            
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
            
            SLog.log(LogCategory.PLAN, LogEvent.COMPLETE,
                plan.to_log_dict(),
                f"実行計画生成完了: {len(plan.steps)}アクション"
            )
            SLog.attach_text(plan.to_allure_text(), "💡 LLM Response: Execution Plan")
            
            return plan
            
        except Exception as e:
            err_type = type(e).__name__
            SLog.error(LogCategory.PLAN, LogEvent.FAIL, {"error_type": err_type, "error": str(e)}, "create_execution_plan_for_objective Exception")
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
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "evaluate_objective_completion",
            "model": self.model_name,
            "prompt": prompt,
            "has_image": bool(image_url)
        }, "LLMプロンプト送信: evaluate_objective_completion", attach_to_allure=True)

        try:
            structured_llm = self.llm.with_structured_output(ObjectiveStepResult)
            
            with self.token_callback.track_query():
                result = await structured_llm.ainvoke(messages)
            
            status_icon = "✅" if result.achieved else "❌"
            SLog.log(LogCategory.OBJECTIVE, LogEvent.COMPLETE if result.achieved else LogEvent.FAIL, {
                "objective": objective_step.description[:30],
                "achieved": result.achieved,
                "evidence": result.evidence
            }, f"{status_icon} 目標「{objective_step.description[:30]}...」: {'達成' if result.achieved else '未達成'}")
            SLog.attach_text(result.to_allure_text(), "💡 LLM Response: Objective Evaluation")
            
            return result
            
        except Exception as e:
            err_type = type(e).__name__
            SLog.error(LogCategory.OBJECTIVE, LogEvent.FAIL, {"error_type": err_type, "error": str(e)}, "evaluate_objective_completion Exception")
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
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "create_recovery_plan",
            "model": self.model_name,
            "prompt": prompt,
            "has_image": bool(image_url)
        }, "LLMプロンプト送信: create_recovery_plan", attach_to_allure=True)

        try:
            structured_llm = self.llm.with_structured_output(Plan)
            
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
            
            description = f"障害物を回避: {blocking_reason[:50]}..."
            SLog.log(LogCategory.PLAN, LogEvent.COMPLETE,
                plan.to_log_dict(),
                f"Recovery計画生成: {len(plan.steps)}アクション"
            )
            SLog.attach_text(plan.to_allure_text(), "💡 LLM Response: Recovery Plan")
            
            return description, plan.steps
            
        except Exception as e:
            err_type = type(e).__name__
            SLog.error(LogCategory.PLAN, LogEvent.FAIL, {"error_type": err_type, "error": str(e)}, "create_recovery_plan Exception")
            return f"障害物を回避: {blocking_reason[:30]}...", ["障害物を閉じる"]

    async def replan(
        self,
        state: PlanExecute,
        locator: str,
        image_url: str,
        previous_image_url: str,
        objective_progress: ObjectiveProgress,
        step_history: list = None,
    ) -> Act:
        """実行結果を評価して計画を再調整する
        
        Args:
            state: 現在の実行状態
            locator: 画面のロケーター情報
            image_url: 現在のスクリーンショット
            previous_image_url: 前回のスクリーンショット
            objective_progress: 目標進捗管理オブジェクト（必須）
        """
        import time
        from ..appium_tools import take_screenshot, get_page_source
        
        # 設定値
        SCREEN_INCONSISTENCY_WAIT_SEC = 3  # 画面不整合時の待機時間
        SCREEN_INCONSISTENCY_MAX_RETRIES = 2  # 最大リトライ回数
        
        # Multi-stage replan処理
        try:
            # ★ デバッグ用ウェイト ★
            SLog.log(LogCategory.REPLAN, LogEvent.START, {}, "⏳ Replan前の待機中... (3秒)")
            time.sleep(3)

            # ★ 画面不整合時の再チェックループ ★
            retry_count = 0
            while True:
                SLog.log(LogCategory.REPLAN, LogEvent.EXECUTE, {
                    "stage": 1,
                    "model": self.model_name
                }, "🔀 Multi-stage replan: STAGE 1（State Analysis）")
                state_analysis = await self.replanner.analyze_state(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    locator=locator,
                    previous_image_url=previous_image_url,
                    current_image_url=image_url,
                    objective_progress=objective_progress,
                    step_history=step_history or []
                )
                
                # 画面不整合チェック
                if state_analysis.has_screen_inconsistency():
                    retry_count += 1
                    if retry_count <= SCREEN_INCONSISTENCY_MAX_RETRIES:
                        SLog.warn(LogCategory.SCREEN, LogEvent.RETRY, {
                            "screen_inconsistency": state_analysis.screen_inconsistency,
                            "retry_count": retry_count,
                            "max_retries": SCREEN_INCONSISTENCY_MAX_RETRIES,
                            "wait_sec": SCREEN_INCONSISTENCY_WAIT_SEC
                        }, f"⚠️ 画面不整合を検出、{SCREEN_INCONSISTENCY_WAIT_SEC}秒待機して再チェック")
                        time.sleep(SCREEN_INCONSISTENCY_WAIT_SEC)
                        
                        # 画面情報を再取得（LangChainツールなので.invoke()で呼び出し）
                        previous_image_url = image_url  # 現在の画像を前回として保持
                        locator = get_page_source.invoke({})
                        image_url = take_screenshot.invoke({"as_data_url": True})
                        continue  # 再分析
                    else:
                        # リトライ上限到達 → テスト失敗
                        error_msg = f"画面不整合が{retry_count}回のリトライ後も解消されませんでした。\n詳細: {state_analysis.screen_inconsistency}"
                        SLog.error(LogCategory.SCREEN, LogEvent.FAIL, {
                            "retry_count": retry_count,
                            "screen_inconsistency": state_analysis.screen_inconsistency
                        }, "❌ 画面不整合が解消されません（リトライ上限到達）")
                        SLog.attach_text(error_msg, "❌ 画面不整合（リトライ上限到達）")
                        pytest.fail(error_msg)
                else:
                    # 正常（不整合なし）
                    if retry_count > 0:
                        SLog.log(LogCategory.SCREEN, LogEvent.COMPLETE, {
                            "retry_count": retry_count
                        }, f"✅ 画面不整合が解消されました（{retry_count}回目のリトライで成功）")
                    break  # 正常に続行
            
            # ★ ダイアログ処理モードの切り替え ★
            if state_analysis.blocking_dialogs:
                # ブロッキングダイアログあり → モードに入る（冪等）
                if not objective_progress.is_handling_dialog():
                    objective_progress.enter_dialog_handling_mode()
                    current_step = objective_progress.get_current_step()
                    remaining = objective_progress.get_current_remaining_plan()
                    SLog.log(LogCategory.DIALOG, LogEvent.START, {
                        "blocking_dialogs": state_analysis.blocking_dialogs,
                        "frozen_steps": len(remaining),
                        "target_objective": {"index": current_step.index, "description": current_step.description[:50]},
                        "stop_position": remaining[0][:60] if remaining else None
                    }, "🔒 ダイアログ処理モード開始")
            else:
                # ブロッキングダイアログなし → モードから抜ける
                if objective_progress.is_handling_dialog():
                    dialog_count = objective_progress.get_dialog_handling_count()
                    objective_progress.exit_dialog_handling_mode()
                    remaining = objective_progress.get_current_remaining_plan()
                    current_step = objective_progress.get_current_step()
                    SLog.log(LogCategory.DIALOG, LogEvent.END, {
                        "dialog_steps_executed": dialog_count,
                        "remaining_steps": len(remaining),
                        "resume_position": remaining[0][:60] if remaining else None
                    }, "🔓 ダイアログ処理モード終了 → 通常処理に復帰")
            
            # 全目標達成判定（現在の目標の達成状態を考慮）
            all_objectives_completed = objective_progress.is_all_objectives_completed_with_current(
                state_analysis.current_objective_achieved
            )
            
            # 構造化された状態分析結果をログ出力
            if objective_progress.is_handling_dialog():
                dialog_count = objective_progress.get_dialog_handling_count()
                dialog_mode_info = f"\n処理モード: 🔒 ダイアログ処理中 (累計{dialog_count}ステップ)"
            else:
                dialog_mode_info = f"\n処理モード: 📋 通常処理"
            state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}{dialog_mode_info}
画面不整合: {state_analysis.screen_inconsistency or "なし"}
テスト進捗: {state_analysis.test_progress}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
現在の目標ステップ根拠: {state_analysis.current_objective_evidence}
全ての目標ステップ達成: {"Yes" if all_objectives_completed else "No"}
次のアクション提案: {state_analysis.suggested_next_action or "なし"}
"""
            SLog.log(LogCategory.ANALYZE, LogEvent.COMPLETE, {
                "state_summary": state_summary
            }, "状態分析結果")
            
            SLog.log(LogCategory.REPLAN, LogEvent.EXECUTE, {"stage": 2}, "🔀 Multi-stage replan: STAGE 2（Action Decision）")
            decision, reason = await self.replanner.decide_action(
                goal=state["input"],
                original_plan=state["plan"],
                past_steps=state["past_steps"],
                state_analysis=state_analysis,
                objective_progress=objective_progress
            )
            SLog.log(LogCategory.PLAN, LogEvent.COMPLETE, {
                "decision": decision,
                "reason": reason
            }, f"判定結果: {decision}")
            
            SLog.log(LogCategory.REPLAN, LogEvent.EXECUTE, {"stage": 3}, "🔀 Multi-stage replan: STAGE 3（Output Generation）")
            if decision == "RESPONSE":
                # RESPONSE判定 = テスト終了（成功または失敗）
                SLog.log(LogCategory.REPLAN, LogEvent.UPDATE, {}, "→ RESPONSE分岐に入りました。build_response()を呼び出します...")
                
                # 目標進捗を更新（RESPONSEが返される = 現在の目標が達成または終了）
                if state_analysis.current_objective_achieved:
                    current_step = objective_progress.get_current_step()
                    if current_step.status != "completed":
                        evidence = state_analysis.current_objective_evidence or "状態分析により達成確認"
                        SLog.log(LogCategory.OBJECTIVE, LogEvent.ACHIEVED, {
                            "index": current_step.index,
                            "description": current_step.description[:50]
                        }, f"✅ 目標ステップ完了: [{current_step.index}]")
                        objective_progress.mark_current_completed(evidence=evidence)
                
                try:
                    response = await self.replanner.build_response(
                        goal=state["input"],
                        past_steps=state["past_steps"],
                        state_analysis=state_analysis,
                        objective_progress=objective_progress
                    )
                    SLog.log(LogCategory.TEST, LogEvent.COMPLETE, {
                        "status": response.status,
                        "reason": response.reason[:100]
                    }, f"✅ Response生成完了: [{response.status}]")

                    return Act(
                        action=response,
                        state_analysis=state_summary,
                        current_objective_achieved=state_analysis.current_objective_achieved,
                        current_objective_evidence=state_analysis.current_objective_evidence
                    )
                except Exception as build_err:
                    SLog.error(LogCategory.REPLAN, LogEvent.FAIL, {"error": str(build_err)}, "❌ build_response()でエラー")
                    SLog.attach_text(f"build_response error: {build_err}", "❌ build_response Error")
                    raise
            else:
                # PLAN判定 = まだ継続が必要
                # 現在の目標ステップが達成されている場合は次の目標に進む
                if state_analysis.current_objective_achieved:
                    current_step = objective_progress.get_current_step()
                    if current_step.status != "completed":
                        evidence = state_analysis.current_objective_evidence or "状態分析により達成確認"
                        SLog.log(LogCategory.OBJECTIVE, LogEvent.ACHIEVED, {
                            "index": current_step.index,
                            "description": current_step.description[:50]
                        }, f"✅ 目標ステップ完了: [{current_step.index}]")
                        objective_progress.mark_current_completed(evidence=evidence)
                        
                        # 次の目標に進む
                        has_next = objective_progress.advance_to_next_objective()
                        if has_next:
                            next_objective = objective_progress.get_current_step()
                            SLog.log(LogCategory.OBJECTIVE, LogEvent.CHANGE, {
                                "index": next_objective.index,
                                "description": next_objective.description[:50]
                            }, f"🎯 次の目標ステップに進みます: [{next_objective.index}]")
                
                # 現在の目標（または次の目標）に対する計画を作成
                plan = await self.replanner.build_plan(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    state_analysis=state_analysis,
                    objective_progress=objective_progress,
                    locator=locator,  # ブロッキングダイアログ処理用にロケーター情報を渡す
                    step_history=step_history  # 実行ステップ失敗時のリプラン用
                )
                SLog.log(LogCategory.PLAN, LogEvent.COMPLETE, {
                    "step_count": len(plan.steps)
                }, f"📋 Plan生成完了: {len(plan.steps)}ステップ")
                return Act(
                    action=plan,
                    state_analysis=state_summary,
                    current_objective_achieved=state_analysis.current_objective_achieved,
                    current_objective_evidence=state_analysis.current_objective_evidence
                )
        
        except Exception as e:
            SLog.error(LogCategory.REPLAN, LogEvent.FAIL, {"error": str(e)}, "⚠️ Multi-stage replan エラー")
            SLog.attach_text(f"Multi-stage replan error: {e}", "❌ Multi-stage error")
            # フォールバック: 残りのステップを返す
            remaining_steps = state["plan"][len(state["past_steps"]):]
            if remaining_steps:
                fallback_plan = Plan(steps=remaining_steps)
                SLog.warn(LogCategory.REPLAN, LogEvent.RETRY, {"remaining_steps": len(remaining_steps)}, f"🔄 フォールバック: 残り{len(remaining_steps)}ステップを返却")
                return Act(action=fallback_plan)
            else:
                fallback_response = Response(status=RESULT_PASS, reason=f"エラー発生のため処理を中断します: {e}")
                return Act(action=fallback_response)
