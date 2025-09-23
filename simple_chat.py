import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from langchain.chat_models import init_chat_model
from event_logger import EventLogger

SERVER_CONFIG = {
    "jarvis-appium": {
        "command": "npx",
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
        llm = init_chat_model(model="gpt-4o", temperature=0)
        agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt=(
                "あなたはAppiumテストエージェントです。ユーザーの指示に従い、Androidデバイスを操作してください。"
            )
        )
        logger = EventLogger(verbose=True)
        print("インタラクティブモード開始。'exit'で終了")

        
        while True:
            user_input = input(">>> 入力: ").strip()
            if user_input.lower() in ("exit", "quit"):
                print("終了します。")
                break

            print("エージェント実行中...")
            post_task_message = """\nタスクを実行するために必要な操作を計画しなさい。
                ツールを使って計画を推進するために計画をブレークダウンしなさい
                失敗した場合の対処法を考えなさい
                次に計画に沿って１つ１つ実行しなさい。"""
            
            inputs = {"messages": [
                ("user", user_input),
                ("user", post_task_message)
            ]}
            async for event in agent.astream_events(inputs, version="v2"):
                logger.dispatch(event)
    print("セッション終了")

if __name__ == "__main__":
    asyncio.run(main())
