"""
テスト失敗レポート生成モジュール

JSONLログから失敗テストを抽出し、LLMを使用して分析、
Markdownレポートを生成します。

使用例:
    from smartestiroid.utils.failure_report_generator import FailureReportGenerator
    
    generator = FailureReportGenerator(
        log_dir=Path("smartestiroid_logs/run_20251205_194626"),
        use_llm=True
    )
    report_path = generator.generate_report()
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

# LangChainインポート（オプショナル）
try:
    from langchain_openai import ChatOpenAI
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False


# ========================================
# Pydantic モデル（LLM Structured Output用）
# ========================================

class FailureAnalysis(BaseModel):
    """LLMが出力する失敗分析（形式固定）"""
    
    failure_category: Literal[
        "APPIUM_CONNECTION_ERROR",    # Appium接続エラー
        "ELEMENT_NOT_FOUND",          # 要素が見つからない
        "VERIFICATION_FAILED",        # 検証失敗（LLM判定）
        "TIMEOUT",                    # タイムアウト
        "LLM_JUDGMENT_ERROR",         # LLM判定ミス
        "APP_CRASH",                  # アプリクラッシュ
        "SESSION_ERROR",              # セッションエラー
        "UNKNOWN"                     # 不明
    ] = Field(description="失敗カテゴリ")
    
    summary: str = Field(description="失敗概要（1文で簡潔に）")
    
    root_causes: List[str] = Field(
        description="技術的な原因（1-3個）",
        min_length=1,
        max_length=3
    )
    
    recommendations: List[str] = Field(
        description="具体的な対処法（優先度順、1-3個）",
        min_length=1,
        max_length=3
    )
    
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        description="分析の確信度"
    )
    
    def to_plaintext(self) -> str:
        """分析結果をプレーンテキスト形式で出力"""
        category_display = CATEGORY_DISPLAY.get(self.failure_category, self.failure_category)
        
        root_causes_text = "\n".join(f"  - {cause}" for cause in self.root_causes)
        recommendations_text = "\n".join(f"  {i}. {rec}" for i, rec in enumerate(self.recommendations, 1))
        
        return f"""---
テスト失敗の原因分析:

カテゴリ: {category_display}

概要:
{self.summary}

推定原因:
{root_causes_text}

推奨アクション:
{recommendations_text}

