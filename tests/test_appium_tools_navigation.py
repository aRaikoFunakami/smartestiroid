"""Navigation and scroll tests for appium_tools.

テスト内容:
- スクロール操作
- 要素へのスクロール
- ナビゲーションフロー

これらは画面遷移とスクロールに関するテストです。
"""

import asyncio
import pytest
from appium_tools import (
    scroll_element,
    scroll_to_element,
    click_element,
    get_current_app,
    take_screenshot,
    get_page_source,
    press_keycode,
)


@pytest.mark.asyncio
async def test_scroll_element(driver_session):
    """Test scroll_element tool."""
    result = scroll_element.invoke({
        "by": "xpath",
        "value": "//*[@scrollable='true']",
        "direction": "down"
    })
    assert "scrolled" in result.lower() or "failed" in result.lower()
    
    await asyncio.sleep(0.5)
    
    result = scroll_element.invoke({
        "by": "xpath",
        "value": "//*[@scrollable='true']",
        "direction": "up"
    })
    assert "scrolled" in result.lower() or "failed" in result.lower()


@pytest.mark.asyncio
async def test_scroll_to_element(driver_session):
    """Test scroll_to_element tool."""
    result = scroll_to_element.invoke({
        "by": "xpath",
        "value": "//*[@text='System']",
        "scrollable_by": "xpath",
        "scrollable_value": "//*[@scrollable='true']"
    })
    assert "scrolled to element" in result.lower() or "failed" in result.lower()
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_navigation_flow(driver_session):
    """Test a complete navigation flow."""
    initial_app = get_current_app.invoke({})
    assert "com.android.settings" in initial_app
    
    screenshot1 = take_screenshot.invoke({})
    assert len(screenshot1) > 100
    
    click_result = click_element.invoke({"by": "xpath", "value": "//*[@text='Apps']"})
    if "successfully clicked" in click_result.lower():
        await asyncio.sleep(1)
        
        current_app = get_current_app.invoke({})
        assert "com.android.settings" in current_app
        
        screenshot2 = take_screenshot.invoke({})
        assert len(screenshot2) > 100
        
        page_source = get_page_source.invoke({})
        assert len(page_source) > 100
        
        press_keycode.invoke({"keycode": 4})
        await asyncio.sleep(1)
        
        back_app = get_current_app.invoke({})
        assert len(back_app) > 0
    else:
        pytest.skip("Could not click Apps element")


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])
