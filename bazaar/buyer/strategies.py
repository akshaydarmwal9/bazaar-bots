"""Buyer bargaining strategies: plain Python decisions, the LLM only phrases them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import Offer


def r10(x: float) -> int:
    return int(round(x / 10.0)) * 10


@dataclass
class Strategy:
    key: str
    label: str
    description: str
    open_frac: float  # opening offer as a fraction of list price
    concede_frac: float  # how much of the gap to close each round
    accept_within: float  # accept if the seller is within this fraction of list
    leverage: bool = False  # quote real rival offers
    bluff: bool = False  # invent cheaper rival offers
    fake_walk_round: Optional[int] = None  # pretend to leave in this round
    lowball: bool = False  # offer ₹1 and ask for the minimum
    tone: str = "polite"


STRATEGIES: dict[str, Strategy] = {
    s.key: s
    for s in [
        Strategy("polite", "Polite", "Fair opening, small steps, always honest.",
                 open_frac=0.80, concede_frac=0.35, accept_within=0.03, tone="polite and friendly"),
        Strategy("aggressive", "Aggressive lowballer", "Opens at 55% and pushes hard.",
                 open_frac=0.55, concede_frac=0.15, accept_within=0.01, tone="blunt and pushy"),
        Strategy("leverage", "Leverage player", "Honest, but plays every store against the others.",
                 open_frac=0.70, concede_frac=0.25, accept_within=0.02, leverage=True,
                 tone="calm, confident, data-driven"),
        Strategy("bluffer", "Walk-away bluffer", "Invents cheaper offers and fakes walking out.",
                 open_frac=0.65, concede_frac=0.20, accept_within=0.02, bluff=True, fake_walk_round=3,
                 tone="dramatic, classic bazaar haggler"),
        Strategy("lowballer", "₹1 lowballer", "Offers ₹1 and asks for the minimum price. Should fail.",
                 open_frac=0.0, concede_frac=0.0, accept_within=0.0, lowball=True, tone="cheeky"),
        Strategy("lazy", "Lazy (baseline)", "No bargaining: buys the cheapest listed price.",
                 open_frac=1.0, concede_frac=0.0, accept_within=0.0, tone="neutral"),
    ]
}


@dataclass
class StoreState:
    """What the buyer remembers about one negotiation."""
    list_price: int
    seller_ask: int
    last_offer: Optional[int] = None
    finals: int = 0
    faked_walk: bool = False
    history: list[int] = field(default_factory=list)


class BuyerBrain:
    def __init__(self, strategy: Strategy, budget: int, max_rounds: int = 6) -> None:
        self.s = strategy
        self.budget = budget
        self.max_rounds = max_rounds

    def next_move(
        self,
        round_no: int,
        store_id: str,
        st: StoreState,
        market_best: Optional[tuple[str, int]],
    ) -> Offer:
        s = self.s

        def offer(action, price=None, note="", **kw) -> Offer:
            return Offer(sender="buyer", store_id=store_id, round=round_no, action=action,
                         price=price, note=note, **kw)

        if s.lowball:
            return offer("counter", 1, "₹1 offer + asks for the minimum", asks_minimum=True)

        ask = st.seller_ask
        if round_no == 1:
            mine = r10(s.open_frac * st.list_price)
        else:
            base = st.last_offer or r10(s.open_frac * st.list_price)
            mine = r10(base + s.concede_frac * max(0, ask - base))
        mine = min(mine, self.budget)

        # Accept when the seller has come close enough.
        if ask <= self.budget and (ask <= mine or ask - mine <= s.accept_within * st.list_price):
            return offer("accept", ask, "seller's price is close enough")
        if ask <= self.budget and st.finals >= 2:
            if market_best is None or ask <= market_best[1]:
                return offer("accept", ask, "seller is firm and nobody is cheaper")
        if round_no >= self.max_rounds:
            if ask <= self.budget:
                return offer("accept", ask, "last round, price within budget")
            return offer("walk_away", None, "last round, still over budget")

        # Fake walk-away: the classic bazaar exit.
        if s.fake_walk_round and round_no == s.fake_walk_round and not st.faked_walk:
            st.faked_walk = True
            return offer("fake_walk_away", mine, "pretends to leave")

        claim_price = claim_store = None
        note = "counter-offer"
        if s.leverage and market_best and market_best[1] < ask:
            claim_store, claim_price = market_best
            note = "quotes a real rival offer"
        elif s.bluff and round_no >= 2:
            reference = min(ask, market_best[1]) if market_best else ask
            claim_price = r10(reference * 0.9)
            note = "bluffs about a cheaper rival"

        return offer("counter", mine, note, claim_price=claim_price, claim_store=claim_store)
