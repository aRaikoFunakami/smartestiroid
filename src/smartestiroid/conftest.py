from typing import Dict, Any, Optional

from langchain_openai import ChatOpenAI
from .utils.structured_logger import SLog, LogCategory, LogEvent
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

from .appium_tools import appium_driver, appium_tools, set_verify_model
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
    parser.addoption(
        "--test-range",
        action="store",
        default=None,
        help="テストIDの範囲を指定 (例: 0025-0030,0040-0045,0050)"
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
        SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"source": "command_line"}, "カスタムknowhow（直接指定）を使用します")
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
            SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"source": "file", "path": knowhow_path}, f"カスタムknowhow（ファイル: {knowhow_path}）を使用します")
            return knowhow_content
        except FileNotFoundError:
            SLog.warn(LogCategory.CONFIG, LogEvent.FAIL, {"path": knowhow_path}, f"knowhowファイル '{knowhow_path}' が見つかりません。デフォルトを使用します。")
        except Exception as e:
            SLog.warn(LogCategory.CONFIG, LogEvent.FAIL, {"path": knowhow_path, "error": str(e)}, f"knowhowファイルの読み込みエラー: {e}。デフォルトを使用します。")
    
    # デフォルト
    return KNOWHOW_INFO


@pytest.fixture(scope="session")
def testsheet_path(request):
    """テストシートCSVファイルのパスを取得するfixture
    
    --testsheet オプションで指定されたパス、またはデフォルトの testsheet.csv を返す
    """
    path = request.config.getoption("--testsheet")
    SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"testsheet": path}, f"テストシートCSV: {path}")
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
        # verify_screen_content のモデルも更新
        set_verify_model(cfg.MODEL_MINI)
        SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"mode": "mini"}, "Miniモデルモードで実行します")
    
    # テストシートパスをグローバル変数として保存
    sys._pytest_testsheet_path = config.getoption("--testsheet")
    
    # capabilities パスを設定（相対パスの場合はカレントディレクトリ基準で解決）
    cap_path = config.getoption("--capabilities")
    if not os.path.isabs(cap_path):
        cap_path = os.path.join(os.getcwd(), cap_path)
    capabilities_path = cap_path


def _parse_test_range(range_str: str) -> set:
    """テスト範囲文字列をパースしてテストID番号のセットを返す
    
    Args:
        range_str: 範囲指定文字列 (例: "0025-0030,0040-0045,0050")
    
    Returns:
        テストID番号のセット (例: {25, 26, 27, 28, 29, 30, 40, 41, ...})
    """
    result = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            # 範囲指定: "0025-0030"
            start, end = part.split("-", 1)
            try:
                start_num = int(start)
                end_num = int(end)
                for i in range(start_num, end_num + 1):
                    result.add(i)
            except ValueError:
                pass  # 無効な範囲は無視
        else:
            # 単一指定: "0050"
            try:
                result.add(int(part))
            except ValueError:
                pass
    return result


def pytest_collection_modifyitems(session, config, items):
    """pytest がテストを収集した後に呼ばれる（-k フィルタ適用後）
    
    各テストアイテムに実行順と総数を付与する。
    これにより -k で絞られた実際の実行テスト数を正確に取得できる。
    
    注意: このフックは deselect フィルタ適用後に呼ばれるため、
    items には実際に実行されるテストのみが含まれる。
    """
    import sys
    import re
    
    # --test-range オプションによるフィルタリング
    test_range = config.getoption("--test-range", None)
    if test_range:
        allowed_ids = _parse_test_range(test_range)
        selected = []
        deselected = []
        
        for item in items:
            # テスト名から TEST_XXXX の番号を抽出
            match = re.search(r'TEST_(\d+)', item.name)
            if match:
                test_num = int(match.group(1))
                if test_num in allowed_ids:
                    selected.append(item)
                else:
                    deselected.append(item)
            else:
                # TEST_XXXX 形式でないテストは除外
                deselected.append(item)
        
        if deselected:
            config.hook.pytest_deselected(items=deselected)
        items[:] = selected
        
        SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {
            "range": test_range,
            "selected_count": len(selected)
        }, f"--test-range: {len(selected)}件のテストを選択")
    
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
    
    # セッション統計を更新
    if hasattr(sys, '_pytest_session_stats'):
        sys._pytest_session_stats["total"] = total
    
    # 各テストに正しい順番を再設定
    for i, item in enumerate(session.items, 1):
        item._test_progress_current = i
        item._test_progress_total = total
        sys._pytest_test_order[item.name] = i
    
    # テスト総数をログ出力（解析用）
    SLog.log(LogCategory.SESSION, LogEvent.COLLECT, {
        "total_tests": total,
        "test_ids": [item.name for item in session.items]
    }, f"テスト収集完了: {total}件のテストを実行します")


