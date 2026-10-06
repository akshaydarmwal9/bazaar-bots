"""The offer ledger: the arena's record of every real offer.

Sellers use it to check whether a buyer's "another store offered me X" claim is true.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ..models import Offer


class Ledger:
    def __init__(self, verify_claims: bool = True) -> None:
        self.verify_claims = verify_claims  # False = sellers must trust buyer claims
        self.offers: list[Offer] = []
        self._best_seller_price: dict[str, dict[str, int]] = defaultdict(dict)

    def record(self, offer: Offer, product_id: str) -> None:
        self.offers.append(offer)
        if offer.sender == "seller" and offer.price is not None:
            current = self._best_seller_price[product_id].get(offer.store_id)
            if current is None or offer.price < current:
                self._best_seller_price[product_id][offer.store_id] = offer.price

    def best_rival_price(self, product_id: str, exclude_store: str) -> Optional[tuple[str, int]]:
        """Lowest real seller price for this product from any *other* store."""
        rivals = {
            s: p for s, p in self._best_seller_price[product_id].items() if s != exclude_store
        }
        if not rivals:
            return None
        store = min(rivals, key=rivals.get)
        return store, rivals[store]

    def verify_claim(self, product_id: str, claim_store: Optional[str], claim_price: int) -> bool:
        """True if some rival (or the named rival) really offered claim_price or lower."""
        if not self.verify_claims:
            return True
        prices = self._best_seller_price[product_id]
        if claim_store and claim_store in prices:
            return prices[claim_store] <= claim_price * 1.01
        return any(p <= claim_price * 1.01 for p in prices.values())
