"""Load real FamilyMart data, and generate random instances."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import csv
import random
import re

# Family-size packs (>= this many servings) are NOT a realistic single-meal
# purchase — you cannot buy 1/4 of a 1857 ml soy-milk bottle or 1/3 of a 936 ml
# milk carton for one meal. Such SKUs are dropped from the optimiser entirely.
# Single packs and small 2-packs (2-入 onigiri, a 2-pack snack) are kept.
FAMILY_PACK_MIN_SERVINGS = 3

# A single convenience-store portion never realistically costs less than this.
# Small multipacks that survive the filter still have their price divided by
# `n_servings`; flooring stops an imputed pack price from turning into an
# unrealistic per-serving price that dominates the cost-minimising objective.
# Single-serving items (n_servings == 1) keep their real price.
MIN_SERVING_PRICE = 18.0

# total beverage volume embedded in a product name, e.g. "...1857ml", "...2L"
_VOL_ML_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:毫升|ml|cc)", re.IGNORECASE)
_VOL_L_RE  = re.compile(r"(\d+(?:\.\d+)?)\s*(?:公升|l)(?![a-z])", re.IGNORECASE)


def _portion_name(name: str, servings: float) -> str:
    """Turn a multipack name into a per-serving name.

    Drops the misleading whole-pack volume (e.g. "1857ml") and, when a volume is
    present, annotates the realistic per-serving volume instead.
    """
    if servings <= 1:
        return name
    n = int(servings) if servings == int(servings) else round(servings, 1)
    m = _VOL_ML_RE.search(name)
    total_ml = float(m.group(1)) if m else None
    if total_ml is None:
        m = _VOL_L_RE.search(name)
        total_ml = float(m.group(1)) * 1000 if m else None
    if m is not None:
        base = (name[:m.start()] + name[m.end():]).strip()
        per = int(round(total_ml / servings / 5.0) * 5)  # nearest 5 ml
        return f"{base}（約 {per}ml／份，整包{n}份）"
    return f"{name}（單份，整包{n}份）"


@dataclass
class Product:
    pid: int
    name: str
    category: str
    is_main: bool
    is_protein: bool
    price: float
    cal: float
    pro: float
    fat: float
    carb: float
    sug: float
    sod: float
    role: str = "side"   # main / drink / dessert / side (meal-structure role)


# Meal-structure role of each product, derived from its FamilyMart category (the
# CSV's keyword-based is_main / is_protein flags are noisy — e.g. cakes and
# cookies were flagged as protein sources). One of: main / drink / dessert / side.
ROLE_BY_CATEGORY = {
    "主餐麵食": "main", "壽司手卷飯糰": "main", "三明治漢堡": "main",
    "冷凍食品": "main", "麵包": "main", "蒸箱食品": "main",
    "一般飲料": "drink", "現做飲料": "drink", "乳製品": "drink",
    "點心零食": "dessert", "蛋糕甜品": "dessert", "冰品": "dessert",
    "加工食品": "side", "燒烤食品": "side", "小菜、滷味、湯品": "side",
    "現煮鍋物": "side", "生鮮蔬果沙拉": "side", "營養食品": "side",
}
# An item counts as a real protein source only if it clears this per-serving
# protein bar AND is not a dessert/sweet (so a 6 g-protein cake never qualifies).
PROTEIN_MIN_G = 7.0

# A "麵包" with at least this much sugar is a sweet bread (菠蘿/拔絲/可可可頌) —
# really a snack, not a meal's staple main. Reclassified as dessert so it can't
# be a regular meal's main and is limited to one per meal.
SWEET_BREAD_SUGAR_G = 10.0


def _derive_role(category: str, name: str) -> str:
    role = ROLE_BY_CATEGORY.get(category, "side")
    # keyword overrides for items mis-placed by their category. Use multi-char
    # keywords only — a bare "蛋" would wrongly match "蛋糕" (cake).
    if any(k in name for k in ("便當", "炒飯", "丼", "飯糰", "壽司", "三明治",
                               "漢堡", "義大利麵", "炒麵", "烏龍麵", "拉麵", "水餃")):
        role = "main"
    elif role == "dessert" and any(k in name for k in (
            "雞胸", "雞腿", "雞肉", "豬肉", "牛肉", "鮭魚", "鯖魚", "茶葉蛋",
            "滷蛋", "豆腐", "毛豆", "沙拉")):
        role = "side"
    return role


@dataclass
class Combo:
    cid: int
    name: str
    item_ids: List[int]
    promo_price: float
    original_price: float


@dataclass
class Instance:
    products: List[Product]
    combos: List[Combo]
    history: List[int] = field(default_factory=list)  # recent purchase ids, most-recent first


def load_real_instance(data_dir: str = "data", use_scraped: bool = True) -> Instance:
    """Load the FamilyMart real-world instance.

    If `use_scraped` and `familymart_products_real.csv` is present (output of
    scrape_familymart.py), use the scraped 580+ product set; otherwise fall
    back to the curated 75-item file for backward compatibility.
    """
    base = Path(data_dir)
    priced  = base / "familymart_products_priced.csv"     # real prices (preferred)
    scraped = base / "familymart_products_real.csv"        # nutrition only
    if use_scraped and priced.exists():
        fname = priced
    elif use_scraped and scraped.exists():
        fname = scraped
    else:
        fname = base / "familymart_products.csv"
    products: List[Product] = []
    with open(fname, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Many FamilyMart SKUs are multi-serving packs (e.g. a 1857 ml soy
            # milk = 4 servings, a snack box = 24). The raw nutrition/price are
            # for the WHOLE pack, which is not what a single meal contains.
            # Normalise everything to ONE serving so the optimiser reasons about
            # a realistic per-meal portion (and price-per-serving is comparable).
            try:
                servings = float(row.get("n_servings", "1") or "1")
            except ValueError:
                servings = 1.0
            if servings < 1.0:
                servings = 1.0
            # Drop family-size packs (large bottles / bulk boxes) — they are not
            # a sensible single-meal item, and their imputed per-serving price
            # otherwise lets them dominate the recommendation every time.
            if servings >= FAMILY_PACK_MIN_SERVINGS:
                continue
            # When a pack is multi-serving, the values shown are per single
            # serving — annotate the name (and drop the misleading whole-pack
            # volume) so the user knows it's a portion, not the whole pack.
            name = _portion_name(row["name"], servings)
            # Per-serving price, floored so imputed multipack prices can't turn
            # into an unrealistic ~1 NTD "serving" that dominates the objective.
            per_serving_price = float(row["price"]) / servings
            if servings > 1:
                per_serving_price = max(per_serving_price, MIN_SERVING_PRICE)
            category = row.get("category", "")
            pro_g = round(float(row["protein"]) / servings, 1)
            sug_g = round(float(row["sugar"]) / servings, 1)
            role = _derive_role(category, name)
            # a sugar-heavy bread is a snack, not a staple main
            if role == "main" and category == "麵包" and sug_g >= SWEET_BREAD_SUGAR_G:
                role = "dessert"
            # Re-derive structure flags from category/role + protein content
            # rather than trusting the noisy keyword-based CSV flags.
            is_main = role == "main"
            is_protein = pro_g >= PROTEIN_MIN_G and role != "dessert"
            products.append(Product(
                pid=int(row["product_id"]),
                name=name,
                category=category,
                is_main=is_main,
                is_protein=is_protein,
                price=round(per_serving_price, 1),
                cal=round(float(row["calories"]) / servings, 1),
                pro=pro_g,
                fat=round(float(row["fat"]) / servings, 1),
                carb=round(float(row["carb"]) / servings, 1),
                sug=sug_g,
                sod=round(float(row["sodium"]) / servings, 1),
                role=role,
            ))

    combos: List[Combo] = (_build_combos(products)
                            if fname.name.endswith(("real.csv", "priced.csv"))
                            else _load_curated_combos(base, products))
    return Instance(products=products, combos=combos, history=[])


def _load_curated_combos(base: Path, products: List[Product]) -> List["Combo"]:
    combos: List[Combo] = []
    f = base / "familymart_combos.csv"
    if not f.exists():
        return combos
    with open(f, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ids = [int(x.strip()) for x in row["items"].split(",")]
            combos.append(Combo(
                cid=int(row["combo_id"]),
                name=row["name"],
                item_ids=ids,
                promo_price=float(row["promo_price"]),
                original_price=float(row["original_price"]),
            ))
    return combos


def _build_combos(products: List[Product]) -> List["Combo"]:
    """Synthesize plausible combo offers for the scraped product set.
    Heuristic: pair each main with a complementary drink/side at 88% of list price.
    """
    import random
    rng = random.Random(0)
    drinks = [p for p in products if any(k in p.name for k in ["豆漿","茶","咖啡","乳","汁","水","可可"])]
    sides  = [p for p in products if any(k in p.name for k in ["蛋","沙拉","毛豆","豆腐","湯","水果"])]
    mains  = [p for p in products if p.is_main]
    pmap = {p.pid: p for p in products}
    combos: List[Combo] = []
    cid = 1
    # 30 main+drink combos
    for m in rng.sample(mains, min(30, len(mains))):
        if not drinks: break
        d = rng.choice(drinks)
        if d.pid == m.pid: continue
        orig = m.price + d.price
        promo = round(orig * 0.88)
        combos.append(Combo(cid=cid, name=f"{m.name}+{d.name}",
                            item_ids=[m.pid, d.pid],
                            promo_price=promo, original_price=orig))
        cid += 1
    # 15 main+side combos
    for m in rng.sample(mains, min(15, len(mains))):
        if not sides: break
        s = rng.choice(sides)
        if s.pid == m.pid: continue
        orig = m.price + s.price
        promo = round(orig * 0.85)
        combos.append(Combo(cid=cid, name=f"{m.name}+{s.name}",
                            item_ids=[m.pid, s.pid],
                            promo_price=promo, original_price=orig))
        cid += 1
    # 10 main+side+drink triples
    for m in rng.sample(mains, min(10, len(mains))):
        if not sides or not drinks: break
        s = rng.choice(sides); d = rng.choice(drinks)
        ids = list({m.pid, s.pid, d.pid})
        if len(ids) != 3: continue
        orig = sum(pmap[i].price for i in ids)
        promo = round(orig * 0.83)
        combos.append(Combo(cid=cid, name=f"{m.name}+{s.name}+{d.name}",
                            item_ids=ids, promo_price=promo, original_price=orig))
        cid += 1
    return combos


def generate_random_instance(n_products: int, n_combos: int, seed: int = 0,
                             main_ratio: float = 0.35, protein_ratio: float = 0.45) -> Instance:
    """Generate a random instance. Parameter ranges roughly match real FamilyMart data."""
    rng = random.Random(seed)
    products: List[Product] = []
    for i in range(1, n_products + 1):
        is_main = rng.random() < main_ratio
        is_protein = rng.random() < protein_ratio
        if is_main:
            cal = rng.uniform(180, 650)
            carb = rng.uniform(30, 75)
            pro = rng.uniform(5, 30) if is_protein else rng.uniform(2, 10)
            fat = rng.uniform(3, 25)
            price = rng.uniform(28, 99)
        else:
            cal = rng.uniform(15, 320)
            carb = rng.uniform(0, 30)
            pro = rng.uniform(0, 28) if is_protein else rng.uniform(0, 6)
            fat = rng.uniform(0, 20)
            price = rng.uniform(15, 75)
        sug = rng.uniform(0, max(0.1, 0.3 * carb))
        sod = rng.uniform(0, 1400)
        products.append(Product(
            pid=i, name=f"item_{i}", category="random",
            is_main=is_main, is_protein=is_protein,
            price=round(price, 1), cal=round(cal, 1),
            pro=round(pro, 1), fat=round(fat, 1), carb=round(carb, 1),
            sug=round(sug, 1), sod=round(sod, 1),
            role="main" if is_main else "side",
        ))

    combos: List[Combo] = []
    for k in range(1, n_combos + 1):
        size = rng.choice([2, 2, 3])
        chosen = rng.sample(range(1, n_products + 1), size)
        orig = sum(p.price for p in products if p.pid in chosen)
        promo = round(orig * rng.uniform(0.80, 0.92), 1)
        combos.append(Combo(cid=k, name=f"combo_{k}", item_ids=chosen,
                            promo_price=promo, original_price=round(orig, 1)))
    return Instance(products=products, combos=combos, history=[])


if __name__ == "__main__":
    inst = load_real_instance()
    print(f"Loaded {len(inst.products)} products and {len(inst.combos)} combos.")
    print("First product:", inst.products[0])
    print("First combo:", inst.combos[0])

    rinst = generate_random_instance(40, 12, seed=42)
    print(f"\nRandom: {len(rinst.products)} products, {len(rinst.combos)} combos.")
