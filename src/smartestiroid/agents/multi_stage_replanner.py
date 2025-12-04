"""
Multi-stage replanner for SmartestiRoid test framework.

This module provides a 3-stage replanning process for mini models.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from colorama import Fore
from langchain_core.messages import HumanMessage
import allure

from ..models import Plan, Response, DecisionResult, ObjectiveStep, ObjectiveProgress
from ..config import RESULT_PASS, RESULT_FAIL


class ObjectiveEvaluation(BaseModel):
    """個別の目標ステップの達成評価"""
    step_index: int = Field(description="目標ステップのインデックス")
    description: str = Field(description="目標ステップの説明")
    achieved: bool = Field(description="達成されているかどうか")
    evidence: str = Field(description="達成/未達成の根拠")


class StateAnalysis(BaseModel):
    """リプラン時の画面状態分析結果"""
    screen_changes: str = Field(description="前ステップからの画面変化と差分（UI要素の追加/削除/変更）")
    current_screen_type: str = Field(description="現在の画面の種類（例：ホーム画面、検索結果、設定画面など）")
    main_elements: str = Field(description="画面上の主要UI要素の説明")
    blocking_dialogs: Optional[str] = Field(default=None, description="目標達成を妨げるダイアログやオーバーレイがある場合、その内容と閉じるためのボタンのresource-id（例：'利用規約ダイアログ、閉じるボタン: com.example:id/agree_button'）")
    test_progress: str = Field(description="テスト進捗の評価（定量的または定性的）")
    problems_detected: Optional[str] = Field(default=None, description="異常挙動・エラー・予期しない遷移がある場合、その詳細")
    
    # アプリ不具合の検出（新規追加）
    app_defect_detected: bool = Field(default=False, description="アプリの不具合が検出されたかどうか（クラッシュ、フリーズ、予期しないエラー、操作不能など）")
    app_defect_reason: Optional[str] = Field(default=None, description="アプリ不具合の詳細（検出された場合のみ）")
    is_stuck: bool = Field(default=False, description="同じ操作を繰り返しても進捗がない状態（スタック状態）かどうか")
    
    # 目標ステップ単位の評価（新規追加）
    current_objective_achieved: bool = Field(description="現在の目標ステップが達成されているかどうか")
    current_objective_evidence: str = Field(description="現在の目標ステップの達成/未達成の根拠")
    
    # 従来のフィールド（互換性維持）
    goal_achieved: bool = Field(description="全体の目標が達成されているかどうか")
    goal_achievement_reason: str = Field(description="目標達成/未達成の判断根拠（ロケーター情報や画面状態に基づく）")
    suggested_next_action: Optional[str] = Field(default=None, description="次に実行すべきアクションの提案（任意）")


class MultiStageReplanner:
    """3段階に分けてreplanを実行するクラス（miniモデル用）"""
    
    def __init__(self, llm, knowhow: str, token_callback=None):
        self.llm = llm
        self.knowhow = knowhow
        self.model_name = llm.model_name if hasattr(llm, 'model_name') else "unknown"
        self.token_callback = token_callback  # track_query()用に保持
    
    async def analyze_state(
        self,
        goal: str,
        original_plan: list,
        past_steps: list,
        locator: str,
        previous_image_url: str = "",
        current_image_url: str = "",
        objective_progress: Optional[ObjectiveProgress] = None
    ) -> StateAnalysis:
        """ステージ1: 画像（前回/現在）とロケーターから現状を把握

        画像がある場合はLLMへマルチモーダルで渡し、差分言及を促す。
        構造化されたStateAnalysisオブジェクトを返す。
        
        Args:
            goal: 全体の目標
            original_plan: 元の実行計画
            past_steps: 完了済みステップ
            locator: 画面のロケーター情報
            previous_image_url: 前回のスクリーンショット
            current_image_url: 現在のスクリーンショット
            objective_progress: 目標進捗管理オブジェクト（新規追加）
        """
        # 進捗情報を計算
        total_steps = len(original_plan)
        completed_steps = len(past_steps)
        remaining_steps = max(total_steps - completed_steps, 0)
        
        # 目標ステップ情報を構築
        objective_info = ""
        current_objective = ""
        if objective_progress:
            current_step = objective_progress.get_current_step()
            if current_step:
                current_objective = current_step.description
            
            # 全目標ステップの一覧
            objective_list = []
            for step in objective_progress.objective_steps:
                status_icon = {
                    "completed": "✅",
                    "in_progress": "🔄",
                    "pending": "⏳",
                    "failed": "❌",
                    "skipped": "⏭️"
                }.get(step.status, "?")
                type_label = "🎯" if step.step_type == "objective" else "🔧"
                objective_list.append(f"  {status_icon} {type_label} [{step.index}] {step.description}")
            
            objective_info = f"""
