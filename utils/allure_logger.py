"""
Allure logging utilities for SmartestiRoid test framework.

This module provides callback handlers and logging functions for Allure integration.
"""

from typing import Dict, Any
import json
import time
import allure
from colorama import Fore
from langchain_core.callbacks import BaseCallbackHandler

from config import OPENAI_TIMEOUT


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
