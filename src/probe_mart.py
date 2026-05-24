"""Use Playwright to capture all XHR/fetch calls made by mart.family.com.tw
when you load the category page. Goal: discover the real product-listing API
that returns prices."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    captured = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def on_response(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "json" in ct or "salepage" in url.lower() or "category" in url.lower():
                try:
                    body = await resp.text()
                    captured.append((url, resp.status, ct, body[:500]))
                except Exception:
                    captured.append((url, resp.status, ct, "<binary>"))

        page.on("response", on_response)
        # Category page: 美食/生鮮
        await page.goto("https://mart.family.com.tw/v2/official/SalePageCategory/118919",
                        wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Also try a single product detail page if one is found
        # Look for links to product details
        links = await page.eval_on_selector_all("a[href*='SalePage/']", "as => as.map(a => a.href).slice(0,5)")
        print("Product page links:")
        for l in links: print(" ", l)
        if links:
            await page.goto(links[0], wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

        await browser.close()

    print(f"\n=== {len(captured)} relevant responses captured ===")
    SKIP = ("google", "doubleclick", "facebook", "track", "tagmanager",
            "fbcdn", "91app.io", "googleadservices", "rmkt", "TraceSalePageList",
            "GetShopPayType", "GetEnableDisplay", "GetShopAvailLanguages",
            "Auth/IsLogin", "ShoppingCart")
    for url, status, ct, body in captured:
        if any(s in url for s in SKIP): continue
        if "json" not in ct: continue
        print(f"\n[{status}] {url}")
        print(f"  body[:600]: {body}")


if __name__ == "__main__":
    asyncio.run(main())