【ユーザー目標ステップ】（これらが達成されたかを評価する基準）
{chr(10).join(objective_list)}

【現在評価中の目標ステップ】
{current_objective}

【目標進捗】
{objective_progress.get_completed_objectives_count()}/{objective_progress.get_total_objectives_count()} 目標完了
"""
        
        prompt_text = f"""
あなたは画面状態を分析するエキスパートです。

【全体の目標】
{goal}
{objective_info}

【LLM実行計画の進捗】（参考情報：目標達成のために生成された実行手順）
計画ステップ数: {total_steps}
完了ステップ数: {completed_steps}
残りステップ数: {remaining_steps}
最後の完了ステップ: {past_steps[-1][0] if past_steps else "(なし)"}

【重要】評価基準について
- LLM実行計画の進捗ではなく、「ユーザー目標ステップ」が達成されたかで判断すること
- 実行計画が全て完了しても、目標ステップが未達成なら「未達成」と判断すること
- 現在評価中の目標ステップ「{current_objective or goal}」が達成されているかを特に評価すること

【「確認する」目標の判定基準】（重要）
- 「〇〇を確認する」「〇〇ダイアログを確認する」目標の場合:
  - 対象が画面に表示されている → 「達成」（表示を確認できた）
  - 対象が画面に表示されていない → 「未達成」（表示されていないので確認できない）
  - ブロッキング要素がないのに対象が表示されていない場合は、未達成と判断し、テストに失敗を報告すること

【★アプリ不具合の検出★】（重要）
以下のいずれかに該当する場合は、app_defect_detected=True として報告すること:
- アプリがクラッシュした（ホーム画面に戻った、「アプリが停止しました」ダイアログが表示など）
- 予期しないエラーダイアログが表示された（「問題が発生しました」「エラー」など）
- アプリがフリーズして操作できない
- 同じ操作を繰り返しても画面が変化しない（スタック状態）→ is_stuck=True も設定
- 画面が真っ白/真っ黒になった
- 操作したボタンが反応しない（複数回試行後も）
- 確認するべきダイアログやテキストや要素が表示されない（ブロッキング要素がなく、かつ目標ステップが未達成の場合）

【★超重要★ アプリ不具合として報告してはいけないケース】
以下はアプリ不具合ではないため、app_defect_detected=False とすること:
- 初期設定ダイアログ/オンボーディング画面が表示されている場合
  → これは正常な動作。blocking_dialogs として報告し、回避操作で対応可能
- ログイン/アカウント設定を促す画面が表示されている場合
  → これは正常な動作。「Use without an account」等で回避可能
- プライバシーポリシー/Cookie同意画面が表示されている場合
  → これは正常な動作。同意ボタンで回避可能
- 広告/通知許可ダイアログが表示されている場合
  → これは正常な動作。閉じるボタンやスキップで回避可能
- 目標の操作対象が表示されていないが、ブロッキングダイアログを閉じれば表示される可能性がある場合
  → まずブロッキングダイアログを処理すべき
    つまり: ブロッキングダイアログがある場合 → app_defect_detected=False（回避操作で解決可能）
