import asyncio
import logging
import os
from threading import Thread
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler

# Configuração de logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Servidor Flask para manter o Render ativo
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot de Apostas +EV está Online!"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


# --- COMANDOS DO TELEGRAM ---
async def start(update: Update, context):
    await update.message.reply_text(
        "Olá! Envie /analisar para procurar apostas com valor esperado (+EV)."
    )


async def analisar(update: Update, context):
    await update.message.reply_text(
        "🔍 A procurar jogos e a calcular valor esperado (+EV)..."
    )

    try:
        if not ODDS_API_KEY:
            await update.message.reply_text(
                "❌ Erro: ODDS_API_KEY não configurada no Render."
            )
            return

        # Fazer requisição à Odds API (exemplo: Premier League)
        url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            await update.message.reply_text(
                f"❌ Erro na Odds API ({response.status_code}): {response.text}"
            )
            return

        dados = response.json()
        if not dados:
            await update.message.reply_text(
                "⚠️ Nenhum jogo encontrado no momento."
            )
            return

        mensagens = []
        for jogo in dados[:5]:  # Analisa os primeiros 5 jogos
            home_team = jogo.get("home_team", "Casa")
            away_team = jogo.get("away_team", "Fora")
            bookmakers = jogo.get("bookmakers", [])

            if bookmakers:
                markets = bookmakers[0].get("markets", [])
                if markets:
                    outcomes = markets[0].get("outcomes", [])
                    if outcomes:
                        odd_casa = outcomes[0].get("price", 1.0)
                        msg = f"⚽ *{home_team} vs {away_team}*\n📈 Odd Casa: {odd_casa}"
                        mensagens.append(msg)

        if mensagens:
            texto_final = "\n\n--------------------\n\n".join(mensagens)
            await update.message.reply_text(
                texto_final, parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "⚠️ Nenhum jogo com valor (+EV) encontrado."
            )

    except Exception as e:
        logging.error(f"Erro no comando analisar: {e}")
        await update.message.reply_text(f"❌ Erro interno no código: {e}")


# --- INICIALIZAÇÃO ASSÍNCRONA ---
async def main():
    if not TELEGRAM_TOKEN:
        print("ERRO CRÍTICO: TELEGRAM_TOKEN não configurado!")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analisar", analisar))

    print("Bot de Apostas +EV Ativo...")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Mantém o evento ativo para o Render não fechar
    await asyncio.Event().wait()


if __name__ == "__main__":
    # 1. Inicia o Flask numa thread secundária
    thread_flask = Thread(target=run_flask)
    thread_flask.daemon = True
    thread_flask.start()

    # 2. Inicia o Bot na thread principal com asyncio
    asyncio.run(main())


