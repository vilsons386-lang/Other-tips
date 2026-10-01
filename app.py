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

# Lista das principais ligas para analisar
LIGAS = [
    "soccer_epl",              # Premier League
    "soccer_portugal_primeira_liga", # Liga Portugal
    "soccer_spain_la_liga",    # La Liga
    "soccer_italy_serie_a",    # Serie A
    "soccer_germany_bundesliga",# Bundesliga
    "soccer_uefa_champs_league"# Champions League
]

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot +EV Multi-Ligas (Bwin) está Online!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

def calcular_ev(probabilidade_fair, odd_oferecida):
    ev = (probabilidade_fair * odd_oferecida) - 1
    return round(ev * 100, 2)

async def start(update: Update, context):
    await update.message.reply_text(
        "👋 Envie /analisar para procurar oportunidades +EV na Bwin (Próximas 48h em várias Ligas)."
    )

async def analisar(update: Update, context):
    await update.message.reply_text(
        "🔍 A analisar Bwin em várias ligas (Premier League, Liga Portugal, La Liga, etc.)..."
    )

    try:
        if not ODDS_API_KEY:
            await update.message.reply_text("❌ Erro: ODDS_API_KEY não configurada no Render.")
            return

        now_utc = datetime.now(timezone.utc)
        limite_tempo = now_utc + timedelta(hours=48)
        oportunidades = []

        for liga in LIGAS:
            url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals"
            res = requests.get(url, timeout=10)

            if res.status_code != 200:
                continue

            dados = res.json()
            if not dados:
                continue

            for jogo in dados:
                commence_time_str = jogo.get("commence_time")
                if commence_time_str:
                    jogo_time = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
                    if jogo_time < now_utc or jogo_time > limite_tempo:
                        continue

                home = jogo.get("home_team", "Casa")
                away = jogo.get("away_team", "Fora")
                bookmakers = jogo.get("bookmakers", [])
                if not bookmakers:
                    continue

                hora_jogo = jogo_time.strftime("%d/%m %H:%M")

                # Mercado H2H (Resultado Final)
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

                    prob_c, prob_f, prob_e = (1 / avg_c) / margin, (1 / avg_fora) / margin if avg_fora else 0, (1 / avg_empate) / margin if avg_empate else 0

                    bwin_bk = next((bk for bk in bookmakers if bk.get("key") == "bwin"), None)
                    if bwin_bk:
                        for mk in bwin_bk.get("markets", []):
                            if mk.get("key") == "h2h":
                                for out in mk.get("outcomes", []):
                                    sel = out["name"]
                                    odd_bwin = out["price"]
                                    p = prob_c if sel == home else (prob_f if sel == away else prob_e)
                                    ev = calcular_ev(p, odd_bwin)

                                    if ev > 1.0: # Filtro de +EV > 1.0%
                                        msg = (
                                            f"⚽ *{home} vs {away}*\n"
                                            f"📅 *{hora_jogo} UTC*\n"
                                            f"🎯 Mercado: *Resultado Final*\n"
                                            f"🏆 Apostar em: *{sel}*\n"
                                            f"🏠 Casa: *Bwin*\n"
                                            f"📈 Odd Bwin: *{odd_bwin}*\n"
                                            f"💎 Valor Esperado (+EV): *+{ev}%*"
                                        )
                                        oportunidades.append(msg)

        if oportunidades:
            texto_final = "\n\n--------------------\n\n".join(oportunidades[:5])
            await update.message.reply_text(texto_final, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "⚠️ Nenhuma oportunidade +EV encontrada na Bwin para as próximas 48h nas ligas analisadas."
            )

    except Exception as e:
        logging.error(f"Erro ao analisar: {e}")
        await update.message.reply_text(f"❌ Erro de processamento: {e}")

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