- typoや軽微なUIの違いによって目標ステップが未達成となっている場合
    → これはアプリ不具合ではない。目標ステップは未達成と判断すること
- find_elementなどの画面に変更を与えないツールが呼び出された後の状態
    → 画面が変化しないのは正常な動作。アプリ不具合ではない

アプリ不具合を検出した場合は、app_defect_reason に詳細を記載すること。

【分析指示】
1. 前ステップからの画面変化と差分（UI要素の追加/削除/変更）
2. 現在の画面の種類（例：ホーム画面、検索結果、設定画面など）
3. 画面上の主要UI要素の説明 (ボタン、テキストフィールド、画像、リスト、メニュー、ダイアログ、背景などを resource-id や class 名で具体的に記述)
4. 目標達成を妨げるダイアログやオーバーレイの有無（★超重要★これがあればまず処理が必要）
   ★ブロッキングダイアログを検出した場合は、閉じるためのボタンの resource-id も blocking_dialogs に記載すること★
   例: 「利用規約ダイアログ、閉じるボタン: com.example.app:id/terms_agree」
5. アプリの不具合が検出されたかどうか（★重要★）
6. 現在の目標ステップが達成されているかどうか
7. 現在の目標ステップの達成/未達成の根拠
8. 全体の目標が達成されているかどうか
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

        # 構造化出力を使用
        structured_llm = self.llm.with_structured_output(StateAnalysis)
        
        # track_query()でクエリごとのトークン使用量を記録
        with self.token_callback.track_query():
            state_analysis: StateAnalysis = await structured_llm.ainvoke([HumanMessage(content=content_blocks)])
        
        print(Fore.MAGENTA + f"[MultiStageReplanner.analyze_state model: {self.model_name}] State analysis completed")
        print(Fore.CYAN + f"  - screen_type: {state_analysis.current_screen_type}")
        print(Fore.CYAN + f"  - current_objective_achieved: {state_analysis.current_objective_achieved}")
        print(Fore.CYAN + f"  - goal_achieved: {state_analysis.goal_achieved}")
        print(Fore.CYAN + f"  - blocking_dialogs: {state_analysis.blocking_dialogs or 'None'}")
        print(Fore.CYAN + f"  - app_defect_detected: {state_analysis.app_defect_detected}")
        if state_analysis.app_defect_detected:
            print(Fore.RED + f"  - app_defect_reason: {state_analysis.app_defect_reason}")
        if state_analysis.is_stuck:
            print(Fore.RED + f"  - is_stuck: True")
        return state_analysis

    
    async def decide_action(
        self, 
        goal: str, 
        original_plan: list, 
        past_steps: list, 
        state_analysis: StateAnalysis,
        objective_progress: Optional[ObjectiveProgress] = None
    ) -> tuple:
        """ステージ2: Plan/Responseどちらを返すべきか判断（構造化出力）
        
        Args:
            goal: テスト目標
            original_plan: 元の計画
            past_steps: 完了済みステップ
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト（新規追加）
        """
        remaining_steps = max(len(original_plan) - len(past_steps), 0)

        # 目標ステップの進捗情報を構築
        objective_info = ""
        all_objectives_completed = False
        is_last_objective = False
        if objective_progress:
            all_objectives_completed = objective_progress.is_all_objectives_completed()
            completed_count = objective_progress.get_completed_objectives_count()
            total_count = objective_progress.get_total_objectives_count()
            
            # 現在の目標ステップが達成されたら全目標達成かどうかを判定
            remaining_after_current = total_count - completed_count - (1 if state_analysis.current_objective_achieved else 0)
            is_last_objective = remaining_after_current <= 0 and state_analysis.current_objective_achieved
            
            objective_info = f"""
【ユーザー目標ステップの進捗】
完了: {completed_count}/{total_count}
全目標達成: {"Yes" if all_objectives_completed else "No"}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
現在の目標が最後の目標: {"Yes" if is_last_objective else "No"}
"""

        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}
