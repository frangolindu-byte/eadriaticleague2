import asyncio
import logging
from playwright.async_api import async_playwright
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Debug")


async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=Config.HEADLESS)
        page = await browser.new_page()

        logger.info(f"Acessando {Config.BASE_URL}...")
        await page.goto(Config.BASE_URL, wait_until="networkidle")
        await asyncio.sleep(Config.WAIT_TIME)

        title = await page.title()
        logger.info(f"Título: {title}")

        content = await page.content()
        logger.info(f"Tamanho do conteúdo: {len(content)} caracteres")

        with open("page_debug.html", "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("HTML salvo em page_debug.html")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug())
