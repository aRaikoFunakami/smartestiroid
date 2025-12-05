# Allure Attach 統一化 詳細設計書

## 1. 概要

### 1.1 目的
現在プロジェクト全体に散在している `allure.attach()` 呼び出しを、`SLog.log()` 内で自動的にattachする仕組みに統一する。

### 1.2 現状の問題
- `allure.attach()` が約50箇所に散在
  - `workflow.py`: 約25箇所
  - `simple_planner.py`: 約7箇所
  - `multi_stage_replanner.py`: 1箇所
  - `conftest.py`: 2箇所
- attachの形式やネーミングが不統一
- ログ出力と別にattachを書く必要があり、コードが冗長

### 1.3 採用方針
**SLog.log() 呼び出し時に自動的に allure.attach を実行する方式**

メリット:
- ログ出力と Allure attach が1回の呼び出しで完結
- ステップ実行ごとの確認性を維持
- コードがシンプルになる
- 一貫したネーミングと形式を保証

---

## 2. アーキテクチャ

### 2.1 コンポーネント構成

```
structured_logger.py
├── StructuredLogger (SLog)
│   ├── log()           ← 既存: コンソール + JSONL出力
│   ├── _attach_to_allure()  ← 新規: Allure attach処理
│   └── save_screenshot()    ← 既存: 画像保存
│
└── AttachConfig        ← 新規: カテゴリ別attach設定
```

### 2.2 処理フロー

```
SLog.log() 呼び出し
    │
    ├─→ コンソール出力（既存）
    │
    ├─→ JSONL ファイル出力（既存）
    │
    └─→ _attach_to_allure() 呼び出し（新規）
            │
            ├─→ カテゴリに応じたattach形式を決定
            │
            ├─→ dataにscreenshotがあれば画像としてattach
            │
            └─→ それ以外はTEXT形式でattach
```

---

## 3. 詳細設計

### 3.1 AttachConfig クラス

```python
from dataclasses import dataclass
from typing import Optional, Callable
import allure

@dataclass
class AttachConfig:
    """カテゴリ別のAllure attach設定"""
    enabled: bool = True                    # attachするか
    attachment_type: str = "TEXT"           # TEXT, PNG, JPG, JSON
    name_template: str = "{icon} {category}: {event}"  # attach名テンプレート
    include_data: bool = True               # dataをattachに含めるか
    include_message: bool = True            # messageをattachに含めるか
```

### 3.2 カテゴリ別のattach設定

```python
ATTACH_CONFIG: Dict[str, AttachConfig] = {
    # === テスト実行 ===
    LogCategory.TEST: AttachConfig(
        enabled=True,
        name_template="{icon} Test: {event}",
        include_data=True
    ),
    LogCategory.STEP: AttachConfig(
        enabled=True,
        name_template="{icon} Step: {message_short}",
        include_data=True
    ),
    LogCategory.TOOL: AttachConfig(
        enabled=False,  # ツール詳細はAllureLoggerで処理
    ),
    
    # === LLM関連 ===
    LogCategory.LLM: AttachConfig(
        enabled=True,
        name_template="{icon} LLM: {event}",
        include_data=True
    ),
    LogCategory.PLAN: AttachConfig(
        enabled=True,
        name_template="📋 Plan: {event}",
        include_data=True
    ),
    LogCategory.REPLAN: AttachConfig(
        enabled=True,
        name_template="🔄 Replan: {event}",
        include_data=True
    ),
    LogCategory.ANALYZE: AttachConfig(
        enabled=True,
        name_template="🔍 Analysis: {event}",
        include_data=True
    ),
    LogCategory.DECIDE: AttachConfig(
        enabled=True,
        name_template="⚖️ Decision: {event}",
        include_data=True
    ),
    
    # === 進捗管理 ===
    LogCategory.PROGRESS: AttachConfig(
        enabled=True,
        name_template="📊 Progress: {event}",
        include_data=True
    ),
    LogCategory.OBJECTIVE: AttachConfig(
        enabled=True,
        name_template="🎯 Objective: {event}",
        include_data=True
    ),
    
    # === 画面関連 ===
    LogCategory.SCREEN: AttachConfig(
        enabled=True,
        name_template="📱 Screen: {event}",
        include_data=True
    ),
    LogCategory.DIALOG: AttachConfig(
        enabled=True,
        name_template="🔒 Dialog: {event}",
        include_data=True
    ),
    
    # === システム ===
    LogCategory.SESSION: AttachConfig(
        enabled=False,  # セッション管理はattach不要
    ),
    LogCategory.CONFIG: AttachConfig(
        enabled=False,  # 設定はattach不要
    ),
    LogCategory.ERROR: AttachConfig(
        enabled=True,
        name_template="❌ Error: {event}",
        include_data=True
    ),
    LogCategory.TOKEN: AttachConfig(
        enabled=False,  # トークン使用量はattach不要
    ),
}
```

### 3.3 _attach_to_allure() メソッド

