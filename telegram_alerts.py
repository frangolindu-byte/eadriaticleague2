"""
Telegram Bot de Alertas de Apostas - Versao Melhorada
- Envia alertas com % de assertividade
- Salva message_id para atualizacao posterior
- Atualiza com ✅ (bateu) ou 🔥 (nao bateu)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List
from urllib.request import Request, urlopen
from urllib.error import URLError

import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict

from config import Config

logger = logging.getLogger("TelegramAlerts")

# ============================================================
# Telegram API
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

ALERTS_FILE = "sent_alerts.json"


def telegram_request(method: str, data: dict) -> dict | None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return None
    url = f"{TELEGRAM_URL}/{method}"
    req = Request(url, json.dumps(data).encode("utf-8"), {"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except Exception as e:
        logger.error("Telegram API error: %s", e)
        return None


def send_message(text: str) -> int | None:
    result = telegram_request("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


def edit_message(message_id: int, new_text: str) -> bool:
    result = telegram_request("editMessageText", {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    return result.get("ok", False) if result else False


# ============================================================
# Analise
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_data():
    creds = Credentials.from_service_account_file(
        Config.CREDENTIALS_PATH, scopes=SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(Config.SPREADSHEET_ID)
    ws = spreadsheet.worksheet(Config.TAB_BASE_DIARIA)
    rows = ws.get_all_values()
    data = []
    for row in rows[1:]:
        if len(row) < 6:
            continue
        data.append({
            "data": row[0],
            "liga": row[1],
            "p1": row[2],
            "placar": row[3],
            "p2": row[4],
            "status": row[5],
        })
    return data


def parse_score(placar):
    if not placar or "-" not in placar:
        return None
    try:
        g1, g2 = placar.split("-")
        return int(g1), int(g2)
    except (ValueError, IndexError):
        return None


def calc_player_stats(matches):
    stats = defaultdict(lambda: {
        "W": 0, "D": 0, "L": 0, "GP": 0, "GC": 0, "J": 0,
        "over25": 0, "btts": 0, "form": [],
    })
    for m in matches:
        if m["status"] != "Finalizado":
            continue
        score = parse_score(m["placar"])
        if not score:
            continue
        g1, g2 = score
        total = g1 + g2
        for p, gp, gc in [(m["p1"], g1, g2), (m["p2"], g2, g1)]:
            s = stats[p]
            s["J"] += 1
            s["GP"] += gp
            s["GC"] += gc
            if total > 2.5:
                s["over25"] += 1
            if gp > 0 and gc > 0:
                s["btts"] += 1
            if gp > gc:
                s["W"] += 1
                s["form"].append("W")
            elif gp < gc:
                s["L"] += 1
                s["form"].append("L")
            else:
                s["D"] += 1
                s["form"].append("D")

    results = {}
    for player, s in stats.items():
        if s["J"] < 3:
            continue
        wr = s["W"] / s["J"] * 100
        recent = s["form"][-5:]
        results[player] = {
            "jogos": s["J"],
            "win_rate": round(wr, 1),
            "over25_pct": round(s["over25"] / s["J"] * 100, 1),
            "btts_pct": round(s["btts"] / s["J"] * 100, 1),
            "media_gp": round(s["GP"] / s["J"], 2),
            "media_gc": round(s["GC"] / s["J"], 2),
            "forma": "-".join(recent),
            "forma_wins": recent.count("W"),
        }
    return results


def find_alerts(matches):
    player_stats = calc_player_stats(matches)
    upcoming = [m for m in matches if m["status"] == "Agendado"]
    alerts = []

    for m in upcoming:
        p1, p2 = m["p1"], m["p2"]
        s1 = player_stats.get(p1, {})
        s2 = player_stats.get(p2, {})
        j1 = s1.get("jogos", 0)
        j2 = s2.get("jogos", 0)
        wr1 = s1.get("win_rate", 50)
        wr2 = s2.get("win_rate", 50)
        o25_1 = s1.get("over25_pct", 0)
        o25_2 = s2.get("over25_pct", 0)
        btts_1 = s1.get("btts_pct", 0)
        btts_2 = s2.get("btts_pct", 0)
        media1 = s1.get("media_gp", 0)
        media2 = s2.get("media_gp", 0)
        gc1 = s1.get("media_gc", 0)
        gc2 = s2.get("media_gc", 0)
        form1 = s1.get("forma", "N/A")
        form2 = s2.get("forma", "N/A")
        fw1 = s1.get("forma_wins", 0)
        fw2 = s2.get("forma_wins", 0)

        score = 0
        reasons = []

        over25_avg = (o25_1 + o25_2) / 2 if j1 >= 3 and j2 >= 3 else 94.7
        if over25_avg >= 95:
            score += 40
            reasons.append(f"Over 2.5: {over25_avg:.0f}%")
        elif over25_avg >= 90:
            score += 25
            reasons.append(f"Over 2.5: {over25_avg:.0f}%")

        btts_avg = (btts_1 + btts_2) / 2 if j1 >= 3 and j2 >= 3 else 91.9
        if btts_avg >= 90:
            score += 25
            reasons.append(f"BTTS: {btts_avg:.0f}%")

        if j1 >= 5 and j2 >= 5:
            diff = abs(wr1 - wr2)
            if diff >= 30:
                score += 20
                fav = p1 if wr1 > wr2 else p2
                fav_wr = max(wr1, wr2)
                reasons.append(f"Vitoria {fav} (WR {fav_wr:.0f}%)")

        if wr1 < 15 and j1 >= 5:
            score += 10
        if wr2 < 15 and j2 >= 5:
            score += 10

        if fw1 >= 4 and j1 >= 5:
            score += 5
        if fw2 >= 4 and j2 >= 5:
            score += 5

        if score >= 70:
            fav = p1 if wr1 > wr2 else p2
            fav_wr = max(wr1, wr2)
            avg_goals = (media1 + gc2 + media2 + gc1) / 2 if j1 >= 3 and j2 >= 3 else 6.5

            win_prob = fav_wr / 100.0
            over_prob = min(over25_avg / 100.0, 1.0)
            btts_prob = min(btts_avg / 100.0, 1.0)
            assertividade = (over_prob * 0.40 + win_prob * 0.35 + btts_prob * 0.25) * 100

            alerts.append({
                "liga": m["liga"],
                "p1": p1,
                "p2": p2,
                "wr1": wr1,
                "wr2": wr2,
                "j1": j1,
                "j2": j2,
                "over25": over25_avg,
                "btts": btts_avg,
                "avg_goals": avg_goals,
                "form1": form1,
                "form2": form2,
                "fav": fav,
                "fav_wr": fav_wr,
                "score": score,
                "reasons": reasons,
                "assertividade": round(assertividade, 1),
            })

    return sorted(alerts, key=lambda x: x["score"], reverse=True)


# ============================================================
# Formatacao
# ============================================================

def format_alert(alert: Dict) -> str:
    emoji = "🟢" if alert["score"] >= 90 else "🟡"
    reasons_text = "\n".join([f"   ✅ {r}" for r in alert["reasons"]])

    msg = (
        f"🚨 <b>ALERTA DE APOSTA</b> {emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{alert['p1']}</b> vs <b>{alert['p2']}</b>\n"
        f"🏆 {alert['liga']}\n\n"
        f"📊 <b>Assertividade: {alert['assertividade']:.1f}%</b>\n\n"
        f"📈 <b>Estatisticas:</b>\n"
        f"   {alert['p1']}: WR {alert['wr1']:.0f}% ({alert['j1']}j) | Forma: {alert['form1']}\n"
        f"   {alert['p2']}: WR {alert['wr2']:.0f}% ({alert['j2']}j) | Forma: {alert['form2']}\n"
        f"   Over 2.5: {alert['over25']:.0f}% | BTTS: {alert['btts']:.0f}%\n"
        f"   Media estimada: {alert['avg_goals']:.1f} gols\n\n"
        f"💡 <b>Recomendacoes:</b>\n"
        f"{reasons_text}\n\n"
        f"🎯 <b>Dica:</b> Over 2.5 + Vitoria {alert['fav']}\n\n"
        f"⏳ <i>Aguardando resultado...</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg


def format_result_update(alert: Dict, placar: str, bateu: bool) -> str:
    emoji = "🟢" if alert["score"] >= 90 else "🟡"
    reasons_text = "\n".join([f"   ✅ {r}" for r in alert["reasons"]])

    if bateu:
        result_icon = "✅"
        result_text = "GREEN! Aposta bateu!"
    else:
        result_icon = "🔥"
        result_text = "RED! Nao bateu."

    msg = (
        f"🚨 <b>ALERTA DE APOSTA</b> {emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{alert['p1']}</b> vs <b>{alert['p2']}</b>\n"
        f"🏆 {alert['liga']}\n\n"
        f"📊 <b>Assertividade: {alert['assertividade']:.1f}%</b>\n\n"
        f"📈 <b>Estatisticas:</b>\n"
        f"   {alert['p1']}: WR {alert['wr1']:.0f}% ({alert['j1']}j) | Forma: {alert['form1']}\n"
        f"   {alert['p2']}: WR {alert['wr2']:.0f}% ({alert['j2']}j) | Forma: {alert['form2']}\n"
        f"   Over 2.5: {alert['over25']:.0f}% | BTTS: {alert['btts']:.0f}%\n"
        f"   Media estimada: {alert['avg_goals']:.1f} gols\n\n"
        f"💡 <b>Recomendacoes:</b>\n"
        f"{reasons_text}\n\n"
        f"🎯 <b>Dica:</b> Over 2.5 + Vitoria {alert['fav']}\n\n"
        f"{result_icon} <b>{result_text}</b>\n"
        f"   Placar final: <b>{placar}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg


# ============================================================
# Persistencia
# ============================================================

def load_json(filepath: str) -> list:
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return []


def save_json(filepath: str, data: list):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def get_alert_key(alert: Dict) -> str:
    players = sorted([alert["p1"], alert["p2"]])
    return f"{alert['liga']}|{players[0]}|{players[1]}"


# ============================================================
# Main - Enviar Alertas
# ============================================================

def send_alerts():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERRO: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nao configurados")
        return

    print("Buscando dados...")
    matches = get_data()
    agendados = [m for m in matches if m["status"] == "Agendado"]
    print(f"  {len(agendados)} jogos agendados")

    print("Analisando oportunidades...")
    alerts = find_alerts(matches)
    print(f"  {len(alerts)} oportunidades de ALTA confianca")

    if not alerts:
        print("Nenhum alerta novo.")
        return

    sent = load_json(ALERTS_FILE)
    sent_keys = {s.get("key", "") for s in sent}

    new_alerts = []
    for alert in alerts:
        key = get_alert_key(alert)
        if key not in sent_keys:
            alert["key"] = key
            new_alerts.append(alert)

    if not new_alerts:
        print("Todos os alertas ja foram enviados.")
        return

    print(f"\nEnviando {len(new_alerts)} alertas...")
    for i, alert in enumerate(new_alerts, 1):
        msg = format_alert(alert)
        msg_id = send_message(msg)
        if msg_id:
            alert["message_id"] = msg_id
            sent.append(alert)
            print(f"  [{i}/{len(new_alerts)}] {alert['p1']} vs {alert['p2']} - ENVIADO (msg_id={msg_id})")
        else:
            print(f"  [{i}/{len(new_alerts)}] {alert['p1']} vs {alert['p2']} - FALHOU")
        time.sleep(1.5)

    save_json(ALERTS_FILE, sent)
    print(f"\nTotal enviados: {len(new_alerts)}")


# ============================================================
# Main - Atualizar Resultados
# ============================================================

def update_results():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram nao configurado.")
        return

    print("Buscando dados para atualizar resultados...")
    matches = get_data()
    finalizados = {}
    for m in matches:
        if m["status"] == "Finalizado":
            finalizados[m["p1"] + "|" + m["p2"]] = m
            finalizados[m["p2"] + "|" + m["p1"]] = m

    sent = load_json(ALERTS_FILE)
    updated_count = 0

    for alert in sent:
        if alert.get("result_checked"):
            continue

        key = alert.get("key", "")
        parts = key.split("|")
        if len(parts) < 3:
            continue

        p1 = parts[1]
        p2 = parts[2]

        result_match = finalizados.get(p1 + "|" + p2)
        if not result_match:
            continue

        placar = result_match["placar"]
        score = parse_score(placar)
        if not score:
            alert["result_checked"] = True
            continue

        g1, g2 = score
        total_goals = g1 + g2
        fav = alert["fav"]
        fav_is_p1 = fav == p1
        fav_goals = g1 if fav_is_p1 else g2
        underdog_goals = g2 if fav_is_p1 else g1

        over25_hit = total_goals > 2.5
        fav_win = fav_goals > underdog_goals
        bateu = over25_hit and fav_win

        msg_id = alert.get("message_id")
        if msg_id:
            new_msg = format_result_update(alert, placar, bateu)
            success = edit_message(msg_id, new_msg)
            if success:
                print(f"  {'✅ GREEN' if bateu else '🔥 RED'}: {p1} vs {p2} = {placar}")
            else:
                print(f"  ⚠️ Falha ao editar: {p1} vs {p2}")

        alert["result_checked"] = True
        alert["result_placar"] = placar
        alert["result_status"] = "bateu" if bateu else "errou"
        updated_count += 1

    save_json(ALERTS_FILE, sent)
    print(f"Resultados atualizados: {updated_count}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update_results()
    else:
        send_alerts()


if __name__ == "__main__":
    main()
