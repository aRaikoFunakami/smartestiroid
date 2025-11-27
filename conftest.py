import operator
from typing import Annotated, List, Tuple, Union, Optional, Dict, Any, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from colorama import Fore, init

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.graph import StateGraph, START, END
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
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

# 不要となった詳細例外型や時間計測は簡素化のため削除

capabilities_path = os.path.join(os.getcwd(), "capabilities.json")

# OpenAI API timeout settings
OPENAI_TIMEOUT = 180.0  # 180秒
OPENAI_MAX_RETRIES = 1  # リトライ1回

# Result status constants
EXPECTED_STATS_RESULT = "EXPECTED_STATS_RESULT"
SKIPPED_STATS_RESULT = "SKIPPED_STATS_RESULT"

# Knowhow information for all LLMs
KNOWHOW_INFO = """
重要な前提条件:
* 事前に appium とは接続されています
* アプリ起動時にプライバシーポリシーが表示された場合、同意操作を行ってください
* アプリ起動時にディスクリーマーポリシーが表示された場合、同意操作を行ってください
* 必要に応じてスクロール操作でポリシーを全文表示させてから同意してください
* アプリ起動時に初期設定ダイアログが表示された場合、適切に対応してください
* アプリ起動時に広告ダイアログが表示された場合、閉じる操作を行ってください

ツール使用のルール - 必ず守ること:
* アプリの操作は、必ずツールを使用して行いなさい
* アプリの起動や終了も、必ずツールを使用して行いなさい
* アプリ実行/起動: activate_app を使用せよ (但し、既に指定のアプリが起動している場合はスキップ処理で良い)
* アプリ終了: terminate_app を使用せよ
* 入力確定: press_keycode で <Enter> を使用せよ

禁止事項:
* アカウント情報の入力やログイン操作は行わないでください
* 新しいアカウントの作成や登録は行わないでください
"""

SERVER_CONFIG = {
    "jarvis-appium-sse": {
        "url": "http://localhost:7777/sse",
        "transport": "sse",
    },
}

init(autoreset=True)


class AllureToolCallbackHandler(BaseCallbackHandler):
    """Allure にツール呼び出し履歴を記録するコールバックハンドラー"""
    
    def __init__(self):
        super().__init__()
        self.tool_calls = []
        self.current_step = None
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """ツール呼び出し開始時"""
        tool_name = serialized.get("name", "Unknown")
        timestamp = time.time()
        
        # input_str が辞書やオブジェクトの場合は文字列化
        input_display = str(input_str) if input_str is not None else ""
        
        tool_call = {
            "tool_name": tool_name,
            "input": input_display,
            "start_time": timestamp,
            "end_time": None,
            "output": None,
            "error": None,
        }
        self.tool_calls.append(tool_call)
        
        print(Fore.YELLOW + f"🔧 Tool Start: {tool_name}")
        print(Fore.YELLOW + f"   Input: {input_display[:200]}...")
    
    def on_tool_end(self, output: str, **kwargs) -> None:
        """ツール呼び出し終了時"""
        if self.tool_calls:
            tool_call = self.tool_calls[-1]
            tool_call["end_time"] = time.time()
            # output が複雑なオブジェクトの場合は文字列化
            tool_call["output"] = str(output) if output is not None else None
            
            elapsed = tool_call["end_time"] - tool_call["start_time"]
            print(Fore.GREEN + f"✅ Tool End: {tool_call['tool_name']} ({elapsed:.2f}s)")
            print(Fore.GREEN + f"   Output: {str(output)[:200]}...")
    
    def on_tool_error(self, error: BaseException, **kwargs) -> None:
        """ツール呼び出しエラー時"""
        if self.tool_calls:
            tool_call = self.tool_calls[-1]
            tool_call["end_time"] = time.time()
            tool_call["error"] = str(error)
            
            elapsed = tool_call["end_time"] - tool_call["start_time"]
            print(Fore.RED + f"❌ Tool Error: {tool_call['tool_name']} ({elapsed:.2f}s)")
            print(Fore.RED + f"   Error: {str(error)[:200]}...")
    
    def save_to_allure(self, step_name: str = None):
        """Allure にツール呼び出し履歴を保存"""
        if not self.tool_calls:
            return
        
        # JSON形式で保存
        tool_history_json = json.dumps(self.tool_calls, indent=2, ensure_ascii=False)
        allure.attach(
            tool_history_json,
            name="[DEBUG] Tool Calls History",
            attachment_type=allure.attachment_type.JSON,
        )
    
    def clear(self):
        """履歴をクリア"""
        self.tool_calls = []


