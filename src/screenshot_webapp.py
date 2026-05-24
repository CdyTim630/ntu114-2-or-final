"""Capture screenshots of the running web app for the report/slides."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent.parent / "results" / "figs"
OUT.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,
        )
        page = await ctx.new_page()

        # 1) empty form
        await page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUT / "webapp_form.png"), full_page=True)
        print("wrote webapp_form.png")

        # 2) fill the form and submit
        await page.select_option("select[name=sex]", "M")
        await page.fill("input[name=age]", "22")
        await page.fill("input[name=height]", "175")
        await page.fill("input[name=weight]", "70")
        await page.select_option("select[name=activity]", "mid")
        await page.select_option("select[name=goal]", "cut")
        await page.select_option("select[name=scenario]", "regular")
        await page.fill("input[name=budget]", "120")
        async with page.expect_response("**/api/recommend") as resp:
            await page.click("button.primary")
        r = await resp.value
        body = await r.json()
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "webapp_result.png"), full_page=True)
        print("wrote webapp_result.png  (recommend ok=", body.get("ok"), ")")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
