import os
import logging
import asyncio
from datetime import datetime
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from threading import Thread

# ======================================================
# ⚙️ CONFIGURAÇÕES E LOGGING
# ======================================================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://finbot-5zoa.onrender.com")
PORT = int(os.getenv("PORT", 8080))
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

if not all([TELEGRAM_TOKEN, ADMIN_CHAT_ID, SHEET_ID, GOOGLE_CREDENTIALS]):
    raise Exception("❌ Variáveis de ambiente ausentes! Configure TELEGRAM_TOKEN, ADMIN_CHAT_ID, SHEET_ID e GOOGLE_CREDENTIALS.")

# ======================================================
# 📊 CONEXÃO COM GOOGLE SHEETS
# ======================================================
def conectar_sheets():
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        logging.info("✅ Conectado ao Google Sheets com sucesso.")
        return sheet
    except Exception as e:
        logging.error(f"❌ Erro ao conectar ao Google Sheets: {e}")
        return None

# ======================================================
# 🤖 CONFIGURAÇÃO DO TELEGRAM BOT
# ======================================================
bot = Bot(token=TELEGRAM_TOKEN)
flask_app = Flask(__name__)

# ======================================================
# 💬 COMANDOS TELEGRAM
# ======================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "Olá! 👋 Eu sou o *FinBotBeta* 💰\n\n"
        "Comandos disponíveis:\n"
        "• /total → Mostra o total de gastos\n"
        "• /categoria → Mostra total por categoria\n"
        "• /lembrete → Envia um lembrete manual\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = conectar_sheets()
        if not sheet:
            await update.message.reply_text("⚠️ Não foi possível acessar o Google Sheets.")
            return

        valores = sheet.col_values(2)[1:]  # Coluna "Valor"
        total_gastos = sum(float(v.replace(",", ".")) for v in valores if v)
        await update.message.reply_text(f"💸 Total de gastos: *R$ {total_gastos:.2f}*", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Erro no comando /total: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao calcular o total.")

async def categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = conectar_sheets()
        if not sheet:
            await update.message.reply_text("⚠️ Não foi possível acessar o Google Sheets.")
            return

        categorias = sheet.col_values(3)[1:]  # Coluna "Categoria"
        valores = sheet.col_values(2)[1:]
        totais = {}

        for c, v in zip(categorias, valores):
            if c and v:
                valor = float(v.replace(",", "."))
                totais[c] = totais.get(c, 0) + valor

        if not totais:
            await update.message.reply_text("📂 Nenhum gasto registrado ainda.")
            return

        texto = "📊 *Total por categoria:*\n\n"
        for cat, val in totais.items():
            texto += f"• {cat}: R$ {val:.2f}\n"
        await update.message.reply_text(texto, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Erro no comando /categoria: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao calcular por categoria.")

async def lembrete_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await enviar_lembrete()
    await update.message.reply_text("🔔 Lembrete enviado manualmente!")

# ======================================================
# 🔔 LEMBRETES AUTOMÁTICOS
# ======================================================
async def enviar_lembrete():
    try:
        mensagem = f"🔔 Lembrete financeiro!\n{datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n💰 Já registrou seus gastos hoje?"
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=mensagem)
        logging.info("📨 Lembrete enviado com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao enviar lembrete: {e}")

async def loop_lembretes():
    logging.info("🔁 Iniciando lembretes automáticos a cada 1 hora...")
    while True:
        await enviar_lembrete()
        await asyncio.sleep(3600)  # 1 hora (ajuste se quiser testar mais rápido)

# ======================================================
# 🌐 FLASK + WEBHOOK
# ======================================================
@flask_app.route("/", methods=["GET"])
def home():
    return "🚀 FinBotBeta está online com Webhook!", 200

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        flask_app.application.update_queue.put_nowait(update)
        return "ok", 200
    except Exception as e:
        logging.error(f"Erro no webhook: {e}")
        return "erro", 500

# ======================================================
# 🚀 INICIALIZAÇÃO DO BOT
# ======================================================
async def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    flask_app.application = application

    # Registrar comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("total", total))
    application.add_handler(CommandHandler("categoria", categoria))
    application.add_handler(CommandHandler("lembrete", lembrete_manual))

    # Configurar Webhook
    await bot.delete_webhook()
    await bot.set_webhook(f"{RENDER_URL}/webhook")
    logging.info(f"✅ Webhook registrado com sucesso em {RENDER_URL}/webhook")

    # Iniciar lembretes
    asyncio.create_task(loop_lembretes())

    # Iniciar o bot
    await application.initialize()
    await application.start()
    logging.info("🤖 FinBotBeta rodando em modo WEBHOOK.")
    await asyncio.Event().wait()

# ======================================================
# 🧠 EXECUÇÃO
# ======================================================
if __name__ == "__main__":
    logging.info("🚀 Iniciando FinBotBeta...")
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=PORT)).start()
    asyncio.run(main())
