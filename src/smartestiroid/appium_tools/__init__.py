"""Appium tools for LangChain integration."""

import logging

# Create logger for appium_tools package
logger = logging.getLogger(__name__)

from .session import appium_driver, get_driver_status
from .interaction import find_element, click_element, get_text, press_keycode, double_tap, send_keys
from .navigation import take_screenshot, scroll_element, get_page_source, scroll_to_element, wait_short_loading
from .app_management import get_current_app, activate_app, terminate_app, list_apps, restart_app
from .device_info import get_device_info, is_locked, get_orientation, set_orientation

__all__ = [
    # Session
    "appium_driver",
    "get_driver_status",
    # Interaction
    "find_element",
    "click_element",
    "get_text",
    "press_keycode",
    "double_tap",
    "send_keys",
    # Navigation
    "take_screenshot",
    "scroll_element",
    "get_page_source",
    "scroll_to_element",
    "wait_short_loading",
    # App Management
    "get_current_app",
    "activate_app",
    "terminate_app",
    "list_apps",
    "restart_app",
    # Device Info
    "get_device_info",
    "is_locked",
    "get_orientation",
    "set_orientation",
    # Main function
    "appium_tools",
]


def appium_tools():
    """LangChain エージェント用の全Appiumツールリストを返す。
    
    Returns:
        list: LangChain BaseTool のリスト（19個のAppium自動化ツール）
    """
    return [
        get_driver_status,
        find_element,
        click_element,
        get_text,
        press_keycode,
        double_tap,
        send_keys,
        take_screenshot,
        scroll_element,
        get_page_source,
        scroll_to_element,
        get_current_app,
        activate_app,
        terminate_app,
        list_apps,
        restart_app,
        get_device_info,
        is_locked,
        get_orientation,
        set_orientation,
        wait_short_loading,
    ]
