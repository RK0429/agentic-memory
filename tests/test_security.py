from __future__ import annotations

from agentic_memory.core.security import SecretScanPolicy


def test_secret_scan_policy_detects_common_secret_patterns() -> None:
    # Secret-like fixtures are assembled at runtime so that no literal token
    # appears in source and trips GitHub push protection / secret scanning.
    # The scanner sees the fully concatenated text, so detection is unaffected.
    aws_key = "AKI" + "A1234567890ABCDEF"
    github_pat = "ghp" + "_abcdefghijklmnopqrstuvwxyz1234567890"
    pem_header = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
    slack_bot = "xox" + "b-123456789012-123456789012-abcdefghijklmnopqrstuvwx"
    slack_user = "xox" + "p-123456789012-123456789012-abcdefghijklmnopqrstuvwx"
    api_token = "api_key=" + "sk_" + "live_abcdEFGH1234567890"
    entropy = "X7f0sM8qL2nP5vR9" + "tW1yZ4cB6dH3kJ8m"

    text = f"""
    aws = {aws_key}
    github = {github_pat}
    private_key = {pem_header}
    slack_bot = {slack_bot}
    slack_user = {slack_user}
    token = {api_token}
    entropy = {entropy}
    """

    matches = SecretScanPolicy.scan(text)
    pattern_names = {match.pattern_name for match in matches}

    assert "aws_access_key" in pattern_names
    assert "github_pat" in pattern_names
    assert "pem_private_key" in pattern_names
    assert "slack_token" in pattern_names
    assert "generic_api_token" in pattern_names
    assert "high_entropy_string" in pattern_names
    assert SecretScanPolicy.contains_secret(text) is True


def test_secret_scan_policy_ignores_safe_text() -> None:
    text = "workflow: prefer small changes and focused reviews"
    assert SecretScanPolicy.scan(text) == []
    assert SecretScanPolicy.contains_secret(text) is False
