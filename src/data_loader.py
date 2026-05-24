"""Load real FamilyMart data, and generate random instances."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import csv
import random


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
            products.append(Product(
                pid=int(row["product_id"]),
                name=row["name"],
                category=row.get("category", ""),
                is_main=row["is_main"] == "1",
                is_protein=row["is_protein"] == "1",
                price=float(row["price"]),
                cal=float(row["calories"]),
                pro=float(row["protein"]),
                fat=float(row["fat"]),
                carb=float(row["carb"]),
                sug=float(row["sugar"]),
                sod=float(row["sodium"]),
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
