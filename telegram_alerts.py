"""
Telegram Bot de Alertas de Apostas
- Só envia jogos que AINDA NÃO COMEÇARAM (status == "Agendado")
- Mostra % de assertividade
- Atualiza mensagem com ✅ GREEN ou 🔥 RED após resultado
"""

import json
import os
import sys
import time
from urllib.request import Request, urlopen

import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict

from config import Config

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
ALERTS_FILE = "sent_alerts.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ============================================================
# Telegram
# ============================================================

def tg(method, data):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return None
    url = f"{TELEGRAM_URL}/{method}"
    req = Request(url, json.dumps(data).encode(), {"Content-Type": "application/json"})
    try:
        return json.loads(urlopen(req, timeout=15).read())
    except Exception as e:
        print(f"  Telegram error: {e}")
        return None


def send_msg(text):
    r = tg("sendMessage", {
        "chat_id": CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    })
    return r["result"]["message_id"] if r and r.get("ok") else None


def edit_msg(msg_id, text):
    r = tg("editMessageText", {
        "chat_id": CHAT_ID, "message_id": msg_id,
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    })
    return r.get("ok", False) if r else False


# ============================================================
# Dados
# ============================================================

def get_matches():
    creds = Credentials.from_service_account_file(Config.CREDENTIALS_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_key(Config.SPREADSHEET_ID).worksheet(Config.TAB_BASE_DIARIA)
    rows = ws.get_all_values()
    data = []
    for row in rows[1:]:
        if len(row) >= 6:
            data.append({
                "data": row[0], "liga": row[1],
                "p1": row[2], "placar": row[3],
                "p2": row[4], "status": row[5],
            })
    return data


def parse_score(placar):
    if not placar or "-" not in placar:
        return None
    try:
        a, b = placar.split("-")
        return int(a), int(b)
    except (ValueError, IndexError):
        return None


def player_stats(matches):
    s = defaultdict(lambda: {"W": 0, "D": 0, "L": 0, "GP": 0, "GC": 0, "J": 0, "o25": 0, "btts": 0, "form": []})
    for m in matches:
        if m["status"] != "Finalizado":
            continue
        sc = parse_score(m["placar"])
        if not sc:
            continue
        g1, g2 = sc
        for p, gp, gc in [(m["p1"], g1, g2), (m["p2"], g2, g1)]:
            x = s[p]
            x["J"] += 1; x["GP"] += gp; x["GC"] += gc
            if g1 + g2 > 2.5: x["o25"] += 1
            if gp > 0 and gc > 0: x["btts"] += 1
            if gp > gc: x["W"] += 1; x["form"].append("W")
            elif gp < gc: x["L"] += 1; x["form"].append("L")
            else: x["D"] += 1; x["form"].append("D")

    out = {}
    for p, x in s.items():
        if x["J"] < 3: continue
        f = x["form"][-5:]
        out[p] = {
            "J": x["J"], "WR": round(x["W"] / x["J"] * 100, 1),
            "o25": round(x["o25"] / x["J"] * 100, 1),
            "btts": round(x["btts"] / x["J"] * 100, 1),
            "gp": round(x["GP"] / x["J"], 2), "gc": round(x["GC"] / x["J"], 2),
            "form": "-".join(f), "fw": f.count("W"),
        }
    return out


# ============================================================
# Alertas
# ============================================================

def find_alerts(matches):
    ps = player_stats(matches)
    upcoming = [m for m in matches if m["status"] == "Agendado"]
    print(f"  Jogos Agendados (nao comecaram): {len(upcoming)}")

    alerts = []
    for m in upcoming:
        p1, p2 = m["p1"], m["p2"]
        a, b = ps.get(p1, {}), ps.get(p2, {})
        j1, j2 = a.get("J", 0), b.get("J", 0)
        w1, w2 = a.get("WR", 50), b.get("WR", 50)
        o1, o2 = a.get("o25", 0), b.get("o25", 0)
        bt1, bt2 = a.get("btts", 0), b.get("btts", 0)
        f1, f2 = a.get("form", "N/A"), b.get("form", "N/A")
        gp1, gp2 = a.get("gp", 0), b.get("gp", 0)
        gc1, gc2 = a.get("gc", 0), b.get("gc", 0)

        score = 0
        reasons = []

        o25 = (o1 + o2) / 2 if j1 >= 3 and j2 >= 3 else 94.7
        if o25 >= 95: score += 40; reasons.append(f"Over 2.5: {o25:.0f}%")
        elif o25 >= 90: score += 25; reasons.append(f"Over 2.5: {o25:.0f}%")

        btts = (bt1 + bt2) / 2 if j1 >= 3 and j2 >= 3 else 91.9
        if btts >= 90: score += 25; reasons.append(f"BTTS: {btts:.0f}%")

        if j1 >= 5 and j2 >= 5:
            diff = abs(w1 - w2)
            if diff >= 30:
                fav = p1 if w1 > w2 else p2
                score += 20
                reasons.append(f"Vitoria {fav} (WR {max(w1,w2):.0f}%)")

        if w1 < 15 and j1 >= 5: score += 10
        if w2 < 15 and j2 >= 5: score += 10

        if score >= 70:
            fav = p1 if w1 > w2 else p2
            avg_g = (gp1 + gc2 + gp2 + gc1) / 2 if j1 >= 3 and j2 >= 3 else 6.5
            assertividade = (min(o25/100, 1) * 0.40 + max(w1, w2) / 100 * 0.35 + min(btts/100, 1) * 0.25) * 100

            alerts.append({
                "liga": m["liga"], "p1": p1, "p2": p2,
                "w1": w1, "w2": w2, "j1": j1, "j2": j2,
                "o25": o25, "btts": btts, "avg_g": avg_g,
                "f1": f1, "f2": f2, "fav": fav,
                "score": score, "reasons": reasons,
                "assertividade": round(assertividade, 1),
            })

    return sorted(alerts, key=lambda x: x["score"], reverse=True)


def fmt_alert(a):
    reasons = "\n".join(f"   ✅ {r}" for r in a["reasons"])
    return (
        f"🚨 <b>ALERTA DE APOSTA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{a['p1']}</b> vs <b>{a['p2']}</b>\n"
        f"🏆 {a['liga']}\n\n"
        f"📊 <b>Assertividade: {a['assertividade']:.1f}%</b>\n\n"
        f"📈 <b>Estatisticas:</b>\n"
        f"   {a['p1']}: WR {a['w1']:.0f}% ({a['j1']}j) | Forma: {a['f1']}\n"
        f"   {a['p2']}: WR {a['w2']:.0f}% ({a['j2']}j) | Forma: {a['f2']}\n"
        f"   Over 2.5: {a['o25']:.0f}% | BTTS: {a['btts']:.0f}%\n"
        f"   Media estimada: {a['avg_g']:.1f} gols\n\n"
        f"💡 <b>Recomendacoes:</b>\n"
        f"{reasons}\n\n"
        f"🎯 <b>Dica:</b> Over 2.5 + Vitoria {a['fav']}\n\n"
        f"⏳ <i>Aguardando resultado...</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


def fmt_result(a, placar, bateu):
    reasons = "\n".join(f"   ✅ {r}" for r in a["reasons"])
    icon = "✅" if bateu else "🔥"
    txt = "GREEN! Aposta bateu!" if bateu else "RED! Nao bateu."
    return (
        f"🚨 <b>ALERTA DE APOSTA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{a['p1']}</b> vs <b>{a['p2']}</b>\n"
        f"🏆 {a['liga']}\n\n"
        f"📊 <b>Assertividade: {a['assertividade']:.1f}%</b>\n\n"
        f"📈 <b>Estatisticas:</b>\n"
        f"   {a['p1']}: WR {a['w1']:.0f}% ({a['j1']}j) | Forma: {a['f1']}\n"
        f"   {a['p2']}: WR {a['w2']:.0f}% ({a['j2']}j) | Forma: {a['f2']}\n"
        f"   Over 2.5: {a['o25']:.0f}% | BTTS: {a['btts']:.0f}%\n"
        f"   Media estimada: {a['avg_g']:.1f} gols\n\n"
        f"💡 <b>Recomendacoes:</b>\n"
        f"{reasons}\n\n"
        f"🎯 <b>Dica:</b> Over 2.5 + Vitoria {a['fav']}\n\n"
        f"{icon} <b>{txt}</b>\n"
        f"   Placar final: <b>{placar}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


def load_sent():
    if os.path.exists(ALERTS_FILE):
        with open(ALERTS_FILE) as f:
            return json.load(f)
    return []


def save_sent(data):
    with open(ALERTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def alert_key(a):
    players = sorted([a["p1"], a["p2"]])
    return f"{a['liga']}|{players[0]}|{players[1]}"


# ============================================================
# Main
# ============================================================

def send_alerts():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERRO: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID nao configurados")
        return

    print("Buscando dados do Google Sheets...")
    matches = get_matches()
    print(f"  Total de partidas: {len(matches)}")
    print(f"  Finalizados: {len([m for m in matches if m['status'] == 'Finalizado'])}")
    print(f"  Agendados: {len([m for m in matches if m['status'] == 'Agendado'])}")

    alerts = find_alerts(matches)
    print(f"  Alertas com score >= 70: {len(alerts)}")

    if not alerts:
        print("  Nenhum alerta de alta confianca no momento.")
        return

    sent = load_sent()
    sent_keys = {s.get("key", "") for s in sent}

    new = []
    for a in alerts:
        k = alert_key(a)
        if k not in sent_keys:
            a["key"] = k
            new.append(a)
        else:
            print(f"  Ja enviado: {a['p1']} vs {a['p2']}")

    if not new:
        print("  Todos os alertas ja foram enviados anteriormente.")
        return

    print(f"\nEnviando {len(new)} alerta(s)...")
    for i, a in enumerate(new, 1):
        msg = fmt_alert(a)
        msg_id = send_msg(msg)
        if msg_id:
            a["message_id"] = msg_id
            sent.append(a)
            print(f"  [{i}/{len(new)}] {a['p1']} vs {a['p2']} - ENVIADO (msg_id={msg_id})")
        else:
            print(f"  [{i}/{len(new)}] {a['p1']} vs {a['p2']} - FALHOU")
        time.sleep(2)

    save_sent(sent)
    print(f"\nTotal enviado: {len(new)}")


def update_results():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    print("Buscando resultados...")
    matches = get_matches()

    # Mapa de jogos finalizados (ambas as ordens)
    done = {}
    for m in matches:
        if m["status"] == "Finalizado":
            done[m["p1"] + "|" + m["p2"]] = m
            done[m["p2"] + "|" + m["p1"]] = m

    sent = load_sent()
    updated = 0

    for a in sent:
        if a.get("result_checked"):
            continue

        parts = a.get("key", "").split("|")
        if len(parts) < 3:
            continue

        p1, p2 = parts[1], parts[2]
        result = done.get(p1 + "|" + p2)
        if not result:
            continue

        placar = result["placar"]
        sc = parse_score(placar)
        if not sc:
            a["result_checked"] = True
            continue

        g1, g2 = sc
        fav = a["fav"]
        fav_g = g1 if fav == p1 else g2
        und_g = g2 if fav == p1 else g1

        bateu = (g1 + g2 > 2.5) and (fav_g > und_g)

        msg_id = a.get("message_id")
        if msg_id:
            new_msg = fmt_result(a, placar, bateu)
            ok = edit_msg(msg_id, new_msg)
            print(f"  {'✅ GREEN' if bateu else '🔥 RED'}: {p1} vs {p2} = {placar} (edit={'ok' if ok else 'falha'})")

        a["result_checked"] = True
        a["result_placar"] = placar
        a["result_status"] = "bateu" if bateu else "errou"
        updated += 1

    save_sent(sent)
    print(f"Resultados atualizados: {updated}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update_results()
    else:
        send_alerts()
