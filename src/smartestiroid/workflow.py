"""ワークフローロジックモジュール

Plan-Executeパターンのワークフロー関数を提供します。
"""

import base64
from enum import Enum
import allure
from langchain_core.messages import HumanMessage
from langgraph.graph import END

from .models import PlanExecute, Response, Plan
from .progress import ExecutionProgress, ObjectiveProgress, ExecutedAction
from .config import KNOWHOW_INFO, RESULT_PASS, RESULT_FAIL
# モデル変数（planner_model等）は pytest_configure で動的に変更されるため、
# 直接インポートせず cfg.planner_model のように参照する（config.py のコメント参照）
from . import config as cfg
from .utils import AllureToolCallbackHandler
from .utils.structured_logger import SLog, LogCategory, LogEvent


class FailureType(Enum):
    """テスト失敗の種類を定義するEnum
    
    今後の拡張に備えて、失敗タイプを厳密に管理する。
    新しい失敗タイプを追加する場合は、このEnumに追加すること。
    """
    TEST_FAILURE = "test_failure"          # 通常のテスト失敗（目標未達成、アプリ不具合検出など）
    REPLAN_LIMIT = "replan_limit"          # リプラン回数制限到達
    # 将来の拡張用:
    # TIMEOUT = "timeout"                  # タイムアウト
    # ELEMENT_NOT_FOUND = "element_not_found"  # 要素が見つからない
    # APP_CRASH = "app_crash"              # アプリクラッシュ


async def analyze_test_failure(
    state: PlanExecute,
    step_history: list,
    replan_count: int,
    failure_type: FailureType = FailureType.TEST_FAILURE,
) -> str:
    """テスト失敗時に原因分析を行う
    
    FailureReportGeneratorと同じ方式で、FailedTestInfoを構築し、
    同一のプロンプト形式でLLM分析を行う。
    
    Args:
        state: 現在のワークフロー状態
        step_history: 実行されたステップの履歴
        replan_count: 実行されたリプラン回数
        failure_type: 失敗の種類（FailureType Enum）
        
    Returns:
        plaintext形式の原因分析結果
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from .config import OPENAI_TIMEOUT, OPENAI_MAX_RETRIES
    from .utils.failure_report_generator import FailureAnalysis, FailedTestInfo
    
    # step_historyからFailedTestInfoを構築（FailureReportGeneratorと同じ構造）
    test_info = FailedTestInfo(
        test_id=state.get("test_id", "UNKNOWN"),
        title=state.get("input", "")[:100] if state.get("input") else "",
        steps=state.get("input", ""),
        expected=state.get("expected", "テストが成功すること"),
    )
    
    # 完了ステップと失敗ステップを抽出
    for step_info in step_history:
        if step_info.get("success", False):
            test_info.completed_steps.append(step_info.get("step", ""))
        else:
            # 最後の失敗ステップを記録
            test_info.failed_step = step_info.get("step", "")
            test_info.error_message = step_info.get("response", "")
            
            # 評価結果からエラー情報を抽出
            evaluation = step_info.get("evaluation", {})
            if evaluation:
                executor_reason = evaluation.get("executor_reason", "")
                if "not found" in executor_reason.lower():
                    test_info.error_type = "NoSuchElementError"
                elif "timeout" in executor_reason.lower():
                    test_info.error_type = "TimeoutError"
                else:
                    test_info.error_type = "UnknownError"
                
                # Phase1/Phase2の検証結果を保存
                test_info.verification_phase1 = {
                    "success": evaluation.get("executor_success"),
                    "reason": evaluation.get("executor_reason", "")
                }
                if evaluation.get("verified") is not None:
                    test_info.verification_phase2 = {
                        "verified": evaluation.get("verified"),
                        "confidence": evaluation.get("verification_confidence"),
                        "reason": evaluation.get("executor_reason", ""),
                    }
    
    # 分析用のLLMを初期化
    analysis_llm = ChatOpenAI(
        model=cfg.evaluation_model,
        timeout=OPENAI_TIMEOUT,
        max_retries=OPENAI_MAX_RETRIES,
        temperature=0,
    )
    
    # FailureReportGeneratorと同じプロンプト形式を使用
    prompt = _build_analysis_prompt(test_info)
    
    # LLMプロンプトをログ出力
    SLog.log(LogCategory.LLM, LogEvent.START, {
        "method": "analyze_test_failure",
        "model": cfg.evaluation_model,
        "prompt": prompt[:1000]
    }, "LLMプロンプト送信: analyze_test_failure", attach_to_allure=True)

    try:
        # Structured Outputを使用
        structured_llm = analysis_llm.with_structured_output(FailureAnalysis)
        result: FailureAnalysis = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        
        # plaintext形式で出力
        plaintext_result = result.to_plaintext()
        
        # LLMレスポンスをログ出力
        SLog.log(LogCategory.ANALYZE, LogEvent.COMPLETE, {
            "failure_category": result.failure_category,
            "summary": result.summary,
            "confidence": result.confidence
        }, "原因分析完了")
        SLog.attach_text(f"## 🔍 原因分析結果\n\n{plaintext_result}", "💡 LLM Response: Failure Analysis")
        
        return plaintext_result
    except Exception as e:
        SLog.error(LogCategory.ANALYZE, LogEvent.FAIL, {"error": str(e)}, "原因分析エラー")
        return f"原因分析中にエラーが発生しました: {str(e)}"


def _build_analysis_prompt(test_info) -> str:
    """分析用プロンプトを構築（FailureReportGeneratorと同一形式）"""
    prompt = f"""あなたはモバイルアプリテスト自動化の専門家です。
