# SmartestiRoid ログ出力リファクタリング計画

> **最終更新**: 2025-01-XX  
> **バージョン**: 2.0  
> **ステータス**: 実装待ち

## 📚 目次

### Part 1: 現状と課題
1. [🚨 不足している情報（追加必須）](#-不足している情報追加必須)
2. [📊 現状分析](#-現状分析)
3. [🎯 リファクタリング目標](#-リファクタリング目標)

### Part 2: 設計仕様
4. [🚨 GUI通知用print（変更禁止）](#-gui通知用print変更禁止)
5. [📝 新ログフォーマット仕様](#-新ログフォーマット仕様)
6. [📁 ログファイル構成](#-ログファイル構成)

### Part 3: 実装詳細
7. [🔧 具体的な修正案](#-具体的な修正案)
8. [📋 出力例（リファクタリング後）](#-出力例リファクタリング後)
9. [📝 追加すべきログイベント](#-追加すべきログイベント)

### Part 4: 実行計画
10. [🚀 実装計画](#-実装計画)
11. [🧪 テスト計画](#-テスト計画)
12. [📊 成功基準](#-成功基準)

### Part 5: 補足情報
13. [📊 期待される効果](#-期待される効果)
14. [📁 関連ファイル](#-関連ファイル)
15. [⚠️ 移行時の注意事項](#️-移行時の注意事項)
16. [🔄 ロールバック計画](#-ロールバック計画)
17. [✅ 実施TODO（チェックリスト）](#-実施todoチェックリスト)

---

## 🚨 不足している情報（追加必須）

現状のログでは以下の重要な情報が記録されておらず、不具合解析が困難です。

### 1. LLMへの入出力（最重要）

| 項目 | 現状 | 必要な情報 |
|------|------|-----------|
| **System Prompt** | ❌ 記録なし | 各ステージで使用するシステムプロンプト全文 |
| **User Prompt** | ❌ 記録なし | LLMに渡すユーザープロンプト全文 |
| **画面ロケーター** | ⚠️ Allureのみ | JSONログにもXML/圧縮XMLを記録 |
| **スクリーンショット** | ⚠️ Allureのみ | JSONログに画像パスまたはbase64 |
| **LLM応答（生）** | ❌ 記録なし | structured_output前の生レスポンス |
| **LLM応答（構造化）** | ⚠️ 一部のみ | Plan, StateAnalysis等のPydanticモデル全体 |

### 2. Multi-Stage Replanの各ステージ

| ステージ | 現状 | 必要な情報 |
|---------|------|-----------|
| **analyze_state** | ⚠️ 結果のみ | 入力プロンプト、StateAnalysis全フィールド |
| **decide_action** | ⚠️ 結果のみ | 判定ロジック、決定理由、Actオブジェクト |
| **build_plan** | ⚠️ ステップ数のみ | 入力プロンプト、生成されたPlan全体 |

### 3. ツール呼び出し

| 項目 | 現状 | 必要な情報 |
|------|------|-----------|
| **ツール名** | ✅ 記録あり | - |
| **入力引数（全体）** | ⚠️ 200文字で切り捨て | 完全な入力引数（特にxpath等） |
| **出力（全体）** | ⚠️ 200文字で切り捨て | 完全な出力（エラーメッセージ含む） |
| **実行時間** | ✅ 記録あり | - |
| **呼び出し元ステップ** | ⚠️ 不明確 | どのステップからの呼び出しか明示 |

### 4. 進捗と状態遷移

| 項目 | 現状 | 必要な情報 |
|------|------|-----------|
| **目標ステップ一覧** | ⚠️ 初期のみ | 各replan時点での状態 |
| **目標達成判定理由** | ❌ 記録なし | なぜ達成/未達成と判定したか |
| **スキップ判定** | ❌ 記録なし | 要素をスキップした場合の理由 |
| **画面遷移履歴** | ❌ 記録なし | 画面タイプの変化履歴 |

---

## 📊 現状分析

### 1. 現在のログ出力の問題点

#### 1.1 フォーマットの不統一
```
# 現状の問題例
print(Fore.CYAN + "📋 目標ステップ解析完了:")        # プレフィックスなし
print(Fore.MAGENTA + "[MultiStageReplanner.analyze_state model: gpt-4.1]")  # クラス名形式
print(f"[PROGRESS] {json.dumps(...)}")                # JSON形式
print(Fore.GREEN + f"✅ Tool End: click_element (0.14s)")  # ツール形式
```

#### 1.2 構造化されていない出力
- 同じイベントでも出力形式がバラバラ
- LLMが解析しにくい自然言語混在
- タイムスタンプが一部のログのみ（logging経由のみ）

#### 1.3 色の使い分けが不明確
| 色 | 現状の用途 | 問題点 |
|---|---|---|
| CYAN | 情報、進捗、ステータス | 用途が広すぎる |
| GREEN | 成功、完了 | 比較的一貫 |
| YELLOW | 警告 | 比較的一貫 |
| RED | エラー | 比較的一貫 |
| MAGENTA | LLM関連 | 不明確 |

### 2. ログ出力箇所の分類（2025年1月時点）

> print文の総数: **約210箇所**

#### 2.1 workflow.py（55箇所）
```
カテゴリ分類:
- ステップ実行: 15箇所
- リプラン進捗: 12箇所
- 検証LLM: 10箇所
- 目標進捗: 10箇所
- エラー/警告: 8箇所
```

#### 2.2 multi_stage_replanner.py（50箇所）
```
カテゴリ分類:
- analyze_state: 15箇所
- decide_action: 10箇所
- build_plan: 10箇所
- build_response: 10箇所
- エラー: 5箇所
```

#### 2.3 conftest.py（48箇所）
```
カテゴリ分類:
- セットアップ/設定: 15箇所
- テスト進捗: 10箇所
- トークン使用量: 8箇所
- エラー/警告: 10箇所
- セッション管理: 5箇所
```

#### 2.4 agents/simple_planner.py（46箇所）
```
カテゴリ分類:
- 画面分析: 10箇所
- プラン生成: 12箇所
- 目標評価: 10箇所
- 画面不整合リトライ: 8箇所
- エラー: 6箇所
```

#### 2.5 test_android_app.py（8箇所）
```
カテゴリ分類:
- テスト開始/終了: 4箇所
- 進捗通知: 4箇所
```

#### 2.6 その他（3箇所）
```
- appium_tools/device_info.py: 1箇所
- appium_tools/token_counter.py: 1箇所
- utils/allure_logger.py: 1箇所
```

---

## 🎯 リファクタリング目標

### 1. LLM解析しやすい構造化ログ
```python
# 提案形式
[TIMESTAMP] [LEVEL] [CATEGORY] [EVENT] {structured_data}

# 例
[22:19:30] [INFO] [STEP] [EXECUTE] {"step":"click_element","target":"terms_agree","result":"success","duration_ms":140}
```

### 2. 出力先の分離（案C採用）

| 出力先 | 形式 | 用途 |
|-------|------|------|
| コンソール | アイコン付きテキスト（色なし） | 人間が実行中に確認 |
| ファイル | JSON Lines形式 | LLMによる後続解析 |

```python
# コンソール出力例（人間用）
✅ ツール完了: click_element (0.14s)
🎯 目標達成: [0] アプリを起動する
📊 進捗: 2/3 (67%)

# ファイル出力例（LLM解析用）- smartestiroid_YYYYMMDD_HHMMSS.jsonl
{"ts":"22:19:36","lvl":"INFO","cat":"TOOL","evt":"COMPLETE","data":{"tool":"click_element","ms":140}}
{"ts":"22:19:40","lvl":"INFO","cat":"OBJECTIVE","evt":"ACHIEVED","data":{"index":0,"objective":"アプリを起動する"}}
```

### 3. 設計方針

- **色は使用しない**: colorama依存を削除、シンプルなテキスト出力
- **アイコンで視認性確保**: ✅❌⚠️🎯📊🚀🔧 等で状況を即座に把握
- **JSONログは自動ファイル出力**: テスト開始時にログファイルを自動生成

---

## 🚨 GUI通知用print（変更禁止）

以下のprint文はGUIへの通知に使用されているため、**絶対に変更・削除しない**こと。

### 変更禁止のprint文

| ファイル | プレフィックス | 用途 |
|---------|---------------|------|
| `test_android_app.py` | `[PROGRESS]` | テスト開始/完了通知 |
| `conftest.py` | `[PROGRESS]` | テスト収集完了通知 |
| `workflow.py` | `[REPLAN_PROGRESS]` | リプラン進捗通知 |

### 具体的な箇所

```python
# test_android_app.py
print(f"[PROGRESS] {progress_start}")   # テスト開始
print(f"[PROGRESS] {progress_done}")    # テスト完了

# conftest.py  
print(Fore.CYAN + f"\n[PROGRESS] {{\"total\": {total}, \"status\": \"collected\"}}")

# workflow.py
print(f"[REPLAN_PROGRESS] {json.dumps({'current_replan_count': 0, ...})}")
print(f"[REPLAN_PROGRESS] {json.dumps({'current_replan_count': current_replan_count + 1, ...})}")
```

### 対応方針

1. **既存のGUI通知printはそのまま維持**
2. 新しいStructuredLoggerは**並行して**出力（置き換えではない）
3. coloramaの色（`Fore.CYAN`等）は削除しても、print文自体は残す

```python
# Before
print(Fore.CYAN + f"\n[PROGRESS] {{\"total\": {total}, \"status\": \"collected\"}}")

# After（coloramaのみ削除、printは維持）
print(f"[PROGRESS] {{\"total\": {total}, \"status\": \"collected\"}}")

# + 新規ログ追加（並行）
SLog.log(category="TEST", event="COLLECTED", data={"total": total})
```

---

## 📝 新ログフォーマット仕様

### 1. カテゴリ定義

```python
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
    
    # 進捗管理
    PROGRESS = "PROGRESS"   # 進捗更新
    OBJECTIVE = "OBJECTIVE" # 目標進捗
    
    # システム
    SESSION = "SESSION"     # セッション管理
    CONFIG = "CONFIG"       # 設定
    ERROR = "ERROR"         # エラー
```

### 2. イベント定義

```python
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
    
    # 状態変化
    UPDATE = "UPDATE"
    CHANGE = "CHANGE"
    
    # 判定
    ACHIEVED = "ACHIEVED"
    NOT_ACHIEVED = "NOT_ACHIEVED"
```

### 3. 構造化ログ出力関数

```python
# src/smartestiroid/utils/structured_logger.py

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

class StructuredLogger:
    """構造化ログ出力クラス（コンソール + JSONファイル分離）"""
    
    _log_file: Optional[Path] = None
    _file_handle = None
    
    # イベント別アイコン
    ICONS = {
        "START": "🚀",
        "END": "🏁",
        "EXECUTE": "🔧",
        "COMPLETE": "✅",
        "FAIL": "❌",
        "SKIP": "⏭️",
        "ACHIEVED": "🎯",
        "NOT_ACHIEVED": "🔄",
        "UPDATE": "📊",
        "WARN": "⚠️",
    }
    
    @classmethod
    def init(cls, test_id: str, output_dir: Path = Path(".")):
        """ログファイルを初期化
        
        Args:
            test_id: テストID（ファイル名に使用）
            output_dir: 出力ディレクトリ
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cls._log_file = output_dir / f"smartestiroid_{test_id}_{timestamp}.jsonl"
        cls._file_handle = open(cls._log_file, "w", encoding="utf-8")
    
    @classmethod
    def close(cls):
        """ログファイルをクローズ"""
        if cls._file_handle:
            cls._file_handle.close()
            cls._file_handle = None
    
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
            level: ログレベル (INFO, WARN, ERROR)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # === ファイル出力（JSON Lines） ===
        if cls._file_handle:
            log_entry = {
                "ts": timestamp,
                "lvl": level,
                "cat": category,
                "evt": event,
            }
            if data:
                log_entry["data"] = data
            cls._file_handle.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            cls._file_handle.flush()
        
        # === コンソール出力（人間用） ===
        if message:
            icon = cls._get_icon(event, level)
            print(f"{icon} {message}")
    
    @classmethod
    def _get_icon(cls, event: str, level: str) -> str:
        """イベントとレベルに応じたアイコンを返す"""
        if level == "ERROR":
            return "❌"
        if level == "WARN":
            return "⚠️"
        return cls.ICONS.get(event, "📍")
```

---

## 🔧 具体的な修正案

### 1. conftest.py の修正例

#### Before:
```python
print(Fore.CYAN + f"使用モデル: {cfg.execution_model}")
print(Fore.CYAN + f"Agent Executor用モデル: {cfg.execution_model}")
print(Fore.MAGENTA + "=" * 60)
print(Fore.MAGENTA + "【LLMに渡されるknowhow情報】")
```

#### After:
```python
from smartestiroid.utils.structured_logger import StructuredLogger as SLog

SLog.log(
    category="CONFIG",
    event="UPDATE",
    data={"execution_model": cfg.execution_model},
    message=f"使用モデル: {cfg.execution_model}"
)
```

### 2. workflow.py の修正例

#### Before:
```python
print(Fore.CYAN + f"\n{'='*50}")
print(Fore.CYAN + "📊 現在の進捗状況:")
print(Fore.CYAN + progress_summary)
print(Fore.CYAN + f"{'='*50}\n")
```

#### After:
```python
SLog.log(
    category="PROGRESS",
    event="UPDATE",
    data={
        "completed_steps": completed_steps,
        "total_steps": total_steps,
        "tool_calls": len(tool_call_log),
    },
    message=f"進捗: {completed_steps}/{total_steps} ステップ完了"
)
```

### 3. multi_stage_replanner.py の修正例

#### Before:
```python
print(Fore.MAGENTA + f"[MultiStageReplanner.analyze_state model: {self.model_name}] State analysis completed")
print(Fore.CYAN + f"  - screen_type: {state_analysis.current_screen_type}")
print(Fore.CYAN + f"  - current_objective_achieved: {state_analysis.current_objective_achieved}")
```

#### After:
```python
SLog.log(
    category="ANALYZE",
    event="COMPLETE",
    data={
        "model": self.model_name,
        # === StateAnalysis全9フィールド ===
        # 画面状態
        "screen_changes": state_analysis.screen_changes,
        "screen_type": state_analysis.current_screen_type,
        "main_elements": state_analysis.main_elements,
        "blocking_dialogs": state_analysis.blocking_dialogs,
        # 画面整合性
        "screen_inconsistency": state_analysis.screen_inconsistency,
        # 進捗評価
        "test_progress": state_analysis.test_progress,
        # 目標評価
        "objective_achieved": state_analysis.current_objective_achieved,
        "objective_evidence": state_analysis.current_objective_evidence,
        # 提案
        "suggested_next_action": state_analysis.suggested_next_action,
    },
    message=f"画面分析完了: {state_analysis.current_screen_type}"
)
```

### 4. Tool実行ログの修正例

#### Before:
```python
print(f"🔧 Tool Start: {tool_name}")
print(f"   Input: {input_preview}...")
# ... 実行 ...
print(f"✅ Tool End: {tool_name} ({duration:.2f}s)")
print(f"   Output: {output_preview}...")
```

#### After:
```python
SLog.log(
    category="TOOL",
    event="START",
    data={"tool": tool_name, "input": input_data},
    message=f"ツール開始: {tool_name}"
)

# ... 実行 ...

SLog.log(
    category="TOOL",
    event="COMPLETE",
    data={
        "tool": tool_name,
        "duration_ms": int(duration * 1000),
        "success": True,
        "output_preview": output_preview[:100]
    },
    message=f"ツール完了: {tool_name} ({duration:.2f}s)"
)
```

---

## 📋 出力例（リファクタリング後）

### コンソール出力（人間用・色なし）
```
🚀 テスト開始: TEST_0015 - トップメニューのタブ切り替え動作確認
✅ 画面分析完了: 利用規約ダイアログ
✅ プラン生成: 2ステップ
🔧 ツール実行: click_element
✅ ツール完了: click_element (0.14s)
🎯 目標達成: [0] アプリを起動する
📊 リプラン #1: 次のアクションを計画
📊 目標進捗: 2/3 (67%)
⚠️ フォールバック: スクロールして要素を探索
❌ ツール失敗: click_element - Element not found
🏁 テスト終了: PASS
```

### ファイル出力（LLM解析用・JSON Lines）
ファイル名: `smartestiroid_TEST_0015_20241204_221930.jsonl`
```json
{"ts":"22:19:30","lvl":"INFO","cat":"TEST","evt":"START","data":{"test_id":"TEST_0015","title":"トップメニューのタブ切り替え動作確認"}}
{"ts":"22:19:31","lvl":"INFO","cat":"ANALYZE","evt":"COMPLETE","data":{"model":"gpt-4.1","screen_type":"利用規約ダイアログ"}}
{"ts":"22:19:35","lvl":"INFO","cat":"PLAN","evt":"COMPLETE","data":{"model":"gpt-4.1","steps":2}}
{"ts":"22:19:36","lvl":"INFO","cat":"TOOL","evt":"START","data":{"tool":"click_element"}}
{"ts":"22:19:36","lvl":"INFO","cat":"TOOL","evt":"COMPLETE","data":{"tool":"click_element","ms":140,"success":true}}
{"ts":"22:19:40","lvl":"INFO","cat":"OBJECTIVE","evt":"ACHIEVED","data":{"index":0,"objective":"アプリを起動する"}}
{"ts":"22:19:45","lvl":"INFO","cat":"REPLAN","evt":"UPDATE","data":{"count":1,"max":20,"decision":"PLAN"}}
{"ts":"22:19:50","lvl":"INFO","cat":"PROGRESS","evt":"UPDATE","data":{"completed":2,"total":3,"pct":67}}
{"ts":"22:20:00","lvl":"WARN","cat":"STEP","evt":"SKIP","data":{"reason":"fallback_scroll"}}
{"ts":"22:20:30","lvl":"ERROR","cat":"TOOL","evt":"FAIL","data":{"tool":"click_element","error":"Element not found"}}
{"ts":"22:21:00","lvl":"INFO","cat":"TEST","evt":"END","data":{"result":"PASS","duration_s":90}}
```

---

## 📝 追加すべきログイベント

### 1. LLM入出力ログ（新規追加）

```json
// LLM呼び出し開始（プロンプト記録）
{"ts":"22:19:31","lvl":"DEBUG","cat":"LLM","evt":"REQUEST","data":{
  "stage":"analyze_state",
  "model":"gpt-4.1",
  "system_prompt":"あなたは画面分析のエキスパートです...",
  "user_prompt":"【全体目標】トップメニューのタブ切り替え...",
  "locator_file":"locator_22_19_31.xml",
  "screenshot_file":"screen_22_19_31.jpg"
}}

// LLM応答（構造化データ記録）- StateAnalysis全9フィールド
{"ts":"22:19:33","lvl":"DEBUG","cat":"LLM","evt":"RESPONSE","data":{
  "stage":"analyze_state",
  "model":"gpt-4.1",
  "duration_ms":2150,
  "tokens":{"prompt":1250,"completion":380,"total":1630},
  "response":{
    "screen_changes":"前ステップなし（初期状態）",
    "current_screen_type":"トップメニュー画面",
    "main_elements":"ホームタブ(選択中), 映画タブ, 音楽タブ, ポッドキャストタブ...",
    "blocking_dialogs":null,
    "screen_inconsistency":null,
    "test_progress":"0/7タブ確認済み",
    "current_objective_achieved":false,
    "current_objective_evidence":"まだタブをタップしていない",
    "suggested_next_action":"すべてのタブを順番にタップする"
  }
}}
```

### 2. プラン生成ログ（詳細化）

```json
// プラン生成結果（全ステップ記録）
{"ts":"22:19:35","lvl":"INFO","cat":"PLAN","evt":"COMPLETE","data":{
  "stage":"build_plan",
  "model":"gpt-4.1",
  "current_objective":"すべてのタブをタップして切り替え動作を確認する",
  "steps":[
    "ホームタブをタップする",
    "映画タブをタップする",
    "音楽タブをタップする",
    "ポッドキャストタブをタップする",
    "オーディオブックタブをタップする",
    "ライブタブをタップする",
    "設定タブをタップする"
  ],
  "step_count":7,
  "expected_element_count":7,
  "reasoning":"7つのタブすべてをタップする必要がある"
}}
```

### 3. ツール呼び出しログ（完全版）

```json
// ツール開始（入力全体）
{"ts":"22:19:36","lvl":"DEBUG","cat":"TOOL","evt":"START","data":{
  "tool":"click_element",
  "step_index":1,
  "step_text":"映画タブをタップする",
  "input":{
    "selector":"//android.widget.TextView[@text='映画']",
    "strategy":"xpath"
  }
}}

// ツール完了（出力全体）
{"ts":"22:19:36","lvl":"DEBUG","cat":"TOOL","evt":"COMPLETE","data":{
  "tool":"click_element",
  "step_index":1,
  "duration_ms":140,
  "success":true,
  "output":"Element clicked successfully at (540, 180)"
}}

// ツール失敗（エラー詳細）
{"ts":"22:20:30","lvl":"ERROR","cat":"TOOL","evt":"FAIL","data":{
  "tool":"click_element",
  "step_index":5,
  "step_text":"設定タブをタップする",
  "duration_ms":5020,
  "error":"NoSuchElementException",
  "error_detail":"Element not found: //android.widget.TextView[@text='設定']",
  "input":{
    "selector":"//android.widget.TextView[@text='設定']",
    "strategy":"xpath"
  }
}}
```

### 4. 目標達成判定ログ（新規追加）

```json
// 目標達成判定
{"ts":"22:19:40","lvl":"INFO","cat":"OBJECTIVE","evt":"EVALUATE","data":{
  "index":1,
  "description":"すべてのタブをタップして切り替え動作を確認する",
  "achieved":true,
  "reason":"7個のタブすべてがタップされ、各タブの画面に遷移した",
  "evidence":{
    "expected_taps":7,
    "actual_taps":7,
    "tapped_elements":["ホーム","映画","音楽","ポッドキャスト","オーディオブック","ライブ","設定"]
  }
}}

// スキップ判定（問題検出用）
{"ts":"22:19:38","lvl":"WARN","cat":"OBJECTIVE","evt":"SKIP","data":{
  "index":1,
  "skipped_element":"ホームタブ",
  "reason":"初期状態で選択済みのためスキップ",
  "is_bug":true,
  "expected_behavior":"選択済みでもタップを実行すべき"
}}
```

### 5. 画面遷移ログ（新規追加）

```json
// 画面遷移記録
{"ts":"22:19:37","lvl":"DEBUG","cat":"SCREEN","evt":"CHANGE","data":{
  "from":"ホームタブ画面",
  "to":"映画タブ画面",
  "trigger":"click_element",
  "element":"映画タブ"
}}
```

### 6. 画面整合性チェックログ（新規追加）

画面不整合（page_sourceとスクリーンショット画像の不一致）の検出とリトライをログ記録。

```json
// 画面不整合検出（初回）
{"ts":"22:20:15","lvl":"WARN","cat":"SCREEN","evt":"INCONSISTENCY_DETECTED","data":{
  "retry_count": 1,
  "max_retries": 2,
  "inconsistency": "画像は黒いローディング画面だがpage_sourceには要素がある",
  "screen_type": "ローディング画面",
  "wait_seconds": 3
}}

// リトライ成功（整合性回復）
{"ts":"22:20:18","lvl":"INFO","cat":"SCREEN","evt":"INCONSISTENCY_RESOLVED","data":{
  "retry_count": 1,
  "resolution": "3秒待機後、画像とpage_sourceが一致",
  "screen_type": "メイン画面"
}}

// リトライ失敗（pytest.fail呼び出し前）
{"ts":"22:20:24","lvl":"ERROR","cat":"SCREEN","evt":"INCONSISTENCY_PERSISTENT","data":{
  "retry_count": 2,
  "max_retries": 2,
  "inconsistency": "画像は黒いままでpage_sourceには要素がある",
  "action": "pytest.fail",
  "reason": "画面不整合が解消されないためテスト失敗"
}}
```

### 7. 検証LLMログ（新規追加）

ステップ実行後の検証LLM（アクション結果の確認）をログ記録。

```json
// 検証LLM呼び出し
{"ts":"22:19:37","lvl":"DEBUG","cat":"LLM","evt":"VERIFY_REQUEST","data":{
  "step_text": "利用規約に同意するボタンをタップ",
  "model": "gpt-4.1-mini",
  "locator_file": "locator_22_19_37.xml",
  "screenshot_file": "screen_22_19_37.jpg"
}}

// 検証LLM応答（成功）
{"ts":"22:19:38","lvl":"INFO","cat":"LLM","evt":"VERIFY_RESPONSE","data":{
  "step_text": "利用規約に同意するボタンをタップ",
  "result": "success",
  "evidence": "次のダイアログに遷移した",
  "duration_ms": 850
}}

// 検証LLM応答（失敗）
{"ts":"22:19:38","lvl":"WARN","cat":"LLM","evt":"VERIFY_RESPONSE","data":{
  "step_text": "利用規約に同意するボタンをタップ",
  "result": "failure",
  "evidence": "画面に変化がない、ボタンがまだ存在する",
  "contradiction": "アクション成功の報告と画面状態が矛盾",
  "duration_ms": 920
}}
```

---

## 🚀 実装計画

### Phase 1: StructuredLogger クラス作成（1日目）

**ファイル**: `src/smartestiroid/utils/structured_logger.py`

```
実装内容:
1. StructuredLoggerクラスの骨格
   - init(): ログディレクトリ初期化
   - close(): ファイルハンドルクローズ
   - log(): メインログ出力
   
2. ファイル保存メソッド
   - save_locator(): XMLを別ファイルに保存
   - save_screenshot(): 画像を別ファイルに保存
   - save_prompt(): プロンプトを別ファイルに保存
   - save_response(): LLM応答を別ファイルに保存
   
3. 補助機能
   - ログレベルフィルタリング
   - コンソール出力（アイコン付き）
   - バッファリング（オプション）

テスト: tests/test_structured_logger.py
```

### Phase 2: LLM入出力の記録追加（2日目）

**優先度: 最高**（不具合解析に最も重要）

**ファイル**: `src/smartestiroid/agents/multi_stage_replanner.py`

```
変更箇所:
1. analyze_state()
   - 入力: プロンプト、ロケーター、スクリーンショットを保存
   - 出力: StateAnalysis全フィールドを保存

2. decide_action()
   - 入力: 状態分析結果
   - 出力: Act決定理由

3. build_plan()
   - 入力: プランニングプロンプト
   - 出力: Plan全ステップ
```

**ファイル**: `src/smartestiroid/agents/simple_planner.py`

```
変更箇所:
1. parse_objective_steps()
2. create_execution_plan_for_objective()
3. analyze_screen()
4. evaluate_objective_completion()
```

### Phase 3: ツール呼び出しの完全記録（3日目）

**ファイル**: `src/smartestiroid/utils/allure_logger.py`

```
変更箇所:
1. on_tool_start()
   - 入力引数の切り捨て廃止（または別ファイル保存）
   - ステップインデックスの紐付け

2. on_tool_end()
   - 出力の切り捨て廃止
   - 成功/失敗フラグ

3. on_tool_error()
   - スタックトレース完全記録
```

### Phase 4: ワークフロー進捗の記録（4日目）

**ファイル**: `src/smartestiroid/workflow.py`

```
変更箇所:
1. execute_step()
   - ステップ開始/終了ログ
   - エージェント応答ログ

2. plan_step()
   - 初期プラン生成ログ

3. replan_step()
   - リプラン進捗ログ
   - 目標達成判定ログ
```

### Phase 5: 設定・セットアップの記録（5日目）

**ファイル**: `src/smartestiroid/conftest.py`

```
変更箇所:
1. テスト開始/終了
2. モデル設定
3. Knowhow情報
4. 評価結果
```

### Phase 6: クリーンアップ（6日目）

```
1. colorama依存の削除（pyproject.tomlから削除可能か確認）
2. 未使用のprint文削除
3. ドキュメント更新（AGENTS.md）
4. 最終テスト
```

---

## 📁 ログファイル構成

### ディレクトリ構造
```
logs/
└── TEST_0015_20241204_221930/           # テストごとのディレクトリ
    ├── main.jsonl                        # メインログ（軽量・インデックス）
    ├── prompts/                          # LLMプロンプト（大きいので分離）
    │   ├── 001_analyze_state.txt
    │   ├── 002_build_plan.txt
    │   └── ...
    ├── responses/                        # LLM応答（構造化JSON）
    │   ├── 001_analyze_state.json
    │   ├── 002_build_plan.json
    │   └── ...
    ├── locators/                         # 画面ロケーター（XML、数十KB〜数百KB）
    │   ├── 001.xml
    │   ├── 002.xml
    │   └── ...
    └── screenshots/                      # スクリーンショット（JPEG、数百KB）
        ├── 001.jpg
        ├── 002.jpg
        └── ...
```

### メインログ（main.jsonl）の設計方針

**原則: メインログは軽量に保ち、詳細は参照ファイルへ**

```json
// ❌ 悪い例: ロケーターを直接埋め込む（ログが肥大化）
{"ts":"22:19:31","cat":"LLM","evt":"REQUEST","data":{"locator":"<hierarchy>...</hierarchy>"}}

// ✅ 良い例: ファイル参照のみ記録
{"ts":"22:19:31","cat":"LLM","evt":"REQUEST","data":{"locator_file":"locators/001.xml","screenshot_file":"screenshots/001.jpg"}}
```

### ファイル参照のルール

| データ種別 | サイズ目安 | 保存先 | メインログ記録 |
|-----------|----------|--------|---------------|
| タイムスタンプ | 数バイト | main.jsonl | 直接 |
| カテゴリ/イベント | 数バイト | main.jsonl | 直接 |
| ツール名/引数 | 〜1KB | main.jsonl | 直接 |
| エラーメッセージ | 〜1KB | main.jsonl | 直接 |
| **LLMプロンプト** | 5〜50KB | prompts/*.txt | ファイルパス |
| **LLM応答** | 1〜10KB | responses/*.json | ファイルパス |
| **ロケーター** | 50〜500KB | locators/*.xml | ファイルパス |
| **スクリーンショット** | 100〜500KB | screenshots/*.jpg | ファイルパス |

### StructuredLoggerのファイル保存API

```python
class StructuredLogger:
    """構造化ログ出力クラス"""
    
    _log_dir: Optional[Path] = None
    _file_counter: int = 0
    
    @classmethod
    def init(cls, test_id: str, output_dir: Path = Path("logs")):
        """テスト用ログディレクトリを初期化"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cls._log_dir = output_dir / f"{test_id}_{timestamp}"
        cls._log_dir.mkdir(parents=True, exist_ok=True)
        
        # サブディレクトリ作成
        (cls._log_dir / "prompts").mkdir()
        (cls._log_dir / "responses").mkdir()
        (cls._log_dir / "locators").mkdir()
        (cls._log_dir / "screenshots").mkdir()
        
        cls._main_log = open(cls._log_dir / "main.jsonl", "w", encoding="utf-8")
        cls._file_counter = 0
    
    @classmethod
    def save_locator(cls, xml_content: str) -> str:
        """ロケーターを別ファイルに保存し、相対パスを返す"""
        cls._file_counter += 1
        filename = f"locators/{cls._file_counter:03d}.xml"
        filepath = cls._log_dir / filename
        filepath.write_text(xml_content, encoding="utf-8")
        return filename
    
    @classmethod
    def save_screenshot(cls, image_data: bytes) -> str:
        """スクリーンショットを別ファイルに保存し、相対パスを返す"""
        cls._file_counter += 1
        filename = f"screenshots/{cls._file_counter:03d}.jpg"
        filepath = cls._log_dir / filename
        filepath.write_bytes(image_data)
        return filename
    
    @classmethod
    def save_prompt(cls, prompt: str, stage: str) -> str:
        """LLMプロンプトを別ファイルに保存し、相対パスを返す"""
        cls._file_counter += 1
        filename = f"prompts/{cls._file_counter:03d}_{stage}.txt"
        filepath = cls._log_dir / filename
        filepath.write_text(prompt, encoding="utf-8")
        return filename
    
    @classmethod
    def save_response(cls, response: dict, stage: str) -> str:
        """LLM応答を別ファイルに保存し、相対パスを返す"""
        cls._file_counter += 1
        filename = f"responses/{cls._file_counter:03d}_{stage}.json"
        filepath = cls._log_dir / filename
        filepath.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        return filename
    
    @classmethod
    def log(cls, category: str, event: str, data: dict = None, message: str = None, level: str = "INFO"):
        """メインログに記録（dataにはファイルパス参照を含める）"""
        # ... 既存の実装 ...
```

### 使用例

```python
# multi_stage_replanner.py での使用例
from smartestiroid.utils.structured_logger import StructuredLogger as SLog

async def analyze_state(self, locator: str, image_data: bytes, ...):
    # 大きなデータは別ファイルに保存
    locator_file = SLog.save_locator(locator)
    screenshot_file = SLog.save_screenshot(image_data)
    prompt_file = SLog.save_prompt(system_prompt + user_prompt, "analyze_state")
    
    # メインログには参照パスのみ記録
    SLog.log(
        category="LLM",
        event="REQUEST",
        data={
            "stage": "analyze_state",
            "model": self.model_name,
            "locator_file": locator_file,
            "screenshot_file": screenshot_file,
            "prompt_file": prompt_file
        },
        message="画面分析開始"
    )
    
    # LLM呼び出し
    response = await self.llm.ainvoke(...)
    
    # 応答も別ファイルに保存
    response_file = SLog.save_response(response.dict(), "analyze_state")
    
    SLog.log(
        category="LLM",
        event="RESPONSE",
        data={
            "stage": "analyze_state",
            "duration_ms": elapsed_ms,
            "response_file": response_file
        },
        message=f"画面分析完了: {response.current_screen_type}"
    )
```

### LLM解析時の読み込み

```python
# ログ解析スクリプト例
import json
from pathlib import Path

def load_full_context(log_dir: Path, log_entry: dict) -> dict:
    """メインログエントリから完全なコンテキストを読み込む"""
    data = log_entry.get("data", {})
    
    # ファイル参照があれば読み込む
    if "locator_file" in data:
        data["locator"] = (log_dir / data["locator_file"]).read_text()
    if "prompt_file" in data:
        data["prompt"] = (log_dir / data["prompt_file"]).read_text()
    if "response_file" in data:
        data["response"] = json.loads((log_dir / data["response_file"]).read_text())
    
    return data
```

---

## 📊 期待される効果

### 1. LLM解析の精度向上
- JSON形式の構造化ログにより、LLMが正確に状態を把握
- カテゴリ・イベントの標準化で、パターン認識が容易に

### 2. デバッグ効率の向上
- 問題箇所の特定が容易（カテゴリでフィルタ可能）
- 時系列での追跡がしやすい

### 3. ログ解析ツールとの統合
- JSON形式でログ分析ツールに取り込み可能
- グラフ化・可視化が容易

### 4. 人間の可読性維持
- アイコン付きサマリメッセージで直感的に状況把握
- 構造化されたAllureレポートで詳細確認

---

## 📁 関連ファイル

| ファイル | print箇所 | 優先度 |
|---------|----------|--------|
| `conftest.py` | 50箇所 | 低 |
| `workflow.py` | 25箇所 | 高 |
| `agents/simple_planner.py` | 25箇所 | 中 |
| `agents/multi_stage_replanner.py` | 12箇所 | 高 |
| `appium_tools/device_info.py` | 1箇所 | 低 |
| `appium_tools/token_counter.py` | 1箇所 | 低 |

---

## ⚠️ 移行時の注意事項

### 1. 後方互換性

```python
# 既存のAllureレポートとの統合を維持
# Allureへの出力は引き続き行い、JSONログと並行運用
allure.attach(...)  # 既存のまま維持
SLog.log(...)       # 新規追加
```

### 2. パフォーマンス考慮

```python
# ファイルI/Oの頻度を抑える
# - バッファリング: flush()は重要なイベント時のみ
# - 非同期書き込み: 将来的にはasyncio対応も検討

class StructuredLogger:
    _buffer: list = []
    _buffer_size: int = 10  # 10件ごとにflush
    
    @classmethod
    def log(cls, ...):
        cls._buffer.append(log_entry)
        if len(cls._buffer) >= cls._buffer_size or level in ("ERROR", "WARN"):
            cls._flush()
```

### 3. ログレベルによるフィルタリング

```python
# 環境変数でログレベルを制御
# SMARTESTIROID_LOG_LEVEL=DEBUG → 全ログ出力
# SMARTESTIROID_LOG_LEVEL=INFO → DEBUG以外
# SMARTESTIROID_LOG_LEVEL=WARN → WARN, ERROR のみ

import os
LOG_LEVEL = os.environ.get("SMARTESTIROID_LOG_LEVEL", "INFO")
```

### 4. 既存コードへの影響最小化

```python
# 段階的移行: 新旧両方を出力
def legacy_print_with_new_log(message: str, category: str, event: str, data: dict):
    """移行期間中の互換関数"""
    # 旧: 既存のprint出力（徐々に削除）
    print(message)
    # 新: 構造化ログ出力
    SLog.log(category, event, data, message)
```

---

## 🧪 テスト計画

### 1. 単体テスト（structured_logger.py）

```python
# tests/test_structured_logger.py

def test_log_creates_jsonl_file():
    """JSONLファイルが正しく作成されること"""
    
def test_log_entry_format():
    """ログエントリが正しいフォーマットであること"""
    
def test_save_locator_creates_file():
    """ロケーターが別ファイルに保存されること"""
    
def test_save_screenshot_creates_file():
    """スクリーンショットが別ファイルに保存されること"""
    
def test_file_reference_in_log():
    """メインログにファイル参照パスが記録されること"""
    
def test_console_output_has_icon():
    """コンソール出力にアイコンが付くこと"""
    
def test_log_level_filtering():
    """ログレベルによるフィルタリングが動作すること"""
```

### 2. 統合テスト

```bash
# 実際のテスト実行でログを確認
uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001" -v

# 生成されたログを検証
ls -la logs/TEST_0001_*/
cat logs/TEST_0001_*/main.jsonl | head -20
```

### 3. ログ解析テスト

```python
# ログからTEST_0015のタブスキップ問題を検出できるか確認
def test_can_detect_tab_skip_from_log():
    """ログからスキップ問題を検出できること"""
    log_dir = Path("logs/TEST_0015_...")
    main_log = log_dir / "main.jsonl"
    
    # SKIPイベントを検索
    skip_events = [
        json.loads(line) for line in main_log.read_text().splitlines()
        if '"evt":"SKIP"' in line
    ]
    
    assert len(skip_events) > 0, "スキップイベントが記録されていない"
```

---

## 📊 成功基準

### 必須要件
- [ ] すべてのLLM呼び出しのプロンプト/応答がファイルに保存される
- [ ] すべてのツール呼び出しの入出力が完全に記録される
- [ ] テストごとに独立したログディレクトリが作成される
- [ ] コンソール出力が人間に読みやすい（アイコン付き）
- [ ] JSONログがLLMで解析可能（構造化されている）

### 推奨要件
- [ ] ログサイズが適切（メインログ < 1MB/テスト）
- [ ] colorama依存が削除されている
- [ ] 既存のAllureレポートが引き続き動作する
- [ ] TEST_0015のタブスキップ問題がログから検出可能

---

## 🔄 ロールバック計画

問題発生時のロールバック手順：

```bash
# 1. structured_logger.pyを削除
rm src/smartestiroid/utils/structured_logger.py

# 2. 変更したファイルをrevert
git checkout src/smartestiroid/workflow.py
git checkout src/smartestiroid/agents/multi_stage_replanner.py
git checkout src/smartestiroid/agents/simple_planner.py
git checkout src/smartestiroid/conftest.py

# 3. 動作確認
uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001" -v
```

---

## ✅ 実施TODO（チェックリスト）

> **推奨実施順序**: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6

### Phase 1: StructuredLogger 基盤実装 🏗️

- [ ] **1.1** `src/smartestiroid/utils/structured_logger.py` を作成
  - [ ] StructuredLogger クラスの骨組み
  - [ ] `init(test_id, output_dir)` メソッド
  - [ ] `close()` メソッド  
  - [ ] `log(category, event, data, message, level)` メソッド
  - [ ] JSONLファイルへの出力
  - [ ] コンソール出力（アイコン付き）
- [ ] **1.2** LogCategory 定数クラスを定義
- [ ] **1.3** LogEvent 定数クラスを定義
- [ ] **1.4** `tests/test_structured_logger.py` を作成
  - [ ] `test_log_creates_jsonl_file`
  - [ ] `test_log_entry_format`
  - [ ] `test_console_output_has_icon`
- [ ] **1.5** テスト実行: `uv run pytest tests/test_structured_logger.py -v`

### Phase 2: conftest.py 移行 🔧

- [ ] **2.1** StructuredLogger のインポート追加
- [ ] **2.2** `pytest_collection_finish` でロガー初期化
- [ ] **2.3** セットアップ/設定系print → SLog.log 移行（約15箇所）
  - [ ] 使用モデル情報
  - [ ] knowhow情報
  - [ ] capabilities情報
- [ ] **2.4** トークン使用量print → SLog.log 移行（約8箇所）
- [ ] **2.5** セッション管理print → SLog.log 移行（約5箇所）
- [ ] **2.6** ⚠️ **GUI通知用print `[PROGRESS]` は変更しない**
- [ ] **2.7** テスト実行: `uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001"`

### Phase 3: workflow.py 移行 🔧

- [ ] **3.1** StructuredLogger のインポート追加
- [ ] **3.2** ステップ実行print → SLog.log 移行（約15箇所）
  - [ ] STEP.START
  - [ ] STEP.COMPLETE
  - [ ] STEP.FAIL
- [ ] **3.3** リプラン進捗print → SLog.log 移行（約12箇所）
  - [ ] REPLAN.START
  - [ ] REPLAN.COMPLETE
- [ ] **3.4** 検証LLMprint → SLog.log 移行（約10箇所）
  - [ ] LLM.VERIFY_REQUEST
  - [ ] LLM.VERIFY_RESPONSE
- [ ] **3.5** 目標進捗print → SLog.log 移行（約10箇所）
  - [ ] OBJECTIVE.ACHIEVED
  - [ ] OBJECTIVE.NOT_ACHIEVED
- [ ] **3.6** ⚠️ **GUI通知用print `[REPLAN_PROGRESS]` は変更しない**
- [ ] **3.7** テスト実行

### Phase 4: multi_stage_replanner.py 移行 🔧

- [ ] **4.1** StructuredLogger のインポート追加
- [ ] **4.2** analyze_state print → SLog.log 移行（約15箇所）
  - [ ] ANALYZE.START
  - [ ] ANALYZE.COMPLETE
  - [ ] StateAnalysis全9フィールドをdataに含める
- [ ] **4.3** decide_action print → SLog.log 移行（約10箇所）
  - [ ] DECIDE.START
  - [ ] DECIDE.COMPLETE
- [ ] **4.4** build_plan print → SLog.log 移行（約10箇所）
  - [ ] PLAN.START
  - [ ] PLAN.COMPLETE
- [ ] **4.5** build_response print → SLog.log 移行（約10箇所）
- [ ] **4.6** 画面不整合検出print → SLog.log 移行
  - [ ] SCREEN.INCONSISTENCY_DETECTED
  - [ ] SCREEN.INCONSISTENCY_RESOLVED
  - [ ] SCREEN.INCONSISTENCY_PERSISTENT
- [ ] **4.7** テスト実行

### Phase 5: simple_planner.py 移行 🔧

- [ ] **5.1** StructuredLogger のインポート追加
- [ ] **5.2** 画面分析print → SLog.log 移行（約10箇所）
- [ ] **5.3** プラン生成print → SLog.log 移行（約12箇所）
- [ ] **5.4** 目標評価print → SLog.log 移行（約10箇所）
- [ ] **5.5** 画面不整合リトライprint → SLog.log 移行（約8箇所）
- [ ] **5.6** テスト実行

### Phase 6: クリーンアップ 🧹

- [ ] **6.1** colorama依存の削除
  - [ ] `from colorama import Fore, Style` を削除
  - [ ] `Fore.CYAN`, `Fore.GREEN` 等の参照を削除
- [ ] **6.2** pyproject.tomlからcolorama依存を削除（使用箇所がなくなった場合）
- [ ] **6.3** 全テスト実行: `uv run pytest tests/ -v`
- [ ] **6.4** 実機テスト: `uv run pytest src/smartestiroid/test_android_app.py -k "TEST_0001"`
- [ ] **6.5** ログファイル出力確認
  - [ ] JSONLフォーマットが正しい
  - [ ] LLM入出力が完全に記録されている
  - [ ] ツール入出力が完全に記録されている
- [ ] **6.6** TEST_0023で画面不整合ログを確認
- [ ] **6.7** 不要なprint文の最終削除

---

## 📊 進捗トラッキング

| Phase | タスク数 | 完了 | ステータス |
|-------|---------|------|-----------|
| Phase 1 | 5 | 0 | ⬜ 未着手 |
| Phase 2 | 7 | 0 | ⬜ 未着手 |
| Phase 3 | 7 | 0 | ⬜ 未着手 |
| Phase 4 | 7 | 0 | ⬜ 未着手 |
| Phase 5 | 6 | 0 | ⬜ 未着手 |
| Phase 6 | 7 | 0 | ⬜ 未着手 |
| **合計** | **39** | **0** | ⬜ **0%** |

