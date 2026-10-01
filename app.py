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


def calcular_ev(probabilidade_fair, odd_oferecida):
    """Calcula o Valor Esperado (+EV) em percentagem."""
    ev = (probabilidade_fair * odd_oferecida) - 1
    return round(ev * 100, 2)


# --- COMANDOS DO TELEGRAM ---
async def start(update: Update, context):
    await update.message.reply_text(
        "👋 Olá! Envie /analisar para procurar oportunidades de apostas +EV."
    )


async def analisar(update: Update, context):
    await update.message.reply_text(
        "🔍 A procurar jogos na Odds API e a calcular +EV..."
    )

    try:
        if not ODDS_API_KEY:
            await update.message.reply_text(
                "❌ Erro: ODDS_API_KEY não configurada no Render."
            )
            return

        # Obter dados da Odds API (Premier League)
        url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            await update.message.reply_text(
                f"❌ Erro na Odds API ({response.status_code})."
            )
            return

        dados = response.json()
        if not dados:
            await update.message.reply_text(
                "⚠️ Nenhum jogo encontrado de momento."
            )
            return

        oportunidades = []

        for jogo in dados:
            home = jogo.get("home_team", "Casa")
            away = jogo.get("away_team", "Fora")
            bookmakers = jogo.get("bookmakers", [])

            if len(bookmakers) < 2:
                continue

            # Média das odds para encontrar a "odd justa" sem margem
            odds_casa = []
            odds_fora = []
            odds_empate = []

            for bk in bookmakers:
                for mk in bk.get("markets", []):
                    if mk.get("key") == "h2h":
                        for out in mk.get("outcomes", []):
                            if out["name"] == home:
                                odds_casa.append(out["price"])
                            elif out["name"] == away:
                                odds_fora.append(out["price"])
                            else:
                                odds_empate.append(out["price"])

            if not odds_casa or not odds_fora or not odds_empate:
                continue

            # Cálculo de probabilidade média
            avg_odd_casa = sum(odds_casa) / len(odds_casa)
            avg_odd_fora = sum(odds_fora) / len(odds_fora)
            avg_odd_empate = sum(odds_empate) / len(odds_empate)

            margin = (
                (1 / avg_odd_casa) + (1 / avg_odd_fora) + (1 / avg_odd_empate)
            )
            prob_casa_fair = (1 / avg_odd_casa) / margin

            # Verifica se alguma casa tem uma odd acima do valor justo (+EV)
            for bk in bookmakers:
                bk_name = bk.get("title", "Casa")
                for mk in bk.get("markets", []):
                    if mk.get("key") == "h2h":
                        for out in mk.get("outcomes", []):
                            if out["name"] == home:
                                odd_oferecida = out["price"]
                                ev = calcular_ev(prob_casa_fair, odd_oferecida)

                                # Filtra apenas oportunidades com +EV > 2%
                                if ev > 2.0:
                                    msg = (
                                        f"⚽ *{home} vs {away}*\n"
                                        f"🏆 Apostar em: *{home}*\n"
                                        f"🏠 Casa: {bk_name}\n"
                                        f"📈 Odd Oferecida: *{odd_oferecida}*\n"
                                        f"💎 Valor Esperado (+EV): *+{ev}%*"
                                    )
                                    oportunidades.append(msg)

        if oportunidades:
            # Envia no máximo 5 melhores entradas
            texto_final = "\n\n--------------------\n\n".join(
                oportunidades[:5]
            )
            await update.message.reply_text(
                texto_final, parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "⚠️ Nenhuma aposta com +EV superior a +2% encontrada neste momento."
            )

    except Exception as e:
        logging.error(f"Erro ao analisar: {e}")
        await update.message.reply_text(f"❌ Erro de processamento: {e}")


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

    await asyncio.Event().wait()


if __name__ == "__main__":
    thread_flask = Thread(target=run_flask)
    thread_flask.daemon = True
    thread_flask.start()

    asyncio.run(main())