以下のテスト失敗を分析し、構造化された分析結果を出力してください。

## テスト情報
- **テストID**: {test_info.test_id}
- **テスト名**: {test_info.title}
- **テスト手順**:
{test_info.steps}
- **期待結果**: {test_info.expected}

## 進捗状況
- 完了ステップ: {len(test_info.completed_steps)}
- 失敗したステップ: {test_info.failed_step or "不明"}
"""
    
    if test_info.progress_summary:
        prompt += f"\n### 進捗サマリー\n{test_info.progress_summary}\n"
    
    if test_info.last_screen_type:
        prompt += f"\n## 直前の画面状態\n- 画面タイプ: {test_info.last_screen_type}\n"
    
    error_msg = test_info.error_message[:500] if test_info.error_message else "不明"
    prompt += f"""
## エラー情報
- **エラータイプ**: {test_info.error_type or "不明"}
- **エラー内容**: {error_msg}
"""
    
    if test_info.verification_phase1:
        prompt += f"""
## LLM検証結果（Phase 1）
- success: {test_info.verification_phase1.get("success")}
- reason: {str(test_info.verification_phase1.get("reason", ""))[:300]}
"""
    
    if test_info.verification_phase2:
        prompt += f"""
## LLM検証結果（Phase 2）
- verified: {test_info.verification_phase2.get("verified")}
- confidence: {test_info.verification_phase2.get("confidence")}
- reason: {str(test_info.verification_phase2.get("reason", ""))[:300]}
- discrepancy: {test_info.verification_phase2.get("discrepancy")}
"""
    
    prompt += """
## 分析の観点
1. **failure_category**: 最も該当するカテゴリを1つ選択
   - APPIUM_CONNECTION_ERROR: Appiumサーバーとの接続問題
   - ELEMENT_NOT_FOUND: 画面要素が見つからない
   - VERIFICATION_FAILED: LLMによる画面検証が失敗
   - TIMEOUT: 操作のタイムアウト
   - LLM_JUDGMENT_ERROR: LLMの判断ミス
   - APP_CRASH: アプリのクラッシュ
   - SESSION_ERROR: Appiumセッションの問題
   - UNKNOWN: 上記に該当しない

2. **summary**: 何が起きたかを1文で（技術用語を使わず簡潔に）

3. **root_causes**: 技術的な原因（1-3個、箇条書き用）

4. **recommendations**: 具体的な対処法（優先度順、1-3個、実行可能なアクション）

5. **confidence**: 分析の確信度
   - HIGH: ログから原因が明確に特定できる
   - MEDIUM: 原因は推定できるが確定ではない
   - LOW: 情報が不足しており推測の要素が大きい

## 重要
- 推測は避け、ログから読み取れる事実に基づくこと
- リコメンデーションは実行可能な具体的アクションにすること
"""
    return prompt


async def evaluate_step_execution(
    llm,
    step_description: str,
    agent_response: str,
    tool_calls_summary: str,
    token_callback=None
):
    """ステップ実行結果をLLMで評価する（Phase 1: Executor自己評価）
    
    Args:
        llm: 評価に使用するLLM
        step_description: 実行しようとしたステップの説明
        agent_response: エージェントの応答内容
        tool_calls_summary: 実行されたツール呼び出しの要約
        token_callback: トークンカウンターコールバック
    
    Returns:
        StepExecutionResult: 構造化された実行結果
    """
    from .models import StepExecutionResult
    
    prompt = f"""あなたはステップ実行結果を評価するエキスパートです。

【実行しようとしたステップ】
{step_description}

【エージェントの応答】
{agent_response}

【実行されたツール呼び出し】
{tool_calls_summary}

【評価基準】
以下の基準で success を判断してください：

success = True の条件:
- 意図したツールが正常に呼び出された
- ツールの実行結果がエラーを含まない
- 画面操作が完了した（タップ、入力など）
- find系ツールで要素が見つかった

success = False の条件:
- 要素が見つからなかった（element not found, no element found など）
- ツールの実行がエラーで失敗した
- タイムアウトが発生した
- 操作対象が特定できなかった
- ツールが呼び出されなかった（確認ステップを除く）

【出力フィールドの説明】
- success: 上記基準で判断
- reason: 成功/失敗の具体的な理由
- executed_action: 実際に実行した操作（例：'resource-id xxx をタップした'）
- expected_screen_change: ★重要★ あなたは実行後の画面を確認できません。
  操作後に**期待される**画面変化を記述してください。
  例：'ホーム画面に遷移する'、'ダイアログが表示される'、'テキストが入力される'
- no_page_source_change: page_sourceに影響を与えないツールのみを実行した場合は True。
  例：find_element, verify_screen_content, get_page_source, screenshot 等の確認・取得系ツール。
  これらのツールは画面状態を変更しないため、検証LLMはこのフラグを参照して判断を調整します。

