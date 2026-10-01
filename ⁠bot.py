import logging
import requests
import numpy as np
from scipy.stats import poisson
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- INSERE AS TUAS CHAVES AQUI ---
TELEGRAM_TOKEN = "TEU_TOKEN_DO_BOTFATHER"
ODDS_API_KEY = "TUA_KEY_DA_THE_ODDS_API"  # A chave df1843e55bbf8c... da imagem

logging.basicConfig(level=logging.INFO)

def calcular_poisson(gp_casa=1.6, gc_casa=0.9, gp_vis=1.2, gc_vis=1.4):
    l_casa = (gp_casa / 1.4) * (gc_vis / 1.4) * 1.4
    l_vis = (gp_vis / 1.1) * (gc_casa / 1.1) * 1.1
    
    matriz = np.zeros((6, 6))
    for i in range(6):
        for j in range(6):
            matriz[i, j] = poisson.pmf(i, l_casa) * poisson.pmf(j, l_vis)
            
    p_casa = float(np.sum(np.tril(matriz, -1)))
    p_empate = float(np.sum(np.diag(matriz)))
    p_vis = float(np.sum(np.triu(matriz, 1)))
    
    return {'h2h_home': p_casa, 'h2h_draw': p_empate, 'h2h_away': p_vis}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Bot de Apostas +EV Ativo!*\n\n"
        "Comandos disponíveis:\n"
        "• `/analisar` - Procura odds de valor em tempo real.",
        parse_mode="Markdown"
    )

async def analisar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 A procurar jogos e odds de valor...")
    
    url = 'https://api.the-odds-api.com/v4/sports/soccer_epl/odds/'
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': 'eu',
        'markets': 'h2h'
    }
    
    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            await update.message.reply_text("❌ Erro ao ligar à API de Odds.")
            return
            
        jogos = response.json()
        probs_modelo = calcular_poisson()
        alertas = 0

        for jogo in jogos[:3]:
            home = jogo['home_team']
            away = jogo['away_team']
            
            for bookmaker in jogo.get('bookmakers', []):
                casa = bookmaker['title']
                for market in bookmaker.get('markets', []):
                    if market['key'] == 'h2h':
                        for outcome in market['outcomes']:
                            selecao = outcome['name']
                            odd_casa = outcome['price']
                            
                            prob = probs_modelo['h2h_home'] if selecao == home else (probs_modelo['h2h_away'] if selecao == away else probs_modelo['h2h_draw'])
                            odd_justa = 1 / prob if prob > 0 else 0
                            ev = (prob * odd_casa) - 1
                            
                            if ev >= 0.05:
                                alertas += 1
                                msg = (
                                    f"🚨 *APOSTA DE VALOR (+EV)* 🚨\n\n"
                                    f"⚽ *Jogo:* {home} vs {away}\n"
                                    f"🎯 *Aposta:* {selecao}\n"
                                    f"🏦 *Casa:* {casa}\n"
                                    f"📈 *Odd da Casa:* `{odd_casa}`\n"
                                    f"📐 *Odd Justa:* `{odd_justa:.2f}`\n"
                                    f"💰 *+EV:* `+{ev*100:.1f}%`"
                                )
                                await update.message.reply_text(msg, parse_mode="Markdown")
                                
        if alertas == 0:
            await update.message.reply_text("ℹ️ Nenhuma aposta +EV encontrada no momento.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro ao processar: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analisar", analisar))
    app.run_polling()
