# ccquota

[Claude](https://claude.ai) の使用量をターミナルに表示する CLI ツール。セッション制限、週間制限、組織の支出、ユーザー別の内訳を確認できます。

[English README](README.md)

## 仕組み

`ccquota` は Claude の内部 API を直接呼び出します。通常の使用時にブラウザウィンドウは表示されません。

1. **ログイン（初回のみ）:** Chrome を開いて claude.ai にサインイン。セッションは `~/.config/ccquota/browser/` にローカル保存されます。
2. **表示（デフォルト）:** 保存済みセッションから Cookie を抽出（ヘッドレス、ウィンドウなし）し、[curl_cffi](https://github.com/lexiforest/curl_cffi) でブラウザの TLS フィンガープリントを模倣して Cloudflare を通過します。

## 出力例

```
  Your Usage
  ──────────────────────────────────────────────
  Session           ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 0%
  Weekly Limit      █████████████████████░░░░░░░░░ 72%
                    ↻ resets 4/29 (Wed) 17:00
  Claude Design     ████████████████░░░░░░░░░░░░░░ 54%
                    ↻ resets 4/29 (Wed) 17:00

  Organization (MyTeam)
  ──────────────────────────────────────────────
  Monthly Spend     ██████████████████░░░░░░░░░░░░ 60%  ($120.09 / $200.00)
  Balance           $79.90

  Spend by User
  ──────────────────────────────────────────────
  Alice                     $95.47
  Bob                       $24.67
```

## 必要な環境

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（推奨）または pip
- Google Chrome がインストールされていること

## インストール

```bash
git clone https://github.com/sanoakr/ccquota.git
cd ccquota
uv sync
uv run playwright install chromium
```

## 使い方

### 初回セットアップ

```bash
uv run ccquota login
```

Chrome ウィンドウが開きます。claude.ai にサインインすると、ログイン完了を自動検出します（最大 5 分待機）。セッションは `~/.config/ccquota/browser/` に保存されます。

### 使用量を表示

```bash
uv run ccquota           # デフォルト: 使用量を表示
uv run ccquota show      # サブコマンドを明示
uv run ccquota --debug   # API の生 JSON を表示
```

### コマンドとしてインストール

```bash
uv pip install -e .
ccquota
```

## 使用する API エンドポイント

| エンドポイント | データ |
|---|---|
| `/api/bootstrap` | 組織 ID、ユーザー情報 |
| `/api/organizations/{id}/usage` | セッション（5h）、週間、Design、Opus の使用率 |
| `/api/organizations/{id}/overage_spend_limit` | 月間支出と上限 |
| `/api/organizations/{id}/overage_spend_limits` | ユーザー別支出 |
| `/api/organizations/{id}/prepaid/credits` | プリペイド残高 |

## データの保存場所

すべてのデータは `~/.config/ccquota/browser/` にローカル保存されます。これは Chromium のユーザーデータディレクトリで、claude.ai のセッション Cookie が含まれています。他の場所に認証情報は保存されません。

ログアウトするにはディレクトリを削除します:

```bash
rm -rf ~/.config/ccquota/browser
```

## ライセンス

MIT
