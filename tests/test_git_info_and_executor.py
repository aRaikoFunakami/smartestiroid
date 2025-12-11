"""Git情報取得とexecutor.json生成機能のテスト"""
import os
import json
import tempfile
import shutil
from pathlib import Path
import pytest


def test_get_git_info():
    """_get_git_info() 関数のテスト"""
    from smartestiroid.conftest import _get_git_info
    
    git_info = _get_git_info()
    
    # 基本的なキーが存在することを確認
    assert "version" in git_info
    assert "uncommitted_changes" in git_info
    assert "has_changes" in git_info
    
    # バージョンが取得できていることを確認
    assert git_info["version"] != "unknown", "Git バージョンが取得できませんでした"
    
    # versionはタグまたはコミットハッシュの形式
    version = git_info["version"]
    assert len(version) > 0, "バージョン文字列が空です"
    
    # uncommitted_changesはリスト
    assert isinstance(git_info["uncommitted_changes"], list)
    
    # has_changesはブール値
    assert isinstance(git_info["has_changes"], bool)
    
    # 変更がある場合はリストが空でない
    if git_info["has_changes"]:
        assert len(git_info["uncommitted_changes"]) > 0
    else:
        assert len(git_info["uncommitted_changes"]) == 0
    
    print(f"✅ Git情報取得成功:")
    print(f"  バージョン: {git_info['version']}")
    print(f"  未コミット変更: {git_info['has_changes']}")
    if git_info["has_changes"]:
        print(f"  変更ファイル数: {len(git_info['uncommitted_changes'])}")
        for change in git_info["uncommitted_changes"][:3]:
            print(f"    - {change}")


def test_create_executor_json():
    """_create_executor_json() 関数のテスト"""
    from smartestiroid.conftest import _create_executor_json
    
    # 一時ディレクトリを作成
    with tempfile.TemporaryDirectory() as tmpdir:
        # モックのpytest configオブジェクトを作成
        class MockConfig:
            def __init__(self, allure_dir):
                self._allure_dir = allure_dir
            
            def getoption(self, name, default=None):
                if name == "--alluredir":
                    return self._allure_dir
                return default
        
        config = MockConfig(tmpdir)
        
        # executor.jsonを生成
        _create_executor_json(config)
        
        # ファイルが作成されたことを確認
        executor_file = Path(tmpdir) / "executor.json"
        assert executor_file.exists(), "executor.json が作成されませんでした"
        
        # JSONファイルを読み込み
        with open(executor_file, "r", encoding="utf-8") as f:
            executor_data = json.load(f)
        
        # 必須フィールドの存在を確認
        assert "name" in executor_data
        assert "type" in executor_data
        assert "buildName" in executor_data
        
        # 値の検証
        assert executor_data["name"] == "SmarTestiRoid"
        assert executor_data["type"] == "pytest"
        assert "smartestiroid" in executor_data["buildName"]
        
        print(f"✅ executor.json 生成成功:")
        print(f"  name: {executor_data['name']}")
        print(f"  type: {executor_data['type']}")
        print(f"  buildName: {executor_data['buildName']}")
        if "buildUrl" in executor_data:
            print(f"  buildUrl: {executor_data['buildUrl']}")


def test_create_executor_json_without_alluredir():
    """alluredir指定なしの場合のテスト"""
    from smartestiroid.conftest import _create_executor_json
    
    # モックのpytest configオブジェクト（alluredir無し）
    class MockConfig:
        def getoption(self, name, default=None):
            return default
    
    config = MockConfig()
    
    # 例外が発生しないことを確認（静かに終了する）
    try:
        _create_executor_json(config)
        print("✅ alluredir無しの場合も正常終了")
    except Exception as e:
        pytest.fail(f"例外が発生しました: {e}")


def test_create_executor_json_with_uncommitted_changes():
    """未コミット変更がある場合のテスト"""
    from smartestiroid.conftest import _get_git_info, _create_executor_json
    
    # 実際のGit状態を確認
    git_info = _get_git_info()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        class MockConfig:
            def __init__(self, allure_dir):
                self._allure_dir = allure_dir
            
            def getoption(self, name, default=None):
                if name == "--alluredir":
                    return self._allure_dir
                return default
        
        config = MockConfig(tmpdir)
        _create_executor_json(config)
        
        executor_file = Path(tmpdir) / "executor.json"
        with open(executor_file, "r", encoding="utf-8") as f:
            executor_data = json.load(f)
        
        # 未コミット変更がある場合、buildUrlが設定されている
        if git_info["has_changes"]:
            assert "buildUrl" in executor_data
            assert "Uncommitted" in executor_data["buildUrl"]
            print(f"✅ 未コミット変更がある場合のbuildUrl: {executor_data['buildUrl']}")
        else:
            print("✅ 未コミット変更なし（buildUrlは設定されない）")


def test_executor_json_with_many_changes():
    """多数の未コミット変更がある場合の表示テスト（シミュレーション）"""
    import json
    import tempfile
    from pathlib import Path
    
    # 多数のファイル変更をシミュレート
    simulated_changes = [
        " M file1.py",
        " M file2.py",
        " M file3.py",
        " M file4.py",
        " M file5.py",
        "?? new_file.py"
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # executor.jsonを手動で作成（多数変更の場合）
        executor_data = {
            "name": "SmarTestiRoid",
            "type": "pytest",
            "buildName": "smartestiroid v0.1.0-dirty",
        }
        
        # 3ファイルまで表示、それ以上は件数表示
        if len(simulated_changes) > 3:
            executor_data["buildUrl"] = f"Uncommitted: {', '.join(simulated_changes[:3])}... ({len(simulated_changes)} files)"
        
        executor_file = Path(tmpdir) / "executor.json"
        with open(executor_file, "w", encoding="utf-8") as f:
            json.dump(executor_data, f, indent=2, ensure_ascii=False)
        
        # 検証
        with open(executor_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert "buildUrl" in data
        assert "Uncommitted" in data["buildUrl"]
        assert "6 files" in data["buildUrl"]
        
        print(f"✅ 多数変更時のbuildUrl: {data['buildUrl']}")


if __name__ == "__main__":
    print("=" * 60)
    print("Git情報とexecutor.json生成機能のテスト")
    print("=" * 60)
    
    try:
        print("\n[テスト 1] Git情報取得")
        test_get_git_info()
        
        print("\n[テスト 2] executor.json生成")
        test_create_executor_json()
        
        print("\n[テスト 3] alluredir無しの場合")
        test_create_executor_json_without_alluredir()
        
        print("\n[テスト 4] 未コミット変更がある場合")
        test_create_executor_json_with_uncommitted_changes()
        
        print("\n[テスト 5] 多数変更時の表示")
        test_executor_json_with_many_changes()
        
        print("\n" + "=" * 60)
        print("✅ すべてのテストが成功しました！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ テスト失敗: {e}")
        import traceback
        traceback.print_exc()
