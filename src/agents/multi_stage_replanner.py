"""
Multi-stage replanner for SmartestiRoid test framework.

This module provides a 3-stage replanning process for mini models.
"""

from typing import List, Dict, Any
from colorama import Fore
from langchain_core.messages import HumanMessage
import allure

from models import Plan, Response, DecisionResult
from config import RESULT_PASS, RESULT_FAIL


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
1. **画面の変化と差分分析**  
前ステップからの変更点を、特に重要なUI差分に焦点を当てて記述すること。

2. **テスト進捗**  
現在のテスト状態を定量的または定性的に評価して示すこと。

3. **問題兆候の有無**  
異常挙動・エラー・予期しない遷移の有無を判断し、詳細に記述すること。

4. **画面主要要素の確認と説明**  
現在の画面が何を表示しているかを理解するため、  
主要なUI要素を **画像ベース** 及び **ロケータ（例: XPath, CSS Selector）** によって確認し、  
それぞれの役割や意図を詳細に説明すること。

5. **目標達成の可否**  
テストの目標が達成されているか明確に判定すること。

6. **目標達成可否の理由**  
判断根拠をロケータ情報および実際の画面状況に基づき論理的に記述すること。

7. **ステップ改善案（任意）**  
改善できる操作や検証観点があれば具体的に提案すること。

現在のロケーター情報:
{locator}

画面スクリーンショット（前回の画面と現在の画面):
"""

        content_blocks: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        if previous_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": previous_image_url}})
        if current_image_url:
            content_blocks.append({"type": "image_url", "image_url": {"url": current_image_url}})

        # track_query()でクエリごとのトークン使用量を記録
        with self.token_callback.track_query():
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
- ステップを実行できる状態でない場合は、現在の状態を考慮して最適なステップを再構築してください
- 可能なら既存未完了ステップを再利用し重複を避けること
- ステップを選択した根拠（進捗・画面要素・残り目標）を簡潔に言語化すること
- 現在の状態を考慮すること
- 不要なステップは追加しない
- 各ステップは具体的で実行可能なこと
- 目標の手順を踏まえた、目標を達成するための全てのステップ列がふくまれていること

厳格ルール:
- アカウント作成は禁止
- 自動ログインは禁止

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
1. status: {RESULT_PASS} または {RESULT_FAIL} のいずれかを設定
2. reason: 完了理由の詳細をロケーター情報や画面状態に基づいて説明（100〜600文字程度）
   - 目標が達成されていることの根拠
   - 確認した要素の説明
   - 実行した手順の対応

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