【出力形式】
厳格なJSON形式
"""
    
    # LLMプロンプトをログ出力
    SLog.log(LogCategory.LLM, LogEvent.START, {
        "method": "evaluate_step_execution",
        "prompt": prompt
    }, "LLMプロンプト送信: evaluate_step_execution", attach_to_allure=True)
    
    structured_llm = llm.with_structured_output(StepExecutionResult)
    
    if token_callback:
        with token_callback.track_query():
            result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
    else:
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)])
    
    # LLMレスポンスをログ出力
    SLog.log(LogCategory.ANALYZE, LogEvent.COMPLETE, {
        "success": result.success,
        "reason": result.reason,
        "executed_action": result.executed_action,
        "expected_screen_change": result.expected_screen_change,
        "no_page_source_change": result.no_page_source_change
    }, f"Executor評価完了: success={result.success}")
    SLog.attach_text(result.to_allure_text(), "💡 LLM Response: Step Execution")
    
    return result


async def verify_step_execution(
    llm,
    step_description: str,
    execution_result,
    page_source_after: str,
    screenshot_url_before: str = "",
    screenshot_url_after: str = "",
    token_callback=None
):
    """ステップ実行結果を検証LLMで検証する（Phase 2: 独立検証）
    
    Args:
        llm: 検証に使用するLLM
        step_description: 実行しようとしたステップの説明
        execution_result: Phase 1の実行結果（StepExecutionResult）
        page_source_after: 実行後のpage_source
        screenshot_url_before: 実行前のスクリーンショットURL
        screenshot_url_after: 実行後のスクリーンショットURL
        token_callback: トークンカウンターコールバック
    
    Returns:
        StepVerificationResult: 検証結果
    """
    from .models import StepVerificationResult
    
    # page_sourceに影響がないツールのみの場合は検証方針が異なる
    no_page_source_change = getattr(execution_result, 'no_page_source_change', False)
    expected_change = getattr(execution_result, 'expected_screen_change', None) or "不明"
    
    if no_page_source_change:
        no_change_note = """\n★重要★ page_sourceに影響がないツールの実行について:
Executorは find_element, verify_screen_content, get_page_source, screenshot 等の
確認・取得系ツールのみを実行しました。
この場合、画面変化は発生しません。Executorの成功/失敗判定（要素が見つかったかどうか）を
そのまま信頼してください。page_source で該当要素の存在を確認するだけで十分です。
"""
    else:
        no_change_note = ""
    
    prompt = f"""あなたはステップ実行結果を**独立して検証する**エキスパートです。

【検証対象ステップ】
{step_description}

【Executorの自己評価】
- 成功判定: {"成功" if execution_result.success else "失敗"}
- 判断理由: {execution_result.reason}
- 実行した操作: {execution_result.executed_action}
- 期待される画面変化: {expected_change}
- page_sourceに影響なし: {"はい" if no_page_source_change else "いいえ"}
{no_change_note}

【検証タスク】
Executorの自己評価が正しいかを、実行後の画面状態と突き合わせて検証してください。

★重要★ 以下の観点で検証:
1. ステップの意図した操作が実際に完了しているか
2. page_source の内容がステップ実行後の期待状態と一致するか
3. Executorの「成功」判定に矛盾がないか

例:
- 「ホームタブをタップする」→ page_source で該当タブが selected="true" か確認
- 「検索ボックスに入力する」→ page_source で入力テキストが反映されているか確認
- 「ボタンをタップする」→ 画面遷移またはダイアログ表示があるか確認
- 「要素を確認する」（find系）→ page_source に該当要素が存在するか確認

★矛盾の例★:
- Executorが「成功」と言っているが、page_source に該当要素がない
- 「タップした」と言っているが、期待した画面変化がない
- 「入力した」と言っているが、テキストが反映されていない

★重要★ 矛盾と判断しないケース:
- ダイアログを閉じた後、**別のダイアログ**が表示された場合
  → resource-id が異なる同意ボタンが存在する = 成功（画面遷移した証拠）
  → 例: terms_agree をタップ後、btn_disclaimer_agree が表示される = 成功
- 操作対象のresource-idが消え、**別のresource-id**の類似要素が表示された場合
  → 画面遷移の証拠として「成功」と判断する
- 複数段階のダイアログフロー（利用規約→免責事項→メイン画面）は正常な動作

【判断のポイント】
- 操作対象の**正確なresource-id**がpage_sourceに残っているかを確認
- 同じテキスト「同意する」でもresource-idが異なれば**別の要素**
- 画面遷移があれば成功、なければ失敗

【画像比較について】
2枚の画像（実行前・実行後）が添付されています。
- 1枚目: 実行前のスクリーンショット
- 2枚目: 実行後のスクリーンショット
視覚的な変化も確認し、page_sourceの情報と合わせて検証してください。

【出力形式】
厳格なJSON形式

