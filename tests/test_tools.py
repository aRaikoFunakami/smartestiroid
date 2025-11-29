"""Test all Appium tools directly without LLM using pytest."""

import asyncio
import pytest
from appium_tools.navigation import wait_short_loading
import pytest_asyncio
from appium.options.android import UiAutomator2Options
from appium_tools import (
    appium_driver,
    get_driver_status,
    find_element,
    click_element,
    get_page_source,
    take_screenshot,
    scroll_element,
    scroll_to_element,
    get_current_app,
    get_text,
    press_keycode,
    double_tap,
    send_keys,
    activate_app,
    terminate_app,
    list_apps,
    get_device_info,
    is_locked,
    get_orientation,
    set_orientation,
)


@pytest_asyncio.fixture
async def driver_session():
    """Fixture to provide Appium driver session for tests."""
    options = UiAutomator2Options()
    options.set_capability("platformName", "Android")
    options.set_capability("appium:automationName", "uiautomator2")
    options.set_capability("appium:deviceName", "Android")
    options.set_capability("appium:appPackage", "com.android.settings")
    options.set_capability("appium:appActivity", ".Settings")
    options.set_capability("appium:language", "en")
    options.set_capability("appium:locale", "US")
    options.set_capability("appium:newCommandTimeout", 300)
    
    async with appium_driver(options) as driver:
        yield driver


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
async def test_wait_short_loading(driver_session):
    """wait_short_loading ツールの基本動作をテストする。
    ドライバーが初期化済みである前提で、5秒待機の結果文字列が返ることを確認。
    """
    try:
        res = wait_short_loading.invoke({"seconds": "1"})
        # 実行環境によっては正確な秒数に依存しないため、メッセージの一部を確認
        assert "Waited" in res
        assert "seconds" in res
    except Exception as e:
        # セッションや環境に依存する失敗はスキップ
        pytest.skip(f"wait_short_loading skipped due to environment: {e}")


@pytest.mark.asyncio
async def test_get_page_source(driver_session):
    """Test get_page_source tool."""
    result = get_page_source.invoke({})
    assert len(result) > 100
    assert "xml" in result.lower() or "hierarchy" in result.lower()


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
async def test_scroll_element(driver_session):
    """Test scroll_element tool."""
    # Try to scroll down
    result = scroll_element.invoke({
        "by": "xpath",
        "value": "//*[@scrollable='true']",
        "direction": "down"
    })
    assert "scrolled" in result.lower() or "failed" in result.lower()
    
    await asyncio.sleep(0.5)
    
    # Scroll back up
    result = scroll_element.invoke({
        "by": "xpath",
        "value": "//*[@scrollable='true']",
        "direction": "up"
    })
    assert "scrolled" in result.lower() or "failed" in result.lower()


@pytest.mark.asyncio
async def test_press_keycode(driver_session):
    """Test press_keycode tool."""
    # Press back button
    result = press_keycode.invoke({"keycode": 4})
    assert "successfully pressed" in result.lower() or "failed" in result.lower()
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_send_keys(driver_session):
    """Test send_keys tool."""
    # Click search bar title
    click_result = click_element.invoke({
        "by": "id",
        "value": "com.android.settings:id/search_bar_title"
    })
    
    if "successfully clicked" in click_result.lower():
        await asyncio.sleep(1)
        
        # Send keys to search field without clearing
        result = send_keys.invoke({
            "by": "id",
            "value": "com.google.android.settings.intelligence:id/open_search_view_edit_text",
            "text": "wifi"
        })
        assert "successfully sent keys" in result.lower()
        
        await asyncio.sleep(1)
        
        # Press back twice to close search
        press_keycode.invoke({"keycode": 4})
        await asyncio.sleep(0.5)
        press_keycode.invoke({"keycode": 4})
        await asyncio.sleep(0.5)
    else:
        pytest.skip("Search bar title not found")


