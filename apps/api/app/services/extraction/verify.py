"""Quote verification: the cheap hallucination wall (AI_SYSTEM.md §3).

Every LLM-extracted fact must carry a quote copied from its source chunk.
A fact whose quote cannot be found in the chunk (normalized substring or
fuzzy window match) is rejected — it was invented.
"""

import difflib
import re


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def quote_in_text(quote: str, text: str, min_ratio: float = 0.8) -> bool:
    if not quote or not text:
        return False
    norm_quote = _normalize(quote)
    norm_text = _normalize(text)
    if not norm_quote:
        return False
    if norm_quote in norm_text:
        return True
    # Fuzzy fallback: compare against sliding windows of similar length.
    words = norm_text.split()
    quote_words = norm_quote.split()
    window = len(quote_words)
    if window == 0 or window > len(words):
        return False
    best = 0.0
    for start in range(0, len(words) - window + 1):
        candidate = " ".join(words[start : start + window])
        ratio = difflib.SequenceMatcher(None, norm_quote, candidate).ratio()
        if ratio > best:
            best = ratio
            if best >= 0.95:
                return True
    return best >= min_ratio
