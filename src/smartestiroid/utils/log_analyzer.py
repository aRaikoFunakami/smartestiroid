"""
SmartestiRoid ログ解析ツール

JSONLログファイルを解析し、以下の機能を提供します：
1. 基本統計 - ログ件数、LLM呼び出し回数、エラー数
2. LLMプロンプト抽出 - プロンプト内容を別ファイルに出力
3. 失敗分析用サマリー - LLMに渡しやすい形式で出力
4. タイムライン表示 - 時系列でのイベント一覧

使用例:
    # コマンドラインから実行
    python -m smartestiroid.utils.log_analyzer logs/smartestiroid_*.jsonl
    
    # Pythonから使用
    from smartestiroid.utils.log_analyzer import LogAnalyzer
    analyzer = LogAnalyzer("logs/smartestiroid_session_xxx.jsonl")
    analyzer.print_summary()
    analyzer.export_for_llm_analysis("output.txt")
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LogEntry:
    """ログエントリを表すデータクラス"""
    timestamp: str
    level: str
    category: str
    event: str
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    
    @classmethod
    def from_json(cls, json_str: str) -> "LogEntry":
        """JSON文字列からLogEntryを作成"""
        obj = json.loads(json_str)
        return cls(
            timestamp=obj.get("ts", ""),
            level=obj.get("lvl", "INFO"),
            category=obj.get("cat", "UNKNOWN"),
            event=obj.get("evt", "UNKNOWN"),
            message=obj.get("msg"),
            data=obj.get("data")
        )
    
    @property
    def time_only(self) -> str:
        """時刻部分のみを返す (HH:MM:SS)"""
        if len(self.timestamp) >= 19:
            return self.timestamp[11:19]
        return self.timestamp


@dataclass
class AnalysisResult:
    """解析結果を格納するデータクラス"""
    log_file: Path
    total_logs: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    errors: int = 0
    warnings: int = 0
    inconsistencies: int = 0
    screenshots: int = 0  # スクリーンショット数
    
    # 詳細データ
    llm_prompts: List[Dict[str, Any]] = field(default_factory=list)
    error_entries: List[LogEntry] = field(default_factory=list)
    warning_entries: List[LogEntry] = field(default_factory=list)
    timeline: List[LogEntry] = field(default_factory=list)
    screenshot_entries: List[Dict[str, Any]] = field(default_factory=list)  # スクリーンショット情報
    
    # テスト情報
    test_id: Optional[str] = None
    test_title: Optional[str] = None
    test_result: Optional[str] = None  # PASSED, FAILED, SKIPPED
    
    # 時間情報
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    
    # 画像ディレクトリ
    images_dir: Optional[Path] = None


class LogAnalyzer:
    """SmartestiRoid ログ解析クラス"""
    
    def __init__(self, log_file: str | Path):
        """
        Args:
            log_file: JSONLログファイルのパス
        """
        self.log_file = Path(log_file)
        self.entries: List[LogEntry] = []
        self.result: Optional[AnalysisResult] = None
        
        self._load_log()
        self._analyze()
    
    def _load_log(self):
        """ログファイルを読み込む"""
        if not self.log_file.exists():
            raise FileNotFoundError(f"ログファイルが見つかりません: {self.log_file}")
        
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = LogEntry.from_json(line)
                        self.entries.append(entry)
                    except json.JSONDecodeError as e:
                        print(f"警告: JSON解析エラー: {e}")
    
    def _analyze(self):
        """ログを解析"""
        self.result = AnalysisResult(
            log_file=self.log_file,
            total_logs=len(self.entries),
            timeline=self.entries
        )
        
        # 画像ディレクトリを推定
        images_dir = self.log_file.parent / f"{self.log_file.stem}_images"
        if images_dir.exists():
            self.result.images_dir = images_dir
        
        for entry in self.entries:
            # LLM呼び出し
            if entry.category == "LLM" and entry.event == "START":
                self.result.llm_calls += 1
                if entry.data and isinstance(entry.data, dict):
                    prompt = entry.data.get("prompt") or entry.data.get("system_prompt") or ""
                    self.result.llm_prompts.append({
                        "timestamp": entry.time_only,
                        "method": entry.data.get("method", "unknown"),
                        "model": entry.data.get("model", "unknown"),
                        "prompt": prompt,
                        "prompt_length": len(str(prompt))
                    })
            
            # ツール呼び出し
            if entry.category == "TOOL":
                self.result.tool_calls += 1
            
            # スクリーンショット
            if entry.category == "SCREEN" and entry.data and isinstance(entry.data, dict):
                if "image_path" in entry.data:
                    self.result.screenshots += 1
                    self.result.screenshot_entries.append({
                        "timestamp": entry.time_only,
                        "image_path": entry.data.get("image_path"),
                        "image_filename": entry.data.get("image_filename"),
                        "label": entry.data.get("label"),
                    })
            
            # エラー
            if entry.level == "ERROR":
                self.result.errors += 1
                self.result.error_entries.append(entry)
            
            # 警告
            if entry.level == "WARN":
                self.result.warnings += 1
                self.result.warning_entries.append(entry)
            
            # 画面不整合
            if "不整合" in str(entry.event) or "INCONSISTENCY" in str(entry.event):
                self.result.inconsistencies += 1
            
            # テスト情報
            if entry.category == "TEST" and entry.event == "START":
                if entry.data:
                    self.result.test_id = entry.data.get("test_id")
                    self.result.test_title = entry.data.get("title")
                if not self.result.start_time:
                    self.result.start_time = entry.timestamp
            
            if entry.category == "TEST" and entry.event == "END":
                if entry.data:
                    self.result.test_result = entry.data.get("status")
                self.result.end_time = entry.timestamp
            
            # セッション終了からテスト結果を取得
            if entry.category == "SESSION" and entry.event == "END":
                self.result.end_time = entry.timestamp
    
    def print_summary(self):
        """サマリーをコンソールに出力"""
        r = self.result
        
        print("=" * 60)
        print("📊 SmartestiRoid ログ解析結果")
        print("=" * 60)
        
        print(f"\n📁 ログファイル: {r.log_file}")
        print(f"🔗 file://{r.log_file.absolute()}")
        
        print(f"""
