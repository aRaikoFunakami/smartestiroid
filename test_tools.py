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
    for server_name in SERVER_CONFIG.keys():
        print(f"{server_name} ツール一覧:")
        async with client.session(server_name) as session:
            tools = await load_mcp_tools(session)
            for t in tools:
                print(f"- {t.name}")


if __name__ == "__main__":
    asyncio.run(main())
