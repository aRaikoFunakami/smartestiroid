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
    },
    "jarvis-appium-sse": {
        "url": "http://localhost:7777/sse",
        "transport": "sse",
    },
    "mobile-mcp": {
        "command": "/opt/homebrew/opt/node@20/bin/npx",
        "args": ["-y", "@mobilenext/mobile-mcp@latest"],
        "transport": "stdio",
    },
}

async def main():
    client = MultiServerMCPClient(SERVER_CONFIG)
    async with client.session("jarvis-appium-sse") as session:
        tools = await load_mcp_tools(session)
        print(f"jarvis-appium-sse 取得ツール数: {len(tools)}")
        for tool in tools:
            print(f"- {tool.name}")


if __name__ == "__main__":
    asyncio.run(main())
