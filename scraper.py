import asyncio
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, List, Optional

from playwright.async_api import async_playwright, Page, Browser

from config import Config

# Supress CMD windows on Windows
if sys.platform == "win32":
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
    _orig_Popen = subprocess.Popen

    class _PopenNoWindow(_orig_Popen):
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = _PopenNoWindow


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
STATUS_FINALIZADO = "Finalizado"
STATUS_AGENDADO = "Agendado"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

logger = logging.getLogger("Scraper")


# ---------------------------------------------------------------------------
# Modelo de dados
# ---------------------------------------------------------------------------
@dataclass
class Match:
    liga: str
    p1: str
    p2: str
    placar: str
    status: str

    def as_dict(self) -> dict[str, str]:
        return {
            "liga": self.liga,
            "p1": self.p1,
            "p2": self.p2,
            "placar": self.placar,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
class EAdriaticScraper:
    def __init__(self) -> None:
        self.url = Config.BASE_URL
        self.max_retries = Config.MAX_RETRIES
        self.retry_delay = Config.RETRY_DELAY

    # --- ciclo de vida do navegador ----------------------------------------

    async def _create_browser(self) -> tuple[Any, Browser, Page]:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=Config.HEADLESS)
        ctx = await browser.new_context(user_agent=USER_AGENT)
        page = await ctx.new_page()
        return pw, browser, page

    async def _close_browser(
        self, pw: Any, browser: Optional[Browser]
    ) -> None:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()

    # --- navegação ----------------------------------------------------------

    async def _load_page(self, page: Page) -> None:
        logger.info("Navegando para %s", self.url)
        await page.goto(self.url, wait_until="networkidle", timeout=30_000)
        await asyncio.sleep(Config.WAIT_TIME)

    # --- parsing -----------------------------------------------------------

    @staticmethod
    def _clean_score(raw: str) -> str:
        raw = re.sub(r"\(.*?\)", "", raw)
        return raw.replace("\n", "").replace(" ", "").strip()

    @staticmethod
    def _is_finished(score: str) -> bool:
        return "-" in score and score != "VS" and len(score) >= 3

    def _parse_score(self, raw: str) -> tuple[str, str]:
        score = self._clean_score(raw)
        status = STATUS_FINALIZADO if self._is_finished(score) else STATUS_AGENDADO
        return score, status

    # --- extração ----------------------------------------------------------

    async def _read_league(self, row) -> Optional[str]:
        elem = await row.query_selector("span.fg-heading")
        if elem:
            return (await elem.inner_text()).strip()
        return None

    async def _read_match_row(self, row, liga: str) -> Optional[Match]:
        href = await row.get_attribute("data-match-href")
        if not href:
            return None

        tds = await row.query_selector_all("td")
        if len(tds) < 3:
            return None

        p1_elem = await tds[0].query_selector("a")
        p2_elem = await tds[2].query_selector("a")
        if not p1_elem or not p2_elem:
            return None

        p1 = (await p1_elem.inner_text()).strip()
        p2 = (await p2_elem.inner_text()).strip()
        if not p1 or not p2:
            return None

        score_raw = (await tds[1].inner_text()).strip()
        placar, status = self._parse_score(score_raw)

        return Match(liga=liga, p1=p1, p2=p2, placar=placar, status=status)

    async def _extract_matches(self, page: Page) -> List[Match]:
        rows = await page.query_selector_all("tr")
        logger.info("Encontradas %d linhas na página", len(rows))

        matches: List[Match] = []
        liga_atual = "Desconhecida"

        for row in rows:
            try:
                league = await self._read_league(row)
                if league:
                    liga_atual = league
                    continue

                match = await self._read_match_row(row, liga_atual)
                if match:
                    matches.append(match)

            except Exception as exc:
                logger.debug("Erro ao processar linha: %s", exc)

        return matches

    # --- entrypoint --------------------------------------------------------

    async def scrape(self) -> List[dict[str, str]]:
        for attempt in range(1, self.max_retries + 1):
            pw, browser = None, None
            try:
                logger.info("Tentativa %d/%d", attempt, self.max_retries)
                pw, browser, page = await self._create_browser()
                await self._load_page(page)

                matches = await self._extract_matches(page)
                logger.info("%d partidas extraídas", len(matches))
                return [m.as_dict() for m in matches]

            except Exception as exc:
                logger.error("Tentativa %d falhou: %s", attempt, exc)
                if attempt < self.max_retries:
                    logger.info("Aguardando %ds...", self.retry_delay)
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.error("Todas as tentativas esgotadas")
                    raise
            finally:
                await self._close_browser(pw, browser)

        return []


# ---------------------------------------------------------------------------
# Execução standalone
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scraper = EAdriaticScraper()
    results = asyncio.run(scraper.scrape())
    for m in results:
        print(f"[{m['liga']}] {m['p1']} {m['placar']} {m['p2']} ({m['status']})")
