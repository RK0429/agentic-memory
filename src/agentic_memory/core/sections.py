"""Section aliases and caps for agentic-memory state/note parsing."""

from __future__ import annotations

# ノートセクション: 日本語名 → 英語名
NOTE_SECTION_ALIASES: dict[str, str] = {
    "目標": "Goal",
    "計画": "Plan",
    "作業ログ": "Work Log",
    "変更点": "Changes",
    "コマンド": "Commands",
    "検証": "Verification",
    "成果": "Outcome",
    "判断": "Decisions",
    "次のアクション": "Next",
    "注意点・残課題": "Pitfalls / Follow-ups",
    "想起フィードバック（任意）": "Recall feedback (optional)",
    "スキル候補": "Skill candidates",
    "スキルフィードバック": "Skill feedback",
}

# ステートセクション: 日本語名 → 英語名
STATE_SECTION_ALIASES: dict[str, str] = {
    "現在のフォーカス": "Current focus",
    "未解決・次のアクション": "Open threads / Next",
    "主要な判断": "Key decisions",
    "注意点": "Pitfalls",
    "スキルバックログ": "Skill backlog",
    "改善バックログ": "Improvement backlog",
}

# 逆引き辞書（自動生成）
_NOTE_REVERSE: dict[str, str] = {v: k for k, v in NOTE_SECTION_ALIASES.items()}
_STATE_REVERSE: dict[str, str] = {v: k for k, v in STATE_SECTION_ALIASES.items()}
_ALL_REVERSE: dict[str, str] = {**_NOTE_REVERSE, **_STATE_REVERSE}
_ALL_ALIASES: dict[str, str] = {**NOTE_SECTION_ALIASES, **STATE_SECTION_ALIASES}


def get_section(secs: dict[str, list[str]], name: str) -> list[str]:
    """Find section lines with Japanese priority and English fallback."""
    canonical = _ALL_REVERSE.get(name, name)
    if canonical in secs:
        return secs[canonical]
    alias = _ALL_ALIASES.get(canonical)
    if alias and alias in secs:
        return secs[alias]
    if name in secs:
        return secs[name]
    alt = _ALL_ALIASES.get(name) or _ALL_REVERSE.get(name)
    if alt and alt in secs:
        return secs[alt]
    return []


# ステートセクション ショートキー: ショートキー → 日本語正規名
STATE_SHORT_KEYS: dict[str, str] = {
    "focus": "現在のフォーカス",
    "open": "未解決・次のアクション",
    "decisions": "主要な判断",
    "pitfalls": "注意点",
    "skills": "スキルバックログ",
    "improvements": "改善バックログ",
}

# ステートセクション上限値
STATE_CAPS: dict[str, int] = {
    "focus": 3,
    "open": 8,
    "decisions": 8,
    "pitfalls": 8,
    "skills": 8,
    "improvements": 8,
}

# ショートキー逆引き（日本語名 → ショートキー、英語名 → ショートキー）
_SHORT_KEY_REVERSE: dict[str, str] = {}
for _sk, _ja in STATE_SHORT_KEYS.items():
    _SHORT_KEY_REVERSE[_ja] = _sk
    _en = STATE_SECTION_ALIASES.get(_ja)
    if _en:
        _SHORT_KEY_REVERSE[_en] = _sk


def resolve_short_key(key: str) -> str:
    """ショートキー / 日本語名 / 英語エイリアスから日本語正規名に解決。

    マッチなしの場合は ValueError を送出する。
    """
    # ショートキーそのまま
    if key in STATE_SHORT_KEYS:
        return STATE_SHORT_KEYS[key]
    # 日本語正規名そのまま
    if key in _SHORT_KEY_REVERSE:
        sk = _SHORT_KEY_REVERSE[key]
        return STATE_SHORT_KEYS[sk]
    # 大文字小文字を無視して検索
    key_lower = key.lower()
    for sk in STATE_SHORT_KEYS:
        if sk.lower() == key_lower:
            return STATE_SHORT_KEYS[sk]
    for name, sk in _SHORT_KEY_REVERSE.items():
        if name.lower() == key_lower:
            return STATE_SHORT_KEYS[sk]
    raise ValueError(f"Unknown section key: {key!r}")


def get_cap(key: str) -> int:
    """セクションキーから上限値を取得する。"""
    # ショートキーの場合
    if key in STATE_CAPS:
        return STATE_CAPS[key]
    # 日本語名 / 英語名の場合はショートキーに解決
    if key in _SHORT_KEY_REVERSE:
        sk = _SHORT_KEY_REVERSE[key]
        return STATE_CAPS[sk]
    raise ValueError(f"Unknown section key: {key!r}")
