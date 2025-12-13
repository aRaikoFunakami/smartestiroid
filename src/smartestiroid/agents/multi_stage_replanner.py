"""
Multi-stage replanner for SmartestiRoid test framework.

This module provides a 3-stage replanning process for mini models.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
import allure

from ..models import Plan, Response, DecisionResult
from ..progress import ObjectiveStep, ObjectiveProgress
from ..config import RESULT_PASS, RESULT_FAIL
from ..utils.structured_logger import SLog, LogCategory, LogEvent
import smartestiroid.appium_tools as appium_tools


class ObjectiveEvaluation(BaseModel):
    """個別の目標ステップの達成評価"""
    step_index: int = Field(description="目標ステップのインデックス")
    description: str = Field(description="目標ステップの説明")
    achieved: bool = Field(description="達成されているかどうか")
    evidence: str = Field(description="達成/未達成の根拠")


class StateAnalysis(BaseModel):
    """リプラン時の画面状態分析結果
    
    整理済みフィールド（9個）:
    - 画面状態: screen_changes, current_screen_type, main_elements, blocking_dialogs
    - 画面整合性: screen_inconsistency（page_sourceと画像の不整合を検出）
    - 進捗評価: test_progress
    - 目標評価: current_objective_achieved, current_objective_evidence
    - 提案: suggested_next_action
    
    画面整合性チェックについて:
    - screen_inconsistency: page_sourceとスクリーンショット画像の不整合を検出した場合に設定
    - 不整合検出時は呼び出し元でウェイト後に再チェックする
    - 再チェックでも不整合なら pytest.fail でテスト失敗
    
    削除されたフィールド（導出可能または不要のため）:
    - goal_achieved → ObjectiveProgress.is_all_objectives_completed()で判断
    - goal_achievement_reason → current_objective_evidenceで十分
    - plan_still_valid → blocking_dialogs / current_objective_achieved から導出
    - plan_invalidation_reason → 不要
    """
    # 画面状態
    screen_changes: str = Field(description="前ステップからの画面変化と差分（UI要素の追加/削除/変更）")
    current_screen_type: str = Field(description="現在の画面の種類（例：ホーム画面、検索結果、設定画面など）")
    main_elements: str = Field(description="画面上の主要UI要素の説明")
    blocking_dialogs: Optional[str] = Field(default=None, description="目標達成を妨げるダイアログやオーバーレイがある場合、その内容と閉じるためのボタンのresource-id（例：'利用規約ダイアログ、閉じるボタン: com.example:id/agree_button'）")
    
    # 画面整合性（page_sourceと画像の不整合）
    screen_inconsistency: Optional[str] = Field(default=None, description="page_sourceとスクリーンショット画像の間に不整合がある場合、その詳細を記載。例: '画像は黒いがpage_sourceには要素がある', 'ローディングスピナーが表示されている'")
    
    # 進捗評価
    test_progress: str = Field(description="テスト進捗の評価（定量的または定性的）")
    
    # 目標ステップ単位の評価
    current_objective_achieved: bool = Field(description="現在の目標ステップが達成されているかどうか")
    current_objective_evidence: str = Field(description="現在の目標ステップの達成/未達成の根拠（ロケーター情報や画面状態に基づく）")
    
    # 残りステップの処理方針（残りステップがある場合のみ設定）
    remaining_steps_action: Optional[str] = Field(
        default=None,
        description="残りの実行ステップをどう処理すべきか: 'EXECUTE'(そのまま実行) / 'DISCARD'(破棄して確認操作) / 'REPLAN'(修正が必要)"
    )
    
    # 提案（任意）
    suggested_next_action: Optional[str] = Field(default=None, description="次に実行すべきアクションの提案（任意）")
    
    def has_screen_inconsistency(self) -> bool:
        """画面不整合があるかどうか（page_sourceと画像の不整合）"""
        return self.screen_inconsistency is not None and len(self.screen_inconsistency.strip()) > 0
    
    def is_plan_still_valid(self, remaining_steps: int) -> bool:
        """既存プランが有効かどうかを判定（blocking_dialogs/current_objective_achievedから導出）
        
        Args:
            remaining_steps: 残りステップ数
        
        Returns:
            True: プラン継続可能
            False: プラン再構築が必要
        """
        # ブロッキングダイアログがある → プラン無効（回避操作が必要）
        if self.blocking_dialogs:
            return False
        # 現在の目標ステップが達成された → プラン無効（次の目標用のプランが必要）
        if self.current_objective_achieved:
            return False
        # 残りステップがない → プラン無効
        if remaining_steps <= 0:
            return False
        # それ以外はプラン継続可能
        return True
    
    def to_log_dict(self, plan_still_valid: bool = None) -> dict:
        """ログ出力用の辞書を返す
        
        Args:
            plan_still_valid: プラン有効性（呼び出し元で計算した値を渡す）
        """
        return {
            # 画面状態
            "screen_changes": self.screen_changes,
            "current_screen_type": self.current_screen_type,
            "main_elements": self.main_elements,
            "blocking_dialogs": self.blocking_dialogs,
            # 画面整合性
            "screen_inconsistency": self.screen_inconsistency if self.has_screen_inconsistency() else None,
            # 進捗評価
            "test_progress": self.test_progress,
            # 目標評価
            "current_objective_achieved": self.current_objective_achieved,
            "current_objective_evidence": self.current_objective_evidence,
            # 提案
            "suggested_next_action": self.suggested_next_action,
            # 導出値（渡された場合のみ）
            **({
                "plan_still_valid": plan_still_valid
            } if plan_still_valid is not None else {})
        }
    
    def to_allure_text(self, plan_still_valid: bool = None) -> str:
        """Allure表示用の整形されたテキストを返す
        
        Args:
            plan_still_valid: プラン有効性（呼び出し元で計算した値を渡す）
        """
        # 目標達成アイコン
        achieved_icon = "✅" if self.current_objective_achieved else "❌"
        plan_valid_icon = "✅" if plan_still_valid else "🔄" if plan_still_valid is not None else "?"
        
        lines = [
            "## 🖥️ 画面状態",
            f"**画面タイプ:** {self.current_screen_type}",
            "",
            "### 画面変化",
            self.screen_changes,
            "",
            "### 主要要素",
            self.main_elements,
            "",
        ]
        
        # ブロッキングダイアログ
        if self.blocking_dialogs:
            lines.extend([
                "### ⚠️ ブロッキングダイアログ",
                f"```",
                self.blocking_dialogs,
                f"```",
                "",
            ])
        
        # 画面整合性
        if self.has_screen_inconsistency():
            lines.extend([
                "### ⚠️ 画面整合性エラー",
                f"```",
                self.screen_inconsistency,
                f"```",
                "",
            ])
        
        lines.extend([
            "---",
            "## 📊 進捗評価",
            f"**テスト進捗:** {self.test_progress}",
            "",
            f"### {achieved_icon} 現在の目標ステップ達成: {'Yes' if self.current_objective_achieved else 'No'}",
            f"**根拠:** {self.current_objective_evidence}",
            "",
        ])
        
        if plan_still_valid is not None:
            lines.extend([
                f"### {plan_valid_icon} プラン有効性: {'有効' if plan_still_valid else '再構築必要'}",
                "",
            ])
        
        if self.suggested_next_action:
            lines.extend([
                "---",
                "## 💡 次のアクション提案",
                self.suggested_next_action,
            ])
        
        return "\n".join(lines)


class MultiStageReplanner:
    """3段階に分けてreplanを実行するクラス（miniモデル用）"""
    
    def __init__(self, llm, app_package_info: str, knowhow: str, token_callback=None):
        self.llm = llm
        self.app_package_info = app_package_info
        self.knowhow = knowhow
        self.model_name = llm.model_name if hasattr(llm, 'model_name') else "unknown"
        self.token_callback = token_callback  # track_query()用に保持
    
    def _format_step_history(self, step_history: list) -> str:
        """ステップ履歴を整形してLLMプロンプト用の文字列として返す"""
        if not step_history:
            return "(実行済みステップなし)"
        
        formatted = []
        for i, entry in enumerate(step_history[-3:], 1):  # 最新3件のみ
            step = entry.get("step", "不明")
            success = entry.get("success", False)
            evaluation = entry.get("evaluation", {})
            
            status = "✅ 成功" if success else "❌ 失敗"
            executor_reason = evaluation.get("executor_reason", "").strip()[:200]
            
            formatted.append(f"""
