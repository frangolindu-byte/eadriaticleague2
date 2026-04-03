"""
Deleta todas as mensagens do canal Telegram.
Usado para limpar alertas antigos (Over 2.5) antes de comecar com Over 6.5.
"""

import json
import os
from urllib.request import Request, urlopen

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("ERRO: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nao configurados")
    exit(1)

def get_updates(offset=0):
    url = f"{TELEGRAM_URL}/getUpdates?chat_id={CHAT_ID}&offset={offset}&limit=100"
    req = Request(url)
    resp = json.loads(urlopen(req, timeout=15).read())
    return resp.get("result", [])

def delete_message(msg_id):
    url = f"{TELEGRAM_URL}/deleteMessage"
    data = json.dumps({"chat_id": CHAT_ID, "message_id": msg_id}).encode()
    req = Request(url, data, {"Content-Type": "application/json"})
    try:
        resp = json.loads(urlopen(req, timeout=15).read())
        return resp.get("ok", False)
    except Exception as e:
        print(f"  Erro ao deletar msg {msg_id}: {e}")
        return False

print("Buscando mensagens do canal...")
all_msgs = []
offset = 0
while True:
    updates = get_updates(offset)
    if not updates:
        break
    for u in updates:
        if "message" in u:
            msg = u["message"]
            if msg.get("chat", {}).get("id") == int(CHAT_ID):
                all_msgs.append(msg["message_id"])
    offset = updates[-1]["update_id"] + 1

print(f"  Encontradas {len(all_msgs)} mensagens no canal")

if not all_msgs:
    print("Nenhuma mensagem para deletar.")
    exit(0)

print(f"\nDeletando {len(all_msgs)} mensagens...")
deleted = 0
for i, msg_id in enumerate(all_msgs, 1):
    ok = delete_message(msg_id)
    if ok:
        deleted += 1
        print(f"  [{i}/{len(all_msgs)}] Deletada msg {msg_id}")
    else:
        print(f"  [{i}/{len(all_msgs)}] Falha ao deletar msg {msg_id}")

print(f"\nTotal deletadas: {deleted}/{len(all_msgs)}")