テスト進捗: {state_analysis.test_progress}
検出された問題: {state_analysis.problems_detected or "なし"}
アプリ不具合検出: {"Yes - " + (state_analysis.app_defect_reason or "詳細不明") if state_analysis.app_defect_detected else "No"}
スタック状態: {"Yes" if state_analysis.is_stuck else "No"}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
現在の目標ステップ根拠: {state_analysis.current_objective_evidence}
全体の目標達成: {"Yes" if state_analysis.goal_achieved else "No"}
達成判断理由: {state_analysis.goal_achievement_reason}
"""

        prompt = f"""あなたは次のアクションを厳密に判断するエキスパートです。

【目標】
{goal}
{objective_info}

【状態分析結果】
{state_summary}

【LLM実行計画の進捗】（参考）
計画ステップ総数: {len(original_plan)} / 完了: {len(past_steps)} / 残り: {remaining_steps}

【判断基準（厳格）】
★重要★ 判断基準は「ユーザー目標ステップ」の達成度です。LLM実行計画の進捗ではありません。

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

通常の判断:
2. 現在の目標ステップが未達成 → decision=PLAN
3. 現在の目標ステップが達成済みで、かつ「現在の目標が最後の目標: Yes」の場合 → decision=RESPONSE（テスト成功として報告）
4. 現在の目標ステップが達成済みで、まだ次の目標ステップがある場合 → decision=PLAN
5. 全ての目標ステップが達成済み → decision=RESPONSE（テスト成功として報告）

【出力仕様】
厳格なJSON
"""

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(DecisionResult)
        try:
            if self.token_callback:
                with self.token_callback.track_query():
                    result = await structured_llm.ainvoke(messages)
            else:
                result = await structured_llm.ainvoke(messages)
            
            print(Fore.MAGENTA + f"[MultiStageReplanner.decide_action model: {self.model_name}] Decision: {result.decision}")
            decision_norm = result.decision.strip().upper()
            if decision_norm not in ("PLAN", "RESPONSE"):
                decision_norm = "PLAN"  # 安全側フォールバック
            return decision_norm, result.reason.strip()
        except Exception as e:
            # 構造化出力失敗時は安全側でPLANを返す
            print(Fore.RED + f"Structured Output Error: {e}")
            allure.attach(str(e), name="❌ decide_action: Structured Output Error", attachment_type=allure.attachment_type.TEXT)
            return "PLAN", "構造化出力エラーのためフォールバック"
    
    async def build_plan(
        self,
        goal: str,
        original_plan: list,
        past_steps: list,
        state_analysis: StateAnalysis,
        objective_progress: Optional[ObjectiveProgress] = None,
        locator: str = ""
    ) -> Plan:
        """ステージ3a: 次のPlanを作成
        
        Args:
            goal: テスト目標
            original_plan: 元の計画
            past_steps: 完了済みステップ
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト
            locator: 画面のロケーター情報（ブロッキングダイアログ処理用）
        """
        remaining = original_plan[len(past_steps):]
        total_steps = len(original_plan)
        completed_steps = len(past_steps)
        remaining_count = len(remaining)
        
        # 目標ステップ情報を構築
        objective_info = ""
        current_objective = ""
        remaining_objectives = []
        if objective_progress:
            current_step = objective_progress.get_current_step()
            if current_step:
                current_objective = current_step.description
            
            # 未完了の目標ステップ一覧
            for step in objective_progress.objective_steps:
                if step.status not in ("completed", "skipped"):
                    remaining_objectives.append(f"  - [{step.index}] {step.description}")
            
            objective_info = f"""
【★重要★ ユーザー目標ステップ】（これが達成基準）
残り目標ステップ数: {len(remaining_objectives)}
{chr(10).join(remaining_objectives) if remaining_objectives else "(全目標達成済み)"}

