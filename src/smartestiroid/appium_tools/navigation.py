"""Navigation and screen inspection tools for Appium."""

import base64
import io
import logging
import os
import tempfile
import time
from typing import Optional
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from PIL import Image
from pydantic import BaseModel, Field
from selenium.common.exceptions import InvalidSessionIdException, StaleElementReferenceException

from .interaction import _find_element_internal, STALE_ELEMENT_RETRY_COUNT, STALE_ELEMENT_RETRY_DELAY
from .xml_compressor import compress_xml

logger = logging.getLogger(__name__)

# スクリーンショット保存先のパス（環境変数で設定可能）
SCREENSHOT_PATH = os.getenv("SMARTESTIROID_SCREENSHOT_PATH", "/app/data/latest_screenshot.png")


def _save_screenshot_to_file(screenshot_base64: str) -> None:
    """スクリーンショットをファイルに保存する（UI表示用）
    
    アトミックな書き込みを行い、読み込み側が不完全なファイルを取得しないようにする。
    一時ファイルに書き込んでから rename することで、ファイルの置き換えをアトミックに行う。
    """
    try:
        screenshot_data = base64.b64decode(screenshot_base64)
        
        # 一時ファイルに書き込み（同じディレクトリに作成してrenameがアトミックになるようにする）
        dir_path = os.path.dirname(SCREENSHOT_PATH)
        with tempfile.NamedTemporaryFile(mode='wb', dir=dir_path, delete=False, suffix='.tmp') as f:
            f.write(screenshot_data)
            temp_path = f.name
        
        # アトミックにファイルを置き換え
        os.replace(temp_path, SCREENSHOT_PATH)
        logger.debug(f"Screenshot saved to {SCREENSHOT_PATH}")
    except Exception as e:
        logger.warning(f"Failed to save screenshot to file: {e}")
        # 一時ファイルが残っていたら削除
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            pass


def _process_screenshot_for_vision(screenshot_base64: str, max_width: int = 1280) -> str:
    """スクリーンショットをVision API用に処理する（JPEG変換・リサイズ）
    
    Args:
        screenshot_base64: 元のbase64エンコードされたスクリーンショット
        max_width: 最大横幅（デフォルト1280px）
        
    Returns:
        処理済みのbase64エンコードされたJPEG画像
    """
    try:
        # base64デコード時のパディングエラーを処理
        try:
            img_bytes = base64.b64decode(screenshot_base64)
        except Exception as decode_error:
            # パディング修正を試みる
            logger.warning(f"⚠️ base64デコードエラー、パディング修正を試みます: {decode_error}")
            missing_padding = len(screenshot_base64) % 4
            if missing_padding:
                screenshot_base64 += '=' * (4 - missing_padding)
            img_bytes = base64.b64decode(screenshot_base64)
        
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")

        # 横幅が max_width を超えていればリサイズ
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # JPEG形式でbase64化
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        img_bytes_jpeg = buf.getvalue()
        return base64.b64encode(img_bytes_jpeg).decode()
        
    except Exception as e:
        logger.warning(f"⚠️ 画像処理エラー、元の画像を返します: {e}")
        return screenshot_base64


