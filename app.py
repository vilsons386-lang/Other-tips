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
    return "Bot de Jogos do Dia está Online!"


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
        "👋 Olá! Envie /analisar para ver a lista dos próximos jogos (hoje e amanhã)."
    )


async def analisar(update: Update, context):
    await update.message.reply_text(
        "🔍 A procurar todos os jogos para as próximas 24-30 horas..."
    )

    try:
        if not ODDS_API_KEY:
            await update.message.reply_text(
                "❌ Erro: ODDS_API_KEY não configurada no Render."
            )
            return

        now_utc = datetime.now(timezone.utc)
        # Limite de tempo reduzido para apanhar APENAS jogos de HOJE/AMANHÃ (máx 30h)
        limite_tempo = now_utc + timedelta(hours=30)

        # Procura jogos nas ligas disponíveis
        url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
        
        # Se a rota genérica falhar, tenta ligas específicas
        res = requests.get(url, timeout=10)
        dados = []

        if res.status_code == 200:
            dados = res.json()
        else:
            # Fallback para Premier League e Liga Portugal
            for liga in ["soccer_epl", "soccer_portugal_primeira_liga", "soccer_spain_la_liga"]:
                u = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
                r = requests.get(u, timeout=8)
                if r.status_code == 200 and r.json():
                    dados.extend(r.json())

        if not dados:
            await update.message.reply_text("⚠️ Nenhum jogo encontrado no momento.")
            return

        lista_jogos = []

        for jogo in dados:
            commence_time_str = jogo.get("commence_time")
            if commence_time_str:
                jogo_time = datetime.fromisoformat(
                    commence_time_str.replace("Z", "+00:00")
                )
                # Filtra apenas o que acontece HOJE/AMANHÃ cedo
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

                # Apresenta a melhor odd disponível no mercado para a equipa da casa
                bk_melhor = max(
                    bookmakers,
                    key=lambda x: next(
                        (o["price"] for m in x["markets"] if m["key"] == "h2h" for o in m["outcomes"] if o["name"] == home),
                        0,
                    ),
                )
                casa_nome = bk_melhor.get("title", "Casa")
                odd_melhor = next(
                    (o["price"] for m in bk_melhor["markets"] if m["key"] == "h2h" for o in m["outcomes"] if o["name"] == home),
                    avg_c,
                )

                ev = calcular_ev(prob_c, odd_melhor)

                # Mostra TODOS os jogos sem filtrar por EV mínimo
                msg = (
                    f"⚽ *{home} vs {away}*\n"
                    f"📅 Hora: *{hora_jogo} UTC*\n"
                    f"🎯 Palpite: *{home} (Vitória Casa)*\n"
                    f"🏠 Melhor Casa: *{casa_nome}*\n"
                    f"📈 Odd: *{odd_melhor}*\n"
                    f"💎 Valor Calculado (+EV): *{'+' if ev > 0 else ''}{ev}%*"
                )
                lista_jogos.append((jogo_time, msg))

        if lista_jogos:
            # Ordena por hora do jogo (os mais próximos primeiro)
            lista_jogos.sort(key=lambda x: x[0])
            mensagens = [item[1] for item in lista_jogos[:8]]

            texto_final = "🔥 *Próximos Jogos de Hoje / Amanhã:*\n\n" + "\n\n--------------------\n\n".join(mensagens)
            await update.message.reply_text(texto_final, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "⚠️ Nenhum jogo agendado para as próximas 24 horas."
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
