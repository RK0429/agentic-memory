# 要件定義書: agentic-memory Knowledge & Values 拡張

| 項目 | 内容 |
|---|---|
| バージョン | 0.1.0（ドラフト） |
| 最終更新日 | 2026-04-09 |
| ステータス | ドラフト — レビュー待ち |
| 作成者 | エージェント（requirements-definer） |
| レビュー者 | — |

---

## 変更履歴

| バージョン | 日付 | 変更内容 |
|---|---|---|
| 0.1.0 | 2026-04-08 | 初版作成 |
| — | 2026-04-09 | レビュー指摘対応: Values 節配置移動、Evidence.date 形式明記、domain/category 適用タイミング補足 |
| — | 2026-04-09 | レビュー指摘対応: Distillation 定義の Values 蒸留限定化、昇格候補通知の出力仕様具体化、REQ-FUNC-016 昇格条件チェック追加、REQ-FUNC-026 公開 API 契約追記、期間表記統一 |
| — | 2026-04-09 | レビュー指摘対応: F-01〜F-10（REQ-NF-003 例外明記、蒸留時機密スキップ、_state.md 日付フィルタ除外、update 重複チェック、CONTRADICT_EXISTING 根拠追記、promoted 削除マーカー検証、REQ-NF-002 計測境界明確化、蒸留トリガー _state.md 除外根拠、health check lazy 生成セマンティクス） |
| — | 2026-04-09 | レビュー指摘対応: BM25 max-normalization 定義（REQ-FUNC-007）、_state.md 由来 Evidence.date 導出規則（REQ-FUNC-011）、values_delete confirm ガードレール追加（REQ-FUNC-024）、削除 reason の非永続化明記（REQ-FUNC-023, REQ-FUNC-024）、未確定事項セクションの解決済み分離 |
| — | 2026-04-09 | レビュー指摘対応: 「実質同一」の同値条件を用語集に明文化（NFC + trim + 空白圧縮 → case-sensitive 完全一致）、Values evidence 初期10件保持時の順序規則を明文化（提供リスト先頭10件保持、末尾切り捨て） |
| — | 2026-04-09 | レビュー指摘対応（cross-doc review）: REQ-FUNC-025 出力契約追加、REQ-FUNC-034 受け入れ基準・処理・出力追加、REQ-NF-004 に related リンク整合性チェックと fix=true の修復スコープ明確化を追加、REQ-FUNC-017/018 を参照 alias として明確化 |
| — | 2026-04-09 | レビュー指摘対応（再レビュー残件）: REQ-FUNC-025 / REQ-FUNC-034 の出力節に `{ok: true, ...}` エンベロープ規約との対応を明示 |
| — | 2026-04-10 | レビュー指摘対応: REQ-FUNC-034 から内部設計識別子（`syncCheck()`, `ValuesEntry.demote()`, `PromotionState`）を除去し観測可能な振る舞い記述へ変更、未確定事項 #3/#4（domain/category 分類体系）を解決済みへ移動 |

---

## 1. プロジェクト概要

### 1.1 背景・動機

現在の agentic-memory（v0.13.0）はセッション単位の「具体的な記録」（Memory）に特化しており、記録の蓄積から抽象的な知見を蒸留する仕組みがない。エージェントが蓄積した Memory から知識（Knowledge）と価値観（Values）を自律的に形成し、「使えば使うほど良くなる」体験を実現したい。

**コアコンセプト**: 「人と AI が共に成長していく」

### 1.2 目的

agentic-memory に Knowledge 層と Values 層を追加し、以下を実現する。

1. **Knowledge**: エージェントがドメイン知識を自律的に蓄積・体系化し、ユーザーの学習を支援できるようにする
2. **Values**: エージェントがユーザーの判断傾向を自律的に学習し、代理人としての行動精度を継続的に改善する

### 1.3 体系的分類

| 層 | 名称 | 性質 | 情報源 | 行動への影響 |
|---|---|---|---|---|
| 具体 | **Memory** | 具体的な宣言・手続き | セッション記録 | ローリングステートとして参照 |
| 抽象（宣言） | **Knowledge** | 事実・概念・ルール | Memory 蒸留、自律収集、ユーザー教示+リサーチ | Tips/クイズとして提供（push は別実装） |
| 抽象（手続き） | **Values** | 判断傾向・選好パターン | Memory 蒸留（判断履歴の傾向抽出） | 判断時に検索して参照。高確信度のものは AGENTS.md に昇格 |

### 1.4 対象ユーザー

agentic-workspace を利用する開発者（主に本プロジェクトのオーナー自身）。

### 1.5 スコープ

**スコープ内:**

- Knowledge / Values のデータモデル・ストレージ設計
- Knowledge / Values の CRUD 操作（MCP ツール）
- Memory → Knowledge / Values の蒸留パイプライン
- Knowledge の自律収集ワークフロー定義
- Values の AGENTS.md 昇格メカニズム
- 検索・参照統合
- AGENTS.md の記憶管理セクション改修
- 関連スキル（retrospective 等）の拡張

**スコープ外:**

- push 型配信の実装（Tips/クイズの定期配信）。エージェントが MCP ツールを使って自律的に実行する前提であり、本要件定義では Knowledge/Values の管理基盤のみを対象とする

### 1.6 制約条件

| 制約 | 内容 |
|---|---|
| 技術基盤 | 既存の agentic-memory（Python, MCP サーバー, v0.13.0）のアーキテクチャ上に構築する |
| ストレージ | 既存の `memory/` ディレクトリ構造と共存する。外部 DB は使用しない |
| 互換性 | 既存の Memory 機能（19 MCP ツール）に破壊的変更を加えない |
| 検索エンジン | 既存の BM25+ スコアリングエンジンを流用・拡張する |

### 1.7 成功基準

| # | 基準 | 検証方法 |
|---|---|---|
| SC-1 | エージェントが Memory ノートから Knowledge を自律的に抽出・登録できる | `memory_distill_knowledge` の `dry_run=false` で Knowledge エントリが作成されることを確認 |
| SC-2 | エージェントが Memory ノートから Values を自律的に抽出・登録できる | `memory_distill_values` の `dry_run=false` で Values エントリが作成されることを確認 |
| SC-3 | エージェントが判断時に関連する Values を参照できる | `memory_values_search` でコンテキストに関連する Values が返されることを確認 |
| SC-4 | 高確信度の Values が AGENTS.md に昇格できる | `memory_values_promote` で AGENTS.md の「内面化された価値観」セクションに反映されることを確認 |
| SC-5 | 既存の Memory 機能が正常に動作し続ける | 既存テストスイート（270+ テストケース）が全件パスすること |

---

## 2. 用語集

| 用語 | 定義 |
|---|---|
| **Memory** | セッション単位の具体的な記録。ノート（`.md` ファイル）とローリングステート（`_state.md`）で構成される。既存の agentic-memory の中核概念 |
| **Knowledge** | Memory から蒸留された、または自律的に収集された抽象的な宣言的知識。事実・概念・定義・ルールを含む |
| **Values** | Memory の判断履歴から蒸留された、ユーザーの判断傾向・選好パターン。エージェントの行動指針として機能する |
| **蒸留（Distillation）** | Memory ノート群から一般化可能な Knowledge や Values を抽出するプロセス。Values 蒸留ではローリングステート（`_state.md`）の「主要な判断」セクションも入力とする |
| **昇格（Promotion）** | 高確信度の Values エントリを AGENTS.md に反映し、エージェントの常時参照指針とするプロセス |
| **降格（Demotion）** | 昇格済みの Values を AGENTS.md から削除し、通常の Values エントリに戻すプロセス |
| **確信度（Confidence）** | Values エントリに付与される 0.0〜1.0 の数値。ユーザーの判断傾向としての確実性を表す。evidence の蓄積により上昇し、矛盾する事例により低下する |
| **正確性（Accuracy）** | Knowledge エントリに付与される品質指標。`verified`（複数ソースで確認済み）/ `likely`（単一ソースで確認）/ `uncertain`（未確認）の3段階 |
| **Evidence** | Values の根拠となる具体的な事例。参照先（`ref`: Memory ノートパスまたは `_state.md` セクション参照）、要約（`summary`）、日付（`date`: `YYYY-MM-DD` 形式）で構成される |
| **Source** | Knowledge の引用元。Memory ノートパス、URL、ユーザー教示等の参照情報 |
| **SIGFB** | Skill Feedback Signal。ツール・スキル・サブエージェントの使用体験を記録するフィードバック信号（既存概念） |
| **ローリングステート** | セッション横断で保持されるエージェントの作業状態。`_state.md` に記録される（既存概念） |
| **実質同一（Substantial Equivalence）** | 重複判定における文字列の同値条件。比較対象の各フィールドに対して (1) Unicode NFC 正規化 → (2) 前後空白の除去（trim）→ (3) 連続空白文字の単一スペースへの圧縮 を適用した後、case-sensitive で完全一致する場合に「実質同一」とする。Knowledge では `title` + `domain` + `content`、Values では `description` + `category` が比較対象フィールドとなる |

---

## 3. 機能要件

### 3.1 機能領域マップ

| 領域コード | 機能領域 | 要件数 | 対応要件 |
|---|---|---|---|
| K | Knowledge 管理 | 7 | REQ-FUNC-001, 003, 004, 005, 006, 023, 030 |
| V | Values 管理 | 8 | REQ-FUNC-002, 007, 008, 009, 024, 025, 031, 034 |
| D | 蒸留エンジン | 5 | REQ-FUNC-010, 011, 012, 013, 026 |
| R | Knowledge 自律収集 | 3 | REQ-FUNC-014, 027, 033 |
| P | Values 昇格 | 3 | REQ-FUNC-015, 016, 028 |
| S | 検索・参照統合 | 3 | REQ-FUNC-017, 018, 032 |
| A | AGENTS.md / スキル改修 | 5 | REQ-FUNC-019, 020, 021, 022, 029 |

> **注記**: REQ-FUNC-003（Knowledge / Values ストレージ設計）は K/V 共通要件だが、ストレージの初出定義として K に計上している。

### 3.2 MoSCoW サマリ

| 優先度 | 件数 | 概要 |
|---|---|---|
| Must | 22 | データモデル、CRUD コア、蒸留エンジン、昇格判定・反映、AGENTS.md 改修 |
| Should | 7 | 削除、一括参照、蒸留トリガー、ユーザー教示 Knowledge 化、昇格同期、retrospective 拡張 |
| Could | 5 | 統計、横断検索、関連知識の自律探索、降格メカニズム |
| Won't | 0 | — |

**MCP ツール共通規約:** 以降で定義する全 MCP ツールは、既存ツールと同様に `memory_dir`（任意、記憶ディレクトリの指定）パラメータを受け取る。成功レスポンスは `ok` フィールドを含むエンベロープ形式で返す。`warnings` フィールドは警告がある場合にのみ付与される（`list[str]`）。各ツール定義では共通パラメータを省略し、ツール固有のパラメータのみを記載する。

---

### 3.3 K: Knowledge 管理

#### REQ-FUNC-001: Knowledge データモデル

- **ストーリー**: エージェントとして、Knowledge エントリに正確性・引用元・ユーザー理解度等のメタデータを紐づけたい。それはユーザーの学習状況に応じた知識提供を可能にするためだ。
- **受け入れ基準**:
  - Given 任意の Knowledge エントリ, When シリアライズ/デシリアライズ, Then 全属性が欠損なく復元される
  - Given `accuracy` に無効な値が指定された場合, When バリデーション実行, Then エラーを返す
  - Given `title` + `domain` + `content` が既存エントリと実質同一の場合, When 登録試行, Then 重複エラーを返す
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-003, REQ-FUNC-004

**Knowledge エントリ属性:**

| 属性 | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | 自動 | 一意識別子（作成時に UUID を生成し `k-` プレフィックスを付与。以降は不変。内容の変化に依存しない安定した識別子） |
| `title` | string | Yes | 知識のタイトル・トピック |
| `content` | string | Yes | 知識の本体（定義・説明・ルール等） |
| `domain` | string | Yes | ドメイン分類（例: `machine-learning`, `rust`, `company-rules`）。kebab-case に正規化される |
| `tags` | list[string] | No | 検索用タグ |
| `accuracy` | enum | No | `verified` / `likely` / `uncertain`（デフォルト: `uncertain`） |
| `sources` | list[Source] | No | 引用元リスト |
| `source_type` | enum | No | `memory_distillation` / `autonomous_research` / `user_taught`。エントリの主要な出自を示す。`sources[].type` とは独立に、エントリレベルの分類として使用する |
| `user_understanding` | enum | No | `unknown` / `novice` / `familiar` / `proficient` / `expert`（デフォルト: `unknown`） |
| `related` | list[string] | No | 関連 Knowledge の ID |
| `created_at` | datetime | 自動 | 作成日時 |
| `updated_at` | datetime | 自動 | 最終更新日時 |

**Source 構造:**

| 属性 | 型 | 説明 |
|---|---|---|
| `type` | enum | `memory_distillation` / `autonomous_research` / `user_taught`。個々の引用元の出自を示す。エントリレベルの `source_type` とは独立で、sources マージにより異なる type が混在し得る |
| `ref` | string | 参照先（Memory ノートパス、URL、セッション参照等） |
| `summary` | string | 引用元の要約 |

---

#### REQ-FUNC-003: Knowledge / Values ストレージ設計

- **ストーリー**: エージェントとして、Knowledge と Values を既存の Memory ストレージと共存する形で永続化したい。それは既存機能を壊さずに新機能を追加するためだ。
- **受け入れ基準**:
  - Given `memory_init` 実行時, When `knowledge/` と `values/` ディレクトリが存在しない場合, Then 自動作成される
  - Given Knowledge エントリが登録された場合, When `_knowledge.jsonl` を確認, Then 対応するインデックスエントリが存在する
  - Given Knowledge エントリのファイルが手動削除された場合, When `memory_health_check` 実行, Then orphan インデックスエントリが検出される
  - Given Values エントリが登録された場合, When `_values.jsonl` を確認, Then 対応するインデックスエントリが存在する
  - Given Values エントリのファイルが手動削除された場合, When `memory_health_check` 実行, Then orphan インデックスエントリが検出される
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-001, REQ-FUNC-002

**ディレクトリ構造:**

```
memory/
├── _state.md              # 既存: ローリングステート
├── _index.jsonl           # 既存: Memory ノートインデックス
├── _knowledge.jsonl       # 新規: Knowledge インデックス（検索用）
├── _values.jsonl          # 新規: Values インデックス（検索用）
├── knowledge/             # 新規: Knowledge エントリ格納
│   └── {id}.md            #   個別エントリ（Markdown + YAML frontmatter, id は `k-` プレフィックス付き）
├── values/                # 新規: Values エントリ格納
│   ├── {id}.md            #   個別エントリ（Markdown + YAML frontmatter, id は `v-` プレフィックス付き）
│   └── ...
└── YYYY-MM-DD/            # 既存: Memory ノートディレクトリ
    └── ...
```

**設計方針:**
- Knowledge は `knowledge/` 直下にフラット配置（保存パスは immutable な ID のみに依存）
- Values はフラットディレクトリ（エントリ数が Knowledge より少ない想定）
- 各エントリは Markdown + YAML frontmatter で人間可読
- `_knowledge.jsonl` / `_values.jsonl` は検索用インデックス（既存 `_index.jsonl` と同じ設計思想）

**生成タイミング（eager / lazy）:**
- `memory_init` が作成するもの（eager）: `knowledge/` ディレクトリ、`values/` ディレクトリ、AGENTS.md の `BEGIN/END:PROMOTED_VALUES` マーカー（全て冪等）。既存リポジトリへの導入時も自動シード/バックフィルは行わない（空のストアから開始）
- 初回操作時に作成するもの（lazy）: `_knowledge.jsonl`（初回 `memory_knowledge_add` 時）、`_values.jsonl`（初回 `memory_values_add` 時）、`_state.md` の蒸留日時フロントマター（各フィールドは更新条件を初めて満たした時点で遅延追加。`last_*_evaluated_at` は初回 `dry_run=false` 蒸留完了時、`last_*_distilled_at` は初回の永続化発生時に追加される）。lazy 生成ファイルの health check セマンティクスは REQ-NF-004 を参照

**AGENTS.md のパス解決規則:**
`memory_init` および `memory_values_promote` / `memory_values_demote` / `memory_values_delete`（promoted エントリ）が AGENTS.md を操作する際のパス解決は、以下の優先順位に従う:
1. 環境変数 `AGENTS_MD_PATH`（明示指定。設定されていれば常に優先）
2. `memory_dir` の親ディレクトリ（= リポジトリルート想定）の `AGENTS.md`
3. `memory_dir` の親ディレクトリの `CLAUDE.md`（AGENTS.md への symlink 考慮）

いずれも見つからない場合、`memory_init` はマーカー挿入をスキップし警告を返す。昇格/降格/削除操作はエラーを返す。

---

#### REQ-FUNC-004: Knowledge 登録

- **ストーリー**: エージェントとして、新たに獲得した知識を Knowledge エントリとして登録したい。それは知識を永続化し、後続セッションで参照可能にするためだ。
- **受け入れ基準**:
  - Given 有効なパラメータ, When `memory_knowledge_add` 実行, Then `.md` ファイルと `_knowledge.jsonl` エントリが作成される
  - Given `domain` に任意の値を指定, When 実行, Then `knowledge/{id}.md` としてエントリが作成される
  - Given `title` + `domain` + `content` が既存エントリと実質同一の内容で実行, When 実行, Then 重複エラーを返す
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-001, REQ-FUNC-003

**MCP ツール: `memory_knowledge_add`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `title` | string | Yes | 知識のタイトル |
| `content` | string | Yes | 知識の本体 |
| `domain` | string | Yes | ドメイン分類 |
| `tags` | list[string] | No | 検索用タグ |
| `accuracy` | enum | No | `verified` / `likely` / `uncertain`（デフォルト: `uncertain`） |
| `sources` | list[Source] | No | 引用元リスト |
| `source_type` | enum | No | `memory_distillation` / `autonomous_research` / `user_taught` |
| `user_understanding` | enum | No | デフォルト: `unknown` |
| `related` | list[string] | No | 関連 Knowledge ID |

**処理:**
1. UUID を生成し `k-` プレフィックスを付与して `id` とする（作成時のみ。以降不変）
2. 重複チェック（`title` + `domain` + `content` が既存エントリと実質同一であればエラー。ID ではなく内容ベースで判定）
3. `knowledge/{id}.md` にファイル作成
4. `_knowledge.jsonl` にインデックスエントリを追加

**出力:** 作成されたエントリの `id` とパス

---

#### REQ-FUNC-005: Knowledge 検索

- **ストーリー**: エージェントとして、キーワードやドメインで Knowledge を検索したい。それはユーザーへの知識提供や蒸留時の重複チェックに使うためだ。
- **受け入れ基準**:
  - Given Knowledge エントリが5件存在し `domain: "rust"` が2件, When `domain="rust"` で検索, Then 2件のみ返される
  - Given `query="所有権"`, When 検索実行, Then title/content/tags に「所有権」を含むエントリが上位に返される
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-003, REQ-FUNC-017

**MCP ツール: `memory_knowledge_search`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `query` | string | No | 検索クエリ（`query` と `domain` の少なくとも一方を指定） |
| `domain` | string | No | ドメインフィルタ |
| `accuracy` | enum | No | 正確性フィルタ |
| `user_understanding` | enum | No | 理解度フィルタ |
| `top` | int | No | 最大件数（デフォルト: 10） |

**制約:** `query` と `domain` の少なくとも一方が必須。両方省略した場合はバリデーションエラーを返す。`domain` のみ指定時はフィルタ結果を `updated_at` 降順で返す。

**出力:** エントリリスト（`id`, `title`, `domain`, `accuracy`, `user_understanding`, `content` の先頭部分）。`query` 指定時は関連度スコア降順、`domain` のみ指定時は `updated_at` 降順で返す。

---

#### REQ-FUNC-006: Knowledge 更新

- **ストーリー**: エージェントとして、既存の Knowledge の正確性・引用元・理解度等を更新したい。それは知識を最新に保ち、ユーザーの学習進捗を反映するためだ。
- **受け入れ基準**:
  - Given 既存エントリ, When `accuracy` のみ更新, Then 他の属性は変更されず `updated_at` のみ更新される
  - Given `sources` を追加, When 更新実行, Then 既存の sources に追加される（置換ではない）
  - Given 存在しない `id`, When 更新試行, Then エラーを返す
  - Given 既存エントリ B と同一の `title` + `domain` + `content` になるよう `content` を更新, When 実行, Then 重複エラーを返す
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-001, REQ-FUNC-004

**MCP ツール: `memory_knowledge_update`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | Yes | 更新対象の Knowledge ID |
| `content` | string | No | 更新後の本体 |
| `accuracy` | enum | No | 更新後の正確性 |
| `sources` | list[Source] | No | 追加する引用元（既存にマージ） |
| `user_understanding` | enum | No | 更新後の理解度 |
| `related` | list[string] | No | 追加する関連 Knowledge ID（既存にマージ） |
| `tags` | list[string] | No | 置換後のタグリスト |

**処理:** `id` 以外のパラメータが一つも指定されていない場合はバリデーションエラーを返す。指定された属性のみ更新。`content` が更新された場合、更新後の `title` + `domain` + `content` が自エントリ以外の既存エントリと実質同一でないことを検証する。同一の場合はエラーを返し更新を拒否する。`updated_at` を自動更新。`.md` ファイルと `_knowledge.jsonl` を同期更新。

**出力:** 更新されたエントリの `id`。

---

### 3.4 V: Values 管理

#### REQ-FUNC-002: Values データモデル

- **ストーリー**: エージェントとして、Values エントリに確信度・根拠事例・最終更新日時を紐づけたい。それは確信度に基づいて判断の参考度合いを調整するためだ。
- **受け入れ基準**:
  - Given `confidence` が 0.0〜1.0 の範囲外, When バリデーション実行, Then エラーを返す
  - Given 新しい evidence が追加された場合, When 更新実行, Then `evidence_count` が自動インクリメントされ `updated_at` が更新される
  - Given `promoted: true` のエントリ, When 検索結果に含まれる場合, Then `promoted` フラグが結果に表示される
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-003, REQ-FUNC-007

**Values エントリ属性:**

| 属性 | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | 自動 | 一意識別子（作成時に UUID を生成し `v-` プレフィックスを付与。以降は不変。内容の変化に依存しない安定した識別子） |
| `description` | string | Yes | 価値観の記述 |
| `category` | string | Yes | 分類（`coding-style` / `communication` / `workflow` / `design` / `review` 等）。kebab-case に正規化される |
| `confidence` | float | No | 確信度 0.0〜1.0（デフォルト: 0.3） |
| `evidence` | list[Evidence] | No | 根拠事例（最大10件保持。リスト先頭が最新。登録時は提供リストの先頭10件を保持し末尾を切り捨て。更新時は先頭に追加し末尾を除外） |
| `evidence_count` | int | 自動 | 根拠事例の総数（evidence リスト外のものもカウント） |
| `promoted` | bool | 自動 | AGENTS.md に昇格済みか（デフォルト: `false`） |
| `promoted_at` | datetime | 自動 | 昇格日時（`promoted=true` の場合） |
| `promoted_confidence` | float | 自動 | 昇格時の確信度（降格判定に使用。`promoted=true` の場合のみ） |
| `demotion_reason` | string | 自動 | 降格理由（降格実行時に記録。降格履歴がない場合は null） |
| `demoted_at` | datetime | 自動 | 降格日時（降格実行時に記録。降格履歴がない場合は null） |
| `created_at` | datetime | 自動 | 作成日時 |
| `updated_at` | datetime | 自動 | 最終更新日時 |

**Evidence 構造:**

| 属性 | 型 | 説明 |
|---|---|---|
| `ref` | string | 根拠の参照先。Memory ノートパス（例: `memory/2026-03-15/1430_session.md`）または `_state.md` セクション参照（例: `_state.md#主要な判断`） |
| `summary` | string | 事例の要約 |
| `date` | string | 事例の日付（`YYYY-MM-DD` 形式） |

---

#### REQ-FUNC-007: Values 登録

- **ストーリー**: エージェントとして、検出したユーザーの判断傾向を Values エントリとして登録したい。それはユーザーの代理人としての行動精度を向上させるためだ。
- **受け入れ基準**:
  - Given 有効なパラメータ, When `memory_values_add` 実行, Then `.md` ファイルとインデックスエントリが作成される
  - Given `description` + `category` が既存エントリと実質同一の場合, When 登録試行, Then 重複エラーを返す（厳密重複）
  - Given 意味的に類似する既存 Values が存在（`id` は異なる）, When 登録試行, Then 類似エントリの情報が警告として返される（登録自体は成功する）
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-002, REQ-FUNC-003

**MCP ツール: `memory_values_add`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `description` | string | Yes | 価値観の記述 |
| `category` | string | Yes | 分類 |
| `confidence` | float | No | 初期確信度（デフォルト: 0.3） |
| `evidence` | list[Evidence] | No | 初期根拠事例 |

**処理:**
1. UUID を生成し `v-` プレフィックスを付与して `id` とする（作成時のみ。以降不変）
2. 厳密重複チェック: `description` + `category` が既存エントリと実質同一の場合はエラーを返す（ID ではなく内容ベースで判定。Knowledge の REQ-FUNC-004 と同じ方針）
3. 類似判定: 既存 Values と意味的に重複する場合は警告を返す（エラーではなく、マージ提案。厳密重複とは別のチェック。アルゴリズムは下記「類似判定の仕様」参照）
4. `evidence` 初期化: `evidence` パラメータが指定された場合、提供リストの先頭10件を保持し末尾を切り捨てる（10件以下ならそのまま保持。リスト先頭が最新として扱われる）。`evidence_count` は指定された `evidence` の件数（切り捨て前の総数）で初期化する（未指定時は 0）
5. 昇格候補判定: 初期 `confidence` と `evidence_count` が昇格条件（REQ-FUNC-015: `confidence >= 0.8` AND `evidence_count >= 5`）を満たす場合、レスポンスに昇格候補である旨を通知する（REQ-FUNC-009 の更新時通知と同じ形式）
6. `values/{id}.md` にファイル作成（`id` は `v-` プレフィックス付きで自動生成済み）
7. `_values.jsonl` にインデックスエントリを追加

**類似判定の仕様:**
- **アルゴリズム**: 候補の `description` を検索クエリとして `_values.jsonl` に対し BM25+ スコアリングを実行し、正規化スコアが閾値以上の既存エントリを類似候補とする
- **正規化方法**: 各エントリの BM25+ 生スコアをクエリ結果セット内の最大スコアで除算する（max-normalization）。結果は 0.0–1.0 の相対値となる。最大スコアが 0 の場合（ヒットなし）は類似候補なしとする
- **閾値**: max-normalized スコア 0.7 以上（暫定値。運用データの蓄積後に調整する）
- **対象**: 厳密重複（内容ベースで同一と判定されたもの）を除外した既存エントリ全件

**出力:** 作成されたエントリの `id`。昇格候補条件（REQ-FUNC-015）を満たす場合は `promotion_candidate: true` を返す（満たさない場合はフィールド自体を省略）。類似既存エントリがある場合はその情報を `warnings` に含める（例: `"Similar value exists: v-xxxxxxxx — {description}"`）。

---

#### REQ-FUNC-008: Values 検索

- **ストーリー**: エージェントとして、判断が必要な場面で関連する Values を検索したい。それはユーザーの選好に沿った判断を行うためだ。
- **受け入れ基準**:
  - Given `min_confidence=0.5` を指定, When 検索実行, Then `confidence < 0.5` のエントリは返されない
  - Given `query="コミットメッセージ"`, When 検索実行, Then コミット・git 関連の Values が上位に返される
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-002, REQ-FUNC-018

**MCP ツール: `memory_values_search`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `query` | string | No | 検索クエリ（判断のコンテキスト。`query` と `category` の少なくとも一方を指定） |
| `category` | string | No | カテゴリフィルタ |
| `min_confidence` | float | No | 確信度の下限（デフォルト: 0.0） |
| `top` | int | No | 最大件数（デフォルト: 5） |

**制約:** `query` と `category` の少なくとも一方が必須。両方省略した場合はバリデーションエラーを返す。`category` のみ指定時はフィルタ結果を `confidence` 降順で返す。

**出力:** エントリリスト（`id`, `description`, `category`, `confidence`, `evidence_count`, `promoted`）。`query` 指定時は関連度スコア降順、`category` のみ指定時は `confidence` 降順（同値の場合は `updated_at` 降順）で返す。

---

