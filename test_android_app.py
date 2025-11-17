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


# pytest_generate_tests フックでテストを動的生成
def pytest_generate_tests(metafunc):
    """pytestのテスト生成フック - CSVからテストケースを動的に生成"""
    if "test_case" in metafunc.fixturenames:
        # testsheet_path オプションから CSVパスを取得
        testsheet_path = metafunc.config.getoption("--testsheet")
        cases = load_csv_cases(testsheet_path)
        
        # テストケースIDのリストを生成（-k オプションで使用可能）
        test_ids = []
        for case in cases:
            cid = str(case.get("ID", "")).strip()
            test_id = cid if cid else f"case_{cases.index(case)+1:03d}"
            test_ids.append(test_id.replace("-", "_").replace(" ", "_"))
        
        # parametrize でテストケースを生成
        metafunc.parametrize("test_case,test_num,total_tests", 
                            [(case, i+1, len(cases)) for i, case in enumerate(cases)],
                            ids=test_ids)


@pytest.mark.asyncio
@pytest.mark.android
@pytest.mark.slow
async def test_android_app(test_case, test_num, total_tests, custom_knowhow):
    """CSVから動的に生成されたテストケースを実行"""
    case = test_case
    
    # CSVからepic、feature、storyを取得
    epic = str(case.get("Epic", "")).strip() or "Android Automation"
    feature = str(case.get("Feature", "")).strip() or "Step Recording"
    story = str(case.get("Story", "")).strip() or "Screenshot and Thoughts Capture"
    
    # Allureメタデータを動的に設定
    allure.dynamic.epic(epic)
    allure.dynamic.feature(feature)
    allure.dynamic.story(story)
    
    # テスト進捗ログ
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + f"🚀 テスト進捗: {test_num}/{total_tests} ({(test_num/total_tests)*100:.1f}%)")
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
        print(Fore.GREEN + f"✅ テスト {test_num}/{total_tests} 完了: {title}")
        if test_num == total_tests:
            print(Fore.GREEN + "🎉 全テスト完了！")


if __name__ == "__main__":
    print("Please use pytest to run this test.")