def log_openai_timeout_to_allure(location: str, model: str, elapsed: float, context: dict = None):
    """OpenAI タイムアウトエラーを Allure に記録する共通関数
    
    Args:
        location: 発生箇所（関数名など）
        model: モデル名
        elapsed: 経過時間（秒）
        context: 追加のコンテキスト情報（辞書形式）
    """
    error_details = f"""OpenAI API タイムアウト
発生箇所: {location}
モデル: {model}
経過時間: {elapsed:.2f}秒 / タイムアウト設定: {OPENAI_TIMEOUT}秒"""
    
    if context:
        error_details += "\n\nコンテキスト:"
        for key, value in context.items():
            error_details += f"\n- {key}: {value}"
    
    print(Fore.RED + f"❌ OpenAI API タイムアウト in {location}: {elapsed:.2f}秒")
    
    allure.attach(
        error_details,
        name=f"🚨 OpenAI Timeout in {location}",
        attachment_type=allure.attachment_type.TEXT
    )
    allure.dynamic.label("error_type", "openai_timeout")
    allure.dynamic.label("error_location", location)
    allure.dynamic.label("model", model)


def log_openai_error_to_allure(error_type: str, location: str, model: str, error: Exception, context: dict = None):
    """OpenAI API エラー全般を Allure に記録する共通関数
    
    Args:
        error_type: エラー種別（RateLimitError, APIError など）
        location: 発生箇所（関数名など）
        model: モデル名
        error: 例外オブジェクト
        context: 追加のコンテキスト情報（辞書形式）
    """
    error_details = f"""OpenAI API エラー
エラー種別: {error_type}
発生箇所: {location}
モデル: {model}
エラー内容: {str(error)}"""
    
    if context:
        error_details += "\n\nコンテキスト:"
        for key, value in context.items():
            error_details += f"\n- {key}: {value}"
    
    # エラー種別に応じた色分け
    if error_type == "RateLimitError":
        print(Fore.YELLOW + f"⚠️  OpenAI API レート制限 in {location}")
    elif error_type == "AuthenticationError":
        print(Fore.RED + f"🔐 OpenAI API 認証エラー in {location}")
    elif error_type == "APIConnectionError":
        print(Fore.YELLOW + f"🌐 OpenAI API 接続エラー in {location}")
    else:
        print(Fore.RED + f"❌ OpenAI API エラー ({error_type}) in {location}")
    
    allure.attach(
        error_details,
        name=f"🚨 OpenAI {error_type} in {location}",
        attachment_type=allure.attachment_type.TEXT
    )
    allure.dynamic.label("error_type", f"openai_{error_type.lower()}")
    allure.dynamic.label("error_location", location)
    allure.dynamic.label("model", model)


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
    """タスク結果を構造化評価し EXPECTED_STATS_RESULT / SKIPPED_STATS_RESULT を厳密返却する"""
    use_mini_model = os.environ.get("USE_MINI_MODEL", "0") == "1"
    if use_mini_model:
        print(Fore.CYAN + "🔀 Miniモデルによる再評価モード有効")
        model = "gpt-5-mini"
    else:
        model = "gpt-5"

    # モデルは現状固定（簡素化）
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        timeout=OPENAI_TIMEOUT,
        max_retries=OPENAI_MAX_RETRIES
    )

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
1. {EXPECTED_STATS_RESULT} の条件:
    - 指示手順を過不足なく実行
    - 不要/逸脱ステップなし
    - 初期設定ダイアログ対応や広告ダイアログ対応は不要/逸脱ステップに含めない
    - 応答内に期待基準へ直接対応する具体的根拠（要素ID / text / 画像説明 / 操作結果）が存在
    - 画像評価が必要なケースではその根拠を言及
2. {SKIPPED_STATS_RESULT} の条件:
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

        color = Fore.GREEN if status == EXPECTED_STATS_RESULT else Fore.RED
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
        return f"{SKIPPED_STATS_RESULT}\n判定理由: 評価中エラー ({err_type})"


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
    reasoning: Optional[str] = Field(default=None, description="このステップ列を選択した根拠の要約（100〜400文字程度）")


