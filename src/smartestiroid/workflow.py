"""ワークフローロジックモジュール

Plan-Executeパターンのワークフロー関数を提供します。
"""

import base64
import allure
from colorama import Fore
from langchain_core.messages import HumanMessage
from langgraph.graph import END

from .models import PlanExecute, Response, ExecutionProgress, ObjectiveProgress
from .config import KNOWHOW_INFO, RESULT_PASS, RESULT_FAIL
# モデル変数（planner_model等）は pytest_configure で動的に変更されるため、
# 直接インポートせず cfg.planner_model のように参照する（config.py のコメント参照）
from . import config as cfg
from .utils import AllureToolCallbackHandler, generate_screen_info


async def analyze_replan_limit_reached(
    state: PlanExecute,
    step_history: list,
    max_replan_count: int,
) -> str:
    """リプラン回数制限到達時に原因分析を行う
    
    Args:
        state: 現在のワークフロー状態
        step_history: 実行されたステップの履歴
        max_replan_count: 最大リプラン回数
        
    Returns:
        LLMによる原因分析結果
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    from .config import OPENAI_TIMEOUT, OPENAI_MAX_RETRIES
    
    # 分析用のLLMを初期化
    analysis_llm = ChatOpenAI(
        model=cfg.evaluation_model,
        timeout=OPENAI_TIMEOUT,
        max_retries=OPENAI_MAX_RETRIES,
    )
    
    # ステップ履歴を整形
    step_history_text = ""
    for i, step_info in enumerate(step_history, 1):
        status = "✅ 成功" if step_info.get("success", False) else "❌ 失敗"
        step_history_text += f"{i}. [{status}] {step_info.get('step', 'Unknown step')}\n"
        step_history_text += f"   応答: {step_info.get('response', 'No response')[:200]}...\n\n"
    
    # past_stepsも整形
    past_steps_text = ""
    for step, result in state.get("past_steps", []):
        past_steps_text += f"- ステップ: {step}\n  結果: {str(result)[:200]}...\n\n"
    
    system_prompt = """あなたはソフトウェアテストの専門家です。
テスト実行がリプラン回数の制限に達して終了した状況を分析し、原因を特定してください。

以下の3つの可能性について言及してください：
1. **テストケースの問題**: テストシナリオや期待値の設定が不適切である可能性
2. **テスト対象アプリの問題**: アプリ自体のバグ、UIの変更、応答遅延などの可能性
3. **テストフレームワーク(smartestiroid)の問題**: ツールの不具合、タイムアウト設定、要素検出の問題など

分析結果はPlantextで以下の形式で出力してください：
---
リプラン回数制限到達の分析:

事実:
何が起きたかの客観的な記述をしなさい

推定原因:
- テストケースの問題
- テスト対象アプリの問題
- テストフレームワークの問題

推奨アクション:
問題解決のための具体的な提案を記述しなさい
---
"""

    user_prompt = f"""以下のテスト実行がリプラン回数制限（{max_replan_count}回）に達して終了しました。
原因を分析してください。

## テスト入力
{state.get("input", "不明")}

## 実行されたステップ履歴
{step_history_text if step_history_text else "履歴なし"}

## 過去のステップと結果
{past_steps_text if past_steps_text else "履歴なし"}

## 現在の計画
{state.get("plan", [])}
"""

    try:
        response = await analysis_llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        return response.content
    except Exception as e:
        return f"原因分析中にエラーが発生しました: {str(e)}"


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
    
    # 進捗追跡（計画ステップとツール呼び出しの関係を管理）
    execution_progress = {"progress": None}  # ExecutionProgressオブジェクトを格納
    
    # 目標進捗管理（ユーザー目標ステップの進捗を管理）
    objective_progress_cache = {"progress": None}  # ObjectiveProgressオブジェクトを格納
    
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
            
            # 現在の進捗を取得（なければ作成）
            if execution_progress["progress"] is None:
                execution_progress["progress"] = ExecutionProgress(original_plan=plan)
                tool_callback.set_execution_progress(execution_progress["progress"])
            
            # 現在のステップインデックスを計算
            # past_stepsの数 = 完了済みステップ数
            completed_count = len(state.get("past_steps", []))
            current_step_index = completed_count
            
            # ステップ実行を開始
            tool_callback.start_step(current_step_index, task)
            
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
            # 進捗情報を計算
            total_steps = len(plan)
            step_number = current_step_index + 1  # 1-indexed for display
            remaining_steps = total_steps - step_number
            
            task_formatted = f"""【あなたの担当】
