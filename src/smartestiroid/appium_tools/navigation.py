"""Navigation and screen inspection tools for Appium."""

import logging
import time
from langchain.tools import tool
from selenium.common.exceptions import InvalidSessionIdException

from .interaction import _find_element_internal

logger = logging.getLogger(__name__)


@tool
def take_screenshot() -> str:
    """Take a screenshot of the current screen and return it as base64 string.
    
    Returns:
        The screenshot as a base64 encoded string that can be used by other tools, or an error message
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        screenshot_base64 = driver.get_screenshot_as_base64()
        logger.info("🔧 Screenshot taken successfully")
        return screenshot_base64
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def wait_short_loading(seconds: str = "5") -> str:
    """画面が読み込み中と判断した場合に短時間待機する。

    LLMがナビゲーション直後や重い処理後にUIがまだ安定していないと判断した際に
    呼び出してください。指定秒数だけ待機して、後続の操作の安定性を高めます。

    Args:
        seconds: 待機秒数を文字列で指定（デフォルト: "5"）。数値化できない場合は5秒。

    Returns:
        待機結果を示す文字列（成功/失敗メッセージ）。
    """
    from .session import driver
    if not driver:
        return "Driver is not initialized"

    try:
        try:
            wait_secs = max(0, int(seconds))
        except Exception:
            wait_secs = 5

        logger.info(f"🔧 Waiting {wait_secs}s to allow UI to settle...")
        time.sleep(wait_secs)
        return f"Waited {wait_secs} seconds for loading"
    except InvalidSessionIdException:
        # セッション切れの場合は上位で対処できるようにそのまま再送出
        raise
    except Exception as e:
        return f"Failed: {e}"


@tool
def get_page_source() -> str:
    """Get the XML source of the current screen layout.
    
    ⚠️ IMPORTANT: Use this tool when:
    - An element cannot be found (NoSuchElementException)
    - You need to see what elements are actually on the screen
    - You want to find the correct resource-id, text, or class name
    - Before trying multiple different XPath selectors blindly
    
    The XML shows all elements with their attributes (resource-id, text, class, content-desc).
    This helps you write accurate selectors instead of guessing.
    
    Returns:
        The XML page source if successful, or an error message
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        source = driver.page_source
        logger.info("🔧 Page source retrieved successfully")  
        logger.debug(f"\n{source}\n")     
        return f"Page source retrieved successfully:\n{source}"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def scroll_element(by: str, value: str, direction: str = "up") -> str:
    """Scroll within a scrollable element (like a list or scrollview).
    
    Args:
        by: The locator strategy (e.g., "xpath", "id", "accessibility_id")
        value: The locator value to find the scrollable element
        direction: Direction to scroll - "up", "down", "left", or "right" (default: "up")
        
    Returns:
        A message indicating success or failure of scrolling
        
    Examples:
        Scroll up in a list: scroll_element("id", "android:id/list", "up")
        Scroll down: scroll_element("xpath", "//*[@scrollable='true']", "down")
        
    Raises:
        ValueError: If driver is not initialized or direction is invalid
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    
    element, error = _find_element_internal(by, value)
    if error:
        return error
    
    # Get element location and size
    location = element.location
    size = element.size
    
    # Calculate center point
    center_x = location['x'] + size['width'] // 2
    center_y = location['y'] + size['height'] // 2
    
    # Calculate swipe coordinates within the element
    if direction == "up":
        start_x = center_x
        start_y = location['y'] + size['height'] * 0.8
        end_x = center_x
        end_y = location['y'] + size['height'] * 0.2
    elif direction == "down":
        start_x = center_x
        start_y = location['y'] + size['height'] * 0.2
        end_x = center_x
        end_y = location['y'] + size['height'] * 0.8
    elif direction == "left":
        start_x = location['x'] + size['width'] * 0.8
        start_y = center_y
        end_x = location['x'] + size['width'] * 0.2
        end_y = center_y
    elif direction == "right":
        start_x = location['x'] + size['width'] * 0.2
        start_y = center_y
        end_x = location['x'] + size['width'] * 0.8
        end_y = center_y
    else:
        return f"❌ Invalid direction: '{direction}'. Use 'up', 'down', 'left', or 'right'"
    
    # Perform swipe
    driver.swipe(int(start_x), int(start_y), int(end_x), int(end_y), 500)
    logger.info(f"🔧 Scrolled {direction} in element found by {by} with value {value}")
    return f"Successfully scrolled {direction} in element"


@tool
def scroll_to_element(by: str, value: str, scrollable_by: str = "xpath", scrollable_value: str = "//*[@scrollable='true']") -> str:
    """Scroll within a scrollable container until an element is visible.
    
    Args:
        by: The locator strategy for the target element (e.g., "xpath", "id", "accessibility_id")
        value: The locator value for the target element
        scrollable_by: The locator strategy for the scrollable container (default: "xpath")
        scrollable_value: The locator value for the scrollable container (default: "//*[@scrollable='true']")
        
    Returns:
        A message indicating success or failure of scrolling to the element
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    
    max_scrolls = 10
    for i in range(max_scrolls):
        # Try to find the target element
        element, error = _find_element_internal(by, value)
        if element and element.is_displayed():
            logger.info(f"🔧 Found element by {by} with value {value} after {i} scrolls")
            return f"Successfully scrolled to element by {by} with value {value}"
        
        # If it's a locator error (not just "not found"), return immediately
        if error and "Invalid locator" in error:
            return error
        
        # Find scrollable container and scroll down
        scrollable, scroll_error = _find_element_internal(scrollable_by, scrollable_value)
        if scroll_error:
            return scroll_error
        
        location = scrollable.location
        size = scrollable.size
        center_x = location['x'] + size['width'] // 2
        start_y = location['y'] + size['height'] * 0.8
        end_y = location['y'] + size['height'] * 0.2
        driver.swipe(int(center_x), int(start_y), int(center_x), int(end_y), 500)
    
    return f"❌ Element not found after scrolling: No element found with by='{by}' and value='{value}' after {max_scrolls} scrolls. IMPORTANT: Use get_page_source() to verify the element exists and check its exact identifiers."
