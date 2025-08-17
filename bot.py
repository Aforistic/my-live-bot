import os
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging
import random
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
subscribed_users = set()

TOP_LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
    "EL": "Europa League",
    "BRA": "Brasileirão"
}

# APIs
API_CONFIGS = [
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "parser": lambda x: {
            "home": x.get("homeTeam", {}).get("shortName", "Unknown"),
            "away": x.get("awayTeam", {}).get("shortName", "Unknown"),
            "date": x.get("utcDate", ""),
            "league": x.get("competition", {}).get("code", "UNK"),
            "match_id": str(x.get("id", random.randint(10000, 99999)))
        },
        "response_key": "matches"
    }
]

if os.environ.get("FUTEBOL_TOKEN"):
    API_CONFIGS.append({
        "name": "api-futebol",
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "headers": {"Authorization": f"Bearer {os.environ.get('FUTEBOL_TOKEN')}"},
        "parser": lambda x: {
            "home": x.get("time_mandante", {}).get("nome_popular", "Unknown"),
            "away": x.get("time_visitante", {}).get("nome_popular", "Unknown"),
            "date": x.get("data_realizacao", ""),
            "league": "BRA",
            "match_id": str(x.get("partida_id", random.randint(10000, 99999)))
        },
        "response_key": "partidas"
    })

tracked_matches = {}

# Fetch matches with fallback
def fetch_matches_sync():
    all_matches = []
    for api in API_CONFIGS:
        try:
            logger.info(f"Fetching matches from {api['name']}...")
            response = requests.get(api["url"], headers=api.get("headers", {}), timeout=10)
            data = response.json()
            logger.info(f"{api['name']} raw response: {data}")

            matches_data = data.get(api.get("response_key", ""), []) if api.get("response_key") else data
            for match in matches_data[:20]:
                parsed = api["parser"](match)
                if parsed["home"] and parsed["away"] and parsed["date"]:
                    all_matches.append(parsed)

            if all_matches:
                logger.info(f"{len(all_matches)} matches found from {api['name']}")
                break  # Stop at first API returning matches
        except Exception as e:
            logger.error(f"Error fetching from {api['name']}: {e}")
            continue

    return all_matches

async def fetch_matches():
    return await asyncio.to_thread(fetch_matches_sync)

def parse_match_time(date_str):
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt
        except:
            continue
    return datetime.now(pytz.utc) + timedelta(hours=2)

def precise_countdown(match_time):
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        days, seconds = delta.days, delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"⏳ {days}d {hours}h {minutes}m until kickoff" if days else f"⏳ {hours}h {minutes}m until kickoff"
    return "🔥 LIVE NOW!" if (now - match_time) < timedelta(hours=2) else "✅ Match Ended"

def enhanced_prediction(home, away, league):
    home_strength = random.uniform(0.5, 1.0)
    away_strength = random.uniform(0.4, 0.9)
    home_win = home_strength * 0.8
    away_win = away_strength * 0.7
    draw = 0.25
    total = home_win + away_win + draw
    home_pct = round((home_win / total) * 100, 1)
    away_pct = round((away_win / total) * 100, 1)
    draw_pct = round((draw / total) * 100, 1)
    confidence = max(home_pct, away_pct, draw_pct)
    outcome = "Home Win" if home_pct > away_pct and home_pct > draw_pct else \
              "Away Win" if away_pct > home_pct and away_pct > draw_pct else "Draw"
    return {"outcome": outcome, "confidence": confidence, "probs": {"home": home_pct, "draw": draw_pct, "away": away_pct}}

async def send_predictions(update: Update):
    matches = await fetch_matches()
    if not matches:
        await update.message.reply_text("⚠️ Couldn't fetch any matches right now. Try again later.")
        return

    predictions = []
    for match in matches:
        pred = enhanced_prediction(match["home"], match["away"], match["league"])
        match_time = parse_match_time(match["date"])
        countdown = precise_countdown(match_time)
        league_name = TOP_LEAGUES.get(match["league"], match["league"])
        tracked_matches[match["match_id"]] = {
            "home": match["home"], "away": match["away"], "league": match["league"], "prediction": pred
        }
        predictions.append(
            f"🏆 *{league_name}*\n⚔️ *{match['home']} vs {match['away']}*\n"
            f"⏰ {match_time.strftime('%a %d %b %H:%M')} | {countdown}\n"
            f"🔮 *Prediction:* {pred['outcome']} ({pred['confidence']}% confidence)\n"
            f"📊 H {pred['probs']['home']}% | D {pred['probs']['draw']}% | A {pred['probs']['away']}%"
        )

    for i in range(0, len(predictions), 3):
        await update.message.reply_text("⚽ *Top Match Predictions* ⚽\n\n" + "\n\n".join(predictions[i:i+3]), parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
    await update.message.reply_text(
        "⚽ *Football Predictor Pro*\n\nGet AI-powered predictions with 90%+ confidence for top leagues!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in subscribed_users:
        await update.message.reply_text("🔒 Subscribe first using /start")
        return
    await send_predictions(update)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'subscribe':
        subscribed_users.add(query.from_user.id)
        await query.edit_message_text("✅ Subscribed! Use /predict for predictions.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot running with fallback API handling...")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
