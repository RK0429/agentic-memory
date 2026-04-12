from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import agentic_memory.server as server_module
from agentic_memory.core.knowledge import KnowledgeRepository
from agentic_memory.server import (
    memory_knowledge_add,
    memory_knowledge_delete,
    memory_knowledge_search,
    memory_knowledge_update,
)


def _knowledge_add_payload(memory_dir: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return json.loads(memory_knowledge_add(entries=entries, memory_dir=str(memory_dir)))


def _knowledge_update_payload(memory_dir: Path, updates: list[dict[str, Any]]) -> dict[str, Any]:
    return json.loads(memory_knowledge_update(updates=updates, memory_dir=str(memory_dir)))


def _knowledge_delete_payload(
    memory_dir: Path,
    ids: list[str],
    *,
    confirm: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    return json.loads(
        memory_knowledge_delete(
            ids=ids,
            confirm=confirm,
            reason=reason,
            memory_dir=str(memory_dir),
        )
    )


def _single_result(payload: dict[str, Any]) -> dict[str, Any]:
    assert payload["ok"] is True
    assert len(payload["results"]) == 1
    return payload["results"][0]


def test_memory_knowledge_tools_add_search_update_flow(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    base_payload = _knowledge_add_payload(
        tmp_memory_dir,
        [
            {
                "title": "Rust ownership",
                "content": "Ownership explains moves and borrows.",
                "domain": "rust",
                "tags": ["rust"],
                "accuracy": "likely",
                "sources": [
                    {
                        "type": "memory_note",
                        "ref": "memory/2026-04-10/rust.md",
                        "summary": "Ownership note",
                    }
                ],
            }
        ],
    )
    related_payload = _knowledge_add_payload(
        tmp_memory_dir,
        [
            {
                "title": "Rust lifetimes",
                "content": "Lifetimes connect borrows to scopes.",
                "domain": "rust",
            }
        ],
    )

    base = _single_result(base_payload)
    related = _single_result(related_payload)
    assert base_payload["success_count"] == 1
    assert base_payload["error_count"] == 0
    assert base["path"] == f"knowledge/{base['id']}.md"
    assert base["domain"] == "rust"

    search_payload = json.loads(
        memory_knowledge_search(query="ownership", memory_dir=str(tmp_memory_dir))
    )
    assert search_payload["ok"] is True
    assert search_payload["entries"][0]["id"] == base["id"]
    assert "Ownership explains moves" in search_payload["entries"][0]["content_snippet"]
    assert search_payload["entries"][0]["score"] > 0

    update_payload = _knowledge_update_payload(
        tmp_memory_dir,
        [
            {
                "id": base["id"],
                "accuracy": "verified",
                "user_understanding": "familiar",
                "related": [related["id"]],
                "sources": [
                    {
                        "type": "web",
                        "ref": "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
                        "summary": "Rust Book ownership",
                    }
                ],
                "tags": ["rust", "systems"],
            }
        ],
    )

    assert update_payload == {
        "ok": True,
        "success_count": 1,
        "error_count": 0,
        "results": [
            {
                "index": 0,
                "ok": True,
                "id": base["id"],
                "updated_fields": [
                    "accuracy",
                    "sources",
                    "user_understanding",
                    "related",
                    "tags",
                ],
            }
        ],
    }

    updated_entry = repository.load(base["id"])
    related_entry = repository.load(related["id"])
    assert str(updated_entry.accuracy) == "verified"
    assert str(updated_entry.user_understanding) == "familiar"
    assert len(updated_entry.sources) == 2
    assert updated_entry.tags == ["rust", "systems"]
    assert [str(related_id) for related_id in updated_entry.related] == [related["id"]]
    assert [str(related_id) for related_id in related_entry.related] == [base["id"]]


def test_memory_knowledge_add_isolates_secret_and_duplicate_errors(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _knowledge_add_payload(
        tmp_memory_dir,
        [
            {
                "title": "Rust ownership",
                "content": "Ownership summary",
                "domain": "rust",
            },
            {
                "title": "Secret example",
                "content": 'api_key="AbCdEf1234567890"',
                "domain": "security",
            },
            {
                "title": "Rust ownership",
                "content": "Ownership   summary",
                "domain": "Rust",
            },
        ],
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert payload["error_count"] == 2
    assert payload["results"][0]["ok"] is True
    assert payload["results"][1] == {
        "index": 1,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": (
            "Content appears to contain secrets (detected: generic_api_token). "
            "Remove secrets or sanitize the content before retrying."
        ),
        "hint": (
            "Sanitize sensitive values (API keys, tokens, high-entropy strings) "
            "from the content and retry."
        ),
    }
    assert payload["results"][2]["ok"] is False
    assert payload["results"][2]["message"].startswith("Duplicate knowledge entry")
    assert len(list((tmp_memory_dir / "knowledge").glob("*.md"))) == 1


def test_memory_knowledge_add_rejects_malformed_content_per_item_and_continues(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _knowledge_add_payload(
        tmp_memory_dir,
        [
            {
                "title": "Bad content none",
                "content": None,
                "domain": "rust",
            },
            {
                "title": "Rust ownership",
                "content": "Ownership summary",
                "domain": "rust",
            },
            {
                "title": "Bad content list",
                "content": [],
                "domain": "rust",
            },
        ],
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert payload["error_count"] == 2
    assert payload["results"][0] == {
        "index": 0,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].content` entry: expected a non-empty string.",
        "hint": "Pass `entries[].content` as a non-empty string.",
    }
    assert payload["results"][1]["ok"] is True
    assert payload["results"][2] == {
        "index": 2,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].content` entry: expected a non-empty string.",
        "hint": "Pass `entries[].content` as a non-empty string.",
    }
    assert len(list((tmp_memory_dir / "knowledge").glob("*.md"))) == 1


def test_memory_knowledge_add_rejects_malformed_title_and_domain_per_item_and_continues(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _knowledge_add_payload(
        tmp_memory_dir,
        [
            {
                "title": None,
                "content": "Ownership summary",
                "domain": "rust",
            },
            {
                "title": "Bad domain list",
                "content": "Ownership summary",
                "domain": [],
            },
            {
                "title": "Rust ownership",
                "content": "Ownership summary",
                "domain": "rust",
            },
            {
                "title": "",
                "content": "Ownership summary",
                "domain": "rust",
            },
            {
                "title": "Bad domain blank",
                "content": "Ownership summary",
                "domain": "   ",
            },
        ],
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert payload["error_count"] == 4
    assert payload["results"][0] == {
        "index": 0,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].title` entry: expected a non-empty string.",
        "hint": "Pass `entries[].title` as a non-empty string.",
    }
    assert payload["results"][1] == {
        "index": 1,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].domain` entry: expected a non-empty string.",
        "hint": "Pass `entries[].domain` as a non-empty string.",
    }
    assert payload["results"][2]["ok"] is True
    assert payload["results"][3] == {
        "index": 3,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].title` entry: expected a non-empty string.",
        "hint": "Pass `entries[].title` as a non-empty string.",
    }
    assert payload["results"][4] == {
        "index": 4,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].domain` entry: expected a non-empty string.",
        "hint": "Pass `entries[].domain` as a non-empty string.",
    }
    assert len(list((tmp_memory_dir / "knowledge").glob("*.md"))) == 1


def test_memory_knowledge_add_validates_schema_enum_defaults_and_batch_limits(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    malformed = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Rust ownership",
                    "content": "Ownership summary",
                    "domain": "rust",
                    "sources": [{"type": "user_taught", "ref": "memory/2026-04-10/rust.md"}],
                }
            ],
        )
    )
    assert malformed["ok"] is False
    assert malformed["error_type"] == "validation_error"
    assert "{type, ref, summary}" in malformed["hint"]

    invalid_source_type = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Rust ownership 2",
                    "content": "Ownership summary 2",
                    "domain": "rust",
                    "origin": "invalid_source_type",
                }
            ],
        )
    )
    assert invalid_source_type["ok"] is False
    assert invalid_source_type["error_type"] == "validation_error"
    assert "is not a valid SourceType" in invalid_source_type["message"]
    assert "origin" in invalid_source_type["hint"]

    created = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Rust defaults",
                    "content": "Ownership defaults",
                    "domain": "rust",
                }
            ],
        )
    )
    assert str(repository.load(created["id"]).origin) == "user_taught"

    fifty_entries = [
        {"title": f"Topic {index}", "content": f"Content {index}", "domain": "batch"}
        for index in range(50)
    ]
    full_batch = _knowledge_add_payload(tmp_memory_dir, fifty_entries)
    assert full_batch["ok"] is True
    assert full_batch["success_count"] == 50
    assert full_batch["error_count"] == 0

    oversize = _knowledge_add_payload(
        tmp_memory_dir,
        fifty_entries + [{"title": "Overflow", "content": "Overflow", "domain": "batch"}],
    )
    assert oversize["ok"] is False
    assert oversize["error_type"] == "validation_error"
    assert oversize["message"] == (
        "Batch size 51 exceeds maximum 50 (configurable via AGENTIC_MEMORY_MAX_BATCH_SIZE)"
    )

    empty = _knowledge_add_payload(tmp_memory_dir, [])
    assert empty["ok"] is False
    assert empty["error_type"] == "validation_error"
    assert empty["message"] == "Batch cannot be empty"


