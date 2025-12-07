"""Appium tools for LangChain integration."""

import logging

# Create logger for appium_tools package
logger = logging.getLogger(__name__)

from .session import appium_driver, get_driver_status
from .interaction import find_element, click_element, get_text, press_keycode, double_tap, send_keys
from .navigation import take_screenshot, scroll_element, get_page_source, scroll_to_element, wait_short_loading, verify_screen_content, set_verify_model, get_verify_model
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
    "verify_screen_content",
    "set_verify_model",
    "get_verify_model",
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
    "appium_tools_for_prompt",
]


def appium_tools_for_prompt():
    """LLMプロンプト用のツール機能説明を返す。
    
    planやreplanでLLMが利用可能なツールの機能を理解するための説明文を生成する。
    
    Returns:
        str: 各ツールの名前、説明、パラメータをフォーマットした文字列
    """
    tools = appium_tools()
    
    tool_descriptions = []
    for tool in tools:
        # ツール名
        name = tool.name
        # ツールの説明
        description = tool.description
        
        # パラメータ情報（args_schemaから取得）
        params_info = ""
        if hasattr(tool, 'args_schema') and tool.args_schema:
            schema = tool.args_schema.model_json_schema()
            properties = schema.get('properties', {})
            required = schema.get('required', [])
            
            if properties:
                param_lines = []
                for param_name, param_info in properties.items():
                    param_type = param_info.get('type', 'any')
                    param_desc = param_info.get('description', '')
                    is_required = 'required' if param_name in required else 'optional'
                    param_lines.append(f"    - {param_name} ({param_type}, {is_required}): {param_desc}")
                
                if param_lines:
                    params_info = "\n  Parameters:\n" + "\n".join(param_lines)
        
        tool_descriptions.append(f"# {name}\n{description}{params_info}")
    
    return "\n\n".join(tool_descriptions)


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
        verify_screen_content,
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
