import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Alvo ───────────────────────────────────────────────────────────────
    BASE_URL = "https://eadriaticleague2.leaguerepublic.com/index.html"

    # ── Google Sheets ──────────────────────────────────────────────────────
    SPREADSHEET_ID = "15wDWF7T7WNUiYZsXifGgkThad7rseExGhxRVUEAy7JQ"
    CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "credentials.json")

    TAB_BASE_DIARIA = "BASE_DIARIA"
    TAB_RESUMO = "RESUMO_POR_LIGA"
    TAB_JOGOS_DIA = "JOGOS_DO_DIA"
    TAB_CLASSIFICACAO = "CLASSIFICACAO_POR_LIGA"

    # ── Scraper ────────────────────────────────────────────────────────────
    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    WAIT_TIME = int(os.getenv("WAIT_TIME", "5"))

    # ── Retry ──────────────────────────────────────────────────────────────
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY = int(os.getenv("RETRY_DELAY", "10"))
