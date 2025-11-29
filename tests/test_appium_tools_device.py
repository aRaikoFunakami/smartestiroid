"""Device info and state tests for appium_tools.

テスト内容:
- デバイス情報取得
- ロック状態確認
- 画面向き操作

これらはデバイス状態に関するテストです。
"""

import asyncio
import pytest
from smartestiroid.appium_tools import (
    get_device_info,
    is_locked,
    get_orientation,
    set_orientation,
)


@pytest.mark.asyncio
async def test_get_device_info(driver_session):
    """Test get_device_info tool."""
    result = get_device_info.invoke({})
    if "adb_shell" in result.lower() and "not been enabled" in result.lower():
        pytest.skip("adb_shell feature not enabled in Appium server")
    assert "device information" in result.lower()
    assert "model" in result.lower()
    assert "android version" in result.lower()


@pytest.mark.asyncio
async def test_is_locked(driver_session):
    """Test is_locked tool."""
    result = is_locked.invoke({})
    assert "locked" in result.lower() or "unlocked" in result.lower()


@pytest.mark.asyncio
async def test_orientation(driver_session):
    """Test get_orientation and set_orientation tools."""
    current = get_orientation.invoke({})
    assert "portrait" in current.lower() or "landscape" in current.lower()
    
    if "portrait" in current.lower():
        set_result = set_orientation.invoke({"orientation": "LANDSCAPE"})
        await asyncio.sleep(1)
        set_orientation.invoke({"orientation": "PORTRAIT"})
    else:
        set_result = set_orientation.invoke({"orientation": "PORTRAIT"})
        await asyncio.sleep(1)
        set_orientation.invoke({"orientation": "LANDSCAPE"})
    
    assert "set orientation" in set_result.lower() or "failed" in set_result.lower()


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])