def pytest_runtest_setup(item):
    """各テスト実行前に現在のテストアイテムを保存"""
    import sys
    sys._pytest_current_item = item


def pytest_runtest_logreport(report):
    """各テスト実行後に結果を記録"""
    import sys
    
    # call フェーズ（実際のテスト実行）の結果のみを記録
    if report.when == "call":
        if hasattr(sys, '_pytest_session_stats'):
            stats = sys._pytest_session_stats
            
            if report.passed:
                stats["passed"] += 1
            elif report.failed:
                stats["failed"] += 1
            elif report.skipped:
                stats["skipped"] += 1


def pytest_sessionstart(session):
    """テストセッション開始時の処理"""
    from pathlib import Path
    from datetime import datetime
    import sys
    
    # コマンド実行ごとのタイムスタンプを生成
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1回のコマンド実行ごとのフォルダを作成
    # smartestiroid_logs/run_YYYYMMDD_HHMMSS/
    base_log_dir = Path(os.getcwd()) / "smartestiroid_logs"
    run_log_dir = base_log_dir / f"run_{run_timestamp}"
    run_log_dir.mkdir(parents=True, exist_ok=True)
    
    # セッション全体で共有するためにグローバル変数に保存
    sys._pytest_run_log_dir = run_log_dir
    
    # セッション統計を初期化
    sys._pytest_session_stats = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "start_time": time.time()
    }
    
    # ログを初期化（実行ごとのフォルダ内に保存）
    SLog.init(test_id="session", output_dir=run_log_dir)
    SLog.log(LogCategory.SESSION, LogEvent.START, {
        "timestamp": run_timestamp,
        "log_dir": str(run_log_dir)
    }, f"テストセッション開始 (ログ: {run_log_dir.name})")


def pytest_sessionfinish(session, exitstatus):
    """テストセッション終了時に全体の課金情報をAllureレポートに書き込む"""
    import sys
    
    # テスト結果サマリーをログ出力
    if hasattr(sys, '_pytest_session_stats'):
        stats = sys._pytest_session_stats
        elapsed_time = time.time() - stats.get("start_time", 0)
        
        # SESSION/SUMMARYイベントで統計を出力（解析しやすい形式）
        SLog.log(LogCategory.SESSION, LogEvent.SUMMARY, {
            "total_tests": stats.get("total", 0),
            "passed": stats.get("passed", 0),
            "failed": stats.get("failed", 0),
            "skipped": stats.get("skipped", 0),
            "elapsed_seconds": round(elapsed_time, 2),
            "exit_status": exitstatus
        }, f"テスト結果サマリー: 総数={stats.get('total', 0)}, 成功={stats.get('passed', 0)}, 失敗={stats.get('failed', 0)}, スキップ={stats.get('skipped', 0)}")
    
    SLog.info(LogCategory.TOKEN, LogEvent.START, {"event": "generating_report"}, "Generating Global Token Usage Report")
    
    # テスト終了時のステータスをログ出力
    exit_status_map = {0: "PASSED", 1: "FAILED", 2: "INTERRUPTED", 5: "NO_TESTS"}
    status_str = exit_status_map.get(exitstatus, f"UNKNOWN({exitstatus})")
    SLog.log(LogCategory.SESSION, LogEvent.END, {"exit_status": exitstatus, "status": status_str}, f"テストセッション終了: {status_str}")
    
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
    
    SLog.info(LogCategory.TOKEN, LogEvent.COMPLETE, {"file": csv_file}, f"Token usage CSV written to {csv_file}")
    
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
    
    SLog.info(LogCategory.TOKEN, LogEvent.COMPLETE, {"file": env_file}, f"Global token usage written to {env_file}")
    
    # ログ解析ファイルを自動生成（LLM解析用）
    _generate_log_analysis()
    
    # ログを閉じる
    SLog.close()


