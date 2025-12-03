"""Element interaction tools for Appium."""

import logging
import time
from typing import Tuple, Optional, Any
from langchain.tools import tool
from selenium.common.exceptions import (
    InvalidSessionIdException,
    InvalidArgumentException,
    InvalidSelectorException,
    NoSuchElementException,
    StaleElementReferenceException
)

logger = logging.getLogger(__name__)

# リトライ設定
STALE_ELEMENT_RETRY_COUNT = 3
STALE_ELEMENT_RETRY_DELAY = 0.5  # 秒


def _find_element_internal(by: str, value: str) -> Tuple[Optional[Any], Optional[str]]:
    """Internal helper to find an element with proper error handling.
    
    This is a shared helper function used by all element-finding tools.
    It provides consistent error handling for common Appium/Selenium exceptions.
    
    Args:
        by: The locator strategy (e.g., "xpath", "id", "accessibility_id")
        value: The locator value to search for
        
    Returns:
        Tuple of (element, error_message). 
        - If element is found: (element, None)
        - If element is not found or error occurs: (None, error_message)
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired (must be handled by caller)
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        element = driver.find_element(by=by, value=value)
        logger.info(f"🔧 Found element by {by} with value {value}")
        return element, None
    except (InvalidArgumentException, InvalidSelectorException) as e:
        error_msg = f"❌ Invalid locator: by='{by}' is not a valid locator strategy. Use 'xpath', 'id', 'accessibility_id', 'class_name', etc. Error: {e.msg}"
        return None, error_msg
    except NoSuchElementException:
        error_msg = f"❌ Element not found: No element found with by='{by}' and value='{value}'. IMPORTANT: Before trying different selectors, use get_page_source() to see the actual screen structure and find the correct element identifiers."
        return None, error_msg
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def find_element(by: str, value: str) -> str:
    """Find an element on the current screen using a locator strategy.
    
    Args:
        by: The locator strategy (e.g., "xpath", "id", "accessibility_id")
        value: The locator value to search for
        
    Returns:
        A message indicating success or failure of finding the element
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    element, error = _find_element_internal(by, value)
    if error:
        return error
    return f"Successfully found element by {by} with value {value}"


@tool
def click_element(by: str, value: str) -> str:
    """Find and click an element on the current screen.
    
    Args:
        by: The locator strategy (e.g., "xpath", "id", "accessibility_id")
        value: The locator value to search for
        
    Returns:
        A message indicating success or failure of clicking the element
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    last_error = None
    
    for attempt in range(STALE_ELEMENT_RETRY_COUNT):
        element, error = _find_element_internal(by, value)
        if error:
            return error
        
        try:
            element.click()
            logger.info(f"🔧 Clicked element by {by} with value {value}")
            return f"Successfully clicked on element by {by} with value {value}"
        except StaleElementReferenceException as e:
            last_error = e
            logger.warning(f"⚠️ StaleElementReferenceException (attempt {attempt + 1}/{STALE_ELEMENT_RETRY_COUNT}): {e}")
            if attempt < STALE_ELEMENT_RETRY_COUNT - 1:
                time.sleep(STALE_ELEMENT_RETRY_DELAY)
                # リトライ前に要素を再検索する（ループの先頭で行われる）
                continue
    
    # 全リトライ失敗
    error_msg = f"❌ Element became stale after {STALE_ELEMENT_RETRY_COUNT} attempts. The element '{value}' was found but disappeared from DOM before click. This usually means the screen changed. Use get_page_source() to check the current screen state."
    logger.error(error_msg)
    return error_msg


@tool
def get_text(by: str, value: str) -> str:
    """Get the text content of an element on the screen.
    
    Args:
        by: The locator strategy (e.g., "xpath", "id", "accessibility_id")
        value: The locator value to search for
        
    Returns:
        The text content of the element, or an error message
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    last_error = None
    
    for attempt in range(STALE_ELEMENT_RETRY_COUNT):
        element, error = _find_element_internal(by, value)
        if error:
            return error
        
        try:
            text = element.text
            logger.info(f"🔧 Got text '{text}' from element by {by} with value {value}")
            return f"Element text: {text}"
        except StaleElementReferenceException as e:
            last_error = e
            logger.warning(f"⚠️ StaleElementReferenceException (attempt {attempt + 1}/{STALE_ELEMENT_RETRY_COUNT}): {e}")
            if attempt < STALE_ELEMENT_RETRY_COUNT - 1:
                time.sleep(STALE_ELEMENT_RETRY_DELAY)
                continue
    
    # 全リトライ失敗
    error_msg = f"❌ Element became stale after {STALE_ELEMENT_RETRY_COUNT} attempts. The element '{value}' was found but disappeared from DOM before getting text. Use get_page_source() to check the current screen state."
    logger.error(error_msg)
    return error_msg


