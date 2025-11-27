from typing import Dict, Any, Optional
from colorama import Fore, init

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage
import base64
from PIL import Image
import io
import allure
import pytest
import json
import os
import asyncio
import time

from appium_tools import appium_driver, appium_tools
from langchain_core.callbacks import BaseCallbackHandler

# Import from newly created modules
from models import (
    PlanExecute, Plan, Response, Act, DecisionResult, EvaluationResult
)
from config import (
    OPENAI_TIMEOUT, OPENAI_MAX_RETRIES,
    MODEL_STANDARD, MODEL_MINI, MODEL_EVALUATION, MODEL_EVALUATION_MINI,
    planner_model, execution_model, evaluation_model,
    RESULT_PASS, RESULT_SKIP, RESULT_NG,
    KNOWHOW_INFO
)
from workflow import create_workflow_functions
from utils.allure_logger import log_openai_error_to_allure
from utils.device_info import write_device_info_once
from agents import SimplePlanner




capabilities_path = os.path.join(os.getcwd(), "capabilities.json")

init(autoreset=True)


# Pytest hooks for command-line options
def pytest_addoption(parser):
    """pytest コマンドラインオプションを追加"""
    parser.addoption(
        "--knowhow",
        action="store",
        default=None,
        help="カスタムknowhow情報のファイルパス（全テストに適用）"
    )
    parser.addoption(
        "--knowhow-text",
        action="store",
        default=None,
        help="カスタムknowhow情報を直接指定（全テストに適用）"
    )
    parser.addoption(
        "--testsheet",
        action="store",
        default="testsheet.csv",
        help="テストケース定義CSVファイルのパス（デフォルト: testsheet.csv）"
    )


@pytest.fixture(scope="session")
def custom_knowhow(request):
    """カスタムknowhow情報を取得するfixture
    
    優先順位:
    1. --knowhow-text オプション（コマンドラインから直接指定）
    2. --knowhow オプション（ファイルパスから読み込み）
    3. デフォルト（KNOWHOW_INFO）
    """
    # テキストが直接指定された場合（最優先）
    knowhow_text = request.config.getoption("--knowhow-text")
    if knowhow_text:
        print(Fore.CYAN + "📝 カスタムknowhow（直接指定）を使用します")
        return knowhow_text
    
    # ファイルパスが指定された場合
    knowhow_path = request.config.getoption("--knowhow")
    if knowhow_path:
        try:
            with open(knowhow_path, "r", encoding="utf-8") as f:
                knowhow_content = f.read()
            print(Fore.CYAN + f"📝 カスタムknowhow（ファイル: {knowhow_path}）を使用します")
            return knowhow_content
        except FileNotFoundError:
            print(Fore.RED + f"⚠️  警告: knowhowファイル '{knowhow_path}' が見つかりません。デフォルトを使用します。")
        except Exception as e:
            print(Fore.RED + f"⚠️  警告: knowhowファイルの読み込みエラー: {e}。デフォルトを使用します。")
    
    # デフォルト
    return KNOWHOW_INFO


@pytest.fixture(scope="session")
def testsheet_path(request):
    """テストシートCSVファイルのパスを取得するfixture
    
    --testsheet オプションで指定されたパス、またはデフォルトの testsheet.csv を返す
    """
    path = request.config.getoption("--testsheet")
    print(Fore.CYAN + f"📋 テストシートCSV: {path}")
    return path


def pytest_configure(config):
    """pytest設定時にグローバル変数を設定"""
    # テストシートパスをグローバル変数として保存
    import sys
    sys._pytest_testsheet_path = config.getoption("--testsheet")