@tool
def take_screenshot(as_data_url: bool = False) -> str:
    """Take a screenshot of the current screen and return it as base64 string.
    
    The screenshot is automatically:
    - Converted to JPEG format for Vision API compatibility
    - Resized to max 1280px width for token efficiency
    
    Args:
        as_data_url: If True, return with "data:image/jpeg;base64," prefix for Vision API.
                     If False (default), return raw base64 string.
    
    Returns:
        The screenshot as a base64 encoded JPEG string
        
    Raises:
        ValueError: If driver is not initialized
        InvalidSessionIdException: If Appium session has expired
    """
    from .session import driver
    if not driver:
        raise ValueError("Driver is not initialized")
    
    try:
        screenshot_base64 = driver.get_screenshot_as_base64()
        # Vision API用に処理（JPEG変換・リサイズ）
        processed_screenshot = _process_screenshot_for_vision(screenshot_base64)
        # UI表示用にファイルにも保存（元の画像を保存）
        _save_screenshot_to_file(screenshot_base64)
        logger.info("🔧 Screenshot taken and processed successfully")
        time.sleep(1)  # ツール実行後のウェイト
        
        if as_data_url:
            return f"data:image/jpeg;base64,{processed_screenshot}"
        return processed_screenshot
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
    
    Note: The XML is compressed to reduce token usage:
    - Unnecessary attributes are removed (index, package, displayed, etc.)
    - Empty text/content-desc/resource-id attributes are removed
    - Empty elements with no meaningful attributes are removed
    - XML structure (parent-child relationships) is preserved
    
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
        # XMLを圧縮して不要なデータを削除
        compressed_source = compress_xml(source)
        logger.info("🔧 Page source retrieved and compressed successfully")  
        logger.debug(f"\n{compressed_source}\n")     
        time.sleep(1)  # ツール実行後のウェイト
        return compressed_source
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
    
    for attempt in range(STALE_ELEMENT_RETRY_COUNT):
        element, error = _find_element_internal(by, value)
        if error:
            return error
        
        try:
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
            time.sleep(1)  # ツール実行後のウェイト
            return f"Successfully scrolled {direction} in element"
            
        except StaleElementReferenceException as e:
            logger.warning(f"⚠️ StaleElementReferenceException in scroll_element (attempt {attempt + 1}/{STALE_ELEMENT_RETRY_COUNT}): {e}")
            if attempt < STALE_ELEMENT_RETRY_COUNT - 1:
                time.sleep(STALE_ELEMENT_RETRY_DELAY)
                continue
    
    # 全リトライ失敗
    error_msg = f"❌ Element became stale after {STALE_ELEMENT_RETRY_COUNT} attempts. The scrollable element '{value}' disappeared from DOM. Use get_page_source() to check the current screen state."
    logger.error(error_msg)
    return error_msg


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
    scroll_count = 0
    total_scroll_distance = 0
    
    for i in range(max_scrolls):
        # Try to find the target element
        element, error = _find_element_internal(by, value)
        try:
            if element and element.is_displayed():
                if scroll_count == 0:
                    logger.info(f"🔧 Found element by {by} with value {value} (already visible, no scroll needed)")
                    time.sleep(1)  # ツール実行後のウェイト
                    return f"Element already visible by {by} with value {value} (no scroll needed)"
                else:
                    logger.info(f"🔧 Found element by {by} with value {value} after {scroll_count} scroll(s), total distance: {total_scroll_distance}px")
                    time.sleep(1)  # ツール実行後のウェイト
                    return f"Successfully scrolled to element by {by} with value {value} after {scroll_count} scroll(s), total scroll distance: {total_scroll_distance}px"
        except StaleElementReferenceException:
            # 要素がstaleになった場合は次のスクロールへ
            logger.warning(f"⚠️ Target element became stale, continuing scroll...")
        
        # If it's a locator error (not just "not found"), return immediately
        if error and "Invalid locator" in error:
            return error
        
        # Find scrollable container and scroll down with retry
        for attempt in range(STALE_ELEMENT_RETRY_COUNT):
            scrollable, scroll_error = _find_element_internal(scrollable_by, scrollable_value)
            if scroll_error:
                return scroll_error
            
            try:
                location = scrollable.location
                size = scrollable.size
                center_x = location['x'] + size['width'] // 2
                start_y = location['y'] + size['height'] * 0.8
                end_y = location['y'] + size['height'] * 0.2
                scroll_distance = int(start_y - end_y)
                total_scroll_distance += scroll_distance
                driver.swipe(int(center_x), int(start_y), int(center_x), int(end_y), 500)
                scroll_count += 1
                break  # スワイプ成功
            except StaleElementReferenceException as e:
                logger.warning(f"⚠️ StaleElementReferenceException in scroll_to_element (attempt {attempt + 1}/{STALE_ELEMENT_RETRY_COUNT}): {e}")
                if attempt < STALE_ELEMENT_RETRY_COUNT - 1:
                    time.sleep(STALE_ELEMENT_RETRY_DELAY)
                    continue
                else:
                    # 全リトライ失敗
                    return f"❌ Scrollable element became stale after {STALE_ELEMENT_RETRY_COUNT} attempts. Use get_page_source() to check the current screen state."
    
    return f"❌ Element not found after scrolling: No element found with by='{by}' and value='{value}' after {scroll_count} scrolls (total scroll distance: {total_scroll_distance}px). IMPORTANT: Use get_page_source() to verify the element exists and check its exact identifiers."


