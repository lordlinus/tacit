"""Token estimation for the benchmark.

A deterministic heuristic (no network, no model download) applied identically
to both arms of the experiment, so the *ratio* between cold and warm is fair
even if absolute counts drift a few percent from a real tokenizer. Calibrated
to cl100k-family tokenizers on English prose + code: ~4 chars/token prose,
denser for code/punctuation.
"""

from __future__ import annotations

import re

_WORD_OR_SYMBOL = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    pieces = _WORD_OR_SYMBOL.findall(text)
    tokens = 0
    for piece in pieces:
        if piece.isalnum() or "_" in piece:
            # Long identifiers/words split into ~4-char subword units.
            tokens += max(1, (len(piece) + 3) // 4)
        else:
            tokens += 1  # each symbol is roughly one token
    return tokens
