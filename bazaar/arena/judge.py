"""Score finished deals on more than price: delivery, warranty, rating and freebies."""
from __future__ import annotations

from ..models import NegotiationResult, ShopperNeeds, Store


def score_deal(result: NegotiationResult, store: Store, needs: ShopperNeeds) -> float:
    """Higher is better. Roughly: value in rupees to the shopper."""
    extras_value = sum(e.value for e in store.extras if e.item in result.extras)
    late_days = 0
    if needs.max_delivery_days is not None:
        late_days = max(0, store.delivery_days - needs.max_delivery_days)
    return (
        -result.final_price
        + extras_value
        + 25 * store.warranty_months
        + 300 * (store.rating - 4.0)
        - 400 * late_days
    )


def rank(results: list[NegotiationResult], stores: dict[str, Store], needs: ShopperNeeds) -> list[NegotiationResult]:
    deals = [r for r in results if r.status in ("deal", "fixed_price") and r.final_price is not None
             and r.final_price <= needs.budget]
    for r in deals:
        r.score = round(score_deal(r, stores[r.store_id], needs), 1)
    return sorted(deals, key=lambda r: r.score, reverse=True)
