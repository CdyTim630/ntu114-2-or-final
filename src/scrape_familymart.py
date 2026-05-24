"""Scrape real FamilyMart nutrition data from the food-safety API.

Data source: https://foodsafety.family.com.tw (全家食在購安心)
Public endpoints (POST JSON):
  - ws/QueryFsProductListByFilter   {MEMBER:'N', KEYWORD:'...'}
  - ws/QueryFsProductByItem         {CMNO:'...'}

The API returns nutrition per package (PROTEIN, TOTALFAT, CARBOHYDRATE, SODIUM, SUGAR)
and calorie/serving info inside NOTE. Prices are NOT exposed by this API and are
estimated from category averages observed in store; this limitation is documented
in the report.
"""
from __future__ import annotations
import csv
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE = "https://foodsafety.family.com.tw/Web_FFD_2022/ws/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NTU-OR-class-project)",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Categories worth covering for a meal-recommendation problem.
# (Category-id -> Chinese label is documented at /Web_FFD_2022/json/product_category.json)
KEYWORDS = [
    "飯糰", "便當", "炒飯", "燴飯", "丼", "三明治", "漢堡", "貝果", "可頌", "麵包",
    "沙拉", "輕食", "雞胸", "雞腿", "豬", "牛", "魚",
    "義大利麵", "拉麵", "烏龍麵", "涼麵", "炒麵",
    "蒸蛋", "茶葉蛋", "毛豆", "豆腐", "關東煮",
    "湯", "粥",
    "牛奶", "豆漿", "優酪乳", "優格", "鮮乳",
    "水果", "香蕉",
    "包子", "燒賣", "餃",
    "熱狗", "蛋餅", "捲餅",
]

# Price heuristic by CATEGORY_ID (NT$). Based on FamilyMart retail observations.
PRICE_BY_CATEGORY = {
    "1":  35,   # 壽司手卷飯糰
    "2":  79,   # 便當/麵食/微波餐
    "3":  55,   # 漢堡/三明治/貝果
    "4":  65,   # 沙拉/涼麵
    "5":  35,   # 台式小吃
    "6":  35,   # 甜點
    "7":  35,   # 麵包
    "8":  45,   # 咖啡/茶
    "9":  35,   # 冰品
    "10": 35,   # 蒸食/包子
    "11": 35,   # 熱狗/熱食
    "12": 20,   # 關東煮
    "13": 20,   # 蛋類
    "14": 25,   # 冰棒
    "15": 75,   # 冷凍食品
    "16": 35,   # 乳製品
    "17": 30,   # 飲料
    "18": 35,   # 零食
    "19": 79,   # 加工食品
    "20": 30,   # 健康
}


