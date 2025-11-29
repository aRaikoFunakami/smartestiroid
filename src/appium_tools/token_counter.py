"""
Token counting and cost calculation functionality using tiktoken
OpenAI APIのトークン数計算と費用計算機能
"""
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager
from langchain_core.callbacks.base import BaseCallbackHandler


class OpenAIPricingCalculator:
    """OpenAI APIの料金計算クラス"""
    
    # OpenAI pricing (USD per 1K tokens) - 2025年11月24日時点の最新料金
    # https://platform.openai.com/docs/pricing
    PRICING = {
        # Latest GPT-5 series (最新モデル)
        "gpt-5.1": {
            "input": 0.00125,  # $1.25 / 1M tokens
            "cached": 0.000125,  # $0.125 / 1M tokens (10%)
            "output": 0.010,   # $10.00 / 1M tokens
        },
        "gpt-5": {
            "input": 0.00125,  # $1.25 / 1M tokens
            "cached": 0.000125,  # $0.125 / 1M tokens (10%)
            "output": 0.010,   # $10.00 / 1M tokens
        },
        "gpt-5-mini": {
            "input": 0.00025,  # $0.25 / 1M tokens
            "cached": 0.000025,  # $0.025 / 1M tokens (10%)
            "output": 0.002,   # $2.00 / 1M tokens
        },
        "gpt-5-nano": {
            "input": 0.00005,  # $0.05 / 1M tokens
            "cached": 0.000005,  # $0.005 / 1M tokens (10%)
            "output": 0.0004,  # $0.40 / 1M tokens
        },
        "gpt-5.1-chat-latest": {
            "input": 0.00125,  # $1.25 / 1M tokens
            "cached": 0.000125,  # $0.125 / 1M tokens (10%)
            "output": 0.010,   # $10.00 / 1M tokens
        },
        "gpt-5-chat-latest": {
            "input": 0.00125,  # $1.25 / 1M tokens
            "cached": 0.000125,  # $0.125 / 1M tokens (10%)
            "output": 0.010,   # $10.00 / 1M tokens
        },
        "gpt-5.1-codex": {
            "input": 0.00125,  # $1.25 / 1M tokens
            "cached": 0.000125,  # $0.125 / 1M tokens (10%)
            "output": 0.010,   # $10.00 / 1M tokens
        },
        "gpt-5-codex": {
            "input": 0.00125,  # $1.25 / 1M tokens
            "cached": 0.000125,  # $0.125 / 1M tokens (10%)
            "output": 0.010,   # $10.00 / 1M tokens
        },
        "gpt-5-pro": {
            "input": 0.015,    # $15.00 / 1M tokens
            "cached": 0.015,   # キャッシュなし
            "output": 0.120,   # $120.00 / 1M tokens
        },
        
        # GPT-4.1 series (新しいモデル)
        "gpt-4.1": {
            "input": 0.002,    # $2.00 / 1M tokens
            "cached": 0.0005,  # $0.50 / 1M tokens (25%)
            "output": 0.008,   # $8.00 / 1M tokens
        },
        "gpt-4.1-mini": {
            "input": 0.0004,   # $0.40 / 1M tokens
            "cached": 0.0001,  # $0.10 / 1M tokens (25%)
            "output": 0.0016,  # $1.60 / 1M tokens
        },
        "gpt-4.1-nano": {
            "input": 0.0001,   # $0.10 / 1M tokens
            "cached": 0.000025,  # $0.025 / 1M tokens (25%)
            "output": 0.0004,  # $0.40 / 1M tokens
        },
        
        # O-series models (推論モデル)
        "o1": {
            "input": 0.015,    # $15.00 / 1M tokens
            "cached": 0.0075,  # $7.50 / 1M tokens (50%)
            "output": 0.060,   # $60.00 / 1M tokens
        },
        "o1-pro": {
            "input": 0.150,    # $150.00 / 1M tokens
            "cached": 0.150,   # キャッシュなし
            "output": 0.600,   # $600.00 / 1M tokens
        },
        "o3": {
            "input": 0.002,    # $2.00 / 1M tokens
            "cached": 0.0005,  # $0.50 / 1M tokens (25%)
            "output": 0.008,   # $8.00 / 1M tokens
        },
        "o3-pro": {
            "input": 0.020,    # $20.00 / 1M tokens
            "cached": 0.020,   # キャッシュなし
            "output": 0.080,   # $80.00 / 1M tokens
        },
        "o3-deep-research": {
            "input": 0.010,    # $10.00 / 1M tokens
            "cached": 0.0025,  # $2.50 / 1M tokens (25%)
            "output": 0.040,   # $40.00 / 1M tokens
        },
        "o4-mini": {
            "input": 0.0011,   # $1.10 / 1M tokens
            "cached": 0.000275,  # $0.275 / 1M tokens (25%)
            "output": 0.0044,  # $4.40 / 1M tokens
        },
        "o4-mini-deep-research": {
            "input": 0.002,    # $2.00 / 1M tokens
            "cached": 0.0005,  # $0.50 / 1M tokens (25%)
            "output": 0.008,   # $8.00 / 1M tokens
        },
        "o3-mini": {
            "input": 0.0011,   # $1.10 / 1M tokens
            "cached": 0.00055,  # $0.55 / 1M tokens (50%)
            "output": 0.0044,  # $4.40 / 1M tokens
        },
        "o1-mini": {
            "input": 0.0011,   # $1.10 / 1M tokens
            "cached": 0.00055,  # $0.55 / 1M tokens (50%)
            "output": 0.0044,  # $4.40 / 1M tokens
        },
        
        # GPT-4o models (現行モデル)
        "gpt-4o": {
            "input": 0.0025,   # $2.50 / 1M tokens
            "cached": 0.00125,  # $1.25 / 1M tokens (50%)
            "output": 0.010,   # $10.00 / 1M tokens
        },
        "gpt-4o-mini": {
            "input": 0.000150, # $0.15 / 1M tokens
            "cached": 0.000075, # $0.075 / 1M tokens (50%)
            "output": 0.000600, # $0.60 / 1M tokens
        },
        "gpt-4o-2024-05-13": {
            "input": 0.005,    # $5.00 / 1M tokens
            "cached": 0.005,   # キャッシュなし
            "output": 0.015,   # $15.00 / 1M tokens
        },
        
        # Realtime models
        "gpt-realtime": {
            "input": 0.004,    # $4.00 / 1M tokens
            "cached": 0.0004,  # $0.40 / 1M tokens (10%)
            "output": 0.016,   # $16.00 / 1M tokens
        },
        "gpt-realtime-mini": {
            "input": 0.0006,   # $0.60 / 1M tokens
            "cached": 0.00006,  # $0.06 / 1M tokens (10%)
            "output": 0.0024,  # $2.40 / 1M tokens
        },
        
        # Legacy models for backward compatibility
        "gpt-4": {
            "input": 0.03,     # $30.00 / 1M tokens
            "cached": 0.03,    # キャッシュなし
            "output": 0.06,    # $60.00 / 1M tokens
        },
        "gpt-4-32k": {
            "input": 0.06,     # $60.00 / 1M tokens
            "cached": 0.06,    # キャッシュなし
            "output": 0.12,    # $120.00 / 1M tokens
        },
        "gpt-4-turbo": {
            "input": 0.01,     # $10.00 / 1M tokens
            "cached": 0.01,    # キャッシュなし
            "output": 0.03,    # $30.00 / 1M tokens
        },
        "gpt-3.5-turbo": {
            "input": 0.0005,   # $0.50 / 1M tokens
            "cached": 0.0005,  # キャッシュなし
            "output": 0.0015,  # $1.50 / 1M tokens
        },
        "gpt-3.5-turbo-16k": {
            "input": 0.003,    # $3.00 / 1M tokens
            "cached": 0.003,   # キャッシュなし
            "output": 0.004,   # $4.00 / 1M tokens
        },
        
        # Fallback for unknown models - use gpt-4.1-mini pricing (cost-effective)
        "default": {
            "input": 0.0004,
            "cached": 0.0001,
            "output": 0.0016,
        }
    }
    
    @classmethod
    def calculate_cost(cls, model_name: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """
        トークン数から費用を計算する
        
        Args:
            model_name: OpenAIモデル名
            input_tokens: 入力トークン数
            output_tokens: 出力トークン数
            
        Returns:
            Dict containing input_cost, output_cost, total_cost in USD
        """
        # モデル名を正規化（バージョン番号等を除去）
        normalized_model = cls._normalize_model_name(model_name)
        
        # 料金情報を取得（未知のモデルはdefaultを使用）
        pricing = cls.PRICING.get(normalized_model, cls.PRICING["default"])
        
        # 費用計算（1K tokens単位での料金なので、1000で割る）
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        total_cost = input_cost + output_cost
        
        return {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total_cost, 6)
        }
    
    @classmethod
    def _normalize_model_name(cls, model_name: str) -> str:
        """
        モデル名を正規化して料金表のキーと一致させる
        """
        model_lower = model_name.lower().strip()
        
        # Exact matches first
        if model_lower in cls.PRICING:
            return model_lower
        
        # Pattern matching for versioned models (最新モデルから順番にチェック)
        # GPT-5 series
        if "gpt-5-pro" in model_lower:
            return "gpt-5-pro"
        elif "gpt-5-nano" in model_lower:
            return "gpt-5-nano"
        elif "gpt-5-mini" in model_lower:
            return "gpt-5-mini"
        elif "gpt-5-chat-latest" in model_lower:
            return "gpt-5-chat-latest"
        elif "gpt-5-codex" in model_lower:
            return "gpt-5-codex"
        elif "gpt-5" in model_lower:
            return "gpt-5"
        
        # GPT-4.1 series
        elif "gpt-4.1-nano" in model_lower:
            return "gpt-4.1-nano"
        elif "gpt-4.1-mini" in model_lower:
            return "gpt-4.1-mini"
        elif "gpt-4.1" in model_lower:
            return "gpt-4.1"
        
        # O-series models
        elif "o4-mini-deep-research" in model_lower:
            return "o4-mini-deep-research"
        elif "o4-mini" in model_lower:
            return "o4-mini"
        elif "o3-deep-research" in model_lower:
            return "o3-deep-research"
        elif "o3-pro" in model_lower:
            return "o3-pro"
        elif "o3-mini" in model_lower:
            return "o3-mini"
        elif "o3" in model_lower:
            return "o3"
        elif "o1-pro" in model_lower:
            return "o1-pro"
        elif "o1-mini" in model_lower:
            return "o1-mini"
        elif "o1" in model_lower:
            return "o1"
        
        # GPT-4o series
        elif "gpt-4o-mini" in model_lower:
            return "gpt-4o-mini"
        elif "gpt-4o-2024-05-13" in model_lower:
            return "gpt-4o-2024-05-13"
        elif "gpt-4o" in model_lower:
            return "gpt-4o"
        
        # Realtime models
        elif "gpt-realtime-mini" in model_lower:
            return "gpt-realtime-mini"
        elif "gpt-realtime" in model_lower:
            return "gpt-realtime"
        
        # Legacy GPT-4 models
        elif "gpt-4-turbo" in model_lower:
            return "gpt-4-turbo"
        elif "gpt-4-32k" in model_lower:
            return "gpt-4-32k"
        elif "gpt-4" in model_lower:
            return "gpt-4"
        
        # GPT-3.5 models
        elif "gpt-3.5-turbo-16k" in model_lower:
            return "gpt-3.5-turbo-16k"
        elif "gpt-3.5-turbo" in model_lower:
            return "gpt-3.5-turbo"
        
        else:
            return "default"


