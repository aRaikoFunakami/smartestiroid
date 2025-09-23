import pytest
import allure
from colorama import Fore, init
from conftest import TestAgent, agent_session

init(autoreset=True)

EXPECTED_STATS_RESULT = "all_stats_visible"

# テストケース定義（グローバルスコープ）
testSet = [
    {
        "test_case": "AndroidでChromeを操作して新しいタブを開く",
        "steps": f"""
        試験手順:
        1. Chrome を起動する" 
        2. 画面右上のメニューアイコン（三点リーダー）を選択する
        3. 表示されたメニューから「New Tab」を選択する
        判定基準: 画面上部のタブバーに新しいタブが追加され、合計2つのタブが表示されていること
        判定基準に合致する場合は、判断理由とともに {EXPECTED_STATS_RESULT} と答えなさい。
        """,
        "criteria": EXPECTED_STATS_RESULT,
    },
    {
        "test_case": "AndroidでChromeを操作してYahooにアクセスする",
        "steps": f"""
        1. Chrome を起動する
        2. yahoo.co.jp をURLバーに入力してアクセスしてください。
        判定基準: 画面上部のURLバーに「yahoo.co.jp」と表示され,yahooのトップページが表示されていること
        判定基準に合致する場合は、判断理由とともに {EXPECTED_STATS_RESULT} と答えなさい。
        """,
        "criteria": EXPECTED_STATS_RESULT,
    },
]


def make_test_func(test):
    @pytest.mark.asyncio
    @pytest.mark.android
    @pytest.mark.slow
    @allure.epic("Android Automation")
    @allure.feature("Step Recording")
    @allure.story("Screenshot and Thoughts Capture")
    @allure.title(test["test_case"])
    @allure.description(test["test_case"])
    async def _test():
        print(Fore.YELLOW + f"=== テストケース: {test['test_case']} ===")
        print(Fore.YELLOW + f"タスク: {test['steps']}")
        print(Fore.YELLOW + f"期待される基準: {test['criteria']}")
        with allure.step(test["test_case"]):
            agent = TestAgent(agent_session)
            agent_response = await agent.validate_task(
                task=test["steps"],
                expected_substring=test["criteria"],
                ignore_case=True,
            )
            print(Fore.MAGENTA + f"最終応答: {agent_response}")

    return _test


# グローバルスコープでpytestが収集できるように登録
for idx, test in enumerate(testSet):
    func = make_test_func(test)
    func.__name__ = f"test_dynamic_{idx}_{test['test_case']}"
    globals()[func.__name__] = func

# 以降は既存のコード
if __name__ == "__main__":
    print("Please use pytest to run this test.")
