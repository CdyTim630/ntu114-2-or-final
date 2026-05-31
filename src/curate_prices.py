"""Curate market-realistic per-item prices for the non-tier products.

Background
----------
`scrape_freshfood_prices.py` produces `familymart_products_priced.csv` with a
`price_source` column.  Only the `tier` rows carry a real in-store price (the
鮮食 49/59/.../109 promo tiers).  The other ~78% are either:
  * `mart`            — 全家行動購 e-commerce prices, which are *bulk / case*
                        prices (e.g. a box of 紅燒牛肉麵 at 249), wrong for a
                        single-meal item, and
  * `category_avg` /
    `cat_median_tier` — a single flat number per category (e.g. every 乳製品
                        priced 35), which does not reflect real shelf prices.

FamilyMart exposes no public per-item shelf price for packaged goods, so this
script replaces every NON-tier price with a market-realistic estimate built
from (a) a per-category single-serving price table calibrated to typical
Taiwan FamilyMart shelf prices and (b) a volume model for beverages whose name
carries a millilitre figure.  Real `tier` rows are left untouched.

Semantics: the CSV `price` is the WHOLE-PACK price (data_loader divides it by
`n_servings`).  We therefore estimate a realistic per-serving unit price and
write `price = unit_price * n_servings`, so the per-meal portion the optimiser
sees is realistic for both single items and small multipacks.
"""
from __future__ import annotations
import csv
import re
import shutil
from pathlib import Path

PRICED = Path("data/familymart_products_priced.csv")

# typical single-serving FamilyMart shelf price by category (NTD)
CATEGORY_UNIT_PRICE = {
    "乳製品": 28, "一般飲料": 28, "現做飲料": 50,
    "點心零食": 32, "加工食品": 45, "冷凍食品": 65,
    "小菜、滷味、湯品": 45, "蛋糕甜品": 35, "冰品": 30,
    "現煮鍋物": 20, "燒烤食品": 45, "生鮮蔬果沙拉": 65,
    "主餐麵食": 85, "壽司手卷飯糰": 40, "麵包": 30,
    "三明治漢堡": 45, "營養食品": 40, "蒸箱食品": 45,
}
DEFAULT_UNIT_PRICE = 40

_VOL_ML_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:毫升|ml|cc)", re.IGNORECASE)
_VOL_L_RE  = re.compile(r"(\d+(?:\.\d+)?)\s*(?:公升|l)(?![a-z])", re.IGNORECASE)


def _total_ml(name: str):
    m = _VOL_ML_RE.search(name)
    if m:
        return float(m.group(1))
    m = _VOL_L_RE.search(name)
    if m:
        return float(m.group(1)) * 1000
    return None


def _beverage_unit_price(per_serving_ml: float) -> float:
    """Per-serving price of a drink from its per-serving volume."""
    return max(15.0, min(45.0, 8.0 + 0.055 * per_serving_ml))


def _keyword_refine(category: str, name: str, base: float) -> float:
    """Nudge the category base by recognisable sub-types."""
    if category == "乳製品":
        if "高蛋白" in name or "蛋白" in name:           return 38
        if "優酪乳" in name:                              return 30
        if "起司" in name or "乳酪" in name:              return 33
    if category == "加工食品":
        if "沙拉" in name:                                return 59
        if "雞胸" in name:                                return 59
        if "雞腿" in name:                                return 55
        if "牛肉麵" in name or "拉麵" in name:            return 79
    if category in ("蛋糕甜品",) and ("優格" in name):     return 35
    if category == "點心零食" and ("糖" in name and "餅" not in name):
        return 25
    return base


def curate() -> None:
    rows = list(csv.DictReader(open(PRICED, encoding="utf-8")))
    fields = list(rows[0].keys())

    n_curated = 0
    for r in rows:
        if r.get("price_source") == "tier":
            continue  # real in-store price — keep
        try:
            servings = float(r.get("n_servings", "1") or "1")
        except ValueError:
            servings = 1.0
        if servings < 1.0:
            servings = 1.0

        cat = r.get("category", "")
        name = r.get("name", "")
        base = CATEGORY_UNIT_PRICE.get(cat, DEFAULT_UNIT_PRICE)

        total_ml = _total_ml(name)
        if cat in ("乳製品", "一般飲料") and total_ml:
            unit = _beverage_unit_price(total_ml / servings)
        else:
            unit = _keyword_refine(cat, name, base)

        r["price"] = round(unit * servings)
        r["price_source"] = "curated"
        n_curated += 1

    with open(PRICED, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"curated {n_curated}/{len(rows)} non-tier prices "
          f"(kept {len(rows) - n_curated} real tier prices)")


if __name__ == "__main__":
    if not PRICED.exists():
        raise SystemExit(f"{PRICED} not found — run scrape_freshfood_prices.py first")
    # safety backup (only if one doesn't already exist from this session)
    bak = PRICED.with_suffix(".precurate.csv")
    if not bak.exists():
        shutil.copy(PRICED, bak)
        print(f"backup -> {bak}")
    curate()