class VerifyScreenContentInput(BaseModel):
    """Input schema for verify_screen_content."""
    target: str = Field(description="The target content to verify is displayed on the screen (e.g., '利用規約ダイアログ', 'ログインボタン', 'エラーメッセージ')")


class VerifyScreenContentResult(BaseModel):
    """Output schema for verify_screen_content LLM response."""
    result: str = Field(description="FOUND if target is displayed, NOT_FOUND otherwise")
    reason: str = Field(description="1-2 sentence explanation of why the target was found or not found")
    detail: Optional[str] = Field(default=None, description="XML element or text that matches the target, or null if not found")


# グローバル変数でモデル名を保持（外部から設定可能）
_verify_model_name: str = "gpt-4.1-mini"


def set_verify_model(model_name: str) -> None:
    """Set the model name used for verify_screen_content.
    
    Args:
        model_name: The model name to use (e.g., "gpt-4.1-mini", "gpt-4o")
    """
    global _verify_model_name
    _verify_model_name = model_name
    logger.info(f"🔧 Verify model set to: {model_name}")


def get_verify_model() -> str:
    """Get the current model name used for verify_screen_content."""
    return _verify_model_name


@tool("verify_screen_content", args_schema=VerifyScreenContentInput)
def verify_screen_content(target: str) -> str:
    """Verify that the specified content is displayed on the current screen.
    
    Uses LLM with both XML page source and screenshot to verify.
    Use this for confirmation steps like "利用規約ダイアログを確認する" or "エラーメッセージが表示されていることを確認する".
    
    Args:
        target: The target content to verify (e.g., "利用規約ダイアログ", "ログインボタン")
        
    Returns:
        A string indicating whether the target was found and evidence.
    """
    from .session import _driver
    
    if _driver is None:
        raise InvalidSessionIdException("No Appium session. Call start_session() first.")
    
    try:
        # take_screenshot と get_page_source ツールを使用
        # take_screenshot は既にJPEG変換・リサイズ済み、data URL形式で取得
        image_url = take_screenshot.invoke({"as_data_url": True})
        compressed_xml = get_page_source.invoke({})
        
        # Call LLM to verify with structured output
        base_model = ChatOpenAI(model=_verify_model_name, temperature=0)
        structured_model = base_model.with_structured_output(VerifyScreenContentResult)
        
        prompt = f"""あなたは画面確認アシスタントです。提供されたXMLソースとスクリーンショットを分析し、指定されたコンテンツが画面に表示されているかを確認してください。

【確認対象】
{target}

【XML Page Source】
```xml
{compressed_xml}
```

【判定基準】
1. XMLに確認対象に関連するテキストや要素が含まれているか
2. スクリーンショットに確認対象が視覚的に表示されているか
3. ダイアログの場合は、ダイアログの枠やオーバーレイがあるか

【回答】
- result: "FOUND" (確認対象が表示されている) または "NOT_FOUND" (表示されていない)
- reason: 確認対象が見つかった/見つからなかった根拠を1-2文で説明
- detail: 見つかった場合はXMLのどの要素やテキストが該当するかを記載。見つからなかった場合はnull"""

        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                            "detail": "high"
                        }
                    }
                ]
            )
        ]
        
        # with_structured_output で厳密にパース
        result_data: VerifyScreenContentResult = structured_model.invoke(messages)
        
        # テキスト形式に変換
        if result_data.result == "FOUND":
            logger.info(f"✅ verify_screen_content: '{target}' was FOUND on screen")
            detail_text = f"\n[詳細]: {result_data.detail}" if result_data.detail else ""
            return f"✅ 確認成功: '{target}' が画面に表示されています。\n\n[結果]: FOUND\n[根拠]: {result_data.reason}{detail_text}"
        else:
            logger.warning(f"❌ verify_screen_content: '{target}' was NOT_FOUND on screen")
            return f"❌ 確認失敗: '{target}' が画面に見つかりませんでした。\n\n[結果]: NOT_FOUND\n[根拠]: {result_data.reason}"
            
    except InvalidSessionIdException:
        raise
    except Exception as e:
        logger.error(f"❌ verify_screen_content failed: {e}")
        return f"❌ 確認中にエラーが発生しました: {str(e)}"
