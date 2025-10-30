import os
import re
import json
import time
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from flask import Flask
from threading import Thread
from gspread.exceptions import APIError

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
    """Conecta ao Google Sheets e retorna a primeira aba."""
    if not GOOGLE_CREDENTIALS:
        raise Exception("❌ GOOGLE_CREDENTIALS não encontrada!")

    info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1

    # Cabeçalhos automáticos se a planilha estiver vazia
    if not sheet.get_all_values():
        sheet.append_row([
            "ID Usuário", "Nome", "Valor (R$)", "Categoria",
            "Data", "Forma de Pagamento", "Observações"
        ])

    return sheet


def salvar_dados(user_id, nome, valor, categoria, data, forma_pagamento, observacoes, tentativas=5):
    """Salva uma linha de dados no Google Sheets com retry automático."""
    for tentativa in range(tentativas):
        try:
            sheet = conectar_sheets()
            data_formatada = data.strftime("%d/%m/%Y %H:%M")
            valor_formatado = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            sheet.append_row([
                user_id,
                nome,
                valor_formatado,
                categoria.capitalize(),
                data_formatada,
                forma_pagamento or "—",
                observacoes or "—"
            ])
            return True

        except APIError as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                espera = 2 ** tentativa
                print(f"⚠️ Erro 503 (serviço indisponível). Tentando novamente em {espera}s...")
                time.sleep(espera)
            else:
                print("❌ Erro inesperado ao salvar no Sheets:", e)
                return False

    print("🚫 Não foi possível salvar após várias tentativas.")
    return False


# ===============================
# INTERPRETA MENSAGEM
# ===============================
def parse_mensagem(mensagem, data_mensagem):
    """Extrai informações estruturadas da mensagem de texto."""
    valores = re.findall(r"\d+(?:[.,]\d+)?", mensagem)
    if not valores:
        return None

    valor = float(valores[0].replace(",", "."))

    # Detecta forma de pagamento
    forma_pagamento = ""
    for fp in ["cartao", "cartão", "dinheiro", "pix", "transferencia", "boleto"]:
        if fp in mensagem.lower():
            forma_pagamento = fp.capitalize()
            break

    # Identifica categoria
    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", mensagem)
    palavras = [p for p in palavras if p.lower() != forma_pagamento.lower()]
    categoria = palavras[0].capitalize() if palavras else "Geral"

    # Extrai data (ou usa a data da mensagem)
    data_regex = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", mensagem)
    if data_regex:
        data = datetime.strptime(
            data_regex.group(0),
            "%d/%m/%Y" if "/" in data_regex.group(0) else "%Y-%m-%d"
        )
    else:
        data = data_mensagem

    # Observações (texto residual)
    obs = re.sub(r"\d+(?:[.,]\d+)?", "", mensagem)
    obs = re.sub(categoria, "", obs, flags=re.IGNORECASE)
    obs = re.sub(forma_pagamento, "", obs, flags=re.IGNORECASE)
    observacoes = obs.strip().capitalize()

    return valor, categoria, data, forma_pagamento, observacoes


# ===============================
# BOT DO TELEGRAM
# ===============================
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa cada mensagem recebida no Telegram."""
    mensagem = update.message.text.strip()
    data_mensagem = update.message.date
    user = update.message.from_user
    nome = user.first_name

    parsed = parse_mensagem(mensagem, data_mensagem)
    if not parsed:
        await update.message.reply_text("⚠️ Não encontrei um valor na mensagem. Envie algo como:\n`Almoço 25,50 cartão`")
        return

    valor, categoria, data, forma_pagamento, observacoes = parsed

    if salvar_dados(user.id, nome, valor, categoria, data, forma_pagamento, observacoes):
        data_br = data.strftime("%d/%m/%Y às %H:%M")
        valor_br = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        await update.message.reply_text(
            f"✅ {nome}, seu gasto foi registrado com sucesso!\n\n"
            f"💰 {valor_br}\n"
            f"📂 {categoria}\n"
            f"💳 {forma_pagamento or '—'}\n"
            f"📅 {data_br}\n"
            f"📝 {observacoes or '—'}"
        )
    else:
        await update.message.reply_text("⚠️ Não consegui registrar agora. Tente novamente em alguns minutos.")


def main():
    """Inicia o bot do Telegram."""
    if not TELEGRAM_TOKEN:
        raise Exception("❌ TELEGRAM_TOKEN não encontrado!")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_message))

    print("🤖 FinBotBeta está online e pronto para registrar gastos!")
    app.run_polling(drop_pending_updates=True)


# ===============================
# FLASK SERVER (para Render)
# ===============================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "FinBotBeta está rodando 🚀"

def run_flask():
    """Executa o servidor Flask para manter o bot ativo no Render."""
    flask_app.run(host="0.0.0.0", port=8080)


# ===============================
# INICIALIZAÇÃO
# ===============================
if __name__ == "__main__":
    Thread(target=run_flask).start()
    main()
