# ObjectiveProgress 設計書

## 概要

ユーザーが定義した**目標ステップ（Objective Steps）**と、LLMが生成する**実行計画（Execution Plan）**を明確に分離し、テスト進捗を正確に追跡するための設計。

---

## 問題点（現状）

### 1. 用語の混同
- ユーザー定義の「目標ステップ」とLLM生成の「実行ステップ」が両方「steps」と呼ばれている
- 進捗評価時に「4/4ステップ完了」がどちらを指すか不明確

### 2. 進捗評価の基準が間違っている
- LLMの実行ステップ完了率で進捗を評価している
- 本来はユーザー目標の達成度で評価すべき

### 3. PLAN/RESPONSE判断の誤り
- 実行ステップが全て完了しても、目標未達成ならPLANを返すべき
- 現状は実行ステップ数で判断している

---

## 設計方針

### 用語の明確化

| 用語 | 説明 | 例 |
|------|------|-----|
| **Objective Step** | ユーザーが達成したい目標の個別ステップ | 「yahoo.co.jpがURLバーに入力される」 |
| **Execution Plan** | 特定のObjective Stepを達成するためのLLM生成アクション列 | `["URLバーをタップ", "yahoo.co.jpを入力", "Enterを押す"]` |
| **Recovery Step** | ブロック（ダイアログ等）回避のための特殊なステップ | 「広告ダイアログを閉じる」 |

### 階層構造

```
ObjectiveProgress
├── objective_steps[0] (type=objective) "Chromeが起動している"
│   └── execution_plan: ["activate_app com.android.chrome"]
│
├── objective_steps[1] (type=objective) "yahoo.co.jp入力確定"
│   └── execution_plan: ["URLバータップ", "入力", "Enter"]
│       │
│       └── ⚠️ ブロック検出時に動的挿入 ↓
│
├── objective_steps[1.1] (type=recovery) "広告ダイアログを閉じる"
│   ├── parent_index: 1
│   └── execution_plan: ["Got itボタンをクリック"]
│
└── objective_steps[2] (type=objective) "星マークをクリック"
    └── execution_plan: ["星マークをタップ", "状態確認"]
```

---

## データモデル

### ObjectiveStep

```python
class ObjectiveStep(BaseModel):
    """目標ステップ（通常目標 or 回避用）"""
    
    index: int
    """ステップのインデックス（0から開始）"""
    
    description: str
    """ステップの説明（例: "Chromeが起動している"）"""
    
    step_type: Literal["objective", "recovery"]
    """ステップの種類
    - objective: ユーザー定義の目標ステップ
    - recovery: ブロック回避のための一時ステップ
    """
    
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"]
    """ステップの状態
    - pending: 未開始
    - in_progress: 実行中
    - completed: 完了
    - failed: 失敗
    - skipped: スキップ（recovery完了後の元ステップ再開時など）
    """
    
    execution_plan: List[str] = Field(default_factory=list)
    """このステップを達成するための実行計画（LLMが生成）"""
    
    executed_actions: List[ExecutedAction] = Field(default_factory=list)
    """実行済みアクションの履歴"""
    
    parent_index: Optional[int] = None
    """recovery時のみ: 派生元のobjective stepのインデックス"""
    
    blocking_reason: Optional[str] = None
    """recovery時のみ: ブロックされた理由（例: "広告ダイアログが表示された"）"""
    
    completion_evidence: Optional[str] = None
    """完了時: 達成の根拠（画面要素やロケーター情報）"""


class ExecutedAction(BaseModel):
    """実行されたアクションの記録"""
    
    action: str
    """アクション内容"""
    
    tool_name: str
    """使用したツール名（例: click_element, input_text）"""
    
    result: str
    """実行結果"""
    
    timestamp: str
    """実行時刻"""
```

### ObjectiveProgress