async def evaluate_task_result(
    task_input: str, response: str, executed_steps: list = None
) -> str:
    """タスク結果を構造化評価し RESULT_PASS / RESULT_SKIP / RESULT_NG を厳密返却する"""
    # 使用モデルの決定
    model = evaluation_model

    # モデルは現状固定（簡素化）
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        timeout=OPENAI_TIMEOUT,
        max_retries=OPENAI_MAX_RETRIES
    )
    print(Fore.CYAN + f"評価用モデル: {model}")

    # 実行ステップ履歴の文字列化
    steps_summary = ""
    if executed_steps:
        for i, step_info in enumerate(executed_steps, 1):
            success_mark = "✓" if step_info["success"] else "✗"
            steps_summary += f"{i}. {success_mark} {step_info['step']}\n"

    print(f"【実行されたステップ履歴】\n{steps_summary}")

    evaluation_prompt = f"""
あなたはテスト結果判定のエキスパートです。以下を厳密に検証し JSON のみで返答してください。

【元タスク指示】
{task_input}

【実行ステップ履歴】
{steps_summary or '(なし)'}

【最終応答】
{response}

判定規則:
1. {RESULT_PASS} の条件:
    - 指示手順を過不足なく実行
    - 不要/逸脱ステップなし
    - 初期設定ダイアログ対応や広告ダイアログ対応は不要/逸脱ステップに含めない
    - 応答内に期待基準へ直接対応する具体的根拠（要素ID / text / 画像説明 / 操作結果）が存在
    - 画像評価が必要なケースではその根拠を言及
2. {RESULT_SKIP} の条件:
    - 根拠が曖昧 / 反証不能 / 主観的
    - 必要手順不足 or 余計な操作あり
    - ロケータ / 画像確認が必要なのに不十分
    - エラー / 不整合 / 判定困難

出力仕様:
厳密JSON
"""
    print(Fore.CYAN + "[evaluate_task_result] 評価プロンプトを生成")
    print(Fore.CYAN + evaluation_prompt)

    try:
        messages = [
            SystemMessage(content="あなたは正確なテスト結果判定を行うエキスパートです。JSONのみ返答。"),
            HumanMessage(content=evaluation_prompt),
        ]
        structured_llm = llm.with_structured_output(EvaluationResult)
        eval_struct: EvaluationResult = await structured_llm.ainvoke(messages)

        status = eval_struct.status
        reason = eval_struct.reason.strip()

        color = Fore.GREEN if status == RESULT_PASS else Fore.RED
        print(color + f"[evaluate_task_result] status={status}")

        return f"{status}\n判定理由:\n{reason}"
    except Exception as e:
        err_type = type(e).__name__
        print(Fore.RED + f"[evaluate_task_result] Exception: {err_type}: {e}")
        allure.attach(
            f"Exception Type: {err_type}\nLocation: evaluate_task_result\nMessage: {e}",
            name="❌ evaluate_task_result Exception",
            attachment_type=allure.attachment_type.TEXT
        )
        log_openai_error_to_allure(
            error_type=err_type,
            location="evaluate_task_result",
            model=model,
            error=e
        )
        return f"{RESULT_SKIP}\n判定理由: 評価中エラー ({err_type})"


# --- ヘルパー関数 ---
# (generate_screen_info は utils.screen_helper に移動)