ステップ {i}: {step}
状態: {status}
評価理由: {executor_reason}
""")
        
        return "\n".join(formatted)

    async def analyze_state(
        self,
        goal: str,
        original_plan: list,
        past_steps: list,
        locator: str,
        previous_image_url: str,
        current_image_url: str,
        objective_progress: ObjectiveProgress,
        step_history: list = None
    ) -> StateAnalysis:
        """ステージ1: 画像（前回/現在）とロケーターから現状を把握

        画像がある場合はLLMへマルチモーダルで渡し、差分言及を促す。
        構造化されたStateAnalysisオブジェクトを返す。
        
        Args:
            goal: 全体の目標
            original_plan: 元の実行計画（参照用）
            past_steps: 完了済みステップ（参照用、全履歴）
            locator: 画面のロケーター情報
            previous_image_url: 前回のスクリーンショット
            current_image_url: 現在のスクリーンショット
            objective_progress: 目標進捗管理オブジェクト（必須）
        """
        # 進捗情報を取得
        current_step = objective_progress.get_current_step()
        if not current_step:
            raise ValueError("No current step in ObjectiveProgress")
        
        remaining = objective_progress.get_current_remaining_plan()
        total_steps = len(current_step.execution_plan)
        remaining_steps = len(remaining)
        completed_steps = total_steps - remaining_steps
        dialog_mode = objective_progress.is_handling_dialog()
        dialog_count = objective_progress.get_dialog_handling_count()
        
        # ★ログ出力: ダイアログ処理モードと通常モードで分離
        if dialog_mode:
            # ダイアログ処理モード用ログ
            SLog.log(LogCategory.ANALYZE, LogEvent.START, {
                "mode": "dialog",
                "dialog_count": dialog_count,
                "frozen_plan": {"total": total_steps, "completed": completed_steps, "remaining": remaining_steps},
                "target_objective": {"index": current_step.index, "description": current_step.description[:60]},
                "next_pending_step": remaining[0][:70] if remaining else None
            }, "🔒 ダイアログ処理モード")
        else:
            # 通常モード用ログ
            SLog.log(LogCategory.ANALYZE, LogEvent.START, {
                "mode": "normal",
                "plan": {"total": total_steps, "completed": completed_steps, "remaining": remaining_steps},
                "objective_progress": f"{objective_progress.get_completed_objectives_count()}/{objective_progress.get_total_objectives_count()}",
                "current_objective": {"index": current_step.index, "description": current_step.description[:60]}
            }, "📋 通常処理モード")
        
        # 直近の実行ステップ（両モード共通）
        if past_steps:
            recent_steps = [{"step": step[:60], "result": str(result)[:50]} for step, result in past_steps[-3:]]
            SLog.log(LogCategory.ANALYZE, LogEvent.UPDATE, {"recent_steps": recent_steps}, "直近のステップ (最新3件)")
        
        # 目標ステップ情報を構築
        # ObjectiveProgress.format_for_llm()を使用して進捗情報を生成
        progress_info = ""
        current_objective = ""
        if objective_progress:
            progress_info = objective_progress.format_for_llm()
            current_step = objective_progress.get_current_step()
            if current_step:
                current_objective = current_step.description
        
        prompt_text = f"""
あなたは画面状態を分析するエキスパートです。

【全体の目標】
{goal}

{progress_info}

【実行済みステップの詳細情報】★超重要★
以下は各ステップの実行結果と評価内容です。条件分岐ステップの評価に特に注目してください。
{self._format_step_history(step_history)}

【重要】評価基準について
- 「目標と実行プランの全体進捗」を確認し、実行プランが全て✅なら目標達成と判断すること
- 現在評価中の目標ステップ「{current_objective or goal}」が達成されているかを特に評価すること
- 【実行済みステップの詳細情報】から条件不成立（success=False）の理由を確認し、
  テスト合否判定基準に照らして妥当かを判断すること

