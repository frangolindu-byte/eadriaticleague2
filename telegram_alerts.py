"""
Telegram Bot de Alertas de Apostas
Envia alertas automaticos para canal/grupo do Telegram quando
detecta oportunidades de CONFIANCA ALTA.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List
from urllib.request import Request, urlopen

from config import Config

logger = logging.getLogger("TelegramAlerts")

# ============================================================
# Telegram API (sem dependencias externas)
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """Envia mensagem para o canal/grupo do Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID nao configurados")
        return False

    url = f"{TELEGRAM_URL}/sendMessage"
    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=15)
        result = json.loads(response.read().decode())
        if result.get("ok"):
            logger.info("Alerta enviado com sucesso")
            return True
        else:
            logger.error("Erro Telegram: %s", result.get("description"))
            return False
    except Exception as e:
        logger.error("Falha ao enviar mensagem: %s", e)
        return False


def send_photo(caption: str, photo_url: str = None) -> bool:
    """Envia foto com legenda (opcional)."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False

    url = f"{TELEGRAM_URL}/sendPhoto"
    data = json.dumps({
        "chat_id": CHAT_ID,
        "caption": caption,
        "parse_mode": "HTML",
    }).encode("utf-8")

    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=15)
        return json.loads(response.read().decode()).get("ok", False)
    except Exception as e:
        logger.error("Falha ao enviar foto: %s", e)
        return False


# ============================================================
# Analise de Confrontos (mesma logica do create_betting_sheet)
# ============================================================

import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_data():
    """Puxa dados da BASE_DIARIA."""
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


def calc_h2h(matches, p1, p2):
    total = 0
    w1 = 0
    w2 = 0
    draws = 0
    goals = []

    for m in matches:
        if m["status"] != "Finalizado":
            continue
        if not ((m["p1"] == p1 and m["p2"] == p2) or (m["p1"] == p2 and m["p2"] == p1)):
            continue
        score = parse_score(m["placar"])
        if not score:
            continue
        g1, g2 = score
        goals.append(g1 + g2)
        total += 1

        if m["p1"] == p1:
            if g1 > g2:
                w1 += 1
            elif g2 > g1:
                w2 += 1
            else:
                draws += 1
        else:
            if g2 > g1:
                w1 += 1
            elif g1 > g2:
                w2 += 1
            else:
                draws += 1

    return {
        "total": total,
        "w1": w1,
        "w2": w2,
        "draws": draws,
        "media_gols": round(sum(goals) / len(goals), 1) if goals else 0,
    }


def find_high_confidence_alerts(matches):
    """Encontra jogos agendados com confianca ALTA."""
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

        h2h = calc_h2h(matches, p1, p2)

        score = 0
        reasons = []

        # Over 2.5
        over25_avg = (o25_1 + o25_2) / 2 if j1 >= 3 and j2 >= 3 else 94.7
        if over25_avg >= 95:
            score += 40
            reasons.append(f"Over 2.5: {over25_avg:.0f}%")
        elif over25_avg >= 90:
            score += 25
            reasons.append(f"Over 2.5: {over25_avg:.0f}%")

        # BTTS
        btts_avg = (btts_1 + btts_2) / 2 if j1 >= 3 and j2 >= 3 else 91.9
        if btts_avg >= 90:
            score += 25
            reasons.append(f"BTTS: {btts_avg:.0f}%")

        # Win rate diff
        if j1 >= 5 and j2 >= 5:
            diff = abs(wr1 - wr2)
            if diff >= 30:
                score += 20
                fav = p1 if wr1 > wr2 else p2
                fav_wr = max(wr1, wr2)
                reasons.append(f"Vitoria {fav} (WR {fav_wr:.0f}%)")

        # H2H
        if h2h["total"] >= 2 and h2h["media_gols"] > 7:
            score += 10
            reasons.append(f"H2H: {h2h['media_gols']} gols media")

        # Forma
        if fw1 >= 4 and j1 >= 5:
            score += 5
        if fw2 >= 4 and j2 >= 5:
            score += 5

        # Contra fracos
        if wr1 < 15 and j1 >= 5:
            score += 10
        if wr2 < 15 and j2 >= 5:
            score += 10

        if score >= 70:
            fav = p1 if wr1 > wr2 else p2
            fav_wr = max(wr1, wr2)
            zebra = p2 if wr1 > wr2 else p1
            zebra_wr = min(wr1, wr2)
            avg_goals = (media1 + gc2 + media2 + gc1) / 2 if j1 >= 3 and j2 >= 3 else 6.5

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
                "h2h": h2h,
                "form1": form1,
                "form2": form2,
                "fav": fav,
                "fav_wr": fav_wr,
                "zebra": zebra,
                "zebra_wr": zebra_wr,
                "score": score,
                "reasons": reasons,
            })

    return sorted(alerts, key=lambda x: x["score"], reverse=True)


# ============================================================
# Formatacao das Mensagens
# ============================================================

def format_alert_message(alert: Dict[str, Any]) -> str:
    """Formata mensagem de alerta unico."""
    emoji_conf = "🟢" if alert["score"] >= 90 else "🟡"

    h2h_text = ""
    if alert["h2h"]["total"] > 0:
        h2h_text = (
            f"\n📊 <b>H2H ({alert['h2h']['total']} jogos):</b>\n"
            f"   {alert['h2h']['media_gols']} gols de media"
        )

    reasons_text = "\n".join([f"   ✅ {r}" for r in alert["reasons"]])

    msg = (
        f"🚨 <b>ALERTA DE APOSTA - CONFIANCA ALTA</b> {emoji_conf}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{alert['p1']}</b> vs <b>{alert['p2']}</b>\n"
        f"🏆 {alert['liga']}\n\n"
        f"📈 <b>Estatisticas:</b>\n"
        f"   {alert['p1']}: WR {alert['wr1']:.0f}% ({alert['j1']} jogos) | Forma: {alert['form1']}\n"
        f"   {alert['p2']}: WR {alert['wr2']:.0f}% ({alert['j2']} jogos) | Forma: {alert['form2']}\n"
        f"   Over 2.5: {alert['over25']:.0f}% | BTTS: {alert['btts']:.0f}%\n"
        f"   Media estimada: {alert['avg_goals']:.1f} gols{h2h_text}\n\n"
        f"💡 <b>Recomendacoes:</b>\n"
        f"{reasons_text}\n\n"
        f"🎯 <b>Dica Principal:</b>\n"
        f"   Over 2.5 Gols + Vitoria {alert['fav']}\n\n"
        f"⚠️ <i>Aposte com responsabilidade. Gerencie sua banca.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg


def format_daily_summary(alerts: List[Dict[str, Any]]) -> str:
    """Resumo diario com todos os alertas."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    msg = (
        f"📋 <b>RESUMO DIARIO DE OPORTUNIDADES</b>\n"
        f"🕐 {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 <b>{len(alerts)} oportunidades de ALTA confianca detectadas</b>\n\n"
    )

    for i, a in enumerate(alerts[:10], 1):
        emoji = "🟢" if a["score"] >= 90 else "🟡"
        msg += (
            f"{emoji} <b>{i}. {a['p1']} vs {a['p2']}</b>\n"
            f"   WR: {a['wr1']:.0f}% vs {a['wr2']:.0f}% | Over 2.5: {a['over25']:.0f}%\n"
            f"   Dica: Over 2.5 + Vitoria {a['fav']}\n\n"
        )

    if len(alerts) > 10:
        msg += f"   ...e mais {len(alerts) - 10} oportunidades\n\n"

    msg += (
        f"⚠️ <i>Aposte com responsabilidade.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg


# ============================================================
# Controle de Alertas Enviados (evita duplicatas)
# ============================================================

ALERTS_FILE = "sent_alerts.json"


def load_sent_alerts() -> set:
    if os.path.exists(ALERTS_FILE):
        with open(ALERTS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_sent_alerts(alerts: set):
    with open(ALERTS_FILE, "w") as f:
        json.dump(list(alerts), f)


def get_alert_key(alert: Dict) -> str:
    """Chave unica para cada alerta (liga + jogadores)."""
    players = sorted([alert["p1"], alert["p2"]])
    return f"{alert['liga']}|{players[0]}|{players[1]}"


# ============================================================
# Main
# ============================================================

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERRO: Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nas variaveis de ambiente")
        return

    print("Buscando dados...")
    matches = get_data()
    agendados = [m for m in matches if m["status"] == "Agendado"]
    print(f"  {len(agendados)} jogos agendados encontrados")

    print("Analisando oportunidades...")
    alerts = find_high_confidence_alerts(matches)
    print(f"  {len(alerts)} oportunidades de ALTA confianca")

    if not alerts:
        print("Nenhum alerta de alta confianca no momento.")
        return

    # Carrega alertas ja enviados
    sent = load_sent_alerts()
    new_alerts = []

    for alert in alerts:
        key = get_alert_key(alert)
        if key not in sent:
            new_alerts.append(alert)
            sent.add(key)

    if not new_alerts:
        print("Todos os alertas ja foram enviados anteriormente.")
        return

    # Envia alertas individuais
    print(f"\nEnviando {len(new_alerts)} novos alertas...")
    for i, alert in enumerate(new_alerts, 1):
        msg = format_alert_message(alert)
        success = send_telegram_message(msg)
        status = "OK" if success else "FALHOU"
        print(f"  [{i}/{len(new_alerts)}] {alert['p1']} vs {alert['p2']} - {status}")
        time.sleep(1)  # Evita rate limit

    # Envia resumo
    if len(new_alerts) > 1:
        summary = format_daily_summary(new_alerts)
        send_telegram_message(summary)
        print("  Resumo diario enviado")

    # Salva estado
    save_sent_alerts(sent)
    print(f"\nTotal de alertas enviados: {len(new_alerts)}")


if __name__ == "__main__":
    main()