```python
class ObjectiveProgress(BaseModel):
    """目標全体の進捗状態"""
    
    original_input: str
    """ユーザーの元の入力（テストシートの手順）"""
    
    objective_steps: List[ObjectiveStep]
    """全ステップのリスト（objective + recovery）"""
    
    current_step_index: int
    """現在実行中のステップのインデックス"""
    
    def get_current_step(self) -> ObjectiveStep:
        """現在実行中のステップを取得"""
        return self.objective_steps[self.current_step_index]
    
    def get_objective_steps_only(self) -> List[ObjectiveStep]:
        """objectiveタイプのステップのみ取得（recoveryを除く）"""
        return [s for s in self.objective_steps if s.step_type == "objective"]
    
    def get_completed_objectives_count(self) -> int:
        """完了したobjectiveステップ数を取得"""
        return len([s for s in self.objective_steps 
                    if s.step_type == "objective" and s.status == "completed"])
    
    def get_total_objectives_count(self) -> int:
        """全objectiveステップ数を取得"""
        return len([s for s in self.objective_steps if s.step_type == "objective"])
    
    def insert_recovery_step(
        self, 
        parent_index: int, 
        description: str, 
        blocking_reason: str,
        execution_plan: List[str]
    ) -> int:
        """recovery_stepを現在位置の次に挿入し、そのindexを返す"""
        insert_pos = self.current_step_index + 1
        recovery_step = ObjectiveStep(
            index=insert_pos,
            description=description,
            step_type="recovery",
            status="pending",
            execution_plan=execution_plan,
            parent_index=parent_index,
            blocking_reason=blocking_reason
        )
        self.objective_steps.insert(insert_pos, recovery_step)
        # 挿入位置以降のindexを更新
        for i in range(insert_pos + 1, len(self.objective_steps)):
            self.objective_steps[i].index = i
        return insert_pos
    
    def advance_to_next_step(self) -> bool:
        """次のステップに進む。進めた場合True、終了の場合False"""
        if self.current_step_index < len(self.objective_steps) - 1:
            self.current_step_index += 1
            self.objective_steps[self.current_step_index].status = "in_progress"
            return True
        return False
    
    def return_to_parent_objective(self) -> bool:
        """recovery完了後、親のobjectiveに戻る"""
        current = self.get_current_step()
        if current.step_type == "recovery" and current.parent_index is not None:
            # 親のobjectiveを再度in_progressに
            parent = self.objective_steps[current.parent_index]
            parent.status = "in_progress"
            self.current_step_index = current.parent_index
            return True
        return False
    
    def get_progress_summary(self) -> str:
        """進捗サマリーを文字列で取得"""
        completed = self.get_completed_objectives_count()
        total = self.get_total_objectives_count()
        current = self.get_current_step()
        
        lines = [
            f"【目標進捗】 {completed}/{total} 完了 ({completed/total*100:.0f}%)" if total > 0 else "【目標進捗】 0/0",
            f"【現在のステップ】 [{current.step_type}] {current.description}",
            f"【ステータス】 {current.status}",
        ]
        
        if current.step_type == "recovery":
            lines.append(f"【ブロック理由】 {current.blocking_reason}")
            lines.append(f"【親ステップ】 #{current.parent_index}")
        
        return "\n".join(lines)
```

---

## 処理フロー

### 1. 初期化フロー（plan_step）

```
ユーザー入力: "1. Chrome起動 2. yahoo.co.jp入力 3. 星マーククリック"
                    ↓
        parse_objective_steps() [LLM呼び出し]
                    ↓
ObjectiveProgress {
    original_input: "1. Chrome起動 2. yahoo.co.jp入力 3. 星マーククリック",
    objective_steps: [
        {index: 0, description: "Chromeが起動している", step_type: "objective", status: "pending"},
        {index: 1, description: "yahoo.co.jpがURLバーに入力される", step_type: "objective", status: "pending"},
        {index: 2, description: "星マークがクリックされる", step_type: "objective", status: "pending"},
    ],
    current_step_index: 0
}
                    ↓
        create_execution_plan_for_objective(step[0]) [LLM呼び出し]
                    ↓
step[0].execution_plan = ["activate_app com.android.chrome"]
step[0].status = "in_progress"
```

### 2. 実行フロー（execute_step）

```
objective_steps[0] (Chromeが起動している)
    status: in_progress
    execution_plan: ["activate_app com.android.chrome"]
                    ↓
        execute_step() - execution_planのアクションを実行
                    ↓
        executed_actions に結果を記録
```

### 3. 評価・遷移フロー（replan_step）

```
analyze_state() で画面分析
                    ↓
┌─────────────────────────────────────────────────────┐
│ 分岐判断                                            │
├─────────────────────────────────────────────────────┤
│ A) ブロック検出（ダイアログ等）                      │
│    → insert_recovery_step() で回避ステップ挿入      │
│    → recovery_step の execution_plan を生成         │
│    → current_step_index を recovery に移動          │
│                                                     │
│ B) 現在のobjective達成                              │
│    → step.status = "completed"                      │
│    → advance_to_next_step()                         │
│    → 次のobjective の execution_plan を生成         │
│                                                     │
│ C) 現在のobjective未達成（ブロックなし）            │
│    → execution_plan を再生成/調整                   │
│                                                     │
│ D) recovery完了                                     │
│    → return_to_parent_objective()                   │
│    → 親objective の execution_plan を再生成         │
│                                                     │
│ E) 全objective完了                                  │
│    → RESPONSE を返す（テスト終了）                  │
└─────────────────────────────────────────────────────┘
```

### 4. Recovery フロー（詳細）

