"""
構造化ログ出力モジュール

コンソール出力（人間用）とJSONLファイル出力（LLM解析用）を分離して提供します。

使用例:
    from smartestiroid.utils.structured_logger import SLog, LogCategory, LogEvent

    # 初期化（テスト開始時）
    SLog.init("TEST_0001", Path("logs"))

    # ログ出力
    SLog.log(
        category=LogCategory.STEP,
        event=LogEvent.START,
        data={"step": "click_element", "target": "agree_button"},
        message="ステップ開始: click_element"
    )

    # 終了（テスト終了時）
    SLog.close()
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, TextIO


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
        level: str = "INFO"
    ):
        """ログを出力（コンソール + ファイル）

        Args:
            category: ログカテゴリ (TEST, STEP, TOOL, LLM, etc.)
            event: イベント種別 (START, END, EXECUTE, etc.)
            data: 構造化データ (dict)
            message: 人間向けサマリメッセージ
            level: ログレベル (DEBUG, INFO, WARN, ERROR)
        """
        if not cls._enabled:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
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
        """INFOレベルのログ出力"""
        cls.log(category, event, data, message, level="INFO")

    @classmethod
    def warn(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None
    ):
        """WARNレベルのログ出力"""
        cls.log(category, event, data, message, level="WARN")

    @classmethod
    def error(
        cls,
        category: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None
    ):
        """ERRORレベルのログ出力"""
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
            image_data: PNG画像のバイナリデータ
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
            filename = f"{cls._image_counter:04d}_{timestamp}{label_part}.png"
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
                level="INFO"
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
            base64_data: Base64エンコードされたPNG画像データ
            category: ログカテゴリ
            event: イベント種別
            label: 画像のラベル
            message: ログメッセージ
            
        Returns:
            保存した画像ファイルのパス（失敗時はNone）
        """
        import base64
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


# エイリアス（簡潔な呼び出し用）
SLog = StructuredLogger