# --- 応答モデル ---
class Response(BaseModel):
    response: str


class Act(BaseModel):
    action: Union[Response, Plan] = Field(
        description="実行するアクション。ユーザーに応答する場合はResponse、さらにツールを使用してタスクを実行する場合はPlanを使用してください。"
    )

class DecisionResult(BaseModel):
    # pattern指定によるフォーマットエラー発生の可能性があるため、Literalで厳密化し安全側に変更
    decision: Literal["PLAN", "RESPONSE"] = Field(description="次に返すべきアクション種別 (PLAN|RESPONSE)")
    reason: str = Field(description="判断理由（1〜200文字程度）")

class EvaluationResult(BaseModel):
    """テスト結果評価の構造化出力モデル

    status: EXPECTED_STATS_RESULT (合格) か SKIPPED_STATS_RESULT (要目視確認)
    reason: 判定根拠（手順整合性 / 要素根拠 / 不足点 / 画像評価有無などを含める）
    """
    status: Literal["EXPECTED_STATS_RESULT", "SKIPPED_STATS_RESULT"] = Field(description="判定結果ステータス")
    reason: str = Field(description="詳細な判定理由（100〜600文字程度。根拠要素/手順対応/不足点/改善提案を含め可）")


# --- Multi-stage Replanner (for mini models) ---
class MultiStageReplanner:
    """3段階に分けてreplanを実行するクラス（miniモデル用）"""
    
    def __init__(self, llm, knowhow: str):
        self.llm = llm
        self.knowhow = knowhow
    
    async def analyze_state(
        self,
        goal: str,
        original_plan: list,
        past_steps: list,
        locator: str,
        previous_image_url: str = "",
        current_image_url: str = ""
    ) -> str:
        """ステージ1: 画像（前回/現在）とロケーターから現状を把握

        画像がある場合はLLMへマルチモーダルで渡し、差分言及を促す。
        """
        prompt_text = f"""
あなたは画面状態を分析するエキスパートです。

目標:
{goal}

元の計画ステップ数: {len(original_plan)}
完了済みステップ数: {len(past_steps)}
最後の完了ステップ: {past_steps[-1][0] if past_steps else "(なし)"}


指示:
目標が達成されているか否かを、画面のロケータ情報と、前回と現在の画面スクリーンショットを基に判断してください。
画像差分 / テスト進捗 / 問題兆候 / 主要要素 を分析した結果に加えて、目標が達成されているか否かを判断した理由をロケーター情報と共に詳細に示しなさい。

厳格ルール:
残り推定ステップ数が1以上であれば、それが省略可能に見えても必ず PLAN を返してください。Response を返してよいのは残り推定ステップ数が0 かつ STATE_SUMMARY から達成根拠（要素確認等）が明確な場合のみです。
なぜなら、省略可能に見えたとしても、そのステップを反映することがテストの正確性と安全性を高めるからです。
したがって、"省略" や "不要" といった語で未実行ステップを評価してはいけません。”省略可能”と判断した場合でも、必ずそのステップを実行しなければならない前提でPLANを返してください。

出力形式:
プレーンテキストで、判断に利用したオブジェクトとそのロケーター情報と共に以下のセクションを含むこと。
- 画面の変化と差分分析
- テスト進捗
- 次のステップをそのまま実行可能か否かをその理由と共に
- 問題兆候の有無
- 主要要素の確認状況
- 目標達成の可否
- 目標達成の可否の理由

現在のロケーター情報:
{locator}
"""

        content_blocks: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        if previous_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": previous_image_url}})
        if current_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": current_image_url}})

        # 画像が無い場合はテキストのみ
        res = await self.llm.ainvoke([HumanMessage(content=content_blocks)])
        return res.content.strip()
    
    async def decide_action(self, goal: str, original_plan: list, past_steps: list, state_summary: str) -> tuple:
        """ステージ2: Plan/Responseどちらを返すべきか判断（構造化出力）"""
        remaining_steps = max(len(original_plan) - len(past_steps), 0)

        prompt = f"""あなたは次のアクションを厳密に判断するエキスパートです。

【目標】
{goal}

【状態要約】
{state_summary}

【進捗】
計画ステップ総数: {len(original_plan)} / 完了: {len(past_steps)} / 残り: {remaining_steps}

【判断基準（厳格）】
1. 残りステップが１以上存在する : decision=PLAN （省略可能に見えても必ず PLAN）
2. 残りステップが存在せず目標が100%達成済みで追加行動が論理的に一切不要 : decision=RESPONSE
3. 画面/ロケーターに不整合・エラー兆候がある → decision=PLAN

【厳格ルール】
残り推定ステップ数が1以上であれば、それが省略可能に見えても必ず PLAN を返してください。Response を返してよいのは残り推定ステップ数が0 かつ STATE_SUMMARY から達成根拠（要素確認等）が明確な場合のみです。
なぜなら、省略可能に見えたとしても、そのステップを反映することがテストの正確性と安全性を高めるからです。
したがって、"省略" や "不要" といった語で未実行ステップを評価してはいけません。”省略可能”と判断した場合でも、必ずそのステップを実行しなければならない前提でPLANを返してください。

【出力仕様】
厳格なJSON
"""

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(DecisionResult)
        try:
            result = await structured_llm.ainvoke(messages)
            decision_norm = result.decision.strip().upper()
            if decision_norm not in ("PLAN", "RESPONSE"):
                decision_norm = "PLAN"  # 安全側フォールバック
            return decision_norm, result.reason.strip()
        except Exception as e:
            # 構造化出力失敗時は安全側でPLANを返す
            print(Fore.RED + f"decide_action構造化出力エラー: {e}")
            allure.attach(str(e), name="❌ decide_action 構造化出力エラー", attachment_type=allure.attachment_type.TEXT)
            return "PLAN", "構造化出力エラーのためフォールバック"
    
    async def build_plan(self, goal: str, original_plan: list, past_steps: list, state_summary: str) -> Plan:
        """ステージ3a: 次のPlanを作成"""
        remaining = original_plan[len(past_steps):]
        
        prompt = f"""
あなたは実行計画を作成するエキスパートです。

目標:
{goal}

現在の状態要約:
{state_summary}

完了済みステップ数: {len(past_steps)}

残りの候補ステップ:
{remaining}

ノウハウ:   
{self.knowhow}

タスク:
目標達成のために必要な最適なステップ列を作成してください。以下を必ず守ること：
- 現在フォアグラウンドで動作しているアプリIDがテストを実施するアプリであることを確認すること
- ステップを実行できる状態でない場合は、現在の状態を考慮して最適なステップを再構築してください
- 可能なら既存未完了ステップを再利用し重複を避けること
- ステップを選択した根拠（進捗・画面要素・残り目標）を簡潔に言語化すること
- そのステップの必要性をロケーター情報を含めて必ず明示すること
- 現在の状態を考慮すること
- 不要なステップは追加しない
- 各ステップは具体的で実行可能なこと
- 目標の手順を踏まえた、目標を達成するための全てのステップ列がふくまれていること

出力形式（JSON）:
厳密なJSON形式
"""
        
        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Plan)
        plan = await structured_llm.ainvoke(messages)
        return plan
    
    async def build_response(self, goal: str, past_steps: list, state_summary: str) -> Response:
        """ステージ3b: 完了Responseを作成"""
        prompt = f"""あなたはタスク完了報告を作成するエキスパートです。

【目標】
{goal}

【現在の状態要約】
{state_summary}

【完了済みステップ】
{len(past_steps)}個のステップを完了

【タスク】
タスクの完了を報告してください。以下を含めること：
1. 完了理由の詳細をロケーター情報や画面状態に基づいて説明
2. 目標が達成されていることの根拠をロケーター情報や画面状態に基づいて詳細に説明
3. 最後の行に必ず {EXPECTED_STATS_RESULT} を単独で記載

出力形式:
- テキストでタスク完了の理由と根拠を詳細に記述する
- 初期設定ダイアログ対応や広告ダイアログ対応は不要/逸脱ステップに含めないステップを行った場合は、そのステップの詳細をロケーター情報を含めて保持事項として説明する
- 最後の行に {EXPECTED_STATS_RESULT} を追記する
"""
        
        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Response)
        resp = await structured_llm.ainvoke(messages)
        return resp


