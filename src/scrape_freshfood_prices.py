"""Scrape product prices from FamilyMart's official freshfood promo page.

Page : https://nevent.family.com.tw/freshfood/   (優惠組合餐)
The page lists products bucketed by price tier (49 / 59 / 69 / 79 / 99 / 109 元)
in Bootstrap accordion sections. We parse those sections and produce a
{ product_name : price_tier_NTD } dictionary.

These tier numbers are the bundle-meal prices (鮮食 + 飲品). For the OR model
we use them directly as the per-product price (the optimiser also models combo
discounts separately).
"""
from __future__ import annotations
import csv
import re
import urllib.request
from pathlib import Path
from typing import Dict, List


URL = "https://nevent.family.com.tw/freshfood/"

PRICE_TIERS = [49, 59, 69, 79, 99, 109]


def fetch_html() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="ignore")


def _section(html: str, sid: int) -> str:
    """Return the HTML inside id="collapseNN" up to balanced div close."""
    m = re.search(rf'id="collapse{sid}"[^>]*>', html)
    if not m: return ""
    start, depth, i = m.end(), 1, m.end()
    while i < len(html) and depth > 0:
        t = html.find("<div", i)
        c = html.find("</div", i)
        if c == -1: break
        if t != -1 and t < c:
            depth += 1; i = t + 4
        else:
            depth -= 1; i = c + 5
    return html[start:i]


# Bucket / category headers that should be excluded from the product list
EXCLUDE = {
    "壽司手卷/飯糰", "壽司手卷/飯糰區商品", "熱食區(限店販售)", "蒸包",
    "麵包/可頌", "三明治/漢堡", "麵包", "飲品(整月活動)", "整月活動限定",
    "沙拉手捲商品", "漢堡區商品", "指定主食99元", "指定主食109元", "指定主餐99元",
    "指定主餐109元", "飲品", "副餐", "主餐", "點心",
}


def parse_tier(html: str, sid: int) -> List[str]:
    """Return the list of product names listed under price tier `sid`."""
    s = _section(html, sid)
    if not s: return []
    text = re.sub(r"<[^>]+>", "|", s)
    text = re.sub(r"\|+", "|", text)
    items: List[str] = []
    for raw in text.split("|"):
        n = raw.strip()
        if not n or len(n) < 3:               continue
        if n.startswith(("▲", "▼", "-", "(", "（")):   continue
        if any(k in n for k in ["上市", "活動", "限店", "區商品", "Let's", "Fami"]): continue
        if n in EXCLUDE:                       continue
        # drop leading bullets / decorations
        n = re.sub(r"^[（(]?[新]?[)）]?[-－]?", "", n).strip()
        if not n: continue
        items.append(n)
    return items


def normalize_for_match(s: str) -> str:
    s = re.sub(r"[（(].*?[)）]", "", s)
    s = re.sub(r"[／/].*?(?=$|[\s,，。])", "", s)
    s = re.sub(r"[ＡＢＣＤ\s\-_,，·•·]", "", s)
    return s.lower()


def main():
    html = fetch_html()
    Path("data").mkdir(exist_ok=True)

    # 1) collect tier-level price map
    name_to_price: Dict[str, int] = {}
    for tier in PRICE_TIERS:
        items = parse_tier(html, tier)
        print(f"  tier {tier}元: {len(items)} items")
        for it in items:
            name_to_price.setdefault(it, tier)

    raw_path = Path("data/familymart_tier_prices.csv")
    with open(raw_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["name", "tier_price"])
        for n, p in sorted(name_to_price.items()):
            w.writerow([n, p])
    print(f"wrote {raw_path}  ({len(name_to_price)} tier-priced items)")

    # 2) merge into the nutrition CSV (familymart_products_real.csv).
    # Two price sources, in priority order:
    #   tier   : freshfood promo page (49/59/69/79/99/109 NT$) — covers popular 鮮食
    #   mart   : mart.family.com.tw GraphQL — covers 冷藏/冷凍/雜貨 (1600+ items)
    nut_path = Path("data/familymart_products_real.csv")
    nut_rows = list(csv.DictReader(open(nut_path, encoding="utf-8")))

    tier_norm = {normalize_for_match(n): p for n, p in name_to_price.items()}

    mart_rows = []
    mart_path = Path("data/mart_prices_raw.csv")
    if mart_path.exists():
        for r in csv.DictReader(open(mart_path, encoding="utf-8")):
            try:
                price = float(r.get("price") or 0)
            except ValueError:
                continue
            title = r.get("title", "")
            # strip 【冷藏店取-廠商】 / 【冷凍店取－廠商】 prefixes
            title_clean = re.sub(r"^【[^】]+】", "", title)
            if price > 0 and title_clean:
                mart_rows.append((normalize_for_match(title_clean), price, title_clean))

    def fuzzy_lookup(norm_name: str, candidates, threshold: float):
        """Generic 3-gram fuzzy match. candidates: iterable of (norm, price, ...)."""
        if not norm_name or len(norm_name) < 2:
            return None
        row_set = {norm_name[i:i+3] for i in range(len(norm_name)-2)} | set(norm_name)
        best = (0.0, None)
        for tup in candidates:
            k = tup[0]
            if not k: continue
            k_set = {k[i:i+3] for i in range(len(k)-2)} | set(k)
            inter = len(row_set & k_set)
            score = inter / max(len(k_set), len(row_set))
            if score > best[0]:
                best = (score, tup[1])
        return best[1] if best[0] >= threshold else None

    # First pass: direct + fuzzy matches against tier prices and mart prices.
    matched_tier = matched_mart = 0
    cat_to_tiers: dict = {}            # category_id → list[tier_price] for fallback median
    for row in nut_rows:
        n_norm = normalize_for_match(row["name"])

        p = tier_norm.get(n_norm)
        if p is None:
            p = fuzzy_lookup(n_norm, [(k, v) for k, v in tier_norm.items()], 0.50)
        if p is not None:
            row["price"], row["price_source"] = p, "tier"
            cat_to_tiers.setdefault(row.get("category_id", ""), []).append(p)
            matched_tier += 1
            continue

        p = fuzzy_lookup(n_norm, mart_rows, 0.50)
        if p is not None:
            row["price"], row["price_source"] = round(p), "mart"
            matched_mart += 1
            continue

        row["price_source"] = "pending"

    # Second pass: for "pending" rows, use the median tier price observed
    # *within the same FamilyMart category_id* — gives a much better real-world
    # estimate than the global category average.
    from statistics import median
    matched_cat = 0
    for row in nut_rows:
        if row.get("price_source") != "pending":
            continue
        cat = row.get("category_id", "")
        tiers = cat_to_tiers.get(cat, [])
        if tiers:
            row["price"] = round(median(tiers))
            row["price_source"] = "cat_median_tier"
            matched_cat += 1
        else:
            row["price_source"] = "category_avg"

    out_path = Path("data/familymart_products_priced.csv")
    fields = list(nut_rows[0].keys())
    if "price_source" not in fields: fields.append("price_source")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(nut_rows)
    n = len(nut_rows)
    real = matched_tier + matched_mart
    print(f"matched: tier={matched_tier} ({matched_tier/n*100:.1f}%) "
          f"+ mart={matched_mart} ({matched_mart/n*100:.1f}%) "
          f"+ cat_median={matched_cat} ({matched_cat/n*100:.1f}%) "
          f"= REAL price coverage {real/n*100:.1f}%, "
          f"category-derived {matched_cat/n*100:.1f}%, "
          f"global-avg fallback {(n-real-matched_cat)/n*100:.1f}%")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
