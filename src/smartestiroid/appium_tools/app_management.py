"""App management tools for Appium."""

import logging
import time
from langchain.tools import tool
from selenium.common.exceptions import InvalidSessionIdException

logger = logging.getLogger(__name__)


@tool
def get_current_app() -> str:
    """Get the package name and activity of the currently running app.
    
    Returns:
        The current app package and activity information, or an error message
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        current_package = driver.current_package
        current_activity = driver.current_activity
        logger.info(f"🔧 Current app: {current_package}/{current_activity}")
        time.sleep(1)  # ツール実行後のウェイト
        return f"Current app package: {current_package}\nCurrent activity: {current_activity}"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def activate_app(app_id: str) -> str:
    """Activate (launch) an app by its package name.
    
    Args:
        app_id: The app package name to activate (e.g., "com.android.settings")
        
    Returns:
        A message indicating success or failure
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        driver.activate_app(app_id)
        logger.info(f"🔧 Activated app: {app_id}")
        time.sleep(1)  # ツール実行後のウェイト
        return f"Successfully activated app: {app_id}"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def terminate_app(app_id: str) -> str:
    """Terminate (force stop) an app by its package name.
    
    Args:
        app_id: The app package name to terminate (e.g., "com.android.settings")
        
    Returns:
        A message indicating success or failure
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        result = driver.terminate_app(app_id)
        logger.info(f"🔧 Terminated app: {app_id}, result: {result}")
        time.sleep(1)  # ツール実行後のウェイト
        return f"Successfully terminated app: {app_id} (result: {result})"
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def list_apps() -> str:
    """List all installed apps on the device.
    
    Returns:
        A list of installed app package names, or an error message
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        # Get list of installed packages using adb shell
        result = driver.execute_script("mobile: shell", {
            "command": "pm",
            "args": ["list", "packages"]
        })
        # Handle both dict and string responses
        if isinstance(result, dict):
            packages = result.get("stdout", "").strip()
        else:
            packages = str(result).strip()
        
        # Parse package names (format: "package:com.example.app")
        package_list = [line.replace("package:", "") for line in packages.split("\n") if line.startswith("package:")]
        logger.info(f"🔧 Found {len(package_list)} installed apps")
        logger.debug(f"🔧 Installed apps: {package_list}")
        time.sleep(1)  # ツール実行後のウェイト
        return f"Installed apps ({len(package_list)}):\n" + "\n".join(package_list)
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise


@tool
def restart_app(app_id: str, wait_seconds: int = 3) -> str:
    """Restart an app by terminating and then activating it.
    
    This tool terminates the specified app, waits for a specified duration,
    and then activates the app again. Useful for clearing app state or
    recovering from stuck states.
    
    Args:
        app_id: The app package name to restart (e.g., "com.android.chrome")
        wait_seconds: Seconds to wait between terminate and activate (default: 3)
        
    Returns:
        A message indicating success or failure
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        # Step 1: Terminate the app
        terminate_result = driver.terminate_app(app_id)
        logger.info(f"🔄 Terminated app for restart: {app_id}, result: {terminate_result}")
        
        # Step 2: Wait between terminate and activate
        logger.info(f"🔄 Waiting {wait_seconds} seconds before reactivating...")
        time.sleep(wait_seconds)
        
        # Step 3: Activate the app
        driver.activate_app(app_id)
        logger.info(f"🔄 Reactivated app: {app_id}")
        
        time.sleep(1)  # ツール実行後のウェイト
        return f"Successfully restarted app: {app_id} (waited {wait_seconds}s between terminate and activate)"    
    except InvalidSessionIdException:
        # Session expired - re-raise to caller
        raise
