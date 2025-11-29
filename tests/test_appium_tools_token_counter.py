"""
Test program for TiktokenCountCallback global statistics feature
複数セッション（appium_driverの複数起動）をまたいだグローバル統計機能のテスト
"""

import pytest
from appium_tools.token_counter import TiktokenCountCallback


def simulate_llm_call(counter: TiktokenCountCallback, 
                      input_tokens: int, 
                      output_tokens: int,
                      cached_tokens: int = 0):
    """
    LLMコールをシミュレートするヘルパー関数
    """
    # on_llm_start をシミュレート
    counter.on_llm_start({}, ["test prompt"])
    
    # on_llm_end をシミュレート
    class MockResponse:
        def __init__(self, input_tok, output_tok, cached_tok):
            self.llm_output = {
                'token_usage': {
                    'prompt_tokens': input_tok,
                    'completion_tokens': output_tok,
                    'prompt_tokens_details': {
                        'cached_tokens': cached_tok
                    }
                }
            }
    
    response = MockResponse(input_tokens, output_tokens, cached_tokens)
    counter.on_llm_end(response)


@pytest.fixture(autouse=True)
def reset_global_state():
    """各テストの前後でグローバル状態をリセット"""
    TiktokenCountCallback.reset_global_history()
    yield
    TiktokenCountCallback.reset_global_history()


