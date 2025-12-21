"""
Offline GIF bank support for DjCap.

This module loads a small curated GIF bank (built from previous AudioApis /
DjCap Giphy responses) and exposes a helper for retrieving GIFs based on
keywords. It is used as a fallback when the live Giphy API is disabled or
returns no results.
"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Path to the offline GIF bank
GIF_BANK_PATH = Path(__file__).parent.parent / "data" / "gif_bank" / "gif_bank.json"

_GIF_BANK_LOADED = False
_GIF_BANK: List[Dict[str, Any]] = []


def _load_gif_bank() -> None:
    """Load the offline GIF bank into memory (once)."""
    global _GIF_BANK_LOADED, _GIF_BANK

    if _GIF_BANK_LOADED:
        return

    try:
        if not GIF_BANK_PATH.exists():
            logger.warning(f"GIF bank file not found at {GIF_BANK_PATH}")
            _GIF_BANK = []
            _GIF_BANK_LOADED = True
            return

        with open(GIF_BANK_PATH, "r") as f:
            data = json.load(f)

        gifs = data.get("gifs", [])

        # Normalise width/height to ints when possible
        for gif in gifs:
            for key in ("width", "height"):
                if key in gif and isinstance(gif[key], str) and gif[key].isdigit():
                    gif[key] = int(gif[key])

        _GIF_BANK = gifs
        _GIF_BANK_LOADED = True
        logger.info(f"Loaded {len(_GIF_BANK)} GIFs from offline bank")
    except Exception as e:
        logger.warning(f"Failed to load GIF bank from {GIF_BANK_PATH}: {e}")
        _GIF_BANK = []
        _GIF_BANK_LOADED = True


def get_offline_gifs(keywords: List[str], limit: int) -> List[Dict[str, Any]]:
    """
    Return GIFs from the offline bank that best match the provided keywords.

    Matching is intentionally simple: we score GIFs by counting how many of the
    keywords (case-insensitive) appear in the GIF's title or tags, and then
    return the best `limit` matches. If there are no matches, we fall back to
    random GIFs from the bank.
    """
    _load_gif_bank()

    if not _GIF_BANK:
        logger.info("Offline GIF bank is empty - no offline GIFs available")
        return []

    if not keywords:
        # Pure random fallback
        logger.info("No keywords provided for offline GIF bank, returning random GIFs")
        return random.sample(_GIF_BANK, min(limit, len(_GIF_BANK)))

    kw_lower = [kw.lower() for kw in keywords if kw]
    scored: List[tuple[int, Dict[str, Any]]] = []

    for gif in _GIF_BANK:
        title = (gif.get("title") or "").lower()
        tags = [t.lower() for t in gif.get("tags", []) if isinstance(t, str)]

        score = 0
        for kw in kw_lower:
            if kw in title:
                score += 2
            elif any(kw in tag for tag in tags):
                score += 1

        if score > 0:
            scored.append((score, gif))

    if scored:
        # Sort by score desc, then randomise within same score a bit
        random.shuffle(scored)
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [gif for _, gif in scored[:limit]]
        logger.info(
            f"Offline GIF bank: returning {len(selected)} GIFs for keywords {keywords}"
        )
        return selected

    # No scored matches, try partial/fuzzy matching before falling back to random
    # Try matching individual words from keywords
    partial_matches = []
    for gif in _GIF_BANK:
        title = (gif.get("title") or "").lower()
        tags = [t.lower() for t in gif.get("tags", []) if isinstance(t, str)]
        all_text = " ".join([title] + tags).lower()
        
        # Check if any keyword word appears in the text
        for kw in kw_lower:
            kw_words = kw.split()
            for kw_word in kw_words:
                if len(kw_word) > 3 and kw_word in all_text:  # Only match words > 3 chars
                    partial_matches.append(gif)
                    break
            if gif in partial_matches:
                break
    
    if partial_matches:
        # Remove duplicates while preserving order
        seen = set()
        unique_matches = []
        for gif in partial_matches:
            gif_id = gif.get("id")
            if gif_id and gif_id not in seen:
                seen.add(gif_id)
                unique_matches.append(gif)
        
        selected = unique_matches[:limit]
        logger.info(
            f"Offline GIF bank: no exact matches for {keywords}, "
            f"returning {len(selected)} partial matches"
        )
        return selected
    
    # No scored matches, fall back to random selection
    logger.info(
        f"Offline GIF bank: no matches for {keywords}, "
        f"returning random GIFs"
    )
    return random.sample(_GIF_BANK, min(limit, len(_GIF_BANK)))


__all__ = ["get_offline_gifs"]


