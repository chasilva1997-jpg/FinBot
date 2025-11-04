import os
import re
import json
import gspread
import logging
from datetime import datetime
from flask import Flask, request
from google.oauth2.service_account import Credentials
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ===============================
# CONFIGURAÇÕES
# ===============================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not all([TELEGRAM_TOKEN, SHEET_ID, GOOGLE_CREDENTIALS, WEBHOOK_URL]):
    raise Exception("❌ Variáveis de ambiente ausentes!")

# ===============================
# GOOGLE SHEETS
# ===============================
def conectar_sheets():
    info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1

    if not sheet.get_all_values():
        sheet.append_row(["Usuário", "Valor", "Categoria", "Data", "Forma de Pagamento", "Observações"])
    return sheet


def salvar_dados(nome, valor, categoria, data, forma_pagamento, observacoes):
    """Salva valor cru como texto para evitar bugs de formatação"""
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
    """Calcula total geral e por categoria"""
    sheet = conectar_sheets()
    dados = sheet.get_all_records()
    if not dados:
        return 0.0, {}

    total_geral = 0.0
    totais_por_categoria = {}

    for linha in dados:
        valor_str = str(linha["Valor"]).strip().replace(",", ".")
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
# COMANDOS DO BOT
# ===============================
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mensagem = update.message.text
        data_mensagem = update.message.date
        nome = update.message.from_user.first_name

        valor, categoria, data, forma_pagamento, observacoes = parse_mensagem(mensagem, data_mensagem)
        salvar_dados(nome, valor, categoria, data, forma_pagamento, observacoes)

        await update.message.reply_text(
            f"✅ {nome}, gasto registrado!\n\n"
            f"💰 Valor: R$ {valor:.2f}\n"
            f"📂 Categoria: {categoria.title()}\n"
            f"📅 Data: {data.strftime('%d/%m/%Y')}\n"
            f"💳 Pagamento: {forma_pagamento.capitalize() or '—'}\n"
            f"📝 Obs: {observacoes or '—'}"
        )

    except Exception as e:
        logging.error(f"Erro ao processar mensagem: {e}")
        await update.message.reply_text("⚠️ Erro ao registrar o gasto.")


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


# ===============================
# FLASK SERVER (Render + Webhook)
# ===============================
app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
application = Application.builder().token(TELEGRAM_TOKEN).build()

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
application.add_handler(CommandHandler("total", comando_total))
application.add_handler(CommandHandler("categorias", comando_categorias))
application.add_handler(CommandHandler("resumo", comando_resumo))

@app.route("/", methods=["GET"])
def home():
    return "✅ FinBot ativo no Render!"


@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    application.update_queue.put_nowait(update)
    return "OK", 200


if __name__ == "__main__":
    logging.info("🚀 FinBot iniciado no modo WEBHOOK Render")
    bot.delete_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
