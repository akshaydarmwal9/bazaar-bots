"""Hard rules enforced in plain Python. The LLM never decides money.

"The AI negotiates. The code enforces."
"""
from __future__ import annotations

import re

from ..models import Offer, Product


class GuardrailViolation(Exception):
    pass


def check_seller_offer(offer: Offer, product: Product) -> Offer:
    """A seller may never sell below its floor price."""
    if offer.price is not None and offer.price < product.floor_price:
        raise GuardrailViolation(
            f"seller offer {offer.price} below floor for {product.product_id}"
        )
    return offer


def check_buyer_offer(offer: Offer, budget: int) -> Offer:
    """A buyer may never commit above the shopper's budget."""
    if offer.action == "accept" and offer.price is not None and offer.price > budget:
        raise GuardrailViolation(f"buyer accepted {offer.price} above budget {budget}")
    if offer.action in ("counter", "fake_walk_away") and offer.price is not None and offer.price > budget:
        offer.price = budget  # offering more than the budget is never allowed
    return offer


def _numbers(text: str) -> set[int]:
    nums = set()
    for m in re.findall(r"\d[\d,]*", text):
        try:
            nums.add(int(m.replace(",", "")))
        except ValueError:
            pass
    return nums


def message_is_safe(message: str, private: set[int], allowed: set[int]) -> bool:
    """Reject LLM text that leaks private numbers or invents prices.

    private: numbers that must never appear (floor, cost, stock, buyer budget...).
    allowed: prices the code really used in this negotiation. Any other number
    of 100 or more is treated as an invented price and the message is rejected.
    """
    nums = _numbers(message)
    if nums & (private - allowed):
        return False
    return all(n < 100 or n in allowed for n in nums)


def seller_private_numbers(product: Product) -> set[int]:
    return {product.floor_price, product.target_price, product.cost_price, product.stock}
