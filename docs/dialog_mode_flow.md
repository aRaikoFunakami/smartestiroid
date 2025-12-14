# ダイアログモード フロー説明書

## 概要

SmartestiRoidでは、テスト実行中にブロッキングダイアログ（利用規約、プライバシーポリシー等）が検出された場合、**ダイアログモード**に切り替えて処理を行います。本ドキュメントでは、モード管理の仕組みとフローを図解します。

---

## モードの種類

| モード | 説明 | 目標評価 | decide_action |
|--------|------|---------|---------------|
| **通常モード** | 目標ステップを達成するための処理 | ✅ 実施 | LLM呼び出し |
| **ダイアログモード** | ブロッキングダイアログを閉じるための処理 | ❌ スキップ | **スキップ** |

---

## plan_step からのフロー（テスト開始時）

テスト開始時の`plan_step`でもダイアログが検出される可能性があります。

```mermaid
flowchart TD
    subgraph "plan_step（テスト開始）"
        A[テスト開始] --> B[スクリーンショット取得]
        B --> C[parse_objective_steps<br/>目標ステップ解析]
        C --> D[analyze_screen<br/>画面分析]
        D --> E{blocking_dialogs?}
        
        E -->|あり| F[ダイアログモードへ遷移]
        E -->|なし| G[create_execution_plan<br/>通常計画生成]
        
        F --> H["通常計画 = 空<br/>(ダイアログ解消後に生成)"]
        H --> I[ダイアログ処理ステップ生成]
        I --> J[execute_step<br/>ダイアログモード]
        
        G --> K[execute_step<br/>通常モード]
    end
```

### plan_stepでのダイアログ検出の特徴

| 項目 | 説明 |
|------|------|
| 分析メソッド | `analyze_screen`（`analyze_state`とは別） |
| 通常計画 | 空のまま（ダイアログ解消後に`replan_step`で生成） |
| モード遷移 | その場で`enter_dialog_handling_mode()` |
| 目標進行 | 目標進行ロジックが存在しないため問題なし |

---

## replan_step からの全体フロー

```mermaid
flowchart TD
    subgraph "テスト実行ループ"
        A[ステップ実行] --> B[replan]
        B --> C{モード判定}
        
        C -->|通常モード| D[analyze_state<br/>通常モード用プロンプト]
        C -->|ダイアログモード| E[analyze_state<br/>ダイアログモード用プロンプト]
        
        D --> F{blocking_dialogs?}
        E --> G{blocking_dialogs?}
        
        F -->|あり| H[ダイアログモードへ遷移]
        F -->|なし| I[通常処理継続]
        
        G -->|あり| J[ダイアログモード継続]
        G -->|なし| K[通常モードへ復帰]
        
        H --> L[build_plan<br/>ダイアログ処理ステップ生成]
        I --> M[decide_action<br/>LLM呼び出し]
        J --> L
        K --> N[build_plan<br/>サスペンドしたステップを再開]
        
        M --> O{PLAN or RESPONSE?}
        O -->|PLAN| P[build_plan]
        O -->|RESPONSE| Q[build_response<br/>テスト終了]
        
        L --> R[Executor<br/>ダイアログモード用プロンプト]
        P --> S[Executor<br/>通常モード用プロンプト]
        N --> S
        
        R --> A
        S --> A
    end
```

---

## モード遷移詳細

```mermaid
stateDiagram-v2
    [*] --> 通常モード: テスト開始
    
    通常モード --> ダイアログモード: blocking_dialogs検出
    ダイアログモード --> ダイアログモード: blocking_dialogsあり<br/>(別のダイアログ)
    ダイアログモード --> 通常モード: blocking_dialogs=null<br/>(ダイアログ閉じた)
    
    通常モード --> [*]: 全目標完了<br/>or テスト失敗
```

---

## 各コンポーネントの動作

### 1. analyze_state

```mermaid
flowchart LR
    subgraph "analyze_state"
        A[モード確認] --> B{ダイアログモード?}
        B -->|Yes| C[ダイアログ用プロンプト]
        B -->|No| D[通常用プロンプト]
        
        C --> E[LLM呼び出し]
        D --> E
        
        E --> F[StateAnalysis]
    end
    
    subgraph "ダイアログモード時の特徴"
        G["current_objective_achieved = false (固定)"]
        H["目標達成評価をスキップ"]
        I["ダイアログが閉じたかを確認"]
    end
    
    C --> G
    C --> H
    C --> I
```

### 2. decide_action

```mermaid
flowchart LR
    subgraph "decide_action"
        A[モード確認] --> B{ダイアログモード?}
        B -->|Yes| C["decision = PLAN<br/>(LLMスキップ)"]
        B -->|No| D[LLM呼び出し]
        D --> E{判定結果}
        E -->|PLAN| F[PLAN]
        E -->|RESPONSE| G[RESPONSE]
    end
```

### 3. Executor

```mermaid
flowchart LR
    subgraph "Executor"
        A[モード確認] --> B{ダイアログモード?}
        B -->|Yes| C[ダイアログ用プロンプト]
        B -->|No| D[通常用プロンプト]
        
        C --> E["シンプルなゴール:<br/>ダイアログを閉じる"]
        D --> F["目標コンテキスト付き:<br/>目標ステップを達成"]
        
        E --> G[LLM実行]
        F --> G
    end
```

