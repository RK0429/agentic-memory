"""Aggregate and analyze skill feedback signals in the memory index."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

SIGNAL_TYPES = ("success", "friction", "failure", "workaround", "gap")
NEGATIVE_TYPES = ("friction", "failure", "workaround", "gap")
WEIGHTS = {
    "failure": 3,
    "workaround": 2,
    "friction": 1,
    "gap": 1,
}


def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD string."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def load_index(index_path: Path) -> list[dict]:
    """Load _index.jsonl and return list of entries."""
    if not index_path.exists():
        raise FileNotFoundError(f"Index file not found: {index_path}")

    entries: list[dict] = []
    for lineno, raw_line in enumerate(
        index_path.read_text(encoding="utf-8", errors="ignore").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {lineno}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Invalid entry type at line {lineno}: expected object")
        entries.append(row)
    return entries


def aggregate_signals(entries: list[dict], since: str | None = None) -> dict:
    """Aggregate skill feedback signals by skill and type."""
    since_date = _parse_date(since) if since else None

    skills: dict[str, dict] = {}
    for entry in entries:
        entry_date_raw = entry.get("date")
        if since_date is not None:
            if not isinstance(entry_date_raw, str) or not entry_date_raw.strip():
                continue
            try:
                entry_date = _parse_date(entry_date_raw)
            except ValueError:
                continue
            if entry_date < since_date:
                continue

        feedbacks = entry.get("skill_feedback")
        if not isinstance(feedbacks, list):
            continue

        note_path = str(entry.get("path", ""))
        entry_date_text = str(entry_date_raw or "")
        for fb in feedbacks:
            if not isinstance(fb, dict):
                continue
            skill = fb.get("skill")
            signal_type = fb.get("type")
            if not isinstance(skill, str) or not skill.strip():
                continue
            if not isinstance(signal_type, str) or not signal_type.strip():
                continue

            skill = skill.strip()
            signal_type = signal_type.strip()
            desc = fb.get("desc")
            desc_text = desc if isinstance(desc, str) else ("" if desc is None else str(desc))

            if skill not in skills:
                skills[skill] = {
                    "success": 0,
                    "friction": 0,
                    "failure": 0,
                    "workaround": 0,
                    "gap": 0,
                    "total": 0,
                    "total_negative": 0,
                    "entries": [],
                }

            skill_data = skills[skill]
            if signal_type in SIGNAL_TYPES:
                skill_data[signal_type] += 1
            skill_data["total"] += 1
            skill_data["entries"].append(
                {
                    "date": entry_date_text,
                    "type": signal_type,
                    "desc": desc_text,
                    "note": note_path,
                }
            )

    for skill_data in skills.values():
        skill_data["total_negative"] = skill_data["total"] - skill_data["success"]

    return {
        "mode": "aggregate",
        "since": since,
        "skills": skills,
    }


def _severity(weighted_score: int) -> str:
    if weighted_score >= 8:
        return "high"
    if weighted_score >= 4:
        return "medium"
    if weighted_score >= 1:
        return "low"
    return "low"


def _action_for_severity(severity: str) -> str:
    if severity == "high":
        return "スキル定義またはガイドラインの見直しを推奨"
    if severity == "medium":
        return "フィードバックの傾向を確認し改善を検討"
    return "引き続き観察"


def _top_issues(entries: list[dict], limit: int = 5) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        desc = entry.get("desc", "")
        if not isinstance(desc, str):
            desc = str(desc)
        clean = desc.strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        issues.append(clean)
        if len(issues) >= limit:
            break
    return issues


def analyze_signals(aggregated: dict, threshold: int = 3) -> list[dict]:
    """Analyze aggregated signals and generate improvement candidates."""
    if threshold < 0:
        raise ValueError("threshold must be >= 0")

    skills = aggregated.get("skills", {})
    if not isinstance(skills, dict):
        return []

    candidates: list[dict] = []
    for skill, data in skills.items():
        if not isinstance(data, dict):
            continue
        total_negative = int(data.get("total_negative", 0))
        if total_negative < threshold:
            continue

        breakdown: dict[str, int] = {}
        for signal_type in NEGATIVE_TYPES:
            count = int(data.get(signal_type, 0))
            if count > 0:
                breakdown[signal_type] = count

        weighted_score = sum(int(data.get(k, 0)) * w for k, w in WEIGHTS.items())
        severity = _severity(weighted_score)
        issue_list = _top_issues(data.get("entries", []))
        detail_parts = [f"{signal_type}({count}件)" for signal_type, count in breakdown.items()]
        detail_text = " + ".join(detail_parts) if detail_parts else "no-negative-signals(0件)"

        candidates.append(
            {
                "skill": skill,
                "weighted_score": weighted_score,
                "severity": severity,
                "total_negative": total_negative,
                "breakdown": breakdown,
                "top_issues": issue_list,
                "suggestion": f"{detail_text} — {_action_for_severity(severity)}",
            }
        )

    candidates.sort(
        key=lambda item: (
            -int(item.get("weighted_score", 0)),
            -int(item.get("total_negative", 0)),
            str(item.get("skill", "")),
        )
    )
    return candidates


def check_improvement_triggers(
    entries: list[dict],
    candidates: list[dict],
    existing_backlog_texts: list[str] | None = None,
) -> list[dict]:
    """Check for improvement triggers beyond simple severity thresholds.

    Triggers:
    - periodic_review: dynamic threshold met and no recent [periodic_review] in backlog
    - pattern_escalation: medium candidate with friction+workaround >= 3
    - gap_expansion: same skill has gap count >= 2

    Args:
        entries: Raw index entries (from load_index).
        candidates: Output of analyze_signals().
        existing_backlog_texts: Normalized backlog texts for dedup (optional).

    Returns:
        List of trigger dicts: {"type", "skill", "detail", "severity"}.
    """
    backlog = {t.lower() for t in (existing_backlog_texts or [])}
    triggers: list[dict] = []

    # periodic_review: dynamic threshold + cooldown check
    periodic_threshold = max(10, len(entries) // 5)
    has_recent_review = False
    for t in backlog:
        if "[periodic_review]" not in t:
            continue
        has_recent_review = True
        # Check if the existing periodic_review entry has a date within 14 days
        date_match = re.search(r"\[(\d{4}-\d{2}-\d{2})", t)
        if date_match:
            try:
                review_date = date.fromisoformat(date_match.group(1))
                days_since = (date.today() - review_date).days
                if days_since < 14:
                    has_recent_review = True
                    break
                else:
                    has_recent_review = False  # Old review, allow new one
            except ValueError:
                pass

    if len(entries) >= periodic_threshold and not has_recent_review:
        triggers.append(
            {
                "type": "periodic_review",
                "skill": "*",
                "detail": f"インデックスに{len(entries)}件のエントリ — 全スキル定期レビューを推奨",
                "severity": "medium",
            }
        )

    for cand in candidates:
        severity = cand.get("severity", "")
        skill = cand.get("skill", "")
        breakdown = cand.get("breakdown", {})

        # pattern_escalation: medium with friction+workaround >= 3
        if severity == "medium":
            friction = int(breakdown.get("friction", 0))
            workaround = int(breakdown.get("workaround", 0))
            if friction + workaround >= 3:
                triggers.append(
                    {
                        "type": "pattern_escalation",
                        "skill": skill,
                        "detail": (
                            f"friction({friction})+workaround({workaround})の蓄積パターンを検出"
                        ),
                        "severity": "medium",
                    }
                )

        # gap_expansion: gap count >= 2 for same skill
        gap_count = int(breakdown.get("gap", 0))
        if gap_count >= 2:
            triggers.append(
                {
                    "type": "gap_expansion",
                    "skill": skill,
                    "detail": f"gap({gap_count}件) — 新モジュール拡張の候補",
                    "severity": "medium",
                }
            )

    return triggers


def format_report(aggregated: dict, candidates: list[dict]) -> str:
    """Format human-readable report from aggregation and analysis."""
    lines: list[str] = []
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    threshold = int(aggregated.get("threshold", 3))

    lines.append("=== Skill Feedback Report ===")
    lines.append(f"Generated: {generated}")
    lines.append("")
    lines.append("--- Aggregation ---")

    skills = aggregated.get("skills", {})
    if isinstance(skills, dict) and skills:
        sorted_skills = sorted(
            skills.items(),
            key=lambda item: (
                -int(item[1].get("total_negative", 0)),
                -int(item[1].get("total", 0)),
                str(item[0]),
            ),
        )
        for skill, data in sorted_skills:
            parts = []
            for signal_type in SIGNAL_TYPES:
                count = int(data.get(signal_type, 0))
                if count > 0:
                    parts.append(f"{signal_type}={count}")
            if not parts:
                parts.append("no-signals")
            lines.append(
                f"{skill}: {', '.join(parts)} (total_negative={int(data.get('total_negative', 0))})"
            )
    else:
        lines.append("No skill feedback entries.")

    lines.append("")
    lines.append(f"--- Improvement Candidates (threshold={threshold}) ---")
    if not candidates:
        lines.append("No improvement candidates found.")
        return "\n".join(lines)

    for cand in candidates:
        severity = str(cand.get("severity", "low")).upper()
        skill = str(cand.get("skill", ""))
        score = int(cand.get("weighted_score", 0))
        negative = int(cand.get("total_negative", 0))
        lines.append(f"[{severity}] {skill} (score={score}, negative={negative})")

        breakdown = cand.get("breakdown", {})
        if isinstance(breakdown, dict) and breakdown:
            lines.append(
                "  "
                + " + ".join(f"{signal_type}({count})" for signal_type, count in breakdown.items())
            )
        else:
            lines.append("  no-negative-signals(0)")

        issues = cand.get("top_issues", [])
        if isinstance(issues, list) and issues:
            lines.append("  Top issues:")
            for issue in issues:
                lines.append(f"    - {issue}")

        lines.append(f"  Suggestion: {cand.get('suggestion', '')}")
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
