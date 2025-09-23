import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import Tool
from langgraph.prebuilt import create_react_agent
from langchain.chat_models import init_chat_model

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

        # LangChain ReAct Agentの作成
        llm = init_chat_model(model="gpt-4o", temperature=0)
        agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt="あなたはAppiumテストエージェントです。select_platform→create_session→generate_locatorsの順でAndroid画面解析を自動で行ってください。"
        )

        # エージェントに指示を与える
        user_input = "Android画面の要素を解析してください"
        print(f"エージェント入力: {user_input}")
        result = await agent.ainvoke({"input": user_input})
        print("エージェント出力:", result)

    print("セッション終了")

if __name__ == "__main__":
    asyncio.run(main())