【実行後の画面状態（page_source）】
{page_source_after}
"""

    content_blocks = [{"type": "text", "text": prompt}]
    # 実行前のスクリーンショットを追加（1枚目）
    if screenshot_url_before:
        content_blocks.append({"type": "image_url", "image_url": {"url": screenshot_url_before}})
    # 実行後のスクリーンショットを追加（2枚目）
    if screenshot_url_after:
        content_blocks.append({"type": "image_url", "image_url": {"url": screenshot_url_after}})
    
    # LLMプロンプトをログ出力
    SLog.log(LogCategory.LLM, LogEvent.START, {
        "method": "verify_step_execution",
        "prompt": prompt,
        "has_image_before": bool(screenshot_url_before),
        "has_image_after": bool(screenshot_url_after)
    }, "LLMプロンプト送信: verify_step_execution", attach_to_allure=True)
    
    structured_llm = llm.with_structured_output(StepVerificationResult)
    
    if token_callback:
        with token_callback.track_query():
            result = await structured_llm.ainvoke([HumanMessage(content=content_blocks)])
    else:
        result = await structured_llm.ainvoke([HumanMessage(content=content_blocks)])
    
    # LLMレスポンスをログ出力
    SLog.log(LogCategory.ANALYZE, LogEvent.COMPLETE, {
        "verified": result.verified,
        "confidence": result.confidence,
        "reason": result.reason,
        "discrepancy": result.discrepancy
    }, f"検証完了: verified={result.verified}, confidence={result.confidence}")
    SLog.attach_text(result.to_allure_text(), "💡 LLM Response: Step Verification")
    
    return result


def create_workflow_functions(
    planner,
    agent_executor,
    screenshot_tool,
    get_page_source_tool,
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
        get_page_source_tool: ページソース取得ツール
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
                return {"past_steps": [("[SYSTEM_SKIP]", "計画ステップなし - リプランが必要")]}
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
            image_url = await screenshot_tool.ainvoke({"as_data_url": True})
            ui_elements = await get_page_source_tool.ainvoke({})
            
            # ログにスクリーンショットを添付
            if image_url:
                SLog.attach_screenshot(image_url, label="Current Screen")
            
            # タスクにロケーター情報と画像相互補完の指示を含める（LLMには生データを渡す）
            # 進捗情報を計算
            total_steps = len(plan)
            step_number = current_step_index + 1  # 1-indexed for display
            remaining_steps = total_steps - step_number
            
            # 目標ステップのコンテキストを取得（Executorが正しい要素を特定できるようにする）
            objective_context = ""
            if objective_progress_cache["progress"] is not None:
                current_obj = objective_progress_cache["progress"].get_current_step()
                if current_obj:
                    objective_context = f"""\n【現在の目標ステップ（重要なコンテキスト）】
{current_obj.description}
※ 上記の目標を達成するために、以下の実行ステップを行います。目標の文脈を考慮して正しい要素を特定してください。
"""
            
            task_formatted = f"""【あなたの担当】

- あなたはAndroidアプリをツールを使って自動操作するエージェントです
{objective_context}
次のタスクを実行してください:
ステップ{step_number}/{total_steps}: {task}

【厳格ルール】
- ツールを用いて、上記のステップ「{task}」のみを実行しなさい

【ツール使用時の厳格ルール】
以下の操作は、明示的な指示がない限り専用ツールを優先的に使用すること:
- アプリを起動する → activate_app(app_id) を使用
- アプリを終了する → terminate_app(app_id) を使用
- アプリを再起動する → restart_app(app_id) を使用（terminate→待機→activateを自動実行）
- 現在のアプリを確認する → get_current_app() を使用

【確認ステップの優先ツール】
「〇〇を確認する」「〇〇が表示されていることを確認する」などの確認ステップには、以下のツールを優先的に使用:
- verify_screen_content(target) を使用（XMLとスクリーンショットをLLMで分析）
- 例: 「利用規約ダイアログを確認する」→ verify_screen_content("利用規約ダイアログ")
- 例: 「エラーメッセージが表示されていることを確認する」→ verify_screen_content("エラーメッセージ")

【画面情報の活用方法】
- 画像とロケーター情報の情報を突き合わせて画面オブジェクトの位置情報を正確に分析しなさい
- 操作対象の要素を特定してツールを使用すること
- 複数の要素が類似している場合は、目標ステップの指示と bounds や resource-id や content-desc や class 名を参考に正確に特定すること

