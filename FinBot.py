import os
import re
import json
import gspread
import logging
from datetime import datetime
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask, request

# ===============================
# CONFIGURAÇÕES
# ===============================
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Exemplo: https://finbot.onrender.com
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not all([TELEGRAM_TOKEN, SHEET_ID, GOOGLE_CREDENTIALS, WEBHOOK_URL]):
    raise Exception("❌ Faltam variáveis de ambiente: TELEGRAM_TOKEN, SHEET_ID, GOOGLE_CREDENTIALS ou WEBHOOK_URL")

# ===============================
# GOOGLE SHEETS
# ===============================
def conectar_sheets():
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
    sheet = conectar_sheets()
    data_iso = data.strftime("%Y-%m-%d")
    valor_str = f"{valor:.2f}"
    sheet.append_row([
        nome,
        valor_str,
        categoria.title(),
        data_iso,
        forma_pagamento.capitalize() if forma_pagamento else "—",
        observacoes or "—"
    ])


def obter_totais():
    sheet = conectar_sheets()
    dados = sheet.get_all_records()
    if not dados:
        return 0.0, {}

    total_geral = 0.0
    totais_por_categoria = {}
    for linha in dados:
        valor_str = str(linha.get("Valor", "")).replace(",", ".").strip()
        try:
            valor = float(valor_str)
        except ValueError:
            continue
        categoria = linha.get("Categoria", "Geral").title()
        total_geral += valor
        totais_por_categoria[categoria] = totais_por_categoria.get(categoria, 0) + valor

    return total_geral, totais_por_categoria

# ===============================
# INTERPRETA MENSAGEM
# ===============================
def parse_mensagem(mensagem, data_mensagem):
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
# BOT TELEGRAM
# ===============================
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message.text
        nome = update.message.from_user.first_name
        data_msg = update.message.date

        valor, categoria, data, forma_pagamento, observacoes = parse_mensagem(msg, data_msg)
        salvar_dados(nome, valor, categoria, data, forma_pagamento, observacoes)

        await update.message.reply_text(
            f"✅ Gasto registrado!\n"
            f"💰 Valor: R$ {valor:.2f}\n"
            f"📂 Categoria: {categoria}\n"
            f"📅 Data: {data.strftime('%d/%m/%Y')}\n"
            f"💳 Pagamento: {forma_pagamento or '—'}\n"
            f"📝 Obs: {observacoes or '—'}"
        )
    except Exception as e:
        logging.error(f"Erro ao processar mensagem: {e}")
        await update.message.reply_text("⚠️ Erro ao registrar o gasto. Tente novamente.")

async def comando_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total, _ = obter_totais()
    await update.message.reply_text(f"💰 Total de gastos: R$ {total:.2f}")

async def comando_categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, totais = obter_totais()
    if not totais:
        await update.message.reply_text("📊 Nenhum gasto registrado ainda.")
        return
    resposta = "📂 *Total por Categoria:*\n\n"
    for cat, val in totais.items():
        resposta += f"• {cat}: R$ {val:.2f}\n"
    await update.message.reply_text(resposta, parse_mode="Markdown")

async def comando_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total, totais = obter_totais()
    if not totais:
        await update.message.reply_text("📊 Nenhum gasto registrado ainda.")
        return
    resposta = f"📘 *Resumo Geral:*\n\n💰 Total: R$ {total:.2f}\n\n📂 *Por Categoria:*\n"
    for cat, val in totais.items():
        resposta += f"• {cat}: R$ {val:.2f}\n"
    await update.message.reply_text(resposta, parse_mode="Markdown")

async def comando_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ajuda = (
        "🤖 *Comandos disponíveis:*\n\n"
        "/total → total geral\n"
        "/categorias → total por categoria\n"
        "/resumo → resumo geral\n\n"
        "📝 Exemplo:\n"
        "`Padaria 12,50 pix` ou `Gasolina 100 dinheiro`"
    )
    await update.message.reply_text(ajuda, parse_mode="Markdown")

# ===============================
# FLASK + WEBHOOK
# ===============================
app = Flask(__name__)
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()

telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
telegram_app.add_handler(CommandHandler("total", comando_total))
telegram_app.add_handler(CommandHandler("categorias", comando_categorias))
telegram_app.add_handler(CommandHandler("resumo", comando_resumo))
telegram_app.add_handler(CommandHandler("ajuda", comando_ajuda))

@app.route("/")
def home():
    return "✅ FinBot ativo!"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    await telegram_app.process_update(update)
    return "ok"

async def iniciar_webhook():
    await telegram_app.bot.delete_webhook()
    await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
    logging.info("Webhook configurado com sucesso!")

if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(iniciar_webhook())
    app.run(host="0.0.0.0", port=10000)