📈 統計情報:
─────────────────────────────
総ログ数:        {r.total_logs:>5} 件
LLM呼び出し:     {r.llm_calls:>5} 回
ツール呼び出し:  {r.tool_calls:>5} 回
エラー:          {r.errors:>5} 件
警告:            {r.warnings:>5} 件
画面不整合検出:  {r.inconsistencies:>5} 回
─────────────────────────────
""")
        
        if r.test_id:
            print(f"🧪 テスト情報:")
            print(f"   ID: {r.test_id}")
            print(f"   タイトル: {r.test_title}")
            print(f"   結果: {r.test_result or '不明'}")
            print()
        
        print("🤖 LLMプロンプト一覧:")
        for i, p in enumerate(r.llm_prompts, 1):
            print(f"  {i}. [{p['timestamp']}] {p['method']:<35} ({p['prompt_length']:,} chars)")
        
        if r.error_entries:
            print(f"\n❌ エラー ({len(r.error_entries)}件):")
            for e in r.error_entries:
                msg = e.message or str(e.data) if e.data else "(メッセージなし)"
                if len(msg) > 70:
                    msg = msg[:67] + "..."
                print(f"  [{e.time_only}] {msg}")
        
        if r.inconsistencies > 0:
            print(f"\n⚠️ 画面不整合イベント ({r.inconsistencies}件):")
            for e in r.timeline:
                if "不整合" in str(e.event) or "INCONSISTENCY" in str(e.event):
                    print(f"  [{e.time_only}] {e.event}")
        
        if r.screenshot_entries:
            print(f"\n📷 スクリーンショット ({len(r.screenshot_entries)}枚):")
            for s in r.screenshot_entries[:10]:  # 最初の10枚のみ表示
                path = s.get('image_path') or s.get('image_filename', '')
                print(f"  [{s['timestamp']}] {path}")
            if len(r.screenshot_entries) > 10:
                print(f"  ... 他 {len(r.screenshot_entries) - 10} 枚")
        
        print("\n" + "=" * 60)
    
    def export_for_llm_analysis(self, output_file: Optional[str | Path] = None) -> str:
        """LLM解析用のテキストファイルを出力
        
        Args:
            output_file: 出力ファイルパス（省略時はログファイル名_analysis.txt）
        
        Returns:
            出力内容（文字列）
        """
        r = self.result
        
        lines = []
        lines.append("# SmartestiRoid テスト実行ログ解析用データ")
        lines.append("")
        lines.append(f"元ログファイル: {r.log_file}")
        lines.append(f"ファイルリンク: file://{r.log_file.absolute()}")
        lines.append("")
        
        # 統計サマリー
        lines.append("## 統計サマリー")
        lines.append(f"- 総ログ数: {r.total_logs}")
        lines.append(f"- LLM呼び出し: {r.llm_calls}回")
        lines.append(f"- ツール呼び出し: {r.tool_calls}回")
        lines.append(f"- エラー: {r.errors}件")
        lines.append(f"- 警告: {r.warnings}件")
        lines.append(f"- 画面不整合: {r.inconsistencies}件")
        lines.append("")
        
        # テスト情報
        if r.test_id:
            lines.append("## テスト情報")
            lines.append(f"- テストID: {r.test_id}")
            lines.append(f"- タイトル: {r.test_title}")
            lines.append(f"- 結果: {r.test_result or '不明'}")
            lines.append("")
        
        # タイムライン（簡略版）
        lines.append("## イベントタイムライン")
        for e in r.timeline:
            msg = e.message or ""
            if len(msg) > 80:
                msg = msg[:77] + "..."
            lines.append(f"[{e.time_only}] [{e.category}] [{e.event}] {msg}")
        lines.append("")
        
        # LLMプロンプト
        lines.append("## LLMプロンプト詳細")
        for i, p in enumerate(r.llm_prompts, 1):
            lines.append(f"\n### {i}. {p['method']} ({p['timestamp']})")
            lines.append(f"モデル: {p['model']}")
            lines.append(f"文字数: {p['prompt_length']:,}")
            lines.append("```")
            # プロンプトが長すぎる場合は切り詰め
            prompt_text = str(p['prompt'])
            if len(prompt_text) > 2000:
                prompt_text = prompt_text[:2000] + "\n... (truncated)"
            lines.append(prompt_text)
            lines.append("```")
        lines.append("")
        
        # エラー詳細
        if r.error_entries:
            lines.append("## エラー詳細")
            for e in r.error_entries:
                lines.append(f"\n### [{e.time_only}] {e.category}")
                lines.append(f"イベント: {e.event}")
                if e.message:
                    lines.append(f"メッセージ: {e.message}")
                if e.data:
                    lines.append(f"データ: {json.dumps(e.data, ensure_ascii=False, indent=2)}")
        
        # スクリーンショット情報
        if r.screenshot_entries:
            lines.append("")
            lines.append("## スクリーンショット")
            lines.append(f"保存枚数: {len(r.screenshot_entries)}枚")
            for s in r.screenshot_entries:
                path = s.get('image_path') or s.get('image_filename', '')
                lines.append(f"- [{s['timestamp']}] {path}")
        
        content = "\n".join(lines)
        
        # ファイル出力
        if output_file is None:
            output_file = r.log_file.parent / f"{r.log_file.stem}_analysis.txt"
        
        output_path = Path(output_file)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"✅ LLM解析用ファイルを出力: {output_path}")
        print(f"🔗 file://{output_path.absolute()}")
        
        return content
    
    def export_prompts(self, output_dir: Optional[str | Path] = None) -> List[Path]:
        """LLMプロンプトを個別ファイルに出力
        
        Args:
            output_dir: 出力ディレクトリ（省略時はログファイルと同じディレクトリ）
        
        Returns:
            出力したファイルパスのリスト
        """
        r = self.result
        
        if output_dir is None:
            output_dir = r.log_file.parent / f"{r.log_file.stem}_prompts"
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        output_files = []
        for i, p in enumerate(r.llm_prompts, 1):
            filename = f"{i:02d}_{p['method']}.txt"
            filepath = output_path / filename
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# {p['method']}\n")
                f.write(f"# Timestamp: {p['timestamp']}\n")
                f.write(f"# Model: {p['model']}\n")
                f.write(f"# Length: {p['prompt_length']:,} chars\n")
                f.write("\n")
                f.write(str(p['prompt']))
            
            output_files.append(filepath)
        
        print(f"✅ {len(output_files)}個のプロンプトファイルを出力: {output_path}/")
        print(f"🔗 file://{output_path.absolute()}")
        
        return output_files
    
    def get_failure_analysis_prompt(self) -> str:
        """テスト失敗分析用のLLMプロンプトを生成"""
        r = self.result
        
        prompt = f"""以下のSmartestiRoidテスト実行ログを解析し、失敗原因を特定してください。