```python
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
    try:
        import allure
    except ImportError:
        return  # allureが利用できない場合は何もしない
    
    # 設定を取得
    config = cls.ATTACH_CONFIG.get(category)
    if config is None or not config.enabled:
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
                import base64
                image_bytes = base64.b64decode(
                    data["screenshot_base64"].replace("data:image/jpeg;base64,", "")
                    .replace("data:image/png;base64,", "")
                )
                allure.attach(
                    image_bytes,
                    name=f"📷 {message_short}" if message else f"📷 Screenshot",
                    attachment_type=allure.attachment_type.PNG
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
                from pathlib import Path
                image_path = Path(data["image_path"])
                if image_path.exists():
                    allure.attach.file(
                        str(image_path),
                        name=f"📷 {data.get('label', 'Screenshot')}",
                        attachment_type=allure.attachment_type.PNG
                    )
            except Exception:
                pass
    
    # === テキストデータのattach ===
    content_parts = []
    if config.include_message and message:
        content_parts.append(message)
    if config.include_data and data:
        import json
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
```

### 3.4 log() メソッドの変更

```python
@classmethod
def log(
    cls,
    category: str,
    event: str,
    data: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    level: str = "INFO",
    attach_to_allure: bool = True  # 新規パラメータ
):
    """ログを出力（コンソール + ファイル + Allure）

    Args:
        category: ログカテゴリ
        event: イベント種別
        data: 構造化データ
        message: 人間向けサマリメッセージ
        level: ログレベル
        attach_to_allure: Allureにattachするか（デフォルトTrue）
    """
    if not cls._enabled:
        return

    # ... 既存のファイル出力とコンソール出力 ...

    # === Allure attach（新規追加） ===
    if attach_to_allure:
        cls._attach_to_allure(category, event, data, message, level)
```

### 3.5 便利メソッドの追加

```python
@classmethod
def attach_screenshot(
    cls,
    base64_data: str,
    label: Optional[str] = None,
    message: Optional[str] = None
) -> Optional[Path]:
    """スクリーンショットを保存してAllureにもattach
    
    Args:
        base64_data: Base64エンコードされた画像
        label: 画像ラベル
        message: ログメッセージ
        
    Returns:
        保存したファイルのパス
    """
    # ファイルに保存
    path = cls.save_screenshot_base64(
        base64_data,
        category=LogCategory.SCREEN,
        event=LogEvent.UPDATE,
        label=label,
        message=message
    )
    
    # Allureにもattach
    if path and path.exists():
        try:
            import allure
            allure.attach.file(
                str(path),
                name=f"📷 {label or 'Screenshot'}",
                attachment_type=allure.attachment_type.PNG
            )
        except Exception:
            pass
    
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
    cls.log(
        category=LogCategory.SCREEN,
        event=LogEvent.UPDATE,
        data={"locator_info_length": len(ui_elements)},
        message=f"📍 {label}",
        level="DEBUG"
    )
    
    try:
        import allure
        allure.attach(
            ui_elements,
            name=f"📍 {label}",
            attachment_type=allure.attachment_type.TEXT
        )
    except Exception:
        pass
```

---

## 4. 既存コード変更計画

### 4.1 削除対象の allure.attach

#### workflow.py（約25箇所）

| 行番号 | 現在のコード | 変更後 |
|--------|-------------|--------|
| 386-390 | `allure.attach(ui_elements, ...)` | `SLog.attach_locator_info(ui_elements)` |
| 392-396 | `allure.attach(screenshot, ...)` | `SLog.attach_screenshot(image_url, "Before Execution")` |
| 465-469 | `allure.attach(task, ...)` | 削除（SLog.logで代替） |
| 474-478 | `allure.attach(response, ...)` | 削除（SLog.logで代替） |
| ... | ... | ... |

#### simple_planner.py（約7箇所）

| 行番号 | 現在のコード | 変更後 |
|--------|-------------|--------|
| 563-567 | `allure.attach(...)` | 削除（SLog.logで代替） |
| 627 | `allure.attach(state_summary, ...)` | `SLog.log(ANALYZE, RESPONSE, {...})` |
| 641 | `allure.attach(decision, ...)` | `SLog.log(DECIDE, RESPONSE, {...})` |
| ... | ... | ... |

#### multi_stage_replanner.py（1箇所）

| 行番号 | 現在のコード | 変更後 |
|--------|-------------|--------|
| 419 | `allure.attach(str(e), ...)` | `SLog.error(DECIDE, FAIL, {...})` |

#### conftest.py（2箇所）

| 行番号 | 現在のコード | 変更後 |
|--------|-------------|--------|
| 442-446 | `allure.attach(exception_info, ...)` | `SLog.error(LLM, FAIL, {...})` |
| 737-741 | `allure.attach(analysis, ...)` | 維持（テスト終了時の特殊ケース） |

### 4.2 維持する allure.attach

以下は `SLog` の範囲外なので維持:

