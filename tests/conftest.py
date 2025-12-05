"""Shared fixtures for appium_tools tests.

テストカテゴリ:
- appium_tools: Appiumツールテスト（Android端末が必要）
- agent: エージェントロジックテスト（端末不要）
- unit: 純粋なユニットテスト（外部依存なし）

使い方:
    # Appiumツールテストのみ実行
    uv run pytest tests/ -m appium_tools
    
    # エージェントテストのみ実行
    uv run pytest tests/ -m agent
    
    # ユニットテストのみ実行（端末不要）
    uv run pytest tests/ -m unit
    
    # Appiumツールテストを除外（エージェント修正時に推奨）
    uv run pytest tests/ -m "not appium_tools"
"""

import pytest
import pytest_asyncio
from appium.options.android import UiAutomator2Options
from smartestiroid.appium_tools import appium_driver


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests based on their file location."""
    for item in items:
        # tests/test_appium_tools_*.py → appium_tools マーカー
        if "test_appium_tools" in item.fspath.basename:
            item.add_marker(pytest.mark.appium_tools)
        # tests/test_xml_compressor.py など端末不要 → unit マーカー
        elif "test_xml_compressor" in item.fspath.basename:
            item.add_marker(pytest.mark.unit)
        elif "test_smartestiroid_import" in item.fspath.basename:
            item.add_marker(pytest.mark.unit)


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