【現在取り組むべき目標】
{current_objective or "(全目標達成済み)"}
"""
        
        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
ブロッキングダイアログ: {state_analysis.blocking_dialogs or "なし"}
テスト進捗: {state_analysis.test_progress}
検出された問題: {state_analysis.problems_detected or "なし"}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
達成判断理由: {state_analysis.goal_achievement_reason}
次のアクション提案: {state_analysis.suggested_next_action or "なし"}
"""
        
        # ロケーター情報セクション（ブロッキングダイアログ処理用）
        locator_section = ""
        if locator and state_analysis.blocking_dialogs:
            locator_section = f"""
【★重要★ 現在の画面ロケーター情報】
ブロッキングダイアログを閉じるために、以下のロケーター情報から適切なボタン（同意、OK、閉じる等）を見つけてください:
{locator}
"""
        
        prompt = f"""
あなたは実行計画を作成するエキスパートです。

【全体の目標】
{goal}
{objective_info}

【現在の状態分析結果】
{state_summary}
{locator_section}
【LLM実行計画の進捗】（参考情報）
計画総ステップ数: {total_steps}
完了済みステップ数: {completed_steps}
残りステップ数: {remaining_count}

残りの候補ステップ:
{remaining}

【ノウハウ】
{self.knowhow}

【★最重要ルール★】
1. 生成するステップは**ユーザー目標ステップを達成するため**のものであること
2. 現在取り組むべき目標「{current_objective or goal}」を達成するための最小限のステップを生成すること
3. 目標ステップの数を超える過剰なステップを生成しないこと
4. 現在の目標が達成済みなら、次の目標に進むステップのみを生成すること

【タスク】
現在の目標ステップを達成するために必要な最適なステップ列を作成してください：

★最優先★ ブロッキング画面の処理:
- ブロッキングダイアログが検出されている場合:
  → 状態分析結果のblocking_dialogsに記載されているresource-idを使って閉じるステップを生成する
  → 例: 「resource-id 'com.example:id/agree_button' をタップして利用規約に同意する」
  → ロケーター情報が提供されている場合は、そこから適切なボタン（同意、OK、閉じる等）を見つけて使用する
- 初期設定画面、プライバシー画面、オンボーディング画面が表示されている場合:
  → まずこれを完了させるステップを生成する
  → 「More」「Next」「Accept」「OK」「Got it」「同意する」などのボタンを押して先に進む
  → 目標の操作対象（例：メニューアイコン）が表示される画面に到達するまで進める

- 現在の画面状態を考慮して最適なステップを構築
- 不要なステップは追加しない（目標達成に直接関係するもののみ）
- 各ステップは具体的で実行可能なこと

【重要】1ステップ=1ツール呼び出しの原則:
各ステップは**1つのツール呼び出し**に対応すること。複数の操作を1ステップにまとめないこと。

◆ ステップの分割例:
- ❌「検索ボックスをタップし、'キーワード'を入力して検索ボタンを押す」
- ✅「検索ボックスをタップする」→「'キーワード'を入力する」→「検索ボタンを押す」

◆ 1ステップの単位:
- タップ操作: 1要素のタップ = 1ステップ
- テキスト入力: 1フィールドへの入力 = 1ステップ（send_keysで文字列全体を入力）
- スクロール: 1回のスクロール = 1ステップ
- 確認: 1つの要素/状態の確認 = 1ステップ

【テキスト入力のルール】（厳守）:
- テキスト入力には必ず send_keys を使用すること
- press_keycode で1文字ずつ入力してはいけない（効率が悪く、キーコード変換エラーが起きやすい）
- press_keycode は Enter キー（keycode 66）や Back キー（keycode 4）などの特殊キーにのみ使用すること
- 正しい例: 「URLバーに 'yahoo.co.jp' を入力する」→「Enter キーを押して確定する」
- 誤った例: 「キーコードを使って1文字ずつ入力する」（禁止）

【厳格ルール】
- アカウント作成は禁止
- 自動ログインは禁止
- 目標ステップと関係ない操作は禁止

出力形式（JSON）:
厳密なJSON形式
"""
        
        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Plan)
        
        if self.token_callback:
            with self.token_callback.track_query():
                plan = await structured_llm.ainvoke(messages)
        else:
            plan = await structured_llm.ainvoke(messages)
        
        print(Fore.MAGENTA + f"[MultiStageReplanner.build_plan model: {self.model_name}] Plan created with {len(plan.steps)} steps")
        return plan
    
    async def build_response(
        self, 
        goal: str, 
        past_steps: list, 
        state_analysis: StateAnalysis,
        objective_progress: Optional[ObjectiveProgress] = None
    ) -> Response:
        """ステージ3b: 完了Responseを作成
        
        Args:
            goal: テスト目標
            past_steps: 完了済みステップ
            state_analysis: analyze_stateからの構造化された状態分析結果
            objective_progress: 目標進捗管理オブジェクト（新規追加）
        """
        completed_count = len(past_steps)
        
        # 完了したステップの一覧を作成
        completed_steps_list = "\n".join(
            f"{i+1}. {step[0]}" for i, step in enumerate(past_steps)
        ) if past_steps else "(なし)"
        
        # 目標ステップの進捗情報
        objective_summary = ""
        if objective_progress:
            objective_list = []
            for step in objective_progress.objective_steps:
                status_icon = "✅" if step.status == "completed" else "❌" if step.status == "failed" else "⏳"
                objective_list.append(f"  {status_icon} {step.description}")
            
            objective_summary = f"""
【ユーザー目標ステップの達成状況】
{chr(10).join(objective_list)}

完了: {objective_progress.get_completed_objectives_count()}/{objective_progress.get_total_objectives_count()}
"""
        
        # StateAnalysisから状態要約を構築
        state_summary = f"""
画面タイプ: {state_analysis.current_screen_type}
画面変化: {state_analysis.screen_changes}
主要要素: {state_analysis.main_elements}
テスト進捗: {state_analysis.test_progress}
現在の目標ステップ達成: {"Yes" if state_analysis.current_objective_achieved else "No"}
全体の目標達成: {"Yes" if state_analysis.goal_achieved else "No"}
達成判断理由: {state_analysis.goal_achievement_reason}
"""
        
        # アプリ不具合情報を追加
        defect_info = ""
        if state_analysis.app_defect_detected:
            defect_info = f"""
【★アプリ不具合検出★】
不具合が検出されました: {state_analysis.app_defect_reason or "詳細不明"}
スタック状態: {"Yes" if state_analysis.is_stuck else "No"}
検出された問題: {state_analysis.problems_detected or "なし"}
"""
        
        prompt = f"""あなたはタスク完了報告を作成するエキスパートです。

【目標】
{goal}
{objective_summary}
{defect_info}

【現在の状態分析結果】
{state_summary}

【完了済み実行ステップ一覧】
{completed_steps_list}

【タスク】
タスクの完了を報告してください。以下を含めること：
1. status: {RESULT_PASS} または {RESULT_FAIL} のいずれかを設定
   - 全ての目標ステップが達成されている場合は {RESULT_PASS}
   - 目標ステップが未達成の場合は {RESULT_FAIL}
   - ★アプリ不具合が検出された場合は必ず {RESULT_FAIL}★
2. reason: 完了理由の詳細（100〜600文字程度）
   - 各目標ステップの達成状況
   - 達成の根拠（ロケーター情報や画面状態）
   - 未達成がある場合はその理由
   - ★アプリ不具合が検出された場合は、その詳細を必ず記載すること★

出力形式:
厳格なJSON形式（status と reason フィールドを持つ）
"""
        
        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Response)
        
        if self.token_callback:
            with self.token_callback.track_query():
                resp = await structured_llm.ainvoke(messages)
        else:
            resp = await structured_llm.ainvoke(messages)
        
        print(Fore.MAGENTA + f"[MultiStageReplanner.build_response model: {self.model_name}] Response created: {resp.status}")
        return resp
