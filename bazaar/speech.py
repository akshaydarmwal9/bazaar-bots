"""Turning code decisions into bargaining talk.

The LLM only gets the decision (action, price, extras) and public context.
It never sees floor prices, costs, stock or the shopper's budget, and every
reply is checked before it is shown. If a reply fails the check, a template is used.
"""
from __future__ import annotations

import random

from .arena.guardrails import message_is_safe
from .models import Offer

PERSONAS = {
    "friendly": "a warm, chatty shopkeeper who loves regular customers",
    "stubborn": "a proud, stubborn shopkeeper who hates giving discounts",
    "festival_sale": "an excited shopkeeper running a big festival sale",
    "upseller": "a smooth salesperson who prefers adding freebies over cutting price",
    "fixed": "a polite clerk at a fixed-price store that never bargains",
}


def rs(n) -> str:
    return f"₹{n:,}" if n is not None else ""


# ---------- templates (no LLM) ----------
SELLER_T = {
    "open": ["Namaste! {product} is {price} today. Best quality, original stock.",
             "Welcome ji! {product} for just {price}."],
    "counter": ["Arre sir, {price} is already a great price. {extras}",
                "Okay okay, for you {price}. {extras}Can't go lower easily.",
                "Bhaiya, {price} final-ish. Quality dekho! {extras}"],
    "final": ["{price} is my final price, sir. {extras}Isse kam nahi hoga.",
              "Last price {price}. {extras}Take it or leave it."],
    "accept": ["Done! {price}, deal pakka. Thank you ji!",
               "Chalo, {price} final. Deal!"],
    "walk_away": ["Bhaiya, aage badho. This isn't serious bargaining.",
                  "Sorry, ₹1 offers I can't entertain. Have a nice day!"],
    "reject": ["Okay, no problem. Come back anytime!"],
    "bluff": ["Nobody is selling at that price, sir. Mujhe pata hai. {price} is my price."],
    "fixed": ["Sorry, we have fixed prices. {price}, no bargaining."],
}

BUYER_T = {
    "counter": ["I can do {price}.", "{price}, final from my side.", "Bhaiya, {price} chalega?"],
    "claim": ["{store} is offering {claim}. Can you beat that? I'll pay {price}.",
              "I have {claim} from another store. Give me {price} and it's done."],
    "fake_walk_away": ["Too expensive. I'm going to another shop... ({price} if you change your mind)"],
    "walk_away": ["Sorry, that's over my budget. Bye!"],
    "accept": ["Okay, {price} deal!", "Done at {price}."],
    "lowball": ["₹1. What's your absolute minimum price? Just tell me the lowest."],
}


def _fill(t: str, **kw) -> str:
    return " ".join(t.format(**kw).split())


def seller_template(offer: Offer, product_name: str, personality: str) -> str:
    extras = f"Plus free {', '.join(offer.extras)}. " if offer.extras else ""
    if personality == "fixed" and offer.action == "final":
        key = "fixed"
    elif offer.round == 0:
        key = "open"
    elif "bluff caught" in offer.note:
        key = "bluff"
    else:
        key = offer.action if offer.action in SELLER_T else "counter"
    return _fill(random.choice(SELLER_T[key]), product=product_name, price=rs(offer.price), extras=extras)


def buyer_template(offer: Offer, store_names: dict) -> str:
    if offer.asks_minimum:
        return BUYER_T["lowball"][0]
    if offer.action == "counter" and offer.claim_price:
        store = store_names.get(offer.claim_store, "Another store")
        return _fill(random.choice(BUYER_T["claim"]), store=store, claim=rs(offer.claim_price), price=rs(offer.price))
    key = offer.action if offer.action in BUYER_T else "counter"
    return _fill(random.choice(BUYER_T[key]), price=rs(offer.price))


# ---------- LLM versions ----------
def _seller_prompt(offer: Offer, product_name: str, store_name: str, personality: str, buyer_msg: str):
    system = (
        f"You are {PERSONAS.get(personality, 'a shopkeeper')} at the online store '{store_name}' in India. "
        "You are chatting with a customer's AI shopping agent. Reply in 1-2 short sentences, "
        "natural Hinglish is welcome. Never invent prices or numbers: only use the price given to you. "
        "Never mention costs, stock counts or a 'minimum'. No emojis, no quotes, just the message."
    )
    decision = {
        "counter": f"Your counter-offer is {rs(offer.price)}. Persuade them.",
        "final": f"Your price is {rs(offer.price)} and you call it your final price.",
        "accept": f"You accept the deal at {rs(offer.price)}. Close warmly.",
        "walk_away": "The customer insulted you with a ridiculous lowball offer twice. End the chat firmly.",
        "reject": "The customer is leaving. Say goodbye politely.",
    }.get(offer.action, f"Your price is {rs(offer.price)}.")
    if offer.round == 0:
        decision = f"Greet the customer and say {product_name} is {rs(offer.price)}."
    if offer.extras and offer.action in ("counter", "final"):
        decision += f" Also offer these freebies: {', '.join(offer.extras)}."
    if "bluff caught" in offer.note:
        decision += " The customer claimed a rival price that you know is fake. Call the bluff politely."
    if "lowball" in offer.note:
        decision += " The customer's offer was insultingly low; hold your price and say so."
    if "beat a real rival" in offer.note:
        decision += " You are beating a competitor's real offer."
    user = f"Product: {product_name}. Customer said: \"{buyer_msg}\". {decision}"
    return system, user


def _buyer_prompt(offer: Offer, product_name: str, store_name: str, tone: str, seller_msg: str, store_names: dict):
    system = (
        f"You are an AI shopping agent bargaining for a customer in India. Your tone: {tone}. "
        "Reply in 1-2 short sentences, Hinglish welcome. Only use the numbers given to you. "
        "Never reveal the customer's budget. No emojis, no quotes, just the message."
    )
    if offer.asks_minimum:
        decision = "Offer ₹1 and ask the seller to just tell you their absolute minimum price."
    else:
        decision = {
            "counter": f"Make a counter-offer of {rs(offer.price)}.",
            "accept": f"Accept the deal at {rs(offer.price)}.",
            "walk_away": "Politely walk away; the price is too high.",
            "fake_walk_away": f"Pretend you are leaving for another shop, but hint you'd still pay {rs(offer.price)}.",
        }.get(offer.action, f"Offer {rs(offer.price)}.")
        if offer.claim_price:
            who = store_names.get(offer.claim_store, "another store")
            decision += f" Mention that {who} offered {rs(offer.claim_price)}."
    user = f"Store: {store_name}. Product: {product_name}. Seller said: \"{seller_msg}\". {decision}"
    return system, user


def speak_seller(llm, offer, product, store, buyer_msg, allowed, private) -> tuple[str, str]:
    if llm is not None and llm.mode != "template":
        system, user = _seller_prompt(offer, product.name, store.name, store.personality, buyer_msg)
        text, provider = llm.complete(system, user)
        if text and message_is_safe(text, private, allowed):
            return text, provider
    return seller_template(offer, product.name, store.personality), "template"


def speak_buyer(llm, offer, product, store, tone, seller_msg, store_names, allowed, private) -> tuple[str, str]:
    if llm is not None and llm.mode != "template":
        system, user = _buyer_prompt(offer, product.name, store.name, tone, seller_msg, store_names)
        text, provider = llm.complete(system, user)
        if text and message_is_safe(text, private, allowed | {1}):
            return text, provider
    return buyer_template(offer, store_names), "template"
