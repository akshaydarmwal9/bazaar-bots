"""Run a negotiation from the terminal.

    python -m bazaar.cli "ANC headphones under 5000" --strategy leverage --llm groq
"""
from __future__ import annotations

import argparse

from .arena.orchestrator import run
from .buyer.strategies import STRATEGIES
from .db import save_run
from .llm import LLM


def rs(n):
    return f"₹{n:,}" if n is not None else "-"


def main() -> None:
    ap = argparse.ArgumentParser(description="Bazaar Bots: AI agents that bargain")
    ap.add_argument("request", nargs="?", default="ANC headphones under 5000, need it in 5 days")
    ap.add_argument("--strategy", default="leverage", choices=list(STRATEGIES))
    ap.add_argument("--llm", default=None, choices=["groq", "gemini", "template"])
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--no-verify", action="store_true", help="sellers can't check rival-offer claims")
    ap.add_argument("--quiet", action="store_true", help="hide the chat transcript")
    args = ap.parse_args()

    llm = LLM(args.llm)
    s = run(args.request, args.strategy, llm, max_rounds=args.rounds, verify_claims=not args.no_verify)
    print(f"\nRequest: {s.needs.raw}\nParsed: {s.needs.category}, budget {rs(s.needs.budget)}, "
          f"delivery <= {s.needs.max_delivery_days or 'any'} days | strategy: {s.strategy} | LLM: {llm.mode}\n")
    if not args.quiet:
        for r in s.results:
            print(f"--- {r.store_name} ({r.product_name}) ---")
            for t in r.turns:
                who = "BUYER " if t.sender == "buyer" else "SELLER"
                print(f"  [{t.round}] {who} {t.action:<15} {rs(t.price):>8}  {t.message}")
            print()
    print(f"{'Store':<12} {'Status':<12} {'List':>8} {'Final':>8} {'Score':>8}")
    for r in s.results:
        print(f"{r.store_name:<12} {r.status:<12} {rs(r.list_price):>8} {rs(r.final_price):>8} "
              f"{(r.score if r.score is not None else '-'):>8}")
    if s.best:
        print(f"\nBest deal: {s.best.store_name} at {rs(s.best.final_price)}"
              f"{' + ' + ', '.join(s.best.extras) if s.best.extras else ''}")
        print(f"Lazy shopper would pay {rs(s.lazy_price)} at {s.lazy_store}. "
              f"Saved {rs(s.savings_vs_lazy)} ({s.savings_pct}%).")
    else:
        print("\nNo deal within budget.")
    print(f"LLM calls: {s.llm_calls} | messages by provider: {s.providers_used}")
    if llm.last_error:
        print(f"Last LLM error: {llm.last_error}")
    save_run(s)


if __name__ == "__main__":
    main()