分析確信度: {self.confidence}
---"""


# カテゴリ表示名
CATEGORY_DISPLAY = {
    "APPIUM_CONNECTION_ERROR": "🔌 Appium接続エラー",
    "ELEMENT_NOT_FOUND": "🔍 要素が見つからない",
    "VERIFICATION_FAILED": "❌ 検証失敗",
    "TIMEOUT": "⏱️ タイムアウト",
    "LLM_JUDGMENT_ERROR": "🤖 LLM判定ミス",
    "APP_CRASH": "💥 アプリクラッシュ",
    "SESSION_ERROR": "🔗 セッションエラー",
    "UNKNOWN": "❓ 不明",
}


# ========================================
# データクラス
# ========================================

@dataclass
class FailedTestInfo:
    """失敗したテストの情報"""
    test_id: str
    title: str
    steps: str
    expected: str
    
    # 失敗情報
    failed_step: Optional[str] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    failure_timestamp: Optional[str] = None
    
    # LLM検証情報
    verification_phase1: Optional[Dict[str, Any]] = None
    verification_phase2: Optional[Dict[str, Any]] = None
    
    # 画面情報
    last_screen_type: Optional[str] = None
    last_screen_xml: Optional[str] = None
    screenshots: List[Dict[str, str]] = field(default_factory=list)
    
    # 進捗情報
    progress_summary: Optional[str] = None
    completed_steps: List[str] = field(default_factory=list)
    
    # ログ行範囲
    log_start_line: int = 0
    log_end_line: int = 0
    
    # LLM分析結果
    analysis: Optional[FailureAnalysis] = None


# ========================================
# メインクラス
# ========================================

class FailureReportGenerator:
    """テスト失敗レポート生成器（LLM分析を使用）"""
    
    def __init__(
        self,
        log_dir: Path,
        model_name: str = "gpt-4.1-mini"
    ):
        """
        Args:
            log_dir: ログディレクトリ（run_YYYYMMDD_HHMMSS）
            model_name: 使用するモデル名
        """
        self.log_dir = Path(log_dir)
        self.model_name = model_name
        
        # JSONLファイルを探す
        jsonl_files = list(self.log_dir.glob("*.jsonl"))
        if not jsonl_files:
            raise FileNotFoundError(f"JSONLファイルが見つかりません: {self.log_dir}")
        self.log_file = jsonl_files[0]
        
        # ログをロード
        self.entries: List[Dict[str, Any]] = []
        self._load_log()
        
        # 全テスト情報を抽出
        self.all_tests: List[Dict[str, Any]] = []
        self._extract_all_tests()
        
        # 失敗テストを抽出
        self.failed_tests: List[FailedTestInfo] = []
        self._extract_failed_tests()
    
    def _load_log(self):
        """ログを読み込む"""
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        entry["_line_num"] = line_num
                        self.entries.append(entry)
                    except json.JSONDecodeError:
                        pass
    
    def _extract_all_tests(self):
        """全テスト情報を抽出
        
        結果の優先順位: skip > fail > pass > unknown
        - SKIP は最終判定として FAIL を上書きできる
        - FAIL は PASS を上書きできる（例: PASS後にエラー発生）
        """
        current_test_id = None
        
        # 結果の優先順位（数値が大きいほど優先）
        RESULT_PRIORITY = {"unknown": 0, "pass": 1, "fail": 2, "skip": 3}
        
        def update_test_result(test_id: str, new_result: str):
            """テスト結果を更新（優先順位が高い場合のみ）"""
            for test in reversed(self.all_tests):
                if test["test_id"] == test_id:
                    current_priority = RESULT_PRIORITY.get(test["result"], 0)
                    new_priority = RESULT_PRIORITY.get(new_result, 0)
                    if new_priority > current_priority:
                        test["result"] = new_result
                    break
        
        for entry in self.entries:
            cat = entry.get("cat", "")
            evt = entry.get("evt", "")
            data = entry.get("data", {}) or {}
            
            # テスト開始
            if cat == "TEST" and evt == "START" and "test_id" in data:
                test_id = data.get("test_id", "")
                # session は除外し、TEST_XXXX 形式のみ対象
                if test_id and test_id.startswith("TEST_"):
                    current_test_id = test_id
                    self.all_tests.append({
                        "test_id": test_id,
                        "title": data.get("title", ""),
                        "result": "unknown"  # 後で更新
                    })
            
            # テスト結果 - COMPLETE イベントで status を確認
            if cat == "TEST" and evt == "COMPLETE" and current_test_id:
                status = data.get("status", "")
                if status == "RESULT_PASS":
                    update_test_result(current_test_id, "pass")
                elif status == "RESULT_SKIP":
                    update_test_result(current_test_id, "skip")
            
            # テスト失敗 - FAIL イベント
            if cat == "TEST" and evt == "FAIL" and current_test_id:
                update_test_result(current_test_id, "fail")
            
            # スキップ - SKIP イベント（従来の方式もサポート）
            if cat == "TEST" and evt == "SKIP" and current_test_id:
                update_test_result(current_test_id, "skip")

    def _extract_failed_tests(self):
        """失敗したテストを抽出"""
        current_test: Optional[FailedTestInfo] = None
        current_test_start_line = 0
        
        for entry in self.entries:
            cat = entry.get("cat", "")
            evt = entry.get("evt", "")
            data = entry.get("data", {}) or {}
            line_num = entry.get("_line_num", 0)
            
            # テスト開始
            if cat == "TEST" and evt == "START" and "test_id" in data:
                if current_test and current_test.error_message:
                    # 前のテストが失敗していたら保存
                    current_test.log_end_line = line_num - 1
                    self.failed_tests.append(current_test)
                
                current_test = FailedTestInfo(
                    test_id=data.get("test_id", ""),
                    title=data.get("title", ""),
                    steps=data.get("steps", ""),
                    expected=data.get("expected", ""),
                    log_start_line=line_num
                )
                current_test_start_line = line_num
            
            if current_test is None:
                continue
            
            # 画面タイプ
            if cat == "SCREEN" and evt == "COMPLETE":
                current_test.last_screen_type = data.get("screen_type")
            
            # スクリーンショット
            if cat == "SCREEN" and evt == "UPDATE" and "image_path" in data:
                current_test.screenshots.append({
                    "path": data.get("image_path", ""),
                    "filename": data.get("image_filename", ""),
                    "label": data.get("label"),
                    "timestamp": entry.get("ts", "")
                })
            
            # XML（LLMプロンプトから抽出）
            if cat == "LLM" and evt == "START":
                user_prompt = data.get("user_prompt", "")
                if "<hierarchy" in user_prompt:
                    # XMLを抽出
                    match = re.search(r'(<hierarchy.*?</hierarchy>)', user_prompt, re.DOTALL)
                    if match:
                        current_test.last_screen_xml = match.group(1)
            
            # 検証結果
            if cat == "LLM" and evt == "VERIFY_RESPONSE":
                phase = data.get("phase")
                if phase == 1:
                    current_test.verification_phase1 = data
                elif phase == 2:
                    current_test.verification_phase2 = data
            
            # 進捗サマリー
            if cat == "OBJECTIVE" and evt == "UPDATE":
                summary = data.get("summary")
                if summary:
                    current_test.progress_summary = summary
            
            # ステップ完了
            if cat == "STEP" and evt == "COMPLETE" and data.get("success"):
                step = data.get("step", "")
                if step:
                    current_test.completed_steps.append(step)
            
            # ステップ失敗
            if cat == "STEP" and evt == "FAIL":
                current_test.failed_step = data.get("step", "")
                # error または reason フィールドからエラーメッセージを取得
                error = data.get("error", "") or data.get("reason", "")
                if error:
                    current_test.error_message = error
                
                    # エラータイプを抽出
                    if "cannot be proxied" in error or "instrumentation process" in error:
                        current_test.error_type = "AppiumConnectionError"
                    elif "InvalidContextError" in error:
                        current_test.error_type = "InvalidContextError"
                    elif "TimeoutError" in error or "timeout" in error.lower():
                        current_test.error_type = "TimeoutError"
                    elif "NoSuchElement" in error or "not found" in error.lower() or "要素が見つから" in error or "存在しな" in error:
                        current_test.error_type = "NoSuchElementError"
                    else:
                        current_test.error_type = "UnknownError"
            
            # テスト失敗
            if cat == "TEST" and evt == "FAIL":
                current_test.failure_timestamp = entry.get("ts", "")
                if not current_test.error_message:
                    # data.error または data.analysis（分析結果）を確認
                    error = data.get("error", "") or data.get("analysis", "")
                    if error and error != "テスト失敗 - 原因分析結果":
                        current_test.error_message = error
            
            # テスト終了（次のテストが始まるか、セッション終了）
            if cat == "SESSION" and evt == "END":
                if current_test and current_test.error_message:
                    current_test.log_end_line = line_num
                    self.failed_tests.append(current_test)
                    current_test = None
        
        # 最後のテスト
        if current_test and current_test.error_message:
            current_test.log_end_line = len(self.entries)
            self.failed_tests.append(current_test)
    
    def _analyze_with_llm(self, test_info: FailedTestInfo) -> Optional[FailureAnalysis]:
        """LLMを使用して失敗を分析"""
        try:
            from langchain_openai import ChatOpenAI
            
            llm = ChatOpenAI(
                model=self.model_name,
                temperature=0,
                timeout=30,
                max_retries=2
            )
            
            # Structured Outputを使用
            structured_llm = llm.with_structured_output(FailureAnalysis)
            
            # プロンプト作成
            prompt = self._build_analysis_prompt(test_info)
            
            # LLM呼び出し
            result = structured_llm.invoke(prompt)
            return result
            
        except Exception as e:
            print(f"⚠️ LLM分析エラー ({test_info.test_id}): {e}")
            return None
    
    def _build_analysis_prompt(self, test_info: FailedTestInfo) -> str:
        """分析用プロンプトを構築"""
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
        
        prompt += f"""