ステップ{step_number}/{total_steps}: {task}

【厳格ルール】
⚠️ 上記のステップ「{task}」のみを実行してください。
⚠️ このステップが完了したら、追加の操作をせずに終了してください。
⚠️ 次のステップは別のエージェントが担当します。先回りして実行しないでください。

【ステップ完了の判断基準】
- 「activate_app」「terminate_app」→ 該当ツールを1回呼び出したら完了
- 「〇〇をタップ」「〇〇をクリック」→ click_element を1回実行したら完了
- 「〇〇を入力」→ send_keys を1回実行したら完了
- 「〇〇を確認」「〇〇が表示されていることを確認」→ get_page_source で確認したら完了

【全体計画（参考）】
{plan_str}

【画面操作時の注意】
- 画面の変更を起こす操作後に続けて操作を行う場合は get_page_source() で最新状態を取得
- send_keys() は EditText/TextField にのみ使用可能
- 画像とロケーター情報を突き合わせて要素を特定

画面ロケーター情報:
{locator}"""
            
            try:
                # マルチモーダルメッセージとして送信（画像付き）
                with token_callback.track_query():
                    agent_response = await agent_executor.ainvoke(
                        {"messages": [HumanMessage(
                            content=[
                                {"type": "text", "text": task_formatted},
                                {"type": "image_url", "image_url": {"url": image_url}}
                            ]
                        )]},
                        config={"callbacks": [tool_callback]}
                    )
                
                # ツール実行完了後、画面反映を待つ
                # 3秒は経験則値、必要に応じて調整可能
                import asyncio
                await asyncio.sleep(3)

                log_text = f"ステップ '{task}' のエージェント応答: {agent_response['messages'][-1].content}"
                print(Fore.RED + log_text)
                allure.attach(
                    task,
                    name=f"Step [model: {cfg.execution_model}]",
                    attachment_type=allure.attachment_type.TEXT,
                )

                # ステップ完了を記録
                tool_callback.complete_step(
                    agent_response["messages"][-1].content,
                    success=True
                )

                # ツール呼び出し履歴を Allure に保存
                tool_callback.save_to_allure(step_name=task)
                tool_callback.clear()

                allure.attach(
                    agent_response["messages"][-1].content,
                    name=f"Response [model: {cfg.execution_model}]",
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
                
                # ステップ失敗を記録
                tool_callback.complete_step(f"Error: {error_msg}", success=False)
                
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
        # リプラン進捗ログを出力（plan_stepは current=0）
        import json
        print(f"[REPLAN_PROGRESS] {json.dumps({'current_replan_count': 0, 'max_replan_count': max_replan_count, 'status': 'planning'})}")
        
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
                    name=f"🎯Plan [model: {cfg.planner_model}]",
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
                
                # 進捗追跡を初期化（新しい計画で開始）
                execution_progress["progress"] = ExecutionProgress(original_plan=plan.steps)
                tool_callback.set_execution_progress(execution_progress["progress"])
                
                # 目標進捗管理を初期化（ユーザー入力を目標ステップに解析）
                try:
                    objective_progress = await planner.parse_objective_steps(state["input"])
                    # 最初の目標ステップに実行計画を設定
                    current_objective = objective_progress.get_current_step()
                    if current_objective:
                        current_objective.execution_plan = plan.steps
                        current_objective.status = "in_progress"
                    objective_progress_cache["progress"] = objective_progress
                    
                    # 目標ステップをログ出力
                    objective_summary = objective_progress.get_summary()
                    print(Fore.GREEN + f"📋 目標ステップ解析完了:\n{objective_summary}")
                    allure.attach(
                        objective_summary,
                        name="📋 Objective Steps (User Goals)",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                except Exception as e:
                    print(Fore.YELLOW + f"⚠️ 目標解析スキップ（従来モードで継続）: {e}")
                    objective_progress_cache["progress"] = None

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
                
                # 進捗追跡を初期化（フォールバック計画で開始）
                execution_progress["progress"] = ExecutionProgress(original_plan=basic_plan.steps)
                tool_callback.set_execution_progress(execution_progress["progress"])
                
                # フォールバック時は目標解析をスキップ
                objective_progress_cache["progress"] = None

                return {
                    "plan": basic_plan.steps,
                    "replan_count": 0,
                }

    async def replan_step(state: PlanExecute):
        """実行結果を評価して計画を再調整する"""
        current_replan_count = state.get("replan_count", 0)
        
        # 進捗サマリーを取得
        progress_summary = ""
        if execution_progress["progress"]:
            progress_summary = execution_progress["progress"].get_progress_summary()
            print(Fore.CYAN + f"\n{'='*50}")
            print(Fore.CYAN + "📊 現在の進捗状況:")
            print(Fore.CYAN + progress_summary)
            print(Fore.CYAN + f"{'='*50}\n")
        
        # 目標進捗サマリーを取得
        objective_summary = ""
        if objective_progress_cache.get("progress"):
            objective_summary = objective_progress_cache["progress"].get_summary()
            print(Fore.CYAN + f"\n{'='*50}")
            print(Fore.CYAN + "🎯 目標ステップ進捗:")
            print(Fore.CYAN + objective_summary)
            print(Fore.CYAN + f"{'='*50}\n")
        
        # リプラン進捗ログを出力（replan_stepは 1 から順にカウント）
        import json
        print(f"[REPLAN_PROGRESS] {json.dumps({'current_replan_count': current_replan_count + 1, 'max_replan_count': max_replan_count, 'status': 'replanning'})}")
        
        with allure.step(f"Action: Replan [Attempt #{current_replan_count+1}]"):
            import time
            
            # 進捗サマリーをAllureに添付
            if progress_summary:
                allure.attach(
                    progress_summary,
                    name="📊 Execution Progress Before Replan",
                    attachment_type=allure.attachment_type.TEXT,
                )
            
            # 目標進捗をAllureに添付
            if objective_summary:
                allure.attach(
                    objective_summary,
                    name="🎯 Objective Progress Before Replan",
                    attachment_type=allure.attachment_type.TEXT,
                )

            start_time = time.time()
            # リプラン回数制限チェック
            if current_replan_count >= max_replan_count:
                print(
                    Fore.YELLOW
                    + f"リプラン回数が制限に達しました（{max_replan_count}回）。原因分析を実行します..."
                )
                
                # LLMによる原因分析を実行
                analysis_result = await analyze_replan_limit_reached(
                    state=state,
                    step_history=step_history["executed_steps"],
                    max_replan_count=max_replan_count,
                )
                
                # 分析結果をログ出力
                print(Fore.YELLOW + f"\n{'='*60}")
                print(Fore.YELLOW + "リプラン回数制限到達 - 原因分析結果")
                print(Fore.YELLOW + f"{'='*60}")
                print(Fore.YELLOW + analysis_result)
                print(Fore.YELLOW + f"{'='*60}\n")
                
                elapsed = time.time() - start_time
                
                # Allureに分析結果を添付
                allure.attach(
                    analysis_result,
                    name="🔍 リプラン制限到達 - 原因分析",
                    attachment_type=allure.attachment_type.TEXT,
                )
                allure.attach(
                    f"{elapsed:.3f} seconds",
                    name="🧠 Replan Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                
                # 結果メッセージを構築
                response_message = f"""## リプラン回数制限到達

