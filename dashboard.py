import datetime
import json
import logging
import os
from typing import Any, Dict, List

from config import Config

logger = logging.getLogger("Dashboard")

STATUS_FINALIZADO = "Finalizado"


def _calc_classificacao(data: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
    ligas: Dict[str, Dict[str, Dict[str, int]]] = {}

    for item in data:
        if item.get("status") != STATUS_FINALIZADO:
            continue

        liga = item.get("liga", "Desconhecida")
        p1 = item.get("p1", "")
        p2 = item.get("p2", "")
        placar = item.get("placar", "")

        if not p1 or not p2 or "-" not in placar:
            continue

        try:
            gols = placar.split("-")
            g1, g2 = int(gols[0]), int(gols[1])
        except (ValueError, IndexError):
            continue

        if liga not in ligas:
            ligas[liga] = {}

        for jogador in [p1, p2]:
            if jogador not in ligas[liga]:
                ligas[liga][jogador] = {
                    "J": 0, "V": 0, "E": 0, "D": 0,
                    "GP": 0, "GC": 0, "Pts": 0,
                }

        ligas[liga][p1]["J"] += 1
        ligas[liga][p1]["GP"] += g1
        ligas[liga][p1]["GC"] += g2
        ligas[liga][p2]["J"] += 1
        ligas[liga][p2]["GP"] += g2
        ligas[liga][p2]["GC"] += g1

        if g1 > g2:
            ligas[liga][p1]["V"] += 1
            ligas[liga][p1]["Pts"] += 3
            ligas[liga][p2]["D"] += 1
        elif g2 > g1:
            ligas[liga][p2]["V"] += 1
            ligas[liga][p2]["Pts"] += 3
            ligas[liga][p1]["D"] += 1
        else:
            ligas[liga][p1]["E"] += 1
            ligas[liga][p1]["Pts"] += 1
            ligas[liga][p2]["E"] += 1
            ligas[liga][p2]["Pts"] += 1

    resultado: Dict[str, List[Dict]] = {}
    for liga, jogadores in ligas.items():
        tabela = []
        for nome, s in jogadores.items():
            sg = s["GP"] - s["GC"]
            tabela.append({
                "nome": nome,
                "Pts": s["Pts"],
                "J": s["J"],
                "V": s["V"],
                "E": s["E"],
                "D": s["D"],
                "GP": s["GP"],
                "GC": s["GC"],
                "SG": sg,
            })
        tabela.sort(key=lambda x: (x["Pts"], x["SG"], x["GP"]), reverse=True)
        for i, row in enumerate(tabela, 1):
            row["pos"] = i
        resultado[liga] = tabela

    return resultado


def _calc_resumo(data: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    resumo: Dict[str, Dict[str, int]] = {}
    for item in data:
        liga = item.get("liga", "Desconhecida")
        if liga not in resumo:
            resumo[liga] = {"total": 0, "finalizados": 0, "agendados": 0}
        resumo[liga]["total"] += 1
        if item.get("status") == STATUS_FINALIZADO:
            resumo[liga]["finalizados"] += 1
        else:
            resumo[liga]["agendados"] += 1
    return resumo


def generate_dashboard(data: List[Dict[str, Any]], output_dir: str = "docs") -> str:
    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    payload = {
        "updated_at": now,
        "summary": {
            "total": len(data),
            "finalizados": sum(1 for m in data if m["status"] == STATUS_FINALIZADO),
            "agendados": sum(1 for m in data if m["status"] != STATUS_FINALIZADO),
            "ligas": len(set(m.get("liga", "") for m in data)),
        },
        "jogos": [
            {
                "liga": m.get("liga", ""),
                "p1": m.get("p1", ""),
                "p2": m.get("p2", ""),
                "placar": m.get("placar", ""),
                "status": m.get("status", ""),
            }
            for m in data
        ],
        "resumo": _calc_resumo(data),
        "classificacao": _calc_classificacao(data),
    }

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info("Dashboard JSON gerado: %s (%d partidas)", path, len(data))
    return path
