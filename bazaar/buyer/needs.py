"""Turn a shopper's plain-English request into structured needs."""
from __future__ import annotations

import json
import re
from typing import Optional

from ..config import load_catalog
from ..models import ShopperNeeds


def _parse_number(text: str) -> Optional[int]:
    m = re.search(r"(?:₹|rs\.?|inr|under|below|budget|max)\s*([\d,]+)\s*(k)?", text, re.I)
    if not m:
        m = re.search(r"([\d,]{3,})\s*(k)?", text, re.I)
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    if m.group(2):
        n *= 1000
    return n


def _parse_days(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*days?", text, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"tomorrow", text, re.I):
        return 1
    if re.search(r"this week|by (friday|saturday|sunday)", text, re.I):
        return 4
    return None


def rule_based_needs(text: str) -> ShopperNeeds:
    catalog = load_catalog()
    low = text.lower()
    best_cat, best_hits, keywords = None, 0, []
    for info in catalog.values():
        hits = [k for k in info["keywords"] if k in low]
        if len(hits) > best_hits:
            best_cat, best_hits, keywords = info["category"], len(hits), hits
    if best_cat is None:
        best_cat = next(iter(catalog.values()))["category"]
    budget = _parse_number(text) or 100000
    return ShopperNeeds(raw=text, category=best_cat, keywords=keywords, budget=budget,
                        max_delivery_days=_parse_days(text))


def parse_needs(text: str, llm=None) -> ShopperNeeds:
    """Use the LLM if available, and fall back to rules if its answer is unusable."""
    fallback = rule_based_needs(text)
    if llm is None or llm.mode == "template":
        return fallback
    categories = sorted({v["category"] for v in load_catalog().values()})
    system = (
        "You extract shopping requirements. Reply with JSON only, no prose: "
        '{"category": one of ' + json.dumps(categories) + ', "budget": integer rupees, '
        '"max_delivery_days": integer or null}'
    )
    reply, _ = llm.complete(system, text, max_tokens=300)
    try:
        data = json.loads(re.search(r"\{.*\}", reply or "", re.S).group(0))
        cat = data.get("category")
        if cat not in categories:
            return fallback
        budget = int(data.get("budget") or fallback.budget)
        days = data.get("max_delivery_days")
        return ShopperNeeds(raw=text, category=cat, keywords=fallback.keywords, budget=budget,
                            max_delivery_days=int(days) if days else fallback.max_delivery_days)
    except Exception:
        return fallback
