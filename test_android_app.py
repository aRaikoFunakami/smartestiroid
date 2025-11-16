import pytest
import allure
from colorama import Fore, init
from conftest import SmartestiRoid, agent_session
import pandas as pd

init(autoreset=True)

EXPECTED_STATS_RESULT = "EXPECTED_STATS_RESULT"
SKIPPED_STATS_RESULT = "SKIPPED_STATS_RESULT"


def load_csv_cases(path: str = "testsheet.csv"):
    """Read CSV and return list[dict] rows.
    Expected columns: ID, Epic, Feature, Story, Title, Description, Step, ExpectedResults, Criteria
    """
    df = pd.read_csv(path, encoding='utf-8')
    df.columns = [str(c).strip() for c in df.columns]
    # Keep only rows that have at least a Title and Step
    if "Title" in df.columns and "Step" in df.columns:
        df = df.dropna(subset=["Title", "Step"])
    return df.to_dict(orient="records")


cases = load_csv_cases("testsheet.csv")

# テスト進捗管理
TOTAL_TESTS = len(cases)


def create_test_function(case, test_num):
    """動的にテスト関数を作成"""
    # CSVからepic、feature、storyを取得
    epic = str(case.get("Epic", "")).strip() or "Android Automation"
    feature = str(case.get("Feature", "")).strip() or "Step Recording"
    story = str(case.get("Story", "")).strip() or "Screenshot and Thoughts Capture"
    
    @pytest.mark.asyncio
    @pytest.mark.android
    @pytest.mark.slow
    @allure.epic(epic)
    @allure.feature(feature)
    @allure.story(story)
    async def dynamic_test(custom_knowhow):  # fixtureを引数に追加
        """Run one row from testsheet.csv as a test case."""
        
        # テスト進捗ログ
        print(Fore.CYAN + "=" * 60)
        print(Fore.CYAN + f"🚀 テスト進捗: {test_num}/{TOTAL_TESTS} ({(test_num/TOTAL_TESTS)*100:.1f}%)")
        print(Fore.CYAN + "=" * 60)
        
        # Extract fields
        cid = str(case.get("ID", "")).strip()
        title = str(case.get("Title", "")).strip() or (
            f"Case {cid}" if cid else "Excel Case"
        )
        desc = str(case.get("Description", "")).strip()
        steps = str(case.get("Step", "")).strip()
        expected = case.get("ExpectedResults").strip()
        criteria = str(case.get("Criteria")).strip()
        
        # Reset列の値を取得してno_reset値を決定
        reset_value = str(case.get("Reset", "")).strip()
        # "Reset"の場合はno_reset=False（リセットあり）、"noReset"の場合はno_reset=True（リセットなし）
        no_reset = reset_value.lower() != 'reset'

        task = (
            f"手順: {steps}\n"
            f"合否判定基準: {expected}\n"
            f"合否判定基準に合致する場合には: 判断理由とともに {criteria} と答えなさい"
        )

        # Allure dynamic metadata
        allure.dynamic.title(f"[{cid}] {title}" if cid else title)

        if desc:
            allure.attach(
                desc, name="Description", attachment_type=allure.attachment_type.TEXT
            )
        if expected:
            allure.attach(
                expected,
                name="ExpectedResults/Criteria",
                attachment_type=allure.attachment_type.TEXT,
            )

        # Execute steps via your agent
        with allure.step(title):
            print(Fore.YELLOW + f"=== テストケース: {title} (ID={cid}) ===")
            print(Fore.YELLOW + f"Reset設定: {reset_value} → appium:noReset={no_reset}")
            print(Fore.YELLOW + f"タスク: {steps}")
            print(Fore.YELLOW + f"期待される基準: {expected}")
            
            # カスタムknowhowを使用してエージェントを作成
            agent = SmartestiRoid(agent_session, no_reset, knowhow=custom_knowhow)
            agent_response = await agent.validate_task(
                task=task,
                expected_substring=criteria,
                ignore_case=True,
            )
            print(Fore.MAGENTA + f"最終応答: {agent_response}")
            
            # テスト完了ログ
            print(Fore.GREEN + f"✅ テスト {test_num}/{TOTAL_TESTS} 完了: {title}")
            if test_num == TOTAL_TESTS:
                print(Fore.GREEN + "🎉 全テスト完了！")
    
    return dynamic_test


# 動的にテスト関数を作成し、グローバルスコープに追加
for i, case in enumerate(cases, 1):
    cid = str(case.get("ID", "")).strip()
    title = str(case.get("Title", "")).strip()
    
    # テスト関数名を生成（pytestが認識できるようにtest_で始める）
    test_name = f"test_{cid}" if cid else f"test_case_{i:03d}"
    # 関数名に使えない文字を置換
    test_name = test_name.replace("-", "_").replace(" ", "_")
    
    # 動的にテスト関数を作成
    _temp_func = create_test_function(case, i)
    _temp_func.__name__ = test_name
    
    # グローバルスコープに追加
    globals()[test_name] = _temp_func

# ループで使用した一時変数を削除
if '_temp_func' in globals():
    del _temp_func


# 以降は既存のコード
if __name__ == "__main__":
    print("Please use pytest to run this test.")
