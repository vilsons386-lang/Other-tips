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

# Servidor Flask para manter o Render ativo
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot de Apostas +EV (Bwin - H2H e Golos) está Online!"


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
        "👋 Olá! Envie /analisar para procurar oportunidades +EV na Bwin (Resultado Final e Golos Over/Under)."
    )


async def analisar(update: Update, context):
    await update.message.reply_text(
        "🔍 A analisar mercados de H2H e Golos (Over/Under) na Bwin..."
    )

    try:
        if not ODDS_API_KEY:
            await update.message.reply_text(
                "❌ Erro: ODDS_API_KEY não configurada no Render."
            )
            return

        # Solicita os mercados h2h e totals (Golos Over/Under)
        url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals"
        res = requests.get(url, timeout=15)

        if res.status_code != 200:
            await update.message.reply_text(
                f"❌ Erro na Odds API ({res.status_code})."
            )
            return

        dados = res.json()
        if not dados:
            await update.message.reply_text(
                "⚠️ Nenhum jogo encontrado no momento."
            )
            return

        now_utc = datetime.now(timezone.utc)
        limite_tempo = now_utc + timedelta(hours=48)

        oportunidades = []

        for jogo in dados:
            commence_time_str = jogo.get("commence_time")
            if commence_time_str:
                jogo_time = datetime.fromisoformat(
                    commence_time_str.replace("Z", "+00:00")
                )
                if jogo_time < now_utc or jogo_time > limite_tempo:
                    continue

            home = jogo.get("home_team", "Casa")
            away = jogo.get("away_team", "Fora")
            bookmakers = jogo.get("bookmakers", [])

            if not bookmakers:
                continue

            hora_jogo = jogo_time.strftime("%d/%m %H:%M")

            # --- ANALISAR RESULTADO FINAL (H2H) ---
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
                margin_h2h = (1 / avg_c) + (1 / avg_f) + (1 / avg_e)

                prob_c = (1 / avg_c) / margin_h2h
                prob_f = (1 / avg_f) / margin_h2h
                prob_e = (1 / avg_e) / margin_h2h

                bwin_bk = next((bk for bk in bookmakers if bk.get("key") == "bwin"), None)
                if bwin_bk:
                    for mk in bwin_bk.get("markets", []):
                        if mk.get("key") == "h2h":
                            for out in mk.get("outcomes", []):
                                sel = out["name"]
                                odd_bwin = out["price"]
                                p = prob_c if sel == home else (prob_f if sel == away else prob_e)
                                ev = calcular_ev(p, odd_bwin)

                                if ev > 1.5:
                                    msg = (
                                        f"⚽ *{home} vs {away}*\n"
                                        f"📅 *{hora_jogo} UTC*\n"
                                        f"🎯 Mercado: *Resultado Final*\n"
                                        f"🏆 Escolha: *{sel}*\n"
                                        f"🏠 Casa: *Bwin*\n"
                                        f"📈 Odd Bwin: *{odd_bwin}*\n"
                                        f"💎 Valor Esperado (+EV): *+{ev}%*"
                                    )
                                    oportunidades.append(msg)

            # --- ANALISAR GOLOS OVER/UNDER (TOTALS) ---
            odds_over, odds_under = {}, {}
            for bk in bookmakers:
                for mk in bk.get("markets", []):
                    if mk.get("key") == "totals":
                        for out in mk.get("outcomes", []):
                            point = out.get("point")
                            if point not in odds_over:
                                odds_over[point] = []
                                odds_under[point] = []
                            if out["name"] == "Over":
                                odds_over[point].append(out["price"])
                            elif out["name"] == "Under":
                                odds_under[point].append(out["price"])

            bwin_bk = next((bk for bk in bookmakers if bk.get("key") == "bwin"), None)
            if bwin_bk:
                for mk in bwin_bk.get("markets", []):
                    if mk.get("key") == "totals":
                        for out in mk.get("outcomes", []):
                            point = out.get("point")
                            sel_type = out["name"]  # Over ou Under
                            odd_bwin = out["price"]

                            if point in odds_over and odds_over[point] and odds_under[point]:
                                avg_over = sum(odds_over[point]) / len(odds_over[point])
                                avg_under = sum(odds_under[point]) / len(odds_under[point])
                                margin_totals = (1 / avg_over) + (1 / avg_under)

                                prob = ((1 / avg_over) / margin_totals) if sel_type == "Over" else ((1 / avg_under) / margin_totals)
                                ev = calcular_ev(prob, odd_bwin)

                                if ev > 1.5:
                                    msg = (
                                        f"⚽ *{home} vs {away}*\n"
                                        f"📅 *{hora_jogo} UTC*\n"
                                        f"🎯 Mercado: *Golos ({sel_type} {point})*\n"
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
                "⚠️ Nenhuma oportunidade +EV encontrada na Bwin para Resultado Final ou Golos nas próximas 48h."
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

    print("Bot +EV Ativo...")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    await asyncio.Event().wait()


if __name__ == "__main__":
    thread_flask = Thread(target=run_flask)
    thread_flask.daemon = True
    thread_flask.start()

    asyncio.run(main())




