import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import base64
from PIL import Image
import io


SERVER_CONFIG = {
    "jarvis-appium": {
        "command": "/opt/homebrew/opt/node@20/bin/npx",
        "args": ["-y", "jarvis-appium"],
        "transport": "stdio",
        "env": {
            "CAPABILITIES_CONFIG": "/Users/raiko.funakami/GitHub/test_robot/capabilities.json",
            "ANDROID_HOME_SDK_ROOT": "/Users/raiko.funakami/Library/Android/sdk",
            "ANDROID_SDK_ROOT": "/Users/raiko.funakami/Library/Android/sdk",
        }
    },
    "jarvis-appium-sse": {
        "url": "http://localhost:7777/sse",
        "transport": "sse",
    },
}

async def main():
    client = MultiServerMCPClient(SERVER_CONFIG)
    async with client.session("jarvis-appium-sse") as session:
        tools = await load_mcp_tools(session)
        select_platform = next(t for t in tools if t.name == "select_platform")
        create_session = next(t for t in tools if t.name == "create_session")
        screenshot_tool = next(t for t in tools if t.name == "appium_screenshot")
        generate_locators = next(t for t in tools if t.name == "generate_locators")

        print("select_platform 実行...")
        platform = await select_platform.ainvoke({"platform": "android"})
        print("select_platform結果:", platform)

        print("create_session 実行...")
        session = await create_session.ainvoke({"platform": "android"})
        print("create_session結果:", session)
    
        print("screenshot_tool 実行...")
        screenshot = await screenshot_tool.ainvoke({})
        print("screenshot_tool 結果:", screenshot[:100])

        print("generate_locators 実行...")
        locator = await generate_locators.ainvoke({})
        print("generate_locators 結果:", locator[:100])

        if isinstance(screenshot, str) and screenshot:
            img_bytes = base64.b64decode(screenshot)
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode == "RGBA":
                img = img.convert("RGB")
            # 横幅1280px以上ならリサイズ
            if img.width > 1280:
                ratio = 1280 / img.width
                new_size = (1280, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            # JPEGで圧縮率80%で保存
            img.save("agent_screenshot.jpg", "JPEG", quality=80)
            print("agent_screenshot.jpg 保存完了")

            # Vision API用にJPEG形式でbase64化
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            img_bytes_jpeg = buf.getvalue()
            image_url = "data:image/jpeg;base64," + base64.b64encode(img_bytes_jpeg).decode()

            # LangChain ChatOpenAI (vision対応) で画像を入力
            llm = ChatOpenAI(
                model="gpt-4.1",
                temperature=0.0,
            )

            messages = [
                SystemMessage(content="あなたは優秀なモバイルアプリのUI解析アシスタントです。ユーザーの指示に合う最も適切な要素をロケータと画像の両方から判断してください。回答には必ず理由を添えてください。"),
                HumanMessage(content=[
                    {"type": "text", "text": "ツールバーに存在するGUIを教えて。画面構成のロケータ: " + str(locator)},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ])
            ]
            response = await llm.ainvoke(messages)
            print("GPTの判断 (with screenshot) :", response.content)
        else:
            print("スクリーンショット取得失敗")

if __name__ == "__main__":
    asyncio.run(main())