画面ロケーター情報:
{ui_elements}"""
            
            try:
                # LLMプロンプトをログ出力
                SLog.log(LogCategory.LLM, LogEvent.START, {
                    "method": "agent_executor",
                    "model": cfg.execution_model,
                    "prompt": task_formatted,
                }, "LLMプロンプト送信: agent_executor", attach_to_allure=True)
                
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
                
                # LLMレスポンスをログ出力
                response_content = agent_response['messages'][-1].content
                SLog.log(LogCategory.LLM, LogEvent.COMPLETE, {
                    "response": response_content[:500]
                }, "エージェント応答完了")
                SLog.attach_text(f"## 🤖 Agent Response\n\n{response_content}", "💡 LLM Response: Agent Executor")
                
                # ツール実行完了後、画面反映を待つ
                # 3秒は経験則値、必要に応じて調整可能
                import asyncio
                await asyncio.sleep(3)

                SLog.debug(LogCategory.STEP, LogEvent.RESPONSE, {"step": task, "response": response_content[:500]}, None)

                # ツール呼び出し履歴を Allure に保存
                tool_callback.save_to_allure(step_name=task)
                
                # === Phase 1: Executor自己評価 ===
                SLog.info(LogCategory.LLM, LogEvent.VERIFY_REQUEST, {"phase": 1, "step": task}, "Phase 1: ステップ実行結果を評価中...")
                tool_calls_summary = tool_callback.get_summary() if hasattr(tool_callback, 'get_summary') else "N/A"
                
                evaluation_result = await evaluate_step_execution(
                    llm=planner.llm,  # Plannerと同じLLMを使用
                    step_description=task,
                    agent_response=agent_response["messages"][-1].content,
                    tool_calls_summary=tool_calls_summary,
                    token_callback=token_callback
                )
                
                SLog.info(LogCategory.LLM, LogEvent.VERIFY_RESPONSE, {
                    "phase": 1,
                    "success": evaluation_result.success,
                    "reason": evaluation_result.reason,
                    "executed_action": evaluation_result.executed_action,
                    "expected_screen_change": evaluation_result.expected_screen_change,
                    "no_page_source_change": evaluation_result.no_page_source_change
                }, f"Executor評価: success={evaluation_result.success}")
                
                # === Phase 2: 独立検証（Executor評価がTrueの場合のみ） ===
                step_success = False
                verification_result = None
                
                if evaluation_result.success:
                    SLog.info(LogCategory.LLM, LogEvent.VERIFY_REQUEST, {"phase": 2, "step": task}, "Phase 2: 検証LLMによる独立検証中...")
                    
                    # 実行後の画面状態を取得
                    page_source_after = await get_page_source_tool.ainvoke({})
                    screenshot_after = await screenshot_tool.ainvoke({"as_data_url": True})
                    
                    verification_result = await verify_step_execution(
                        llm=planner.llm,  # 検証にも同じLLMを使用（別モデルにする場合は要変更）
                        step_description=task,
                        execution_result=evaluation_result,
                        page_source_after=page_source_after,
                        screenshot_url_before=image_url,  # 実行前のスクリーンショット
                        screenshot_url_after=screenshot_after,
                        token_callback=token_callback
                    )
                    
                    SLog.info(LogCategory.LLM, LogEvent.VERIFY_RESPONSE, {
                        "phase": 2,
                        "verified": verification_result.verified,
                        "confidence": verification_result.confidence,
                        "reason": verification_result.reason,
                        "discrepancy": verification_result.discrepancy
                    }, f"検証結果: verified={verification_result.verified}, confidence={verification_result.confidence:.2f}")
                    
                    # 両方がTrueで確信度が0.7以上の場合のみ成功とする
                    step_success = verification_result.verified and verification_result.confidence >= 0.7
                    
                    if not step_success:
                        SLog.warn(LogCategory.LLM, LogEvent.VERIFY_RESPONSE, {"verified": verification_result.verified, "confidence": verification_result.confidence, "discrepancy": verification_result.discrepancy}, f"検証失敗: verified={verification_result.verified}, confidence={verification_result.confidence:.2f}")
                else:
                    SLog.warn(LogCategory.LLM, LogEvent.SKIP, {"reason": "executor_evaluation_failed"}, "Executor評価が失敗のため、検証をスキップ")
                    step_success = False
                
                # ステップ完了を記録（評価結果に基づく）
                tool_callback.complete_step(
                    agent_response["messages"][-1].content,
                    success=step_success
                )
                tool_callback.clear()
                
                elapsed = time.time() - start_time
                SLog.attach_text(f"{elapsed:.3f} seconds", "⏱️Execute Step Time")
                
                if step_success:
                    SLog.info(LogCategory.STEP, LogEvent.COMPLETE, {"step": task, "success": True}, f"SUCCESS: ステップ '{task}'")
                else:
                    SLog.warn(LogCategory.STEP, LogEvent.FAIL, {"step": task, "success": False}, f"FAILED: ステップ '{task}'")

                # 実行されたステップを履歴に追加（評価結果に基づく）
                step_history["executed_steps"].append(
                    {
                        "step": task,
                        "response": agent_response["messages"][-1].content,
                        "timestamp": time.time(),
                        "success": step_success,
                        "evaluation": {
                            "executor_success": evaluation_result.success,
                            "executor_reason": evaluation_result.reason,
                            "verified": verification_result.verified if verification_result else None,
                            "verification_confidence": verification_result.confidence if verification_result else None,
                        }
                    }
                )
                
                # ObjectiveProgressの実行計画を1ステップ進める & アクション履歴を記録
                # ★ 成功した場合のみ進める ★
                if step_success and objective_progress_cache["progress"]:
                    current_obj_step = objective_progress_cache["progress"].get_current_step()
                    if current_obj_step:
                        # 実行済みアクションを記録
                        last_tool = None
                        if hasattr(tool_callback, 'get_last_tool_name'):
                            last_tool = tool_callback.get_last_tool_name()
                        current_obj_step.executed_actions.append(ExecutedAction(
                            action=task,
                            tool_name=last_tool or "unknown",
                            result=agent_response["messages"][-1].content[:500],
                            success=True
                        ))
                    
                    # ★ ダイアログ処理モード分岐 ★
                    if objective_progress_cache["progress"].is_handling_dialog():
                        # ダイアログ処理中 → execution_plan_indexは進めない
                        objective_progress_cache["progress"].increment_dialog_handling_count()
                        dialog_count = objective_progress_cache["progress"].get_dialog_handling_count()
                        SLog.info(LogCategory.STEP, LogEvent.COMPLETE, {"mode": "dialog", "dialog_count": dialog_count}, f"ダイアログ処理ステップ完了 (計{dialog_count}ステップ)")
                    else:
                        # 通常モード → execution_plan_indexを進める
                        objective_progress_cache["progress"].advance_current_execution_plan()
                        remaining = len(objective_progress_cache["progress"].get_current_remaining_plan())
                        SLog.info(LogCategory.STEP, LogEvent.COMPLETE, {"mode": "normal", "remaining": remaining}, f"通常ステップ完了 (残り: {remaining}ステップ)")
                elif not step_success:
                    # 失敗した場合もアクション履歴を記録（失敗として）
                    if objective_progress_cache["progress"]:
                        current_obj_step = objective_progress_cache["progress"].get_current_step()
                        if current_obj_step:
                            last_tool = None
                            if hasattr(tool_callback, 'get_last_tool_name'):
                                last_tool = tool_callback.get_last_tool_name()
                            current_obj_step.executed_actions.append(ExecutedAction(
                                action=task,
                                tool_name=last_tool or "unknown",
                                result=f"FAILED: {evaluation_result.reason}",
                                success=False
                            ))
                    SLog.warn(LogCategory.STEP, LogEvent.FAIL, {"step": task, "reason": evaluation_result.reason}, "ステップ失敗のため、計画を進めません。リプランが必要です。")

                return {
                    "past_steps": [(task, agent_response["messages"][-1].content)],
                    "step_success": step_success,  # ステップ成功フラグを追加
                    "evaluation_result": evaluation_result,  # 評価結果を追加
                    "verification_result": verification_result,  # 検証結果を追加
                }
            except Exception as e:
                error_msg = str(e)
                SLog.error(LogCategory.STEP, LogEvent.FAIL, {"step": task, "error": error_msg}, f"execute_stepでエラー: {e}")
                
                # ステップ失敗を記録
                tool_callback.complete_step(f"Error: {error_msg}", success=False)
                
                elapsed = time.time() - start_time
                SLog.attach_text(f"{elapsed:.3f} seconds", "Execute Step Time")
                SLog.attach_text(f"Detail:\n{error_msg}\n\nStep: {task}", "❌ Execute Step Error")

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
                image_url = await screenshot_tool.ainvoke({"as_data_url": True})
                ui_elements = await get_page_source_tool.ainvoke({})

                if image_url:
                    SLog.attach_screenshot(image_url, label="Screenshot before Planning")

                # Step 1: ユーザー入力から目標ステップを解析
                objective_progress = await planner.parse_objective_steps(state["input"])
                objective_progress_cache["progress"] = objective_progress
                
                # AllureLoggerにObjectiveProgressを設定
                tool_callback.set_objective_progress(objective_progress)
                
                # 目標ステップをAllureに出力（ログは parse_objective_steps 内で出力済み）
                objective_summary = objective_progress.get_progress_summary()
                SLog.debug(LogCategory.OBJECTIVE, LogEvent.UPDATE, {"summary": objective_summary}, None)
                SLog.attach_text(objective_summary, "📋 Objective Steps (User Goals)")

                # Step 2: 現在の目標ステップに基づいて実行計画を作成
                current_objective = objective_progress.get_current_step()
                current_objective.status = "in_progress"
                
                # 画面分析を実行
                screen_analysis = await planner.analyze_screen(ui_elements, image_url, current_objective.description)
                
                # ★ブロッキングダイアログチェック★
                # blocking_dialogsがある場合はダイアログ処理モードに入り、
                # 通常計画は生成せずにダイアログ処理のみを行う
                if screen_analysis.blocking_dialogs:
                    SLog.warn(LogCategory.SCREEN, LogEvent.INCONSISTENCY_DETECTED, {"blocking_dialogs": screen_analysis.blocking_dialogs}, f"ブロッキングダイアログ検出: {screen_analysis.blocking_dialogs}")
                    
                    # ダイアログ処理モードに入る
                    objective_progress.enter_dialog_handling_mode()
                    
                    # ダイアログ処理ステップのみを生成（通常計画は空のまま）
                    dialog_plan = await planner.replanner._generate_dialog_handling_steps(
                        planner.replanner._create_state_analysis_for_dialog(screen_analysis),
                        ui_elements
                    )
                    
                    # 空の通常計画を設定（ダイアログ解消後にreplanで生成される）
                    current_objective.execution_plan = []
                    
                    SLog.info(LogCategory.PLAN, LogEvent.START, {"mode": "dialog", "steps": len(dialog_plan)}, f"ダイアログ処理ステップ: {len(dialog_plan)}個")
                    for i, step in enumerate(dialog_plan):
                        SLog.debug(LogCategory.PLAN, LogEvent.UPDATE, {"index": i, "step": step}, None)
                    
                    # 初回画像をキャッシュに保存
                    image_cache["previous_image_url"] = image_url
                    
                    # ステップ履歴を初期化
                    step_history["executed_steps"] = []
                    
                    # 進捗追跡を初期化
                    execution_progress["progress"] = ExecutionProgress(original_plan=dialog_plan)
                    tool_callback.set_execution_progress(execution_progress["progress"])
                    
                    elapsed = time.time() - start_time
                    SLog.attach_text(
                        f"ブロッキングダイアログ検出: {screen_analysis.blocking_dialogs}\nダイアログ処理ステップ: {dialog_plan}",
                        "🔒 Dialog Handling Mode [Initial]"
                    )
                    SLog.attach_text(f"{elapsed:.3f} seconds", f"⏱️ Plan Step Time : {elapsed:.3f} seconds")
                    
                    return {
                        "plan": dialog_plan,
                        "replan_count": 0,
                    }
                
                # 現在の目標に対する実行計画を作成（全目標ステップを渡して境界を明確に）
                plan = await planner.create_execution_plan_for_objective(
                    current_objective, screen_analysis, ui_elements, image_url,
                    all_objective_steps=objective_progress.objective_steps
                )
                current_objective.execution_plan = plan.steps
                
                SLog.info(LogCategory.PLAN, LogEvent.COMPLETE, {"objective": current_objective.description[:50], "steps": len(plan.steps)}, f"目標「{current_objective.description[:50]}...」の実行計画: {len(plan.steps)}ステップ")
                SLog.debug(LogCategory.PLAN, LogEvent.UPDATE, {"plan": plan.steps}, None)

                elapsed = time.time() - start_time
                SLog.attach_text(f"{elapsed:.3f} seconds", f"⏱️ Plan Step Time : {elapsed:.3f} seconds")

                # 初回画像をキャッシュに保存
                image_cache["previous_image_url"] = image_url

                # ステップ履歴を初期化
                step_history["executed_steps"] = []
                
                # 進捗追跡を初期化（新しい計画で開始）
                execution_progress["progress"] = ExecutionProgress(original_plan=plan.steps)
                tool_callback.set_execution_progress(execution_progress["progress"])

                return {
                    "plan": plan.steps,
                    "replan_count": 0,  # 初期化時はreplan_countを0に設定
                }
            except Exception as e:
                SLog.error(LogCategory.PLAN, LogEvent.FAIL, {"error": str(e)}, f"plan_stepでエラー: {e}")
                elapsed = time.time() - start_time
                SLog.attach_text(f"{elapsed:.3f} seconds", f"Plan Step Time : {elapsed:.3f} seconds")
                # エラー時は例外を再スロー
                raise

    async def replan_step(state: PlanExecute):
        """実行結果を評価して計画を再調整する"""
        current_replan_count = state.get("replan_count", 0)
        
        # 進捗サマリーを取得
        progress_summary = ""
        if execution_progress["progress"]:
            progress_summary = execution_progress["progress"].get_progress_summary()
            SLog.info(LogCategory.PROGRESS, LogEvent.UPDATE, {"replan_count": current_replan_count}, "現在の進捗状況")
            SLog.debug(LogCategory.PROGRESS, LogEvent.UPDATE, {"summary": progress_summary}, None)
        
        # 目標進捗サマリーを取得
        objective_summary = ""
        if objective_progress_cache.get("progress"):
            objective_summary = objective_progress_cache["progress"].get_progress_summary()
            SLog.info(LogCategory.OBJECTIVE, LogEvent.UPDATE, {"replan_count": current_replan_count}, "目標ステップ進捗")
            SLog.debug(LogCategory.OBJECTIVE, LogEvent.UPDATE, {"summary": objective_summary}, None)
        
        # リプラン進捗ログを出力（replan_stepは 1 から順にカウント）
        # ⚠️ GUI通知用 - 変更禁止
        import json
        print(f"[REPLAN_PROGRESS] {json.dumps({'current_replan_count': current_replan_count + 1, 'max_replan_count': max_replan_count, 'status': 'replanning'})}")
        
        with allure.step(f"Action: Replan [Attempt #{current_replan_count+1}]"):
            import time

            # 目標進捗をAllureに添付
            if objective_summary:
                SLog.attach_text(objective_summary, "🎯 Objective Progress Before Replan")
                     
            # 進捗サマリーをAllureに添付
            if progress_summary:
                SLog.attach_text(progress_summary, "📊 Execution Progress Before Replan")

            start_time = time.time()
            # リプラン回数制限チェック
            if current_replan_count >= max_replan_count:
                SLog.log(
                    LogCategory.REPLAN,
                    LogEvent.END,
                    f"リプラン回数が制限に達しました（{max_replan_count}回）。処理を終了します。",
                )
                
                elapsed = time.time() - start_time
                
                # Allureにリプラン制限到達を記録
                SLog.attach_text(
                    f"リプラン回数が制限（{max_replan_count}回）に達しました。\n"
                    f"完了ステップ数: {len(state['past_steps'])}\n"
                    f"テストは失敗として終了します。",
                    "⚠️ リプラン回数制限到達"
                )
                SLog.attach_text(f"{elapsed:.3f} seconds", "🧠 Replan Step Time")
                
                # 結果メッセージを構築（LLM分析は呼び出さない）
                response_message = f"""## リプラン回数制限到達

