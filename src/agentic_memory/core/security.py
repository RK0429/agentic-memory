from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecretMatch:
    pattern_name: str
    matched_text: str
    position: int


@dataclass(frozen=True, slots=True)
class _PatternRule:
    name: str
    regex: re.Pattern[str]
    group: int = 0


class SecretScanPolicy:
    _PATTERNS = (
        _PatternRule(
            name="aws_access_key",
            regex=re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        ),
        _PatternRule(
            name="github_pat",
            regex=re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,255}\b"),
        ),
        _PatternRule(
            name="pem_private_key",
            regex=re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
        ),
        _PatternRule(
            name="slack_token",
            regex=re.compile(r"\bxox(?:b|p)-[A-Za-z0-9-]{10,}\b"),
        ),
        _PatternRule(
            name="generic_api_token",
            regex=re.compile(
                r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|token)\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})"
            ),
            group=1,
        ),
        _PatternRule(
            name="ai_service_api_key",
            regex=re.compile(
                r"\b(?:sk-ant-(?:api\d+-)?|sk_live_|sk_test_|sk-proj-)[A-Za-z0-9_\-]{16,}\b"
            ),
        ),
        _PatternRule(
            name="high_entropy_string",
            regex=re.compile(r"\b[A-Za-z0-9][A-Za-z0-9/_+=-]{31,}\b"),
        ),
    )

    @classmethod
    def scan(cls, text: str) -> list[SecretMatch]:
        matches: list[SecretMatch] = []
        seen: set[tuple[str, int, str]] = set()
        for rule in cls._PATTERNS:
            for match in rule.regex.finditer(text):
                start = match.start(rule.group)
                value = match.group(rule.group)
                if rule.name == "high_entropy_string" and not cls._is_high_entropy_candidate(value):
                    continue
                dedupe_key = (rule.name, start, value)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                matches.append(
                    SecretMatch(
                        pattern_name=rule.name,
                        matched_text=value,
                        position=start,
                    )
                )
        return matches

    @classmethod
    def contains_secret(cls, text: str) -> bool:
        return bool(cls.scan(text))

    @staticmethod
    def _is_high_entropy_candidate(value: str) -> bool:
        if len(value) < 32:
            return False
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            return False
        if value.lower() == value or value.upper() == value:
            return False

        counts: dict[str, int] = {}
        for char in value:
            counts[char] = counts.get(char, 0) + 1

        entropy = 0.0
        length = len(value)
        for count in counts.values():
            probability = count / length
            entropy -= probability * math.log2(probability)
        return entropy >= 3.5


__all__ = ["SecretMatch", "SecretScanPolicy"]
