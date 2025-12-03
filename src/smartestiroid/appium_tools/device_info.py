"""Device information tools for Appium."""

import logging
import time
from langchain.tools import tool
from selenium.common.exceptions import InvalidSessionIdException

logger = logging.getLogger(__name__)


@tool
def get_device_info() -> str:
    """Get comprehensive device information including model, Android version, display, battery, etc.
    
    Returns:
        A formatted string containing device information, or an error message
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    # Wait 1 second to avoid ADB resource conflicts
    time.sleep(1)
    
    try:
        def shell(cmd, *args):
            result = driver.execute_script("mobile: shell", {
                "command": cmd,
                "args": list(args)
            })
            # Handle both dict and string responses
            if isinstance(result, dict):
                return result.get("stdout", "").strip() if "stdout" in result else str(result)
            else:
                return str(result).strip()

        info = {
            "model": shell("getprop", "ro.product.model"),
            "brand": shell("getprop", "ro.product.brand"),
            "device_name": shell("getprop", "ro.product.name"),
            "android_version": shell("getprop", "ro.build.version.release"),
            "sdk": shell("getprop", "ro.build.version.sdk"),
            "display_resolution": shell("wm", "size"),
            "density": shell("wm", "density"),
            "current_package": driver.current_package,
            "current_activity": driver.current_activity,
            "orientation": driver.orientation,
            "is_locked": driver.is_locked(),
        }
        
        output = "Device Information:\n"
        output += f"Model: {info['model']}\n"
        output += f"Brand: {info['brand']}\n"
        output += f"Device Name: {info['device_name']}\n"
        output += f"Android Version: {info['android_version']}\n"
        output += f"SDK: {info['sdk']}\n"
        output += f"Display: {info['display_resolution']}\n"
        output += f"Density: {info['density']}\n"
        output += f"Current Package: {info['current_package']}\n"
        output += f"Current Activity: {info['current_activity']}\n"
        output += f"Orientation: {info['orientation']}\n"
        output += f"Is Locked: {info['is_locked']}\n"

        
        print(f"🔧 Retrieved device information: {output}")
        time.sleep(1)  # ツール実行後のウェイト
        return output
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def is_locked() -> str:
    """Check if the device screen is locked.
    
    Returns:
        A message indicating whether the device is locked or not
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        locked = driver.is_locked()
        logger.info(f"🔧 Device locked status: {locked}")
        time.sleep(1)  # ツール実行後のウェイト
        return f"Device is {'locked' if locked else 'unlocked'}"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def get_orientation() -> str:
    """Get the current screen orientation.
    
    Returns:
        The current orientation (PORTRAIT or LANDSCAPE)
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        orientation = driver.orientation
        logger.info(f"🔧 Current orientation: {orientation}")
        time.sleep(1)  # ツール実行後のウェイト
        return f"Current orientation: {orientation}"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def set_orientation(orientation: str) -> str:
    """Set the screen orientation.
    
    Args:
        orientation: The desired orientation - "PORTRAIT" or "LANDSCAPE"
        
    Returns:
        A message indicating success or failure
        
    Raises:
        ValueError: If driver is not initialized or orientation is invalid
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    if orientation.upper() not in ["PORTRAIT", "LANDSCAPE"]:
        raise ValueError("Invalid orientation. Use 'PORTRAIT' or 'LANDSCAPE'")
    
    try:
        driver.orientation = orientation.upper()
        logger.info(f"🔧 Set orientation to: {orientation}")
        time.sleep(1)  # ツール実行後のウェイト
        return f"Successfully set orientation to: {orientation}"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise
