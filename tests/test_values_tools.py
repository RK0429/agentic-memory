from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import agentic_memory.server as server_module
from agentic_memory.core.values import (
    Evidence,
    SourceType,
    ValuesEntry,
    ValuesRepository,
    ValuesService,
)
from agentic_memory.server import (
    memory_values_add,
    memory_values_delete,
    memory_values_demote,
    memory_values_list,
    memory_values_promote,
    memory_values_search,
    memory_values_update,
)


def _evidence(index: int) -> dict[str, str]:
    return {
        "ref": f"memory/2026-04-{index:02d}/note.md",
        "summary": f"evidence-{index}",
        "date": f"2026-04-{index:02d}",
    }


def _seed_promoted_entry(memory_dir: Path, *, description: str) -> ValuesEntry:
    entry = ValuesEntry(
        description=description,
        category="design",
        confidence=0.9,
        evidence=[Evidence.from_dict(_evidence(index)) for index in range(1, 7)],
        total_evidence_count=6,
        source_type=SourceType.USER_TAUGHT,
        promoted=True,
        promoted_confidence=0.9,
        created_at="2026-04-10T09:00:00",
        updated_at="2026-04-10T09:00:00",
    )
    ValuesRepository(memory_dir).save(entry)
    return entry


def _values_add_payload(memory_dir: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return json.loads(memory_values_add(entries=entries, memory_dir=str(memory_dir)))


def _values_update_payload(memory_dir: Path, updates: list[dict[str, Any]]) -> dict[str, Any]:
    return json.loads(memory_values_update(updates=updates, memory_dir=str(memory_dir)))


def _values_promote_payload(
    memory_dir: Path,
    ids: list[str],
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    return json.loads(memory_values_promote(ids=ids, confirm=confirm, memory_dir=str(memory_dir)))


def _values_demote_payload(
    memory_dir: Path,
    ids: list[str],
    *,
    reason: str,
    confirm: bool = False,
) -> dict[str, Any]:
    return json.loads(
        memory_values_demote(ids=ids, reason=reason, confirm=confirm, memory_dir=str(memory_dir))
    )


def _values_delete_payload(
    memory_dir: Path,
    ids: list[str],
    *,
    confirm: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    return json.loads(
        memory_values_delete(
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


def test_memory_values_add_returns_path_warning_and_promotion_candidate(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    first = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [{"description": "Prefer focused reversible changes", "category": "workflow"}],
        )
    )

    payload = _values_add_payload(
        tmp_memory_dir,
        [
            {
                "description": "Prefer focused reversible changes in commits",
                "category": "workflow",
                "confidence": 0.85,
                "evidence": [_evidence(index) for index in range(1, 6)],
            }
        ],
    )
    result = _single_result(payload)

    assert payload["success_count"] == 1
    assert payload["error_count"] == 0
    assert result["path"] == f"values/{result['id']}.md"
    assert result["category"] == "workflow"
    assert result["promotion_candidate"] is True
    assert str(first["id"]) in result["warnings"][0]


def test_memory_values_add_reports_duplicate_and_normalized_category(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    _values_add_payload(
        tmp_memory_dir,
        [{"description": "Prefer compact PR summaries", "category": "communication"}],
    )

    duplicate = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [{"description": " Prefer compact  PR summaries ", "category": " communication "}],
        )
    )
    assert duplicate["ok"] is False
    assert duplicate["error_type"] == "validation_error"
    assert "Duplicate value exists" in duplicate["message"]

    normalized = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [
                {
                    "description": "Prefer snake_case categories to normalize consistently",
                    "category": "coding_style",
                }
            ],
        )
    )
    assert normalized["ok"] is True
    assert normalized["category"] == "coding-style"


def test_memory_values_add_isolates_secret_and_schema_errors(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _values_add_payload(
        tmp_memory_dir,
        [
            {"description": "Prefer focused diffs", "category": "workflow"},
            {
                "description": 'Prefer storing api_key="AbCdEf1234567890" only in vaults',
                "category": "security",
            },
            {
                "description": "Prefer documented secret handling",
                "category": "security",
                "evidence": [
                    {
                        "ref": "memory/2026-04-10/security.md",
                        "summary": 'Rotate auth_token="AbCdEf1234567890" immediately',
                        "date": "2026-04-10",
                    }
                ],
            },
            {
                "description": "Prefer evidence with complete metadata",
                "category": "workflow",
                "evidence": [{"ref": "memory/2026-04-10/note.md", "summary": "missing date"}],
            },
        ],
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert payload["error_count"] == 3
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
    assert payload["results"][3]["ok"] is False
    assert '{ref, summary, date: "YYYY-MM-DD"}' in payload["results"][3]["hint"]
    assert "Missing fields: date" in payload["results"][3]["hint"]
    assert len(list((tmp_memory_dir / "values").glob("*.md"))) == 1


def test_memory_values_add_invalid_evidence_date_reports_iso_hint(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    payload = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [
                {
                    "description": "Prefer ISO formatted evidence dates",
                    "category": "workflow",
                    "evidence": [
                        {
                            "ref": "memory/2026-04-10/note.md",
                            "summary": "bad date",
                            "date": "2026/04/10",
                        }
                    ],
                }
            ],
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["message"] == (
        "Invalid `evidence[].date`: value must be an ISO 8601 date (YYYY-MM-DD)."
    )
    assert payload["hint"] == (
        "Format each evidence `date` as YYYY-MM-DD (e.g. '2026-04-12') and retry."
    )

    public_doc = server_module.memory_values_add.__doc__ or ""
    private_doc = server_module._memory_values_add_single.__doc__ or ""
    assert "YYYY-MM-DD" in public_doc
    assert "YYYY-MM-DD" in private_doc


def test_memory_values_add_invalid_evidence_date_us_format(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """`04-12-2026` のような非 ISO 形式の date が ISO 8601 hint を返すこと。"""
    monkeypatch.chdir(tmp_memory_dir.parent)
    payload = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [
                {
                    "description": "Prefer ISO formatted evidence dates strictly",
                    "category": "workflow",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "ref": "memory/2026-04-12/note.md",
                            "summary": "US format date",
                            "date": "04-12-2026",
                        }
                    ],
                }
            ],
        )
    )
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["message"].startswith("Invalid `evidence[].date`")
    assert "YYYY-MM-DD" in payload["hint"]


def test_memory_values_add_confidence_out_of_range_reports_specific_hint(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """confidence=1.5 が confidence 範囲専用の hint を返すこと。"""
    monkeypatch.chdir(tmp_memory_dir.parent)
    payload = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [
                {
                    "description": "Prefer valid confidence ranges",
                    "category": "workflow",
                    "confidence": 1.5,
                }
            ],
        )
    )
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "confidence" in payload["message"].lower()
    assert "[0.0, 1.0]" in payload["hint"]
    assert "`confidence`" in payload["hint"]


def test_memory_values_add_evidence_missing_date_reports_real_key(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """date キー欠落時に Missing fields が実キー 'date' を含むこと。"""
    monkeypatch.chdir(tmp_memory_dir.parent)
    payload = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [
                {
                    "description": "Prefer evidence with required fields",
                    "category": "workflow",
                    "evidence": [
                        {
                            "ref": "memory/2026-04-12/note.md",
                            "summary": "missing date key",
                        }
                    ],
                }
            ],
        )
    )
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "Missing fields: date" in payload["hint"]
    assert '{ref, summary, date: "YYYY-MM-DD"}' in payload["hint"]


def test_memory_values_update_invalid_add_evidence_date_us_format(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    """`memory_values_update` の add_evidence で非 ISO 形式 date がエラーを返すこと。"""
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [{"description": "Prefer ISO add_evidence dates", "category": "workflow"}],
        )
    )
    payload = _single_result(
        _values_update_payload(
            tmp_memory_dir,
            [
                {
                    "id": added["id"],
                    "add_evidence": [
                        {
                            "ref": "memory/2026-04-12/note.md",
                            "summary": "US format date",
                            "date": "04-12-2026",
                        }
                    ],
                }
            ],
        )
    )
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["message"].startswith("Invalid `add_evidence[].date`")
    assert "YYYY-MM-DD" in payload["hint"]


def test_memory_values_add_rejects_malformed_description_per_item_and_continues(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _values_add_payload(
        tmp_memory_dir,
        [
            {"description": None, "category": "workflow"},
            {"description": "Prefer focused diffs", "category": "workflow"},
            {"description": [], "category": "workflow"},
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
        "message": "Invalid `entries[].description` entry: expected a non-empty string.",
        "hint": "Pass `entries[].description` as a non-empty string.",
    }
    assert payload["results"][1]["ok"] is True
    assert payload["results"][2] == {
        "index": 2,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].description` entry: expected a non-empty string.",
        "hint": "Pass `entries[].description` as a non-empty string.",
    }
    assert len(list((tmp_memory_dir / "values").glob("*.md"))) == 1


def test_memory_values_add_rejects_malformed_category_per_item_and_continues(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = _values_add_payload(
        tmp_memory_dir,
        [
            {"description": "Bad category none", "category": None},
            {"description": "Prefer focused diffs", "category": "workflow"},
            {"description": "Bad category list", "category": []},
            {"description": "Bad category blank", "category": ""},
        ],
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 1
    assert payload["error_count"] == 3
    assert payload["results"][0] == {
        "index": 0,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].category` entry: expected a non-empty string.",
        "hint": "Pass `entries[].category` as a non-empty string.",
    }
    assert payload["results"][1]["ok"] is True
    assert payload["results"][2] == {
        "index": 2,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].category` entry: expected a non-empty string.",
        "hint": "Pass `entries[].category` as a non-empty string.",
    }
    assert payload["results"][3] == {
        "index": 3,
        "ok": False,
        "id": None,
        "error_type": "validation_error",
        "message": "Invalid `entries[].category` entry: expected a non-empty string.",
        "hint": "Pass `entries[].category` as a non-empty string.",
    }
    assert len(list((tmp_memory_dir / "values").glob("*.md"))) == 1


def test_memory_values_add_respects_batch_limit_and_env_override(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    monkeypatch.setenv("AGENTIC_MEMORY_MAX_BATCH_SIZE", "100")

    hundred_entries = [
        {"description": f"Prefer item {index}", "category": "workflow"} for index in range(100)
    ]
    allowed = _values_add_payload(tmp_memory_dir, hundred_entries)
    assert allowed["ok"] is True
    assert allowed["success_count"] == 100
    assert allowed["error_count"] == 0

    oversize = _values_add_payload(
        tmp_memory_dir,
        hundred_entries + [{"description": "Prefer overflow", "category": "workflow"}],
    )
    assert oversize["ok"] is False
    assert oversize["error_type"] == "validation_error"
    assert oversize["message"] == (
        "Batch size 101 exceeds maximum 100 (configurable via AGENTIC_MEMORY_MAX_BATCH_SIZE)"
    )

    empty = _values_add_payload(tmp_memory_dir, [])
    assert empty["ok"] is False
    assert empty["error_type"] == "validation_error"
    assert empty["message"] == "Batch cannot be empty"


def test_memory_values_search_and_list_behaviors(tmp_memory_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    payload = json.loads(memory_values_search(memory_dir=str(tmp_memory_dir)))
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["message"] == "At least one of 'query' or 'category' must be provided."

    _values_add_payload(
        tmp_memory_dir,
        [
            {
                "description": "Add regression tests for bug fixes",
                "category": "review",
                "confidence": 0.9,
            },
            {
                "description": "Document release checklist",
                "category": "workflow",
                "confidence": 0.8,
            },
        ],
    )

    search_payload = json.loads(
        memory_values_search(
            query="regression tests",
            min_confidence=0.5,
            top=5,
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert search_payload["ok"] is True
    assert search_payload["entries"][0]["description"] == "Add regression tests for bug fixes"
    assert search_payload["entries"][0]["score"] > 0

    promoted_entry = _seed_promoted_entry(
        tmp_memory_dir,
        description="Prefer reversible schema migrations",
    )
    list_payload = json.loads(
        memory_values_list(
            promoted_only=True,
            top=10,
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert list_payload["ok"] is True
    assert len(list_payload["entries"]) == 1
    assert list_payload["entries"][0]["id"] == str(promoted_entry.id)


def test_memory_values_search_category_only_returns_zero_score(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    _values_add_payload(
        tmp_memory_dir,
        [
            {
                "description": "Prefer review checklists for releases",
                "category": "review",
                "confidence": 0.9,
            },
            {
                "description": "Prefer architecture docs before refactors",
                "category": "review",
                "confidence": 0.6,
            },
            {
                "description": "Automate deploy announcements",
                "category": "workflow",
                "confidence": 0.95,
            },
        ],
    )

    payload = json.loads(memory_values_search(category="review", memory_dir=str(tmp_memory_dir)))

    assert payload["ok"] is True
    assert [entry["score"] for entry in payload["entries"]] == [0.0, 0.0]
    assert [entry["confidence"] for entry in payload["entries"]] == [0.9, 0.6]


def test_memory_values_search_supports_cjk_full_content_and_toggle(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)

    created = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [
                {
                    "description": "コードレビュー観点を標準化する",
                    "category": "review",
                    "confidence": 0.9,
                    "evidence": [_evidence(1)],
                }
            ],
        )
    )

    exact_payload = json.loads(
        memory_values_search(query="レビュー", memory_dir=str(tmp_memory_dir))
    )
    assert exact_payload["ok"] is True
    assert exact_payload["entries"][0]["id"] == created["id"]
    assert "evidence" not in exact_payload["entries"][0]

    expanded_payload = json.loads(
        memory_values_search(query="レビュー観点集", memory_dir=str(tmp_memory_dir))
    )
    assert expanded_payload["ok"] is True
    assert expanded_payload["entries"][0]["id"] == created["id"]

    disabled_payload = json.loads(
        memory_values_search(
            query="レビュー観点集",
            no_cjk_expand=True,
            memory_dir=str(tmp_memory_dir),
        )
    )
    assert disabled_payload == {"entries": [], "ok": True}

    full_payload = json.loads(
        memory_values_search(
            query="レビュー",
            include_full_content=True,
            memory_dir=str(tmp_memory_dir),
        )
    )
    entry = full_payload["entries"][0]
    assert entry["evidence"] == [_evidence(1)]
    assert "source_type" in entry
    assert "created_at" in entry
    assert "updated_at" in entry


def test_memory_values_update_validates_missing_fields_and_add_evidence_shape(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    added = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [{"description": "Prefer explicit evidence batches", "category": "workflow"}],
        )
    )

    missing_fields = _single_result(_values_update_payload(tmp_memory_dir, [{"id": added["id"]}]))
    assert missing_fields["ok"] is False
    assert missing_fields["id"] == added["id"]
    assert missing_fields["error_type"] == "validation_error"
    assert missing_fields["message"] == (
        "At least one update field is required (confidence, add_evidence, description)"
    )

    invalid_shape = _single_result(
        _values_update_payload(
            tmp_memory_dir,
            [{"id": added["id"], "add_evidence": cast(Any, _evidence(1))}],
        )
    )
    assert invalid_shape["ok"] is False
    assert invalid_shape["error_type"] == "validation_error"
    assert invalid_shape["message"] == "`add_evidence` must be a list of evidence objects."


def test_memory_values_update_isolates_missing_id_and_emits_notifications(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    candidate = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [
                {
                    "description": "Require regression coverage for bug fixes",
                    "category": "review",
                    "confidence": 0.8,
                    "evidence": [_evidence(index) for index in range(1, 5)],
                }
            ],
        )
    )
    promoted_entry = _seed_promoted_entry(
        tmp_memory_dir,
        description="Prefer reversible schema migrations",
    )
    secret_entry = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [{"description": "Prefer documented secret handling", "category": "security"}],
        )
    )

    payload = _values_update_payload(
        tmp_memory_dir,
        [
            {"id": candidate["id"], "add_evidence": [_evidence(5)]},
            {"id": str(promoted_entry.id), "confidence": 0.7},
            {
                "id": secret_entry["id"],
                "description": 'Prefer documenting auth_token="AbCdEf1234567890" handling',
            },
            {"id": "v-11111111-1111-1111-1111-111111111111", "confidence": 0.4},
        ],
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 3
    assert payload["error_count"] == 1
    assert payload["results"][0]["updated_fields"] == ["evidence"]
    assert payload["results"][0]["promotion_candidate"] is True
    assert payload["results"][1]["updated_fields"] == ["confidence"]
    assert payload["results"][1]["demotion_candidate"] is True
    assert payload["results"][2]["updated_fields"] == ["description"]
    assert payload["results"][2]["warnings"] == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]
    assert payload["results"][3] == {
        "index": 3,
        "ok": False,
        "id": "v-11111111-1111-1111-1111-111111111111",
        "error_type": "not_found",
        "message": "Values entry not found: v-11111111-1111-1111-1111-111111111111",
        "hint": "Verify the values `id` exists before retrying.",
    }


def test_memory_values_promote_bulk_preview_confirm_and_isolation(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    agents_path.write_text(
        "# Agent Rules\n\n<!-- BEGIN:PROMOTED_VALUES -->\n<!-- END:PROMOTED_VALUES -->\n",
        encoding="utf-8",
    )

    promotable = _values_add_payload(
        tmp_memory_dir,
        [
            {
                "description": "Prefer focused reversible changes",
                "category": "workflow",
                "confidence": 0.85,
                "evidence": [_evidence(index) for index in range(1, 6)],
            },
            {
                "description": "Prefer explicit rollback plans",
                "category": "workflow",
                "confidence": 0.9,
                "evidence": [_evidence(index) for index in range(6, 11)],
            },
            {
                "description": "Prefer shipping ineligible promoted values",
                "category": "workflow",
                "confidence": 0.7,
                "evidence": [_evidence(index) for index in range(1, 5)],
            },
        ],
    )
    ids = [result["id"] for result in promotable["results"] if result["ok"]]

    preview = _values_promote_payload(tmp_memory_dir, [ids[0], ids[1], ids[2]], confirm=False)
    assert preview["ok"] is True
    assert preview["success_count"] == 2
    assert preview["error_count"] == 1
    assert preview["results"][0]["would_promote"] is True
    assert preview["results"][1]["would_promote"] is True
    assert preview["results"][2]["ok"] is False
    assert agents_path.read_text(encoding="utf-8").count("- [") == 0

    confirmed = _values_promote_payload(tmp_memory_dir, [ids[0], ids[1]], confirm=True)
    assert confirmed["ok"] is True
    assert confirmed["success_count"] == 2
    assert confirmed["error_count"] == 0
    assert all(result["promoted"] is True for result in confirmed["results"])
    agents_text = agents_path.read_text(encoding="utf-8")
    assert ids[0] in agents_text
    assert ids[1] in agents_text


def test_memory_values_promote_bulk_reports_missing_agents_md_per_item(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    promotable = _values_add_payload(
        tmp_memory_dir,
        [
            {
                "description": "Prefer focused reversible changes",
                "category": "workflow",
                "confidence": 0.85,
                "evidence": [_evidence(index) for index in range(1, 6)],
            },
            {
                "description": "Prefer explicit rollback plans",
                "category": "workflow",
                "confidence": 0.9,
                "evidence": [_evidence(index) for index in range(6, 11)],
            },
        ],
    )
    promotable_ids = [result["id"] for result in promotable["results"] if result["ok"]]

    payload = _values_promote_payload(
        tmp_memory_dir,
        [promotable_ids[0], "v-11111111-1111-1111-1111-111111111111", promotable_ids[1]],
        confirm=True,
    )

    assert payload["ok"] is True
    assert payload["success_count"] == 0
    assert payload["error_count"] == 3
    assert payload["results"][0] == {
        "index": 0,
        "ok": False,
        "id": promotable_ids[0],
        "error_type": "not_found",
        "message": "AGENTS.md not found",
        "hint": (
            "Set `AGENTS_MD_PATH` or place `AGENTS.md` / `CLAUDE.md` next to the memory directory."
        ),
    }
    assert payload["results"][1] == {
        "index": 1,
        "ok": False,
        "id": "v-11111111-1111-1111-1111-111111111111",
        "error_type": "not_found",
        "message": "Values entry not found: v-11111111-1111-1111-1111-111111111111",
        "hint": "Verify the values `id` exists before retrying.",
    }
    assert payload["results"][2]["message"] == "AGENTS.md not found"


def test_memory_values_demote_bulk_preview_confirm_and_isolation(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    promoted_one = _seed_promoted_entry(
        tmp_memory_dir,
        description="Prefer reversible schema migrations",
    )
    promoted_two = _seed_promoted_entry(
        tmp_memory_dir,
        description="Prefer explicit rollback plans",
    )
    unpromoted = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [{"description": "Prefer draft PRs for large work", "category": "review"}],
        )
    )
    agents_path.write_text(
        "# Agent Rules\n\n"
        "<!-- BEGIN:PROMOTED_VALUES -->\n"
        f"- [{promoted_one.id}] {promoted_one.description}\n"
        f"- [{promoted_two.id}] {promoted_two.description}\n"
        "<!-- END:PROMOTED_VALUES -->\n",
        encoding="utf-8",
    )

    preview = _values_demote_payload(
        tmp_memory_dir,
        [str(promoted_one.id), str(promoted_two.id), unpromoted["id"]],
        reason="confidence dropped",
        confirm=False,
    )
    assert preview["ok"] is True
    assert preview["success_count"] == 2
    assert preview["error_count"] == 1
    assert preview["results"][0]["would_demote"] is True
    assert preview["results"][1]["would_demote"] is True
    assert preview["results"][2] == {
        "index": 2,
        "ok": False,
        "id": unpromoted["id"],
        "error_type": "state_error",
        "message": f"Values entry is not promoted: {unpromoted['id']}",
        "hint": "This entry is not currently promoted. No demotion is needed.",
    }
    assert agents_path.read_text(encoding="utf-8").count("- [") == 2

    confirmed = _values_demote_payload(
        tmp_memory_dir,
        [str(promoted_one.id), str(promoted_two.id)],
        reason="confidence dropped",
        confirm=True,
    )
    assert confirmed["ok"] is True
    assert confirmed["success_count"] == 2
    assert confirmed["error_count"] == 0
    assert all(result["promoted"] is False for result in confirmed["results"])
    agents_text = agents_path.read_text(encoding="utf-8")
    assert str(promoted_one.id) not in agents_text
    assert str(promoted_two.id) not in agents_text


def test_memory_values_delete_bulk_preview_confirm_and_agents_cleanup(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    agents_path = tmp_memory_dir.parent / "AGENTS.md"
    added = _single_result(
        _values_add_payload(
            tmp_memory_dir,
            [{"description": "Prefer focused diffs", "category": "workflow"}],
        )
    )
    promoted = _seed_promoted_entry(
        tmp_memory_dir,
        description="Prefer reversible schema migrations",
    )
    agents_path.write_text(
        "# Agent Rules\n\n"
        "<!-- BEGIN:PROMOTED_VALUES -->\n"
        f"- [{promoted.id}] {promoted.description}\n"
        "<!-- END:PROMOTED_VALUES -->\n",
        encoding="utf-8",
    )

    preview = _values_delete_payload(tmp_memory_dir, [added["id"], str(promoted.id)])
    assert preview["ok"] is True
    assert preview["success_count"] == 2
    assert preview["error_count"] == 0
    assert preview["results"][0]["would_delete"] is True
    assert preview["results"][1]["would_delete"] is True
    assert ValuesRepository(tmp_memory_dir).find_by_id(added["id"]) is not None
    assert str(promoted.id) in agents_path.read_text(encoding="utf-8")

    confirmed = _values_delete_payload(
        tmp_memory_dir,
        [added["id"], str(promoted.id), "v-11111111-1111-1111-1111-111111111111"],
        confirm=True,
        reason="cleanup duplicate value",
    )
    assert confirmed["ok"] is True
    assert confirmed["success_count"] == 2
    assert confirmed["error_count"] == 1
    assert confirmed["results"][0] == {
        "index": 0,
        "ok": True,
        "id": added["id"],
        "deleted_id": added["id"],
        "description": "Prefer focused diffs",
        "deleted": True,
        "was_promoted": False,
        "reason": "cleanup duplicate value",
    }
    assert confirmed["results"][1]["was_promoted"] is True
    assert confirmed["results"][1]["deleted"] is True
    assert confirmed["results"][2]["ok"] is False
    assert ValuesRepository(tmp_memory_dir).find_by_id(added["id"]) is None
    assert ValuesRepository(tmp_memory_dir).find_by_id(promoted.id) is None
    assert str(promoted.id) not in agents_path.read_text(encoding="utf-8")


def test_memory_values_delete_promoted_missing_markers_reports_memory_init_hint(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    promoted = _seed_promoted_entry(
        tmp_memory_dir,
        description="Prefer reversible schema migrations",
    )
    (tmp_memory_dir.parent / "AGENTS.md").write_text("# Agent Rules\n", encoding="utf-8")

    payload = _values_delete_payload(tmp_memory_dir, [str(promoted.id)], confirm=True)

    assert payload["ok"] is True
    assert payload["success_count"] == 0
    assert payload["error_count"] == 1
    assert payload["results"][0] == {
        "index": 0,
        "ok": False,
        "id": str(promoted.id),
        "error_type": "validation_error",
        "message": (
            "AGENTS.md is missing promoted values markers. Run memory_init to recreate them."
        ),
        "hint": "Run `memory_init` to recreate AGENTS.md markers, then retry deletion.",
    }


def test_memory_values_promote_rejects_secret_containing_entry(
    tmp_memory_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_memory_dir.parent)
    entry, warnings = ValuesService().add(
        tmp_memory_dir,
        description='Prefer sharing api_key="AbCdEf1234567890" in chat',
        category="security",
        confidence=0.85,
        evidence=[_evidence(index) for index in range(1, 6)],
    )
    assert warnings == [
        "Content may contain secrets (detected: generic_api_token). Review before sharing."
    ]

    payload = _single_result(
        _values_promote_payload(tmp_memory_dir, [str(entry.id)], confirm=False)
    )
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["message"] == "Cannot promote value containing potential secrets"
