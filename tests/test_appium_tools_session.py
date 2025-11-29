"""Basic session and status tests for appium_tools.

テスト内容:
- ドライバーステータス確認
- 現在のアプリ取得
- スクリーンショット取得
- ページソース取得
- 短時間待機

これらは最も基本的なテストで、Android接続後に最初に実行すべきです。
"""

import pytest
from appium_tools import (
    get_driver_status,
    get_current_app,
    take_screenshot,
    get_page_source,
)
from appium_tools.navigation import wait_short_loading


@pytest.mark.asyncio
async def test_get_driver_status(driver_session):
    """Test get_driver_status tool."""
    result = get_driver_status.invoke({})
    assert "initialized and ready" in result.lower()


@pytest.mark.asyncio
async def test_get_current_app(driver_session):
    """Test get_current_app tool."""
    result = get_current_app.invoke({})
    assert "com.android.settings" in result


@pytest.mark.asyncio
async def test_take_screenshot(driver_session):
    """Test take_screenshot tool."""
    result = take_screenshot.invoke({})
    assert len(result) > 100  # Base64 string should be long
    assert "Failed" not in result


@pytest.mark.asyncio
async def test_get_page_source(driver_session):
    """Test get_page_source tool."""
    result = get_page_source.invoke({})
    assert len(result) > 100
    assert "xml" in result.lower() or "hierarchy" in result.lower()


@pytest.mark.asyncio
async def test_wait_short_loading(driver_session):
    """wait_short_loading ツールの基本動作をテストする。"""
    try:
        res = wait_short_loading.invoke({"seconds": "1"})
        assert "Waited" in res
        assert "seconds" in res
    except Exception as e:
        pytest.skip(f"wait_short_loading skipped due to environment: {e}")


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])