リプラン回数が制限（{max_replan_count}回）に達したため、処理を終了しました。
現在の進捗: {len(state['past_steps'])}ステップ完了

{analysis_result}

{RESULT_FAIL}"""
                
                return {
                    "response": response_message,
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
                replan_result = await planner.replan(
                    state, locator, image_url, previous_image_url,
                    objective_progress=objective_progress_cache.get("progress")
                )

                # 現在画像を次回用にキャッシュに保存
                image_cache["previous_image_url"] = image_url
                print(
                    Fore.YELLOW
                    + f"Replanner Output (replan #{current_replan_count + 1}): {replan_result}"
                )

                if isinstance(replan_result.action, Response):
                    allure.attach(
                        f"Status: {replan_result.action.status}\n\nReason:\n{replan_result.action.reason}",
                        name="Replan Response",
                        attachment_type=allure.attachment_type.TEXT,
                    )

                    evaluated_response = f"{replan_result.action.reason}\n\n{replan_result.action.status}"

                    # 合格判定した場合はその合格判定が正しいかを再評価する
                    # 人間の目視確認が必要な場合はSKIPにする
                    if RESULT_PASS in replan_result.action.status:
                        # 期待動作の抽出（state.inputから期待基準を取得）
                        task_input = state.get("input", "")

                        # リプランナーの判断内容（status, reason）
                        replanner_judgment = f"Status: {replan_result.action.status}\nReason: {replan_result.action.reason}"
                        
                        # リプランナーの状態分析結果
                        state_analysis = replan_result.state_analysis or ""

                        # 合否判定ロジックを適用（ステップ履歴・リプランナー判断・状態分析を含めて）
                        evaluated_response = await evaluate_task_result_func(
                            task_input,
                            evaluated_response,
                            step_history["executed_steps"],
                            replanner_judgment,
                            state_analysis,
                        )

                    allure.attach(
                        evaluated_response,
                        name=f"Final Evalution [model: {cfg.evaluation_model}]",
                        attachment_type=allure.attachment_type.TEXT,
                    )

                    # PASSでない場合は原因分析を実行
                    if RESULT_PASS not in evaluated_response:
                        print(
                            Fore.YELLOW
                            + f"テストがPASSしませんでした。原因分析を実行します..."
                        )
                        
                        # LLMによる原因分析を実行
                        analysis_result = await analyze_replan_limit_reached(
                            state=state,
                            step_history=step_history["executed_steps"],
                            max_replan_count=current_replan_count + 1,
                        )
                        
                        # 分析結果をログ出力
                        print(Fore.YELLOW + f"\n{'='*60}")
                        print(Fore.YELLOW + "テスト失敗 - 原因分析結果")
                        print(Fore.YELLOW + f"{'='*60}")
                        print(Fore.YELLOW + analysis_result)
                        print(Fore.YELLOW + f"{'='*60}\n")
                        
                        # Allureに分析結果を添付
                        allure.attach(
                            analysis_result,
                            name="🔍 テスト失敗 - 原因分析",
                            attachment_type=allure.attachment_type.TEXT,
                        )
                        
                        # 分析結果を含めたレスポンスを構築
                        evaluated_response = f"""{evaluated_response}\n---\n{analysis_result}"""

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
                    formatted_steps = "\n".join(f"{i+1}. {step}" for i, step in enumerate(replan_result.action.steps))
                    if hasattr(replan_result.action, 'reasoning') and replan_result.action.reasoning:
                        formatted_output = f"【計画の根拠】\n{replan_result.action.reasoning}\n\n【実行ステップ】\n{formatted_steps}"
                    else:
                        formatted_output = formatted_steps
                        
                    allure.attach(
                        formatted_output,
                        name=f"🧠 Replan Steps [model: {cfg.planner_model}]",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    elapsed = time.time() - start_time
                    allure.attach(
                        f"{elapsed:.3f} seconds",
                        name="⏱️ Replan Step Time",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    
                    # リプラン後の新しい計画で進捗を更新
                    # 注意: リプランは残りステップの再計画なので、完了済みステップは保持
                    new_plan = replan_result.action.steps
                    if execution_progress["progress"]:
                        # 完了済みステップ数を保持しつつ、新しい計画を設定
                        completed_count = execution_progress["progress"].get_completed_count()
                        # 新しい計画は「残りのステップ」なので、original_planは更新しない
                        # current_step_indexを調整
                        execution_progress["progress"].current_step_index = completed_count
                    
                    return {
                        "plan": new_plan,
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