def post(endpoint: str, payload: Dict) -> Dict:
    req = urllib.request.Request(BASE + endpoint, headers=HEADERS,
                                 data=json.dumps(payload).encode("utf-8"),
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_kcal_per_pack(note: str) -> Optional[Tuple[float, int]]:
    """Parse "每份熱量174大卡;每份規格105公克;(本包裝含1份);" → (174, 1)"""
    kcal_match = re.search(r"每份熱量\s*(\d+(?:\.\d+)?)", note or "")
    n_servings = re.search(r"本包裝含\s*(\d+(?:\.\d+)?)", note or "")
    if not kcal_match:
        # alternate form
        kcal_match = re.search(r"熱量\s*(\d+(?:\.\d+)?)", note or "")
    if kcal_match:
        kcal = float(kcal_match.group(1))
        n = float(n_servings.group(1)) if n_servings else 1.0
        return kcal, int(n)
    return None


def list_products(keyword: str) -> List[Dict]:
    res = post("QueryFsProductListByFilter", {"MEMBER": "N", "KEYWORD": keyword})
    if res.get("RESULT_CODE") != "00":
        return []
    out = []
    for cat in res.get("LIST", []):
        for it in cat.get("ITEM", []):
            out.append({
                "CMNO": it["CMNO"],
                "PRODNAME": it["PRODNAME"],
                "NOTE": it.get("NOTE", ""),
                "CATEGORY_ID": cat.get("CATEGORY_ID"),
                "CATEGORY_NAME": cat.get("CATEGORY_NAME"),
            })
    return out


def fetch_detail(cmno: str) -> Optional[Dict]:
    res = post("QueryFsProductByItem", {"CMNO": cmno})
    if res.get("RESULT_CODE") != "00" or not res.get("LIST"):
        return None
    return res["LIST"][0]


def is_main_dish(category_id: str, name: str) -> bool:
    """Carbohydrate-rich main course. Used by the OR model."""
    if category_id in {"1", "2", "3", "7", "15"}:
        return True
    main_keywords = ["飯糰", "便當", "麵", "三明治", "漢堡", "貝果", "可頌", "麵包",
                      "捲餅", "丼", "粥"]
    return any(k in name for k in main_keywords)


def is_protein_source(category_id: str, name: str, protein_per_pack: float) -> bool:
    """High-protein item (eggs, meat, dairy, beans)."""
    if category_id in {"13", "16"}:
        return True
    pro_keywords = ["雞", "豬", "牛", "魚", "鮭", "鮪", "蛋", "豆", "蝦", "肉",
                     "起司", "乳", "優格", "優酪"]
    if any(k in name for k in pro_keywords):
        return True
    return protein_per_pack >= 10.0


def main():
    out = Path("data/familymart_products_real.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    # phase 1: collect unique CMNOs by keyword search
    seen: Dict[str, Dict] = {}
    for kw in KEYWORDS:
        try:
            items = list_products(kw)
            for it in items:
                seen.setdefault(it["CMNO"], it)
            print(f"  keyword '{kw}': {len(items)} items   total unique={len(seen)}")
            time.sleep(0.15)
        except Exception as e:
            print(f"  WARN keyword '{kw}': {e}")
    print(f"=== {len(seen)} unique CMNOs ===")

    # phase 2: fetch details
    rows = []
    skipped = 0
    for i, (cmno, head) in enumerate(seen.items(), start=1):
        try:
            d = fetch_detail(cmno)
            if d is None:
                skipped += 1
                continue
            nut_list = d.get("NUTRIENTS") or []
            if not nut_list:
                skipped += 1
                continue
            nut = nut_list[0] or {}

            kcal_parse = parse_kcal_per_pack(d.get("NOTE", ""))
            if kcal_parse is None:
                skipped += 1
                continue
            kcal_per_serv, n_serv = kcal_parse
            kcal_per_pack = kcal_per_serv * n_serv

            # Convert per-serving nutrients to per-package
            def fnum(x):
                try: return float(x) if x is not None else 0.0
                except: return 0.0
            pro  = fnum(nut.get("PROTEIN")) * n_serv
            fat  = fnum(nut.get("TOTALFAT")) * n_serv
            carb = fnum(nut.get("CARBOHYDRATE")) * n_serv
            sug  = fnum(nut.get("SUGAR")) * n_serv
            sod  = fnum(nut.get("SODIUM")) * n_serv

            cat_id = str(d.get("CATEGORY_ID") or head.get("CATEGORY_ID") or "")
            cat_name = d.get("CATEGORY_NAME") or head.get("CATEGORY_NAME") or ""
            price = PRICE_BY_CATEGORY.get(cat_id, 40)

            name = d.get("PRODNAME") or head.get("PRODNAME") or ""
            rows.append({
                "product_id": i,
                "cmno": cmno,
                "name": name,
                "category_id": cat_id,
                "category": cat_name,
                "is_main": 1 if is_main_dish(cat_id, name) else 0,
                "is_protein": 1 if is_protein_source(cat_id, name, pro) else 0,
                "price": price,
                "calories": round(kcal_per_pack, 1),
                "protein":  round(pro,  2),
                "fat":      round(fat,  2),
                "carb":     round(carb, 2),
                "sugar":    round(sug,  2),
                "sodium":   round(sod,  1),
                "n_servings": n_serv,
            })
            if i % 20 == 0:
                print(f"  fetched {i}/{len(seen)}  rows={len(rows)} skipped={skipped}")
            time.sleep(0.10)
        except Exception as e:
            print(f"  WARN {cmno}: {e}")
            skipped += 1

    # write CSV
    keys = ["product_id", "cmno", "name", "category_id", "category",
            "is_main", "is_protein", "price",
            "calories", "protein", "fat", "carb", "sugar", "sodium", "n_servings"]
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"=== wrote {len(rows)} products to {out}  (skipped {skipped}) ===")


if __name__ == "__main__":
    main()
