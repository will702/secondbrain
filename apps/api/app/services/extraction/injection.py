"""Deterministic prompt-injection detector (SECURITY.md §9.3).

Flags document content that tries to steer agents. Flagged documents are
still processed as DATA (extraction continues — the attempt itself is a fact),
but they are surfaced for review and their extraction results get extra
scrutiny: nothing they contain can ever become an action.
"""

import re

INJECTION_PATTERNS = [
    re.compile(r"ignore (all|any|the)? ?(previous|prior|above|earlier|initial)? ?instructions", re.I),
    re.compile(r"disregard (all|any|your)? ?(previous|prior|above)? ?instructions", re.I),
    re.compile(r"you are now (a|an|the)\b", re.I),
    re.compile(r"(send|forward|email) (this|it|everything|all|every email)", re.I),
    re.compile(r"\b(system|developer|assistant) (prompt|message|instructions)\b", re.I),
    re.compile(r"reveal (your|the) (instructions|prompt|rules|credentials)", re.I),
    re.compile(r"<\|?(im_start|im_end|system|assistant)\|?>", re.I),
    re.compile(r"(act|behave|pretend) as (if you are|a different)", re.I),
    re.compile(r"override (your|the) (rules|policy|policies|settings)", re.I),
    re.compile(r"curl\s+https?://|wget\s+https?://", re.I),
]


def detect_injection(text: str) -> list[str]:
    """Returns a list of human-readable flags (empty = clean)."""
    flags: list[str] = []
    for pattern in INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            flags.append(f"instruction-like content: {match.group(0)!r}")
    return flags
