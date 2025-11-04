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
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

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
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # seu ID do Telegram

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
        sheet.append_row(["Usuário", "Valor", "Categoria", "Data", "Forma de Pagamento", "Observações"])
    return sheet


def salvar_dados(nome, valor, categoria, data, forma_pagamento, observacoes):
    """Salva uma linha de dados no Google Sheets."""
    sheet = conectar_sheets()
    data_iso = data.strftime("%Y-%m-%d")
    sheet.append_row([
        nome,
        round(valor, 2),
        categoria.title(),
        data_iso,
        forma_pagamento.capitalize() if forma_pagamento else "—",
        observacoes or "—"
    ])


def ler_todos_os_dados():
    """Lê todos os registros do Google Sheets (exceto o cabeçalho)."""
    sheet = conectar_sheets()
    dados = sheet.get_all_records()
    return dados

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
        data = data_mensagem.date()

    obs = re.sub(r"\d+(?:[.,]\d+)?", "", mensagem)
    obs = re.sub(categoria, "", obs, flags=re.IGNORECASE)
    obs = re.sub(forma_pagamento, "", obs, flags=re.IGNORECASE)
    observacoes = obs.strip()

    return valor, categoria, data, forma_pagamento, observacoes

# ===============================
# COMANDOS TELEGRAM
# ===============================
async def cmd_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o total de gastos registrados."""
    try:
        dados = ler_todos_os_dados()
        total = sum(float(d["Valor"]) for d in dados)
        await update.message.reply_text(f"💰 *Total de gastos:* R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                                        parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Erro em /total: {e}")
        await update.message.reply_text("⚠️ Erro ao calcular o total de gastos.")


async def cmd_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra total por categoria."""
    try:
        dados = ler_todos_os_dados()
        categorias = {}
        for d in dados:
            cat = d["Categoria"]
            valor = float(d["Valor"])
            categorias[cat] = categorias.get(cat, 0) + valor

        resposta = "📂 *Total por categoria:*\n"
        for cat, val in categorias.items():
            resposta += f"• {cat}: R$ {val:,.2f}\n"
        await update.message.reply_text(resposta.replace(",", "X").replace(".", ",").replace("X", "."),
                                        parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Erro em /categoria: {e}")
        await update.message.reply_text("⚠️ Erro ao calcular total por categoria.")

# ===============================
# PROCESSAMENTO DE MENSAGENS
# ===============================
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto (não comandos)."""
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
        await update.message.reply_text("⚠️ Erro ao registrar o gasto. Tente novamente.")

# ===============================
# FLASK + WEBHOOK
# ===============================
flask_app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
app = Application.builder().token(TELEGRAM_TOKEN).build()

# Handlers
app.add_handler(CommandHandler("total", cmd_total))
app.add_handler(CommandHandler("categoria", cmd_categoria))
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
    """Registra o webhook no Telegram."""
    for tentativa in range(3):
        try:
            await bot.delete_webhook()
            await bot.set_webhook(WEBHOOK_URL)
            logging.info(f"✅ Webhook registrado com sucesso em {WEBHOOK_URL}")

            if ADMIN_CHAT_ID:
                await bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text="ESOTU PRONTO PARA REGISTRAR SEUS GASTOS!* 💰",
                    parse_mode="Markdown"
                )
            return
        except Exception as e:
            logging.warning(f"Tentativa {tentativa + 1}/3 falhou: {e}")
            await asyncio.sleep(3)
    logging.error("❌ Falha ao registrar o webhook após 3 tentativas.")

async def lembrete_periodico():
    """Envia lembrete periódico para o ADMIN_CHAT_ID."""
    if not ADMIN_CHAT_ID:
        logging.warning("⚠️ Nenhum ADMIN_CHAT_ID configurado — lembretes desativados.")
        return

    logging.info(f"🔔 Iniciando loop de lembretes para ADMIN_CHAT_ID={ADMIN_CHAT_ID} ...")

    while True:
        try:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="🕒 Lembrete: REGISTRAR GASTOS... DISCIPLINA! 💸"
            )
            logging.info("📨 Lembrete enviado com sucesso!")
        except Exception as e:
            logging.error(f"Erro ao enviar lembrete: {e}")
        await asyncio.sleep(60 * 60 * 3)  # 3 horas (use 60 pra testar rápido)

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
        logging.info("🤖 Bot rodando em modo WEBHOOK (sem polling).")
        await asyncio.Event().wait()

    asyncio.run(iniciar_bot())

