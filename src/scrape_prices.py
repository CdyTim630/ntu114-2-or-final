"""Scrape real product prices from mart.family.com.tw (Nineyi/91app GraphQL).

Endpoint  : POST https://fts-api.91app.com/pythia-cdn/graphql
Query     : cms_shopCategory(shopId, categoryId, startIndex, fetchCount, orderBy)
Returns   : { salePageId, title, price, suggestPrice, ... } for each product

Then fuzzy-matches against the food-safety nutrition CSV (familymart_products_real.csv)
by title and overwrites the price column.
"""
from __future__ import annotations
import csv
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple


GRAPHQL = "https://fts-api.91app.com/pythia-cdn/graphql"
SHOP_ID = 360

# minimal GraphQL query (only the fields we care about)
QUERY = """
query cms_shopCategory($shopId: Int!, $categoryId: Int!, $startIndex: Int!, $fetchCount: Int!, $orderBy: String) {
  shopCategory(shopId: $shopId, categoryId: $categoryId) {
    salePageList(startIndex: $startIndex, maxCount: $fetchCount, orderBy: $orderBy) {
      totalSize
      salePageList {
        salePageId
        title
        salePageCode
        price
        suggestPrice
        isSoldOut
      }
    }
  }
}
""".strip()


def fetch_category(category_id: int, page_size: int = 60,
                    order_by: str = "Sales") -> List[Dict]:
    products: List[Dict] = []
    start = 0
    while True:
        body = {
            "operationName": "cms_shopCategory",
            "query": QUERY,
            "variables": {
                "shopId": SHOP_ID,
                "categoryId": category_id,
                "startIndex": start,
                "fetchCount": page_size,
                "orderBy": order_by,
            },
        }
        req = urllib.request.Request(
            GRAPHQL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
                "Origin": "https://mart.family.com.tw",
                "Referer": "https://mart.family.com.tw/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        node = ((data.get("data") or {}).get("shopCategory") or {}).get("salePageList") or {}
        total = node.get("totalSize") or 0
        items = node.get("salePageList") or []
        for it in items:
            products.append(it)
        if len(items) < page_size or len(products) >= total:
            break
        start += len(items)
        time.sleep(0.15)
    return products


def get_subcategories(category_id: int) -> List[int]:
    """Pull the child category IDs of a top category via the REST API."""
    url = (f"https://webapi.91app.com/webapi/ShopCategory/GetShopCategoryTreeListByLevel/{SHOP_ID}"
           f"?level=3&locationId=0&isRetailStoreExpress=false&shopId={SHOP_ID}&lang=zh-TW")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        tree = json.loads(r.read().decode("utf-8"))

    def walk(node, want_root=category_id, in_subtree=False, out=None):
        if out is None: out = []
        is_target = node.get("Id") == want_root
        children = node.get("ChildList") or []
        if is_target or in_subtree:
            out.append(node.get("Id"))
            for c in children:
                walk(c, want_root, True, out)
        else:
            for c in children:
                walk(c, want_root, False, out)
        return out

    out = []
    for root in (tree.get("Data") or {}).get("List", []):
        out.extend(walk(root))
    return sorted(set(out))


def normalize(title: str) -> str:
    """Cleanup for fuzzy matching: drop punctuation/space/series tag."""
    title = re.sub(r"[()（）\[\]［］/／.,，。 \-_]", "", title)
    title = re.sub(r"[a-zA-Z]+", "", title)
    title = re.sub(r"\d+(ml|g|公克|公升|入)", "", title, flags=re.I)
    return title.lower()


def best_match(nutrient_name: str, candidates: List[Tuple[str, float, int]]) -> Tuple[float, int, str] | None:
    """Return (price, salePageId, mart_title) for the candidate with the highest
    n-gram overlap with `nutrient_name`, or None if no decent match."""
    n_norm = normalize(nutrient_name)
    if not n_norm: return None
    n_ngrams = {n_norm[i:i+2] for i in range(len(n_norm) - 1)} | {c for c in n_norm}

    best_score, best_price, best_id, best_title = 0.0, None, None, None
    for title, price, sid in candidates:
        m_norm = normalize(title)
        if not m_norm: continue
        m_ngrams = {m_norm[i:i+2] for i in range(len(m_norm) - 1)} | {c for c in m_norm}
        inter = len(n_ngrams & m_ngrams)
        union = len(n_ngrams | m_ngrams)
        score = inter / union if union else 0
        if score > best_score:
            best_score, best_price, best_id, best_title = score, price, sid, title
    if best_score >= 0.42:
        return best_price, best_id, best_title or ""
    return None


def main():
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)

    # 1) gather every product in the 美食/生鮮 subtree (and a few sibling food cats)
    target_roots = [118919, 116811, 116812, 116813, 116814, 116815, 116816]  # 美食/生鮮 + 鮮食
    cat_ids = set()
    for root in target_roots:
        try:
            cat_ids.update(get_subcategories(root))
        except Exception as e:
            print(f"WARN subcats of {root}: {e}")
    cat_ids.update(target_roots)
    print(f"Will pull {len(cat_ids)} categories")

    all_pages: Dict[int, Dict] = {}
    for cid in sorted(cat_ids):
        try:
            items = fetch_category(cid)
            for it in items:
                sid = it.get("salePageId")
                if sid and sid not in all_pages:
                    all_pages[sid] = it
            print(f"  cat {cid}: +{len(items)} (total unique={len(all_pages)})")
            time.sleep(0.10)
        except Exception as e:
            print(f"  WARN cat {cid}: {e}")

    # dump raw catalog (useful if we ever want to reuse without re-scraping)
    raw_path = out_dir / "mart_prices_raw.csv"
    with open(raw_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["salePageId", "title", "price", "suggestPrice", "isSoldOut"])
        w.writeheader()
        for it in all_pages.values():
            w.writerow({
                "salePageId":  it.get("salePageId"),
                "title":       it.get("title"),
                "price":       it.get("price"),
                "suggestPrice": it.get("suggestPrice"),
                "isSoldOut":   it.get("isSoldOut"),
            })
    print(f"wrote {raw_path}  ({len(all_pages)} mart products)")

    # 2) merge prices into the nutrition CSV
    nut_path = out_dir / "familymart_products_real.csv"
    if not nut_path.exists():
        print("nutrition CSV not present; aborting merge.")
        return

    nutr_rows = list(csv.DictReader(open(nut_path, encoding="utf-8")))
    candidates = [(it.get("title") or "", float(it.get("price") or 0), it.get("salePageId"))
                  for it in all_pages.values() if it.get("price")]
    print(f"matching {len(nutr_rows)} nutrition rows × {len(candidates)} mart candidates …")

    matched = 0
    for row in nutr_rows:
        match = best_match(row["name"], candidates)
        if match:
            price, sid, mart_title = match
            row["price"] = round(price, 0)
            row["mart_id"] = sid
            row["mart_title"] = mart_title
            matched += 1
        else:
            row["mart_id"] = ""
            row["mart_title"] = ""
    print(f"matched {matched}/{len(nutr_rows)} ({matched/len(nutr_rows)*100:.1f}%)")

    out_path = out_dir / "familymart_products_priced.csv"
    fields = list(nutr_rows[0].keys())
    if "mart_id" not in fields: fields += ["mart_id", "mart_title"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(nutr_rows)
    print(f"wrote {out_path}  ({len(nutr_rows)} rows)")


if __name__ == "__main__":
    main()
