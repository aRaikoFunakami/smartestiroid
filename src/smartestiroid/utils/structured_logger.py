"""
構造化ログ出力モジュール

コンソール出力（人間用）とJSONLファイル出力（LLM解析用）を分離して提供します。

使用例:
    from smartestiroid.utils.structured_logger import SLog, LogCategory, LogEvent

    # 初期化（テスト開始時）
    SLog.init("TEST_0001", Path("logs"))

    # ログ出力（基本）
    SLog.log(
        category=LogCategory.STEP,
        event=LogEvent.START,
        data={"step": "click_element", "target": "agree_button"},
        message="ステップ開始: click_element"
    )

    # 終了（テスト終了時）
    SLog.close()

====================================
⚠️ 重要: SLog.error / SLog.warn / SLog.info の引数順序
====================================

すべてのログメソッドは以下の引数順序を持ちます:

    SLog.error(category, event, data, message)
    SLog.warn(category, event, data, message)
    SLog.info(category, event, data, message)
    SLog.debug(category, event, data, message)

【正しい使い方】
    SLog.error(
        LogCategory.PLAN,      # 1. category（必須）
        LogEvent.FAIL,         # 2. event（必須）
        {"error": str(e)},     # 3. data（オプション）
        "エラーメッセージ"      # 4. message（オプション）
    )

【よくある間違い - 絶対に書いてはいけない】
    # ❌ NG: categoryとeventが欠落
    SLog.error({"error": str(e)}, "メッセージ")
    
    # ❌ NG: dataをcategoryに渡している
    SLog.warn({"key": "value"}, "メッセージ")

【例外ハンドラでの典型的な使い方】
    except Exception as e:
        SLog.error(
            LogCategory.PLAN,
            LogEvent.FAIL,
            {"error_type": type(e).__name__, "error": str(e)},
            f"処理に失敗: {e}"
        )
"""

import json
import base64
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, TextIO

# Allure のインポート（オプショナル）
try:
    import allure
    ALLURE_AVAILABLE = True
except ImportError:
    allure = None
    ALLURE_AVAILABLE = False


@dataclass
class AttachConfig:
    """カテゴリ別のAllure attach設定"""
    enabled: bool = True                    # attachするか
    attachment_type: str = "TEXT"           # TEXT, PNG, JPG, JSON
    name_template: str = "{icon} {category}: {event}"  # attach名テンプレート
    include_data: bool = True               # dataをattachに含めるか
    include_message: bool = True            # messageをattachに含めるか


class LogCategory:
    """ログカテゴリ定義"""
    # テスト実行
    TEST = "TEST"           # テスト開始/終了
    STEP = "STEP"           # ステップ実行
    TOOL = "TOOL"           # ツール呼び出し

    # LLM関連
    LLM = "LLM"             # LLM推論
    PLAN = "PLAN"           # プラン生成
    REPLAN = "REPLAN"       # リプラン
    ANALYZE = "ANALYZE"     # 画面分析
    DECIDE = "DECIDE"       # アクション決定

    # 進捗管理
    PROGRESS = "PROGRESS"   # 進捗更新
    OBJECTIVE = "OBJECTIVE" # 目標進捗

    # 画面関連
    SCREEN = "SCREEN"       # 画面状態/遷移
    DIALOG = "DIALOG"       # ダイアログ処理

    # システム
    SESSION = "SESSION"     # セッション管理
    CONFIG = "CONFIG"       # 設定
    ERROR = "ERROR"         # エラー
    TOKEN = "TOKEN"         # トークン使用量


