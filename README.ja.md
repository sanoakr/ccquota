# ccquota

[Claude](https://claude.ai) の使用量をターミナルに表示する CLI ツール。セッション制限、週間制限を表示し、オプションで組織の支出やユーザー別の内訳も確認できます。複数アカウントに対応。

[English README](README.md)

## 仕組み

`ccquota` は Claude の内部 API を直接呼び出します。通常の使用時にブラウザウィンドウは表示されません。

1. **ログイン（アカウントごとに初回のみ）:** Chrome を開いて claude.ai にサインイン。セッションは `~/.config/ccquota/sessions/<name>/` にローカル保存されます。
2. **表示（デフォルト）:** 保存済みセッションから Cookie を抽出（ヘッドレス、ウィンドウなし）し、[curl_cffi](https://github.com/lexiforest/curl_cffi) でブラウザの TLS フィンガープリントを模倣して Cloudflare を通過します。

## 出力例

デフォルト — 保存済み全セッションの個人使用量を表示:

```
  Your Usage (Alice)
  ──────────────────────────────────────────────
  Session           ░░░░░░░░░░░░░░░░░░░░░░░░░ 0%
  Weekly Limit      ██████████████████░░░░░░░ 72%
                    ↻ resets 4/29 (Wed) 17:00
  Claude Design     █████████████░░░░░░░░░░░░ 54%
                    ↻ resets 4/29 (Wed) 17:00

  Your Usage (Bob)
  ──────────────────────────────────────────────
  Session           ░░░░░░░░░░░░░░░░░░░░░░░░░ 0%
  Weekly Limit      ████████░░░░░░░░░░░░░░░░░ 32%
                    ↻ resets 4/30 (Thu) 14:00
```

`--org` 指定時 — 各セッションの個人使用量に加え、組織の支出とユーザー別内訳を表示:

```
  Your Usage (Alice)
  ──────────────────────────────────────────────
  Session           ░░░░░░░░░░░░░░░░░░░░░░░░░ 0%
  Weekly Limit      ██████████████████░░░░░░░ 72%
                    ↻ resets 4/29 (Wed) 17:00
  Claude Design     █████████████░░░░░░░░░░░░ 54%
                    ↻ resets 4/29 (Wed) 17:00

  Organization (MyTeam)
  ──────────────────────────────────────────────
  Monthly Spend     ███████████████░░░░░░░░░░ 60%  ($120.09 / $200.00)
  Balance           $79.90

  Spend by User
  ──────────────────────────────────────────────
  Alice                     $95.47
  Bob                       $24.67

  Your Usage (Bob)
  ──────────────────────────────────────────────
  Session           ░░░░░░░░░░░░░░░░░░░░░░░░░ 0%
  Weekly Limit      ████████░░░░░░░░░░░░░░░░░ 32%
                    ↻ resets 4/30 (Thu) 14:00
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
```

## 使い方

### 初回セットアップ

```bash
uv run ccquota login
```

Chrome ウィンドウが開きます。claude.ai にサインインすると、ログイン完了を自動検出します（最大 5 分待機）。セッションは `~/.config/ccquota/sessions/<name>/` に保存されます。

### 別のアカウントを追加

`ccquota login` をもう一度実行して、別のアカウントでサインインするだけです:

```bash
ccquota login      # 1つ目のアカウント
ccquota login      # 2つ目のアカウント — 新しいブラウザが開く
```

### 使用量を表示

```bash
ccquota                  # 全アカウント（デフォルト）
ccquota --user Alice     # 特定のアカウントのみ
ccquota --org            # 全セッション + 組織の支出・ユーザー別内訳を表示
ccquota --watch          # 60秒ごとに自動更新
ccquota -w -n 30         # 30秒間隔で更新
ccquota -o -w            # 組織込み + watch モード
ccquota --debug          # API の生 JSON を表示
```

> `uv tool install -e .` でシステムワイドにインストールすると `ccquota` をどこからでも実行できます。未インストール時は `uv run` を付けてください。

### ログアウト

```bash
ccquota logout           # セッションを削除（1つだけなら自動選択）
ccquota logout Alice     # 特定のセッションを削除
ccquota logout --all     # すべてのセッションを削除
```

### オプション

| フラグ | 短縮 | 説明 |
|---|---|---|
| `--user NAME` | `-u NAME` | 指定したセッションのみ表示 |
| `--org` | `-o` | 全セッションの使用量 + 組織の支出・ユーザー別内訳を表示 |
| `--watch` | `-w` | 定期的に自動更新（デフォルト: 60秒） |
| `--interval SEC` | `-n SEC` | 更新間隔の秒数（デフォルト: 60） |
| `--debug` | | API の生 JSON データを表示 |

## 使用する API エンドポイント

| エンドポイント | データ | 条件 |
|---|---|---|
| `/api/bootstrap` | 組織 ID、ユーザー情報 | 常時 |
| `/api/organizations/{id}/usage` | セッション（5h）、週間、Design、Opus の使用率 | 常時 |
| `/api/organizations/{id}/overage_spend_limit` | 月間支出と上限 | `--org` |
| `/api/organizations/{id}/overage_spend_limits` | ユーザー別支出 | `--org` |
| `/api/organizations/{id}/prepaid/credits` | プリペイド残高 | `--org` |

## データの保存場所

セッションデータは `~/.config/ccquota/sessions/` に保存され、アカウントごとにサブディレクトリが作られます。各ディレクトリは Chromium のユーザーデータディレクトリで、claude.ai のセッション Cookie が含まれています。他の場所に認証情報は保存されません。

旧形式の単一セッションデータ（`~/.config/ccquota/browser/`）は初回実行時に自動で移行されます。

## ライセンス

MIT
