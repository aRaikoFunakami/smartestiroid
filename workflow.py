"""ワークフローロジックモジュール

Plan-Executeパターンのワークフロー関数を提供します。
"""

import base64
import allure
from colorama import Fore
from langchain_core.messages import HumanMessage
from langgraph.graph import END

from models import PlanExecute, Response
from config import KNOWHOW_INFO, planner_model, execution_model
from utils import AllureToolCallbackHandler, generate_screen_info


def create_workflow_functions(
    planner,
    agent_executor,
    screenshot_tool,
    generate_locators,
    evaluate_task_result_func,
    max_replan_count: int = 10,
    knowhow: str = KNOWHOW_INFO,
    token_callback=None,
):
    """ワークフロー関数を作成する（セッション内のツールを使用）

    Args:
        planner: SimplePlannerインスタンス
        agent_executor: エージェント実行エンジン
        screenshot_tool: スクリーンショット取得ツール
        generate_locators: ロケーター生成ツール
        evaluate_task_result_func: タスク結果評価関数
        max_replan_count: 最大リプラン回数（デフォルト10回）
        knowhow: ノウハウ情報（SimplePlannerに渡される）
        token_callback: トークンカウンターコールバック
        
    Returns:
        tuple: (execute_step, plan_step, replan_step, should_end)
    """

    # 画像キャッシュ（クロージャ内で管理）
    image_cache = {"previous_image_url": ""}

    # ステップ履歴キャッシュ（クロージャ内で管理）
    step_history = {"executed_steps": []}
    
    # ツール呼び出し履歴を記録するコールバックハンドラー
    tool_callback = AllureToolCallbackHandler()

    async def execute_step(state: PlanExecute):
        """計画の最初のステップを実行する"""
        plan = state["plan"]
        with allure.step(f"Action: Execute [{plan[0][:30] if plan else 'No Step'} ...]"):
            import time

            start_time = time.time()
            if not plan:
                return {"past_steps": [("error", "計画が空です")]}
            plan_str = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(plan))
            task = plan[0]
            
            # 現在の画面情報を取得
            locator, image_url = await generate_screen_info(
                screenshot_tool, generate_locators
            )
            
            # ログとAllureには整形したロケーター情報を出力
            allure.attach(
                locator,
                name="📍 Locator Information",
                attachment_type=allure.attachment_type.TEXT
            )
            if image_url:
                allure.attach(
                    base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                    name="📷 Current Screen",
                    attachment_type=allure.attachment_type.JPG,
                )
            
            # タスクにロケーター情報と画像相互補完の指示を含める（LLMには生データを渡す）
            task_formatted = f"""以下の計画について: {plan_str}

あなたはステップ1の実行を担当します: {task}

【重要】画像とロケーター情報の相互補完について:
- 画像には視覚的に見えるアイコンやボタンの位置情報が含まれています
- ロケーター情報には画像で見えない要素のID/XPath/bounds座標が含まれています
- 両方の情報を突き合わせて、ターゲット要素を特定してください

例：
• 画像で「Prime Video」アイコンが見えるが、ロケーターに明確なラベルがない場合
  → 画像の位置とロケーターのbounds座標を照合して要素を特定
• ロケーターに特定のresource-idがあるが、画像では見えない要素の場合
  → ロケーター情報から直接IDやXPathを使用してアクセス

必ず画像とロケーターの両方を確認し、最も確実な方法でターゲット要素を操作してください。

画面ロケーター情報:
{locator}"""
            
            try:
                # 画像がある場合はマルチモーダルメッセージとして送信
                # token_callbackはLLM初期化時に設定済みなので、ここではtool_callbackのみ渡す
                if token_callback:
                    with token_callback.track_query():
                        if image_url:
                            agent_response = await agent_executor.ainvoke(
                                {"messages": [HumanMessage(
                                    content=[
                                        {"type": "text", "text": task_formatted},
                                        {"type": "image_url", "image_url": {"url": image_url}}
                                    ]
                                )]},
                                config={"callbacks": [tool_callback]}
                            )
                        else:
                            agent_response = await agent_executor.ainvoke(
                                {"messages": [("user", task_formatted)]},
                                config={"callbacks": [tool_callback]}
                            )
                else:
                    if image_url:
                        agent_response = await agent_executor.ainvoke(
                            {"messages": [HumanMessage(
                                content=[
                                    {"type": "text", "text": task_formatted},
                                    {"type": "image_url", "image_url": {"url": image_url}}
                                ]
                            )]},
                            config={"callbacks": [tool_callback]}
                        )
                    else:
                        agent_response = await agent_executor.ainvoke(
                            {"messages": [("user", task_formatted)]},
                            config={"callbacks": [tool_callback]}
                        )

                log_text = f"ステップ '{task}' のエージェント応答: {agent_response['messages'][-1].content}"
                print(Fore.RED + log_text)
                allure.attach(
                    task,
                    name=f"Step [model: {execution_model}]",
                    attachment_type=allure.attachment_type.TEXT,
                )


                allure.attach(
                    agent_response["messages"][-1].content,
                    name=f"Response [model: {execution_model}]",
                    attachment_type=allure.attachment_type.TEXT,
                )
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f} seconds",
                    name="⏱️Execute Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )

                # 実行されたステップを履歴に追加
                step_history["executed_steps"].append(
                    {
                        "step": task,
                        "response": agent_response["messages"][-1].content,
                        "timestamp": time.time(),
                        "success": True,
                    }
                )

                return {
                    "past_steps": [(task, agent_response["messages"][-1].content)],
                }
            except Exception as e:
                error_msg = str(e)
                print(Fore.RED + f"execute_stepでエラー: {e}")
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f} seconds",
                    name="Execute Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                
                allure.attach(
                    f"Detail:\n{error_msg}\n\nStep: {task}",
                    name="❌ Execute Step Error",
                    attachment_type=allure.attachment_type.TEXT,
                )

                # エラーも履歴に記録
                step_history["executed_steps"].append(
                    {
                        "step": task,
                        "response": f"Error: {error_msg}",
                        "timestamp": time.time(),
                        "success": False,
                    }
                )

                # エラー発生時はassertで失敗させて次のテストへ
                assert False, f"ステップ実行中にエラーが発生しました: {error_msg}"

    async def plan_step(state: PlanExecute):
        """初期計画を作成する"""
        with allure.step("Action: Plan"):
            import time

            start_time = time.time()
            try:
                locator, image_url = await generate_screen_info(
                    screenshot_tool, generate_locators
                )

                if locator:
                    # ログとAllureには整形したロケーター情報を出力
                    allure.attach(
                        locator,
                        name="📍 Locator Information",
                        attachment_type=allure.attachment_type.TEXT
                    )

                if image_url:
                    allure.attach(
                        base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                        name="📷 Screenshot before Planning",
                        attachment_type=allure.attachment_type.JPG,
                    )

                plan = await planner.create_plan(state["input"], locator, image_url)
                print(Fore.GREEN + f"生成された計画: {plan}")

                # ステップを番号付きリストに整形し、reasoning も含める
                formatted_steps = "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan.steps))
                if plan.reasoning:
                    formatted_output = f"【計画の根拠】\n{plan.reasoning}\n\n【実行ステップ】\n{formatted_steps}"
                else:
                    formatted_output = formatted_steps
                    
                allure.attach(
                    formatted_output,
                    name=f"🎯Plan [model: {planner_model}]",
                    attachment_type=allure.attachment_type.TEXT,
                )

                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f} seconds",
                    name=f"⏱️ Plan Step Time : {elapsed:.3f} seconds",
                    attachment_type=allure.attachment_type.TEXT,
                )

                # 初回画像をキャッシュに保存
                image_cache["previous_image_url"] = image_url

                # ステップ履歴を初期化
                step_history["executed_steps"] = []

                return {
                    "plan": plan.steps,
                    "replan_count": 0,  # 初期化時はreplan_countを0に設定
                }
            except Exception as e:
                print(Fore.RED + f"plan_stepでエラー: {e}")
                # フォールバック: 基本的なプランを作成
                basic_plan = await planner.create_plan(state["input"])
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f} seconds",
                    name=f"Plan Step Time : {elapsed:.3f} seconds",
                    attachment_type=allure.attachment_type.TEXT,
                )
                # エラー時はキャッシュをクリア
                image_cache["previous_image_url"] = ""

                # ステップ履歴も初期化
                step_history["executed_steps"] = []

                return {
                    "plan": basic_plan.steps,
                    "replan_count": 0,
                }

    async def replan_step(state: PlanExecute):
        """実行結果を評価して計画を再調整する"""
        current_replan_count = state.get("replan_count", 0)
        with allure.step(f"Action: Replan [Attempt #{current_replan_count+1}]"):
            import time

            start_time = time.time()
            # リプラン回数制限チェック
            if current_replan_count >= max_replan_count:
                print(
                    Fore.YELLOW
                    + f"リプラン回数が制限に達しました（{max_replan_count}回）。処理を終了します。"
                )
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f} seconds",
                    name="🧠 Replan Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                return {
                    "response": f"リプラン回数が制限（{max_replan_count}回）に達したため、処理を終了しました。現在の進捗: {len(state['past_steps'])}ステップ完了.",
                    "replan_count": current_replan_count + 1,
                }
            try:
                # 前回の画像URLをキャッシュから取得
                previous_image_url = image_cache["previous_image_url"]

                # 現在の画面情報を取得
                locator, image_url = await generate_screen_info(
                    screenshot_tool, generate_locators
                )

                if locator:
                    # ログとAllureには整形したロケーター情報を出力
                    allure.attach(
                        locator,
                        name="📍 Locator Information",
                        attachment_type=allure.attachment_type.TEXT
                    )

                # 前回画像がある場合は比較用として添付
                if previous_image_url:
                    allure.attach(
                        base64.b64decode(
                            previous_image_url.replace("data:image/jpeg;base64,", "")
                        ),
                        name="📷 Previous Screenshot (Before Action)",
                        attachment_type=allure.attachment_type.JPG,
                    )

                # 現在画像を添付
                allure.attach(
                    base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                    name="📷 Current Screenshot (After Action)",
                    attachment_type=allure.attachment_type.JPG,
                )

                # 前回画像と現在画像を使ってリプラン
                output = await planner.replan(
                    state, locator, image_url, previous_image_url
                )

                # 現在画像を次回用にキャッシュに保存
                image_cache["previous_image_url"] = image_url
                print(
                    Fore.YELLOW
                    + f"Replanner Output (replan #{current_replan_count + 1}): {output}"
                )

                if isinstance(output.action, Response):
                    allure.attach(
                        f"Status: {output.action.status}\n\nReason:\n{output.action.reason}",
                        name="Replan Response",
                        attachment_type=allure.attachment_type.TEXT,
                    )

                    evaluated_response = f"{output.action.reason}\n\n{output.action.status}"

                    # 合格判定した場合はその合格判定が正しいかを再評価する
                    # 人間の目視確認が必要な場合はSKIPにする
                    from config import RESULT_PASS
                    if RESULT_PASS in output.action.status:
                        # 期待動作の抽出（state.inputから期待基準を取得）
                        task_input = state.get("input", "")

                        # 合否判定ロジックを適用（ステップ履歴も含めて）
                        evaluated_response = await evaluate_task_result_func(
                            task_input,
                            evaluated_response,
                            step_history["executed_steps"],
                        )

                    allure.attach(
                        evaluated_response,
                        name=f"Final Evalution [model: {planner_model}]",
                        attachment_type=allure.attachment_type.TEXT,
                    )

                    elapsed = time.time() - start_time
                    allure.attach(
                        f"{elapsed:.3f} seconds",
                        name="⏱️ Replan Step Time",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    return {
                        "response": evaluated_response,
                        "replan_count": current_replan_count + 1,
                    }
                else:
                    # ステップを番号付きリストに整形し、reasoning も含める
                    formatted_steps = "\n".join(f"{i+1}. {step}" for i, step in enumerate(output.action.steps))
                    if hasattr(output.action, 'reasoning') and output.action.reasoning:
                        formatted_output = f"【計画の根拠】\n{output.action.reasoning}\n\n【実行ステップ】\n{formatted_steps}"
                    else:
                        formatted_output = formatted_steps
                        
                    allure.attach(
                        formatted_output,
                        name=f"🧠 Replan Steps [model: {planner_model}]",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    elapsed = time.time() - start_time
                    allure.attach(
                        f"{elapsed:.3f} seconds",
                        name="⏱️ Replan Step Time",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    return {
                        "plan": output.action.steps,
                        "replan_count": current_replan_count + 1,
                    }
            except Exception as e:
                print(Fore.RED + f"Error in replan_step: {e}")
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f} seconds",
                    name="⏱️ Replan Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                # エラーの場合は終了
                return {
                    "response": f"エラーが発生しました: {str(e)}",
                    "replan_count": current_replan_count + 1,
                }

    def should_end(state: PlanExecute):
        """ワークフローを終了するか判定する"""
        # レスポンスがある場合は終了
        if "response" in state and state["response"]:
            return END

        # それ以外は継続（replan制限チェックはreplan_step内で行う）
        return "agent"

    return execute_step, plan_step, replan_step, should_end
