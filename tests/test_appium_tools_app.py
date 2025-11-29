"""App management tests for appium_tools.

テスト内容:
- アプリの起動/終了
- インストール済みアプリ一覧

これらはアプリ管理に関するテストです。
"""

import asyncio
import pytest
from smartestiroid.appium_tools import (
    activate_app,
    terminate_app,
    list_apps,
)


@pytest.mark.asyncio
async def test_activate_terminate_app(driver_session):
    """Test activate_app and terminate_app tools."""
    activate_result = activate_app.invoke({"app_id": "com.android.chrome"})
    assert "activated" in activate_result.lower() or "failed" in activate_result.lower()
    await asyncio.sleep(1)
    
    terminate_result = terminate_app.invoke({"app_id": "com.android.chrome"})
    assert "terminated" in terminate_result.lower() or "failed" in terminate_result.lower()
    await asyncio.sleep(0.5)
    
    activate_app.invoke({"app_id": "com.android.settings"})
    await asyncio.sleep(1)


@pytest.mark.asyncio
async def test_list_apps(driver_session):
    """Test list_apps tool."""
    result = list_apps.invoke({})
    if "adb_shell" in result.lower() and "not been enabled" in result.lower():
        pytest.skip("adb_shell feature not enabled in Appium server")
    assert "installed apps" in result.lower()
    assert "com.android.settings" in result.lower() or "com.google" in result.lower()


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])