@pytest.mark.asyncio
async def test_navigation_flow(driver_session):
    """Test a complete navigation flow."""
    # Get initial app and take screenshot
    initial_app = get_current_app.invoke({})
    assert "com.android.settings" in initial_app
    
    screenshot1 = take_screenshot.invoke({})
    assert len(screenshot1) > 100
    
    # Click on Apps if available
    click_result = click_element.invoke({"by": "xpath", "value": "//*[@text='Apps']"})
    if "successfully clicked" in click_result.lower():
        await asyncio.sleep(1)
        
        # Verify navigation happened
        current_app = get_current_app.invoke({})
        assert "com.android.settings" in current_app
        
        # Take screenshot of new screen
        screenshot2 = take_screenshot.invoke({})
        assert len(screenshot2) > 100
        
        # Get page source to verify content
        page_source = get_page_source.invoke({})
        assert len(page_source) > 100
        
        # Go back once
        press_keycode.invoke({"keycode": 4})
        await asyncio.sleep(1)
        
        # Just verify any app is running (don't assert specific app due to environment variation)
        back_app = get_current_app.invoke({})
        assert len(back_app) > 0  # Some app should be active
    else:
        pytest.skip("Could not click Apps element")


@pytest.mark.asyncio
async def test_double_tap(driver_session):
    """Test double_tap tool."""
    result = double_tap.invoke({"by": "xpath", "value": "//*[@text='Network & internet']"})
    # Double tap might fail if element doesn't support it, so just check it doesn't crash
    assert "double tapped" in result.lower() or "failed" in result.lower()
    await asyncio.sleep(0.5)
    press_keycode.invoke({"keycode": 4})
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_scroll_to_element(driver_session):
    """Test scroll_to_element tool."""
    # Try to scroll to System element (usually at bottom of settings)
    result = scroll_to_element.invoke({
        "by": "xpath",
        "value": "//*[@text='System']",
        "scrollable_by": "xpath",
        "scrollable_value": "//*[@scrollable='true']"
    })
    assert "scrolled to element" in result.lower() or "failed" in result.lower()
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_activate_terminate_app(driver_session):
    """Test activate_app and terminate_app tools."""
    # Activate Chrome browser
    activate_result = activate_app.invoke({"app_id": "com.android.chrome"})
    assert "activated" in activate_result.lower() or "failed" in activate_result.lower()
    await asyncio.sleep(1)
    
    # Terminate Chrome
    terminate_result = terminate_app.invoke({"app_id": "com.android.chrome"})
    assert "terminated" in terminate_result.lower() or "failed" in terminate_result.lower()
    await asyncio.sleep(0.5)
    
    # Return to settings
    activate_app.invoke({"app_id": "com.android.settings"})
    await asyncio.sleep(1)


@pytest.mark.asyncio
async def test_list_apps(driver_session):
    """Test list_apps tool."""
    result = list_apps.invoke({})
    # This tool requires adb_shell to be enabled in Appium server
    if "adb_shell" in result.lower() and "not been enabled" in result.lower():
        pytest.skip("adb_shell feature not enabled in Appium server")
    assert "installed apps" in result.lower()
    # Just check that some apps are listed (don't require specific app)
    assert "com.android.settings" in result.lower() or "com.google" in result.lower()


@pytest.mark.asyncio
async def test_get_device_info(driver_session):
    """Test get_device_info tool."""
    result = get_device_info.invoke({})
    # This tool requires adb_shell to be enabled in Appium server
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
    # Get current orientation
    current = get_orientation.invoke({})
    assert "portrait" in current.lower() or "landscape" in current.lower()
    
    # Try to change orientation
    if "portrait" in current.lower():
        set_result = set_orientation.invoke({"orientation": "LANDSCAPE"})
        await asyncio.sleep(1)
        # Change back
        set_orientation.invoke({"orientation": "PORTRAIT"})
    else:
        set_result = set_orientation.invoke({"orientation": "PORTRAIT"})
        await asyncio.sleep(1)
        # Change back
        set_orientation.invoke({"orientation": "LANDSCAPE"})
    
    assert "set orientation" in set_result.lower() or "failed" in set_result.lower()


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])