class LogEvent:
    """ログイベント定義"""
    # ライフサイクル
    START = "START"
    END = "END"

    # 実行
    EXECUTE = "EXECUTE"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"
    SKIP = "SKIP"
    RETRY = "RETRY"

    # 状態変化
    UPDATE = "UPDATE"
    CHANGE = "CHANGE"

    # 判定
    ACHIEVED = "ACHIEVED"
    NOT_ACHIEVED = "NOT_ACHIEVED"

    # LLM関連
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    VERIFY_REQUEST = "VERIFY_REQUEST"
    VERIFY_RESPONSE = "VERIFY_RESPONSE"

    # 画面整合性
    INCONSISTENCY_DETECTED = "INCONSISTENCY_DETECTED"
    INCONSISTENCY_RESOLVED = "INCONSISTENCY_RESOLVED"
    INCONSISTENCY_PERSISTENT = "INCONSISTENCY_PERSISTENT"
    
    # セッション関連
    COLLECT = "COLLECT"  # テスト収集完了
    SUMMARY = "SUMMARY"  # テスト結果サマリー


class StructuredLogger:
    """構造化ログ出力クラス（コンソール + JSONファイル分離）

    シングルトンパターンでクラスメソッドとして使用します。
    """

    _log_file: Optional[Path] = None
    _file_handle: Optional[TextIO] = None
    _test_id: Optional[str] = None
    _log_dir: Optional[Path] = None
    _images_dir: Optional[Path] = None  # 画像保存ディレクトリ
    _image_counter: int = 0  # 画像カウンター
    _enabled: bool = True  # ログ出力の有効/無効

    # イベント別アイコン
    ICONS = {
        "START": "🚀",
        "END": "🏁",
        "EXECUTE": "🔧",
        "COMPLETE": "✅",
        "FAIL": "❌",
        "SKIP": "⏭️",
        "RETRY": "🔄",
        "ACHIEVED": "🎯",
        "NOT_ACHIEVED": "📍",
        "UPDATE": "📊",
        "CHANGE": "🔀",
        "REQUEST": "📤",
        "RESPONSE": "📥",
        "VERIFY_REQUEST": "🔍",
        "VERIFY_RESPONSE": "✔️",
        "INCONSISTENCY_DETECTED": "⚠️",
        "INCONSISTENCY_RESOLVED": "✅",
        "INCONSISTENCY_PERSISTENT": "❌",
    }

    # カテゴリ別プレフィックス
    CATEGORY_PREFIX = {
        "TEST": "[TEST]",
        "STEP": "[STEP]",
        "TOOL": "[TOOL]",
        "LLM": "[LLM]",
        "PLAN": "[PLAN]",
        "REPLAN": "[REPLAN]",
        "ANALYZE": "[ANALYZE]",
        "DECIDE": "[DECIDE]",
        "PROGRESS": "[PROGRESS]",
        "OBJECTIVE": "[OBJECTIVE]",
        "SCREEN": "[SCREEN]",
        "SESSION": "[SESSION]",
        "CONFIG": "[CONFIG]",
        "ERROR": "[ERROR]",
        "TOKEN": "[TOKEN]",
    }

    # カテゴリ別のAllure attach設定
    ATTACH_CONFIG: Dict[str, AttachConfig] = {
        # === テスト実行 ===
        "TEST": AttachConfig(
            enabled=True,
            name_template="{icon} Test: {event}",
        ),
        "STEP": AttachConfig(
            enabled=True,
            name_template="{icon} Step: {message_short}",
        ),
        "TOOL": AttachConfig(
            enabled=False,  # ツール詳細はAllureLoggerで処理
        ),
        
        # === LLM関連 ===
        "LLM": AttachConfig(
            enabled=True,
            name_template="{icon} LLM: {event}",
        ),
        "PLAN": AttachConfig(
            enabled=True,
            name_template="📋 Plan: {event}",
        ),
        "REPLAN": AttachConfig(
            enabled=True,
            name_template="🔄 Replan: {event}",
        ),
        "ANALYZE": AttachConfig(
            enabled=True,
            name_template="🔍 Analysis: {event}",
        ),
        "DECIDE": AttachConfig(
            enabled=True,
            name_template="⚖️ Decision: {event}",
        ),
        
        # === 進捗管理 ===
        "PROGRESS": AttachConfig(
            enabled=True,
            name_template="📊 Progress: {event}",
        ),
        "OBJECTIVE": AttachConfig(
            enabled=True,
            name_template="🎯 Objective: {event}",
        ),
        
        # === 画面関連 ===
        "SCREEN": AttachConfig(
            enabled=True,
            name_template="📱 Screen: {event}",
        ),
        "DIALOG": AttachConfig(
            enabled=True,
            name_template="🔒 Dialog: {event}",
        ),
        
        # === システム ===
        "SESSION": AttachConfig(
            enabled=False,  # セッション管理はattach不要
        ),
        "CONFIG": AttachConfig(
            enabled=False,  # 設定はattach不要
        ),
        "ERROR": AttachConfig(
            enabled=True,
            name_template="❌ Error: {event}",
        ),
        "TOKEN": AttachConfig(
            enabled=False,  # トークン使用量はattach不要
        ),
    }

    @classmethod
    def init(cls, test_id: str, output_dir: Optional[Path] = None):
        """ログファイルを初期化

        Args:
            test_id: テストID（ファイル名に使用）
            output_dir: 出力ディレクトリ（デフォルト: カレントディレクトリ/logs）
        """
        cls._test_id = test_id
        cls._log_dir = output_dir or Path(".") / "logs"
        cls._log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cls._log_file = cls._log_dir / f"smartestiroid_{test_id}_{timestamp}.jsonl"
        cls._file_handle = open(cls._log_file, "w", encoding="utf-8")
        
        # 画像保存ディレクトリを作成
        cls._images_dir = cls._log_dir / f"smartestiroid_{test_id}_{timestamp}_images"
        cls._images_dir.mkdir(parents=True, exist_ok=True)
        cls._image_counter = 0

        # 初期化ログ
        cls.log(
            category=LogCategory.SESSION,
            event=LogEvent.START,
            data={"test_id": test_id, "log_file": str(cls._log_file)},
            message=f"ログ初期化: {cls._log_file.name}"
        )

    @classmethod
    def close(cls):
        """ログファイルをクローズ"""
        if cls._file_handle:
            cls.log(
                category=LogCategory.SESSION,
                event=LogEvent.END,
                data={"test_id": cls._test_id},
                message="ログ終了"
            )
            cls._file_handle.close()
            cls._file_handle = None

    @classmethod
    def set_enabled(cls, enabled: bool):
        """ログ出力の有効/無効を設定"""
        cls._enabled = enabled

    @classmethod
    def log(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
        level: str = "INFO",
        attach_to_allure: bool = False
    ):
        """ログを出力（コンソール + ファイル + Allure）

        Args:
            category: ログカテゴリ (TEST, STEP, TOOL, LLM, etc.)
            event: イベント種別 (START, END, EXECUTE, etc.)
            data: 構造化データ (dict)
            message: 人間向けサマリメッセージ
            level: ログレベル (DEBUG, INFO, WARN, ERROR)
            attach_to_allure: Allureにattachするか（デフォルトFalse）
        """
        if not cls._enabled:
            return

        timestamp_full = datetime.now().isoformat()

        # === ファイル出力（JSON Lines） ===
        if cls._file_handle:
            log_entry: Dict[str, Any] = {
                "ts": timestamp_full,
                "lvl": level,
                "cat": category,
                "evt": event,
            }
            if data:
                log_entry["data"] = data
            if message:
                log_entry["msg"] = message
            cls._file_handle.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            cls._file_handle.flush()

        # === コンソール出力（人間用） ===
        if message:
            icon = cls._get_icon(event, level)
            prefix = cls.CATEGORY_PREFIX.get(category, f"[{category}]")
            print(f"{icon} {prefix} {message}")

        # === Allure attach ===
        if attach_to_allure:
            cls._attach_to_allure(category, event, data, message, level)

    @classmethod
    def _format_llm_prompt(cls, data: Dict[str, Any], message: Optional[str]) -> str:
        """LLMプロンプトを人間が読みやすい形式に整形
        
        Args:
            data: ログデータ（method, model, prompt等を含む）
            message: ログメッセージ
            
        Returns:
            整形されたプロンプト文字列
        """
        lines = []
        
        # ヘッダー情報
        method = data.get("method", "unknown")
        model = data.get("model", "unknown")
        
        lines.append(f"# {method}")
        lines.append(f"# Model: {model}")
        
        # 画像の有無
        has_image = data.get("has_image") or data.get("has_current_image") or data.get("has_previous_image")
        if has_image:
            lines.append(f"# Has Image: Yes")
        
        lines.append("")
        lines.append("=" * 60)
        lines.append("")
        
        # プロンプト本文
        prompt = data.get("prompt") or data.get("system_prompt") or ""
        if prompt:
            prompt_str = str(prompt)
            # 長すぎる場合は切り詰め
            if len(prompt_str) > 50000:
                prompt_str = prompt_str[:50000] + "\n\n... (truncated, original length: {:,} chars)".format(len(prompt))
            lines.append(prompt_str)
        
        # user_prompt がある場合（analyze_screen等）
        user_prompt = data.get("user_prompt")
        if user_prompt:
            lines.append("")
            lines.append("-" * 40)
            lines.append("# User Prompt:")
            lines.append(str(user_prompt))
        
        return "\n".join(lines)

    @classmethod
    def _format_llm_response(cls, category: str, data: Dict[str, Any], message: Optional[str]) -> str:
        """LLMレスポンスを人間が読みやすい形式に整形
        
        Args:
            category: ログカテゴリ
            data: ログデータ
            message: ログメッセージ
            
        Returns:
            整形されたレスポンス文字列
        """
        lines = []
        
        # ヘッダー
        lines.append(f"# LLM Response: {category}")
        if data.get("model"):
            lines.append(f"# Model: {data.get('model')}")
        lines.append("")
        lines.append("=" * 60)
        lines.append("")
        
        # サマリー
        if message:
            lines.append(f"## Summary")
            lines.append(message)
            lines.append("")
        
        # reasoning は改行を維持して読みやすく表示
        reasoning = data.get("reasoning")
        if reasoning:
            lines.append("## Reasoning")
            lines.append(str(reasoning))
            lines.append("")
        
        # steps は見やすくリスト表示
        steps = data.get("steps")
        if steps and isinstance(steps, list):
            lines.append(f"## Steps ({len(steps)} items)")
            for i, step in enumerate(steps, 1):
                lines.append(f"  {i}. {step}")
            lines.append("")
        
        # その他のデータをJSON表示（reasoning, stepsは除外）
        excluded_keys = {"reasoning", "steps", "model"}
        other_data = {k: v for k, v in data.items() if k not in excluded_keys}
        if other_data:
            lines.append("## Other Data")
            lines.append(json.dumps(other_data, ensure_ascii=False, indent=2))
        
        return "\n".join(lines)

    @classmethod
    def _attach_to_allure(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
        level: str = "INFO"
    ) -> None:
        """Allure にデータをattachする
        
        Args:
            category: ログカテゴリ
            event: イベント種別
            data: 構造化データ
            message: メッセージ
            level: ログレベル
        """
        if not ALLURE_AVAILABLE or allure is None:
            return
        
        # 設定を取得
        config = cls.ATTACH_CONFIG.get(category)
        if config is None or not config.enabled:
            return
        
        try:
            # === LLMプロンプトの特別処理 ===
            if category == LogCategory.LLM and event == LogEvent.START and data:
                method = data.get("method", "unknown")
                formatted_content = cls._format_llm_prompt(data, message)
                allure.attach(
                    formatted_content,
                    name=f"🤔 LLM Prompt: {method}",
                    attachment_type=allure.attachment_type.TEXT
                )
                return
            
            # === LLMレスポンスの特別処理 ===
            # LLM呼び出し後のCOMPLETE/FAILイベント（特定のカテゴリ）
            llm_response_categories = {"SCREEN", "OBJECTIVE", "PLAN", "ANALYZE", "DIALOG", "TEST"}
            if category in llm_response_categories and event in (LogEvent.COMPLETE, LogEvent.FAIL) and data:
                formatted_content = cls._format_llm_response(category, data, message)
                icon = "💡" if event == LogEvent.COMPLETE else "❌"
                allure.attach(
                    formatted_content,
                    name=f"{icon} LLM Response: {category}",
                    attachment_type=allure.attachment_type.TEXT
                )
                return
            
            # アイコンを取得
            icon = cls._get_icon(event, level)
            
            # 短縮メッセージ（テンプレート用）
            message_short = (message[:50] + "...") if message and len(message) > 50 else (message or event)
            
            # attach名を生成
            name = config.name_template.format(
                icon=icon,
                category=category,
                event=event,
                message_short=message_short,
                level=level
            )
            
            # === 画像データの特別処理 ===
            if data:
                # screenshot_base64 があれば画像としてattach
                if "screenshot_base64" in data:
                    try:
                        screenshot_data = data["screenshot_base64"]
                        # 画像フォーマットを判定
                        if "data:image/png;base64," in screenshot_data:
                            attachment_type = allure.attachment_type.PNG
                            clean_data = screenshot_data.replace("data:image/png;base64,", "")
                        else:
                            # デフォルトはJPEG（data:image/jpeg;base64, または プレフィックスなし）
                            attachment_type = allure.attachment_type.JPG
                            clean_data = screenshot_data.replace("data:image/jpeg;base64,", "")
                        
                        image_bytes = base64.b64decode(clean_data)
                        allure.attach(
                            image_bytes,
                            name=f"📷 {message_short}" if message else "📷 Screenshot",
                            attachment_type=attachment_type
                        )
                    except Exception:
                        pass  # 画像デコード失敗は無視
                    
                    # screenshot_base64以外のデータがあれば続行
                    data_without_screenshot = {k: v for k, v in data.items() if k != "screenshot_base64"}
                    if not data_without_screenshot and not message:
                        return  # 他にattachするものがない
                    data = data_without_screenshot
                
                # image_path があれば画像ファイルをattach
                if "image_path" in data:
                    try:
                        image_path = Path(data["image_path"])
                        if image_path.exists():
                            label = data.get('label') or 'Screenshot'
                            # ファイル形式を自動判定
                            if image_path.suffix.lower() == '.png':
                                attachment_type = allure.attachment_type.PNG
                            else:
                                attachment_type = allure.attachment_type.JPG
                            
                            # ファイルを読み込んでバイト列としてアタッチ
                            with open(image_path, "rb") as f:
                                image_bytes = f.read()
                            
                            allure.attach(
                                image_bytes,
                                name=f"📷 {label}",
                                attachment_type=attachment_type
                            )
                            # 画像をアタッチした場合はテキストはアタッチしない
                            return
                    except Exception as e:
                        # 画像添付失敗時はエラーログを出力して続行
                        print(f"⚠️  Allure画像添付失敗: {e}")
            
            # === テキストデータのattach ===
            content_parts = []
            if config.include_message and message:
                content_parts.append(message)
            if config.include_data and data:
                # 大きなデータは省略
                data_str = json.dumps(data, ensure_ascii=False, indent=2, default=str)
                if len(data_str) > 10000:
                    data_str = data_str[:10000] + "\n... (truncated)"
                content_parts.append(f"\n--- Data ---\n{data_str}")
            
            if content_parts:
                content = "\n".join(content_parts)
                allure.attach(
                    content,
                    name=name,
                    attachment_type=allure.attachment_type.TEXT
                )
        except Exception:
            pass  # Allure attach失敗は無視

    @classmethod
    def _get_icon(cls, event: str, level: str) -> str:
        """イベントとレベルに応じたアイコンを返す"""
        if level == "ERROR":
            return "❌"
        if level == "WARN":
            return "⚠️"
        return cls.ICONS.get(event, "📍")

    @classmethod
    def debug(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None
    ):
        """DEBUGレベルのログ出力（ファイルのみ、コンソールには出力しない）"""
        if not cls._enabled:
            return

        timestamp_full = datetime.now().isoformat()

        # ファイル出力のみ
        if cls._file_handle:
            log_entry: Dict[str, Any] = {
                "ts": timestamp_full,
                "lvl": "DEBUG",
                "cat": category,
                "evt": event,
            }
            if data:
                log_entry["data"] = data
            if message:
                log_entry["msg"] = message
            cls._file_handle.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            cls._file_handle.flush()

    @classmethod
    def info(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None
    ):
        """INFOレベルのログ出力
        
        Args:
            category: LogCategory.* (例: LogCategory.STEP, LogCategory.PLAN)
            event: LogEvent.* (例: LogEvent.START, LogEvent.COMPLETE)
            data: 追加データ（辞書）
            message: 人間向けメッセージ
        
        Example:
            SLog.info(LogCategory.STEP, LogEvent.START, {"step": "click"}, "ステップ開始")
        """
        cls.log(category, event, data, message, level="INFO")

    @classmethod
    def warn(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None
    ):
        """WARNレベルのログ出力
        
        Args:
            category: LogCategory.* (例: LogCategory.SCREEN, LogCategory.REPLAN)
            event: LogEvent.* (例: LogEvent.RETRY, LogEvent.SKIP)
            data: 追加データ（辞書）
            message: 人間向けメッセージ
        
        Example:
            SLog.warn(LogCategory.SCREEN, LogEvent.RETRY, {"count": 2}, "リトライ中")
        
        ⚠️ 注意: 最初の2引数(category, event)は必須です。
           ❌ 誤: SLog.warn({"key": "val"}, "msg")
           ✅ 正: SLog.warn(LogCategory.X, LogEvent.Y, {"key": "val"}, "msg")
        """
        cls.log(category, event, data, message, level="WARN")

    @classmethod
    def error(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None
    ):
        """ERRORレベルのログ出力
        
        Args:
            category: LogCategory.* (例: LogCategory.PLAN, LogCategory.OBJECTIVE)
            event: LogEvent.* (例: LogEvent.FAIL)
            data: 追加データ（辞書）- 通常 {"error": str(e)} など
            message: 人間向けメッセージ
        
        Example:
            except Exception as e:
                SLog.error(
                    LogCategory.PLAN,
                    LogEvent.FAIL,
                    {"error_type": type(e).__name__, "error": str(e)},
                    f"計画生成失敗: {e}"
                )
        
        ⚠️ 注意: 最初の2引数(category, event)は必須です。
           ❌ 誤: SLog.error({"error": str(e)}, "msg")
           ✅ 正: SLog.error(LogCategory.X, LogEvent.FAIL, {"error": str(e)}, "msg")
        """
        cls.log(category, event, data, message, level="ERROR")

    @classmethod
    def get_log_file(cls) -> Optional[Path]:
        """現在のログファイルパスを取得"""
        return cls._log_file

    @classmethod
    def get_images_dir(cls) -> Optional[Path]:
        """画像保存ディレクトリを取得"""
        return cls._images_dir

    @classmethod
    def save_screenshot(
        cls,
        image_data: bytes,
        category: str = "SCREEN",
        event: str = "UPDATE",
        label: Optional[str] = None,
        message: Optional[str] = None
    ) -> Optional[Path]:
        """スクリーンショットを保存してログに記録
        
        Args:
            image_data: JPEG画像のバイナリデータ
            category: ログカテゴリ
            event: イベント種別
            label: 画像のラベル（ファイル名に使用）
            message: ログメッセージ
            
        Returns:
            保存した画像ファイルのパス（失敗時はNone）
        """
        if not cls._enabled or not cls._images_dir:
            return None
        
        try:
            cls._image_counter += 1
            timestamp = datetime.now().strftime("%H%M%S")
            label_part = f"_{label}" if label else ""
            filename = f"{cls._image_counter:04d}_{timestamp}{label_part}.jpg"
            image_path = cls._images_dir / filename
            
            # 画像を保存
            with open(image_path, "wb") as f:
                f.write(image_data)
            
            # ログに記録（画像パスを含む）
            cls.log(
                category=category,
                event=event,
                data={
                    "image_path": str(image_path),
                    "image_filename": filename,
                    "image_size_bytes": len(image_data),
                    "label": label,
                },
                message=message or f"Screenshot saved: {filename}",
                level="INFO",
                attach_to_allure=True  # スクリーンショットは常にAllureにattach
            )
            
            return image_path
        except Exception as e:
            cls.warn(
                category=category,
                event=LogEvent.FAIL,
                data={"error": str(e)},
                message=f"Screenshot save failed: {e}"
            )
            return None

    @classmethod
    def save_screenshot_base64(
        cls,
        base64_data: str,
        category: str = "SCREEN",
        event: str = "UPDATE",
        label: Optional[str] = None,
        message: Optional[str] = None
    ) -> Optional[Path]:
        """Base64エンコードされたスクリーンショットを保存
        
        Args:
            base64_data: Base64エンコードされたJPEG画像データ
            category: ログカテゴリ
            event: イベント種別
            label: 画像のラベル
            message: ログメッセージ
            
        Returns:
            保存した画像ファイルのパス（失敗時はNone）
        """
        try:
            image_data = base64.b64decode(base64_data)
            return cls.save_screenshot(image_data, category, event, label, message)
        except Exception as e:
            cls.warn(
                category=category,
                event=LogEvent.FAIL,
                data={"error": str(e)},
                message=f"Base64 decode failed: {e}"
            )
            return None

    @classmethod
    def attach_screenshot(
        cls,
        base64_data: str,
        label: Optional[str] = None,
        message: Optional[str] = None
    ) -> Optional[Path]:
        """スクリーンショットを保存してAllureにもattach
        
        Args:
            base64_data: Base64エンコードされた画像（data:image/...形式も可）
            label: 画像ラベル
            message: ログメッセージ
            
        Returns:
            保存したファイルのパス
        """
        # data URL形式の場合はプレフィックスを除去
        clean_data = (base64_data
            .replace("data:image/jpeg;base64,", "")
            .replace("data:image/png;base64,", ""))
        
        # ファイルに保存（これ自体がAllure attachも行う）
        path = cls.save_screenshot_base64(
            clean_data,
            category=LogCategory.SCREEN,
            event=LogEvent.UPDATE,
            label=label,
            message=message
        )
        
        return path

    @classmethod
    def attach_locator_info(
        cls,
        ui_elements: str,
        label: str = "Locator Information"
    ) -> None:
        """ロケーター情報をログとAllureに出力
        
        Args:
            ui_elements: UIエレメント情報（XML等）
            label: ラベル
        """
        # ログ出力（Allure attachは内部で自動実行）
        cls.debug(
            category=LogCategory.SCREEN,
            event=LogEvent.UPDATE,
            data={"locator_info_length": len(ui_elements)},
            message=f"📍 {label}"
        )
        
        # debugはattach_to_allureを呼ばないので、別途attachが必要
        if ALLURE_AVAILABLE and allure is not None:
            try:
                allure.attach(
                    ui_elements,
                    name=f"📍 {label}",
                    attachment_type=allure.attachment_type.TEXT
                )
            except Exception:
                pass

    @classmethod
    def attach_text(
        cls,
        content: str,
        name: str,
        category: str = "STEP",
        event: str = "UPDATE"
    ) -> None:
        """テキストをAllureに直接attach（ログ出力なし）
        
        Args:
            content: attachするテキスト内容
            name: attach名
            category: ログカテゴリ（設定参照用）
            event: イベント種別
        """
        if ALLURE_AVAILABLE and allure is not None:
            try:
                allure.attach(
                    content,
                    name=name,
                    attachment_type=allure.attachment_type.TEXT
                )
            except Exception:
                pass


# エイリアス（簡潔な呼び出し用）
SLog = StructuredLogger