---

## ダイアログ処理の完全フロー

```mermaid
sequenceDiagram
    participant E as Executor
    participant R as Replanner
    participant O as ObjectiveProgress
    participant L as LLM
    
    Note over E,L: 通常モードでステップ実行中
    E->>R: replan()
    R->>O: is_handling_dialog()
    O-->>R: false (通常モード)
    R->>L: analyze_state (通常用プロンプト)
    L-->>R: blocking_dialogs検出!
    
    Note over R,O: ダイアログモードへ遷移
    R->>O: enter_dialog_handling_mode()
    R->>R: decide_action スキップ
    R->>L: build_plan (ダイアログ処理)
    L-->>R: ダイアログ処理ステップ
    R-->>E: Plan
    
    Note over E,L: ダイアログモードでステップ実行
    E->>E: Executor (ダイアログ用プロンプト)
    E->>R: replan()
    R->>O: is_handling_dialog()
    O-->>R: true (ダイアログモード)
    R->>L: analyze_state (ダイアログ用プロンプト)
    L-->>R: blocking_dialogs = null (閉じた!)
    
    Note over R,O: 通常モードへ復帰
    R->>O: exit_dialog_handling_mode()
    R->>L: build_plan (サスペンドしたステップを再開)
    L-->>R: 残りの実行ステップ
    R-->>E: Plan
    
    Note over E,L: 通常モードでステップ実行再開
```

---

## 目標進捗管理

### セーフガード

ダイアログモード中、または`blocking_dialogs`がある場合は、LLMが誤って`current_objective_achieved = true`を返しても、目標ステップは進みません。

```python
# simple_planner.py
# ★セーフガード★ ダイアログモード中、またはblocking_dialogsがある場合は目標を進めない
has_blocking_dialogs = bool(state_analysis.blocking_dialogs)
if state_analysis.current_objective_achieved and not objective_progress.is_handling_dialog() and not has_blocking_dialogs:
    # 上記の条件が false になるため、ここには入らない
    objective_progress.mark_current_completed(evidence=evidence)
    objective_progress.advance_to_next_objective()
```

> **重要**: 最初のダイアログ検出時は、まだダイアログモードに入る前（analyze_state後にモード遷移するため）なので、`has_blocking_dialogs`のチェックが必要です。

### 実行プランのサスペンド

```mermaid
flowchart TD
    subgraph "通常モード"
        A["実行プラン: [1]完了 [2]完了 [3]現在 [4]待機"]
    end
    
    subgraph "ダイアログ検出"
        B["blocking_dialogs: 利用規約ダイアログ"]
    end
    
    subgraph "ダイアログモード"
        C["元の実行プラン: サスペンド (位置: [3])"]
        D["ダイアログ処理プラン: [1]同意ボタンをタップ"]
    end
    
    subgraph "ダイアログ閉じた後"
        E["実行プラン復帰: [3]から再開"]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
```

---

## ログ出力

### ダイアログモード開始

```
[DIALOG] [START] 🔒 ダイアログ処理モード開始
  blocking_dialogs: 利用規約ダイアログ、閉じるボタン: com.example:id/agree
  frozen_steps: 3
  target_objective: [0] アプリを起動する
  stop_position: ホームタブをタップ...
```

### ダイアログモード終了

```
[DIALOG] [END] 🔓 ダイアログ処理モード終了 → 通常処理に復帰
  dialog_steps_executed: 2
  remaining_steps: 3
  resume_position: ホームタブをタップ...
```

### decide_actionスキップ

```
[PLAN] [SKIP] 🔒 ダイアログモード: decide_actionスキップ
  mode: dialog
  decision: PLAN
  reason: ダイアログ処理モード中: ダイアログ処理を継続
```

---

## トラブルシューティング

### 問題: ダイアログモード中に目標が進んでしまう

**原因**: LLMが誤って`current_objective_achieved = true`を返した

**解決**: セーフガードにより防止済み
```python
has_blocking_dialogs = bool(state_analysis.blocking_dialogs)
if state_analysis.current_objective_achieved and not objective_progress.is_handling_dialog() and not has_blocking_dialogs:
```

> **補足**: 最初のダイアログ検出時に目標が進む問題は、`has_blocking_dialogs`チェックで防止しています。通常モード用プロンプトにも「blocking_dialogsがある場合はcurrent_objective_achieved = falseとする」ルールが追加されています。

### 問題: ダイアログが閉じたのに通常モードに復帰しない

**確認ポイント**:
1. `blocking_dialogs`が`null`になっているか
2. `exit_dialog_handling_mode()`が呼ばれているか

### 問題: ダイアログ処理が無限ループする

**確認ポイント**:
1. ダイアログを閉じるボタンのresource-idが正しいか
2. 同じダイアログが何度も表示されていないか

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| [multi_stage_replanner.py](../src/smartestiroid/agents/multi_stage_replanner.py) | analyze_stateのモード別プロンプト |
| [simple_planner.py](../src/smartestiroid/agents/simple_planner.py) | decide_actionスキップ、セーフガード |
| [workflow.py](../src/smartestiroid/workflow.py) | Executorのモード別プロンプト |
| [progress.py](../src/smartestiroid/progress.py) | ObjectiveProgress、モード管理 |
| [dialog_mode_design.md](dialog_mode_design.md) | 設計書 |