【★超重要★ ダイアログ処理と目標ステップ達成の区別】
- ブロッキングダイアログ（初期設定、プライバシーポリシー等）を閉じる操作は、目標ステップとは別物です
- 例: 目標「アプリを起動する」→ ダイアログを閉じただけでは未達成
  - activate_appツールを呼び出して初めて達成
  - 実行プランに「activate_appを呼び出す」等のステップがあるか確認
- 例: 目標「ホームタブをタップする」→ ダイアログを閉じただけでは未達成
  - click_elementでホームタブをタップして初めて達成
  - 実行プランに「ホームタブをクリック」等のステップがあるか確認
- ★判定ルール★: 実行プランの進捗が「0/0」や「0/N」の場合、目標ステップは未達成

【★超重要★ スキップ不可の原則】
- 「すべてのタブをタップする」等の目標において、初期状態で選択済みの要素があっても「達成済み」とみなしてはいけない
- 例: ホームタブが初期選択されていても、ホームタブをタップしていなければ「ホームタブのタップ」は未達成
- 理由: タップすることでUIに変化が発生する可能性があり、テストとして確認が必要
- 【★重要★】目標ステップの達成判定は、実行プランの進捗（✅完了マーク）のみで行うこと
  - ダイアログを閉じただけでは目標ステップは完了していない
  - activate_appツール等、必要なツールを呼び出して初めて完了となる

【★必須★ 「すべて」目標の要素カウント】
- 「すべてのタブ/ボタン/項目をタップする」目標がある場合:
  → 画面上に存在する対象要素の総数を必ずカウントして報告すること
  → 例: 「タブメニューには7個のタブが存在: ホーム、映画、テレビ、アプリ、放送中の番組、お気に入り、最近の項目」
  → このカウントがプラン生成時の参照情報となる

【★超重要★ 「すべて」目標の達成判断ルール】
- 「すべてのタブをタップする」「すべてのボタンを押す」等の目標の達成判断:
  1. 「実行プランの全体像と進捗」を確認する
  2. プラン内の対象操作（各タブのタップ等）が全て ✅（完了済み）かを確認
  3. 全て完了済み → current_objective_achieved = True
  4. ▶️（現在位置）や ⏳（未実行）の対象操作がある → current_objective_achieved = False
  
- ★重要★ 現在の画面状態ではなく、**プランの進捗状況**に基づいて判断すること
  - プランで全タブのタップが✅なら、現在どのタブが選択されていても「達成」
  - プランで「お気に入りタブをタップ」が⏳なら「未達成」

【「確認する」目標の判定基準】（重要）
- 「〇〇を確認する」「〇〇ダイアログを確認する」目標の場合:
  - 対象が画面に表示されている → 「達成」（表示を確認できた）
  - 対象が画面に表示されていない → 「未達成」（表示されていないので確認できない）
  - ブロッキング要素がないのに対象が表示されていない場合は、未達成と判断し、テストに失敗を報告すること

【テスト合否判定基準との照合】★超重要★

現在の目標ステップの達成判断時:
1. プラン進捗を確認
2. 条件不成立ステップ（⚠️）がある場合、テスト合否判定基準を参照
3. 条件不成立がテスト仕様と矛盾する場合:
   - current_objective_achieved = False
   - current_objective_evidence に「テスト合否判定基準との矛盾」を明記
   - 例: 「『初期起動以外はダイアログ非表示』だが、ダイアログが表示されていないため
           目標『ダイアログの同意ボタンを押す』は達成できない。アプリ不具合の可能性」

条件不成立の評価方法（必須の分析手順）:

★★★ 以下の手順を必ず順番通りに実行してください ★★★

【手順1】テスト合否判定基準の条件部分を明示的に抽出
- 「〇〇以外の場合」「△△の後」「××が完了した場合」などを特定
- 例: 「初期起動以外の場合、ディスクレーマーダイアログは表示しない」
  → 条件: 「初期起動以外」、結果: 「ダイアログ非表示」

【手順2】目標ステップ一覧から現在のアプリ状態を明示的に分析（★★★必須★★★）
- 目標ステップ一覧の実行状態（✅完了、🔄実行中、⏳未実行）を注意深く確認
- 条件に関連するステップ（再起動、2回目の操作等）の状態を確認
- **分析例1**: 「初期起動以外」の判断
  - 目標ステップに「アプリを再起動する」が存在するか確認
  - ✅完了 → 既に再起動済み → 初期起動以外の状態
  - ⏳未実行 → まだ再起動していない → **現在は初期起動中**
- **分析例2**: 「ログイン後」の判断
  - 目標ステップに「ログインする」が存在するか確認
  - ✅完了 → ログイン済み → ログイン後の状態
  - ⏳未実行 → ログイン前の状態

【手順3】現在の状態に基づいて期待値を論理的に決定
- 手順2で分析した「現在の状態」が、手順1で特定した「条件」に該当するか判断
- 該当する → 基準の結果部分が期待値
- **該当しない → 基準の逆が期待値（論理的推論）**
- 例: 手順2の分析で「現在は初期起動中」+ 手順1の基準「初期起動以外は非表示」
  → 条件「初期起動以外」に該当しない
  → **期待値は逆の「初期起動時はダイアログ表示」**

【手順4】実際の画面状態と期待値を比較
- 一致 → 仕様通り（current_objective_achieved = true）
- 不一致 → アプリ不具合の可能性（current_objective_achieved = false）

★★★ 重要 ★★★
- 手順2を省略せず、目標ステップ一覧を必ず詳細に分析してください
- 「再起動ステップが⏳未実行」なら「まだ初期起動中」と明示的に判断してください
- 条件に該当しない場合、期待値は基準の逆になります

【★重要★ 画面整合性チェック（page_source と スクリーンショット画像の比較）】
ロケーター情報（page_source）とスクリーンショット画像を比較して、整合性を確認してください。

■ 整合性チェックのポイント:
1. page_sourceに記載されているUI要素が、スクリーンショット画像でも視認できるか
2. 画像が黒い/白い/空の画面なのに、page_sourceには多数の要素が記載されていないか
3. 画面読み込み中（ローディングスピナー、プログレスバー）の兆候がないか

