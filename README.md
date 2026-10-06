# Bazaar Bots 🛍️

**E-commerce killed bargaining. AI agents are bringing it back.**

In Sarojini Nagar, the price tag was just the opening offer. Online shopping replaced that with one fixed price for everyone. Bazaar Bots imagines what comes next: a **buyer agent** that bargains with **every online store at once**, and **seller agents** that bargain back.

- 🧑‍💼 **1 buyer agent** searches 5 stores, negotiates with all of them in parallel and plays real offers against each other.
- 🏪 **5 seller agents** with their own personalities (friendly, stubborn, festival sale, upseller, fixed price) and **hidden floor prices**.
- ⚖️ **A judge** picks the best deal on price, delivery, warranty, rating and freebies, and **you approve** before anything is "bought".

> **The AI talks. The code enforces.** Prices and decisions are plain Python. The LLM only writes the messages, and it never sees floor prices, costs, stock or your budget. Every message is checked before it's shown.

---

## Run it (GitHub Codespaces, free)

1. Add your free Groq key as a Codespaces secret: **Settings → Secrets and variables → Codespaces → New repository secret** → name `GROQ_API_KEY`. (Get a key at [console.groq.com/keys](https://console.groq.com/keys).)
2. **Code → Codespaces → Create codespace on main.**
3. Wait about a minute. Dependencies install and the app opens on port 8501 automatically.

If the app doesn't open by itself:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Terminal version:

```bash
python -m bazaar.cli "ANC headphones under 5000, need it in 5 days" --strategy leverage --llm groq
python -m bazaar.cli "earbuds under 3000" --strategy lowballer --llm template
```

Tests (no LLM needed):

```bash
pytest -q
```

## Buyer strategies

| Strategy | Behaviour |
|---|---|
| Polite | Fair opening, small steps, always honest |
| Aggressive lowballer | Opens at 55% of list and pushes hard |
| Leverage player | Honest, but quotes real rival offers to every store |
| Walk-away bluffer | Invents cheaper offers and fakes walking out |
| ₹1 lowballer | Offers ₹1 and asks for "your minimum". It should fail, and it does |
| Lazy (baseline) | No bargaining, buys the cheapest listed price |

## Why the ₹1 trick doesn't work

Seller agents follow four rules, all in code:

1. **The floor price is never in the LLM's prompt**, so it can't be leaked.
2. **Lowballs (below 50% of list) are insults.** The first one gets no discount, and the second ends the chat.
3. **Reciprocity:** a seller only moves when the buyer moves (`seller_step ≤ 0.8 × buyer_step`).
4. **Rival claims are checked** against the offer ledger. Bluffs get caught (switch this off in the sidebar to see bluffing work).

## Architecture

```
Shopper request ─▶ Buyer agent ──┐                 ┌── Seller agents ◀─ Market setup
  needs → utility                │   Negotiation   │   private config (floor, stock)
  search + shortlist             ├─▶   arena     ◀─┤   decide (code)
  strategy engine                │  orchestrator   │   speak (LLM)
  leverage + bluffs              │  guardrails     │   lowball defense
  stop / walk away               │  offer ledger   │   fixed-price store (control)
                                 │  deal judge     │
                                 └─▶ your approval ┘
Shared: LLM layer (Groq → Gemini → templates) · SQLite logs · Streamlit UI
```

```
bazaar/
├── buyer/        needs.py · strategies.py
├── seller/       decide.py
├── arena/        orchestrator.py · guardrails.py · ledger.py · judge.py
├── speech.py     LLM prompts + templates + leak filter
├── llm.py        Groq / Gemini / template wrapper with fallback
├── db.py         SQLite log (data/bazaar.db)
└── cli.py
config/
├── stores/       one YAML per store (prices, floors, personality, freebies)
├── catalog.yaml  products (fictional brands)
└── llm.yaml      models and fallback order
app.py            Streamlit UI
```

## LLMs (all free)

- **Groq `openai/gpt-oss-20b`** is the default voice. It needs `GROQ_API_KEY`.
- **Gemini** is the automatic backup if Groq is rate-limited. It needs `GEMINI_API_KEY` (optional).
- **Templates** need no LLM and run instantly offline.

Change models in `config/llm.yaml`. Keys come only from environment variables or Codespaces secrets and are never committed.

## Deploy a public demo (optional)

**Streamlit Community Cloud:** share.streamlit.io → sign in with GitHub → New app → this repo, `app.py` → Advanced settings → Secrets: `GROQ_API_KEY = "gsk_..."`.

---

All stores, products and brands are fictional. It's a simulation, and nothing is actually bought.