1. **AllureLogger クラス内のattach**
   - ツール呼び出し履歴の詳細なattach
   - ステップ単位の構造化されたattach

2. **conftest.py のテスト終了時attach**
   - ログ解析結果のattach（_generate_log_analysis）

---

## 5. 実装手順

### Phase 1: StructuredLogger 拡張
1. `AttachConfig` クラス追加
2. `ATTACH_CONFIG` 定義追加
3. `_attach_to_allure()` メソッド追加
4. `log()` メソッド変更
5. 便利メソッド追加（`attach_screenshot`, `attach_locator_info`）

### Phase 2: 既存コード移行（workflow.py）
1. スクリーンショットattachを `SLog.attach_screenshot()` に置換
2. ロケーター情報attachを `SLog.attach_locator_info()` に置換
3. その他のテキストattachを `SLog.log()` に統合
4. 冗長な `allure.attach()` を削除

### Phase 3: 既存コード移行（agents/）
1. `simple_planner.py` の allure.attach を SLog.log に置換
2. `multi_stage_replanner.py` の allure.attach を SLog.log に置換

### Phase 4: 既存コード移行（conftest.py）
1. 例外処理のattachを SLog.error に置換
2. テスト終了時のattachは維持（特殊ケース）

### Phase 5: テストと検証
1. 単体テスト実行
2. 実機テスト（TEST_0001）実行
3. Allureレポート確認

---

## 6. テスト計画

### 6.1 単体テスト

```python
# tests/test_structured_logger_allure.py

@pytest.mark.asyncio
async def test_attach_config_default():
    """デフォルト設定のテスト"""
    config = AttachConfig()
    assert config.enabled == True
    assert config.attachment_type == "TEXT"

def test_attach_to_allure_with_screenshot(mock_allure):
    """スクリーンショット付きログのattachテスト"""
    SLog.init("test", Path("./logs"))
    SLog.log(
        category=LogCategory.SCREEN,
        event=LogEvent.UPDATE,
        data={"screenshot_base64": "...base64..."},
        message="Screenshot captured"
    )
    # mock_allure.attach が呼ばれたことを確認
    assert mock_allure.attach.called
    SLog.close()

def test_attach_disabled_for_session():
    """SESSION カテゴリはattachされないテスト"""
    # SESSION は enabled=False なのでattachされない
    ...
```

### 6.2 統合テスト

```bash
# 実機テスト実行
uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001" --mini-model -v

# Allureレポート確認
allure serve allure-results
```

---

## 7. 移行チェックリスト

- [ ] Phase 1: StructuredLogger 拡張
  - [ ] AttachConfig クラス追加
  - [ ] ATTACH_CONFIG 定義追加
  - [ ] _attach_to_allure() メソッド追加
  - [ ] log() メソッド変更
  - [ ] 便利メソッド追加
  - [ ] 単体テスト追加

- [ ] Phase 2: workflow.py 移行
  - [ ] スクリーンショットattach置換（約4箇所）
  - [ ] ロケーター情報attach置換（約3箇所）
  - [ ] テキストattach統合（約18箇所）
  - [ ] 動作確認

- [ ] Phase 3: agents/ 移行
  - [ ] simple_planner.py（約7箇所）
  - [ ] multi_stage_replanner.py（1箇所）
  - [ ] 動作確認

- [ ] Phase 4: conftest.py 移行
  - [ ] 例外処理attach置換（1箇所）
  - [ ] 動作確認

- [ ] Phase 5: 検証
  - [ ] 単体テスト100%パス
  - [ ] 実機テスト成功
  - [ ] Allureレポート確認

---

## 8. リスクと対策

| リスク | 対策 |
|--------|------|
| allureがインストールされていない環境 | try-except で ImportError を捕捉 |
| 大量のデータによるattach肥大化 | 10KB超のデータは truncate |
| 既存の allure.step との整合性 | allure.step は維持、その中での attach を SLog に置換 |
| パフォーマンス低下 | attach は軽量な操作なので問題なし |

---

## 9. 参考: 変更前後の比較

### Before（現状）
```python
# workflow.py
SLog.info(LogCategory.STEP, LogEvent.EXECUTE, {"step": task}, f"Executing: {task}")
allure.attach(
    task,
    name=f"Step [model: {cfg.execution_model}]",
    attachment_type=allure.attachment_type.TEXT,
)

# スクリーンショット
if image_url:
    allure.attach(
        base64.b64decode(image_url.replace("data:image/jpeg;base64,", "")),
        name="📷 Current Screen",
        attachment_type=allure.attachment_type.JPG,
    )
```

### After（統一後）
```python
# workflow.py
SLog.info(LogCategory.STEP, LogEvent.EXECUTE, {"step": task}, f"Executing: {task}")
# ↑ 自動的にAllureにもattachされる

# スクリーンショット
if image_url:
    SLog.attach_screenshot(image_url, label="Current Screen")
```

コード量が削減され、一貫性のあるログ/attach出力が実現できる。
