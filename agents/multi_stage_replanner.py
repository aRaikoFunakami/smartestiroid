"""
Multi-stage replanner for SmartestiRoid test framework.

This module provides a 3-stage replanning process for mini models.
"""

from typing import List, Dict, Any
from colorama import Fore
from langchain_core.messages import HumanMessage
import allure

from models import Plan, Response, DecisionResult
from config import RESULT_PASS


class MultiStageReplanner:
    """3段階に分けてreplanを実行するクラス（miniモデル用）"""
    
    def __init__(self, llm, knowhow: str):
        self.llm = llm
        self.knowhow = knowhow
        self.model_name = llm.model_name if hasattr(llm, 'model_name') else "unknown"
    
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
したがって、"省略" や "不要" といった語で未実行ステップを評価してはいけません。"省略可能"と判断した場合でも、必ずそのステップを実行しなければならない前提でPLANを返してください。

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
        print(Fore.MAGENTA + f"[MultiStageReplanner.analyze_state model: {self.model_name}] State analysis completed")
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
したがって、"省略" や "不要" といった語で未実行ステップを評価してはいけません。"省略可能"と判断した場合でも、必ずそのステップを実行しなければならない前提でPLANを返してください。

【出力仕様】
厳格なJSON
"""

        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(DecisionResult)
        try:
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
    
    async def build_plan(self, goal: str, original_plan: list, past_steps: list, state_summary: str) -> Plan:
        """ステージ3a: 次のPlanを作成"""
        remaining = original_plan[len(past_steps):]
        
        prompt = f"""
あなたは実行計画を作成するエキスパートです。

目標
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
        print(Fore.MAGENTA + f"[MultiStageReplanner.build_plan model: {self.model_name}] Plan created with {len(plan.steps)} steps")
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
3. 最後の行に必ず {RESULT_PASS} を単独で記載

出力形式:
- テキストでタスク完了の理由と根拠を詳細に記述する
- 初期設定ダイアログ対応や広告ダイアログ対応は不要/逸脱ステップに含めないステップを行った場合は、そのステップの詳細をロケーター情報を含めて保持事項として説明する
- 最後の行に {RESULT_PASS} を追記する
"""
        
        messages = [HumanMessage(content=prompt)]
        structured_llm = self.llm.with_structured_output(Response)
        resp = await structured_llm.ainvoke(messages)
        print(Fore.MAGENTA + f"[MultiStageReplanner.build_response model: {self.model_name}] Response created")
        return resp
