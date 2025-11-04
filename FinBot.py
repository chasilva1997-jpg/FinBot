import os
import logging
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Configuração de logs ===
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# === Variáveis de ambiente ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

if not all([TELEGRAM_TOKEN, SHEET_ID, WEBHOOK_URL, GOOGLE_CREDENTIALS]):
    raise Exception("❌ Variáveis de ambiente faltando. Verifique TELEGRAM_TOKEN, SHEET_ID, GOOGLE_CREDENTIALS, WEBHOOK_URL.")

# === Conexão com Google Sheets ===
import json
creds_json = json.loads(GOOGLE_CREDENTIALS)
scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# === Flask App (para Render e UptimeRobot) ===
app = Flask(__name__)

@app.route("/ping")
def ping():
    return "pong", 200

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run(application.process_update(update))
    return "OK", 200


# === Funções do Bot ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Olá! Envie o gasto no formato: valor, categoria.\nExemplo: 50, mercado")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use: /total para ver o total e /categoria para ver o total por categoria.")

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if "," not in text:
        await update.message.reply_text("❌ Formato inválido. Use: valor, categoria\nExemplo: 50, mercado")
        return

    try:
        valor_str, categoria = text.split(",", 1)
        valor = float(valor_str.replace(",", ".").strip())
        categoria = categoria.strip().capitalize()

        # Salva no Google Sheets
        from datetime import datetime
        sheet.append_row([update.effective_user.first_name, valor, categoria, datetime.now().strftime("%d/%m/%Y")])

        await update.message.reply_text(f"✅ Gasto de R$ {valor:.2f} registrado em {categoria}.")
    except Exception as e:
        logging.error(f"Erro ao registrar gasto: {e}")
        await update.message.reply_text("⚠️ Ocorreu um erro ao registrar o gasto.")


async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dados = sheet.get_all_records()
        total_gasto = sum(float(item["Valor"]) for item in dados)
        await update.message.reply_text(f"💰 Total gasto: R$ {total_gasto:.2f}")
    except Exception as e:
        logging.error(f"Erro ao calcular total: {e}")
        await update.message.reply_text("⚠️ Erro ao calcular total.")

async def categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dados = sheet.get_all_records()
        totais = {}

        for item in dados:
            cat = item["Categoria"]
            val = float(item["Valor"])
            totais[cat] = totais.get(cat, 0) + val

        mensagem = "📊 Gastos por categoria:\n"
        for cat, val in totais.items():
            mensagem += f"• {cat}: R$ {val:.2f}\n"

        await update.message.reply_text(mensagem)
    except Exception as e:
        logging.error(f"Erro ao calcular por categoria: {e}")
        await update.message.reply_text("⚠️ Erro ao calcular por categoria.")


# === Inicialização do Bot ===
application = Application.builder().token(TELEGRAM_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("total", total))
application.add_handler(CommandHandler("categoria", categoria))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense))


# === Iniciar webhook no Render ===
if __name__ == "__main__":
    async def run():
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
        logging.info("🚀 Webhook configurado e bot rodando no Render.")
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

    asyncio.run(run())