@tool
def press_keycode(keycode: int) -> str:
    """Press an Android keycode (e.g., back button, home button, etc.).
    
    Args:
        keycode: The Android keycode to press (e.g., 4 for BACK, 3 for HOME, 82 for MENU)
        
    Returns:
        A message indicating success or failure of pressing the keycode
        
    Common keycodes:
        3 = HOME
        4 = BACK
        82 = MENU
        66 = ENTER
        67 = DEL (backspace)
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    # 並列呼び出し時に正しい順序で実行されるようにウェイトを入れる
    # click_element (0s) -> send_keys (1s) -> press_keycode (2s) の順で実行される
    time.sleep(2)
    
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        driver.press_keycode(keycode)
        logger.info(f"🔧 Pressed keycode {keycode}")
        return f"Successfully pressed keycode {keycode}"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def double_tap(by: str, value: str) -> str:
    """Double tap on an element on the screen.
    
    Args:
        by: The locator strategy (e.g., "xpath", "id", "accessibility_id")
        value: The locator value to search for
        
    Returns:
        A message indicating success or failure of double tapping the element
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    element, error = _find_element_internal(by, value)
    if error:
        return error
    
    # Double tap using actions API
    from .session import driver
    from appium.webdriver.common.touch_action import TouchAction
    action = TouchAction(driver)
    action.tap(element).perform()
    action.tap(element).perform()
    logger.info(f"🔧 Double tapped element by {by} with value {value}")
    return f"Successfully double tapped on element by {by} with value {value}"


@tool
def send_keys(by: str, value: str, text: str) -> str:
    """Send text to an input element (recommended for normal text input).
    
    ✅ This is the recommended method for text input as it:
    - Simulates real user typing through the keyboard
    - Triggers input events properly
    - Works with IME (Input Method Editor) and autocomplete
    - Appends text without clearing existing content
    
    ⚠️ IMPORTANT: Only use this on input elements (EditText, TextField).
    If the screen has changed (after clicking, scrolling, etc.), 
    call get_page_source() first to get the latest UI state.
    
    Args:
        by: The locator strategy (e.g., "xpath", "id", "accessibility_id")
        value: The locator value to search for the input element
        text: The text to send to the input element
        
    Returns:
        A message indicating success or failure of sending keys
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    # 並列呼び出し時に正しい順序で実行されるようにウェイトを入れる
    # click_element (0s) -> send_keys (1s) -> press_keycode (2s) の順で実行される
    time.sleep(1)
    
    element, error = _find_element_internal(by, value)
    if error:
        return error
    
    # 要素のクラス名を取得して入力可能かチェック
    try:
        class_name = element.get_attribute("class") or ""
    except Exception:
        class_name = ""
    
    try:
        element.click()
        element.send_keys(text)
        logger.info(f"🔧 Sent keys '{text}' to element by {by} with value {value}")
        return f"Successfully sent keys '{text}' to element"
    except Exception as e:
        error_msg = str(e)
        if "Cannot set the element" in error_msg or "InvalidElementState" in error_msg:
            return (
                f"Error: Cannot input text to this element (class: {class_name}). "
                f"This element is not an input field (EditText/TextField), or the UI has changed. "
                f"Please call get_page_source() to get the latest UI state and find the correct input element (usually EditText or TextField class)."
            )
        raise
