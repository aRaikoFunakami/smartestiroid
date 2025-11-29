"""Element interaction tools for Appium."""

import logging
from langchain.tools import tool
from selenium.common.exceptions import (
    InvalidSessionIdException,
    InvalidArgumentException,
    InvalidSelectorException,
    NoSuchElementException
)

logger = logging.getLogger(__name__)


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
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        element = driver.find_element(by=by, value=value)
        logger.info(f"🔧 Found element {element} by {by} with value {value}")
        return f"Successfully found element by {by} with value {value}"
    except (InvalidArgumentException, InvalidSelectorException) as e:
        return f"❌ Invalid locator: by='{by}' is not a valid locator strategy. Use 'xpath', 'id', 'accessibility_id', 'class_name', etc. Error: {e.msg}"
    except NoSuchElementException:
        return f"❌ Element not found: No element found with by='{by}' and value='{value}'. IMPORTANT: Before trying different selectors, use get_page_source() to see the actual screen structure and find the correct element identifiers."
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


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
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        element = driver.find_element(by=by, value=value)
        element.click()
        logger.info(f"🔧 Clicked element by {by} with value {value}")
        return f"Successfully clicked on element by {by} with value {value}"
    except (InvalidArgumentException, InvalidSelectorException) as e:
        return f"❌ Invalid locator: by='{by}' is not a valid locator strategy. Use 'xpath', 'id', 'accessibility_id', 'class_name', etc. Error: {e.msg}"
    except NoSuchElementException:
        return f"❌ Element not found: No element found with by='{by}' and value='{value}'. IMPORTANT: Before trying different selectors, use get_page_source() to see the actual screen structure and find the correct element identifiers."
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


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
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        element = driver.find_element(by=by, value=value)
        text = element.text
        logger.info(f"🔧 Got text '{text}' from element by {by} with value {value}")
        return f"Element text: {text}"
    except (InvalidArgumentException, InvalidSelectorException) as e:
        return f"❌ Invalid locator: by='{by}' is not a valid locator strategy. Use 'xpath', 'id', 'accessibility_id', 'class_name', etc. Error: {e.msg}"
    except NoSuchElementException:
        return f"❌ Element not found: No element found with by='{by}' and value='{value}'. IMPORTANT: Before trying different selectors, use get_page_source() to see the actual screen structure and find the correct element identifiers."
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


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
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        element = driver.find_element(by=by, value=value)
        # Double tap using actions API
        from appium.webdriver.common.touch_action import TouchAction
        action = TouchAction(driver)
        action.tap(element).perform()
        action.tap(element).perform()
        logger.info(f"🔧 Double tapped element by {by} with value {value}")
        return f"Successfully double tapped on element by {by} with value {value}"
    except (InvalidArgumentException, InvalidSelectorException) as e:
        return f"❌ Invalid locator: by='{by}' is not a valid locator strategy. Use 'xpath', 'id', 'accessibility_id', 'class_name', etc. Error: {e.msg}"
    except NoSuchElementException:
        return f"❌ Element not found: No element found with by='{by}' and value='{value}'. IMPORTANT: Before trying different selectors, use get_page_source() to see the actual screen structure and find the correct element identifiers."
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def send_keys(by: str, value: str, text: str) -> str:
    """Send text to an input element (recommended for normal text input).
    
    ✅ This is the recommended method for text input as it:
    - Simulates real user typing through the keyboard
    - Triggers input events properly
    - Works with IME (Input Method Editor) and autocomplete
    - Appends text without clearing existing content
    
    For special cases where you need to bypass the keyboard, use set_value() instead.
    
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
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        element = driver.find_element(by=by, value=value)
        element.click()
        element.send_keys(text)
        logger.info(f"🔧 Sent keys '{text}' to element by {by} with value {value}")
        return f"Successfully sent keys '{text}' to element"
    except (InvalidArgumentException, InvalidSelectorException) as e:
        return f"❌ Invalid locator: by='{by}' is not a valid locator strategy. Use 'xpath', 'id', 'accessibility_id', 'class_name', etc. Error: {e.msg}"
    except NoSuchElementException:
        return f"❌ Element not found: No element found with by='{by}' and value='{value}'. IMPORTANT: Before trying different selectors, use get_page_source() to see the actual screen structure and find the correct element identifiers."
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise
