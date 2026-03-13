# agentic-memory

AI エージェント用の永続記憶システム（MCP サーバー）。PyPI パッケージ名: `agmemory`

## 開発

```bash
uv sync --all-extras --dev      # 依存インストール
uv run pre-commit install       # pre-commit フックの有効化
uv run pre-commit install --hook-type pre-push  # pre-push フックの有効化
```

### ローカル品質チェック

pre-commit フックにより、コミット時に ruff (lint + format) と mypy、プッシュ時に pytest が自動実行される。手動で全チェックを実行する場合:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest --cov=agentic_memory --cov-report=term-missing
```

## リリース手順

Trusted Publisher 方式により、バージョンタグのプッシュで PyPI パブリッシュと GitHub Release 作成が自動実行される。

### 手順

1. `pyproject.toml` と `src/agentic_memory/__init__.py` のバージョンを更新する
2. `CHANGELOG.md` に変更内容を記載する
3. コミット・プッシュする
4. バージョンタグを作成してプッシュする

```bash
git tag v<VERSION>
git push origin v<VERSION>
```

### 自動実行される処理 (`publish.yml`)

1. CI（ruff check → ruff format --check → mypy → pytest）を Python 3.12/3.13 で実行
2. CI 通過後、`uv build` でパッケージをビルド
3. `pypa/gh-action-pypi-publish` で PyPI にパブリッシュ（Trusted Publisher 認証）
4. `CHANGELOG.md` から該当バージョンのエントリを抽出し、GitHub Release を作成

### 注意事項

- PyPI の Trusted Publisher 設定が前提（リポジトリ: `RK0429/agentic-memory`、ワークフロー: `publish.yml`）
- `pyproject.toml` と `__init__.py` のバージョンは手動で同期する必要がある
- タグ名は `v` プレフィックス付き（例: `v0.4.2`）
