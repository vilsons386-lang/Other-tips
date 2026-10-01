import logging
import os
from threading import Thread
from flask import Flask
import numpy as np
from scipy.stats import poisson
from telegram import Update
from telegram.ext import Application, ApplicationBuilder



# --- SERVIDOR FLASK PARA O RENDER ---
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot Mytips ativo e a rodar!", 200


def run_http():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


Thread(target=run_http, daemon=True).start()

# --- CONFIGURAÇÃO DE CHAVES (VARIÁVEIS DE AMBIENTE) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")


# Configuração de Logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

def calcular_poisson(gp_casa=1.6, gc_casa=1.0, gp_fora=1.2, gc_fora=1.4):
    """Calcula probabilidades estimadas usando distribuição de Poisson."""
    lambda_casa = (gp_casa + gc_fora) / 2
    lambda_fora = (gp_fora + gc_casa) / 2
    
    prob_casa = 0.0
    prob_empate = 0.0
    prob_fora = 0.0
    
    for x in range(6):
        for y in range(6):
            p = poisson.pmf(x, lambda_casa) * poisson.pmf(y, lambda_fora)
            if x > y:
                prob_casa += p
            elif x == y:
                prob_empate += p
            else:
                prob_fora += p
                
    return prob_casa, prob_empate, prob_fora

def obter_odds_apostas():
    """Obtém odds de futebol em tempo real da The Odds API."""
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start para boas-vindas."""
    await update.message.reply_text(
        "👋 Bem-vindo ao Bot de Apostas +EV!\n\n"
        "Usa o comando /analisar para obter palpites com valor esperado positivo em tempo real."
    )

async def analisar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /analisar para identificar apostas +EV."""
    await update.message.reply_text("🔍 A procurar jogos e a calcular valor esperado (+EV)...")
    
    jogos = obter_odds_apostas()
    if not jogos:
        await update.message.reply_text("❌ Não foi possível obter odds no momento ou limite da API atingido.")
        return
        
    p_casa, p_empate, p_fora = calcular_poisson()
    mensagens = []
    
    for jogo in jogos[:3]:
        home_team = jogo.get("home_team", "Casa")
        away_team = jogo.get("away_team", "Fora")
        
        bookmakers = jogo.get("bookmakers", [])
        if not bookmakers:
            continue
            
        markets = bookmakers[0].get("markets", [])
        if not markets:
            continue
            
        outcomes = markets[0].get("outcomes", [])
        odd_casa = next((o["price"] for o in outcomes if o["name"] == home_team), 0)
        
        ev_casa = (p_casa * odd_casa) - 1
        
        status_ev = "🔥 +EV Encontrado!" if ev_casa > 0 else "⚪ Sem Valor"
        
        msg = (
            f"⚽ *{home_team} vs {away_team}*\n"
            f"📊 Prob. Estimada Casa: {p_casa*100:.1f}%\n"
            f"📈 Odd Mercado: {odd_casa}\n"
            f"💡 EV: {ev_casa*100:+.1f}%\n"
            f"📌 Status: {status_ev}\n"
        )
        mensagens.append(msg)
        
    texto_final = "\n-------------------\n".join(mensagens) if mensagens else "Nenhum jogo analisado no momento."
    await update.message.reply_text(texto_final, parse_mode="Markdown")

def main():
    """Inicia o bot."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analisar", analisar))
    
    print("Bot de Apostas +EV Ativo!")
    app.run_polling()

if __name__ == "__main__":
    main()