def test_memory_knowledge_add_lists_valid_accuracy_and_user_understanding_values_in_hint(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    invalid_accuracy = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Accuracy validation",
                    "content": "Accuracy validation",
                    "domain": "rust",
                    "accuracy": "super-verified",
                }
            ],
        )
    )
    assert invalid_accuracy["ok"] is False
    assert invalid_accuracy["error_type"] == "validation_error"
    assert "is not a valid Accuracy" in invalid_accuracy["message"]
    for value in ("verified", "likely", "uncertain"):
        assert value in invalid_accuracy["hint"]

    invalid_user_understanding = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "User understanding validation",
                    "content": "User understanding validation",
                    "domain": "rust",
                    "user_understanding": "super-expert",
                }
            ],
        )
    )
    assert invalid_user_understanding["ok"] is False
    assert invalid_user_understanding["error_type"] == "validation_error"
    assert "is not a valid UserUnderstanding" in invalid_user_understanding["message"]
    for value in ("unknown", "novice", "familiar", "proficient", "expert"):
        assert value in invalid_user_understanding["hint"]


def test_memory_knowledge_search_supports_cjk_full_content_and_toggle(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    created = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "設計の原則",
                    "content": "KISS 原則と YAGNI 原則を優先する。",
                    "domain": "design",
                    "tags": ["architecture"],
                    "sources": [
                        {
                            "type": "document",
                            "ref": "docs/design-principles.md",
                            "summary": "設計原則のメモ",
                        }
                    ],
                }
            ],
        )
    )

    exact_payload = json.loads(
        memory_knowledge_search(query="原則", memory_dir=str(tmp_memory_dir))
    )
    assert exact_payload["ok"] is True
    assert exact_payload["entries"][0]["id"] == created["id"]
    assert "content" not in exact_payload["entries"][0]

    expanded_payload = json.loads(
        memory_knowledge_search(query="原則詳細論", memory_dir=str(tmp_memory_dir))
    )
    assert expanded_payload["ok"] is True
    assert expanded_payload["entries"][0]["id"] == created["id"]

    disabled_payload = json.loads(
        memory_knowledge_search(
            query="原則詳細論",
            no_cjk_expand=True,
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert disabled_payload == {"entries": [], "ok": True}

    full_payload = json.loads(
        memory_knowledge_search(
            query="原則",
            include_full_content=True,
            memory_dir=str(tmp_memory_dir),
        )
    )
    entry = full_payload["entries"][0]
    assert entry["content"] == "KISS 原則と YAGNI 原則を優先する。"
    assert entry["sources"] == [
        {
            "type": "document",
            "ref": "docs/design-principles.md",
            "summary": "設計原則のメモ",
        }
    ]
    assert entry["tags"] == ["architecture"]
    assert entry["related"] == []
    assert entry["origin"] == "user_taught"
    assert "created_at" in entry
    assert "updated_at" in entry


def test_memory_knowledge_search_domain_only_returns_null_score(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    _knowledge_add_payload(
        tmp_memory_dir,
        [
            {"title": "Rust ownership", "content": "Ownership summary", "domain": "rust"},
            {"title": "Rust lifetimes", "content": "Lifetime summary", "domain": "rust"},
            {"title": "Python generators", "content": "Yield summary", "domain": "python"},
        ],
    )

    payload = json.loads(memory_knowledge_search(domain="rust", memory_dir=str(tmp_memory_dir)))

    assert payload["ok"] is True
    assert [entry["score"] for entry in payload["entries"]] == [None, None]


def test_memory_knowledge_search_domain_only_ignores_min_score(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    _knowledge_add_payload(
        tmp_memory_dir,
        [
            {"title": "Rust ownership", "content": "Ownership summary", "domain": "rust"},
            {"title": "Rust lifetimes", "content": "Lifetime summary", "domain": "rust"},
        ],
    )

    payload = json.loads(
        memory_knowledge_search(
            domain="rust",
            min_score=9999.0,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert len(payload["entries"]) == 2
    assert [entry["score"] for entry in payload["entries"]] == [None, None]


def test_memory_knowledge_search_min_score_filters_lower_scored_matches(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    strong = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Rust ownership and borrowing",
                    "content": "Ownership borrowing ownership borrowing rules for Rust.",
                    "domain": "rust",
                }
            ],
        )
    )
    weaker = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Rust borrowing rules",
                    "content": "Borrowing rules help avoid moving ownership.",
                    "domain": "rust",
                }
            ],
        )
    )

    baseline = json.loads(
        memory_knowledge_search(
            query="ownership borrowing rules",
            top=10,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert baseline["ok"] is True
    assert [entry["id"] for entry in baseline["entries"][:2]] == [strong["id"], weaker["id"]]
    high_score = baseline["entries"][0]["score"]
    low_score = baseline["entries"][1]["score"]
    assert high_score > low_score > 0

    payload = json.loads(
        memory_knowledge_search(
            query="ownership borrowing rules",
            min_score=(high_score + low_score) / 2,
            top=10,
            memory_dir=str(tmp_memory_dir),
        )
    )

    assert payload["ok"] is True
    assert [entry["id"] for entry in payload["entries"]] == [strong["id"]]


def test_memory_knowledge_add_docstring_documents_sources_schema() -> None:
    add_doc = server_module.memory_knowledge_add.__doc__ or ""
    search_doc = server_module.memory_knowledge_search.__doc__ or ""
    update_doc = server_module.memory_knowledge_update.__doc__ or ""

    assert "`origin` is the entry-level provenance classification" in add_doc
    assert "Each source object requires `type`, `ref`, and `summary` fields." in add_doc
    assert "`sources[].type` is the per-reference kind" in add_doc
    assert "`source_type` as an" in add_doc
    for value in (
        '"memory_distillation"',
        '"autonomous_research"',
        '"user_taught"',
    ):
        assert value in add_doc
    for value in (
        '"memory_note"',
        '"web"',
        '"user_direct"',
        '"document"',
        '"code"',
        '"other"',
    ):
        assert value in add_doc
    assert "Optional `min_score`" in search_doc
    assert "BM25+ score threshold" in search_doc
    assert "Immutable fields (`title`, `domain`) cannot be changed after creation." in update_doc


def test_memory_knowledge_add_accepts_legacy_source_type_alias_and_origin_precedence(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    legacy = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Release checklist",
                    "content": "Document the release checklist.",
                    "domain": "ops",
                    "source_type": "autonomous_research",
                }
            ],
        )
    )
    explicit = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Review checklist",
                    "content": "Document the review checklist.",
                    "domain": "ops",
                    "origin": "user_taught",
                    "source_type": "autonomous_research",
                }
            ],
        )
    )

    assert str(repository.load(legacy["id"]).origin) == "autonomous_research"
    assert str(repository.load(explicit["id"]).origin) == "user_taught"