## テスト情報
- テストID: {r.test_id}
- タイトル: {r.test_title}
- 結果: {r.test_result or '不明'}
- LLM呼び出し回数: {r.llm_calls}
- エラー数: {r.errors}
- 画面不整合検出: {r.inconsistencies}回

## イベントタイムライン
"""
        for e in r.timeline:
            msg = e.message or ""
            if len(msg) > 100:
                msg = msg[:97] + "..."
            prompt += f"[{e.time_only}] [{e.level}] [{e.category}] {msg}\n"
        
        if r.error_entries:
            prompt += "\n## エラー詳細\n"
            for e in r.error_entries:
                prompt += f"\n### [{e.time_only}]\n"
                prompt += f"カテゴリ: {e.category}\n"
                prompt += f"イベント: {e.event}\n"
                if e.message:
                    prompt += f"メッセージ: {e.message}\n"
                if e.data:
                    prompt += f"データ: {json.dumps(e.data, ensure_ascii=False)}\n"
        
        prompt += """
## 分析タスク
1. テストが失敗した直接的な原因を特定してください
2. 根本原因（テストケース、アプリ、フレームワークのいずれに問題があるか）を推定してください
3. 改善のための具体的なアクションを提案してください
"""
        
        return prompt


def main():
    """コマンドラインエントリポイント"""
    parser = argparse.ArgumentParser(
        description="SmartestiRoid ログ解析ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # サマリー表示
  python -m smartestiroid.utils.log_analyzer logs/smartestiroid_*.jsonl
  
  # LLM解析用ファイル出力
  python -m smartestiroid.utils.log_analyzer logs/smartestiroid_*.jsonl --export
  
  # プロンプト抽出
  python -m smartestiroid.utils.log_analyzer logs/smartestiroid_*.jsonl --prompts
"""
    )
    
    parser.add_argument("log_file", help="解析するJSONLログファイル")
    parser.add_argument("--export", "-e", action="store_true",
                        help="LLM解析用テキストファイルを出力")
    parser.add_argument("--prompts", "-p", action="store_true",
                        help="LLMプロンプトを個別ファイルに出力")
    parser.add_argument("--failure-prompt", "-f", action="store_true",
                        help="失敗分析用プロンプトを表示")
    parser.add_argument("--output", "-o", help="出力ファイル/ディレクトリ")
    
    args = parser.parse_args()
    
    try:
        analyzer = LogAnalyzer(args.log_file)
        
        # サマリー表示（常に実行）
        analyzer.print_summary()
        
        # オプション処理
        if args.export:
            analyzer.export_for_llm_analysis(args.output)
        
        if args.prompts:
            analyzer.export_prompts(args.output)
        
        if args.failure_prompt:
            print("\n" + "=" * 60)
            print("🤖 失敗分析用LLMプロンプト")
            print("=" * 60)
            print(analyzer.get_failure_analysis_prompt())
    
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