class TestGlobalStatistics:
    """グローバル統計機能のテスト"""
    
    def test_save_session_to_global(self):
        """セッションをグローバル履歴に保存できる"""
        counter = TiktokenCountCallback(model="gpt-4.1-mini")
        
        # セッション1: 2回のLLM呼び出し
        simulate_llm_call(counter, 1000, 200)
        simulate_llm_call(counter, 1500, 300)
        
        # セッションを保存
        counter.save_session_to_global("Test Session 1")
        
        # グローバル履歴を確認
        history = TiktokenCountCallback.get_global_history()
        assert len(history) == 1
        assert history[0]["session_label"] == "Test Session 1"
        assert history[0]["total_invocations"] == 2
        assert history[0]["total_input_tokens"] == 2500
        assert history[0]["total_output_tokens"] == 500
    
    def test_multiple_sessions(self):
        """複数のセッションをグローバル履歴に保存できる"""
        # セッション1
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 1000, 200)
        simulate_llm_call(counter1, 1500, 300)
        counter1.save_session_to_global("Session 1")
        
        # セッション2
        counter2 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter2, 2000, 400)
        counter2.save_session_to_global("Session 2")
        
        # セッション3
        counter3 = TiktokenCountCallback(model="gpt-4o-mini")
        simulate_llm_call(counter3, 3000, 500)
        simulate_llm_call(counter3, 1000, 100)
        simulate_llm_call(counter3, 2000, 200)
        counter3.save_session_to_global("Session 3")
        
        # グローバル履歴を確認
        history = TiktokenCountCallback.get_global_history()
        assert len(history) == 3
        assert history[0]["session_label"] == "Session 1"
        assert history[1]["session_label"] == "Session 2"
        assert history[2]["session_label"] == "Session 3"
    
    def test_get_global_summary(self):
        """グローバルサマリーが正しく集計される"""
        # セッション1: 2回の呼び出し
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 1000, 200)  # 1200 tokens
        simulate_llm_call(counter1, 1500, 300)  # 1800 tokens
        counter1.save_session_to_global("Session 1")
        
        # セッション2: 1回の呼び出し
        counter2 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter2, 2000, 400)  # 2400 tokens
        counter2.save_session_to_global("Session 2")
        
        # グローバルサマリーを確認
        summary = TiktokenCountCallback.get_global_summary()
        assert summary["total_sessions"] == 2
        assert summary["total_invocations"] == 3
        assert summary["total_input_tokens"] == 4500  # 1000+1500+2000
        assert summary["total_output_tokens"] == 900  # 200+300+400
        assert summary["total_tokens"] == 5400
        assert summary["total_cost_usd"] > 0  # コストが計算されている
    
    def test_global_summary_with_cache(self):
        """キャッシュトークンを含むグローバルサマリー"""
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 2000, 300, cached_tokens=500)
        counter1.save_session_to_global("Session with Cache")
        
        summary = TiktokenCountCallback.get_global_summary()
        assert summary["total_cached_tokens"] == 500
    
    def test_reset_counters_preserves_global(self):
        """reset_counters()してもグローバル履歴は保持される"""
        counter = TiktokenCountCallback(model="gpt-4.1-mini")
        
        # セッション1
        simulate_llm_call(counter, 1000, 200)
        counter.save_session_to_global("Session 1")
        
        # リセット
        counter.reset_counters()
        
        # セッション2
        simulate_llm_call(counter, 2000, 400)
        counter.save_session_to_global("Session 2")
        
        # グローバル履歴は両方保持されている
        history = TiktokenCountCallback.get_global_history()
        assert len(history) == 2
        
        summary = TiktokenCountCallback.get_global_summary()
        assert summary["total_sessions"] == 2
        assert summary["total_invocations"] == 2
    
    def test_format_global_summary(self):
        """グローバルサマリーのフォーマット出力"""
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 1000, 200)
        counter1.save_session_to_global("Session 1")
        
        counter2 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter2, 2000, 400)
        counter2.save_session_to_global("Session 2")
        
        formatted = TiktokenCountCallback.format_global_summary()
        
        assert "GLOBAL SUMMARY" in formatted
        assert "Total Sessions: 2" in formatted
        assert "Total LLM Calls: 2" in formatted
        assert "Total Tokens:" in formatted
        assert "Total Cost:" in formatted
    
    def test_format_global_detailed(self):
        """グローバル詳細レポートのフォーマット出力"""
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 1000, 200)
        counter1.save_session_to_global("Session 1")
        
        counter2 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter2, 2000, 400)
        counter2.save_session_to_global("Session 2")
        
        formatted = TiktokenCountCallback.format_global_detailed()
        
        assert "GLOBAL DETAILED REPORT" in formatted
        assert "Session 1" in formatted
        assert "Session 2" in formatted
        assert "Calls:" in formatted
        assert "Tokens:" in formatted
        assert "Cost:" in formatted
    
    def test_auto_generated_session_label(self):
        """session_labelを省略すると自動生成される"""
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 1000, 200)
        counter1.save_session_to_global()  # ラベル省略
        
        counter2 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter2, 2000, 400)
        counter2.save_session_to_global()  # ラベル省略
        
        history = TiktokenCountCallback.get_global_history()
        assert "Session 1" in history[0]["session_label"]
        assert "Session 2" in history[1]["session_label"]
    
    def test_empty_session_not_saved(self):
        """空のセッション（LLM呼び出しなし）は保存されない"""
        counter = TiktokenCountCallback(model="gpt-4.1-mini")
        counter.save_session_to_global("Empty Session")
        
        history = TiktokenCountCallback.get_global_history()
        assert len(history) == 0
    
    def test_reset_global_history(self):
        """グローバル履歴をクリアできる"""
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 1000, 200)
        counter1.save_session_to_global("Session 1")
        
        counter2 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter2, 2000, 400)
        counter2.save_session_to_global("Session 2")
        
        # リセット前
        assert len(TiktokenCountCallback.get_global_history()) == 2
        
        # リセット
        TiktokenCountCallback.reset_global_history()
        
        # リセット後
        assert len(TiktokenCountCallback.get_global_history()) == 0
        summary = TiktokenCountCallback.get_global_summary()
        assert summary["total_sessions"] == 0
    
    def test_different_models_in_sessions(self):
        """異なるモデルを使った複数セッションのコスト計算"""
        # セッション1: gpt-4.1-mini
        counter1 = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter1, 1000, 200)
        counter1.save_session_to_global("gpt-4.1-mini session")
        
        # セッション2: gpt-4o-mini
        counter2 = TiktokenCountCallback(model="gpt-4o-mini")
        simulate_llm_call(counter2, 1000, 200)
        counter2.save_session_to_global("gpt-4o-mini session")
        
        # グローバルサマリー
        history = TiktokenCountCallback.get_global_history()
        
        # 各セッションで異なるコストが計算されているはず
        cost1 = history[0]["total_cost_usd"]
        cost2 = history[1]["total_cost_usd"]
        
        # トークン数は同じだがコストは異なる（モデルが違うため）
        assert history[0]["total_tokens"] == history[1]["total_tokens"]
        assert cost1 != cost2  # 料金が異なる
    
    def test_invocation_details_preserved(self):
        """セッション保存時にinvocation詳細も保存される"""
        counter = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter, 1000, 200)
        simulate_llm_call(counter, 1500, 300)
        counter.save_session_to_global("Detailed Session")
        
        history = TiktokenCountCallback.get_global_history()
        
        # invocationsフィールドに詳細が保存されている
        assert "invocations" in history[0]
        assert len(history[0]["invocations"]) == 2
        assert history[0]["invocations"][0]["invocation_id"] == 1
        assert history[0]["invocations"][1]["invocation_id"] == 2