#### REQ-FUNC-009: Values 更新

- **ストーリー**: エージェントとして、既存 Values の確信度や根拠事例を更新したい。それは新しい事例に基づいて確信度を漸進的に調整するためだ。
- **受け入れ基準**:
  - Given evidence が10件ある状態で `add_evidence`, When 実行, Then 最古の1件が evidence リストから除外され `evidence_count` が +1 される
  - Given `confidence` または `add_evidence` を更新, When 更新後に昇格条件（REQ-FUNC-015）を満たす場合, Then レスポンスに昇格候補である旨を通知する（自動昇格はしない）
  - Given 存在しない `id`, When 更新試行, Then エラーを返す
  - Given 既存エントリ B と同一の `description` + `category` になるよう `description` を更新, When 実行, Then 重複エラーを返す
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-002, REQ-FUNC-015

**MCP ツール: `memory_values_update`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | Yes | 更新対象の Values ID |
| `confidence` | float | No | 更新後の確信度 |
| `add_evidence` | Evidence | No | 追加する根拠事例 |
| `description` | string | No | 更新後の記述 |

**処理:**
1. `id` 以外のパラメータが一つも指定されていない場合はバリデーションエラーを返す
2. 指定属性を更新
3. `description` が更新された場合、更新後の `description` + `category` が自エントリ以外の既存エントリと実質同一でないことを検証する。同一の場合はエラーを返し更新を拒否する
4. `add_evidence` 指定時: evidence リストの先頭に追加し、最新10件を保持。超過分は `evidence_count` のみインクリメント
5. `updated_at` を自動更新
6. `.md` ファイルと `_values.jsonl` を同期更新

**出力:** 更新されたエントリの `id`。更新後に昇格候補条件（REQ-FUNC-015）を満たす場合は `promotion_candidate: true` を返す（満たさない場合はフィールド自体を省略）。

---

### 3.5 D: 蒸留エンジン

#### REQ-FUNC-010: Memory → Knowledge 蒸留

- **ストーリー**: エージェントとして、蓄積された Memory ノートから一般化可能な知識を自動抽出したい。それは暗黙知を形式知として体系化するためだ。
- **受け入れ基準**:
  - Given 10件の Memory ノート, When `dry_run=true` で実行, Then Knowledge 候補リストが返され、`_knowledge.jsonl` は変更されない
  - Given 抽出結果に既存 Knowledge と重複する内容がある, When `dry_run=false`, Then 重複エントリはスキップされ、レスポンスに報告される
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-004, REQ-FUNC-012

**MCP ツール: `memory_distill_knowledge`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `date_from` | string | No | 対象期間の開始日（`YYYY-MM-DD` 形式、inclusive。デフォルト: 全期間の先頭） |
| `date_to` | string | No | 対象期間の終了日（`YYYY-MM-DD` 形式、inclusive。デフォルト: 当日） |
| `domain` | string | No | 特定ドメインに絞る |
| `dry_run` | bool | No | true の場合、抽出結果を返すだけで登録しない（デフォルト: `true`） |

**日付パラメータの仕様:**
- `date_from` / `date_to` はいずれも `YYYY-MM-DD` 形式の文字列。不正な形式の場合はバリデーションエラーを返す
- 境界: 両端 inclusive（`date_from` の日付に作成されたノートも `date_to` の日付に作成されたノートも対象に含む）
- `date_from > date_to`（無効な範囲）の場合はバリデーションエラーを返す
- 片方のみ指定も可。`date_from` のみ → その日以降の全ノート、`date_to` のみ → その日以前の全ノート

**処理:**
1. 対象ノートの Decisions / Pitfalls & Remaining Issues / Results / Work Log セクション（日本語エイリアス: 判断 / 注意点・残課題 / 成果 / 作業ログ）をスキャン。セクション識別はテンプレート言語（日本語・英語）に依存しない正規化済みセクション名で行う
2. 繰り返し現れるパターン・事実・ルールを抽出（`DistillationExtractorPort` 経由で LLM に委譲）。`domain` が指定されている場合、当該ドメインに焦点を絞って抽出する（collect 段ではなく extract 段で適用。Memory ノートにドメインのメタデータが存在しないため）
3. 既存 Knowledge との重複チェック（REQ-FUNC-012: 統合ロジック）
4. `dry_run=false` の場合、新規エントリを `memory_knowledge_add` で登録

**出力:** 抽出された Knowledge 候補のリスト（新規 / 既存マージ / 関連リンク / 重複スキップ / 機密スキップ を区別）と集計（`new_count` / `merged_count` / `linked_count` / `skipped_count` / `secret_skipped_count`）

**補足:** 蒸留の「抽出」は `DistillationExtractorPort` 経由で LLM に委譲する。ツールは collect（ノート選定）→ extract（抽出委譲）→ integrate（統合・永続化）の全段階をオーケストレーションする。

---

#### REQ-FUNC-011: Memory → Values 蒸留

- **ストーリー**: エージェントとして、Memory ノートの判断履歴からユーザーの判断傾向を自動抽出したい。それはユーザーの代理人としての行動精度を継続的に改善するためだ。
- **受け入れ基準**:
  - Given 判断セクションに「テスト追加を求めた」事例が3回以上, When 蒸留実行, Then「バグ修正時にリグレッションテストを求める傾向」のような Values 候補が抽出される
  - Given 既存 Values と同じ傾向が追加抽出された場合, When `dry_run=false`, Then 既存エントリの `confidence` が上昇し `evidence` に新事例が追加される
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-007, REQ-FUNC-013

**MCP ツール: `memory_distill_values`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `date_from` | string | No | 対象期間の開始日（`YYYY-MM-DD` 形式、inclusive。デフォルト: 全期間の先頭） |
| `date_to` | string | No | 対象期間の終了日（`YYYY-MM-DD` 形式、inclusive。デフォルト: 当日） |
| `category` | string | No | 特定カテゴリに絞る |
| `dry_run` | bool | No | デフォルト: `true` |

**日付パラメータの仕様:** `memory_distill_knowledge` と共通。REQ-FUNC-010 の「日付パラメータの仕様」を参照。`_state.md` の「主要な判断」セクションは日付フィルタ（`date_from` / `date_to`）の対象外であり、常に全文をスナップショットに含める。理由: `_state.md` はローリングステートであり、個別の判断エントリに日付メタデータ（`date` フロントマター等）を持たないため、`date_from` / `date_to` によるフィルタリングが適用できない。

**`_state.md` 由来 Evidence の日付導出:** `_state.md` の「主要な判断」セクションから抽出された Values の Evidence.date は、以下の優先順位で決定する:
1. 判断エントリのテキスト内にインライン日付参照（例: `2026-04-01 に決定`）が含まれる場合: その日付を `YYYY-MM-DD` に切り詰めて使用する。LLM 抽出（`DistillationExtractorPort`）が日付を認識できた場合に限る
2. 上記が利用不可能な場合: 蒸留実行日（`memory_distill_values` の呼び出し日）を使用する

日付フィルタでは `_state.md` を除外しつつ Evidence.date では導出する理由: 日付フィルタはノート選定（collect 段）で適用され、個別エントリに日付メタデータがない `_state.md` には適用できない。一方、Evidence.date は抽出後（extract 段）の個別 Evidence に付与するメタデータであり、テキスト内容から推定可能な場合に活用する。

**処理:**
1. 対象ノートの Decisions セクション（日本語エイリアス: 判断）と、ステートの「主要な判断」セクションを重点的にスキャン。セクション識別はテンプレート言語に依存しない正規化済みセクション名で行う
2. 判断の傾向パターンを抽出（`DistillationExtractorPort` 経由で LLM に委譲）。`category` が指定されている場合、当該カテゴリに焦点を絞って抽出する（collect 段ではなく extract 段で適用。Memory ノートにカテゴリのメタデータが存在しないため）
3. 既存 Values との重複チェック（REQ-FUNC-013: 統合ロジック）
4. 重複する場合は確信度を更新し evidence を追加
5. `dry_run=false` の場合、新規は `memory_values_add`、既存更新は `memory_values_update` で反映

**出力:** 抽出された Values 候補のリスト（新規 / 強化（確信度更新） / 矛盾 / スキップ / 機密スキップ を区別）と集計（`new_count` / `reinforced_count` / `contradicted_count` / `skipped_count` / `secret_skipped_count`）

---

#### REQ-FUNC-012: Knowledge 統合ロジック

- **説明**: REQ-FUNC-010 の内部処理。新規抽出 Knowledge と既存 Knowledge の重複を検出・マージする。
- **受け入れ基準**:
  - Given 「Rust の所有権」に関する既存 Knowledge と「Rust のライフタイム」に関する新規 Knowledge, When 統合判定, Then 別エントリとして登録され `related` で相互リンクされる
  - Given 既存と矛盾する内容が抽出された場合, When 統合実行, Then `accuracy` が `uncertain` に設定され、矛盾の内容がレスポンスに報告される
- **優先度**: Must
- **出典**: エージェント推測（蒸留パイプラインに必須の内部処理）
- **関連要件**: REQ-FUNC-010

**処理:**
1. 新規候補の `title` + `content` と既存エントリを照合
2. 同一トピックと判定された場合（`MERGE_EXISTING`）: 既存エントリの `content` を補完・拡張（矛盾する場合は `accuracy: uncertain` にフラグ）、`sources` に新しい引用元を追加、`updated_at` を更新
3. 類似だが別トピックと判定された場合（`LINK_RELATED`）: 候補を新規エントリとして登録した後、新規エントリと既存エントリの `related` を相互に追加する（双方向リンク）

---

#### REQ-FUNC-013: Values 統合ロジック

