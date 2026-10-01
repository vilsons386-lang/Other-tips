import asyncio
from datetime import datetime, timezone, timedelta
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

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot de Apostas +EV (Valores Positivos) está Online!"


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
        "👋 Envie /analisar para buscar oportunidades com +EV Positivo nas próximas 30h."
    )


async def analisar(update: Update, context):
    await update.message.reply_text(
        "🔍 A procurar jogos com Valor Esperado Positivo (+EV > 0%)..."
    )

    try:
        if not ODDS_API_KEY:
            await update.message.reply_text(
                "❌ Erro: ODDS_API_KEY não configurada no Render."
            )
            return

        now_utc = datetime.now(timezone.utc)
        limite_tempo = now_utc + timedelta(hours=30)

        url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
        res = requests.get(url, timeout=10)
        dados = []

        if res.status_code == 200:
            dados = res.json()
        else:
            for liga in [
                "soccer_epl",
                "soccer_portugal_primeira_liga",
                "soccer_spain_la_liga",
                "soccer_germany_bundesliga",
                "soccer_italy_serie_a",
            ]:
                u = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
                r = requests.get(u, timeout=8)
                if r.status_code == 200 and r.json():
                    dados.extend(r.json())

        if not dados:
            await update.message.reply_text("⚠️ Nenhum jogo encontrado no momento.")
            return

        oportunidades = []

        for jogo in dados:
            commence_time_str = jogo.get("commence_time")
            if commence_time_str:
                jogo_time = datetime.fromisoformat(
                    commence_time_str.replace("Z", "+00:00")
                )
                if jogo_time < now_utc or jogo_time > limite_tempo:
                    continue
            else:
                continue

            home = jogo.get("home_team", "Casa")
            away = jogo.get("away_team", "Fora")
            bookmakers = jogo.get("bookmakers", [])

            if not bookmakers:
                continue

            hora_jogo = jogo_time.strftime("%d/%m %H:%M")

            # Média das odds
            odds_casa, odds_fora, odds_empate = [], [], []
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

            if odds_casa and odds_fora and odds_empate:
                avg_c = sum(odds_casa) / len(odds_casa)
                avg_f = sum(odds_fora) / len(odds_fora)
                avg_e = sum(odds_empate) / len(odds_empate)
                margin = (1 / avg_c) + (1 / avg_f) + (1 / avg_e)

                prob_c = (1 / avg_c) / margin
                prob_f = (1 / avg_f) / margin
                prob_e = (1 / avg_e) / margin

                # Mapeamento de seleções e probabilidades
                selecoes = [
                    (home, prob_c, "Vitória Casa"),
                    (away, prob_f, "Vitória Fora"),
                    ("Draw", prob_e, "Empate"),
                ]

                for nome_sel, prob_fair, rotulo in selecoes:
                    # Encontra a melhor casa de apostas para essa seleção
                    melhor_bk = None
                    maior_odd = 0.0

                    for bk in bookmakers:
                        for mk in bk.get("markets", []):
                            if mk.get("key") == "h2h":
                                for out in mk.get("outcomes", []):
                                    if out["name"] == nome_sel and out["price"] > maior_odd:
                                        maior_odd = out["price"]
                                        melhor_bk = bk.get("title", "Desconhecida")

                    if maior_odd > 0 and melhor_bk:
                        ev = calcular_ev(prob_fair, maior_odd)

                        # Apenas aceita se o EV for rigorosamente positivo
                        if ev > 0.0:
                            msg = (
                                f"⚽ *{home} vs {away}*\n"
                                f"📅 Hora: *{hora_jogo} UTC*\n"
                                f"🎯 Palpite: *{nome_sel} ({rotulo})*\n"
                                f"🏠 Melhor Casa: *{melhor_bk}*\n"
                                f"📈 Odd: *{maior_odd}*\n"
                                f"💎 Valor Esperado (+EV): *+{ev}%*"
                            )
                            oportunidades.append((ev, jogo_time, msg))

        if oportunidades:
            # Ordena primeiro pelo maior +EV
            oportunidades.sort(key=lambda x: x[0], reverse=True)
            mensagens = [item[2] for item in oportunidades[:8]]

            texto_final = "🔥 *Oportunidades com +EV Positivo:*\n\n" + "\n\n--------------------\n\n".join(mensagens)
            await update.message.reply_text(texto_final, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "⚠️ Nenhuma oportunidade com +EV positivo encontrada para as próximas 30 horas."
            )

    except Exception as e:
        logging.error(f"Erro ao analisar: {e}")
        await update.message.reply_text(f"❌ Erro de processamento: {e}")


# --- INICIALIZAÇÃO ASSÍNCRONA ---
async def main():
    if not TELEGRAM_TOKEN:
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analisar", analisar))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    await asyncio.Event().wait()


if __name__ == "__main__":
    thread_flask = Thread(target=run_flask)
    thread_flask.daemon = True
    thread_flask.start()

    asyncio.run(main())