def test_memory_knowledge_update_reports_warnings_and_isolates_missing_id(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    base = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [{"title": "Rust ownership", "content": "Ownership summary", "domain": "rust"}],
        )
    )
    related = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [{"title": "Rust borrowing", "content": "Borrowing summary", "domain": "rust"}],
        )
    )

    payload = _knowledge_update_payload(
        tmp_memory_dir,
        [
            {
                "id": base["id"],
                "content": 'auth_token="AbCdEf1234567890"',
                "related": [related["id"]],
            },
            {
                "id": "k-11111111-1111-1111-1111-111111111111",
                "content": "Updated content",
            },
        ],
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert payload["error_count"] == 1
    assert payload["results"][0]["warnings"] == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]
    assert payload["results"][1] == {
        "index": 1,
        "ok": False,
        "id": "k-11111111-1111-1111-1111-111111111111",
        "error_type": "not_found",
        "message": "Knowledge entry not found: k-11111111-1111-1111-1111-111111111111",
        "hint": "Verify the knowledge id and any `related` ids exist before retrying.",
    }
    assert [str(related_id) for related_id in repository.load(related["id"]).related] == [
        base["id"]
    ]


def test_memory_knowledge_update_validates_missing_fields(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    added = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [{"title": "Rust ownership", "content": "Ownership summary", "domain": "rust"}],
        )
    )

    payload = _single_result(_knowledge_update_payload(tmp_memory_dir, [{"id": added["id"]}]))

    assert payload["ok"] is False
    assert payload["id"] == added["id"]
    assert payload["error_type"] == "validation_error"
    assert payload["message"] == (
        "At least one update field is required "
        "(content, accuracy, sources, user_understanding, related, tags)"
    )