■ 整合性チェック結果の報告方法:
- 正常な場合: screen_inconsistency = null（設定しない）
- 不整合がある場合: screen_inconsistency に詳細を記載
  → 例: "画像は黒いがpage_sourceにはナビゲーション要素がある"
  → 例: "ローディングスピナーが表示されている"
  → 例: "page_sourceと画像の内容が著しく異なる"

★重要★ screen_inconsistency は不具合判定ではない:
- 不整合を検出した場合、呼び出し元でウェイト後に再チェックする
- 再チェックでも不整合が続く場合のみ、呼び出し元がアプリ不具合として扱う

■ 重要:
- 正常な画面であれば screen_inconsistency を設定しない
- わずかな違い（アニメーション途中など）は問題なし
- page_sourceに記載された主要要素が画像で見えない場合に設定

【分析指示】
1. 画面整合性チェック（上記の基準に従って screen_inconsistency を設定）
2. 前ステップからの画面変化と差分（UI要素の追加/削除/変更）
3. 現在の画面の種類（例：ホーム画面、検索結果、設定画面など）
4. 画面上の主要UI要素の説明 (ボタン、テキストフィールド、画像、リスト、メニュー、ダイアログ、背景などを resource-id や class 名で具体的に記述)
5. 目標達成を妨げるダイアログやオーバーレイの有無（★超重要★これがあればまず処理が必要）
   ★ブロッキングダイアログを検出した場合は、閉じるためのボタンの resource-id も blocking_dialogs に記載すること★
   例: 「利用規約ダイアログ、閉じるボタン: com.example.app:id/terms_agree」
6. 現在の目標ステップが達成されているかどうか
7. 現在の目標ステップの達成/未達成の根拠
8. 【★重要★ 残りステップの処理方針】（残りステップがある場合のみ）
   - 実行プランの進捗を確認（✅完了、▶️現在、⏳未実行）
   - これまで実行したステップで目標が達成されているか判断
   - 残りステップが本当に必要か評価
   - remaining_steps_action を設定:
     * "EXECUTE": 残りステップをそのまま実行すべき（目標未達成）
     * "DISCARD": 残りステップは不要（目標達成済み、重複操作になる）
     * "REPLAN": 残りステップが不適切（画面状態と合わない、修正が必要）
   - 残りステップがない場合は remaining_steps_action = null
9. 次に実行すべきアクションの提案（任意）

【ブロッキング要素の判定基準】（★重要★）
以下に該当する画面は「目標達成を妨げるダイアログやオーバーレイ」として報告すること:
- アプリの初期設定画面（プライバシーポリシー、チュートリアル、ウェルカム画面など）
- 初回起動時のオンボーディング画面（「次へ」「More」「Got it」「同意する」ボタンがある画面）
- ログイン/アカウント設定を促す画面
- プライバシー設定・Cookie同意画面
- 広告や通知の許可を求める画面
- 位置情報やカメラなどのパーミッション許可画面
- その他、目標の操作対象（メニューアイコン等）が画面に表示されていない原因となる画面
【★例外★】ブロッキングと判定しないケース:
現在の目標ステップがダイアログ自体を操作対象としている場合は、ブロッキングとして報告しないこと。
例:
- 目標「利用規約ダイアログを確認する」→ ダイアログは操作対象なのでブロッキングではない
- 目標「プライバシーポリシーに同意する」→ 同意画面は操作対象なのでブロッキングではない
- 目標「初期設定を完了する」→ 初期設定画面は操作対象なのでブロッキングではない

判定ポイント:
- 現在の目標ステップで操作したい要素（例：メニューアイコン）が画面上に存在しない場合、
  その原因となっている画面はブロッキング要素である
- ただし、その画面自体が目標の操作対象であれば、ブロッキングではなく正常な状態
- 「More」「Next」「Accept」「OK」などのボタンがある画面は、目標がそれ以外の操作を要求している場合のみブロッキング

現在のロケーター情報:
{locator}