def _generate_log_analysis():
    """テスト終了時にログ解析ファイルを自動生成"""
    from .utils.log_analyzer import LogAnalyzer
    from .utils.failure_report_generator import FailureReportGenerator
    
    log_file = SLog.get_log_file()
    if log_file and log_file.exists():
        try:
            analyzer = LogAnalyzer(log_file)
            
            # LLM解析用ファイルを出力
            analyzer.export_for_llm_analysis()
            
            # プロンプトファイルを出力
            analyzer.export_prompts()
            
            SLog.info(
                LogCategory.SESSION, 
                LogEvent.COMPLETE, 
                {"analysis_file": str(log_file.parent / f"{log_file.stem}_analysis.txt")},
                f"ログ解析ファイルを生成しました"
            )
        except Exception as e:
            SLog.warn(
                LogCategory.SESSION,
                LogEvent.FAIL,
                {"error": str(e)},
                f"ログ解析ファイルの生成に失敗: {e}"
            )
        
        # 失敗レポートを生成
        try:
            log_dir = log_file.parent
            generator = FailureReportGenerator(log_dir=log_dir)
            report_path = generator.generate_report()
            SLog.info(
                LogCategory.SESSION,
                LogEvent.COMPLETE,
                {"report_file": str(report_path)},
                f"失敗レポートを生成しました: {report_path.name}"
            )
        except Exception as e:
            SLog.warn(
                LogCategory.SESSION,
                LogEvent.FAIL,
                {"error": str(e)},
                f"失敗レポートの生成に失敗: {e}"
            )


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
    SLog.info(LogCategory.LLM, LogEvent.START, {"model": model, "purpose": "evaluation"}, f"評価用モデル: {model}")

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
    # LLMプロンプトをログ出力
    SLog.log(LogCategory.LLM, LogEvent.START, {
        "method": "evaluate_task_result",
        "prompt": evaluation_prompt
    }, "LLMプロンプト送信: evaluate_task_result", attach_to_allure=True)

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

        # LLMレスポンスをログ出力
        SLog.log(LogCategory.TEST, LogEvent.COMPLETE, {
            "status": status,
            "reason": reason
        }, f"評価完了: {status}")
        SLog.attach_text(eval_struct.to_allure_text(), "💡 LLM Response: Task Evaluation")

        return f"{status}\n判定理由:\n{reason}"
    except Exception as e:
        err_type = type(e).__name__
        SLog.error(LogCategory.LLM, LogEvent.FAIL, {"error_type": err_type, "error": str(e)}, f"[evaluate_task_result] Exception: {err_type}: {e}")
        SLog.attach_text(
            f"Exception Type: {err_type}\nLocation: evaluate_task_result\nMessage: {e}",
            "❌ evaluate_task_result Exception"
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
                "appium:noReset": no_reset, # noResetがTrueならアプリをリセットしない
                "appium:appWaitActivity": "*", # すべてのアクティビティを待機
                "appium:autoGrantPermissions": True, # 権限を自動付与
                "appium:dontStopAppOnReset": dont_stop_app_on_reset, # セッションリセット時にアプリを停止しない
                "appium:adbExecTimeout": 60000,
            })

            # Apply all capabilities from the loaded dictionary
            for key, value in capabilities.items():
                # Set each capability dynamically
                options.set_capability(key, value)
    except FileNotFoundError:
        SLog.error(LogCategory.CONFIG, LogEvent.FAIL, {"path": capabilities_path}, f"警告: {capabilities_path} が見つかりません。")
        raise

    except json.JSONDecodeError:
        SLog.error(LogCategory.CONFIG, LogEvent.FAIL, {"path": capabilities_path}, f"警告: {capabilities_path} のJSON形式が無効です。")
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
            get_page_source_tool = tools_dict.get("get_page_source")
            activate_app = tools_dict.get("activate_app")
            terminate_app = tools_dict.get("terminate_app")
            
            # appPackage情報をknowhowに追加（LLMがテスト対象アプリを認識できるようにする）
            app_package = capabilities.get("appium:appPackage")
            if app_package:
                app_package_info = f"""
テスト対象アプリ情報:
* テスト対象アプリのパッケージID: {app_package}
* activate_app や terminate_app を使用する際は、このパッケージIDを使用してください
* 別のアプリを起動する必要がある場合を除き、このアプリを操作してください
"""
                knowhow = app_package_info + "\n" + knowhow
                SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"app_package": app_package}, f"テスト対象アプリ: {app_package} (knowhowに追加済み)")
            
            # noReset=True の場合、appPackageで指定されたアプリを強制起動
            if no_reset:
                if app_package:
                    SLog.info(LogCategory.SESSION, LogEvent.START, {"app_package": app_package, "no_reset": True}, f"noReset=True: アプリを強制起動します (appPackage={app_package})")
                    try:
                        activate_result = await activate_app.ainvoke({"app_id": app_package})
                        SLog.debug(LogCategory.SESSION, LogEvent.COMPLETE, {"result": str(activate_result)}, None)
                        SLog.info(LogCategory.SESSION, LogEvent.UPDATE, {"wait_seconds": 3}, "アプリ起動待機中... (3秒)")
                        await asyncio.sleep(3)
                    except Exception as e:
                        SLog.warn(LogCategory.SESSION, LogEvent.FAIL, {"error": str(e)}, f"appium_activate_app実行エラー: {e}")
                else:
                    SLog.warn(LogCategory.SESSION, LogEvent.SKIP, {"reason": "no_app_package"}, "appPackageが指定されていないため、アプリ起動をスキップします")
            else:
                # noReset=False の場合は通常通り待機のみ
                SLog.info(LogCategory.SESSION, LogEvent.UPDATE, {"wait_seconds": 3}, "アプリ起動待機中... (3秒)")
                await asyncio.sleep(3)

            # 環境変数でモデル選択（動的に取得）
            SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"model": cfg.execution_model}, f"使用モデル: {cfg.execution_model}")

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
            prompt = f"""
あなたは親切なAndroidアプリをツールで自動操作するアシスタントです。与えられたタスクを正確に実行してください。

重要な前提条件:
- 事前に appium とは接続されています

【ツール呼び出しのルール】（厳守）:
- ツールを使用してアプリを操作します
- ツール以外の方法でアプリを操作してはいけません

【重要】ツール呼び出しの厳格ルール:
- ツールは必ず1つずつ順番に呼び出すこと（並列呼び出し禁止）
- 1つのツールの結果を確認してから次のツールを呼び出すこと
- 例: send_keys → 結果確認 → press_keycode の順で実行

【テキスト入力のルール】（厳守）:
- テキスト入力には必ず send_keys を使用すること
- press_keycode で1文字ずつ入力してはいけない（効率が悪く、キーコード変換エラーが起きやすい）
- press_keycode は特殊キーにのみ使用: Enter(66), Back(4), Home(3), Delete(67) など
- 正しい例: send_keys で "yahoo.co.jp" を入力 → press_keycode 66 で確定
- 誤った例: press_keycode で 'y','a','h','o','o'... と1文字ずつ入力（禁止）

ロケーター戦略の制約 (必ず守ること)
* Androidでは accessibility_id は使用禁止
* 要素を指定する際は必ず 'id' (resource-id), 'xpath', または 'uiautomator' を使用せよ
* 例: {{'by': 'id', 'value': 'com.android.chrome:id/menu_button'}}
* 例: {{'by': 'xpath', 'value': '//android.widget.Button[@content-desc="More options"]'}}

【ドメイン固有ルール】
{knowhow}


"""

            agent_executor = create_agent(llm, appium_tools(), system_prompt=prompt)
            SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"model": cfg.execution_model, "purpose": "agent_executor"}, f"Agent Executor用モデル: {cfg.execution_model}")

            planner = SimplePlanner(
                knowhow, 
                model_name=cfg.planner_model,
                token_callback=token_callback
            )

            # LLMに渡されるknowhow情報を記録
            SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"knowhow_length": len(knowhow)}, "LLMに渡されるknowhow情報を設定")
            SLog.debug(LogCategory.CONFIG, LogEvent.UPDATE, {"knowhow": knowhow}, None)

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
                    get_page_source_tool,
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
                    SLog.info(LogCategory.SESSION, LogEvent.END, {"app_package": app_package}, f"セッション終了: アプリを終了します (appPackage={app_package})")
                    try:
                        terminate_result = await terminate_app.ainvoke({"app_id": app_package})
                        SLog.debug(LogCategory.SESSION, LogEvent.COMPLETE, {"result": str(terminate_result)}, None)
                    except Exception as e:
                        error_msg = str(e)
                        # NoSuchDriverError や session terminated エラーは警告レベルで扱う
                        if "NoSuchDriverError" in error_msg or "session is either terminated or not started" in error_msg or "session" in error_msg.lower():
                            SLog.warn(LogCategory.SESSION, LogEvent.SKIP, {"error": error_msg}, f"セッションが既に終了しています: {e}")
                        else:
                            SLog.warn(LogCategory.SESSION, LogEvent.FAIL, {"error": error_msg}, f"appium_terminate_app実行エラー: {e}")

    except Exception as e:
        error_msg = str(e)
        # NoSuchDriverError や session terminated エラーは情報レベルで扱う
        if "NoSuchDriverError" in error_msg or "session is either terminated or not started" in error_msg:
            SLog.warn(LogCategory.SESSION, LogEvent.SKIP, {"error": error_msg}, f"agent_session: セッションが既に終了しています: {e}")
        else:
            SLog.error(LogCategory.SESSION, LogEvent.FAIL, {"error": error_msg}, f"agent_sessionでエラー: {e}")
            raise e
    finally:
        SLog.info(LogCategory.SESSION, LogEvent.END, None, "セッション終了")


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
                SLog.info(LogCategory.CONFIG, LogEvent.UPDATE, {"custom_knowhow": True}, f"カスタムknowhow情報を使用: {knowhow[:100]}...")

            SLog.info(LogCategory.TEST, LogEvent.START, {"agent": "plan_and_execute"}, "Plan-and-Execute Agent 開始")
            try:
                final_result = {"response": ""}
                async for event in graph.astream(inputs, config=config):
                    for k, v in event.items():
                        if k != "__end__":
                            SLog.debug(LogCategory.STEP, LogEvent.UPDATE, {"event": k, "value": str(v)[:200]}, None)
                            final_result = v

            except Exception as e:
                SLog.error(LogCategory.TEST, LogEvent.FAIL, {"error": str(e)}, f"実行中にエラーが発生しました: {e}")
                SLog.attach_text(
                    f"テスト実行中にエラーが発生しました:\n{e}",
                    "❌ Test Execution Error"
                )
                assert False, f"テスト実行中にエラーが発生しました: {e}"
            finally:
                SLog.info(LogCategory.TEST, LogEvent.END, {"agent": "plan_and_execute"}, "Plan-and-Execute Agent 終了")
            # async forループは一度だけ実行されるのでbreakが不要

        # validation
        result_text = final_result.get("response", None)
        assert result_text is not None, "Agent did not return a final result."

        # RESULT_SKIPが含まれている場合は、pytestでskipする
        if RESULT_SKIP in result_text:
            SLog.log(LogCategory.TEST, LogEvent.SKIP, {"result": "SKIP"}, "⏭️ SKIP: このテストは出力結果の目視確認が必要です")
            pytest.skip("このテストは出力結果の目視確認が必要です")

        # RESULT_FAILが含まれている場合は、テスト失敗として処理
        if RESULT_FAIL in result_text:
            SLog.log(LogCategory.TEST, LogEvent.FAIL, {"result": "FAIL"}, "❌ FAIL: テストが失敗しました")
            # 詳細はworkflow.pyでAllureに添付済みなので、ここでは添付しない
            pytest.fail(f"テストが失敗しました:\n{result_text}")

        # RESULT_PASSが含まれているか確認
        if RESULT_PASS.lower() not in result_text.lower():
            SLog.log(LogCategory.TEST, LogEvent.FAIL, {"result": "FAIL"}, "❌ FAIL: テストが失敗しました（PASSが含まれていない）")
            pytest.fail(f"テストが失敗しました:\n{result_text}")
        
        SLog.log(LogCategory.TEST, LogEvent.COMPLETE, {"result": "PASS"}, "✅ PASS: テストが成功しました")
        return result_text
