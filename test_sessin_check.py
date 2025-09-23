import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

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
    }
}

async def main():
    print("MCPクライアント初期化...")
    client = MultiServerMCPClient(SERVER_CONFIG)
    async with client.session("jarvis-appium") as session:
        print("セッション開始: jarvis-appium")
        tools = await load_mcp_tools(session)
        print(f"取得ツール数: {len(tools)}")
        # select_platform → create_session → generate_locators の流れをテスト
        select_platform = next(t for t in tools if t.name == "select_platform")
        create_session = next(t for t in tools if t.name == "create_session")
        generate_locators = next(t for t in tools if t.name == "generate_locators")

        print("select_platform 実行...")
        result1 = await select_platform.ainvoke({"platform": "android"})
        print("select_platform結果:", result1)

        print("create_session 実行...")
        result2 = await create_session.ainvoke({"platform": "android"})
        print("create_session結果:", result2)

        print("generate_locators 実行...")
        result3 = await generate_locators.ainvoke({})
        print("generate_locators結果:", result3)

    print("セッション終了")

if __name__ == "__main__":
    asyncio.run(main())