画面スクリーンショット（前回の画面と現在の画面):
"""

        content_blocks: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        if previous_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": previous_image_url}})
        if current_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": current_image_url}})

        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "analyze_state",
            "model": self.model_name,
            "prompt": prompt_text,
            "has_previous_image": bool(previous_image_url),
            "has_current_image": bool(current_image_url)
        }, "LLMプロンプト送信: analyze_state", attach_to_allure=True)

        # 構造化出力を使用
        structured_llm = self.llm.with_structured_output(StateAnalysis)
        
        # track_query()でクエリごとのトークン使用量を記録
        with self.token_callback.track_query():
            state_analysis: StateAnalysis = await structured_llm.ainvoke([HumanMessage(content=content_blocks)])
        
        # 残りステップ数を計算してプラン有効性を判定
        # ObjectiveProgressは必須なので、正確な残りステップ数を使用
        plan_still_valid = state_analysis.is_plan_still_valid(remaining_steps)
        
        # StateAnalysisの全フィールドをログ出力（JSONLファイル用）
        SLog.log(LogCategory.ANALYZE, LogEvent.COMPLETE, 
            state_analysis.to_log_dict(plan_still_valid=plan_still_valid),
            "State analysis completed"
        )
        
        # Allure用に整形されたテキストを添付
        SLog.attach_text(
            state_analysis.to_allure_text(plan_still_valid=plan_still_valid),
            "💡 LLM Response: State Analysis"
        )
        
        return state_analysis

    
    async def decide_action(
        self, 
        goal: str, 
        original_plan: list, 
        past_steps: list, 
        state_analysis: StateAnalysis,
        objective_progress: ObjectiveProgress
    ) -> tuple:
        """ステージ2: Plan/Responseどちらを返すべきか判断（構造化出力）
        
        Args:
            goal: テスト目標
            original_plan: 元の計画（参照用）
            past_steps: 完了済みステップ（参照用）
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト（必須）
        """
        # ObjectiveProgressから進捗情報を取得
        # ★重要★ state_analysis.current_objective_achieved を渡して、正しい進捗表示を生成
        objective_and_plan_info = objective_progress.format_for_llm(
            current_objective_achieved=state_analysis.current_objective_achieved
        )
        # 全目標達成判定（現在の目標の達成状態を考慮）
        all_objectives_completed = objective_progress.is_all_objectives_completed_with_current(
            state_analysis.current_objective_achieved
        )

        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}
テスト進捗: {state_analysis.test_progress}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
現在の目標ステップ根拠: {state_analysis.current_objective_evidence}
全ての目標ステップ達成: {"Yes" if all_objectives_completed else "No"}
残りステップ処理方針: {state_analysis.remaining_steps_action or "N/A"}
"""

        prompt = f"""あなたは次のアクションを厳密に判断するエキスパートです。

【目標】
{goal}

{objective_and_plan_info}

【状態分析結果】
{state_summary}

【判断基準（厳格）】
★重要★ 判断基準は「ユーザー目標ステップ」の達成度です。LLM実行計画の進捗ではありません。
★重要★ 「実行プランの全体像と進捗」を確認し、全ステップが✅なら目標達成と判断すること。

【プラン進捗の判断基準】★重要★

実行プランの進捗確認時:
- ✅（完了済み）: ステップが成功裏に実行完了
- ⚠️（条件不成立）: 条件分岐ステップで条件が不成立
- ❌（失敗）: ステップ実行がエラーで失敗

目標達成判断:
- 全ステップが✅ → current_objective_achieved = True
- ⚠️ステップが存在 → current_objective_achieved = False（条件不成立は未達成）
- ❌ステップが存在 → current_objective_achieved = False

例:
- 実行プラン: [1]✅完了 [2]⚠️条件不成立「ダイアログが表示されていれば同意ボタンを押す」 → 目標未達成
- 理由: 条件不成立は「ステップが完了していない」状態を意味する

★最優先★ ブロッキングダイアログの処理:
0. ブロッキングダイアログがある → decision=PLAN（まず障害物を処理）
   - 初期設定ダイアログ、オンボーディング画面は「アプリ不具合」ではない
   - knowhowに従って回避操作（同意ボタン押下など）を実行すべき
   - これは正常なフローなので、テスト失敗として報告してはいけない

★次に重要★ アプリ不具合の検出（ブロッキングダイアログがない場合のみ）:
1. アプリの不具合が検出された場合 → decision=RESPONSE（テスト失敗として報告）
   - アプリがクラッシュした
   - 予期しないエラーダイアログが表示された
   - アプリがフリーズして操作できない
   - 同じ操作を繰り返しても状態が変わらない（スタック状態）
   - ブロッキングダイアログを全て処理した後も、目標の操作対象が存在しない

★条件不成立（⚠️）の特別な判断★:
2. 条件不成立（⚠️）ステップがある場合:
   a. テスト合否判定基準を確認
   b. 条件不成立が「仕様通り（期待される動作）」かどうかを判定
   
   【仕様通りの条件不成立の場合】
   - 例: 「初期起動以外はダイアログ非表示」なのに、目標が「ダイアログの同意ボタンを押す」
   - この場合、目標ステップ自体がテスト仕様と矛盾している
   - → decision=RESPONSE（テスト失敗として報告）
   - reason例: 「目標『ダイアログの同意ボタンを押す』はテスト合否判定基準『初期起動以外はダイアログ非表示』と矛盾。
                初期起動以外の状態でダイアログが表示されないため、同意ボタンを押すことはできない。
                テスト手順またはテスト合否判定基準に誤りがある可能性。」
   
   【仕様外の条件不成立の場合（アプリ不具合）】
   - 例: 「初期起動時はダイアログ表示」だが、実際は表示されていない
   - → decision=RESPONSE（テスト失敗として報告）
   - reason例: 「テスト合否判定基準では初期起動時にダイアログが表示されるべきだが、
                条件『ダイアログが表示されている』が不成立。アプリ不具合の可能性。」

★超重要★ 残りステップ処理方針の考慮:
3. 残りステップ処理方針が "DISCARD" の場合:
   - これは「残りステップは不要、目標達成済み」を意味する
   - 現在の目標が最後の目標なら → decision=RESPONSE（テスト成功）
   - まだ次の目標がある場合 → decision=PLAN（次の目標へ進む）
   - ★重要★: DISCARD = 目標達成済みなので、実行プラン進捗（✅/⏳）を見る必要はない

通常の判断:
4. 現在の目標ステップが未達成（⚠️を除く）→ decision=PLAN
5. 現在の目標ステップが達成済みで、かつ「現在の目標が最後の目標: Yes」の場合 → decision=RESPONSE（テスト成功として報告）
6. 現在の目標ステップが達成済みで、まだ次の目標ステップがある場合 → decision=PLAN
7. 全ての目標ステップが達成済み → decision=RESPONSE（テスト成功として報告）

【出力仕様】
厳格なJSON
"""

        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "decide_action",
            "model": self.model_name,
            "prompt": prompt
        }, "LLMプロンプト送信: decide_action", attach_to_allure=True)

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(DecisionResult)
        try:
            if self.token_callback:
                with self.token_callback.track_query():
                    result = await structured_llm.ainvoke(messages)
            else:
                result = await structured_llm.ainvoke(messages)
            
            SLog.log(LogCategory.PLAN, LogEvent.COMPLETE, 
                result.to_log_dict(),
                f"Decision: {result.decision}"
            )
            SLog.attach_text(result.to_allure_text(), f"💡 LLM Response: Decision")
            decision_norm = result.decision.strip().upper()
            if decision_norm not in ("PLAN", "RESPONSE"):
                decision_norm = "PLAN"  # 安全側フォールバック
            return decision_norm, result.reason.strip()
        except Exception as e:
            # 構造化出力失敗時は安全側でPLANを返す
            SLog.error(LogCategory.DECIDE, LogEvent.FAIL, {"error": str(e)}, "Structured Output Error")
            SLog.attach_text(str(e), "❌ decide_action: Structured Output Error")
            return "PLAN", "構造化出力エラーのためフォールバック"
    
    async def build_plan(
        self,
        goal: str,
        original_plan: list,
        past_steps: list,
        state_analysis: StateAnalysis,
        objective_progress: ObjectiveProgress,
        locator: str,
        step_history: list = None
    ) -> Plan:
        """ステージ3a: 次のPlanを作成（C案: ハイブリッド方式）
        
        残りステップはコード側で保護し、LLMにはブロッキングダイアログ処理のみを任せる。
        
        Args:
            goal: テスト目標
            original_plan: 元の計画（参照用）
            past_steps: 完了済みステップ（参照用）
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト（必須）
            locator: 画面のロケーター情報
            step_history: 実行済みステップの詳細情報（success, evaluationを含む）
        """
        # 進捗情報を取得
        current_step = objective_progress.get_current_step()
        if not current_step:
            raise ValueError("No current step in ObjectiveProgress")
        
        remaining = objective_progress.get_current_remaining_plan()
        dialog_mode = objective_progress.is_handling_dialog()
        dialog_count = objective_progress.get_dialog_handling_count()
        total_steps = len(current_step.execution_plan)
        remaining_count = len(remaining)
        completed_steps = total_steps - remaining_count
        
        # ★ログ出力: ダイアログ処理モードと通常モードで分離
        if dialog_mode:
            # ダイアログ処理モード用ログ
            SLog.log(LogCategory.PLAN, LogEvent.START, {
                "mode": "dialog",
                "dialog_count": dialog_count,
                "blocking_dialogs": state_analysis.blocking_dialogs,
                "frozen_plan": {"total": total_steps, "completed": completed_steps, "remaining": remaining_count},
                "target_objective": {"index": current_step.index, "description": current_step.description[:60]},
                "next_pending_step": remaining[0][:70] if remaining else None
            }, "🔒 ダイアログ処理モード")
        else:
            # 通常モード用ログ
            SLog.log(LogCategory.PLAN, LogEvent.START, {
                "mode": "normal",
                "plan": {"total": total_steps, "completed": completed_steps, "remaining": remaining_count},
                "remaining_steps_preview": [step[:60] for step in remaining[:3]] if remaining else [],
                "objective_progress": f"{objective_progress.get_completed_objectives_count()}/{objective_progress.get_total_objectives_count()}",
                "current_objective": {"index": current_step.index, "description": current_step.description[:60]},
                "state_analysis": {"achieved": state_analysis.current_objective_achieved, "blocking": bool(state_analysis.blocking_dialogs)}
            }, "📋 通常処理モード")
        
        # ★★★ C案: ハイブリッド方式 ★★★
        # 残りステップはコード側で保護し、LLMにはブロッキングダイアログ処理のみを任せる
        
        # ★修正★ ケース1: ブロッキングダイアログがある場合（最優先でチェック）
        # → 残りステップ数に関わらず、ダイアログ処理ステップのみをLLMに生成させる
        if state_analysis.blocking_dialogs:
            SLog.log(LogCategory.DIALOG, LogEvent.START, {
                "blocking_dialogs": state_analysis.blocking_dialogs,
                "frozen_steps": remaining_count
            }, "🔒 ダイアログ処理: ステップ生成中")
            dialog_steps = await self._generate_dialog_handling_steps(
                state_analysis, locator
            )
            SLog.log(LogCategory.DIALOG, LogEvent.COMPLETE, {
                "generated_steps": len(dialog_steps)
            }, "🔒 ダイアログ処理ステップ生成完了")
            return Plan(steps=dialog_steps)  # ダイアログ処理のみ（結合しない）
        
        # ケース1.5: 直前の実行ステップが失敗した場合、リプランが必要
        # → LLMが生成した実行プランが誤っている可能性があるため、新規プラン生成
        # ★重要★ 目標ステップの失敗ではなく、実行ステップの失敗のみをチェック
        if step_history and len(step_history) > 0:
            last_step = step_history[-1]
            if not last_step.get("success", True):
                evaluation = last_step.get("evaluation", {})
                executor_reason = evaluation.get("executor_reason", "")[:150]
                
                SLog.log(LogCategory.PLAN, LogEvent.UPDATE, {
                    "failed_step": last_step.get("step", "")[:60],
                    "executor_reason": executor_reason,
                    "remaining_steps": remaining_count
                }, "📝 前ステップ失敗: プラン修正が必要")
                
                # 新規プラン生成（失敗した理由を考慮して改善されたプランを作る）
                return await self._generate_new_plan(
                    goal, state_analysis, objective_progress, locator
                )
        
        # ケース2: ブロッキングダイアログがなく、残りステップがある場合
        # → analyze_stateで判断された処理方針に従う
        if remaining_count > 0:
            # analyze_stateで判断された処理方針を取得
            action = state_analysis.remaining_steps_action or "EXECUTE"  # デフォルトはEXECUTE
            
            if action == "EXECUTE":
                # 残りステップをそのまま実行
                if dialog_mode:
                    SLog.log(LogCategory.DIALOG, LogEvent.COMPLETE, {
                        "remaining_steps": remaining_count
                    }, "🔓 ダイアログ処理完了 → 通常処理に復帰")
                else:
                    SLog.log(LogCategory.PLAN, LogEvent.UPDATE, {
                        "remaining_steps": remaining_count
                    }, "📋 残りステップを継続実行")
                return Plan(steps=remaining)
            
            elif action == "DISCARD":
                # 残りステップを破棄（目標達成済み）
                SLog.log(LogCategory.PLAN, LogEvent.UPDATE, {
                    "discarded_steps": remaining[:3],
                    "reason": "目標達成済み、残りステップは不要"
                }, "⏭️ 残りステップを破棄: 確認操作に置き換え")
                replacement_steps = ["現在の画面が正しく表示されていることを確認する"]
                return Plan(steps=replacement_steps)
            
            elif action == "REPLAN":
                # 残りステップを修正（リプラン）
                SLog.log(LogCategory.PLAN, LogEvent.UPDATE, {
                    "reason": "残りステップが不適切、リプランが必要"
                }, "🔄 残りステップをリプラン")
                return await self._generate_new_plan(
                    goal, state_analysis, objective_progress, locator
                )
            
            else:
                # フォールバック: そのまま実行
                SLog.warn(LogCategory.PLAN, LogEvent.RETRY, {
                    "unexpected_action": action
                }, "⚠️ 予期しないアクション、残りステップをそのまま実行")
                return Plan(steps=remaining)
        
        # ケース3: ブロッキングダイアログもなく、残りステップもない場合
        # → 目標達成済みまたは次の目標へ進む必要がある（新規プラン生成が必要）
        SLog.log(LogCategory.PLAN, LogEvent.UPDATE, {}, "📝 残りステップなし: 新規プラン生成")
        return await self._generate_new_plan(
            goal, state_analysis, objective_progress, locator
        )
    
    def _create_state_analysis_for_dialog(self, screen_analysis) -> StateAnalysis:
        """ScreenAnalysisからStateAnalysisを生成するヘルパー（plan_step用）
        
        plan_stepで初回のダイアログ検出時に使用。
        ScreenAnalysisの情報をStateAnalysisに変換する。
        
        Args:
            screen_analysis: simple_planner.ScreenAnalysis オブジェクト
            
        Returns:
            StateAnalysis: ダイアログ処理用の状態分析結果
        """
        return StateAnalysis(
            screen_changes="初回分析（前回画面なし）",
            current_screen_type=screen_analysis.screen_type,
            main_elements=screen_analysis.main_elements,
            blocking_dialogs=screen_analysis.blocking_dialogs,
            test_progress="初回計画作成中",
            current_objective_achieved=False,
            current_objective_evidence="初回計画作成中のため未評価",
            suggested_next_action=f"ダイアログを閉じる: {screen_analysis.blocking_dialogs}"
        )
    
    async def _generate_dialog_handling_steps(
        self,
        state_analysis: StateAnalysis,
        locator: str
    ) -> list:
        """ブロッキングダイアログを閉じるためのステップのみを生成（1〜2ステップ）"""
        
        prompt = f"""ブロッキングダイアログを閉じるためのステップを生成してください。

【検出されたブロッキングダイアログ】
{state_analysis.blocking_dialogs}

【画面のロケーター情報】
{locator if locator else "なし"}

【タスク】
上記のダイアログを閉じるためのステップを**1〜2個だけ**生成してください。

【ルール】
- 同意ボタン、OKボタン、閉じるボタンなど、ダイアログを閉じるボタンをタップするステップを生成
- blocking_dialogsに記載されているresource-idがあれば、それを使用する
- ロケーター情報から適切なボタン（"同意する"、"OK"、"閉じる"、"Accept"、"Got it"等）を見つけて使用する
- ステップは具体的で実行可能なこと
- **ダイアログを閉じる操作のみ**を生成すること（その後の操作は含めない）
- ★★重要★★ ステップ記述には必ず「〜して、ダイアログを閉じる」という目的を含めること
  - ✅ 良い例: 「resource-id 'xxx' の「OK」ボタンをタップして、ダイアログを閉じる」
  - ❌ 悪い例: 「resource-id 'xxx' の「OK」ボタンをタップする」（目的不明確）

【出力形式】
steps: ダイアログを閉じるためのステップ（1〜2個のリスト）
"""
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "_generate_dialog_handling_steps",
            "model": self.model_name,
            "prompt": prompt
        }, "LLMプロンプト送信: _generate_dialog_handling_steps", attach_to_allure=True)

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Plan)
        
        try:
            if self.token_callback:
                with self.token_callback.track_query():
                    plan = await structured_llm.ainvoke(messages)
            else:
                plan = await structured_llm.ainvoke(messages)
            
            SLog.log(LogCategory.DIALOG, LogEvent.COMPLETE,
                plan.to_log_dict(),
                f"生成: {len(plan.steps)}ステップ"
            )
            SLog.attach_text(plan.to_allure_text(), "💡 LLM Response: Dialog Handling")
            return plan.steps
        except Exception as e:
            SLog.error(LogCategory.DIALOG, LogEvent.FAIL, {"error": str(e)}, "ダイアログステップ生成エラー")
            # フォールバック: blocking_dialogsに記載されたresource-idを使ってタップ
            if state_analysis.blocking_dialogs:
                fallback_step = f"resource-id '{state_analysis.blocking_dialogs}' をタップしてダイアログを閉じる"
                return [fallback_step]
            return []
    
    async def _generate_new_plan(
        self,
        goal: str,
        state_analysis: StateAnalysis,
        objective_progress: Optional[ObjectiveProgress] = None,
        locator: str = ""
    ) -> Plan:
        """新規プランを生成（残りステップがない場合のみ呼ばれる）"""

        # Appiumツール情報を取得
        tools_info = appium_tools.appium_tools_for_prompt()
        # 現在のアプリ
        current_app_info = await appium_tools.get_current_app.ainvoke({}) if state_analysis else "不明"
        
        # ObjectiveProgressから進捗情報を取得
        objective_and_plan_info = ""
        current_objective = ""
        if objective_progress:
            objective_and_plan_info = objective_progress.format_for_llm()
            current_step = objective_progress.get_current_step()
            if current_step:
                current_objective = current_step.description
        


        # StateAnalysisから状態要約を構築
        state_summary = f"""
{self.app_package_info}
{current_app_info}
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
達成判断理由: {state_analysis.current_objective_evidence}
次のアクション提案: {state_analysis.suggested_next_action or "なし"}
"""
        
        # ロケーター情報セクション
        locator_section = ""
        if locator:
            locator_section = f"""
【現在の画面ロケーター情報】
{locator}
"""
        
        prompt = f"""あなたは実行計画を作成するエキスパートです。

【全体の目標】
{goal}

{objective_and_plan_info}

【現在の状態分析結果】
{state_summary}

{locator_section}

【タスク】
現在の目標ステップ「{current_objective or goal}」を達成するために必要なステップを生成してください。

【ルール】
- 目標達成に必要な**最小限のステップ**のみを生成すること
- 「すべて」「順番に」などの繰り返し目標の場合、**すべての対象要素**に対してステップを生成すること
- 「コンテンツをクリックする」などの抽象的な指示のために、操作対象となるオブジェクトが複数ある場合には、**１つ目の要素に対してのみステップを生成**すること
- 各ステップは具体的で実行可能なこと
- 再起動の場合は再起動ツールを使用すること

【厳格ルール】
- 目標の意味を変えない、拡大解釈しない
- 「確認する」が目標なら確認のみ（操作は不要）
- 「起動する」が目標で既に起動済みの場合でも必ずツールを使って起動する
- ステップは具体的に、かつ簡潔に自然言語で記述し、ツール名や id や xpath を含めてはならない
- 目標と関係ないステップを追加しない
- 勝手にステップを追加しない
- ★★重要★★ ステップ記述には**必ず目的や期待される結果を含める**こと
  - ✅ 良い例: 「ホームタブをタップして、ホーム画面を表示する」
  - ✅ 良い例: 「検索ボックスに『東京』と入力して、検索候補を表示する」
  - ✅ 良い例: 「設定ボタンをタップして、設定画面を開く」
  - ❌ 悪い例: 「ホームタブをタップする」（目的不明確）
  - ❌ 悪い例: 「検索ボックスに入力する」（何を入力するか不明確）

【★超重要★ 目標ステップを忠実に実行プランに変換すること】
- 目標に記載された操作を素直に実行プランに変換すること
- 必要に応じて複数のステップに分解してもよいが、**目標の意図を変えない**こと
- **勝手に条件分岐を追加しない**
  - ❌ 誤り: 目標「〇〇をタップする」→ プラン「〇〇が選択状態であれば何もしない、選択状態でなければタップする」
  - ✅ 正しい: 目標「〇〇をタップする」→ プラン「〇〇をタップする」
  - ✅ 許容: 目標「設定画面で通知をONにする」→ プラン「1. 設定画面を開く 2. 通知項目を探す 3. 通知をONにする」（操作達成に必要な分解）
  - ✅ 許容: 目標「検索バーで『東京』を検索する」→ プラン「1. 検索バーをタップ 2. 『東京』と入力 3. 検索ボタンをタップ」（操作達成に必要な分解）
  - ✅ 許容: 目標「ログイン画面でログインする」→ プラン「1. メールアドレスを入力 2. パスワードを入力 3. ログインボタンをタップ」（操作達成に必要な分解）
- **勝手に「既に〇〇状態かどうかを確認」のような余計なステップを追加しない**
  - 目標に「確認」が含まれない限り、確認ステップは不要
  - タップ、入力、起動などの操作は、そのまま実行すればよい

【条件分岐ステップを生成する唯一の条件】
- テスト合否判定基準に「〇〇の場合は△△」「初期起動以外は〜しない」などの条件が**明示的に**含まれる場合のみ
- 例: 目標「ダイアログの同意ボタンを押す」、基準「初期起動以外はダイアログ非表示」
  → 生成: 「ダイアログが表示されていれば同意ボタンを押す（条件分岐）」
- 条件分岐ステップは必ず「〜であれば〜する（条件分岐）」の形式で記述
- 条件分岐ステップは、条件が不成立の場合でも正常終了として扱われる（⚠️マーク）

【ノウハウ集】
{self.knowhow}

【利用可能なツール】
{tools_info}

出力形式: 厳密なJSON形式
"""
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "_generate_new_plan",
            "model": self.model_name,
            "prompt": prompt
        }, "LLMプロンプト送信: _generate_new_plan", attach_to_allure=True)

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Plan)
        
        if self.token_callback:
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
        else:
            plan = await structured_llm.ainvoke(messages)
        
        SLog.log(LogCategory.PLAN, LogEvent.COMPLETE,
            plan.to_log_dict(),
            "新規プラン生成完了"
        )
        SLog.attach_text(plan.to_allure_text(), "💡 LLM Response: New Plan")
        return plan
    
    async def build_response(
        self, 
        goal: str, 
        past_steps: list, 
        state_analysis: StateAnalysis,
        objective_progress: ObjectiveProgress
    ) -> Response:
        """ステージ3b: 完了Responseを作成
        
        Args:
            goal: テスト目標
            past_steps: 完了済みステップ
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト（必須）
        """
        completed_count = len(past_steps)
        
        # 完了したステップの一覧を作成
        completed_steps_list = "\n".join(
            f"{i+1}. {step[0]}" for i, step in enumerate(past_steps)
        ) if past_steps else "(なし)"
        
        # ObjectiveProgressから進捗情報を取得
        # ★重要★ state_analysis.current_objective_achieved を渡して、正しい進捗表示を生成
        objective_and_plan_info = objective_progress.format_for_llm(
            current_objective_achieved=state_analysis.current_objective_achieved
        )
        # 全目標達成判定（現在の目標の達成状態を考慮）
        all_objectives_completed = objective_progress.is_all_objectives_completed_with_current(
            state_analysis.current_objective_achieved
        )
        
        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
