"""
Device information utilities for SmartestiRoid test framework.

This module provides functions for gathering and recording device information to Allure.
"""

import os
import json


async def write_device_info_once(driver=None, capabilities_path: str = "capabilities.json", appium_tools_func=None):
    """デバイス情報をAllure環境ファイルに書き込む（1回だけ実行）
    
    Args:
        driver: Appium ドライバーインスタンス（オプション）
        capabilities_path: capabilities.json ファイルパス
        appium_tools_func: appium_tools関数への参照（get_device_infoツール取得用）
    """    
    env_file_path = "allure-results/environment.properties"
    info = {}

    # ファイルが既に存在する場合はスキップ
    if os.path.exists(env_file_path):
        return

    try:
        # capabilities.json から基本情報を取得
        with open(capabilities_path, "r") as f:
            info = json.load(f)  
    except Exception as e:
        print(f"警告: デバイス情報の取得に失敗しました: {e}")

    # デバイス詳細を driver から取得
    if appium_tools_func:
        tools_list = appium_tools_func()
        tools_dict = {tool.name: tool for tool in tools_list}
        get_device_info = tools_dict.get("get_device_info")
        
        if get_device_info:
            info_result = await get_device_info.ainvoke({})
            # info_result が文字列の場合はパースする
            if isinstance(info_result, str):
                for line in info_result.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        info[key.strip()] = value.strip()
            elif isinstance(info_result, dict):
                info = info_result
    
    # 環境ファイルに書き込み
    os.makedirs("allure-results", exist_ok=True)
    with open(env_file_path, "w") as f:
        for key, value in info.items():
            if value:
                # キーに空白やコロンが含まれる場合はアンダースコアに置換
                safe_key = key.replace(' ', '_').replace(':', '_')
                f.write(f"{safe_key}={value}\n")
