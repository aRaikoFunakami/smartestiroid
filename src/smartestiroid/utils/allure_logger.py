"""
Allure logging utilities for SmartestiRoid test framework.

This module provides callback handlers and logging functions for Allure integration.
"""

from typing import Dict, Any, List, Optional
import json
import time
import allure
from colorama import Fore
from langchain_core.callbacks import BaseCallbackHandler

from ..config import OPENAI_TIMEOUT
from ..progress import ToolCallRecord, StepExecutionRecord, ExecutionProgress, ObjectiveProgress


class AllureToolCallbackHandler(BaseCallbackHandler):
    """Allure にツール呼び出し履歴を記録するコールバックハンドラー
    
    計画ステップとツール呼び出しの関係を追跡し、
    正確な進捗管理を可能にする。
    """
    
    def __init__(self):
        super().__init__()
        self.tool_calls = []
        self.current_step = None
        # 進捗追跡用
        self._execution_progress: Optional[ExecutionProgress] = None
        self._objective_progress: Optional[ObjectiveProgress] = None
        self._current_step_record: Optional[StepExecutionRecord] = None
    
    def set_execution_progress(self, progress: ExecutionProgress) -> None:
        """進捗追跡オブジェクトを設定"""
        self._execution_progress = progress
    
    def set_objective_progress(self, progress: ObjectiveProgress) -> None:
        """目標進捗追跡オブジェクトを設定"""
        self._objective_progress = progress
    
    def start_step(self, step_index: int, step_text: str) -> StepExecutionRecord:
        """新しいステップの実行を開始"""
        record = StepExecutionRecord(
            step_index=step_index,
            step_text=step_text,
            status="in_progress",
            started_at=time.time()
        )
        self._current_step_record = record
        
        if self._execution_progress:
            self._execution_progress.step_records.append(record)
            self._execution_progress.current_step_index = step_index
        
        return record
    
    def complete_step(self, agent_response: str, success: bool = True) -> None:
        """現在のステップを完了"""
        if self._current_step_record:
            self._current_step_record.completed_at = time.time()
            self._current_step_record.agent_response = agent_response
            self._current_step_record.status = "completed" if success else "failed"
            self._current_step_record = None
    
    def get_progress_summary(self) -> str:
        """現在の進捗サマリーを取得
        
        ObjectiveProgress（目標進捗）を優先して表示する。
        ExecutionProgress（実行計画進捗）は補足情報として表示。
        """
        lines = []
        
        # 目標進捗（ObjectiveProgress）を優先表示
        if self._objective_progress:
            lines.append(self._objective_progress.get_progress_summary())
            lines.append("")
        
        # 実行計画進捗（ExecutionProgress）を補足表示
        if self._execution_progress:
            completed = self._execution_progress.get_completed_count()
            total = len(self._execution_progress.original_plan)
            tool_calls = self._execution_progress.get_total_tool_calls()
            lines.append(f"【LLM実行計画】 {completed}/{total} ステップ完了")
            lines.append(f"【ツール呼び出し】 合計{tool_calls}回")
        
        return "\n".join(lines) if lines else "進捗情報なし"
    
    def get_last_tool_name(self) -> Optional[str]:
        """最後に呼び出されたツール名を取得
        
        Returns:
            最後のツール名、なければNone
        """
        if self.tool_calls:
            return self.tool_calls[-1].get("tool_name")
        return None
    
    def get_summary(self) -> str:
        """ツール呼び出し履歴の要約を取得
        
        Returns:
            ツール呼び出しの要約文字列（評価用）
        """
        if not self.tool_calls:
            return "ツール呼び出しなし"
        
        lines = []
        for i, call in enumerate(self.tool_calls, 1):
            tool_name = call.get("tool_name", "Unknown")
            input_str = call.get("input", "")[:200]  # 入力は200文字まで
            output_str = str(call.get("output", ""))[:300] if call.get("output") else "None"
            error = call.get("error")
            
            status = "❌ ERROR" if error else "✅ OK"
            lines.append(f"{i}. {tool_name}: {status}")
            lines.append(f"   Input: {input_str}")
            if error:
                lines.append(f"   Error: {error[:200]}")
            else:
                lines.append(f"   Output: {output_str}")
        
        return "\n".join(lines)
    
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
        
        # 進捗追跡用のレコードも追加
        if self._current_step_record:
            tool_record = ToolCallRecord(
                tool_name=tool_name,
                input=input_display,
                start_time=timestamp
            )
            self._current_step_record.tool_calls.append(tool_record)
        
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
        
        # 進捗追跡用のレコードも更新
        if self._current_step_record and self._current_step_record.tool_calls:
            tool_record = self._current_step_record.tool_calls[-1]
            tool_record.end_time = time.time()
            tool_record.output = str(output) if output is not None else None
    
    def on_tool_error(self, error: BaseException, **kwargs) -> None:
        """ツール呼び出しエラー時"""
        if self.tool_calls:
            tool_call = self.tool_calls[-1]
            tool_call["end_time"] = time.time()
            tool_call["error"] = str(error)
            
            elapsed = tool_call["end_time"] - tool_call["start_time"]
            print(Fore.RED + f"❌ Tool Error: {tool_call['tool_name']} ({elapsed:.2f}s)")
            print(Fore.RED + f"   Error: {str(error)[:200]}...")
        
        # 進捗追跡用のレコードも更新
        if self._current_step_record and self._current_step_record.tool_calls:
            tool_record = self._current_step_record.tool_calls[-1]
            tool_record.end_time = time.time()
            tool_record.error = str(error)
    
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
        
        # 進捗サマリーも保存
        if self._execution_progress:
            allure.attach(
                self.get_progress_summary(),
                name="📊 Execution Progress",
                attachment_type=allure.attachment_type.TEXT,
            )
    
    def clear(self):
        """履歴をクリア（ステップ間で呼び出す）"""
        self.tool_calls = []
        # 注意: _current_step_record と _execution_progress はクリアしない
        # これらはワークフロー全体で保持する必要がある
    
    def reset_progress(self):
        """進捗追跡をリセット（新しいテストケース開始時に呼び出す）"""
        self._execution_progress = None
        self._objective_progress = None
        self._current_step_record = None
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