class TiktokenCountCallback(BaseCallbackHandler):
    """
    LangChain callback to count tokens using tiktoken
    tiktoken を使用してトークン数を計算するLangChainコールバック
    
    各ainvoke呼び出しごとの詳細な履歴を保存し、後から取り出せます。
    
    グローバル統計機能:
    - 複数のセッション（appium_driverの起動）をまたいだ累積統計を保持
    - reset_counters()を呼んでも、グローバル統計は保持される
    - save_session_to_global()で現在のセッションをグローバル履歴に追加
    """
    
    # クラス変数: 全インスタンス・全セッションを通じた累積履歴
    _global_history: List[Dict[str, Any]] = []
    
    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        """
        Initialize the callback with the specified model
        
        Args:
            model: OpenAI model name for token encoding
        """
        self.model = model
        self.input_tokens = 0
        self.cached_tokens = 0  # キャッシュヒットしたトークン数
        self.output_tokens = 0
        self.pricing_calculator = OpenAIPricingCalculator()
        
        # ainvokeごとの履歴を保存するリスト（セッション単位）
        self.invocation_history: List[Dict[str, Any]] = []
        self._current_invocation_id = 0
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        """LLM開始時に呼び出される - 新しいinvocationの開始を記録"""
        self._current_invocation_id += 1
        self._current_invocation_start_time = __import__('time').time()
    
    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """ストリーミング時に呼び出される（何もしない）"""
        pass
    
    def on_llm_end(self, response, **kwargs: Any) -> None:
        """
        Called when LLM completes - count tokens from actual API response
        LLM完了時に呼び出され、実際のAPIレスポンスからトークン数を取得し、履歴に記録
        """
        if not (hasattr(response, 'llm_output') and response.llm_output):
            raise ValueError("APIレスポンスにllm_outputが含まれていません")
        
        token_usage = response.llm_output.get('token_usage')
        if not token_usage:
            raise ValueError("APIレスポンスにtoken_usageが含まれていません")
        
        # OpenAI APIの実際の使用量を使用
        prompt_tokens = token_usage.get('prompt_tokens', 0)
        completion_tokens = token_usage.get('completion_tokens', 0)
        
        # キャッシュされたトークンを取得（50%割引適用）
        prompt_details = token_usage.get('prompt_tokens_details', {})
        cached_tokens = prompt_details.get('cached_tokens', 0)
        
        # 通常トークンとキャッシュトークンを分けて記録
        self.input_tokens += prompt_tokens
        self.cached_tokens = getattr(self, 'cached_tokens', 0) + cached_tokens
        self.output_tokens += completion_tokens
        
        # このinvocationの費用を計算
        invocation_cost = self._calculate_invocation_cost(
            prompt_tokens, cached_tokens, completion_tokens
        )
        
        # 履歴に記録
        elapsed_time = __import__('time').time() - getattr(self, '_current_invocation_start_time', __import__('time').time())
        invocation_record = {
            "invocation_id": self._current_invocation_id,
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed_time, 2),
            "model": self.model,
            "input_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "input_cost_usd": invocation_cost["input_cost"],
            "output_cost_usd": invocation_cost["output_cost"],
            "cached_cost_usd": invocation_cost["cached_cost"],
            "total_cost_usd": invocation_cost["total_cost"],
        }
        self.invocation_history.append(invocation_record)
    
    def _calculate_invocation_cost(self, input_tokens: int, cached_tokens: int, output_tokens: int) -> Dict[str, float]:
        """
        単一invocationの費用を計算
        """
        normalized_model = self.pricing_calculator._normalize_model_name(self.model)
        pricing = self.pricing_calculator.PRICING.get(normalized_model, self.pricing_calculator.PRICING["default"])
        
        # 通常の入力トークン（キャッシュされていない部分）
        non_cached_tokens = input_tokens - cached_tokens
        
        # 費用計算
        non_cached_cost = (non_cached_tokens / 1000) * pricing["input"]
        cached_cost = (cached_tokens / 1000) * pricing["cached"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        
        input_cost = non_cached_cost + cached_cost
        total_cost = input_cost + output_cost
        
        return {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "cached_cost": round(cached_cost, 6),
            "total_cost": round(total_cost, 6),
        }
    
    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)"""
        return self.input_tokens + self.output_tokens
    
    def get_cost_breakdown(self) -> Dict[str, float]:
        """
        Calculate the cost breakdown for the tokens used
        使用されたトークンの費用内訳を計算（キャッシュ割引を考慮）
        """
        # モデル名を正規化
        normalized_model = self.pricing_calculator._normalize_model_name(self.model)
        pricing = self.pricing_calculator.PRICING.get(normalized_model, self.pricing_calculator.PRICING["default"])
        
        # 通常の入力トークン（キャッシュされていない部分）
        non_cached_tokens = self.input_tokens - self.cached_tokens
        
        # 費用計算
        # 通常の入力トークン: 通常料金
        non_cached_cost = (non_cached_tokens / 1000) * pricing["input"]
        # キャッシュヒットトークン: キャッシュ料金（モデルごとに異なる）
        cached_cost = (self.cached_tokens / 1000) * pricing["cached"]
        # 出力トークン: 通常料金
        output_cost = (self.output_tokens / 1000) * pricing["output"]
        
        input_cost = non_cached_cost + cached_cost
        total_cost = input_cost + output_cost
        
        return {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total_cost, 6),
            "cached_cost": round(cached_cost, 6),
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive metrics including tokens and costs
        トークン数と費用を含む総合的なメトリクスを取得
        """
        cost_breakdown = self.get_cost_breakdown()
        
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "cached_tokens": self.cached_tokens,  # キャッシュヒット数を追加
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost_usd": cost_breakdown["input_cost"],
            "output_cost_usd": cost_breakdown["output_cost"],
            "total_cost_usd": cost_breakdown["total_cost"],
            "cached_cost_usd": cost_breakdown["cached_cost"],  # キャッシュコストを追加
        }
    
    def reset_counters(self) -> None:
        """
        Reset all counters for reuse
        カウンターをリセットして再利用可能にする
        
        注意: グローバル履歴(_global_history)はリセットされません
        """
        self.input_tokens = 0
        self.cached_tokens = 0
        self.output_tokens = 0
        self.invocation_history.clear()
        self._current_invocation_id = 0
    
    def get_invocation_history(self) -> List[Dict[str, Any]]:
        """
        全てのainvoke呼び出し履歴を取得
        
        Returns:
            List of invocation records with tokens, costs, and metadata
        """
        return self.invocation_history.copy()
    
    def get_invocation_by_id(self, invocation_id: int) -> Optional[Dict[str, Any]]:
        """
        特定のinvocation IDの情報を取得
        
        Args:
            invocation_id: The invocation ID to retrieve
            
        Returns:
            Invocation record or None if not found
        """
        for record in self.invocation_history:
            if record["invocation_id"] == invocation_id:
                return record.copy()
        return None
    
    def get_latest_invocation(self) -> Optional[Dict[str, Any]]:
        """
        最新のainvoke呼び出し情報を取得
        
        Returns:
            Latest invocation record or None if no invocations yet
        """
        if not self.invocation_history:
            return None
        return self.invocation_history[-1].copy()
    
    def get_invocations_summary(self) -> Dict[str, Any]:
        """
        全てのainvoke呼び出しのサマリーを取得
        
        Returns:
            Summary including count, total tokens, and total cost
        """
        if not self.invocation_history:
            return {
                "total_invocations": 0,
                "total_input_tokens": 0,
                "total_cached_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "average_tokens_per_invocation": 0.0,
                "average_cost_per_invocation": 0.0,
            }
        
        total_input = sum(r["input_tokens"] for r in self.invocation_history)
        total_cached = sum(r["cached_tokens"] for r in self.invocation_history)
        total_output = sum(r["output_tokens"] for r in self.invocation_history)
        total_cost = sum(r["total_cost_usd"] for r in self.invocation_history)
        count = len(self.invocation_history)
        
        return {
            "total_invocations": count,
            "total_input_tokens": total_input,
            "total_cached_tokens": total_cached,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_cost_usd": round(total_cost, 6),
            "average_tokens_per_invocation": round((total_input + total_output) / count, 2),
            "average_cost_per_invocation": round(total_cost / count, 6),
        }
    
    def format_invocation_details(self, width: int = 70) -> str:
        """
        各LLM呼び出しの詳細を整形された文字列で返す
        
        Args:
            width: 表示幅（デフォルト: 70文字）
            
        Returns:
            整形された詳細情報の文字列
        """
        if not self.invocation_history:
            return "No LLM invocations recorded yet."
        
        lines = []
        lines.append("=" * width)
        lines.append("📊 LLM Invocation Details:")
        lines.append("=" * width)
        
        for inv in self.invocation_history:
            lines.append(f"\n🔹 Call #{inv['invocation_id']} ({inv['elapsed_seconds']}s)")
            lines.append(f"   Tokens: {inv['input_tokens']} input + {inv['output_tokens']} output = {inv['total_tokens']} total")
            if inv['cached_tokens'] > 0:
                lines.append(f"   💾 Cache Hit: {inv['cached_tokens']} tokens saved ${inv['cached_cost_usd']:.6f}")
            lines.append(f"   💰 Cost: ${inv['total_cost_usd']:.6f}")
        
        return "\n".join(lines)
    
    def format_summary(self, width: int = 70) -> str:
        """
        サマリー統計を整形された文字列で返す
        
        Args:
            width: 表示幅（デフォルト: 70文字）
            
        Returns:
            整形されたサマリー情報の文字列
        """
        summary = self.get_invocations_summary()
        
        if summary['total_invocations'] == 0:
            return "No LLM invocations to summarize."
        
        lines = []
        lines.append("=" * width)
        lines.append("📈 Summary:")
        lines.append("=" * width)
        lines.append(f"Total LLM Calls: {summary['total_invocations']}")
        lines.append(f"Total Tokens: {summary['total_tokens']} ({summary['total_input_tokens']} input + {summary['total_output_tokens']} output)")
        if summary['total_cached_tokens'] > 0:
            lines.append(f"💾 Total Cached: {summary['total_cached_tokens']} tokens")
        lines.append(f"💰 Total Cost: ${summary['total_cost_usd']:.6f}")
        lines.append(f"📊 Average: {summary['average_tokens_per_invocation']:.1f} tokens/call, ${summary['average_cost_per_invocation']:.6f}/call")
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def format_report(self, width: int = 70, show_details: bool = True) -> str:
        """
        詳細とサマリーを含む完全なレポートを整形された文字列で返す
        
        Args:
            width: 表示幅（デフォルト: 70文字）
            show_details: 詳細を表示するかどうか（デフォルト: True）
            
        Returns:
            整形された完全なレポートの文字列
        """
        if not self.invocation_history:
            return "No LLM invocations recorded yet."
        
        parts = []
        
        if show_details:
            parts.append(self.format_invocation_details(width))
            parts.append("")  # 空行
        
        parts.append(self.format_summary(width))
        
        return "\n".join(parts)
    
    def format_loop_report(self, start_index: int, width: int = 70) -> str:
        """
        特定のインデックス以降のinvocationのみのレポートを整形して返す（ループごとの表示用）
        
        Args:
            start_index: 開始インデックス（このインデックス以降のinvocationを表示）
            width: 表示幅（デフォルト: 70文字）
            
        Returns:
            整形されたループレポートの文字列
        """
        if not self.invocation_history or start_index >= len(self.invocation_history):
            return ""
        
        loop_history = self.invocation_history[start_index:]
        
        lines = []
        lines.append("=" * width)
        lines.append("📊 This Query LLM Calls:")
        lines.append("=" * width)
        
        loop_input_tokens = 0
        loop_cached_tokens = 0
        loop_output_tokens = 0
        loop_cost = 0.0
        
        for inv in loop_history:
            lines.append(f"\n🔹 Call #{inv['invocation_id']} ({inv['elapsed_seconds']}s)")
            lines.append(f"   Model: {inv['model']}")
            lines.append(f"   Tokens: {inv['input_tokens']} input + {inv['output_tokens']} output = {inv['total_tokens']} total")
            if inv['cached_tokens'] > 0:
                lines.append(f"   💾 Cache Hit: {inv['cached_tokens']} tokens saved ${inv['cached_cost_usd']:.6f}")
            lines.append(f"   💰 Cost: ${inv['total_cost_usd']:.6f}")
            
            loop_input_tokens += inv['input_tokens']
            loop_cached_tokens += inv['cached_tokens']
            loop_output_tokens += inv['output_tokens']
            loop_cost += inv['total_cost_usd']
        
        lines.append("\n" + "-" * width)
        lines.append(f"📊 This Query Total: {len(loop_history)} calls, {loop_input_tokens + loop_output_tokens} tokens, ${loop_cost:.6f}")
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def format_session_summary(self, width: int = 70) -> str:
        """
        セッション全体のサマリーを整形して返す（quit時の表示用）
        
        Args:
            width: 表示幅（デフォルト: 70文字）
            
        Returns:
            整形されたセッションサマリーの文字列
        """
        summary = self.get_invocations_summary()
        
        if summary['total_invocations'] == 0:
            return ""
        
        lines = []
        lines.append("=" * width)
        lines.append("📈 SESSION SUMMARY:")
        lines.append("=" * width)
        lines.append(f"Total LLM Calls: {summary['total_invocations']}")
        lines.append(f"Total Tokens: {summary['total_tokens']} ({summary['total_input_tokens']} input + {summary['total_output_tokens']} output)")
        if summary['total_cached_tokens'] > 0:
            lines.append(f"💾 Total Cached: {summary['total_cached_tokens']} tokens")
        lines.append(f"💰 Total Cost: ${summary['total_cost_usd']:.6f}")
        lines.append(f"📊 Average: {summary['average_tokens_per_invocation']:.1f} tokens/call, ${summary['average_cost_per_invocation']:.6f}/call")
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    @contextmanager
    def track_query(self):
        """
        1つのクエリ（処理単位）を追跡するコンテキストマネージャー
        
        使い方:
            with token_counter.track_query() as query:
                # ainvoke実行
                response = await agent.ainvoke(...)
                # クエリレポート表示
                print(query.report())
        """
        start_index = len(self.invocation_history)
        
        class QueryTracker:
            def __init__(self, counter, start_idx):
                self.counter = counter
                self.start_index = start_idx
            
            def report(self, width: int = 70) -> str:
                """このクエリのレポートを返す"""
                return self.counter.format_loop_report(self.start_index, width)
        
        yield QueryTracker(self, start_index)
    
    # ===== グローバル統計機能 =====
    
    def save_session_to_global(self, session_label: Optional[str] = None) -> None:
        """
        現在のセッション統計をグローバル履歴に保存
        
        Args:
            session_label: セッションのラベル（オプション）。省略時は自動生成
        """
        if not self.invocation_history:
            return  # 空のセッションは保存しない
        
        summary = self.get_invocations_summary()
        
        session_record = {
            "session_label": session_label or f"Session {len(self._global_history) + 1}",
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "total_invocations": summary["total_invocations"],
            "total_input_tokens": summary["total_input_tokens"],
            "total_cached_tokens": summary["total_cached_tokens"],
            "total_output_tokens": summary["total_output_tokens"],
            "total_tokens": summary["total_tokens"],
            "total_cost_usd": summary["total_cost_usd"],
            "invocations": self.invocation_history.copy(),  # 詳細も保存
        }
        
        self._global_history.append(session_record)
    
    @classmethod
    def get_global_history(cls) -> List[Dict[str, Any]]:
        """
        全セッションのグローバル履歴を取得
        
        Returns:
            List of session records
        """
        return cls._global_history.copy()
    
    @classmethod
    def get_global_summary(cls) -> Dict[str, Any]:
        """
        全セッションを集計したグローバルサマリーを取得
        
        Returns:
            Summary of all sessions combined
        """
        if not cls._global_history:
            return {
                "total_sessions": 0,
                "total_invocations": 0,
                "total_input_tokens": 0,
                "total_cached_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
            }
        
        total_sessions = len(cls._global_history)
        total_invocations = sum(s["total_invocations"] for s in cls._global_history)
        total_input = sum(s["total_input_tokens"] for s in cls._global_history)
        total_cached = sum(s["total_cached_tokens"] for s in cls._global_history)
        total_output = sum(s["total_output_tokens"] for s in cls._global_history)
        total_cost = sum(s["total_cost_usd"] for s in cls._global_history)
        
        return {
            "total_sessions": total_sessions,
            "total_invocations": total_invocations,
            "total_input_tokens": total_input,
            "total_cached_tokens": total_cached,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_cost_usd": round(total_cost, 6),
        }
    
    @classmethod
    def format_global_summary(cls, width: int = 70) -> str:
        """
        全セッションのグローバルサマリーを整形して返す
        
        Args:
            width: 表示幅（デフォルト: 70文字）
            
        Returns:
            整形されたグローバルサマリーの文字列
        """
        summary = cls.get_global_summary()
        
        if summary["total_sessions"] == 0:
            return ""
        
        lines = []
        lines.append("=" * width)
        lines.append("🌍 GLOBAL SUMMARY (All Sessions):")
        lines.append("=" * width)
        lines.append(f"Total Sessions: {summary['total_sessions']}")
        lines.append(f"Total LLM Calls: {summary['total_invocations']}")
        lines.append(f"Total Tokens: {summary['total_tokens']} ({summary['total_input_tokens']} input + {summary['total_output_tokens']} output)")
        if summary['total_cached_tokens'] > 0:
            lines.append(f"💾 Total Cached: {summary['total_cached_tokens']} tokens")
        lines.append(f"💰 Total Cost: ${summary['total_cost_usd']:.6f}")
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    @classmethod
    def format_global_detailed(cls, width: int = 70) -> str:
        """
        各セッションの詳細を含むグローバルレポートを整形して返す
        
        Args:
            width: 表示幅（デフォルト: 70文字）
            
        Returns:
            整形された詳細グローバルレポートの文字列
        """
        if not cls._global_history:
            return ""
        
        lines = []
        lines.append("=" * width)
        lines.append("🌍 GLOBAL DETAILED REPORT:")
        lines.append("=" * width)
        
        for i, session in enumerate(cls._global_history, 1):
            lines.append(f"\n📦 {session['session_label']}")
            lines.append(f"   Time: {session['timestamp']}")
            lines.append(f"   Calls: {session['total_invocations']}")
            lines.append(f"   Tokens: {session['total_tokens']} ({session['total_input_tokens']} input + {session['total_output_tokens']} output)")
            if session['total_cached_tokens'] > 0:
                lines.append(f"   💾 Cached: {session['total_cached_tokens']} tokens")
            lines.append(f"   💰 Cost: ${session['total_cost_usd']:.6f}")
        
        lines.append("\n" + "-" * width)
        summary = cls.get_global_summary()
        lines.append(f"🌍 Total: {summary['total_sessions']} sessions, {summary['total_invocations']} calls, {summary['total_tokens']} tokens, ${summary['total_cost_usd']:.6f}")
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    @classmethod
    def reset_global_history(cls) -> None:
        """
        グローバル履歴をクリア
        
        警告: 全セッションの累積統計が削除されます
        """
        cls._global_history.clear()






# Convenience functions for cost calculation
# 費用計算のための便利関数

def calculate_openai_cost(model: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
    """
    Calculate OpenAI API cost for given token usage
    指定されたトークン使用量に対するOpenAI APIの費用を計算
    """
    return OpenAIPricingCalculator.calculate_cost(model, input_tokens, output_tokens)


