import operator
from typing import Annotated, List, Tuple, Union, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from colorama import Fore, init

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, START, END
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.messages import HumanMessage, SystemMessage
import base64
from PIL import Image
import io
import allure
import pytest


# Result status constants
EXPECTED_STATS_RESULT = "EXPECTED_STATS_RESULT"
SKIPPED_STATS_RESULT = "SKIPPED_STATS_RESULT"

SERVER_CONFIG = {
    "jarvis-appium": {
        "command": "/opt/homebrew/opt/node@20/bin/npx",
        "args": ["-y", "jarvis-appium"],
        "transport": "stdio",
        "env": {
            "CAPABILITIES_CONFIG": "/Users/raiko.funakami/GitHub/test_robot/capabilities.json",
            "ANDROID_HOME_SDK_ROOT": "/Users/raiko.funakami/Library/Android/sdk",
            "ANDROID_SDK_ROOT": "/Users/raiko.funakami/Library/Android/sdk",
        },
    },
    "jarvis-appium-sse": {
        "url": "http://localhost:7777/sse",
        "transport": "sse",
    },
}

init(autoreset=True)


async def evaluate_task_result(task_input: str, response: str, executed_steps: list = None) -> str:
    """
    LLMを使用してタスクの結果を評価し、適切な結果ステータスを返す。
    
    Args:
        task_input: 元のタスクの指示内容
        response: エージェントからの応答テキスト
        
    Returns:
        評価後の応答テキスト（EXPECTED_STATS_RESULT または SKIPPED_STATS_RESULT を含む）
    """
    # LLMを使用した判定
    llm = ChatOpenAI(model="gpt-5", temperature=0)
    
    # 実行ステップ履歴の文字列化
    steps_summary = ""
    if executed_steps:
        for i, step_info in enumerate(executed_steps, 1):
            success_mark = "✓" if step_info["success"] else "✗"
            steps_summary += f"{i}. {success_mark} {step_info['step']}\n"


    print(f"【実行されたステップ履歴】\n{steps_summary}")
    
    evaluation_prompt = f"""
あなたはテスト結果の合否を判定するエキスパートです。
以下の情報を基に、元のタスク指示で示された合否判定基準通りにテストの判定を行ったかどうかを判定してください。
ロジカルに合格と判定できても、元タスクの指示に従っていない場合はSKIPとしてください。

【元のタスク指示】
{task_input}

【実行されたステップ履歴】
{steps_summary}

【最終的な実行結果】
{response}

以下の基準で判定してください：

1. PASS（合格）の条件：
   - タスクの指示通りに動作が完了している
   - 実行されたステップが元のタスク指示と大きくズレていない
   - 期待基準が明確に満たされている
   - 実行結果が具体的で確認可能
   - 画像で判定しなければならない場合にも、画像を正しく評価している

2. SKIP（要目視確認）の条件：
   - 実行結果が曖昧で確認困難
   - 期待基準と実行結果の対応が不明確
   - エラーや失敗が発生している
   - 判定に主観的要素が含まれる
   - 画像で判定しなければならない場合に、画像を根拠とせずに判定している
   - 実行されたステップが元のタスク指示から大きく逸脱している
   - 不必要なステップが実行されている、または必要なステップが抜けている

判定結果を以下のいずれかで回答してください：
- PASS: タスクが期待通りに完了し、実行ステップも適切な場合
- SKIP: 目視確認が必要な場合

判定理由も含めて回答してください。
"""

    try:
        messages = [
            SystemMessage(content="あなたは正確なテスト結果判定を行うエキスパートです。"),
            HumanMessage(content=evaluation_prompt)
        ]
        
        evaluation_result = await llm.ainvoke(messages)
        evaluation_content = evaluation_result.content.strip().upper()

        
        
        # 判定結果の解析
        if "PASS" in evaluation_content and "SKIP" not in evaluation_content:
            print(Fore.GREEN + f"Re-Evaluation Content: {evaluation_content}")
            return f"{response}\n再判定結果: {evaluation_content}"
        else:
            print(Fore.RED + f"Re-Evaluation Content: {evaluation_content}")
            return f"{response}\n{SKIPPED_STATS_RESULT}\n再判定結果: {evaluation_content}"

    except Exception as e:
        print(f"LLM評価でエラーが発生しました: {e}")
        # エラーの場合は安全側に倒してSKIPにする
        return f"{response}\n{SKIPPED_STATS_RESULT}"


