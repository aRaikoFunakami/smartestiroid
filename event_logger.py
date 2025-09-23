import time
import allure
from colorama import Fore, init

init(autoreset=True)

class EventLogger:
    """Pretty-Logger for LangGraph astream_events.
    This class prints only observable signals (no chain-of-thought):
    - node start/end
    - LLM streaming tokens (optional)
    - final LLM outputs when provider buffers
    - tool start/end with args and outputs
    Configuration can be passed at construction for reuse.
    """

    def __init__(self,
                 verbose: bool = False):
        self.verbose = verbose
        self.event_log = []  # イベントログを保持

    def _log_and_attach(self, message: str, event_type: str = "Event"):
        """print実行とallure.attachを両方行うラッパー関数
        
        Args:
            message: ログメッセージ
            event_type: イベントタイプ（Allure添付時の名前に使用）
        """
        # コンソールに出力
        print(Fore.BLUE + message)
        
        # イベントログに追加
        self.event_log.append(f"{time.time():.3f}: {message}")
        
        # Allureに添付（リアルタイム）
        try:
            allure.attach(
                message,
                name=f"Agent {event_type}",
                attachment_type=allure.attachment_type.TEXT
            )
        except Exception:
            # Allure添付失敗は無視（テスト実行は継続）
            pass

    def get_complete_log(self) -> str:
        """完全なイベントログを取得"""
        return "\n".join(self.event_log)

    def attach_complete_log(self):
        """完全なイベントログをAllureに添付"""
        try:
            complete_log = self.get_complete_log()
            allure.attach(
                complete_log,
                name="Complete Agent Log",
                attachment_type=allure.attachment_type.TEXT
            )
        except Exception:
            pass

    def info(self, message: str):
        """情報メッセージをログ出力"""
        print(Fore.CYAN + f"ℹ️  {message}")
        self.event_log.append(f"{time.time():.3f}: INFO: {message}")

    def success(self, message: str):
        """成功メッセージをログ出力"""
        print(Fore.GREEN + f"✅ {message}")
        self.event_log.append(f"{time.time():.3f}: SUCCESS: {message}")

    def error(self, message: str):
        """エラーメッセージをログ出力"""
        print(Fore.RED + f"❌ {message}")
        self.event_log.append(f"{time.time():.3f}: ERROR: {message}")

    def warning(self, message: str):
        """警告メッセージをログ出力"""
        print(Fore.YELLOW + f"⚠️  {message}")
        self.event_log.append(f"{time.time():.3f}: WARNING: {message}")

    def debug(self, message: str):
        """デバッグメッセージをログ出力（verbose時のみ）"""
        if self.verbose:
            print(Fore.MAGENTA + f"🔍 {message}")
        self.event_log.append(f"{time.time():.3f}: DEBUG: {message}")

    # --- public handlers ---
    def on_node_start(self, ev):
        """ノード開始時のログ処理"""
        name = ev.get("name") or "<node>"
        message = f"Starting node: {name}"
        self._log_and_attach(f"[NODE:START] {message}", "Node Start")

    def on_node_end(self, ev):
        """ノード終了時のログ処理"""
        name = ev.get("name") or "<node>"
        d = ev.get("data", {})
        output = d.get("output", "")
        message = f"Finished node: {name}"
        if output:
            message += f" with output: {str(output)[:200]}..."  # 長いoutputは切り詰め
        self._log_and_attach(f"[NODE:END] {message}", "Node End")

    def on_tool_start(self, ev):
        d = ev.get("data", {})
        name = ev.get("name") or "<tool>"
        message = f"{name} args={d.get('input')}"
        self._log_and_attach(f"[TOOL:START] {message}", "Tool Start")

    def on_tool_end(self, ev):
        d = ev.get("data", {})
        name = ev.get("name") or "<tool>"
        output_content = d.get('output')
        
        if hasattr(output_content, 'content'):
            output_display = output_content.content
        else:
            output_display = str(output_content)

        message = f"{name} output={output_display}"
        self._log_and_attach(f"[TOOL:END] {message}", "Tool End")

    def _print_on_chat_model_end(self, ev):
        # ev['data']['output'] が AIMessage インスタンス
        message = ev['data']['output'].content
        self._log_and_attach(f"[MODEL:END] {message}", "Model Output")

    def _print_on_chain_start(self, ev):
        if self.verbose:
            self._log_and_attach(f"[CHAIN:START] {ev.get('name')}","Chain Start")

    def _print_on_chain_end(self, ev):
        data = ev.get('data', {})
        output = data.get('output')
        if ev.get('name') == 'should_continue' and output:
            message = "should_continue, " + (output if not isinstance(output, list) else str(output[0]))
            self._log_and_attach(f"[CHAIN:END] {message}", "Chain Decision")
        elif self.verbose:
            self._log_and_attach(f"[CHAIN:END] {ev.get('name')}", "Chain End")

    def dispatch(self, ev):
        et = ev.get("event", "")
        
        if et.endswith("node_start"):
            self.on_node_start(ev)
        elif et.endswith("node_end"):
            self.on_node_end(ev)
        elif et.endswith("tool_start"):
            self.on_tool_start(ev)
        elif et.endswith("tool_end"):
            self.on_tool_end(ev)
        elif et.endswith("on_chat_model_end"):
            self._print_on_chat_model_end(ev)
        elif et.endswith("on_chain_start"):
            self._print_on_chain_start(ev)
        elif et.endswith("on_chain_end"):
            self._print_on_chain_end(ev)