- **説明**: REQ-FUNC-011 の内部処理。新規抽出 Values と既存 Values の重複を検出・確信度を更新する。
- **受け入れ基準**:
  - Given `confidence: 0.6` の既存 Values に対して同傾向の evidence が追加された, When 統合実行, Then `confidence` が 0.6 より上昇する
  - Given 既存 Values と矛盾する判断が検出された, When 統合実行, Then 既存 Values の `confidence` が低下し、矛盾がレスポンスに報告される
- **優先度**: Must
- **出典**: エージェント推測（蒸留パイプラインに必須の内部処理）
- **関連要件**: REQ-FUNC-011

**処理:**
1. 新規候補の `description` と既存エントリを照合
2. 同一傾向と判定された場合: `confidence` を更新（同じ傾向の evidence が増えるほど上昇）、`evidence` に新事例を追加（最新10件保持ルール適用）
3. 矛盾する傾向が検出された場合: 既存エントリの `confidence` を低下させ、矛盾をレスポンスに報告

**確信度更新の方針:**
- 新規事例が既存 Values を支持 → `confidence` を上昇
- 新規事例が既存 Values と矛盾 → `confidence` を低下
- 具体的な更新幅はエージェントが判断（固定の数式ではなく、コンテキストに応じた LLM 判定）

---

### 3.6 R: Knowledge 自律収集

#### REQ-FUNC-014: リサーチ結果の Knowledge 登録

- **ストーリー**: エージェントとして、調査で獲得した知識を Knowledge として登録したい。それは一過性の調査結果を再利用可能な知識資産として蓄積するためだ。
- **受け入れ基準**:
  - Given エージェントが調査で事実を確認した, When `memory_knowledge_add` を `source_type: autonomous_research` で呼び出す, Then Knowledge エントリが作成される
  - Given 単一ソースのみで検証した場合, When 登録, Then `accuracy: likely` で登録される（`verified` には複数ソースの確認が必要）
- **優先度**: Must
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-004, REQ-FUNC-019

**実装方針:** 追加ツールは不要。既存の `memory_knowledge_add` を使用し、ワークフローを AGENTS.md に定義する。

**ワークフロー:**
1. エージェントが調査を実施
2. ファクトチェック（複数ソースでの確認）を実施
3. `memory_knowledge_add` で登録（`source_type` と `accuracy` をファクトチェック結果に応じて設定）

---

### 3.7 P: Values 昇格

#### REQ-FUNC-015: 昇格判定

- **説明**: 高確信度の Values を AGENTS.md 昇格候補として検出する。`memory_values_add` および `memory_values_update` のレスポンスに組み込む。
- **受け入れ基準**:
  - Given `confidence >= 0.8`, `evidence_count >= 5`, `promoted == false` の Values, When `memory_values_add` または `memory_values_update` のレスポンス, Then 昇格候補である旨が通知される
  - Given `confidence >= 0.8` だが `evidence_count < 5` の Values, When `memory_values_add` または `memory_values_update` のレスポンス, Then 昇格候補として通知されない
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-007, REQ-FUNC-009, REQ-FUNC-016

**昇格条件（すべて満たすこと）:**
- `confidence >= 0.8`
- `evidence_count >= 5`
- `promoted == false`

---

#### REQ-FUNC-016: AGENTS.md への Values 反映

- **ストーリー**: エージェントとして、高確信度の Values を AGENTS.md に反映したい。それはセッション開始時に自動参照される常時有効な指針にするためだ。
- **受け入れ基準**:
  - Given `confirm: false`, When 実行, Then エラーを返す（ユーザー確認なしの昇格を防止）
  - Given 昇格実行後, When AGENTS.md を確認, Then 該当 Values が「内面化された価値観」セクションに存在する
  - Given 既に `promoted: true` のエントリ, When 再度昇格, Then エラーを返す
  - Given 昇格条件（REQ-FUNC-015）を満たさない Values（例: `confidence < 0.8`）, When `memory_values_promote` 実行, Then エラーを返す（昇格条件未充足）
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-015, REQ-FUNC-022

**MCP ツール: `memory_values_promote`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | Yes | 昇格対象の Values ID |
| `confirm` | bool | Yes | ユーザー確認済みフラグ（`true` 必須） |

**処理:**
1. `confirm: true` であることを確認（ガードレール）
2. 昇格条件チェック: 対象エントリが REQ-FUNC-015 の昇格条件（`confidence >= 0.8` AND `evidence_count >= 5` AND `promoted == false`）を満たすことを検証。未充足の場合はエラーを返す
3. AGENTS.md の「内面化された価値観」セクションに記述を追記
4. Values エントリの `promoted: true`, `promoted_at`, `promoted_confidence`（昇格時点の `confidence` 値）を更新

**出力:** AGENTS.md の更新差分

---

### 3.8 S: 検索・参照統合

#### REQ-FUNC-017: Knowledge 専用検索（REQ-FUNC-005 の参照 alias）

- **説明**: REQ-FUNC-005 と同一の受け入れ基準・MCP ツール仕様を適用する。既存の `memory_search`（Memory ノート検索）とは独立した Knowledge 専用検索ツールとして提供する。本要件は REQ-FUNC-005 の参照 alias であり、追加の差分受け入れ基準は持たない。設計上の対応はすべて REQ-FUNC-005 に帰属する。
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-005

---

#### REQ-FUNC-018: Values 判断時参照（REQ-FUNC-008 の参照 alias）

- **説明**: REQ-FUNC-008 と同一の受け入れ基準・MCP ツール仕様を適用する。エージェントが判断を求められた場面で、コンテキストに関連する Values を検索する。本要件は REQ-FUNC-008 の参照 alias であり、追加の差分受け入れ基準は持たない。設計上の対応はすべて REQ-FUNC-008 に帰属する。
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-008, REQ-FUNC-020

**AGENTS.md への記載:** 「設計判断・スタイル判断が必要な場面では `memory_values_search` を参照すること」をセッション手順に追加する。

---

### 3.9 A: AGENTS.md / スキル改修

#### REQ-FUNC-019: 記憶管理セクション拡張

- **ストーリー**: エージェントとして、AGENTS.md の記憶管理セクションに Memory / Knowledge / Values の3層構造とライフサイクルを記載したい。それは全エージェントが統一的に Knowledge/Values を活用するためだ。
- **受け入れ基準**:
  - Given AGENTS.md の記憶管理セクション, When 確認, Then Memory / Knowledge / Values の3層分類と各ツール一覧が記載されている
  - Given 新規セッションを開始するエージェント, When AGENTS.md を読み込む, Then Knowledge/Values の参照・更新手順が明確に理解できる
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-020, REQ-FUNC-021

---

#### REQ-FUNC-020: セッション開始手順更新

- **説明**: AGENTS.md の「セッション開始（必須）」の「想起（recalling）」ステップに Values 参照を追加する。
- **受け入れ基準**:
  - Given セッション開始時, When エージェントが想起ステップを実行, Then 現在のタスクに関連する Values が参照される
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-008, REQ-FUNC-019

**追加内容:** 「想起（recalling）」に `memory_values_search` でタスクコンテキストに関連する Values を取得する手順を追加。

---

#### REQ-FUNC-021: セッション終了手順更新

- **説明**: AGENTS.md の「応答終了時」に Knowledge/Values の更新手順を追加する。
- **受け入れ基準**:
  - Given セッション終了時, When エージェントが振り返りステップを実行, Then Knowledge/Values の更新要否が判定される
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-010, REQ-FUNC-011, REQ-FUNC-019, REQ-FUNC-026

**追加内容:**
- 「振り返り（reflecting）」: セッション中の判断が既存 Values を支持/矛盾するか評価。新たな Knowledge が得られた場合の登録判断
- 「保存（storing）」: Knowledge/Values の更新手順（蒸留トリガー条件（REQ-FUNC-026）の評価を含む）

---

#### REQ-FUNC-022: 昇格 Values セクション

- **ストーリー**: エージェントとして、AGENTS.md に動的に管理される「内面化された価値観」セクションを設けたい。それは昇格された Values を全エージェントが常時参照できるようにするためだ。
- **受け入れ基準**:
  - Given AGENTS.md を読み込む全エージェント, When セッション開始, Then 昇格された Values が自動的に判断指針として参照される
  - Given 昇格 Values セクション, When `memory_values_promote` で新規追加, Then セクション末尾に追記される
- **優先度**: Must
- **出典**: ユーザー確認済み
- **関連要件**: REQ-FUNC-016

**セクション形式:**

```markdown
## 内面化された価値観

<!-- BEGIN:PROMOTED_VALUES (agentic-memory managed — do not edit manually) -->

- バグ修正時は最小侵入修正を優先し、周辺コードのリファクタリングを同時に行わない
  （confidence: 0.92, evidence: 8件, id: v-m3n4o5）
- コミットは論理的な変更単位で分割し、1コミット1関心事を徹底する
  （confidence: 0.88, evidence: 6件, id: v-p6q7r8）

<!-- END:PROMOTED_VALUES -->
```

**マーカー仕様:** `<!-- BEGIN:PROMOTED_VALUES ... -->` と `<!-- END:PROMOTED_VALUES -->` の HTML コメントマーカーで囲まれた範囲のみを自動管理対象とする。マーカーは `memory_init` が AGENTS.md に idempotent に自動挿入する（既存マーカーがあれば何もしない）。昇格/降格操作時にマーカーが欠落している場合は操作を拒否し、`memory_init` の再実行を案内する。

---

### 3.10 Should 要件

#### REQ-FUNC-023: Knowledge 削除

