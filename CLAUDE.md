# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
日本語で応答してください

## 概要

住信SBIネット銀行の口座振替通知メールから今月の引き落とし金額を自動集計するPythonツールです。Gmail APIを使用してメールを取得し、正規表現で口座振替先と金額を抽出してCSVファイルに保存します。

## 実行方法

### 基本実行（メール取得のみ）
```bash
uv run main.py 
```

### メール取得 + データ分析・グラフ表示
```bash
uv run main.py --analyze
# または
uv run main.py -a
```

### データ分析のみ実行（メール取得なし）
```bash
uv run main.py --analyze-only
```

### 分析モジュール単体実行
```bash
uv run analyzer.py
```

## テスト実行方法

```bash
uv run pytest
```

## リント・フォーマット実行方法

```bash
# リントチェック
uv run ruff check

# フォーマット
uv run ruff format

# リント + フォーマット（一括実行）
uv run ruff check --fix && uv run ruff format
```

## 前提条件

1. uvが必要(uvでPython 3.13のvenv環境を作る)
2. Gmail APIの認証設定が必要：
   - `credentials.json` ファイル（Google Cloud ConsoleでGmail API用の認証情報）
   - 初回実行時にOAuth認証フローが起動し、`token.pickle`が作成される
