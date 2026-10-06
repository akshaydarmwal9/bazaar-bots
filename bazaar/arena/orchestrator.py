"""Runs all negotiations in parallel, round by round.

Each round: the buyer decides an offer for every open store, then every seller
decides a reply. Decisions are code; the LLM phrases them (concurrently).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..buyer.needs import parse_needs
from ..buyer.strategies import STRATEGIES, BuyerBrain, StoreState
from ..config import load_stores
from ..models import NegotiationResult, Offer, Product, ShopperNeeds, Store
from ..seller.decide import SellerBrain
from ..speech import speak_buyer, speak_seller
from .guardrails import check_buyer_offer, check_seller_offer, seller_private_numbers
from .judge import rank
from .ledger import Ledger


@dataclass
class RunSummary:
    needs: ShopperNeeds
    strategy: str
    results: list[NegotiationResult]
    ranked: list[NegotiationResult]
    lazy_price: Optional[int]
    lazy_store: Optional[str]
    best: Optional[NegotiationResult]
    savings_vs_lazy: Optional[int]
    savings_pct: Optional[float]
    llm_calls: int = 0
    providers_used: dict = field(default_factory=dict)


def find_matches(stores: list[Store], needs: ShopperNeeds) -> list[tuple[Store, Product]]:
    matches = []
    for store in stores:
        for p in store.products.values():
            if p.category == needs.category:
                matches.append((store, p))
    return matches


async def _gather_speech(jobs):
    return await asyncio.gather(*[asyncio.to_thread(fn) for fn in jobs])


async def negotiate(
    needs: ShopperNeeds,
    strategy_key: str = "leverage",
    llm=None,
    max_rounds: int = 6,
    verify_claims: bool = True,
    on_event: Optional[Callable[[str, Offer], None]] = None,
) -> RunSummary:
    stores = load_stores()
    store_by_id = {s.store_id: s for s in stores}
    store_names = {s.store_id: s.name for s in stores}
    strategy = STRATEGIES[strategy_key]
    buyer = BuyerBrain(strategy, needs.budget, max_rounds)
    ledger = Ledger(verify_claims=verify_claims)
    providers: dict[str, int] = {}

    def count(provider):
        providers[provider] = providers.get(provider, 0) + 1

    matches = find_matches(stores, needs)
    results: dict[str, NegotiationResult] = {}
    sellers: dict[str, SellerBrain] = {}
    states: dict[str, StoreState] = {}
    allowed: dict[str, set[int]] = {}
    last_msg: dict[str, str] = {}

    # Lazy baseline: the cheapest listed price, no bargaining.
    in_budget = [(s, p) for s, p in matches if p.list_price <= needs.budget]
    lazy = min(in_budget, key=lambda sp: sp[1].list_price) if in_budget else None

    for store, product in matches:
        results[store.store_id] = NegotiationResult(
            store_id=store.store_id, store_name=store.name, product_id=product.product_id,
            product_name=product.name, list_price=product.list_price, status="open",
            final_price=None, extras=[], turns=[],
        )
        sellers[store.store_id] = SellerBrain(store, product, max_rounds)
        allowed[store.store_id] = {product.list_price}

    def emit(store_id: str, offer: Offer):
        results[store_id].turns.append(offer)
        ledger.record(offer, results[store_id].product_id)
        if on_event:
            on_event(store_id, offer)

    # Lazy shopper: no conversation at all.
    if strategy.key == "lazy":
        for sid, res in results.items():
            if lazy and sid == lazy[0].store_id:
                res.status, res.final_price = "deal", res.list_price
            else:
                res.status = "no_deal"
                res.turns.append(Offer(sender="buyer", store_id=sid, round=0, action="walk_away",
                                       message="(didn't bargain, only compared listed prices)"))
    else:
        # Round 0: every store greets with its opening price.
        openings = {sid: sb.open() for sid, sb in sellers.items()}
        jobs = []
        for sid, off in openings.items():
            st, pr = store_by_id[sid], sellers[sid].p
            allowed[sid].add(off.price)
            jobs.append(lambda off=off, st=st, pr=pr, sid=sid: speak_seller(
                llm, off, pr, st, "Hi, I'm looking for this product.", allowed[sid], seller_private_numbers(pr)))
        for (sid, off), (text, prov) in zip(openings.items(), await _gather_speech(jobs)):
            off.message = text
            count(prov)
            last_msg[sid] = text
            states[sid] = StoreState(list_price=sellers[sid].p.list_price, seller_ask=off.price)
            emit(sid, off)

        # Fixed-price store never negotiates: record it as a fixed offer.
        for sid, sb in sellers.items():
            if not sb.store.negotiates:
                results[sid].status = "fixed_price"
                results[sid].final_price = sb.p.list_price

        for round_no in range(1, max_rounds + 1):
            open_ids = [sid for sid, r in results.items() if r.status == "open"]
            if not open_ids:
                break

            # Buyer decides for every open store, using what it knows from last round.
            buyer_offers = {}
            for sid in open_ids:
                best_rival = ledger.best_rival_price(results[sid].product_id, exclude_store=sid)
                off = buyer.next_move(round_no, sid, states[sid], best_rival)
                buyer_offers[sid] = check_buyer_offer(off, needs.budget)
                for n in (off.price, off.claim_price):
                    if n:
                        allowed[sid].add(n)
            jobs = [
                (lambda sid=sid, off=off: speak_buyer(
                    llm, off, sellers[sid].p, store_by_id[sid], strategy.tone, last_msg[sid],
                    store_names, allowed[sid], {needs.budget}))
                for sid, off in buyer_offers.items()
            ]
            for (sid, off), (text, prov) in zip(buyer_offers.items(), await _gather_speech(jobs)):
                off.message = text
                count(prov)
                states[sid].last_offer = off.price if off.price else states[sid].last_offer
                emit(sid, off)

            # Sellers reply.
            seller_offers = {}
            for sid, b_off in buyer_offers.items():
                s_off = sellers[sid].respond(round_no, b_off, ledger)
                seller_offers[sid] = check_seller_offer(s_off, sellers[sid].p)
                if s_off.price:
                    allowed[sid].add(s_off.price)
            jobs = [
                (lambda sid=sid, off=off: speak_seller(
                    llm, off, sellers[sid].p, store_by_id[sid], buyer_offers[sid].message,
                    allowed[sid], seller_private_numbers(sellers[sid].p)))
                for sid, off in seller_offers.items()
            ]
            for (sid, s_off), (text, prov) in zip(seller_offers.items(), await _gather_speech(jobs)):
                s_off.message = text
                count(prov)
                last_msg[sid] = text
                emit(sid, s_off)
                b_off, res, st = buyer_offers[sid], results[sid], states[sid]

                if s_off.action == "accept":
                    res.status, res.final_price = "deal", s_off.price
                    res.extras = list(s_off.extras)
                elif s_off.action == "walk_away":
                    res.status = "walked_out"
                elif b_off.action == "walk_away" or s_off.action == "reject":
                    res.status = "no_deal"
                else:
                    if s_off.price is not None:
                        st.seller_ask = s_off.price
                    if s_off.action == "final":
                        st.finals += 1
                    res.extras = list(s_off.extras)

        for res in results.values():
            if res.status == "open":
                res.status = "no_deal"
            res.bluffs_caught = sellers[res.store_id].bluffs_caught

    result_list = list(results.values())
    ranked = rank(result_list, store_by_id, needs)
    best = ranked[0] if ranked else None
    lazy_price = lazy[1].list_price if lazy else None
    savings = (lazy_price - best.final_price) if (best and lazy_price) else None
    pct = round(100 * savings / lazy_price, 1) if savings is not None else None
    return RunSummary(
        needs=needs, strategy=strategy.key, results=result_list, ranked=ranked,
        lazy_price=lazy_price, lazy_store=lazy[0].name if lazy else None, best=best,
        savings_vs_lazy=savings, savings_pct=pct,
        llm_calls=getattr(llm, "calls", 0), providers_used=providers,
    )


def run(request: str, strategy_key: str = "leverage", llm=None, **kw) -> RunSummary:
    needs = parse_needs(request, llm)
    return asyncio.run(negotiate(needs, strategy_key, llm, **kw))