# --- シンプルなプランナークラス ---
class SimplePlanner:
    """テスト用のシンプルなプランナー"""

    def __init__(self, pre_action_results: str = "", knowhow: str = KNOWHOW_INFO, multi_stage: bool = False, model_name: str = "gpt-4.1"):
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0,
            timeout=OPENAI_TIMEOUT,
            max_retries=OPENAI_MAX_RETRIES
        )
        self.pre_action_results = pre_action_results
        self.knowhow = knowhow  # ノウハウ情報を保持
        self.multi_stage = multi_stage  # Multi-stage モード
        self.model_name = model_name
        
        # Multi-stage用のreplanner初期化
        if multi_stage:
            self.replanner = MultiStageReplanner(self.llm, knowhow)
            print(Fore.CYAN + f"🔀 Multi-stage replan モード有効 (model: {model_name})")

    async def create_plan(
        self, user_input: str, locator: str = "", image_url: str = ""
    ) -> Plan:
        
        content = """与えられた目標に対して、シンプルかつ必要最小限のステップバイステップ計画を作成してください。
    この計画は、正しく実行されれば期待結果を得られる個別のタスクで構成される必要があります。
    不要・重複・曖昧・推測的なステップは入れないでください。最終ステップの結果が最終的な答えとなります。
    各ステップに必要十分な情報（対象要素/操作/条件）が含まれていることを確認し、省略や飛ばしを行わないでください。
    また、なぜそのステップ列が最適かを短く根拠説明してください。
    """
        
        # 制約・ルールは最後に配置（最も重要な情報として強調）
        content += f"\n\n{self.knowhow}"
        print(Fore.CYAN + f"\n\n\n\nSystem Message for create_plan:\n{content}\n")

        messages = [SystemMessage(content=content)]

        human_message_content = f"""
目標: 
{user_input}

指示: 
現時点のデバイスのスクリーンの状態を、次のロケータ情報とスクリーンショットの２つを突き合わせて解析し、目標達成のための計画を作成しなさい

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
        
        system_content = f"""あなたは計画の再評価と次のステップ決定を行うエキスパートです。
