import asyncio
import logging
import sys
from typing import Dict, List

from config import Config
from scraper import EAdriaticScraper
from sheets_client import SheetsClient
from dashboard import generate_dashboard


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_handlers: list = [logging.FileHandler("robo.log", encoding="utf-8")]
if sys.stdout:
    _log_handlers.insert(0, logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger("Main")


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------
def validate_matches(matches: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [m for m in matches if m.get("p1") and m.get("p2")]


# ---------------------------------------------------------------------------
# Resumo no terminal
# ---------------------------------------------------------------------------
def print_summary(matches: List[Dict[str, str]], novos: int) -> None:
    total = len(matches)
    finalizados = sum(1 for m in matches if m["status"] == "Finalizado")
    agendados = total - finalizados
    ligas: Dict[str, int] = {}
    for m in matches:
        ligas[m["liga"]] = ligas.get(m["liga"], 0) + 1

    print()
    print("=" * 50)
    print("  RESUMO DA EXECUCAO")
    print("=" * 50)
    print(f"  Partidas raspadas:     {total}")
    print(f"  |- Finalizadas:        {finalizados}")
    print(f"  \\- Agendadas:          {agendados}")
    print(f"  Novas (BASE_DIARIA):   {novos}")
    print(f"  Ligas:                 {len(ligas)}")
    print("-" * 50)
    for liga, count in sorted(ligas.items()):
        print(f"  * {liga}: {count}")
    print("=" * 50)


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
async def main() -> None:
    logger.info("=== Iniciando Robo eAdriatic League ===")

    scraper = EAdriaticScraper()
    try:
        matches = await scraper.scrape()
    except Exception as exc:
        logger.error("Scraping falhou: %s", exc, exc_info=True)
        return

    if not matches:
        logger.warning("Nenhuma partida encontrada")
        return

    valid = validate_matches(matches)
    if not valid:
        logger.warning("Nenhuma partida valida apos validacao")
        return

    try:
        sheets = SheetsClient()

        logger.info("-> BASE_DIARIA")
        novos = sheets.update_base_diaria(valid)

        logger.info("-> JOGOS_DO_DIA")
        sheets.update_jogos_do_dia(valid)

        logger.info("-> RESUMO_POR_LIGA")
        sheets.update_resumo(valid)

        logger.info("-> CLASSIFICACAO_POR_LIGA")
        sheets.update_classificacao(valid)

        logger.info("-> DASHBOARD (data.json)")
        generate_dashboard(valid)

        logger.info("=== Concluido com sucesso ===")
        print_summary(valid, novos)

    except Exception as exc:
        logger.error("Erro ao sincronizar: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
