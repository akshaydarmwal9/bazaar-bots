"""Load stores, catalog and LLM settings from the config/ folder."""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import Extra, Product, Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_catalog() -> dict:
    return load_yaml(CONFIG_DIR / "catalog.yaml")


def load_stores() -> list[Store]:
    catalog = load_catalog()
    stores = []
    for path in sorted((CONFIG_DIR / "stores").glob("*.yaml")):
        raw = load_yaml(path)
        products = {}
        for pid, p in raw["products"].items():
            info = catalog[pid]
            products[pid] = Product(
                product_id=pid,
                name=info["name"],
                category=info["category"],
                list_price=int(p["list_price"]),
                floor_price=int(p["floor_price"]),
                target_price=int(p["target_price"]),
                cost_price=int(p["cost_price"]),
                stock=int(p["stock"]),
            )
        stores.append(
            Store(
                store_id=raw["store_id"],
                name=raw["name"],
                personality=raw["personality"],
                negotiates=bool(raw.get("negotiates", True)),
                rating=float(raw["rating"]),
                delivery_days=int(raw["delivery_days"]),
                warranty_months=int(raw["warranty_months"]),
                price_match=bool(raw.get("price_match", True)),
                extras=[Extra(**e) for e in raw.get("extras", [])],
                products=products,
            )
        )
    return stores


def load_llm_config() -> dict:
    return load_yaml(CONFIG_DIR / "llm.yaml")
