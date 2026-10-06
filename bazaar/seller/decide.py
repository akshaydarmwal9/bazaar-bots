"""Seller decision logic: plain Python, no LLM.

The floor price lives only here. The LLM that writes the seller's messages
never sees it, so it can't leak it, however cleverly the buyer asks.
"""
from __future__ import annotations

from typing import Optional

from ..arena.ledger import Ledger
from ..models import Extra, Offer, Product, Store

# How fast each personality concedes along the curve (k > 1 = holds firm, concedes late).
CURVE_K = {"friendly": 0.6, "stubborn": 2.2, "festival_sale": 2.5, "upseller": 1.2}

LOWBALL_FRACTION = 0.5  # offers below 50% of list price are insults
MAX_INSULTS = 2  # second insult ends the negotiation


def r10(x: float) -> int:
    return int(round(x / 10.0)) * 10


class SellerBrain:
    def __init__(self, store: Store, product: Product, max_rounds: int = 6) -> None:
        self.store = store
        self.p = product
        self.max_rounds = max_rounds
        self.current_ask = self.opening_price()
        self.insults = 0
        self.last_buyer_price: Optional[int] = None
        self.used_walkaway_concession = False
        self.bluffs_caught = 0
        self.extras_given: list[Extra] = []

    # ---------- helpers ----------
    def opening_price(self) -> int:
        if self.store.personality == "festival_sale":
            return max(self.p.floor_price, r10(self.p.list_price * 0.85))
        return self.p.list_price

    def _floor_clamp(self, price: float) -> int:
        price = r10(price)
        if price < self.p.floor_price:
            price = self.p.floor_price
        return min(price, self.current_ask)

    def _curve_ask(self, round_no: int) -> float:
        L, F = self.p.list_price, self.p.floor_price
        k = CURVE_K.get(self.store.personality, 1.0)
        speed = 1.25 if self.p.stock > 100 else (0.8 if self.p.stock < 40 else 1.0)
        t = min(1.0, (round_no / self.max_rounds) * speed)
        ask = L - (L - F) * (t ** k)
        if self.store.personality == "festival_sale":
            ask = min(ask, self.opening_price())
        return ask

    def _maybe_extra(self, round_no: int) -> list[str]:
        near_floor = (self.current_ask - self.p.floor_price) <= 0.06 * self.p.list_price
        wants = near_floor or (self.store.personality == "upseller" and round_no >= 2)
        if not wants:
            return []
        for extra in self.store.extras:
            if extra not in self.extras_given:
                self.extras_given.append(extra)
                break
        return [e.item for e in self.extras_given]

    def _offer(self, round_no: int, action: str, price: Optional[int], note: str, extras=None) -> Offer:
        return Offer(
            sender="seller",
            store_id=self.store.store_id,
            round=round_no,
            action=action,
            price=price,
            extras=extras if extras is not None else [e.item for e in self.extras_given],
            note=note,
        )

    # ---------- main entry points ----------
    def open(self) -> Offer:
        note = "festival discount on the tag" if self.current_ask < self.p.list_price else "listed price"
        return self._offer(0, "counter", self.current_ask, note, extras=[])

    def respond(self, round_no: int, buyer: Offer, ledger: Ledger) -> Offer:
        L, F = self.p.list_price, self.p.floor_price

        # Fixed-price store: the control group.
        if not self.store.negotiates:
            if buyer.action == "accept":
                return self._offer(round_no, "accept", L, "fixed price accepted")
            return self._offer(round_no, "final", L, "fixed price, no bargaining")

        if buyer.action == "walk_away":
            return self._offer(round_no, "reject", None, "buyer left")

        if buyer.action == "accept":
            return self._offer(round_no, "accept", self.current_ask, "buyer accepted our price")

        # The classic bazaar move: buyer pretends to leave.
        if buyer.action == "fake_walk_away":
            if not self.used_walkaway_concession:
                self.used_walkaway_concession = True
                self.current_ask = self._floor_clamp(self.current_ask - 0.35 * (self.current_ask - F))
                return self._offer(round_no, "final", self.current_ask, "called buyer back with a last offer")
            return self._offer(round_no, "final", self.current_ask, "let the buyer go, holding price")

        price = buyer.price or 0

        # Lowball defense: ₹1 offers and "tell me your minimum" get nothing.
        if price < LOWBALL_FRACTION * L:
            self.insults += 1
            self.last_buyer_price = price
            if self.insults >= MAX_INSULTS:
                return self._offer(round_no, "walk_away", None, "second lowball, ended the chat")
            return self._offer(round_no, "counter", self.current_ask, "lowball, holding price")

        # Buyer already meets our ask.
        if price >= self.current_ask:
            return self._offer(round_no, "accept", self.current_ask, "buyer met our ask")

        # Close enough to our curve: take it.
        curve = self._curve_ask(round_no)
        if price >= F and price >= curve - 0.02 * L and round_no >= 2:
            self.current_ask = max(price, F)
            return self._offer(round_no, "accept", self.current_ask, "close to our target, accepted")

        # Reciprocity: we move only when the buyer moves.
        desired_drop = max(0.0, self.current_ask - curve)
        if self.last_buyer_price is None or self.last_buyer_price < LOWBALL_FRACTION * L:
            allowed = desired_drop
        else:
            allowed = 0.8 * max(0, price - self.last_buyer_price)
        drop = min(desired_drop, allowed)
        note = "conceded along our curve" if drop > 0 else "buyer didn't move, neither do we"
        self.last_buyer_price = price

        new_ask = self.current_ask - drop

        # Competitor claims: verify against the ledger.
        if buyer.claim_price:
            if not ledger.verify_claim(self.p.product_id, buyer.claim_store, buyer.claim_price):
                self.bluffs_caught += 1
                new_ask = self.current_ask  # no concession for a liar
                note = "bluff caught: no store offered that price"
            elif not self.store.price_match:
                note = "rival offer is real, but we don't price-match"
            elif buyer.claim_price >= F:
                new_ask = min(new_ask, buyer.claim_price - 50)
                note = "beat a real rival offer"
            else:
                new_ask = min(new_ask, F)
                note = "rival is cheaper than we can go"

        self.current_ask = self._floor_clamp(new_ask)
        extras = self._maybe_extra(round_no)

        at_floor = self.current_ask <= F
        last_round = round_no >= self.max_rounds
        if last_round and price >= F and price >= self.current_ask - 0.03 * L:
            self.current_ask = max(price, F)
            return self._offer(round_no, "accept", self.current_ask, "last round, accepted a fair offer")
        action = "final" if (at_floor or last_round or buyer.asks_minimum) else "counter"
        if buyer.asks_minimum and not at_floor:
            note += "; said 'final price' (it isn't)"
        return self._offer(round_no, action, self.current_ask, note, extras=extras)
