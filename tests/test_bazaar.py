"""Core guarantees, tested without any LLM (template mode)."""
import pytest

from bazaar.arena.guardrails import message_is_safe
from bazaar.arena.orchestrator import run
from bazaar.buyer.strategies import STRATEGIES
from bazaar.config import load_stores
from bazaar.llm import LLM

LLM_T = LLM("template")
REQUESTS = ["ANC headphones under 5000", "earbuds under 3000", "smartwatch under 6500"]


@pytest.mark.parametrize("strategy", list(STRATEGIES))
@pytest.mark.parametrize("request_text", REQUESTS)
def test_no_seller_ever_goes_below_floor(strategy, request_text):
    stores = {s.store_id: s for s in load_stores()}
    for verify in (True, False):
        s = run(request_text, strategy, LLM_T, verify_claims=verify)
        for r in s.results:
            floor = stores[r.store_id].products[r.product_id].floor_price
            for t in r.turns:
                if t.sender == "seller" and t.price is not None:
                    assert t.price >= floor
            if r.final_price is not None:
                assert r.final_price >= floor


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_buyer_never_pays_over_budget(strategy):
    s = run("ANC headphones under 4400", strategy, LLM_T)
    for r in s.results:
        if r.status == "deal":
            assert r.final_price <= 4400


def test_rupee_one_lowballer_gets_kicked_out():
    s = run("ANC headphones under 5000", "lowballer", LLM_T)
    negotiating = [r for r in s.results if r.status != "fixed_price"]
    assert negotiating and all(r.status == "walked_out" for r in negotiating)


def test_leverage_beats_lazy_shopper():
    s = run("ANC headphones under 5000", "leverage", LLM_T)
    assert s.best and s.savings_vs_lazy > 0


def test_bluffs_are_caught_when_sellers_can_verify():
    s = run("ANC headphones under 5000", "bluffer", LLM_T, verify_claims=True)
    assert sum(r.bluffs_caught for r in s.results) > 0


def test_message_filter_blocks_leaked_floor():
    assert not message_is_safe("Okay my minimum is ₹3,800", private={3800}, allowed={4999})
    assert not message_is_safe("Fine, ₹3,123 for you", private=set(), allowed={4999})
    assert message_is_safe("Arre sir, ₹4,999 is already discounted!", private={3800}, allowed={4999})