def test_memory_knowledge_update_rejects_unknown_fields(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    added = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [{"title": "Rust ownership", "content": "Ownership summary", "domain": "rust"}],
        )
    )

    unknown_only = _single_result(
        _knowledge_update_payload(tmp_memory_dir, [{"id": added["id"], "unexpected": True}])
    )
    assert unknown_only["ok"] is False
    assert unknown_only["id"] == added["id"]
    assert unknown_only["error_type"] == "validation_error"
    assert unknown_only["message"] == (
        "Unknown update fields: unexpected. "
        "Allowed update fields are: content, accuracy, sources, user_understanding, "
        "related, tags"
    )

    mixed_fields = _single_result(
        _knowledge_update_payload(
            tmp_memory_dir,
            [{"id": added["id"], "content": "Updated summary", "unexpected": True}],
        )
    )
    assert mixed_fields["ok"] is False
    assert mixed_fields["id"] == added["id"]
    assert mixed_fields["error_type"] == "validation_error"
    assert mixed_fields["message"] == (
        "Unknown update fields: unexpected. "
        "Allowed update fields are: content, accuracy, sources, user_understanding, "
        "related, tags"
    )


def test_memory_knowledge_update_missing_id_takes_precedence_over_missing_fields(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _single_result(
        _knowledge_update_payload(
            tmp_memory_dir,
            [{"id": "k-11111111-1111-1111-1111-111111111111"}],
        )
    )

    assert payload["ok"] is False
    assert payload["id"] == "k-11111111-1111-1111-1111-111111111111"
    assert payload["error_type"] == "not_found"
    assert payload["message"] == "Knowledge entry not found: k-11111111-1111-1111-1111-111111111111"


def test_memory_knowledge_delete_preview_and_bulk_delete_preserve_backlink_regression(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    repository = KnowledgeRepository(tmp_memory_dir)

    base = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [{"title": "Rust ownership", "content": "Ownership summary", "domain": "rust"}],
        )
    )
    related = _single_result(
        _knowledge_add_payload(
            tmp_memory_dir,
            [
                {
                    "title": "Rust borrowing",
                    "content": "Borrowing summary",
                    "domain": "rust",
                    "related": [base["id"]],
                }
            ],
        )
    )

    preview = _knowledge_delete_payload(tmp_memory_dir, [base["id"]])
    assert preview == {
        "ok": True,
        "success_count": 1,
        "error_count": 0,
        "results": [
            {
                "index": 0,
                "ok": True,
                "id": base["id"],
                "deleted_id": base["id"],
                "title": "Rust ownership",
                "preview": True,
                "would_delete": True,
            }
        ],
    }
    assert repository.find_by_id(base["id"]) is not None
    assert [str(related_id) for related_id in repository.load(related["id"]).related] == [
        base["id"]
    ]

    payload = _knowledge_delete_payload(
        tmp_memory_dir,
        [base["id"], "k-22222222-2222-2222-2222-222222222222"],
        confirm=True,
        reason="cleanup duplicate knowledge",
    )
    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert payload["error_count"] == 1
    assert payload["results"][0] == {
        "index": 0,
        "ok": True,
        "id": base["id"],
        "deleted_id": base["id"],
        "title": "Rust ownership",
        "deleted": True,
        "reason": "cleanup duplicate knowledge",
    }
    assert payload["results"][1]["ok"] is False
    assert payload["results"][1]["error_type"] == "not_found"
    assert repository.find_by_id(base["id"]) is None
    assert repository.load(related["id"]).related == []