- **ストーリー**: エージェントとして、不要になった Knowledge エントリを削除したい。それは知識ベースの鮮度と正確性を維持するためだ。
- **受け入れ基準**:
  - Given 削除対象の Knowledge, When 実行, Then `knowledge/{id}.md` ファイルと `_knowledge.jsonl` の対応エントリの両方が削除される
  - Given 他エントリが `related` で参照している Knowledge を削除, When 実行, Then 参照元の `related` からも該当 ID が除去される
  - Given 削除実行後, When `memory_knowledge_search` で検索, Then 該当エントリはヒットしない
- **優先度**: Should
- **出典**: エージェント推測（CRUD の D として必要）
- **関連要件**: REQ-FUNC-004

**MCP ツール: `memory_knowledge_delete`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | Yes | 削除対象の Knowledge ID |
| `reason` | string | No | 削除理由 |

**出力:** 削除結果（`deleted_id`, `title` の要約）。`reason` が指定された場合はレスポンスにエコーバックする。`reason` はレスポンス以外には永続化しない（ファイル・インデックスともに削除済み）。削除理由の保存が必要な場合はエージェント側でセッションノートや `memory_state_add` に記録する。

---

#### REQ-FUNC-024: Values 削除

- **ストーリー**: エージェントとして、不要になった Values エントリを削除したい。それは誤った価値観がエージェントの判断に影響し続けることを防ぐためだ。
- **受け入れ基準**:
  - Given 削除対象の Values, When 実行, Then `values/{id}.md` ファイルと `_values.jsonl` の対応エントリの両方が削除される
  - Given `promoted: true` の Values を削除, When 実行, Then AGENTS.md の「内面化された価値観」セクションから該当行も削除される
  - Given `promoted: true` の Values を削除, When AGENTS.md の `BEGIN/END:PROMOTED_VALUES` マーカーが欠落, Then エラーを返し削除を拒否する。`memory_init` の再実行を案内する
  - Given `promoted: true` の Values を削除, When `confirm: false` または未指定, Then エラーを返し、対象エントリの概要と AGENTS.md から除去される行のプレビューを含める
  - Given 削除実行後, When `memory_values_search` で検索, Then 該当エントリはヒットしない
- **優先度**: Should
- **出典**: エージェント推測（CRUD の D として必要）
- **関連要件**: REQ-FUNC-007, REQ-FUNC-016

**MCP ツール: `memory_values_delete`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | Yes | 削除対象の Values ID |
| `reason` | string | No | 削除理由 |
| `confirm` | bool | No | 削除確認フラグ（デフォルト: `false`）。`promoted: true` のエントリでは `confirm: true` が必須 |

**処理:**
1. `promoted: true` の場合、`confirm == true` を検証する。`false` または未指定の場合は削除プレビュー（エントリ概要 + AGENTS.md 該当行）を返しエラーとする
2. `promoted: true` の場合、AGENTS.md の `BEGIN/END:PROMOTED_VALUES` マーカー存在を検証する。欠落時はエラーを返し、`memory_init` の再実行を案内する
3. AGENTS.md から該当行を削除する
4. `values/{id}.md` と `_values.jsonl` を削除する

**出力:** 削除結果（`deleted_id`, `description` の要約, `was_promoted`）。`reason` が指定された場合はレスポンスにエコーバックする。`reason` はレスポンス以外には永続化しない（ファイル・インデックスともに削除済み）。削除理由の保存が必要な場合はエージェント側でセッションノートや `memory_state_add` に記録する。

---

#### REQ-FUNC-025: Values 一括参照

- **ストーリー**: エージェントとして、高確信度の Values を一括取得したい。それはセッション開始時にユーザーの全体的な判断傾向を把握するためだ。
- **受け入れ基準**:
  - Given 30件の Values エントリ, When `min_confidence=0.7` で実行, Then `confidence >= 0.7` のエントリのみ `confidence` 降順で返される
  - Given `promoted_only=true`, When 実行, Then `promoted: true` のエントリのみ返される
- **優先度**: Should
- **出典**: エージェント推測
- **関連要件**: REQ-FUNC-008

**MCP ツール: `memory_values_list`**

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `min_confidence` | float | No | 確信度の下限（デフォルト: 0.5） |
| `category` | string | No | カテゴリフィルタ |
| `promoted_only` | bool | No | 昇格済みのみ（デフォルト: `false`） |
| `top` | int | No | 最大件数（デフォルト: 20） |

**ソート順:** `confidence` 降順。同値の場合は `updated_at` 降順。`promoted_only=true` の場合も同一のソート順を適用する。

**出力:** MCP ツール共通規約（§3.2）に従い `{ok: true, entries: [...]}` 形式で返す。`entries` はエントリリスト（各要素: `id`, `description`, `category`, `confidence`, `evidence_count`, `promoted`）。フィールドセットは `promoted_only` の値に関わらず同一。結果が 0 件の場合は `{ok: true, entries: []}` を返す。

---

#### REQ-FUNC-026: 蒸留トリガー判定

- **説明**: 蒸留を実行すべきタイミングを判定するロジック。AGENTS.md のセッション終了手順に組み込む。
- **受け入れ基準**:
  - Given 最終評価タイムスタンプから 168 時間（7日相当）経過, When セッション終了時の振り返り, Then 蒸留の実行がエージェントに推奨される
  - Given 最終評価タイムスタンプから 48 時間（2日相当）経過かつ新規ノート3件, When セッション終了時, Then 蒸留は推奨されない
- **優先度**: Should
- **出典**: エージェント推測
- **関連要件**: REQ-FUNC-010, REQ-FUNC-011, REQ-FUNC-021

**判定条件（いずれかを満たす場合に蒸留を推奨）:**
1. 最終評価日時以降に作成されたノートが 10 件以上
2. 最終評価日時から 168 時間（7日相当）以上経過（タイムスタンプ精度で比較。日付境界ではなく経過時間で判定）

**Bootstrap rule:** 最終評価日時が未設定（初回蒸留前）の場合は、ノートが 1 件以上あれば条件を満たすものとする。

**`_state.md` の除外:** `_state.md` の「主要な判断」セクションの更新はトリガー条件に含めない。`_state.md` はセッションごとに頻繁に更新されるローリングステートであり、変更検出をトリガーにすると蒸留が過度に頻発する。セッション中の判断は Memory ノートの Decisions セクションにも記録されるため、ノート数カウントが間接的にカバーする。加えて、168 時間の経過時間条件がフォールバックとして機能する。

**2 つの起動経路:**
- *公開 API ベースの推奨判定*（セッション終了時の振り返りおよび retrospective スキルで評価される）: 上記条件（10 ノート以上 OR 168 時間以上経過）を評価し、満たす場合に蒸留を推奨する
- *ユーザーの直接呼び出し* (`memory_distill_knowledge` / `memory_distill_values`): トリガー判定をバイパスし、即座に蒸留パイプラインを実行する

**実装方針:** `_state.md` の YAML フロントマターに蒸留種別ごとに以下の2つの日時を記録する:
- `last_knowledge_distilled_at` / `last_values_distilled_at`: 最終永続化日時。`dry_run=false` かつ 1 件以上の永続化（create / merge / link / reinforce）が発生した蒸留完了時にのみ更新される。`CONTRADICT_EXISTING` は既存エントリの `confidence` を低下させ `memory_values_update` で永続化するが、`last_*_distilled_at` の目的は新たなエントリの追加・統合（create / merge / link / reinforce）の発生記録であり、既存エントリの品質指標調整はこれに該当しないため除外する
- `last_knowledge_evaluated_at` / `last_values_evaluated_at`: 最終評価日時。`dry_run=false` の蒸留が完了した時点で（永続化 0 件であっても）更新される

Knowledge と Values の蒸留は独立にトリガーされるため、日時を個別に管理する。**トリガー条件（10 ノート以上 OR 168 時間以上経過）は「最終評価日時」を基準にタイムスタンプ精度で判定する。** これにより、永続化 0 件（no-op）の蒸留が完了した場合でもタイムスタンプが進み、同じノート集合に対して蒸留推奨が繰り返し出続けることを防止する。

**判定データの公開 API:** エージェント/スキルがトリガー条件を評価するために、以下の既存ツールにフィールドを追加する:
- `memory_state_show`: `frontmatter` フィールドを追加。`_state.md` の YAML フロントマター（`last_knowledge_distilled_at` / `last_values_distilled_at` / `last_knowledge_evaluated_at` / `last_values_evaluated_at`）を返却する
- `memory_stats`: `notes_since_last_knowledge_evaluation` / `notes_since_last_values_evaluation` フィールドを追加。各蒸留種別の最終評価日時以降に作成されたノート数を返却する

**初回実行前（Bootstrap）のレスポンス契約:**
- `memory_state_show.frontmatter`: 蒸留が一度も実行されていない場合、`last_knowledge_distilled_at` / `last_values_distilled_at` / `last_knowledge_evaluated_at` / `last_values_evaluated_at` は `null` を返す（フィールド自体は常に存在し、省略しない）
- `memory_stats.notes_since_last_knowledge_evaluation` / `notes_since_last_values_evaluation`: 対応する `last_*_evaluated_at` が `null` の場合、全ノート数を返す（「最終評価以降」= 全期間として算出）。これにより、Bootstrap rule（最終評価日時が未設定の場合、ノートが 1 件以上あれば条件を満たす）が公開 API のレスポンスから自然に導出される

---

#### REQ-FUNC-027: ユーザー教示の Knowledge 化

- **ストーリー**: エージェントとして、ユーザーが会話中に教えてくれた知識をファクトチェックし Knowledge 化したい。それはユーザーの知識を検証済みの形式で蓄積するためだ。
- **受け入れ基準**:
  - Given ユーザーが「ハミルトン方程式は正準方程式とも呼ばれ…」と教えた, When エージェントが Knowledge 化, Then `source_type: user_taught` で登録される
  - Given ファクトチェックで矛盾が見つかった場合, When 登録, Then `accuracy: uncertain` で登録され、矛盾の内容が `content` に注記される