class TestGlobalStatisticsIntegration:
    """実際の使用パターンに近い統合テスト"""
    
    def test_multi_session_workflow(self):
        """複数セッションのワークフローをシミュレート"""
        # アプリ起動1回目
        print("\n=== First appium_driver session ===")
        counter = TiktokenCountCallback(model="gpt-4.1-mini")
        
        # ユーザークエリ1
        with counter.track_query() as query:
            simulate_llm_call(counter, 1000, 200)
            print(query.report())
        
        # ユーザークエリ2
        with counter.track_query() as query:
            simulate_llm_call(counter, 1500, 300)
            print(query.report())
        
        # セッション終了
        print(counter.format_session_summary())
        counter.save_session_to_global("Appium Session 1")
        
        # アプリ起動2回目（新しいインスタンス）
        print("\n=== Second appium_driver session ===")
        counter2 = TiktokenCountCallback(model="gpt-4.1-mini")
        
        # ユーザークエリ3
        with counter2.track_query() as query:
            simulate_llm_call(counter2, 2000, 400)
            print(query.report())
        
        # セッション終了
        print(counter2.format_session_summary())
        counter2.save_session_to_global("Appium Session 2")
        
        # グローバル統計表示
        print("\n" + TiktokenCountCallback.format_global_summary())
        
        # 検証
        summary = TiktokenCountCallback.get_global_summary()
        assert summary["total_sessions"] == 2
        assert summary["total_invocations"] == 3
        assert summary["total_tokens"] == 5400  # 1000+200 + 1500+300 + 2000+400
    
    def test_realistic_multi_day_usage(self):
        """現実的な複数日の使用をシミュレート"""
        # Day 1
        counter = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter, 1000, 200)
        simulate_llm_call(counter, 1500, 300)
        counter.save_session_to_global("Day 1 - Morning")
        
        counter = TiktokenCountCallback(model="gpt-4.1-mini")
        simulate_llm_call(counter, 2000, 400)
        counter.save_session_to_global("Day 1 - Afternoon")
        
        # Day 2
        counter = TiktokenCountCallback(model="gpt-4o-mini")  # モデル変更
        simulate_llm_call(counter, 3000, 500)
        counter.save_session_to_global("Day 2 - Morning")
        
        # グローバル統計
        formatted = TiktokenCountCallback.format_global_detailed()
        print("\n" + formatted)
        
        assert "Day 1 - Morning" in formatted
        assert "Day 1 - Afternoon" in formatted
        assert "Day 2 - Morning" in formatted
        
        summary = TiktokenCountCallback.get_global_summary()
        assert summary["total_sessions"] == 3
        assert summary["total_invocations"] == 4


if __name__ == "__main__":
    # 直接実行時のテスト
    print("Running global statistics tests...")
    pytest.main([__file__, "-v", "-s"])