テスト進捗: {state_analysis.test_progress}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
全ての目標ステップ達成: {"Yes" if all_objectives_completed else "No"}
達成判断理由: {state_analysis.current_objective_evidence}
"""
        
        prompt = f"""あなたはタスク完了報告を作成するエキスパートです。

【目標】
{goal}

{objective_and_plan_info}

【現在の状態分析結果】
{state_summary}

【完了済み実行ステップ一覧】
{completed_steps_list}

【タスク】
タスクの完了を報告してください。以下を含めること：
1. status: {RESULT_PASS} または {RESULT_FAIL} のいずれかを設定
   - 全ての目標ステップが達成されている場合は {RESULT_PASS}
   - 目標ステップが未達成の場合は {RESULT_FAIL}
2. reason: 完了理由の詳細（100〜600文字程度）
   - 各目標ステップの達成状況
   - 達成の根拠（状態分析結果から引用）
   - 未達成がある場合はその理由
   
★★★ 重要 ★★★
reasonを作成する際は、【現在の状態分析結果】から得られた事実のみを記載してください。
テスト合否判定基準を独自に解釈してreasonに追加してはいけません。
状態分析結果が「未達成」と判断していれば、それをそのまま記載してください。

出力形式:
厳格なJSON形式（status と reason フィールドを持つ）
"""
        
        # LLMプロンプトをログ出力
        SLog.log(LogCategory.LLM, LogEvent.START, {
            "method": "build_response",
            "model": self.model_name,
            "prompt": prompt
        }, "LLMプロンプト送信: build_response", attach_to_allure=True)

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Response)
        
        if self.token_callback:
            with self.token_callback.track_query():
                resp = await structured_llm.ainvoke(messages)
        else:
            resp = await structured_llm.ainvoke(messages)
        
        SLog.log(LogCategory.TEST, LogEvent.COMPLETE,
            resp.to_log_dict(),
            f"Response created: {resp.status}"
        )
        SLog.attach_text(resp.to_allure_text(), "💡 LLM Response: Final Result")
        return resp
