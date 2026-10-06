"""Bazaar Bots: Streamlit demo.

Run:  streamlit run app.py
"""
from __future__ import annotations

import asyncio

import pandas as pd
import streamlit as st

from bazaar.arena.orchestrator import negotiate
from bazaar.buyer.needs import parse_needs
from bazaar.buyer.strategies import STRATEGIES
from bazaar.config import load_stores
from bazaar.db import save_run
from bazaar.llm import LLM

st.set_page_config(page_title="Bazaar Bots", page_icon="🛍️", layout="wide")


def rs(n):
    return f"₹{n:,}" if n is not None else "–"


STATUS_LABEL = {
    "deal": "Agreed",
    "fixed_price": "Fixed price",
    "walked_out": "Seller walked out",
    "no_deal": "No deal",
}

# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Shopper")
    request = st.text_area("What do you want?", "ANC headphones under 5000, need it in 5 days", height=80)
    strategy_key = st.selectbox(
        "Buyer agent strategy",
        list(STRATEGIES),
        index=list(STRATEGIES).index("leverage"),
        format_func=lambda k: STRATEGIES[k].label,
    )
    st.caption(STRATEGIES[strategy_key].description)

    st.header("Engine")
    probe = LLM("template")
    options = ["groq", "gemini", "template"]
    labels = {
        "groq": "Groq (gpt-oss-20b)" + ("" if probe.available("groq") else " — no key"),
        "gemini": "Gemini" + ("" if probe.available("gemini") else " — no key"),
        "template": "No LLM (templates, instant)",
    }
    default_mode = "groq" if probe.available("groq") else "template"
    mode = st.radio("Who does the talking?", options, index=options.index(default_mode),
                    format_func=lambda k: labels[k])
    rounds = st.slider("Max rounds", 3, 10, 6)
    verify = st.checkbox("Sellers can verify rival offers", value=True,
                         help="Off = sellers must trust the buyer's 'another store offered me X' claims.")
    go = st.button("Start bargaining", type="primary", width="stretch")

st.title("Bazaar Bots")
st.caption("E-commerce killed bargaining. AI agents bring it back. "
           "One buyer agent bargains with every store at once. The AI talks; the code enforces the rules.")

if go:
    llm = LLM(mode)
    with st.spinner("Agents are haggling..."):
        needs = parse_needs(request, llm)
        summary = asyncio.run(negotiate(needs, strategy_key, llm, max_rounds=rounds, verify_claims=verify))
        save_run(summary)
    st.session_state["summary"] = summary
    st.session_state["llm_error"] = llm.last_error
    st.session_state["approved"] = False

summary = st.session_state.get("summary")
if not summary:
    st.info("Describe what you want in the sidebar, pick a buyer strategy, and press **Start bargaining**.")
    st.stop()

needs = summary.needs
st.markdown(
    f"**Looking for:** {needs.category} · **Budget:** {rs(needs.budget)} · "
    f"**Delivery:** {str(needs.max_delivery_days) + ' days' if needs.max_delivery_days else 'any'} · "
    f"**Strategy:** {STRATEGIES[summary.strategy].label}"
)

# ---------------- headline numbers ----------------
best = summary.best
c1, c2, c3, c4 = st.columns(4)
c1.metric("Lazy shopper pays", rs(summary.lazy_price), summary.lazy_store or "")
c2.metric("Best deal (judge's pick)", rs(best.final_price) if best else "No deal", best.store_name if best else "")
if summary.savings_vs_lazy is not None:
    c3.metric("Saved vs lazy", rs(summary.savings_vs_lazy), f"{summary.savings_pct}%")
else:
    c3.metric("Saved vs lazy", "–")
c4.metric("Bluffs caught by sellers", sum(r.bluffs_caught for r in summary.results))

# ---------------- results table ----------------
stores = {s.store_id: s for s in load_stores()}
rows = []
for r in summary.results:
    s = stores[r.store_id]
    rows.append({
        "Store": r.store_name,
        "Seller style": s.personality.replace("_", " "),
        "Listed": rs(r.list_price),
        "Result": STATUS_LABEL.get(r.status, r.status),
        "Final price": rs(r.final_price),
        "Freebies": ", ".join(r.extras) if r.status == "deal" else "",
        "Delivery": f"{s.delivery_days} days",
        "Rating": s.rating,
        "Judge score": r.score if r.score is not None else "",
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ---------------- approval ----------------
if best:
    extras = f" + {', '.join(best.extras)}" if best.extras else ""
    st.markdown(f"**Recommended:** {best.product_name} from **{best.store_name}** at **{rs(best.final_price)}**{extras}")
    if not st.session_state.get("approved"):
        if st.button(f"Approve purchase at {rs(best.final_price)}"):
            st.session_state["approved"] = True
            st.rerun()
    else:
        st.success("Approved. (Demo only: nothing was actually bought.)")

# ---------------- chats ----------------
st.subheader("The negotiations")
tabs = st.tabs([r.store_name for r in summary.results])
for tab, r in zip(tabs, summary.results):
    with tab:
        for t in r.turns:
            role = "user" if t.sender == "buyer" else "assistant"
            avatar = "🧑‍💼" if t.sender == "buyer" else "🏪"
            with st.chat_message(role, avatar=avatar):
                st.write(t.message or "")
                bits = [f"round {t.round}", t.action.replace("_", " ")]
                if t.price is not None:
                    bits.append(rs(t.price))
                if t.note:
                    bits.append(t.note)
                st.caption(" · ".join(bits))

# ---------------- behind the curtain ----------------
with st.expander("Behind the curtain: the sellers' hidden numbers (the LLM never saw these)"):
    hidden = []
    for r in summary.results:
        p = stores[r.store_id].products[r.product_id]
        hidden.append({
            "Store": r.store_name, "Listed": rs(p.list_price), "Hidden floor": rs(p.floor_price),
            "Target": rs(p.target_price), "Final": rs(r.final_price),
            "Above floor by": rs(r.final_price - p.floor_price) if r.final_price else "–",
        })
    st.dataframe(pd.DataFrame(hidden), hide_index=True, width="stretch")

st.caption(f"LLM calls: {summary.llm_calls} · messages by provider: {summary.providers_used}")
if st.session_state.get("llm_error"):
    st.warning(f"Some LLM calls fell back to templates. Last error: {st.session_state['llm_error']}")