# --- ワークフロー関数の定義 ---
async def agent_session(no_reset: bool = True, dont_stop_app_on_reset: bool = False, knowhow: str = KNOWHOW_INFO):
    """MCPセッション内でgraphを作成し、セッションを維持しながらyieldする

    Args:
        no_reset: appium:noResetの設定値。True（デフォルト）はリセットなし、Falseはリセットあり。
        knowhow: ノウハウ情報。デフォルトはKNOWHOW_INFO、カスタムknowhowを渡すことも可能。
    """
    
    from appium.options.android import UiAutomator2Options
    options = UiAutomator2Options()
    capabilities = {}

    try:
        with open(capabilities_path, "r") as f:
            capabilities = json.load(f)

            # 任意の追加設定
            capabilities.update({
                "appium:waitForIdleTimeout": 1000, # 高速化のため待機タイムアウトを1秒に設定
                "appium:noReset": no_reset, # noResetがTrueならアプリをリセットしない
                "appium:appWaitActivity": "*", # すべてのアクティビティを待機
                "appium:autoGrantPermissions": True, # 権限を自動付与
                "appium:dontStopAppOnReset": dont_stop_app_on_reset, # セッションリセット時にアプリを停止しない
            })

            # Apply all capabilities from the loaded dictionary
            for key, value in capabilities.items():
                # Set each capability dynamically
                options.set_capability(key, value)
    except FileNotFoundError:
        print(
            f"警告: {capabilities_path} が見つかりません。"
        )
        raise

    except json.JSONDecodeError:
        print(
            f"警告: {capabilities_path} のJSON形式が無効です。デフォルト設定で実行します。"
        )
        raise

    

    try:
        async with appium_driver(options) as driver:
            # 最初のセッション開始時にデバイス情報を取得して書き込む
            await write_device_info_once(
                driver=driver,
                capabilities_path=capabilities_path,
                appium_tools_func=appium_tools
            )

            # 必要なツールを取得（リストから名前で検索）
            tools_list = appium_tools()
            tools_dict = {tool.name: tool for tool in tools_list}
            screenshot_tool = tools_dict.get("take_screenshot")
            generate_locators = tools_dict.get("get_page_source")
            activate_app = tools_dict.get("activate_app")
            terminate_app = tools_dict.get("terminate_app")
            # noReset=True の場合、appPackageで指定されたアプリを強制起動
            if no_reset:
                app_package = capabilities.get("appium:appPackage")
                if app_package:
                    print(Fore.CYAN + f"noReset=True: アプリを強制起動します (appPackage={app_package})")
                    try:
                        activate_result = await activate_app.ainvoke({"app_id": app_package})
                        print(f"appium_activate_app結果: {activate_result}")
                        print("アプリ起動待機中... (3秒)")
                        await asyncio.sleep(3)
                    except Exception as e:
                        print(Fore.YELLOW + f"⚠️  appium_activate_app実行エラー: {e}")
                else:
                    print(Fore.YELLOW + "⚠️  appPackageが指定されていないため、アプリ起動をスキップします")
            else:
                # noReset=False の場合は通常通り待機のみ
                print("アプリ起動待機中... (3秒)")
                await asyncio.sleep(3)

            # 環境変数でモデル選択
            print(Fore.CYAN + f"使用モデル: {execution_model}")

            # エージェントエグゼキューターを作成（カスタムknowhowを使用）
            llm = ChatOpenAI(
                model=execution_model,
                temperature=0,
                timeout=OPENAI_TIMEOUT,
                max_retries=OPENAI_MAX_RETRIES
            )
            prompt = f"""あなたは親切なAndroidアプリを自動操作するアシスタントです。与えられたタスクを正確に実行してください。\n{knowhow}\n"""

            agent_executor = create_agent(llm, appium_tools(), system_prompt=prompt)
            print(Fore.CYAN + f"Agent Executor用モデル: {execution_model}")

            planner = SimplePlanner(
                knowhow, 
                model_name=planner_model,
            )

            # LLMに渡されるknowhow情報を表示
            print(Fore.MAGENTA + "=" * 60)
            print(Fore.MAGENTA + "【LLMに渡されるknowhow情報】")
            print(Fore.MAGENTA + "=" * 60)
            print(Fore.CYAN + knowhow)
            print(Fore.MAGENTA + "=" * 60)

            # ワークフロー関数を作成（セッション内のツールを使用）
            max_replan_count = 20
            execute_step, plan_step, replan_step, should_end = (
                create_workflow_functions(
                    planner,
                    agent_executor,
                    screenshot_tool,
                    generate_locators,
                    evaluate_task_result,
                    max_replan_count,
                    knowhow,
                )
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
            try:
                yield graph
            finally:
                # セッション終了前にアプリを終了
                app_package = capabilities.get("appium:appPackage")
                dont_stop_app_on_reset = capabilities.get("appium:dontStopAppOnReset")
                if app_package and not dont_stop_app_on_reset:
                    print(Fore.CYAN + f"セッション終了: アプリを終了します (appPackage={app_package})")
                    try:
                        terminate_result = await terminate_app.ainvoke({"app_id": app_package})
                        print(f"appium_terminate_app結果: {terminate_result}")
                    except Exception as e:
                        error_msg = str(e)
                        # NoSuchDriverError や session terminated エラーは警告レベルで扱う
                        if "NoSuchDriverError" in error_msg or "session is either terminated or not started" in error_msg or "session" in error_msg.lower():
                            print(Fore.YELLOW + f"⚠️  セッションが既に終了しています: {e}")
                        else:
                            print(Fore.YELLOW + f"⚠️  appium_terminate_app実行エラー: {e}")

    except Exception as e:
        error_msg = str(e)
        # NoSuchDriverError や session terminated エラーは情報レベルで扱う
        if "NoSuchDriverError" in error_msg or "session is either terminated or not started" in error_msg:
            print(Fore.YELLOW + f"⚠️  agent_session: セッションが既に終了しています: {e}")
        else:
            print(Fore.RED + f"agent_sessionでエラー: {e}")
            raise e
    finally:
        print("セッション終了")


class SmartestiRoid:
    """テスト用のPlan-and-Executeエージェントクラス"""

    def __init__(self, agent_session, no_reset: bool = True, dont_stop_app_on_reset: bool = False, knowhow: str = KNOWHOW_INFO):
        self.agent_session = agent_session
        self.no_reset = no_reset
        self.dont_stop_app_on_reset = dont_stop_app_on_reset
        self.knowhow = knowhow  # ノウハウ情報を保持

    async def validate_task(
        self,
        steps: str,
        expected: str = "",
        knowhow: Optional[str] = None,
    ) -> str:
        """
        タスクを実行して結果を検証する
        
        Args:
            task: 実行するタスク
            ignore_case: 大文字小文字を無視するか
            knowhow: カスタムknowhow情報（Noneの場合はインスタンスのknowhowを使用）
        """
        config = {"recursion_limit": 50}

        # knowhowの決定: メソッド引数 > インスタンス変数 > デフォルト
        effective_knowhow = knowhow if knowhow is not None else self.knowhow

        # カスタムknowhowを使用する場合、新しいセッションを作成
        async for graph in self.agent_session(self.no_reset, self.dont_stop_app_on_reset, effective_knowhow):
            # state["input"]には純粋なタスクのみを渡す
            # knowhowは各LLM（SimplePlanner、agent_executor）が既に持っている
            task = (
                f"テスト実施手順:{steps}\n\n"
                f"テスト合否判定基準:{expected}\n"
            )
            inputs = {"input": task}
            
            if knowhow is not None:
                print(Fore.YELLOW + f"カスタムknowhow情報を使用: {knowhow[:100]}...")

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

        # RESULT_SKIPが含まれている場合は、pytestでskipする
        if RESULT_SKIP in result_text:
            pytest.skip("このテストは出力結果の目視確認が必要です")

        if RESULT_PASS:
            result_to_check = result_text.lower()
            substring_to_check = (
                RESULT_PASS.lower()
            )
            assert substring_to_check in result_to_check, (
                f"Assertion failed: Expected '{RESULT_PASS}' not found in agent result: '{result_text}'"
            )
        return result_text
