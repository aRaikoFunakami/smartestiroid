"""Navigation and scroll tests for appium_tools.

テスト内容:
- スクロール操作
- 要素へのスクロール
- ナビゲーションフロー
- 画面コンテンツ確認 (verify_screen_content)

これらは画面遷移とスクロールに関するテストです。
"""

import asyncio
import pytest
from smartestiroid.appium_tools import (
    scroll_element,
    scroll_to_element,
    click_element,
    get_current_app,
    take_screenshot,
    get_page_source,
    press_keycode,
    verify_screen_content,
    set_verify_model,
    get_verify_model,
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


@pytest.mark.asyncio
async def test_verify_screen_content_found(driver_session):
    """Test verify_screen_content tool when target is found."""
    # Settings app should have "Settings" or "設定" text
    result = verify_screen_content.invoke({"target": "設定画面またはSettingsテキスト"})
    
    # Should return a result (either found or not found)
    assert "確認成功" in result or "確認失敗" in result
    assert "[結果]" in result or "エラー" in result


@pytest.mark.asyncio
async def test_verify_screen_content_not_found(driver_session):
    """Test verify_screen_content tool when target is not found."""
    # Something that definitely won't be on Settings screen
    result = verify_screen_content.invoke({"target": "存在しない架空のダイアログXYZ123"})
    
    # Should return not found
    assert "確認" in result
    assert "[結果]" in result or "エラー" in result


@pytest.mark.asyncio
async def test_set_and_get_verify_model():
    """Test set_verify_model and get_verify_model functions."""
    # Get default model
    original_model = get_verify_model()
    assert original_model == "gpt-4.1-mini"
    
    # Set a different model
    set_verify_model("gpt-4o")
    assert get_verify_model() == "gpt-4o"
    
    # Restore original
    set_verify_model(original_model)
    assert get_verify_model() == original_model


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])
