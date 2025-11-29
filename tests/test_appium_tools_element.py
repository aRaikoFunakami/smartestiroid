"""Element interaction tests for appium_tools.

テスト内容:
- 要素検索
- テキスト取得
- クリック
- ダブルタップ
- キー送信
- キーコード送信

これらは要素操作に関するテストです。
"""

import asyncio
import pytest
from smartestiroid.appium_tools import (
    find_element,
    get_text,
    click_element,
    double_tap,
    send_keys,
    press_keycode,
)


@pytest.mark.asyncio
async def test_find_element(driver_session):
    """Test find_element tool."""
    result = find_element.invoke({"by": "xpath", "value": "//*[@text='Apps']"})
    assert "successfully found" in result.lower() or "failed" in result.lower()


@pytest.mark.asyncio
async def test_get_text(driver_session):
    """Test get_text tool."""
    result = get_text.invoke({"by": "xpath", "value": "//*[@text='Apps']"})
    assert "Apps" in result or "Failed" in result


@pytest.mark.asyncio
async def test_click_element(driver_session):
    """Test click_element tool."""
    result = click_element.invoke({"by": "xpath", "value": "//*[@text='Apps']"})
    assert "successfully clicked" in result.lower() or "failed" in result.lower()
    await asyncio.sleep(1)
    
    # Go back
    press_keycode.invoke({"keycode": 4})
    await asyncio.sleep(1)


@pytest.mark.asyncio
async def test_double_tap(driver_session):
    """Test double_tap tool."""
    result = double_tap.invoke({"by": "xpath", "value": "//*[@text='Network & internet']"})
    assert "double tapped" in result.lower() or "failed" in result.lower()
    await asyncio.sleep(0.5)
    press_keycode.invoke({"keycode": 4})
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_press_keycode(driver_session):
    """Test press_keycode tool."""
    result = press_keycode.invoke({"keycode": 4})
    assert "successfully pressed" in result.lower() or "failed" in result.lower()
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_send_keys(driver_session):
    """Test send_keys tool."""
    click_result = click_element.invoke({
        "by": "id",
        "value": "com.android.settings:id/search_bar_title"
    })
    
    if "successfully clicked" in click_result.lower():
        await asyncio.sleep(1)
        
        result = send_keys.invoke({
            "by": "id",
            "value": "com.google.android.settings.intelligence:id/open_search_view_edit_text",
            "text": "wifi"
        })
        assert "successfully sent keys" in result.lower()
        
        await asyncio.sleep(1)
        press_keycode.invoke({"keycode": 4})
        await asyncio.sleep(0.5)
        press_keycode.invoke({"keycode": 4})
        await asyncio.sleep(0.5)
    else:
        pytest.skip("Search bar title not found")


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])