## エラー情報
- **エラータイプ**: {test_info.error_type or "不明"}
- **エラー内容**: {test_info.error_message[:500] if test_info.error_message else "不明"}
"""
        
        if test_info.verification_phase1:
            prompt += f"""
## LLM検証結果（Phase 1）
- success: {test_info.verification_phase1.get("success")}
- reason: {test_info.verification_phase1.get("reason", "")[:300]}
"""
        
        if test_info.verification_phase2:
            prompt += f"""
## LLM検証結果（Phase 2）
- verified: {test_info.verification_phase2.get("verified")}
- confidence: {test_info.verification_phase2.get("confidence")}
- reason: {test_info.verification_phase2.get("reason", "")[:300]}
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
    
    def _fallback_analysis(self, test_info: FailedTestInfo) -> FailureAnalysis:
        """LLMを使用しない場合のフォールバック分析"""
        error = test_info.error_message or ""
        error_lower = error.lower()
        
        # エラーパターンに基づく分類
        if "cannot be proxied" in error or "instrumentation process" in error:
            return FailureAnalysis(
                failure_category="APPIUM_CONNECTION_ERROR",
                summary="Appiumサーバーとの通信が断絶しました",
                root_causes=[
                    "UiAutomator2のinstrumentationプロセスがクラッシュ",
                    "Android端末との接続が不安定"
                ],
                recommendations=[
                    "Android端末/エミュレータを再起動する",
                    "Appiumサーバーを再起動する",
                    "adb devicesで接続状態を確認する"
                ],
                confidence="HIGH"
            )
        elif any(p in error for p in ["NoSuchElement", "要素が見つから", "存在しな", "見つからな", "存在せず", "不在"]) or "not found" in error_lower:
            return FailureAnalysis(
                failure_category="ELEMENT_NOT_FOUND",
                summary="画面上で指定した要素が見つかりませんでした",
                root_causes=[
                    "要素のセレクターが正しくない",
                    "画面遷移が完了していない",
                    "要素が画面外にある"
                ],
                recommendations=[
                    "要素のXPathやresource-idを確認する",
                    "待機時間を増やす",
                    "スクロールで要素を表示する"
                ],
                confidence="MEDIUM"
            )
        elif "timeout" in error_lower or "タイムアウト" in error:
            return FailureAnalysis(
                failure_category="TIMEOUT",
                summary="操作がタイムアウトしました",
                root_causes=["処理に時間がかかりすぎた"],
                recommendations=["タイムアウト値を増やす"],
                confidence="MEDIUM"
            )
        elif any(p in error for p in ["検証失敗", "確認できな", "期待", "判定基準"]):
            return FailureAnalysis(
                failure_category="VERIFICATION_FAILED",
                summary="テスト結果の検証が失敗しました",
                root_causes=[
                    "期待される状態と実際の状態が異なる",
                    "検証条件が厳しすぎる"
                ],
                recommendations=[
                    "期待結果を再確認する",
                    "検証ロジックを見直す"
                ],
                confidence="MEDIUM"
            )
        elif any(p in error for p in ["クラッシュ", "crash", "ANR"]) or "crash" in error_lower:
            return FailureAnalysis(
                failure_category="APP_CRASH",
                summary="アプリがクラッシュしました",
                root_causes=["アプリ内部でエラーが発生"],
                recommendations=[
                    "logcatでクラッシュログを確認する",
                    "アプリ開発者に報告する"
                ],
                confidence="HIGH"
            )
        else:
            return FailureAnalysis(
                failure_category="UNKNOWN",
                summary="テストが失敗しました（詳細はログを確認）",
                root_causes=["詳細なログ確認が必要"],
                recommendations=["詳細ログを確認して原因を特定する"],
                confidence="LOW"
            )
    
    def _analyze_failure_trends(self) -> Optional[str]:
        """LLMを使用して失敗傾向を分析"""
        if not self.failed_tests:
            return None
        
        try:
            from langchain_openai import ChatOpenAI
            
            llm = ChatOpenAI(
                model=self.model_name,
                temperature=0,
                timeout=60,
                max_retries=2
            )
            
            # 失敗テストのサマリーを構築
            failure_summaries = []
            category_counts: Dict[str, int] = {}
            
            for test in self.failed_tests:
                if test.analysis:
                    cat = test.analysis.failure_category
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                    failure_summaries.append(f"- {test.test_id}: {test.analysis.summary}")
            
            # カテゴリ別集計テキスト
            category_text = "\n".join(
                f"- {CATEGORY_DISPLAY.get(cat, cat)}: {count}件"
                for cat, count in sorted(category_counts.items(), key=lambda x: -x[1])
            )
            
            prompt = f"""あなたはモバイルアプリテスト自動化の専門家です。
以下のテスト失敗データを分析し、傾向と特徴を日本語で簡潔にまとめてください。

## テスト実行結果
- テスト総数: {len(self.all_tests)}
- 成功: {sum(1 for t in self.all_tests if t['result'] == 'pass')}
- 失敗: {len(self.failed_tests)}

## 失敗カテゴリ別集計
{category_text}

## 各失敗テストの概要
{chr(10).join(failure_summaries[:20])}  # 最大20件

## 出力形式
以下の観点で分析してください（Markdown形式、各項目2-3文程度）:

### 主な失敗パターン
どのような種類の失敗が多いか、その傾向を説明

### 特徴的な失敗
通常と異なる失敗や、注目すべき失敗があれば記載

### 改善提案
テスト成功率を上げるための具体的な提案（優先度順に2-3個）
"""
            
            response = llm.invoke(prompt)
            return response.content
            
        except Exception as e:
            print(f"⚠️ 傾向分析エラー: {e}")
            return None

    def generate_report(self) -> Path:
        """Markdownレポートを生成"""
        if not self.failed_tests:
            print("✅ 失敗したテストはありません")
            return self._generate_empty_report()
        
        # LLM分析を実行
        print(f"🤖 LLM分析を実行中... ({len(self.failed_tests)}件)")
        for i, test_info in enumerate(self.failed_tests, 1):
            print(f"  [{i}/{len(self.failed_tests)}] {test_info.test_id}...")
            test_info.analysis = self._analyze_with_llm(test_info)
            if test_info.analysis is None:
                test_info.analysis = self._fallback_analysis(test_info)
        
        # レポート生成
        report_content = self._build_report()
        
        # ファイル出力
        report_path = self.log_dir / "failure_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        
        print(f"✅ レポートを生成しました: {report_path}")
        return report_path
    
    def _generate_empty_report(self) -> Path:
        """失敗テストがない場合のレポート"""
        content = f"""# テスト実行レポート

**実行日時**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**ログフォルダ**: `{self.log_dir.name}`

---

## 結果サマリー

✅ **すべてのテストが成功しました**

失敗したテストはありません。
"""
        report_path = self.log_dir / "failure_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
        return report_path
    
    def _build_report(self) -> str:
        """レポート本体を構築"""
        lines = []
        
        # ヘッダー
        run_time = self.log_dir.name.replace("run_", "").replace("_", " ")
        lines.append("# テスト失敗レポート")
        lines.append("")
        lines.append(f"**実行日時**: {run_time}  ")
        lines.append(f"**ログフォルダ**: `{self.log_dir.name}`")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # テスト結果サマリー
        total_tests = len(self.all_tests)
        passed_tests = sum(1 for t in self.all_tests if t["result"] == "pass")
        failed_tests = sum(1 for t in self.all_tests if t["result"] == "fail")
        skipped_tests = sum(1 for t in self.all_tests if t["result"] == "skip")
        unknown_tests = total_tests - passed_tests - failed_tests - skipped_tests
        
        lines.append("## テスト結果サマリー")
        lines.append("")
        lines.append("| 項目 | 値 |")
        lines.append("|------|-----|")
        lines.append(f"| テスト総数 | {total_tests} |")
        lines.append(f"| ✅ 成功 | {passed_tests} |")
        lines.append(f"| ❌ 失敗 | {failed_tests} |")
        if skipped_tests > 0:
            lines.append(f"| ⏭️ スキップ | {skipped_tests} |")
        if unknown_tests > 0:
            lines.append(f"| ❓ 不明 | {unknown_tests} |")
        
        # 成功率を計算
        if total_tests > 0:
            success_rate = (passed_tests / total_tests) * 100
            lines.append(f"| **成功率** | **{success_rate:.1f}%** |")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 失敗カテゴリ別サマリー
        lines.append("## 失敗カテゴリ別サマリー")
        lines.append("")
        
        # カテゴリ別集計
        category_counts: Dict[str, int] = {}
        for test in self.failed_tests:
            if test.analysis:
                cat = test.analysis.failure_category
                category_counts[cat] = category_counts.get(cat, 0) + 1
        
        if category_counts:
            lines.append("| カテゴリ | 件数 |")
            lines.append("|------|-----|")
            for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
                display = CATEGORY_DISPLAY.get(cat, cat)
                lines.append(f"| {display} | {count} |")
            lines.append("")
        else:
            lines.append("失敗テストはありません。")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # LLMによる傾向分析
        if self.failed_tests:
            trend_analysis = self._analyze_failure_trends()
            if trend_analysis:
                lines.append("## 失敗傾向分析")
                lines.append("")
                lines.append(trend_analysis)
                lines.append("")
                lines.append("---")
                lines.append("")
        
        # 各失敗テストの詳細
        lines.append("## 失敗テスト一覧")
        lines.append("")
        
        for test_info in self.failed_tests:
            lines.extend(self._build_test_section(test_info))
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_test_section(self, test_info: FailedTestInfo) -> List[str]:
        """各テストのセクションを構築"""
        lines = []
        analysis = test_info.analysis
        
        # テストヘッダー
        lines.append(f"### {test_info.test_id}: {test_info.title}")
        lines.append("")
        
        # 基本情報テーブル
        lines.append("| 項目 | 内容 |")
        lines.append("|------|------|")
        
        if analysis:
            category_display = CATEGORY_DISPLAY.get(analysis.failure_category, analysis.failure_category)
            lines.append(f"| **結果** | {category_display} |")
        
        if test_info.failure_timestamp:
            time_only = test_info.failure_timestamp[11:19] if len(test_info.failure_timestamp) >= 19 else test_info.failure_timestamp
            lines.append(f"| **失敗時刻** | {time_only} |")
        
        if test_info.failed_step:
            step_display = test_info.failed_step[:50] + "..." if len(test_info.failed_step) > 50 else test_info.failed_step
            lines.append(f"| **失敗ステップ** | {step_display} |")
        
        if analysis:
            lines.append(f"| **信頼度** | {analysis.confidence} |")
        
        lines.append("")
        
        # 失敗概要
        if analysis:
            lines.append("#### 失敗概要")
            lines.append("")
            lines.append(analysis.summary)
            lines.append("")
        
        # 原因詳細
        if analysis and analysis.root_causes:
            lines.append("#### 原因詳細")
            lines.append("")
            for cause in analysis.root_causes:
                lines.append(f"- {cause}")
            lines.append("")
        
        # 推奨対応
        if analysis and analysis.recommendations:
            lines.append("#### 推奨対応")
            lines.append("")
            for i, rec in enumerate(analysis.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")
        
        # 参照ログ
        lines.append("#### 参照ログ")
        lines.append("")
        log_filename = self.log_file.name
        lines.append(f"- [詳細ログ](./{log_filename}) (行{test_info.log_start_line}-{test_info.log_end_line})")
        
        # スクリーンショット
        if test_info.screenshots:
            last_screenshots = test_info.screenshots[-3:]  # 最後の3枚
            images_dir = f"{self.log_file.stem}_images"
            for ss in last_screenshots:
                filename = ss.get("filename", "")
                label = ss.get("label") or "Screenshot"
                lines.append(f"- [{label}](./{images_dir}/{filename})")
        
        lines.append("")
        lines.append("---")
        
        return lines


# ========================================
# コマンドラインインターフェース
# ========================================

def main():
    """コマンドラインエントリポイント"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="テスト失敗レポート生成ツール（LLM分析を使用）"
    )
    parser.add_argument("log_dir", help="ログディレクトリ（run_YYYYMMDD_HHMMSS）")
    parser.add_argument("--model", default="gpt-4.1-mini", help="使用するモデル")
    
    args = parser.parse_args()
    
    try:
        generator = FailureReportGenerator(
            log_dir=Path(args.log_dir),
            model_name=args.model
        )
        
        report_path = generator.generate_report()
        print(f"🔗 file://{report_path.absolute()}")
        
    except FileNotFoundError as e:
        print(f"❌ エラー: {e}")
        return 1
    except Exception as e:
        print(f"❌ 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