```
objective_step[1] 実行中
    description: "yahoo.co.jpがURLバーに入力される"
    status: in_progress
                    ↓
analyze_state() → ブロック検出！
    blocking_dialogs: "広告プライバシーダイアログ「Got it」"
                    ↓
insert_recovery_step(
    parent_index=1,
    description="広告ダイアログを閉じる",
    blocking_reason="広告プライバシーダイアログが表示されている",
    execution_plan=["Got itボタンをクリック"]
)
                    ↓
objective_steps リスト更新:
    [0] objective - Chrome起動 (completed)
    [1] objective - yahoo.co.jp入力 (in_progress) ← 親
    [2] recovery - ダイアログを閉じる (pending) ← 新規挿入
    [3] objective - 星マーククリック (pending)
                    ↓
current_step_index = 2 (recovery)
recovery_step.status = "in_progress"
                    ↓
execute_step() - recovery の execution_plan 実行
                    ↓
recovery_step.status = "completed"
                    ↓
return_to_parent_objective()
    → current_step_index = 1 (親objective)
    → 親objective の execution_plan を再生成
                    ↓
通常フローに復帰
```

---

## LLMプロンプト設計

### parse_objective_steps

```
以下のテスト目標から、個別の検証ステップを抽出してください。

【テスト目標】
{user_input}

【指示】
- 目標を達成するために確認すべき個別ステップを抽出する
- 各ステップは「何が達成されるべきか」という目標レベルで記述
- 具体的なUI操作ではなく、期待される状態や結果を記述
- 順序を保持すること

【出力形式】
steps: ["ステップ1の説明", "ステップ2の説明", ...]
```

### create_execution_plan_for_objective

```
以下の目標ステップを達成するための実行計画を作成してください。

【目標ステップ】
{objective_step.description}

【現在の画面状態】
{screen_analysis}

【指示】
- 目標を達成するために必要な具体的なアクションを列挙
- 各アクションはAppiumツールで実行可能な単位
- 不要なステップは含めない
- 画面状態を考慮して最適なアクション順序を決定

【出力形式】
steps: ["アクション1", "アクション2", ...]
```

### evaluate_objective_completion

```
以下の目標ステップが達成されているか評価してください。

【目標ステップ】
{objective_step.description}

【画面状態分析】
{screen_analysis}

【指示】
- 画面のロケーター情報とスクリーンショットから目標達成を判断
- 達成/未達成の根拠を明確に示す

【出力形式】
achieved: true/false
evidence: "判断根拠の説明"
```

---

## 状態遷移図

```
                    ┌─────────────┐
                    │   pending   │
                    └──────┬──────┘
                           │ start
                           ▼
                    ┌─────────────┐
              ┌─────│ in_progress │─────┐
              │     └──────┬──────┘     │
              │            │            │
        block │     complete│      fail │
        detected           │            │
              │            ▼            │
              │     ┌─────────────┐     │
              │     │  completed  │     │
              │     └─────────────┘     │
              │                         │
              ▼                         ▼
       ┌─────────────┐           ┌─────────────┐
       │  (recovery  │           │   failed    │
       │   挿入)     │           └─────────────┘
       └─────────────┘
```

---

## 影響範囲

### 変更が必要なファイル

1. **models.py**
   - `ObjectiveStep` モデル追加
   - `ObjectiveProgress` モデル追加
   - `ExecutedAction` モデル追加

2. **simple_planner.py**
   - `parse_objective_steps()` メソッド追加
   - `create_execution_plan_for_objective()` メソッド追加
   - `evaluate_objective_completion()` メソッド追加
   - `create_plan()` 修正（ObjectiveProgress初期化）

3. **multi_stage_replanner.py**
   - `analyze_state()` 修正（ObjectiveProgressを参照）
   - `decide_action()` 修正（objective達成度で判断）
   - `build_plan()` 修正（execution_plan生成）
   - recovery_step挿入ロジック追加

4. **workflow.py**
   - `PlanExecute` TypedDict修正（objective_progress追加）
   - `plan_step()` 修正
   - `execute_step()` 修正
   - `replan_step()` 修正

---

## 実装順序

1. **Phase 1: モデル定義**
   - [ ] `models.py` に `ObjectiveStep`, `ObjectiveProgress`, `ExecutedAction` 追加

2. **Phase 2: Planner修正**
   - [ ] `simple_planner.py` に目標解析・実行計画生成メソッド追加

3. **Phase 3: Replanner修正**
   - [ ] `multi_stage_replanner.py` の各メソッドをObjectiveProgress対応に修正

4. **Phase 4: Workflow修正**
   - [ ] `workflow.py` の各ステップ関数を修正

5. **Phase 5: テスト・検証**
   - [ ] 単体テスト追加
   - [ ] 統合テスト実行

---

## 期待される効果

1. **進捗の正確な把握**: 「目標3つ中2つ完了」が明確に
2. **デバッグ容易性**: どの目標でどんなrecoveryが発生したか追跡可能
3. **PLAN/RESPONSE判断の正確化**: 目標達成度に基づく判断
4. **Allureレポートの改善**: objective単位でのステップ表示