リプラン回数が制限（{max_replan_count}回）に達したため、処理を終了しました。
現在の進捗: {len(state['past_steps'])}ステップ完了

{RESULT_FAIL}"""
                
                return {
                    "response": response_message,
                    "replan_count": current_replan_count + 1,
                }
            try:
                # 前回の画像URLをキャッシュから取得
                previous_image_url = image_cache["previous_image_url"]

                # 現在の画面情報を取得
                image_url = await screenshot_tool.ainvoke({"as_data_url": True})
                ui_elements = await get_page_source_tool.ainvoke({})

                # 前回画像がある場合は比較用として添付
                if previous_image_url:
                    SLog.attach_screenshot(previous_image_url, label="Previous Screenshot (Before Action)")

                # 現在画像を添付
                SLog.attach_screenshot(image_url, label="Current Screenshot (After Action)")

                # 前回画像と現在画像を使ってリプラン
                replan_result = await planner.replan(
                    state, ui_elements, image_url, previous_image_url,
                    objective_progress=objective_progress_cache.get("progress")
                )

                # 現在画像を次回用にキャッシュに保存
                image_cache["previous_image_url"] = image_url
                SLog.log(
                    LogCategory.REPLAN,
                    LogEvent.COMPLETE,
                    f"Replanner Output (replan #{current_replan_count + 1}): {replan_result}",
                )
                
                # 注: 目標ステップの完了処理は simple_planner.py の replan() 内で行われる
                # workflow.py では replan_result をそのまま使用する
                objective_progress = objective_progress_cache.get("progress")

                if isinstance(replan_result.action, Response):
                    evaluated_response = f"{replan_result.action.reason}\n\n{replan_result.action.status}"

                    # セーフガード: 目標未達成なのにPASSを返そうとしている場合は警告
                    if RESULT_PASS in replan_result.action.status:
                        if objective_progress and not objective_progress.is_all_objectives_completed():
                            remaining_count = objective_progress.get_total_objectives_count() - objective_progress.get_completed_objectives_count()
                            SLog.warn(LogCategory.OBJECTIVE, LogEvent.UPDATE, {"remaining": remaining_count, "total": objective_progress.get_total_objectives_count()}, f"警告: {remaining_count}個の目標が未達成ですがPASSが返されました")
                            SLog.attach_text(
                                f"警告: 目標ステップが{remaining_count}個未達成ですが、LLMがPASSを返しました。\n"
                                f"達成済み: {objective_progress.get_completed_objectives_count()}/{objective_progress.get_total_objectives_count()}",
                                "⚠️ 目標未達成警告"
                            )
                            # PASSをFAILに変更
                            evaluated_response = evaluated_response.replace(RESULT_PASS, RESULT_FAIL)
                            evaluated_response += f"\n\n【自動補正】目標ステップが未達成のためFAILに変更されました。"

                    # 合格判定した場合はその合格判定が正しいかを再評価する
                    # 人間の目視確認が必要な場合はSKIPにする
                    if RESULT_PASS in evaluated_response:
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

                    # PASSでない場合は原因分析を実行
                    if RESULT_PASS not in evaluated_response:
                        SLog.log(
                            LogCategory.ANALYZE,
                            LogEvent.START,
                            "テストがPASSしませんでした。原因分析を実行します...",
                        )
                        
                        # LLMによる原因分析を実行（通常のテスト失敗）
                        analysis_result = await analyze_test_failure(
                            state=state,
                            step_history=step_history["executed_steps"],
                            replan_count=current_replan_count + 1,
                            failure_type=FailureType.TEST_FAILURE,
                        )
                        
                        # 分析結果をログ出力
                        SLog.warn(LogCategory.TEST, LogEvent.FAIL, {"failure_type": "test_failure"}, "テスト失敗 - 原因分析結果")
                        SLog.debug(LogCategory.TEST, LogEvent.FAIL, {"analysis": analysis_result}, None)
                        
                        # Allureに分析結果を添付
                        SLog.attach_text(analysis_result, "🔍 テスト失敗 - 原因分析")
                        
                        # 分析結果を含めたレスポンスを構築
                        evaluated_response = f"""{evaluated_response}\n---\n{analysis_result}"""

                    elapsed = time.time() - start_time
                    SLog.attach_text(f"{elapsed:.3f} seconds", "⏱️ Replan Step Time")
                    return {
                        "response": evaluated_response,
                        "replan_count": current_replan_count + 1,
                    }
                else:
                    elapsed = time.time() - start_time
                    SLog.attach_text(f"{elapsed:.3f} seconds", "⏱️ Replan Step Time")
                    
                    # リプラン後の新しい計画で進捗を更新
                    # 注意: リプランは残りステップの再計画なので、完了済みステップは保持
                    new_plan = replan_result.action.steps
                    if execution_progress["progress"]:
                        # 完了済みステップ数を保持しつつ、新しい計画を設定
                        completed_count = execution_progress["progress"].get_completed_count()
                        # 新しい計画は「残りのステップ」なので、original_planは更新しない
                        # current_step_indexを調整
                        execution_progress["progress"].current_step_index = completed_count
                    
                    # ObjectiveProgressにも新しい実行計画を設定
                    # ★ ダイアログ処理中は実行計画を更新しない（元の計画を保護）★
                    if objective_progress_cache["progress"]:
                        if objective_progress_cache["progress"].is_handling_dialog():
                            # ダイアログ処理中 → execution_planは更新しない
                            dialog_count = objective_progress_cache["progress"].get_dialog_handling_count()
                            SLog.info(LogCategory.REPLAN, LogEvent.UPDATE, {"mode": "dialog", "dialog_steps": len(new_plan), "dialog_count": dialog_count}, f"ダイアログ処理モード: {len(new_plan)}個のステップを実行予定")
                        else:
                            # 通常モード → 実行計画を更新
                            objective_progress_cache["progress"].set_current_execution_plan(new_plan)
                            SLog.info(LogCategory.REPLAN, LogEvent.UPDATE, {"mode": "normal", "new_steps": len(new_plan)}, f"通常処理モード: 新しい実行計画 {len(new_plan)}ステップ")
                    
                    return {
                        "plan": new_plan,
                        "replan_count": current_replan_count + 1,
                    }
            except Exception as e:
                SLog.error(LogCategory.REPLAN, LogEvent.FAIL, {"error": str(e)}, f"Error in replan_step: {e}")
                elapsed = time.time() - start_time
                SLog.attach_text(f"{elapsed:.3f} seconds", "⏱️ Replan Step Time")
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