# --- 状態定義 ---
class PlanExecute(TypedDict):
    input: str
    plan: List[str]
    past_steps: Annotated[List[Tuple], operator.add]
    response: str
    replan_count: int  # リプラン回数の追跡


# --- プランモデル ---
class Plan(BaseModel):
    steps: List[str] = Field(description="実行すべき手順の一覧（順序通りに並べる）")


# --- 応答モデル ---
class Response(BaseModel):
    response: str


class Act(BaseModel):
    action: Union[Response, Plan] = Field(
        description="実行するアクション。ユーザーに応答する場合はResponse、さらにツールを使用してタスクを実行する場合はPlanを使用してください。"
    )


# --- シンプルなプランナークラス ---
class SimplePlanner:
    """テスト用のシンプルなプランナー"""

    def __init__(self, pre_action_results: str = ""):
        self.llm = ChatOpenAI(model="gpt-4.1", temperature=0)
        self.pre_action_results = pre_action_results

    async def create_plan(
        self, user_input: str, locator: str = "", image_url: str = ""
    ) -> Plan:
        content = f"""与えられた目標に対して、シンプルなステップバイステップの計画を作成してください。
この計画は、正しく実行されれば正解を得られる個別のタスクで構成される必要があります。
不要なステップは追加しないでください。最終ステップの結果が最終的な答えとなります。
各ステップに必要な情報がすべて含まれていることを確認し、ステップを飛ばさないでください。

目標: {user_input}
実行済みのアクション結果: {self.pre_action_results}"""

        if locator:
            content += f"\n\n画面ロケーター情報: {locator}"

        messages = [SystemMessage(content=content)]

        if image_url:
            messages.append(
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "この画面に基づいて計画を作成してください。",
                        },
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ]
                )
            )
        else:
            messages.append(
                HumanMessage(content="この目標のための計画を作成してください。")
            )

        structured_llm = self.llm.with_structured_output(Plan)
        plan = await structured_llm.ainvoke(messages)
        return plan

    async def replan(
        self, state: PlanExecute, locator: str = "", image_url: str = "", previous_image_url: str = ""
    ) -> Act:
        content = f"""あなたの目標: {state["input"]}
元の計画: {str(state["plan"])}
現在完了したステップ: {str(state["past_steps"])}

重要な指示:
1. メインの目標が完全に達成されているかを必ず分析してください
2. メインの目標を完了するために残りのステップがある場合は、必ず残りのステップを含むPlanを返してください
3. 全体の目標が100%完了し、これ以上のアクションが不要な場合のみResponseを返してください
4. 次に必要なアクションが存在する場合は Response を返してはならない
5. 次に必要なアクションが存在する場合はは、それをPlanに含めてください
6. 前のステップでエラーが発生した場合は、それを考慮して代替アプローチを考えてください。
7. レスポンスを返すときは必ずレスポンスを返した理由を詳細に述べてください。画像の変化やロケーター情報の変化を含めることが重要です。
覚えておいてください: あなたの仕事は、現在の状態を観察するだけでなく、実行可能なステップを提供することです。"""

        if locator:
            content += f"\n\n現在の画面ロケーター情報: {locator}"

        messages = [SystemMessage(content=content)]

        if image_url and previous_image_url:
            # 前回と現在の画像両方がある場合
            messages.append(
                HumanMessage(
                    content=[
                        {"type": "image_url", "image_url": {"url": previous_image_url}},
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {
                            "type": "text",
                            "text": "上記の2つの画像を比較してください。1枚目が前回のアクション実行前の画面、2枚目が現在の画面です。\n\n画面の変化を分析して以下を判断してください：\n1. 前回のアクションが成功したか失敗したか\n2. 期待された変化が起きているか\n3. エラーやローディング状態になっていないか\n4. 目標に向かって進捗があるか\n\n画面変化の分析結果と現在のロケーター情報を踏まえて、目標を完了するための残りのステップを判断してください。残りのステップがある場合はPlanとして、目標が完全に達成された場合のみResponseを返してください。",
                        },
                    ]
                )
            )
        elif image_url:
            # 現在の画像のみの場合（初回など）
            messages.append(
                HumanMessage(
                    content=[
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {
                            "type": "text",
                            "text": "現在の画面状態（スクリーンショットとロケータの2つ）に基づいて、目標を完了するための残りのステップは何ですか？残りのステップがある場合はPlanとして返してください。目標が完全に達成された場合のみResponseを使用してください。必ずロケーター情報も考慮してください。",
                        },
                    ]
                )
            )
        else:
            messages.append(
                HumanMessage(
                    content="目標を完了するための残りのステップは何ですか？残りのステップがある場合はPlanとして返してください。"
                )
            )

        structured_llm = self.llm.with_structured_output(Act)
        act = await structured_llm.ainvoke(messages)
        return act


