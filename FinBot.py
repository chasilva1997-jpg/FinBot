import os
import re
import json
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from flask import Flask
from threading import Thread

# ===============================
# VARIÁVEIS DE AMBIENTE
# ===============================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

# ===============================
# GOOGLE SHEETS
# ===============================
def conectar_sheets():
    if not GOOGLE_CREDENTIALS:
        raise Exception("❌ GOOGLE_CREDENTIALS não encontrada!")

    info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet


def salvar_dados(valor, categoria, data, forma_pagamento, observacoes):
    sheet = conectar_sheets()
    sheet.append_row([valor, categoria, str(data), forma_pagamento, observacoes])


# ===============================
# INTERPRETA MENSAGEM
# ===============================
def parse_mensagem(mensagem, data_mensagem):
    valores = re.findall(r"\d+(?:\.\d+)?", mensagem)
    valor = float(valores[0]) if valores else 0

    forma_pagamento = ""
    for fp in ["cartao", "cartão", "dinheiro", "pix", "transferencia", "boleto"]:
        if fp in mensagem.lower():
            forma_pagamento = fp.capitalize()
            break

    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", mensagem)
    palavras = [p for p in palavras if p.lower() != forma_pagamento.lower()]
    categoria = palavras[0] if palavras else "Geral"

    data_regex = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", mensagem)
    if data_regex:
        data = datetime.strptime(
            data_regex.group(0),
            "%d/%m/%Y" if "/" in data_regex.group(0) else "%Y-%m-%d"
        ).date()
    else:
        data = data_mensagem.date()

    obs = re.sub(r"\d+(?:\.\d+)?", "", mensagem)
    obs = re.sub(categoria, "", obs, flags=re.IGNORECASE)
    obs = re.sub(forma_pagamento, "", obs, flags=re.IGNORECASE)
    observacoes = obs.strip()

    return valor, categoria, data, forma_pagamento, observacoes


# ===============================
# BOT DO TELEGRAM
# ===============================
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensagem = update.message.text
    data_mensagem = update.message.date

    valor, categoria, data, forma_pagamento, observacoes = parse_mensagem(mensagem, data_mensagem)
    salvar_dados(valor, categoria, data, forma_pagamento, observacoes)

    await update.message.reply_text(
        f"✅ R${valor:.2f} registrado!\n"
        f"📂 {categoria}\n📅 {data}\n💳 {forma_pagamento}\n📝 {observacoes or '—'}"
    )


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_message))
    print("🤖 FinBotBeta iniciado e aguardando mensagens...")
    app.run_polling(drop_pending_updates=True)


# ===============================
# FLASK SERVER (para Render)
# ===============================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "FinBotBeta está rodando 🚀"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    main()