以下のノウハウに従ってタスクを遂行してください。

{self.knowhow}"""

        # --- Multi-stage モード分岐 ---
        if self.multi_stage:
            try:
                print(Fore.CYAN + "🔀 Multi-stage replan: ステージ1（状態分析）")
                state_summary = await self.replanner.analyze_state(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    locator=locator,
                    previous_image_url=previous_image_url,
                    current_image_url=image_url
                )
                print(Fore.CYAN + f"状態要約:\n{state_summary}")
                allure.attach(state_summary, name="🔍 状態分析結果", attachment_type=allure.attachment_type.TEXT)
                
                print(Fore.CYAN + "🔀 Multi-stage replan: ステージ2（アクション判定）")
                decision, reason = await self.replanner.decide_action(
                    goal=state["input"],
                    original_plan=state["plan"],
                    past_steps=state["past_steps"],
                    state_summary=state_summary
                )
                print(Fore.CYAN + f"判定結果: {decision}\n理由: {reason}")
                allure.attach(f"DECISION: {decision}\n{reason}", name="⚖️ アクション判定", attachment_type=allure.attachment_type.TEXT)
                
                print(Fore.CYAN + "🔀 Multi-stage replan: ステージ3（出力生成）")
                if decision == "RESPONSE":
                    response = await self.replanner.build_response(
                        goal=state["input"],
                        past_steps=state["past_steps"],
                        state_summary=state_summary
                    )
                    print(Fore.GREEN + f"✅ Response生成完了: {response.response[:100]}...")
                    return Act(action=response)
                else:
                    plan = await self.replanner.build_plan(
                        goal=state["input"],
                        original_plan=state["plan"],
                        past_steps=state["past_steps"],
                        state_summary=state_summary
                    )
                    print(Fore.YELLOW + f"📋 Plan生成完了: {len(plan.steps)}ステップ")
                    return Act(action=plan)
            
            except Exception as e:
                print(Fore.RED + f"⚠️ Multi-stage replan エラー: {e}")
                allure.attach(f"Multi-stage replan エラー: {e}", name="❌ Multi-stage エラー", attachment_type=allure.attachment_type.TEXT)
                # フォールバック: 残りのステップを返す
                remaining_steps = state["plan"][len(state["past_steps"]):]
                if remaining_steps:
                    fallback_plan = Plan(steps=remaining_steps)
                    print(Fore.YELLOW + f"🔄 フォールバック: 残り{len(remaining_steps)}ステップを返却")
                    return Act(action=fallback_plan)
                else:
                    fallback_response = Response(response=f"エラー発生のため処理を中断します: {e}\n\n{EXPECTED_STATS_RESULT}")
                    return Act(action=fallback_response)
        
        # --- 従来の単発モード ---
        user_content = f"""あなたの目標: {state["input"]}