- **優先度**: Should
- **出典**: ユーザー明示
- **関連要件**: REQ-FUNC-004, REQ-FUNC-014

**ワークフロー:**
1. エージェントがユーザーの発言から「教示」を検出
2. Web 検索等でファクトチェックを実施
3. `accuracy` をファクトチェック結果に応じて設定（複数ソース確認 → `verified` / 単一 → `likely` / 未確認 → `uncertain`）
4. `memory_knowledge_add` で登録（`source_type: user_taught`）

**ファクトチェック結果の永続化:** エントリレベルの `source_type` は `user_taught`（知識の出自を示す）を維持する。`sources` リストには以下を含める:
- ユーザー教示の Source: `type: user_taught`, `ref`: セッション参照, `summary`: ユーザーの発言要約
- ファクトチェック結果の Source（検証を実施した場合）: `type: autonomous_research`, `ref`: 確認に使用した URL やドキュメント参照, `summary`: 検証結果の要約

これにより、エントリレベルの `source_type`（出自分類）と個別 `sources[].type`（各引用元の出自）が独立に管理され、ファクトチェックの根拠が追跡可能になる。

---

#### REQ-FUNC-028: 昇格 Values の同期

- **説明**: AGENTS.md の「内面化された価値観」セクションと Values エントリの整合性を `memory_health_check` で検証する。
- **受け入れ基準**:
  - Given `promoted: true` だが AGENTS.md に記載がない Values, When `memory_health_check` 実行, Then 不整合として報告される
  - Given AGENTS.md 側の記述が Values エントリと異なる, When チェック実行, Then 差異が報告される
- **優先度**: Should
- **出典**: エージェント推測（昇格メカニズムの運用安定性に必要）
- **関連要件**: REQ-FUNC-016, REQ-FUNC-022

**チェック項目:**
1. `promoted: true` の Values エントリが AGENTS.md セクションに存在するか（`id` による存在チェック）
2. AGENTS.md セクションに記載があるが `promoted: true` でないエントリはないか（`id` による逆方向チェック）
3. AGENTS.md の記述と Values エントリの `description` の**投影後テキスト**が一致するか（内容チェック）

**投影後テキスト:** 昇格時に AGENTS.md へ書き込む際の正規化ルール（正規定義はアーキテクチャ文書セクション 9.2: 200 文字切り詰め、改行のスペース置換、HTML コメントマーカーのサニタイズ）を適用した結果のテキスト。同期チェックでは Values エントリの `description` をこの投影処理に通した値と AGENTS.md 上のテキストを比較する。書き込み側と読み取り側で同一の正規化ルールを使用することで、正当な切り詰め・サニタイズによる差異は不整合として報告されない。

**同期スコープ:** `id`（存在有無）と `description`（投影後テキスト一致）のみをチェック対象とする。AGENTS.md に表示される `confidence` と `evidence` 件数はプロモーション実行時点のスナップショット値であり、Values エントリ更新時に追従しないため、同期チェックの対象外とする。

**復旧経路:** `memory_health_check(fix=true)` 実行時に以下の修復を行う:
1. `promoted: true` だが AGENTS.md に記載がない Values → AGENTS.md の「内面化された価値観」セクションに投影後テキスト（セクション 9.2 の正規化ルール適用）を再挿入する。これは `memory_values_promote` の再実行（REQ-FUNC-016 で禁止）とは異なり、既に `promoted: true` であるエントリの AGENTS.md 側の欠落を修復する操作である
2. AGENTS.md に記載があるが `promoted: true` でないエントリ → AGENTS.md から該当行を除去する
3. AGENTS.md の記述と投影後テキストが不一致 → AGENTS.md 側を投影後テキストで上書きする

---

#### REQ-FUNC-029: retrospective スキル拡張

- **説明**: 既存の retrospective スキルに Knowledge/Values の定期蒸留機能を追加する。
- **受け入れ基準**:
  - Given retrospective スキルを起動, When 蒸留条件（REQ-FUNC-026）を満たしている, Then 蒸留の実行が提案される
  - Given 蒸留モードを実行, When 完了, Then 抽出された Knowledge/Values のサマリがユーザーに報告される
- **優先度**: Should
- **出典**: エージェント推測
- **関連要件**: REQ-FUNC-010, REQ-FUNC-011, REQ-FUNC-026

---

### 3.11 Could 要件

#### REQ-FUNC-030: Knowledge 統計

- **説明**: Knowledge エントリの統計情報（総数、ドメイン別分布、accuracy 別分布、user_understanding 別分布、source_type 別分布）を返す。
- **優先度**: Could
- **出典**: エージェント推測
- **MCP ツール**: `memory_knowledge_stats`

---

#### REQ-FUNC-031: Values 統計

- **説明**: Values エントリの統計情報（総数、カテゴリ別分布、確信度分布、昇格済み数）を返す。
- **優先度**: Could
- **出典**: エージェント推測
- **MCP ツール**: `memory_values_stats`

---

#### REQ-FUNC-032: 横断検索

- **説明**: Memory ノート・Knowledge・Values を横断して検索する。
- **優先度**: Could
- **出典**: エージェント推測
- **関連要件**: REQ-FUNC-005, REQ-FUNC-008
- **MCP ツール**: `memory_search_all`

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `query` | string | Yes | 検索クエリ |
| `include` | list[enum] | No | 検索対象（`memory`, `knowledge`, `values`）。デフォルト: 全て |
| `top` | int | No | 各カテゴリからの最大件数（デフォルト: 5） |

---

#### REQ-FUNC-033: 関連知識の自律探索

- **説明**: 既存 Knowledge の `related` が少ない孤立エントリを検出し、関連トピックを自律的に調査・提案する。
- **優先度**: Could
- **出典**: エージェント推測
- **関連要件**: REQ-FUNC-004, REQ-FUNC-014

---

#### REQ-FUNC-034: Values 降格・撤回

- **説明**: AGENTS.md に昇格済みの Values を降格し、通常の Values エントリに戻す。`confidence` が `promoted_confidence`（昇格時に記録された確信度）から 0.2 以上低下した場合に自動提案。
- **受け入れ基準**:
  - Given `promoted: true` の Values エントリ, When `memory_values_demote(id, reason)` 実行, Then `promoted` が `false` に変更され、エントリに `demotion_reason` と `demoted_at` が記録される
  - Given `promoted: true` のエントリ, When 降格実行, Then AGENTS.md の「内面化された価値観」セクションから該当エントリが除去される
  - Given `promoted: false` のエントリ, When 降格試行, Then エラーを返す（降格対象が昇格済みでない）
  - Given 存在しない `id`, When 降格試行, Then エラーを返す
- **優先度**: Could
- **出典**: エージェント推測
- **関連要件**: REQ-FUNC-016, REQ-FUNC-022
- **MCP ツール**: `memory_values_demote`

| パラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | Yes | 降格対象の Values ID |
| `reason` | string | Yes | 降格理由 |

**処理:**
1. 対象エントリの存在と `promoted: true` を検証する。条件を満たさない場合はエラー
2. AGENTS.md の `BEGIN/END:PROMOTED_VALUES` マーカー存在を検証する。欠落時はエラーを返し、`memory_init` の再実行を案内する
3. AGENTS.md から該当エントリの行を削除する（排他ロック + atomic write）
4. エントリの昇格状態を更新する（`promoted: false`, `demotion_reason: reason`, `demoted_at: now`）
5. `values/{id}.md` と `_values.jsonl` のエントリを更新する（削除ではなく状態更新）

**出力:** MCP ツール共通規約（§3.2）に従い `{ok: true, id, description, reason, demoted_at}` 形式で返す（`description` はエントリの要約）。

**部分失敗:** AGENTS.md 書き込み（外部影響が大きい操作）を先に実行し、Values エントリ更新が失敗した場合は `memory_health_check` で不整合を検出・修復する（昇格フローと同じ方針。REQ-FUNC-028 参照）。

---

## 4. 非機能要件

### 4.1 性能

#### REQ-NF-001: 検索応答時間

- **基準**: `memory_knowledge_search` および `memory_values_search` は、エントリ数 1,000 件以下の場合、95 パーセンタイルで応答時間 500ms 以内
- **ベンチマーク環境**: 以下のいずれかの環境で計測する。どちらの環境でも基準を満たすこと:
  - CI ランナー: GitHub Actions 標準ランナー（`ubuntu-latest`）。ハードウェア仕様はリポジトリ可視性により異なる（private: 2 vCPU / 8 GB RAM、public: 4 vCPU / 16 GB RAM。2026-04-09 時点の GitHub Docs 準拠）。どちらの仕様でも基準を満たすこと
  - 開発者ラップトップ: Apple Silicon（M1 以降）または x86-64、8GB+ RAM、SSD ストレージ
- **根拠**: 既存の `memory_search` と同等の応答性能を維持する
- **優先度**: Must

#### REQ-NF-002: 蒸留処理時間

- **基準**: `memory_distill_knowledge` / `memory_distill_values` の処理時間のうち、collect 段（ノート選定・読み込み）と integrate 段（統合判定・永続化）の合計が 100 ノートあたり 5 秒以内。extract 段（`DistillationExtractorPort` 経由の LLM 抽出）は計測対象外
- **根拠**: 蒸留は LLM がボトルネックであり、ツール側の前処理・後処理は高速である必要がある
- **優先度**: Should

### 4.2 運用性

#### REQ-NF-003: 後方互換性

