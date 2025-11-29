"""Session management tools for Appium."""

import logging
from contextlib import asynccontextmanager
from appium import webdriver
from appium.options.android import UiAutomator2Options
from langchain.tools import tool

logger = logging.getLogger(__name__)

driver = None


@asynccontextmanager
async def appium_driver(options: UiAutomator2Options, appium_server_url: str = 'http://localhost:4723'):
    """Async context manager for initializing and managing the Appium driver.
    
    Args:
        options: UiAutomator2Options instance with driver configuration
        appium_server_url: URL of the Appium server (default: 'http://localhost:4723')
        
    Yields:
        The initialized webdriver instance
        
    Example:
        async with appium_driver(options) as driver:
            element = driver.find_element(by=AppiumBy.XPATH, value='//*[@text="Battery"]')
            element.click()
    """
    driver_instance = None
    try:
        driver_instance = webdriver.Remote(appium_server_url, options=options)
        global driver
        driver = driver_instance
        yield driver_instance
    finally:
        if driver_instance:
            driver_instance.quit()
            driver = None


@tool
def get_driver_status() -> str:
    """Get the current status of the Appium driver.
    
    Returns:
        A message indicating whether the driver is initialized or not
    """
    from .session import driver
    if driver:
        return "Driver is initialized and ready"
    else:
        return "Driver is not initialized"