元の計画: {str(state["plan"])}
現在完了したステップ: {str(state["past_steps"])}

重要な指示:
1. メインの目標が完全に達成されているかを必ず分析してください
2. メインの目標を完了するために残りのステップがある場合は、必ず残りのステップを含むPlanを返してください
3. 全体の目標が100%完了し、これ以上のアクションが不要な場合のみResponseを返してください
4. 次に必要なアクションが存在する場合は Response を返してはならない
5. 次に必要なアクションが存在する場合はは、それをPlanに含めてください
6. 前のステップでエラーが発生した場合は、それを考慮して代替アプローチを考えてください
7. レスポンスを返すときは必ずレスポンスを返した理由を詳細に述べてください。画像の変化やロケーター情報の変化を含めることが重要です

覚えておいてください: あなたの仕事は、現在の状態を観察するだけでなく、実行可能なステップを提供することです。"""

        if locator:
            # LLMには生のロケーター情報を渡す
            user_content += f"\n\n現在の画面ロケーター情報: {locator}"
            
            # ログとAllureには整形したロケーター情報を出力
            allure.attach(
                locator,
                name="📍 replan: ロケーター情報（整形済み）",
                attachment_type=allure.attachment_type.TEXT
            )

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content)
        ]

        if image_url and previous_image_url:
            # 前回と現在の画像両方がある場合
            messages.append(
                HumanMessage(
                    content=[
                        {"type": "image_url", "image_url": {"url": previous_image_url}},
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {
                            "type": "text",
                            "text": (
                                "上記の2つの画像を比較してください。1枚目が前回のアクション実行前の画面、2枚目が現在の画面です。\n\n"
                                "画面の変化を分析して以下を判断してください：\n"
                                "1. 前回のアクションが成功したか失敗したか\n"
                                "2. 期待された変化が起きているか\n"
                                "3. エラーやローディング状態になっていないか\n"
                                "4. 目標に向かって進捗があるか\n\n"
                                "【最優先指示】\n"
                                "画面変化の分析結果と現在のロケーター情報を踏まえて、目標を完了するための残りのステップを判断してください。\n\n"
                                "⚠️ 重要：残りのステップが1つでも存在する場合は「必ずPlan」を返してください。Responseを返してはいけません。\n"
                                "⚠️ 目標が100%完全に達成され、これ以上のアクションが一切不要な場合「のみ」Responseを返してください。\n\n"
                                "分析の結果「残りのステップ」について言及している場合は、それは「Plan」を返すべきサインです。"
                            ),
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
                            "text": (
                                "現在の画面状態（スクリーンショットとロケータの2つ）に基づいて、目標を完了するための残りのステップは何ですか？\n\n"
                                "【最優先指示】\n"
                                "⚠️ 重要：残りのステップが1つでも存在する場合は「必ずPlan」を返してください。Responseを返してはいけません。\n"
                                "⚠️ 目標が100%完全に達成され、これ以上のアクションが一切不要な場合「のみ」Responseを返してください。\n\n"
                                "分析の結果「残りのステップ」について言及している場合は、それは「Plan」を返すべきサインです。必ずロケーター情報も考慮してください。"
                            ),
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

        try:
            structured_llm = self.llm.with_structured_output(Act)
            act = await structured_llm.ainvoke(messages)
            return act
        except Exception as e:
            err_type = type(e).__name__
            print(Fore.RED + f"[replan] Exception: {err_type}: {e}")
            allure.attach(
                f"Exception Type: {err_type}\nLocation: SimplePlanner.replan\nMessage: {e}",
                name="❌ replan Exception",
                attachment_type=allure.attachment_type.TEXT
            )
            log_openai_error_to_allure(
                error_type=err_type,
                location="SimplePlanner.replan",
                model=self.llm.model_name,
                error=e
            )
            raise


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
    max_replan_count: int = 10,
    knowhow: str = KNOWHOW_INFO,
):
    """ワークフロー関数を作成する（セッション内のツールを使用）

    Args:
        max_replan_count: 最大リプラン回数（デフォルト5回）
        knowhow: ノウハウ情報（SimplePlannerに渡される）
    """

    # 画像キャッシュ（クロージャ内で管理）
    image_cache = {"previous_image_url": ""}

    # ステップ履歴キャッシュ（クロージャ内で管理）
    step_history = {"executed_steps": []}
    
    # ツール呼び出し履歴を記録するコールバックハンドラー
    tool_callback = AllureToolCallbackHandler()

    async def execute_step(state: PlanExecute):
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
                name="📍ロケーター情報",
                attachment_type=allure.attachment_type.TEXT
            )
            if image_url:
                allure.attach(
                    base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                    name="📷Current Screen",
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
                    name="Step",
                    attachment_type=allure.attachment_type.TEXT,
                )

                # ツール呼び出し履歴を Allure に保存
                tool_callback.save_to_allure(step_name=task)
                tool_callback.clear()

                allure.attach(
                    agent_response["messages"][-1].content,
                    name="Response",
                    attachment_type=allure.attachment_type.TEXT,
                )
                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f}秒",
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
                    f"{elapsed:.3f}秒",
                    name="Execute Step Time",
                    attachment_type=allure.attachment_type.TEXT,
                )
                
                allure.attach(
                    f"エラー詳細:\n{error_msg}\n\nステップ: {task}",
                    name="❌ Execute Step Error",
                    attachment_type=allure.attachment_type.TEXT,
                )

                # エラーも履歴に記録
                step_history["executed_steps"].append(
                    {
                        "step": task,
                        "response": f"エラー: {error_msg}",
                        "timestamp": time.time(),
                        "success": False,
                    }
                )

                # エラー発生時はassertで失敗させて次のテストへ
                assert False, f"ステップ実行中にエラーが発生しました: {error_msg}"

    async def plan_step(state: PlanExecute):
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
                        name="📍ロケーター情報",
                        attachment_type=allure.attachment_type.TEXT
                    )

                if image_url:
                    allure.attach(
                        base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                        name="📷Screenshot before Planning",
                        attachment_type=allure.attachment_type.JPG,
                    )

                plan = await planner.create_plan(state["input"], locator, image_url)
                print(Fore.GREEN + f"生成された計画: {plan}")

                allure.attach(
                    str(plan.steps),
                    name="🎯Plan",
                    attachment_type=allure.attachment_type.TEXT,
                )

                allure.attach(
                    plan.reasoning, 
                    name="🧠 Plan Reasoning", 
                    attachment_type=allure.attachment_type.TEXT
                )

                elapsed = time.time() - start_time
                allure.attach(
                    f"{elapsed:.3f}秒",
                    name=f"⏱️Plan Step Time : {elapsed:.3f}秒",
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
                    name=f"Plan Step Time : {elapsed:.3f}秒",
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
                    f"{elapsed:.3f}秒",
                    name="🧠 Replan Step Time",
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

                if locator:
                    # ログとAllureには整形したロケーター情報を出力
                    allure.attach(
                        locator,
                        name="📍ロケーター情報",
                        attachment_type=allure.attachment_type.TEXT
                    )

                # 前回画像がある場合は比較用として添付
                if previous_image_url:
                    allure.attach(
                        base64.b64decode(
                            previous_image_url.replace("data:image/jpeg;base64,", "")
                        ),
                        name="📷Previous Screenshot (Before Action)",
                        attachment_type=allure.attachment_type.JPG,
                    )

                # 現在画像を添付
                allure.attach(
                    base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
                    name="📷Current Screenshot (After Action)",
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
                            step_history["executed_steps"],
                        )

                    allure.attach(
                        evaluated_response,
                        name="Final Evalution",
                        attachment_type=allure.attachment_type.TEXT,
                    )

                    elapsed = time.time() - start_time
                    allure.attach(
                        f"{elapsed:.3f}秒",
                        name="⏱️Replan Step Time",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    return {
                        "response": evaluated_response,
                        "replan_count": current_replan_count + 1,
                    }
                else:
                    allure.attach(
                        str(output.action.steps),
                        name="🧠 Replan Steps",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    elapsed = time.time() - start_time
                    allure.attach(
                        f"{elapsed:.3f}秒",
                        name="⏱️Replan Step Time",
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
                    name="⏱️Replan Step Time",
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



async def write_device_info_once(driver=None):
    """デバイス情報をAllure環境ファイルに書き込む（1回だけ実行）"""    
    env_file_path = "allure-results/environment.properties"
    info = {}

    # ファイルが既に存在する場合はスキップ
    if os.path.exists(env_file_path):
        return

    try:
        # capabilities.json から基本情報を取得
        with open(capabilities_path, "r") as f:
            info = json.load(f)  
    except Exception as e:
        print(f"警告: デバイス情報の取得に失敗しました: {e}")

    # デバイス詳細を driver から取得
    tools_list = appium_tools()
    tools_dict = {tool.name: tool for tool in tools_list}
    get_device_info = tools_dict.get("get_device_info")
    
    if get_device_info:
        info_result = await get_device_info.ainvoke({})
        # info_result が文字列の場合はパースする
        if isinstance(info_result, str):
            for line in info_result.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip()] = value.strip()
        elif isinstance(info_result, dict):
            info = info_result
    
    # 環境ファイルに書き込み
    os.makedirs("allure-results", exist_ok=True)
    with open(env_file_path, "w") as f:
        for key, value in info.items():
            if value:
                # キーに空白やコロンが含まれる場合はアンダースコアに置換
                safe_key = key.replace(' ', '_').replace(':', '_')
                f.write(f"{safe_key}={value}\n")



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
            await write_device_info_once(driver)

            # ツールを取得
            pre_action_results = ""

            # 必要なツールを取得（リストから名前で検索）
            tools_list = appium_tools()
            tools_dict = {tool.name: tool for tool in tools_list}
            screenshot_tool = tools_dict.get("take_screenshot")
            generate_locators = tools_dict.get("get_page_source")
            activate_app = tools_dict.get("activate_app")
            terminate_app = tools_dict.get("terminate_app")
            get_current_app = tools_dict.get("get_current_app")

            # noReset=True の場合、appPackageで指定されたアプリを強制起動
            if no_reset:
                app_package = capabilities.get("appium:appPackage")
                if app_package:
                    print(Fore.CYAN + f"noReset=True: アプリを強制起動します (appPackage={app_package})")
                    try:
                        activate_result = await activate_app.ainvoke({"app_id": app_package})
                        print(f"appium_activate_app結果: {activate_result}")
                        pre_action_results += f"appium_activate_app ツールを呼び出しました: {activate_result}\n"
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

            get_current_app_result = await get_current_app.ainvoke({})
            pre_action_results += f"現在のアクティブアプリ: {get_current_app_result}\n"
            print(Fore.GREEN + f"pre_action_results: {pre_action_results}")

            # 環境変数でmulti-stageモード判定
            use_mini_model = os.environ.get("USE_MINI_MODEL", "0") == "1"
            if use_mini_model:
                model = "gpt-4.1-mini"
            else:
                model = "gpt-4.1"
            
            print(Fore.CYAN + f"使用モデル: {model}")

            # エージェントエグゼキューターを作成（カスタムknowhowを使用）
            llm = ChatOpenAI(
                model=model,
                temperature=0,
                timeout=OPENAI_TIMEOUT,
                max_retries=OPENAI_MAX_RETRIES
            )
            prompt = f"""あなたは親切なAndroidアプリを自動操作するアシスタントです。与えられたタスクを正確に実行してください。\n{knowhow}\n"""

            agent_executor = create_agent(llm, appium_tools(), system_prompt=prompt)


            
            if use_mini_model:
                print(Fore.CYAN + "🔀 Multi-stage replan モードで起動（gpt-4.1-mini使用）")
                planner = SimplePlanner(
                    pre_action_results, 
                    knowhow, 
                    multi_stage=True, 
                    model_name="gpt-4.1-mini"
                )
            else:
                print(Fore.CYAN + "📝 通常replanモードで起動（gpt-4.1使用）")
                planner = SimplePlanner(
                    pre_action_results, 
                    knowhow, 
                    multi_stage=True, 
                    model_name="gpt-4.1"
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
        task: str,
        expected_substring: Optional[str] = None,
        ignore_case: bool = False,
        knowhow: Optional[str] = None,
    ) -> str:
        """
        タスクを実行して結果を検証する
        
        Args:
            task: 実行するタスク
            expected_substring: 期待される部分文字列
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