# --- ヘルパー関数 ---
async def generate_screen_info(screenshot_tool, generate_locators):
    """スクリーンショットとロケーター情報を取得する"""
    print("screenshot_tool 実行...")
    screenshot = await screenshot_tool.ainvoke({})
    print("screenshot_tool 結果:", screenshot[:100] if screenshot else "No screenshot")

    print("generate_locators 実行...")
    locator = await generate_locators.ainvoke({})
    print("generate_locators 結果:", locator[:100] if locator else "No locator")

    if not screenshot:
        return str(locator), ""

    try:
        img_bytes = base64.b64decode(screenshot)
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")

        # 横幅1280px以上ならリサイズ
        if img.width > 1280:
            ratio = 1280 / img.width
            new_size = (1280, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # Vision API用にJPEG形式でbase64化
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        img_bytes_jpeg = buf.getvalue()
        image_url = (
            "data:image/jpeg;base64," + base64.b64encode(img_bytes_jpeg).decode()
        )

        return str(locator), image_url
    except Exception as e:
        print(f"画像処理エラー: {e}")
        return str(locator), ""


# --- ワークフロー関数の定義 ---
def create_workflow_functions(
    planner: SimplePlanner,
    agent_executor,
    screenshot_tool,
    generate_locators,
    max_replan_count: int = 5,
):
    """ワークフロー関数を作成する（セッション内のツールを使用）

    Args:
        max_replan_count: 最大リプラン回数（デフォルト5回）
    """
    
    # 画像キャッシュ（クロージャ内で管理）
    image_cache = {"previous_image_url": ""}
    
    # ステップ履歴キャッシュ（クロージャ内で管理）
    step_history = {"executed_steps": []}

    async def execute_step(state: PlanExecute):
        with allure.step("Action: Execute"):
            import time

            start_time = time.time()
            plan = state["plan"]
            if not plan:
                return {"past_steps": [("error", "計画が空です")]}
            plan_str = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(plan))
            task = plan[0]
            task_formatted = f"""以下の計画について: {plan_str}\n\nあなたはステップ1の実行を担当します: {task}"""
            try:
                agent_response = await agent_executor.ainvoke(
                    {"messages": [("user", task_formatted)]}
                )
                log_text = f"ステップ '{task}' のエージェント応答: {agent_response['messages'][-1].content}"
                print(Fore.RED + log_text)
                allure.attach(
                    task,
                    name="Step",
                    attachment_type=allure.attachment_type.TEXT,
                )
                allure.attach(
                    agent_response["messages"][-1].content,
                    name="Response",
                    attachment_type=allure.attachment_type.TEXT,
                )
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f}秒",
                    name="Execute Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                
                # 実行されたステップを履歴に追加
                step_history["executed_steps"].append({
                    "step": task,
                    "response": agent_response["messages"][-1].content,
                    "timestamp": time.time(),
                    "success": True
                })
                
                return {
                    "past_steps": [(task, agent_response["messages"][-1].content)],
                }
            except Exception as e:
                print(Fore.RED + f"execute_stepでエラー: {e}")
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f}秒",
                    name="Execute Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                
                # エラーも履歴に記録
                step_history["executed_steps"].append({
                    "step": task,
                    "response": f"エラー: {str(e)}",
                    "timestamp": time.time(),
                    "success": False
                })
                
                return {"past_steps": [(task, f"エラー: {str(e)}")]}

    async def plan_step(state: PlanExecute):
        with allure.step("Action: Plan"):
            import time

            start_time = time.time()
            try:
                locator, image_url = await generate_screen_info(
                    screenshot_tool, generate_locators
                )
                plan = await planner.create_plan(state["input"], locator, image_url)
                print(Fore.GREEN + f"生成された計画: {plan}")
                allure.attach(
                    base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                    name="Screenshot before Planning",
                    attachment_type=allure.attachment_type.JPG,
                )
                allure.attach(
                    str(plan.steps),
                    name="Plan",
                    attachment_type=allure.attachment_type.TEXT,
                )
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f}秒",
                    name="Plan Step Time",
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
                    f"{elapsed:.3f}秒",
                    name="Plan Step Time",
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
        with allure.step("Action: Replan"):
            import time

            start_time = time.time()
            current_replan_count = state.get("replan_count", 0)
            # リプラン回数制限チェック
            if current_replan_count >= max_replan_count:
                print(
                    Fore.YELLOW
                    + f"リプラン回数が制限に達しました（{max_replan_count}回）。処理を終了します。"
                )
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f}秒",
                    name="Replan Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                return {
                    "response": f"リプラン回数が制限（{max_replan_count}回）に達したため、処理を終了しました。現在の進捗: {len(state['past_steps'])}ステップ完了。",
                    "replan_count": current_replan_count + 1,
                }
            try:
                # 前回の画像URLをキャッシュから取得
                previous_image_url = image_cache["previous_image_url"]
                
                # 現在の画面情報を取得
                locator, image_url = await generate_screen_info(
                    screenshot_tool, generate_locators
                )
                
                # 前回画像と現在画像を使ってリプラン
                output = await planner.replan(state, locator, image_url, previous_image_url)
                
                # 現在画像を次回用にキャッシュに保存
                image_cache["previous_image_url"] = image_url
                print(
                    Fore.YELLOW
                    + f"Replanner Output (replan #{current_replan_count + 1}): {output}"
                )
                
                # 前回画像がある場合は比較用として添付
                if previous_image_url:
                    allure.attach(
                        base64.b64decode(previous_image_url.replace("data:image/jpeg;base64,", "")),
                        name="Previous Screenshot (Before Action)",
                        attachment_type=allure.attachment_type.JPG,
                    )
                
                # 現在画像を添付
                allure.attach(
                    base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                    name="Current Screenshot (After Action)",
                    attachment_type=allure.attachment_type.JPG,
                )
                if isinstance(output.action, Response):
                    allure.attach(
                        output.action.response,
                        name="Replan Response",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    
                    evaluated_response = output.action.response

                    # 合格判定した場合はその合格判定が正しいかを再評価する
                    # 人間の目視確認が必要な場合はSKIPにする
                    if EXPECTED_STATS_RESULT in evaluated_response:
                        # 期待動作の抽出（state.inputから期待基準を取得）
                        task_input = state.get("input", "")           
                        
                        # 合否判定ロジックを適用（ステップ履歴も含めて）
                        evaluated_response = await evaluate_task_result(
                            task_input,
                            output.action.response, 
                            step_history["executed_steps"]
                        )
                    
                    allure.attach(
                        evaluated_response,
                        name="Evaluated Response",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    
                    elapsed = time.time() - start_time
                    allure.attach(
                        f"{elapsed:.3f}秒",
                        name="Replan Step Time",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    return {
                        "response": evaluated_response,
                        "replan_count": current_replan_count + 1,
                    }
                else:
                    allure.attach(
                        str(output.action.steps),
                        name="Replan Steps",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    elapsed = time.time() - start_time
                    allure.attach(
                        f"{elapsed:.3f}秒",
                        name="Replan Step Time",
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
                    f"{elapsed:.3f}秒",
                    name="Replan Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                # エラーの場合は終了
                return {
                    "response": f"エラーが発生しました: {str(e)}",
                    "replan_count": current_replan_count + 1,
                }

    def should_end(state: PlanExecute):
        # レスポンスがある場合は終了
        if "response" in state and state["response"]:
            return END

        # それ以外は継続（replan制限チェックはreplan_step内で行う）
        return "agent"

    return execute_step, plan_step, replan_step, should_end


async def agent_session():
    """MCPセッション内でgraphを作成し、セッションを維持しながらyieldする"""

    try:
        client = MultiServerMCPClient(SERVER_CONFIG)
        async with client.session("jarvis-appium-sse") as session:
            # ツールを取得
            tools = await load_mcp_tools(session)
            pre_action_results = ""

            # 必要なツールを取得
            select_platform = next(t for t in tools if t.name == "select_platform")
            create_session = next(t for t in tools if t.name == "create_session")
            screenshot_tool = next(t for t in tools if t.name == "appium_screenshot")
            generate_locators = next(t for t in tools if t.name == "generate_locators")

            # プラットフォーム選択とセッション作成
            print("select_platform 実行...")
            platform = await select_platform.ainvoke({"platform": "android"})
            print("select_platform結果:", platform)
            pre_action_results += f"select_platform ツールを呼び出しました: {platform}\n"

            print("create_session 実行...")
            session_result = await create_session.ainvoke({"platform": "android"})
            print("create_session結果:", session_result)
            pre_action_results += (
                f"create_session ツールを呼び出しました: {session_result}\n"
            )

            print(Fore.GREEN + f"pre_action_results: {pre_action_results}")

            # エージェントエグゼキューターを作成
            llm = ChatOpenAI(model="gpt-4.1", temperature=0)
            prompt = "あなたは親切なAndroidアプリを自動操作するアシスタントです。与えられたタスクを正確に実行してください。" \
                "事前に select_platform と create_session を実行済みなので、再度実行してはいけません。" 
            
            agent_executor = create_react_agent(llm, tools, prompt=prompt)

            # プランナーを作成
            planner = SimplePlanner(pre_action_results)

            # ワークフロー関数を作成（セッション内のツールを使用）
            max_replan_count = 10
            execute_step, plan_step, replan_step, should_end = create_workflow_functions(
                planner,
                agent_executor,
                screenshot_tool,
                generate_locators,
                max_replan_count,
            )

            # ワークフローを構築
            workflow = StateGraph(PlanExecute)
            workflow.add_node("planner", plan_step)
            workflow.add_node("agent", execute_step)
            workflow.add_node("replan", replan_step)
            workflow.add_edge(START, "planner")
            workflow.add_edge("planner", "agent")
            workflow.add_edge("agent", "replan")
            workflow.add_conditional_edges("replan", should_end, ["agent", END])
            graph = workflow.compile()

            # graphとpast_stepsをyieldして、セッションを維持
            yield graph
    except Exception as e:
        print(Fore.RED + f"agent_sessionでエラー: {e}")
        raise e
    finally:
        print("セッション終了")


class SmartestiRoid:
    """テスト用のPlan-and-Executeエージェントクラス"""

    def __init__(self, agent_session):
        self.agent_session = agent_session

    async def validate_task(
        self,
        task: str,
        expected_substring: Optional[str] = None,
        ignore_case: bool = False,
    ) -> str:
        config = {"recursion_limit": 50}

        async for graph in self.agent_session():
            # ここでgraphが使用可能（セッション内）
            llm_profile = "あなたは優秀なAndroidアプリのテストエンジニアです。与えられたツールを駆使して、テストのタスクを正確に実行しなさい\n" 
            knowhow = """
            # テストを実行する際のノウハウ集
            ここに記載したことは必ず守ってください:
            
            * 事前に select_platform と create_session を実行済みなので、再度実行してはいけません
            * アプリの操作は、必ずツールを使用して行いなさい
            * アプリの起動や終了も、必ずツールを使用して行いなさい
            * アプリ実行/起動: appium_activate_app を使用せよ
            * アプリ終了: appium_terminate_app を使用せよ
            * 入力確定: appium_press_enter を使用せよ
            
            # テストのタスク
            次の指示に従いなさい:
            """

            inputs = {"input": llm_profile + knowhow + task}

            print(Fore.CYAN + "=== Plan-and-Execute Agent 開始 ===")
            try:
                final_result = {"response": ""}
                async for event in graph.astream(inputs, config=config):
                    for k, v in event.items():
                        if k != "__end__":
                            print(Fore.BLUE + str(v))
                            final_result = v

            except Exception as e:
                print(Fore.RED + f"実行中にエラーが発生しました: {e}")
            finally:
                print(Fore.CYAN + "=== Plan-and-Execute Agent 終了 ===")
            # async forループは一度だけ実行されるのでbreakが不要

        # validation
        result_text = final_result.get("response", None)
        assert result_text is not None, "Agent did not return a final result."

        # SKIPPED_STATS_RESULTが含まれている場合は、pytestでskipする
        if SKIPPED_STATS_RESULT in result_text:
            pytest.skip("このテストは出力結果の目視確認が必要です")

        if expected_substring:
            result_to_check = result_text.lower() if ignore_case else result_text
            substring_to_check = (
                expected_substring.lower() if ignore_case else expected_substring
            )
            assert substring_to_check in result_to_check, (
                f"Assertion failed: Expected '{expected_substring}' not found in agent result: '{result_text}'"
            )
        return result_text

