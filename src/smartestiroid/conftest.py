from typing import Dict, Any, Optional
from colorama import Fore, init

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage
from appium.options.android import UiAutomator2Options
import base64
from PIL import Image
import io
import allure
import pytest
import json
import os
import asyncio
import time

from .appium_tools import appium_driver, appium_tools
from .appium_tools.token_counter import TiktokenCountCallback

# Import from newly created modules
from .models import (
    PlanExecute, Plan, Response, Act, DecisionResult, EvaluationResult
)
from .config import (
    OPENAI_TIMEOUT, OPENAI_MAX_RETRIES,
    MODEL_STANDARD, MODEL_MINI, MODEL_EVALUATION, MODEL_EVALUATION_MINI,
    RESULT_PASS, RESULT_SKIP, RESULT_FAIL,
    KNOWHOW_INFO
)
# モデル変数（planner_model等）は pytest_configure で動的に変更されるため、
# 直接インポートせず cfg.planner_model のように参照する（config.py のコメント参照）
from . import config as cfg
from .workflow import create_workflow_functions
from .utils.allure_logger import log_openai_error_to_allure
from .utils.device_info import write_device_info_once
from .agents import SimplePlanner


# パッケージのルートディレクトリ
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

# デフォルトのcapabilitiesパス（pytest_configureで更新される）
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
    parser.addoption(
        "--capabilities",
        action="store",
        default="capabilities.json",
        help="Appium capabilities JSONファイルのパス（デフォルト: capabilities.json）"
    )
    parser.addoption(
        "--mini-model",
        action="store_true",
        default=False,
        help="高速・低コストのMiniモデルを使用する"
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
        # 相対パスの場合はカレントディレクトリ基準で解決
        if not os.path.isabs(knowhow_path):
            knowhow_path = os.path.join(os.getcwd(), knowhow_path)
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
    global capabilities_path
    import sys
    
    # --mini-model オプションが指定された場合、環境変数を設定
    if config.getoption("--mini-model"):
        os.environ["USE_MINI_MODEL"] = "1"
        # configモジュールのモデル設定を更新（トップレベルでインポート済みのcfgを使用）
        cfg.use_mini_model = True
        cfg.planner_model = cfg.MODEL_MINI
        cfg.execution_model = cfg.MODEL_MINI
        cfg.evaluation_model = cfg.MODEL_EVALUATION_MINI
        print(Fore.CYAN + "🚀 Miniモデルモードで実行します")
    
    # テストシートパスをグローバル変数として保存
    sys._pytest_testsheet_path = config.getoption("--testsheet")
    
    # capabilities パスを設定（相対パスの場合はカレントディレクトリ基準で解決）
    cap_path = config.getoption("--capabilities")
    if not os.path.isabs(cap_path):
        cap_path = os.path.join(os.getcwd(), cap_path)
    capabilities_path = cap_path


def pytest_collection_modifyitems(session, config, items):
    """pytest がテストを収集した後に呼ばれる（-k フィルタ適用後）
    
    各テストアイテムに実行順と総数を付与する。
    これにより -k で絞られた実際の実行テスト数を正確に取得できる。
    
    注意: このフックは deselect フィルタ適用後に呼ばれるため、
    items には実際に実行されるテストのみが含まれる。
    """
    import sys
    total = len(items)
    sys._pytest_total_tests = total
    sys._pytest_test_order = {}
    
    for i, item in enumerate(items, 1):
        # 各テストに実行順を付与
        item._test_progress_current = i
        item._test_progress_total = total
        # テスト名から順番を引けるようにマップも作成
        sys._pytest_test_order[item.name] = i
    
    # Note: [PROGRESS] collected は pytest_collection_finish で出力


def pytest_collection_finish(session):
    """テスト収集完了後（すべてのフィルタリング適用後）に呼ばれる"""
    import sys
    # session.items には最終的に実行されるテストのみが含まれる
    total = len(session.items)
    sys._pytest_total_tests = total
    
    # 各テストに正しい順番を再設定
    for i, item in enumerate(session.items, 1):
        item._test_progress_current = i
        item._test_progress_total = total
        sys._pytest_test_order[item.name] = i
    
    print(Fore.CYAN + f"\n[PROGRESS] {{\"total\": {total}, \"status\": \"collected\"}}")


def pytest_runtest_setup(item):
    """各テスト実行前に現在のテストアイテムを保存"""
    import sys
    sys._pytest_current_item = item


def pytest_sessionstart(session):
    """テストセッション開始時の処理"""
    print(Fore.CYAN + "\n" + "="*70)
    print(Fore.CYAN + "🚀 Test Session Started")
    print(Fore.CYAN + "="*70)


def pytest_sessionfinish(session, exitstatus):
    """テストセッション終了時に全体の課金情報をAllureレポートに書き込む"""
    print(Fore.CYAN + "\n" + "="*70)
    print(Fore.CYAN + "📊 Generating Global Token Usage Report")
    print(Fore.CYAN + "="*70)
    
    # グローバル統計のテキストはコンソールに出力しない
    global_summary_text = TiktokenCountCallback.format_global_summary()
    
    # Allureレポートディレクトリの確認
    allure_results_dir = session.config.option.allure_report_dir
    if not allure_results_dir:
        # デフォルトのallure-resultsディレクトリを使用
        allure_results_dir = "allure-results"
    
    if not os.path.exists(allure_results_dir):
        os.makedirs(allure_results_dir)
    
    # グローバルサマリーデータを取得
    global_summary = TiktokenCountCallback.get_global_summary()
    session_history = TiktokenCountCallback.get_global_history()
    
    # CSVファイル名を生成（タイムスタンプ付き）
    csv_filename = f"token-usage-{time.strftime('%Y%m%d%H%M%S')}.csv"
    csv_file = os.path.join(allure_results_dir, csv_filename)
    
    # CSVファイルにセッション詳細を保存
    import csv
    with open(csv_file, "w", encoding="utf-8", newline='') as f:
        writer = csv.writer(f)
        # ヘッダー行
        writer.writerow([
            "Session Label",
            "Timestamp",
            "Total Invocations",
            "Total Tokens",
            "Input Tokens",
            "Output Tokens",
            "Cached Tokens",
            "Total Cost (USD)"
        ])
        
        # 各セッションの詳細
        for session in session_history:
            writer.writerow([
                session.get('session_label', ''),
                session.get('timestamp', ''),
                session.get('total_invocations', 0),
                session.get('total_tokens', 0),
                session.get('total_input_tokens', 0),
                session.get('total_output_tokens', 0),
                session.get('total_cached_tokens', 0),
                f"{session.get('total_cost_usd', 0.0):.6f}"
            ])
        
        # サマリー行（空行の後に追加）
        writer.writerow([])
        writer.writerow([
            "TOTAL",
            "",
            global_summary.get('total_invocations', 0),
            global_summary.get('total_tokens', 0),
            global_summary.get('total_input_tokens', 0),
            global_summary.get('total_output_tokens', 0),
            global_summary.get('total_cached_tokens', 0),
            f"{global_summary.get('total_cost_usd', 0.0):.6f}"
        ])
    
    print(Fore.CYAN + f"✅ Token usage CSV written to {csv_file}")
    
    # environment.propertiesの先頭に課金情報を追加
    env_file = os.path.join(allure_results_dir, "environment.properties")
    
    # 既存の内容を読み込む
    existing_content = ""
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            existing_content = f.read()
    
    # 新しい内容を作成（先頭に課金情報）
    total_invocations = global_summary.get('total_invocations', 0)
    avg_cost = global_summary.get('total_cost_usd', 0.0) / total_invocations if total_invocations > 0 else 0.0
    
    with open(env_file, "w", encoding="utf-8") as f:
        # LLM課金情報を先頭に書き込み
        f.write(f"LLM_totalCostUSD={global_summary.get('total_cost_usd', 0.0):.6f}\n")
        f.write(f"LLM_totalTokens={global_summary.get('total_tokens', 0)}\n")
        f.write(f"LLM_totalInvocations={global_summary.get('total_invocations', 0)}\n")
        f.write(f"LLM_avgCostPerCall={avg_cost:.6f}\n")
        f.write(f"BillingDashboardFile={csv_filename}\n")
        f.write("\n")
        
        # 既存の内容を追加
        f.write(existing_content)
    
    print(Fore.CYAN + f"✅ Global token usage written to {env_file}")


async def evaluate_task_result(
    task_input: str, response: str, executed_steps: list = None, replanner_judgment: str = None, state_analysis: str = None, token_callback=None
) -> str:
    """タスク結果を構造化評価し RESULT_PASS / RESULT_SKIP / RESULT_FAIL を厳密返却する
    
    Args:
        task_input: 元のタスク指示
        response: 最終応答
        executed_steps: 実行されたステップ履歴
        replanner_judgment: リプランナーがRESPONSEと判断したときの内容（status, reason）
        state_analysis: リプランナーによる状態分析結果
        token_callback: トークンカウンターコールバック
    """
    # 使用モデルの決定（動的に取得）
    model = cfg.evaluation_model

    # モデルは現状固定（簡素化）
    callbacks = [token_callback] if token_callback else []
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        timeout=OPENAI_TIMEOUT,
        max_retries=OPENAI_MAX_RETRIES,
        callbacks=callbacks if callbacks else None
    )
    print(Fore.CYAN + f"評価用モデル: {model}")

    # 実行ステップ履歴の文字列化
    steps_summary = ""
    if executed_steps:
        for i, step_info in enumerate(executed_steps, 1):
            success_mark = "✓" if step_info["success"] else "✗"
            steps_summary += f"{i}. {success_mark} {step_info['step']}\n"

    evaluation_prompt = f"""
あなたはテスト結果判定のエキスパートです。以下を厳密に検証し JSON のみで返答してください。

# 元タスク指示:
{task_input}

# 実行ステップ履歴:
{steps_summary or '(なし)'}

# 現在の画面状態分析結果:
{state_analysis}

# リプランナーの判断結果:
{replanner_judgment}

# 最終応答:
{response}

# 判定規則:
1. {RESULT_PASS} の条件:
    - 指示手順を過不足なく実行
    - 不要/逸脱ステップなし
    - 応答内に期待基準へ直接対応する具体的根拠（要素ID / text / 画像説明 / 操作結果）が存在
    - 画像評価が必要なケースではその根拠を言及
    - 以下の対応は、本タスクの評価対象外とし、不要あるいは逸脱ステップとして扱わない：プライバシーポリシー、ディスクレーマー、初期設定ダイアログ、広告ダイアログ など

2. {RESULT_SKIP} の条件:
    - 根拠が曖昧 / 反証不能 / 主観的
    - 必要手順不足 or 余計な操作あり
    - ロケータ / 画像確認が必要なのに不十分
    - エラー / 不整合 / 判定困難

# 出力仕様:
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
        
        # track_query()でクエリごとのトークン使用量を記録
        with token_callback.track_query():
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

            # 環境変数でモデル選択（動的に取得）
            print(Fore.CYAN + f"使用モデル: {cfg.execution_model}")

            # トークンカウンターコールバックを作成
            token_callback = TiktokenCountCallback(model=cfg.execution_model)

            # エージェントエグゼキューターを作成（カスタムknowhowを使用）
            llm = ChatOpenAI(
                model=cfg.execution_model,
                temperature=0,
                timeout=OPENAI_TIMEOUT,
                max_retries=OPENAI_MAX_RETRIES,
                callbacks=[token_callback]
            )
            prompt = f"""あなたは親切なAndroidアプリを自動操作するアシスタントです。与えられたタスクを正確に実行してください。\n{knowhow}\n"""

            agent_executor = create_agent(llm, appium_tools(), system_prompt=prompt)
            print(Fore.CYAN + f"Agent Executor用モデル: {cfg.execution_model}")

            planner = SimplePlanner(
                knowhow, 
                model_name=cfg.planner_model,
                token_callback=token_callback
            )

            # LLMに渡されるknowhow情報を表示
            print(Fore.MAGENTA + "=" * 60)
            print(Fore.MAGENTA + "【LLMに渡されるknowhow情報】")
            print(Fore.MAGENTA + "=" * 60)
            print(Fore.CYAN + knowhow)
            print(Fore.MAGENTA + "=" * 60)

            # ワークフロー関数を作成（セッション内のツールを使用）
            max_replan_count = 20
            
            # evaluate_task_resultをラップしてtoken_callbackを渡す
            async def evaluate_with_token_callback(task_input, response, executed_steps, replanner_judgment=None, state_analysis=None):
                return await evaluate_task_result(task_input, response, executed_steps, replanner_judgment, state_analysis, token_callback)
            
            execute_step, plan_step, replan_step, should_end = (
                create_workflow_functions(
                    planner,
                    agent_executor,
                    screenshot_tool,
                    generate_locators,
                    evaluate_with_token_callback,
                    max_replan_count,
                    knowhow,
                    token_callback,
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
                # 最小限: セッションのグローバル保存のみ（表示や添付はしない）
                
                # グローバル統計に保存（テストケースIDをラベルとして使用）
                try:
                    # pytest の現在のテストアイテムからテストIDを取得
                    import sys
                    test_id = "Unknown Test"
                    if hasattr(sys, '_pytest_current_item'):
                        test_id = sys._pytest_current_item.nodeid
                    
                    # グローバル履歴に保存
                    token_callback.save_session_to_global(test_id)
                except Exception:
                    pass
                
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
                allure.attach(
                    f"テスト実行中にエラーが発生しました:\n{e}",
                    name="❌ Test Execution Error",
                    attachment_type=allure.attachment_type.TEXT,
                )
                assert False, f"テスト実行中にエラーが発生しました: {e}"
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