- **基準**: 既存の 19 MCP ツールの入出力仕様に破壊的変更を加えない。既存テストスイート（270+ テストケース）が全件パスすること
- **注記**: ただし `memory_state_show` および `memory_stats` の 2 ツールは追加的フィールド拡張を行う（REQ-FUNC-026 参照）。`as_json=true`（デフォルト）では新規フィールドの追加のみであり既存フィールドの削除・型変更は行わない。`as_json=false` では rendered markdown の構造が変わるため、`output` 文字列を位置依存でパースするクライアントには影響しうる
- **優先度**: Must

#### REQ-NF-004: Health Check 統合

- **基準**: 既存の `memory_health_check` が Knowledge/Values のインデックス整合性もチェックする。orphan エントリ（ファイルなしのインデックスエントリ）と orphan ファイル（インデックスなしのファイル）を検出できること。加えて、Knowledge の `related` フィールドについて、参照先が存在しない orphan link および片方向リンク（A→B は存在するが B→A が存在しない）を検出すること。`fix` パラメータが `true` の場合、検出された問題を自動修復する（orphan インデックスエントリの除去、未登録ファイルの再インデックス、orphan link の除去、片方向リンクの双方向化）。デフォルト（`fix=false`）は検出・報告のみ。`fix=true` の修復範囲はインデックス整合性、`related` リンク整合性、および AGENTS.md の promoted Values 同期差分（REQ-FUNC-028）を含む。promoted 同期の修復内容は REQ-FUNC-028 の「復旧経路」を参照
- **lazy 生成パターンでの判定基準**:

| 状態 | health check の判定 |
|---|---|
| ディレクトリもインデックスも存在しない | 正常（機能未使用） |
| ディレクトリ存在 + インデックス不在 + ディレクトリ内にファイルなし | 正常（機能未使用、ディレクトリは `memory_init` で作成済み） |
| ディレクトリ存在 + インデックス不在 + ディレクトリ内にファイルあり | 異常（orphan ファイル。インデックスに未登録のエントリファイルが存在） |
| ディレクトリ存在 + インデックス存在 | 通常の orphan チェック（双方向の整合性検証） |

- **優先度**: Must

#### REQ-NF-005: マイグレーション

- **基準**: 既存の `memory/` ディレクトリに Knowledge/Values 機能を導入する際、`memory_init` の再実行のみで必要なディレクトリ・ファイルが作成されること。手動のマイグレーション作業が不要であること
- **優先度**: Must

### 4.3 セキュリティ

#### REQ-NF-006: AGENTS.md 書き込みガードレール

- **基準**: `memory_values_promote` による AGENTS.md 書き込みは `confirm: true` パラメータが必須。誤操作による AGENTS.md の破損を防止する
- **優先度**: Must

#### REQ-NF-007: 機密情報の除外

- **基準**: Knowledge/Values エントリに対してシークレット・認証情報・API キーの検出バリデーションを行う。検出時のポリシーは操作の不可逆度に応じて段階的に適用する:
  - `memory_knowledge_add` / `memory_knowledge_update` / `memory_values_add` / `memory_values_update`: 警告をレスポンスに含めるが、保存は継続する（エージェントが警告に基づいて修正判断を行う想定）
  - `memory_values_promote`: AGENTS.md への書き込みは不可逆影響が大きいため、シークレット検出時は昇格を拒否する
  - `memory_distill_knowledge` / `memory_distill_values`（`dry_run=false`）: 蒸留パイプラインの integrate 段で add/update が機密検出警告を返した場合、該当エントリの永続化をスキップし、`DistillationReport` に `secret_skipped_count` として報告する。蒸留の自動化特性上、人間の介在なしに機密情報が永続化されることを防止する
- **優先度**: Should

### 4.4 テスト

#### REQ-NF-008: テストカバレッジ

- **基準**: 新規追加される全モジュール（Knowledge CRUD、Values CRUD、蒸留エンジン、昇格メカニズム）に対してユニットテストを作成する。各 MCP ツールの正常系・異常系を網羅すること
- **優先度**: Must

---

## 5. 要件間の関連

### 5.1 依存関係（depends on）

```
REQ-FUNC-004 (Knowledge 登録) → REQ-FUNC-001 (Knowledge データモデル)
REQ-FUNC-004 (Knowledge 登録) → REQ-FUNC-003 (ストレージ設計)
REQ-FUNC-005 (Knowledge 検索) → REQ-FUNC-003 (ストレージ設計)
REQ-FUNC-006 (Knowledge 更新) → REQ-FUNC-004 (Knowledge 登録)
REQ-FUNC-007 (Values 登録) → REQ-FUNC-002 (Values データモデル)
REQ-FUNC-007 (Values 登録) → REQ-FUNC-003 (ストレージ設計)
REQ-FUNC-008 (Values 検索) → REQ-FUNC-003 (ストレージ設計)
REQ-FUNC-009 (Values 更新) → REQ-FUNC-007 (Values 登録)
REQ-FUNC-010 (Knowledge 蒸留) → REQ-FUNC-004 (Knowledge 登録)
REQ-FUNC-010 (Knowledge 蒸留) → REQ-FUNC-012 (Knowledge 統合)
REQ-FUNC-011 (Values 蒸留) → REQ-FUNC-007 (Values 登録)
REQ-FUNC-011 (Values 蒸留) → REQ-FUNC-013 (Values 統合)
REQ-FUNC-015 (昇格判定) → REQ-FUNC-007 (Values 登録)
REQ-FUNC-015 (昇格判定) → REQ-FUNC-009 (Values 更新)
REQ-FUNC-016 (AGENTS.md 反映) → REQ-FUNC-015 (昇格判定)
REQ-FUNC-016 (AGENTS.md 反映) → REQ-FUNC-022 (昇格 Values セクション)
REQ-FUNC-019 (記憶管理拡張) → REQ-FUNC-001, REQ-FUNC-002 (データモデル)
REQ-FUNC-020 (開始手順更新) → REQ-FUNC-008 (Values 検索)
REQ-FUNC-021 (終了手順更新) → REQ-FUNC-010, REQ-FUNC-011 (蒸留)
REQ-FUNC-021 (終了手順更新) → REQ-FUNC-026 (蒸留トリガー判定)
REQ-FUNC-023 (Knowledge 削除) → REQ-FUNC-004 (Knowledge 登録)
REQ-FUNC-024 (Values 削除) → REQ-FUNC-007 (Values 登録)
REQ-FUNC-028 (昇格同期) → REQ-FUNC-016 (AGENTS.md 反映)
REQ-FUNC-029 (retrospective 拡張) → REQ-FUNC-010, REQ-FUNC-011 (蒸留)
REQ-FUNC-034 (降格) → REQ-FUNC-016 (AGENTS.md 反映)
```

### 5.2 CRUD データマトリクス

| エンティティ | Create | Read | Update | Delete |
|---|---|---|---|---|
| **Knowledge** | REQ-FUNC-004 | REQ-FUNC-005 | REQ-FUNC-006 | REQ-FUNC-023 (Should) |
| **Values** | REQ-FUNC-007 | REQ-FUNC-008, REQ-FUNC-025 (Should) | REQ-FUNC-009 | REQ-FUNC-024 (Should) |
| **AGENTS.md Values セクション** | REQ-FUNC-022 | (暗黙: AGENTS.md 読み込み) | REQ-FUNC-016 | REQ-FUNC-024, REQ-FUNC-034 (Could) |

---

## 6. 未確定事項

| # | 内容 | 関連要件 | 確認相手 | 暫定値 |
|---|---|---|---|---|
| 1 | 確信度更新の具体的アルゴリズム（LLM 判定 vs 固定数式） | REQ-FUNC-013 | プロダクトオーナー | LLM 判定（コンテキスト依存） |

### 6.1 解決済み事項

| # | 内容 | 関連要件 | 解決内容 |
|---|---|---|---|
| 2 | Knowledge/Values の初期シードデータ（既存 AGENTS.md の設計方針等。CLAUDE.md は AGENTS.md への symlink）を移行するか | REQ-FUNC-001, REQ-FUNC-002 | 自動シード/バックフィルは行わない。既存リポジトリは空の Knowledge/Values ストアから開始する。`memory_init` はディレクトリとマーカーを作成するが、既存 AGENTS.md や Memory ノートからの自動抽出は実施しない（REQ-NF-005 の「手動マイグレーション不要」と整合）。既存の設計方針等を Knowledge/Values として登録したい場合は、ユーザーまたはエージェントが `memory_knowledge_add` / `memory_values_add` / `memory_distill_*` を明示的に実行する |
| 3 | Knowledge の `domain` 分類体系（固定リスト vs 自由入力） | REQ-FUNC-001, REQ-FUNC-004 | 自由入力（kebab-case に正規化）。REQ-FUNC-001 の属性定義、DOMAIN モデルの `Domain` 値オブジェクトとして確定済み |
| 4 | Values の `category` 分類体系（固定リスト vs 自由入力） | REQ-FUNC-002, REQ-FUNC-007 | 自由入力（kebab-case に正規化）。REQ-FUNC-002 の属性定義、DOMAIN モデルの `Category` 値オブジェクトとして確定済み |
| 5 | `memory_values_add` の類似判定に使用するアルゴリズム（BM25 スコア閾値 vs LLM 判定） | REQ-FUNC-007 | BM25+ max-normalized スコア 0.7 以上（REQ-FUNC-007「類似判定の仕様」参照。正規化方法: 最大スコアで除算。運用データの蓄積後に閾値を調整する） |
| 6 | 検索応答時間のベンチマーク環境（ハードウェアスペック） | REQ-NF-001 | REQ-NF-001 に具体的な環境仕様を記載（GitHub Actions 標準ランナー / Apple Silicon M1+ or x86-64, 8GB+ RAM, SSD） |
