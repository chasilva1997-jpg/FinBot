import os
import re
import json
import gspread
import logging
import asyncio
from datetime import datetime, date
from flask import Flask, request
from threading import Thread
from google.oauth2.service_account import Credentials
from telegram import Bot, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ===============================
# CONFIGURAÇÕES E LOGS
# ===============================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # seu ID do Telegram (adicione no Render)

if not all([TELEGRAM_TOKEN, SHEET_ID, GOOGLE_CREDENTIALS, WEBHOOK_URL]):
    raise Exception("❌ Variáveis de ambiente faltando. Verifique TELEGRAM_TOKEN, SHEET_ID, GOOGLE_CREDENTIALS, WEBHOOK_URL.")

# ===============================
# GOOGLE SHEETS
# ===============================
def conectar_sheets():
    """Conecta ao Google Sheets e retorna a aba principal."""
    info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1

    if not sheet.get_all_values():
        sheet.append_row([
            "Usuário", "Valor", "Categoria",
            "Data", "Forma de Pagamento", "Observações"
        ])
    return sheet


def salvar_dados(nome, valor, categoria, data, forma_pagamento, observacoes):
    """Salva uma linha de dados no Google Sheets (formato limpo para Looker)."""
    sheet = conectar_sheets()
    data_iso = data.strftime("%Y-%m-%d")  # formato ISO (sem hora)
    sheet.append_row([
        nome,
        round(valor, 2),  # número puro (ex: 23.50)
        categoria.title(),
        data_iso,
        forma_pagamento.capitalize() if forma_pagamento else "—",
        observacoes or "—"
    ])

# ===============================
# INTERPRETA MENSAGEM
# ===============================
def parse_mensagem(mensagem, data_mensagem):
    """Extrai informações estruturadas da mensagem de texto."""
    valores = re.findall(r"\d+(?:[.,]\d+)?", mensagem)
    valor = float(valores[0].replace(",", ".")) if valores else 0.0

    forma_pagamento = ""
    for fp in ["cartão", "cartao", "dinheiro", "pix", "transferência", "transferencia", "boleto"]:
        if fp in mensagem.lower():
            forma_pagamento = fp
            break

    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", mensagem)
    palavras = [p for p in palavras if p.lower() not in forma_pagamento.lower()]
    categoria = palavras[0] if palavras else "Geral"

    data_regex = re.search(r"(\d{2}/\d{2}/\d{4})", mensagem)
    if data_regex:
        data = datetime.strptime(data_regex.group(0), "%d/%m/%Y").date()
    else:
        data = data_mensagem.date()  # apenas a data, sem hora

    obs = re.sub(r"\d+(?:[.,]\d+)?", "", mensagem)
    obs = re.sub(categoria, "", obs, flags=re.IGNORECASE)
    obs = re.sub(forma_pagamento, "", obs, flags=re.IGNORECASE)
    observacoes = obs.strip()

    return valor, categoria, data, forma_pagamento, observacoes

# ===============================
# BOT TELEGRAM
# ===============================
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa cada mensagem recebida."""
    try:
        mensagem = update.message.text
        data_mensagem = update.message.date
        nome = update.message.from_user.first_name

        valor, categoria, data, forma_pagamento, observacoes = parse_mensagem(mensagem, data_mensagem)
        salvar_dados(nome, valor, categoria, data, forma_pagamento, observacoes)

        await update.message.reply_text(
            f"✅ {nome}, seu gasto foi registrado!\n\n"
            f"💰 *Valor:* R$ {valor:.2f}\n"
            f"📂 *Categoria:* {categoria.title()}\n"
            f"📅 *Data:* {data.strftime('%d/%m/%Y')}\n"
            f"💳 *Pagamento:* {forma_pagamento.capitalize() or '—'}\n"
            f"📝 *Obs:* {observacoes or '—'}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Erro ao processar mensagem: {e}")
        if update.message:
            await update.message.reply_text("⚠️ Erro ao registrar o gasto. Tente novamente em instantes.")

# ===============================
# FLASK + WEBHOOK
# ===============================
flask_app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_message))

@flask_app.route("/")
def home():
    return "🚀 FinBot está online e operando com Webhook!"

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    """Recebe mensagens do Telegram."""
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        app.update_queue.put_nowait(update)
        return "ok", 200
    except Exception as e:
        logging.error(f"Erro no webhook: {e}")
        return "erro", 500

# ===============================
# FUNÇÕES AUXILIARES
# ===============================
async def registrar_webhook():
    """Registra o webhook no Telegram e avisa que está online."""
    for tentativa in range(3):
        try:
            await bot.delete_webhook()
            await bot.set_webhook(WEBHOOK_URL)
            logging.info(f"✅ Webhook registrado com sucesso em {WEBHOOK_URL}")

            if ADMIN_CHAT_ID:
                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text="🤖 FinBotBeta está *online e pronto para registrar seus gastos!* 💰",
                    parse_mode="Markdown"
                )
            return
        except Exception as e:
            logging.warning(f"Tentativa {tentativa+1}/3 falhou: {e}")
            await asyncio.sleep(3)
    logging.error("❌ Falha ao registrar o webhook após 3 tentativas.")

async def lembrete_periodico():
    """Envia lembrete a cada 3 horas para não esquecer de registrar gastos."""
    if not ADMIN_CHAT_ID:
        return
    while True:
        try:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="🕒 Lembrete: não esqueça de registrar seus gastos no FinBotBeta! 💸"
            )
        except Exception as e:
            logging.error(f"Erro ao enviar lembrete: {e}")
        await asyncio.sleep(3 * 60 * 60)  # 3 horas

def run_flask():
    """Executa o servidor Flask."""
    flask_app.run(host="0.0.0.0", port=8080)

# ===============================
# INICIALIZAÇÃO
# ===============================
if __name__ == "__main__":
    logging.info("🚀 Iniciando FinBot com Webhook (modo Looker)...")
    Thread(target=run_flask).start()

    async def iniciar_bot():
        await registrar_webhook()
        asyncio.create_task(lembrete_periodico())
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()

    asyncio.run(iniciar_bot())
