"""
Simple planner for SmartestiRoid test framework.

This module provides a plan-and-execute agent with multi-stage replanning.
"""

from colorama import Fore
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import allure

from ..models import PlanExecute, Plan, Response, Act
from ..config import (
    OPENAI_TIMEOUT, OPENAI_MAX_RETRIES,
    MODEL_STANDARD, KNOWHOW_INFO, RESULT_PASS
)
from .multi_stage_replanner import MultiStageReplanner
from ..utils.allure_logger import log_openai_error_to_allure


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

    async def create_plan(
        self, user_input: str, locator: str = "", image_url: str = ""
    ) -> Plan:
        
        content = """与えられた目標に対して、効率的かつ必要最小限の計画を作成してください。

【重要】ステップの効率化について:
- 関連する連続操作（例：要素をクリック→テキスト入力→Enterキー押下）は**1つのステップにまとめてください**
- 例: 「URLバーをクリックして"yahoo.co.jp"を入力しEnterで確定する」のように記述
- 不必要に細かく分割しないこと。1つのステップで複数の関連ツールを使用することを推奨

この計画は、正しく実行されれば期待結果を得られるタスクで構成される必要があります。
不要・重複・曖昧・推測的なステップは入れないでください。最終ステップの結果が最終的な答えとなります。
また、なぜそのステップ列が最適かを短く根拠説明してください。
"""
        
        # 制約・ルールは最後に配置（最も重要な情報として強調）
        content += f"\n\n{self.knowhow}"
        print(Fore.CYAN + f"\n\n\n\n[model: {self.model_name}] System Message for create_plan:\n{content}\n")

        messages = [SystemMessage(content=content)]

        human_message_content = f"""
目標: 
{user_input}

指示: 
1. 現在の画面が何を表示しているかを理解する 
主要なUI要素を **画像ベース** 及び **ロケータ（例: XPath, CSS Selector）** によって確認し、それぞれの役割や意図を詳細に説明しなさい

2. 目標達成までのステップ作成
現時点のデバイスのスクリーンの状態を、次のロケータ情報とスクリーンショットの２つを突き合わせて解析し、目標達成に必要なステップを作成しなさい
ただし、各ステップは具体的で実行可能なことを確認し、不要・重複・曖昧・推測的なステップは入れない
**関連する連続操作は1つのステップにまとめること**（例：入力欄クリック→テキスト入力→確定は1ステップ）

3. 計画を作成しなさい
ステップ作成に基づき、目標を達成するための「ステップ」と「そのステップを作成した理由」とともに計画を作成してください


厳格ルール:
- アカウント作成は禁止
- 自動ログインは禁止

出力形式:
厳密なJSON形式

現在のロケーター情報:
{locator}
"""
        print(Fore.CYAN + f"\n\nHuman Message for create_plan:\n{human_message_content[:500]} ...\n")
        
        if image_url:
            messages.append(
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": human_message_content,
                        },
                        {   
                            "type": "image_url", 
                            "image_url": {"url": image_url}
                        },
                    ]
                )
            )
        else:
            messages.append(
                HumanMessage(content="この目標のための計画を作成してください。")
            )

        try:
            structured_llm = self.llm.with_structured_output(Plan)
            
            # track_query()でクエリごとのトークン使用量を記録
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
            
            return plan
        
        except Exception as e:
            # 単一の例外処理: 例外種別と場所のみログ/Allureに記録
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
    ) -> Act:
        # Multi-stage replan処理
            try:
                print(Fore.CYAN + f"🔀 Multi-stage replan: STAGE 1（State Analysis）[model: {self.model_name}]")
                state_summary = await self.replanner.analyze_state(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    locator=locator,
                    previous_image_url=previous_image_url,
                    current_image_url=image_url
                )
                print(Fore.CYAN + f"状態要約:\n{state_summary}")
                allure.attach(state_summary, name=f"🔍 State Analysis Results [model: {self.model_name}]", attachment_type=allure.attachment_type.TEXT)
                
                print(Fore.CYAN + "🔀 Multi-stage replan: STAGE 2（Action Decision）")
                decision, reason = await self.replanner.decide_action(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    state_summary=state_summary
                )
                print(Fore.CYAN + f"判定結果: {decision}\n理由: {reason}")
                allure.attach(f"DECISION: {decision}\n{reason}", name=f"⚖️ Action Decision [model: {self.model_name}]", attachment_type=allure.attachment_type.TEXT)
                
                print(Fore.CYAN + "🔀 Multi-stage replan: STAGE 3（Output Generation）")
                if decision == "RESPONSE":
                    response = await self.replanner.build_response(
                        goal=state["input"],
                        past_steps=state["past_steps"],
                        state_summary=state_summary
                    )
                    print(Fore.GREEN + f"✅ Response生成完了: [{response.status}] {response.reason[:100]}...")
                    return Act(action=response, state_analysis=state_summary)
                else:
                    plan = await self.replanner.build_plan(
                        goal=state["input"],
                        original_plan=state["plan"],
                        past_steps=state["past_steps"],
                        state_summary=state_summary
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
