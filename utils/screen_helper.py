"""
Screen information and screenshot utilities for SmartestiRoid test framework.

This module provides functions for capturing screenshots and processing screen information.
"""

import base64
import io
from PIL import Image


async def generate_screen_info(screenshot_tool, generate_locators, max_retries: int = 2):
    """スクリーンショットとロケーター情報を取得する
    
    Args:
        screenshot_tool: スクリーンショット取得ツール
        generate_locators: ロケーター生成ツール
        max_retries: 最大リトライ回数（デフォルト2回）
    
    Returns:
        tuple: (locator_str, image_url)
            - locator_str: ロケーター情報の文字列
            - image_url: base64エンコードされた画像データURL
    """
    import asyncio
    
    screenshot = None
    locator = None
    
    # スクリーンショット取得のリトライ
    for attempt in range(max_retries + 1):
        try:
            print(f"screenshot_tool 実行... (attempt {attempt + 1}/{max_retries + 1})")
            screenshot = await screenshot_tool.ainvoke({})
            print("screenshot_tool 結果: 成功")
            break
        except Exception as e:
            print(f"screenshot_tool エラー (attempt {attempt + 1}): {str(e)[:200]}")
            if attempt < max_retries:
                await asyncio.sleep(1)
            else:
                assert False, f"❌ screenshot取得に失敗しました: {e}"

    # ロケーター取得のリトライ
    for attempt in range(max_retries + 1):
        try:
            print(f"generate_locators 実行... (attempt {attempt + 1}/{max_retries + 1})")
            locator = await generate_locators.ainvoke({})
            print("generate_locators 結果: 成功")
            break
        except Exception as e:
            print(f"generate_locators エラー (attempt {attempt + 1}): {str(e)[:200]}")
            if attempt < max_retries:
                await asyncio.sleep(1)
            else:
                assert False, f"❌ locator取得に失敗しました: {e}"

    # 画像処理
    image_url = ""
    if screenshot:
        try:
            # base64デコード時のパディングエラーを処理
            try:
                img_bytes = base64.b64decode(screenshot)
            except Exception as decode_error:
                # パディング修正を試みる
                print(f"⚠️ base64デコードエラー、パディング修正を試みます: {decode_error}")
                missing_padding = len(screenshot) % 4
                if missing_padding:
                    screenshot += '=' * (4 - missing_padding)
                img_bytes = base64.b64decode(screenshot)
            
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode == "RGBA":
                img = img.convert("RGB")

            # 横幅1280px以上ならリサイズ
            if img.width > 1280:
                ratio = 1280 / img.width
                new_size = (1280, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            # Vision API用にJPEG形式でbase64化
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            img_bytes_jpeg = buf.getvalue()
            image_url = (
                "data:image/jpeg;base64," + base64.b64encode(img_bytes_jpeg).decode()
            )
            print("✅ 画像処理成功")
        except Exception as e:
            print(f"⚠️ 画像処理エラー: {e}")
            image_url = ""

    return str(locator) if locator else "ロケーター情報なし", image_url
