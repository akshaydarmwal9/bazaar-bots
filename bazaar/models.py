"""Shared data structures for Bazaar Bots."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Extra:
    item: str
    cost: int  # cost to the seller (rupees)
    value: int  # perceived value to the buyer (rupees)


@dataclass
class Product:
    product_id: str
    name: str
    category: str
    list_price: int
    floor_price: int  # PRIVATE: never sent to an LLM
    target_price: int  # PRIVATE
    cost_price: int  # PRIVATE
    stock: int  # PRIVATE


@dataclass
class Store:
    store_id: str
    name: str
    personality: str  # friendly | stubborn | festival_sale | upseller | fixed
    negotiates: bool
    rating: float
    delivery_days: int
    warranty_months: int
    price_match: bool
    extras: list[Extra]
    products: dict[str, Product]

    def public_view(self) -> dict:
        """What a buyer is allowed to see (no floors, costs or stock)."""
        return {
            "store_id": self.store_id,
            "name": self.name,
            "rating": self.rating,
            "delivery_days": self.delivery_days,
            "warranty_months": self.warranty_months,
            "products": {
                pid: {"name": p.name, "category": p.category, "list_price": p.list_price}
                for pid, p in self.products.items()
            },
        }


@dataclass
class ShopperNeeds:
    raw: str
    category: str
    keywords: list[str]
    budget: int
    max_delivery_days: Optional[int] = None


@dataclass
class Offer:
    sender: str  # "buyer" or "seller"
    store_id: str
    round: int
    action: str  # counter | accept | reject | walk_away | fake_walk_away | final
    price: Optional[int] = None
    extras: list[str] = field(default_factory=list)
    claim_price: Optional[int] = None  # buyer: "another store offered me X"
    claim_store: Optional[str] = None
    asks_minimum: bool = False  # buyer: "tell me your lowest price"
    message: str = ""
    note: str = ""  # internal reasoning label, shown in the UI


@dataclass
class NegotiationResult:
    store_id: str
    store_name: str
    product_id: str
    product_name: str
    list_price: int
    status: str  # deal | walked_out | no_deal | fixed_price
    final_price: Optional[int]
    extras: list[str]
    turns: list[Offer]
    bluffs_caught: int = 0
    score: Optional[float] = None
