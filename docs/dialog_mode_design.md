# ダイアログモード分離設計書

## 概要

テスト実行中にブロッキングダイアログ（利用規約、プライバシーポリシー等）が検出された場合、通常のテスト実行フローとは異なる「ダイアログモード」で処理を行う。本設計書では、モード別にLLMプロンプトを分離し、各コンポーネントの責務を明確化することで、誤判定を防止する。

---

## 問題点（現状）

### 1. 目標達成の誤判定
- ダイアログモード中でもLLMが `current_objective_achieved = true` を返すことがある
- 実行プランがダイアログ処理用に上書きされているため、「プラン完了 = 目標達成」という判定が誤り

### 2. 不要なLLM呼び出し
- ダイアログモード中は常に `PLAN` を返すべきだが、`decide_action` でLLMを呼び出している
- トークンの無駄遣いと誤判定リスク

### 3. Executorプロンプトの最適化不足
- ダイアログ処理に特化した指示がない
- 通常モードと同じプロンプトでダイアログを閉じようとしている

---

## 設計方針

### モード別プロンプト分離

| コンポーネント | 通常モード | ダイアログモード |
|--------------|-----------|----------------|
| **analyze_state** | 目標達成評価を含む | 目標達成評価をスキップ（常にfalse） |
| **decide_action** | LLMで判定 | **スキップ**（常にPLAN） |
| **Executor** | 目標ステップ達成のためのプロンプト | ダイアログ処理に特化したプロンプト |
| **build_plan** | 通常プラン生成 | 既にコードで分岐済み（変更なし） |
| **build_response** | 結果生成 | ダイアログモード中は呼ばれない |

---

## モード判定ロジック

### モード情報の取得
```python
dialog_mode = objective_progress.is_handling_dialog()
```

### モード遷移タイミング

```
analyze_state呼び出し前: 現在のモードでプロンプト選択
    ↓
analyze_state実行: blocking_dialogs を検出
    ↓
analyze_state完了後: blocking_dialogs に基づいてモード遷移
    ↓
次のステージ: 新しいモードで処理
```

### モード遷移パターン

| 前の状態 | blocking_dialogs | 新しい状態 | analyze_stateプロンプト |
|---------|-----------------|-----------|------------------------|
| 通常 | なし | 通常（継続） | 通常モード用 |
| 通常 | あり | **ダイアログへ遷移** | 通常モード用 |
| ダイアログ | あり | ダイアログ（継続） | ダイアログモード用 |
| ダイアログ | なし | **通常へ復帰** | ダイアログモード用 |

---

## 各コンポーネントの詳細設計

### 1. analyze_state（multi_stage_replanner.py）

#### 通常モード用プロンプト
- 目標達成評価（`current_objective_achieved`）を実施
- ブロッキングダイアログの検出
- 実行プラン進捗の評価

#### ダイアログモード用プロンプト
- **目標達成評価をスキップ**（`current_objective_achieved = false` 固定）
- ダイアログが閉じたかどうかの確認に特化
- 新たなブロッキングダイアログの検出

```python
async def analyze_state(self, ..., dialog_mode: bool = False) -> StateAnalysis:
    if dialog_mode:
        prompt_text = self._build_dialog_mode_analyze_prompt(...)
    else:
        prompt_text = self._build_normal_mode_analyze_prompt(...)
```

### 2. decide_action（simple_planner.py）

#### 通常モード
- LLMを呼び出してPLAN/RESPONSEを判定

#### ダイアログモード
- **LLM呼び出しをスキップ**
- 常に `decision = "PLAN"` を返す

```python
if objective_progress.is_handling_dialog():
    # ダイアログモード中は常にPLAN（LLM呼び出しスキップ）
    decision = "PLAN"
    reason = "ダイアログ処理モード中: ダイアログ処理を継続"
    SLog.log(LogCategory.PLAN, LogEvent.SKIP, {...}, "ダイアログモード: decide_actionスキップ")
else:
    # 通常モードはLLMで判定
    decision, reason = await self.replanner.decide_action(...)
```

### 3. Executor（workflow.py）

#### 通常モード用プロンプト
- 目標ステップのコンテキストを含む
- 通常のツール使用ルール

#### ダイアログモード用プロンプト
- ダイアログ処理に特化
- シンプルなゴール設定（ダイアログを閉じる）

```python
if dialog_mode:
    task_formatted = self._build_dialog_executor_prompt(task, ui_elements)
else:
    task_formatted = self._build_normal_executor_prompt(task, ui_elements, objective_context)
```

### 4. セーフガード（simple_planner.py）

ダイアログモード中、または`blocking_dialogs`がある場合は目標ステップを進めないようにセーフガードを追加：

```python
# 現在の目標ステップが達成されている場合は次の目標に進む
# ★セーフガード★ ダイアログモード中、またはblocking_dialogsがある場合は目標を進めない
has_blocking_dialogs = bool(state_analysis.blocking_dialogs)
if state_analysis.current_objective_achieved and not objective_progress.is_handling_dialog() and not has_blocking_dialogs:
    # 目標進行ロジック
    ...
```

> **注意**: 通常モード用プロンプトでダイアログが初めて検出された場合、モード遷移はanalyze_state後に行われます。そのため、`has_blocking_dialogs`チェックが必要です。

---

## StateAnalysisモデル

### ダイアログモード時のフィールド

| フィールド | 通常モード | ダイアログモード |
|-----------|-----------|----------------|
| `blocking_dialogs` | 検出されたダイアログ | 検出されたダイアログ（or null） |
| `current_objective_achieved` | true/false | **常にfalse** |
| `current_objective_evidence` | 達成根拠 | "ダイアログ処理モード中のため評価保留" |
| `suggested_next_action` | 次のアクション提案 | ダイアログ閉じる操作提案 |

---

## 実装ファイル

| ファイル | 変更内容 |
|---------|---------|
| `multi_stage_replanner.py` | analyze_stateのモード別プロンプト |
| `simple_planner.py` | decide_actionスキップ、セーフガード追加 |
| `workflow.py` | Executorのモード別プロンプト |

---

## 期待される効果

1. **誤判定の防止**: ダイアログモード中に目標が進むことを防止
2. **トークン節約**: decide_actionのLLM呼び出しスキップ
3. **処理の明確化**: 各モードで何をすべきかが明確
4. **デバッグ容易性**: モード別のログ出力で問題追跡が容易
