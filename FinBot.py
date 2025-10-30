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

    # Cria cabeçalhos automáticos se estiver vazia
    if not sheet.get_all_values():
        sheet.append_row([
            "ID Usuário", "Nome", "Valor (R$)", "Categoria",
            "Data", "Forma de Pagamento", "Observações"
        ])

    return sheet


def salvar_dados(user_id, nome, valor, categoria, data, forma_pagamento, observacoes, tentativas=5):
    """Salva uma linha no Google Sheets com retry automático (tratamento de erro 503)."""
    for tentativa in range(tentativas):
        try:
            sheet = conectar_sheets()
            data_formatada = data.strftime("%d/%m/%Y %H:%M")_
