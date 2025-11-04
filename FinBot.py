import os
import asyncio
from flask import Flask, request
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# === VARIÁVEIS DE AMBIENTE ===
TOKEN = os.getenv("BOT_TOKEN")
SHEET_KEY = os.getenv("SHEET_KEY")
CREDENTIALS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# === GOOGLE SHEETS CONFIG ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_KEY).sheet1

# === FLASK APP ===
app = Flask(__name__)

# === TELEGRAM APP ===
application = Application.builder().token(TOKEN).build()

# === COMANDOS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Olá! Envie uma mensagem no formato:\n\n💰 valor, categoria, forma, data(opcional)")

async def add_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        texto = update.message.text.strip()
        partes = [p.strip() for p in texto.split(",")]

        if len(partes) < 2:
            await update.message.reply_text("Use o formato: valor, categoria, forma, data(opcional)")
            return

        valor_str = partes[0].replace("R$", "").replace(",", ".").strip()
        valor = float(valor_str)

        categoria = partes[1]
        forma = partes[2] if len(partes) > 2 else "Desconhecida"
        data = partes[3] if len(partes) > 3 else datetime.now().strftime("%d/%m/%Y")

        # Salva os dados crus no Sheets
        sheet.append_row([update.message.from_user.first_name, valor, categoria, data, forma])

        await update.message.reply_text(f"✅ Gasto registrado: R${valor:.2f} - {categoria}")

    except Exception as e:
        print(f"Erro ao registrar gasto: {e}")
        await update.message.reply_text("⚠️ Erro ao registrar gasto. Verifique o formato e tente novamente.")

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        registros = sheet.get_all_values()[1:]  # Ignora cabeçalho
        total_valor = sum(float(r[1]) for r in registros if r[1])
        await update.message.reply_text(f"💰 Total registrado: R${total_valor:.2f}")
    except Exception as e:
        print(f"Erro ao calcular total: {e}")
        await update.message.reply_text("⚠️ Erro ao calcular o total.")

# === HANDLERS ===
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("total", total))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_gasto))

# === WEBHOOK ===
@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    try:
        update = telegram.Update.de_json(request.get_json(force=True), application.bot)

        # Inicializa o bot se ainda não estiver rodando
        if not application.running:
            await application.initialize()
            await application.start()

        await application.process_update(update)
    except Exception as e:
        print(f"Erro no webhook: {e}")
    return "OK", 200

# === ROTA PING PARA O UPTIMEROBOT ===
@app.route("/", methods=["GET"])
def ping():
    return "FinBot está ativo!", 200

# === MAIN ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    async def main():
        # Garante que o bot foi iniciado antes do Flask
        await application.initialize()
        await application.start()
        print("🚀 Webhook configurado e bot rodando no Render.")

        app.run(host="0.0.0.0", port=port)

    asyncio.run(main())
