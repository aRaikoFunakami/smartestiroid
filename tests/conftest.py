"""Shared fixtures for appium_tools tests."""

import pytest_asyncio
from appium.options.android import UiAutomator2Options
from smartestiroid.appium_tools import appium_driver


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
