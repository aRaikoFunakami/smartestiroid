import pytest
import allure
from .conftest import SmartestiRoid, agent_session
from .utils.structured_logger import SLog, LogCategory, LogEvent
import pandas as pd
import sys
import os


# パッケージのルートディレクトリ
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
# プロジェクトルートディレクトリ（pyproject.tomlがある場所）
PROJECT_ROOT = os.path.dirname(os.path.dirname(PACKAGE_DIR))


def load_csv_cases(path: str = "testsheet.csv"):
    """Read CSV and return list[dict] rows.
    Expected columns: ID, Epic, Feature, Story, Title, Description, Step, ExpectedResults, Criteria
    """
    # 相対パスの場合はカレントディレクトリ（実行元）からの相対パスとして解決
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    df = pd.read_csv(path, encoding='utf-8')
    df.columns = [str(c).strip() for c in df.columns]
    # Keep only rows that have at least a Title and Step
    if "Title" in df.columns and "Step" in df.columns:
        df = df.dropna(subset=["Title", "Step"])
    return df.to_dict(orient="records")


# pytest_configureで設定されたテストシートパスを取得
testsheet_path = getattr(sys, '_pytest_testsheet_path', 'testsheet.csv')
cases = load_csv_cases(testsheet_path)


def create_test_function(case, test_num):
    """動的にテスト関数を作成"""
    # CSVからepic、feature、storyを取得
    epic = str(case.get("Epic", "")).strip() or "Android Automation"
    feature = str(case.get("Feature", "")).strip() or "Step Recording"
    story = str(case.get("Story", "")).strip() or "Screenshot and Thoughts Capture"
    desc = str(case.get("Description", "")).strip()
    expected = str(case.get("ExpectedResults", "")).strip()
    description = f"{desc}\n\nExpected Results: {expected}"
    cid = str(case.get("ID", "")).strip()
    title = str(case.get("Title", "")).strip()
    allure_title = f"[{cid}] {title}"

    
    @pytest.mark.asyncio
    @pytest.mark.android
    @pytest.mark.slow
    @allure.epic(epic)
    @allure.feature(feature)
    @allure.story(story)
    @allure.title(allure_title)
    @allure.description(description)
    async def dynamic_test(request, custom_knowhow):  # request fixture を追加
        """Run one row from testsheet.csv as a test case."""
        
        # pytest_collection_modifyitems で設定された進捗情報を取得
        current = getattr(request.node, '_test_progress_current', 0)
        total = getattr(request.node, '_test_progress_total', 0)
        test_id = cid
        test_title = title
        
        # テスト開始ログ（JSON形式で統一）
        import json
        progress_start = json.dumps({
            "current": current,
            "total": total,
            "status": "running",
            "test_id": test_id,
            "test_title": test_title
        }, ensure_ascii=False)
        print(f"[PROGRESS] {progress_start}")
        
        # Extract fields
        steps = str(case.get("Step", "")).strip() 
        
        # Reset列の値を取得してno_reset値を決定
        # "Reset"の場合はno_reset=False（リセットあり）、"noReset"の場合はno_reset=True（リセットなし）
        reset_value = str(case.get("Reset", "")).strip()
        no_reset = reset_value.lower() != 'reset'

        # Get dontStopAppOnReset value
        # "dontStop"の場合はTrue、それ以外はFalse
        dont_stop_app_on_reset_value = str(case.get("dontStopAppOnReset", "")).strip()
        dont_stop_app_on_reset = dont_stop_app_on_reset_value.lower() == 'dontstop'


        # Execute steps via your agent
        with allure.step(title):
            SLog.log(LogCategory.TEST, LogEvent.START, {
                "test_id": cid,
                "title": title,
                "reset_value": reset_value,
                "no_reset": no_reset,
                "steps": steps,
                "expected": expected
            }, f"=== テストケース: {title} (ID={cid}) ===")
            
            # カスタムknowhowを使用してエージェントを作成
            agent = SmartestiRoid(agent_session, no_reset, dont_stop_app_on_reset, knowhow=custom_knowhow)
            agent_response = await agent.validate_task(
                steps=steps,
                expected=expected,
            )
            SLog.log(LogCategory.TEST, LogEvent.COMPLETE, {
                "response": str(agent_response)
            }, f"最終応答: {agent_response}")
            
            # テスト完了ログ（JSON形式で統一）
            progress_done = json.dumps({
                "current": current,
                "total": total,
                "status": "passed",
                "test_id": test_id,
                "test_title": test_title
            }, ensure_ascii=False)
            print(f"[PROGRESS] {progress_done}")
    
    return dynamic_test


# 動的にテスト関数を作成し、グローバルスコープに追加
for i, case in enumerate(cases, 1):
    cid = str(case.get("ID", "")).strip()
    title = str(case.get("Title", "")).strip()
    
    # テスト関数名を生成（pytestが認識できるようにtest_で始める）
    test_name = f"test_{cid}" if cid else f"test_case_{i:03d}"
    # 関数名に使えない文字を置換
    test_name = test_name.replace("-", "_").replace(" ", "_")
    
    # 動的にテスト関数を作成（test_num は使わない）
    _temp_func = create_test_function(case, i)
    _temp_func.__name__ = test_name
    
    # グローバルスコープに追加
    globals()[test_name] = _temp_func

# ループで使用した一時変数を削除
if '_temp_func' in globals():
    del _temp_func


if __name__ == "__main__":
    print("Please use pytest to run this test.")
