# Examples

外部プロジェクトから `smartestiroid` を使用する例を示します。

## 前提条件

```bash
# smartestiroid を editable インストール
uv add smartestiroid --path /path/to/smartestiroid --editable

# または pip で
pip install -e /path/to/smartestiroid
```

## 基本的な使用例

### basic_usage.py

最もシンプルな使用例です。

```bash
uv run python examples/basic_usage.py
```

## オプション一覧

| オプション | 説明 |
|-----------|------|
| `--testsheet` | テストシートCSVのパス（カレントディレクトリ基準） |
| `--capabilities` | capabilities.jsonのパス |
| `--knowhow` | カスタムノウハウファイルのパス |
| `--knowhow-text` | ノウハウテキストを直接指定 |
| `--mini-model` | 高速・低コストのminiモデルを使用 |
