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
    return "Bot +EV Sem Falhar está Online!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

def calcular_ev(probabilidade_fair, odd_oferecida):
    ev = (probabilidade_fair * odd_oferecida) - 1
    return round(ev * 100, 2)

async def start(update: Update, context):
    await update.message.reply_text(
        "👋 Envie /analisar para ver os melhores jogos e apostas +EV das próximas 48 horas!"
    )

async def analisar(update: Update, context):
    await update.message.reply_text("🔍 A obter todos os jogos das próximas 48h...")

    try:
        if not ODDS_API_KEY:
            await update.message.reply_text("❌ Erro: ODDS_API_KEY não configurada.")
            return

        now_utc = datetime.now(timezone.utc)
        limite_tempo = now_utc + timedelta(hours=48)

        # 1. Obter primeiro a lista de desportos/ligas com jogos ativos
        sports_url = f"https://api.the-odds-api.com/v4/sports/?apiKey={ODDS_API_KEY}"
        res_sports = requests.get(sports_url, timeout=10)
        
        ligas_futebol = []
        if res_sports.status_code == 200:
            for s in res_sports.json():
                if s.get("group") == "Soccer":
                    ligas_futebol.append(s.get("key"))

        # Fallback se não conseguir a lista de ligas
        if not ligas_futebol:
            ligas_futebol = ["soccer_epl", "soccer_spain_la_liga", "soccer_portugal_primeira_liga", "soccer_italy_serie_a"]

        oportunidades = []
        jogos_gerais = []

        # Analisa até 8 ligas ativas
        for liga in ligas_futebol[:8]:
            url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
            res = requests.get(url, timeout=8)

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
                else:
                    continue

                home = jogo.get("home_team", "Casa")
                away = jogo.get("away_team", "Fora")
                bookmakers = jogo.get("bookmakers", [])
                if not bookmakers:
                    continue

                hora_jogo = jogo_time.strftime("%d/%m %H:%M")

                # Cálculo de odds médias
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

                    # Guarda uma opção geral do jogo
                    bk_principal = bookmakers[0]
                    casa_nome_p = bk_principal.get("title", "Casa")
                    odd_p = bk_principal["markets"][0]["outcomes"][0]["price"]
                    
                    jogos_gerais.append(
                        f"⚽ *{home} vs {away}*\n"
                        f"📅 *{hora_jogo} UTC*\n"
                        f"🏠 Casa: *{casa_nome_p}*\n"
                        f"📈 Odd ({home}): *{odd_p}*"
                    )

                    # Verifica oportunidades +EV
                    for bk in bookmakers:
                        casa_nome = bk.get("title", "Desconhecida")
                        for mk in bk.get("markets", []):
                            if mk.get("key") == "h2h":
                                for out in mk.get("outcomes", []):
                                    sel = out["name"]
                                    odd = out["price"]
                                    p = prob_c if sel == home else (prob_f if sel == away else prob_e)
                                    ev = calcular_ev(p, odd)

                                    if ev > 0.1:  # Aceita qualquer valor positivo
                                        msg = (
                                            f"⚽ *{home} vs {away}*\n"
                                            f"📅 *{hora_jogo} UTC*\n"
                                            f"🎯 Escolha: *{sel}*\n"
                                            f"🏠 Casa: *{casa_nome}*\n"
                                            f"📈 Odd: *{odd}*\n"
                                            f"💎 Valor Esperado (+EV): *+{ev}%*"
                                        )
                                        oportunidades.append((ev, msg))

        # Exibição de Resultados
        if oportunidades:
            oportunidades.sort(key=lambda x: x[0], reverse=True)
            mensagens = [item[1] for item in oportunidades[:5]]
            texto_final = "🔥 *Oportunidades +EV Encontradas:*\n\n" + "\n\n--------------------\n\n".join(mensagens)
            await update.message.reply_text(texto_final, parse_mode="Markdown")
        elif jogos_gerais:
            texto_final = "📋 *Próximos Jogos Registados (Sem +EV alto de momento):*\n\n" + "\n\n--------------------\n\n".join(jogos_gerais[:3])
            await update.message.reply_text(texto_final, parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ Nenhum jogo agendado para as próximas 48 horas nas ligas consultadas.")

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
