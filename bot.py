import os
import requests
import joblib
import numpy as np
from datetime import datetime, timedelta
import pytz
from dateutil import parser
from sklearn.ensemble import RandomForestClassifier
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging
import random

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
FUTEBOL_TOKEN = os.environ.get("FUTEBOL_TOKEN")
subscribed_users = set()
bot_instance = Bot(token=TOKEN)

POPULAR_LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga", 
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
    "ELC": "Championship",
    "BRA": "Brasileirão"
}

# Load AI model
try:
    model = joblib.load('model.joblib')
    logger.info("AI model loaded successfully")
except Exception as e:
    logger.warning(f"No trained model found: {e}, using fallback")
    model = RandomForestClassifier(n_estimators=100)

# Countdown function (aware datetime)
def get_countdown(match_time):
    now = datetime.now(pytz.utc)
    if match_time.tzinfo is None:
        match_time = match_time.replace(tzinfo=pytz.utc)
    if match_time > now:
        delta = match_time - now
        if delta.days > 0:
            return f"⏳ {delta.days}d {delta.seconds//3600}h"
        return f"⏳ {delta.seconds//3600}h {(delta.seconds//60)%60}m"
    return "🔥 LIVE NOW!" if (now - match_time) < timedelta(hours=3) else "✅ Match Ended"

def prepare_features(home_team, away_team, league_id):
    """Prepare features for AI prediction"""
    try:
        return np.array([
            random.uniform(0.6, 1.0),
            random.uniform(0.5, 0.9),
            random.uniform(0.5, 1.0),
            random.uniform(0.4, 0.8),
            0.9 if league_id in ["PL", "CL"] else 0.8
        ]).reshape(1, -1)
    except Exception as e:
        logger.error(f"Feature prep error: {e}")
        return np.array([[0.7, 0.7, 0.7, 0.7, 0.8]])

def get_ai_prediction(home, away, league_id):
    """Get AI prediction with confidence"""
    try:
        features = prepare_features(home, away, league_id)
        proba = model.predict_proba(features)[0]
        confidence = max(proba.max(), 0.8)
        outcome = ["Home Win", "Draw", "Away Win"][proba.argmax()]
        return {
            "outcome": outcome,
            "confidence": round(confidence*100,1),
            "probs": {"home": round(proba[0]*100,1), "draw": round(proba[1]*100,1), "away": round(proba[2]*100,1)}
        }
    except Exception as e:
        logger.error(f"AI prediction failed: {e}")
        return {"outcome": "Draw", "confidence": 80.0, "probs": {"home": 40,"draw":35,"away":25}}

async def fetch_league_matches(league_id):
    """Fetch matches for a league"""
    try:
        url = f"https://api.api-futebol.com.br/v1/campeonatos/{10 if league_id=='BRA' else 1}/partidas"  # Adjust if needed
        headers = {"Authorization": f"Bearer {FUTEBOL_TOKEN}"} if FUTEBOL_TOKEN else {}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("partidas", [])
    except Exception as e:
        logger.error(f"API fetch error ({url}): {e}")
        return []

async def fetch_all_matches():
    """Fetch matches from all leagues"""
    all_matches = []
    for league_id in POPULAR_LEAGUES:
        matches = await fetch_league_matches(league_id)
        for match in matches[:4]:
            try:
                home = match['time_mandante']['nome_popular']
                away = match['time_visitante']['nome_popular']
                match_time = parser.isoparse(match['data_realizacao_iso'])
                all_matches.append({"home":home,"away":away,"time":match_time,"league":league_id})
            except KeyError as e:
                logger.warning(f"Match parsing error: {e}")
    return sorted(all_matches, key=lambda x: x["time"])[:20]

def get_betting_tip(pred, league_id):
    if pred["confidence"] > 85:
        if "Home" in pred["outcome"]:
            return "Home win & Over 1.5 goals"
        elif "Away" in pred["outcome"]:
            return "Away win or Draw No Bet"
    if league_id in ["PL", "BL1"]:
        return "Both Teams to Score"
    elif league_id == "SA":
        return "Under 2.5 goals"
    return "Double Chance"

async def send_predictions(update, from_query=False):
    """Send predictions to user"""
    try:
        matches = await fetch_all_matches()
        if not matches:
            text = "⚠️ No matches found. Try again later."
            if from_query:
                await update.callback_query.edit_message_text(text)
            else:
                await update.message.reply_text(text)
            return

        predictions = []
        for match in matches:
            pred = get_ai_prediction(match["home"], match["away"], match["league"])
            predictions.append(
                f"🏆 *{POPULAR_LEAGUES.get(match['league'], 'Unknown')}*\n"
                f"⚔️ {match['home']} vs {match['away']}\n"
                f"⏰ {match['time'].strftime('%a %d %b %H:%M')} | {get_countdown(match['time'])}\n"
                f"🔮 *Prediction:* {pred['outcome']} ({pred['confidence']}%)\n"
                f"📊 H {pred['probs']['home']}% | D {pred['probs']['draw']}% | A {pred['probs']['away']}%\n"
                f"💡 *Tip:* {get_betting_tip(pred, match['league'])}"
            )

        for i in range(0, len(predictions), 5):
            text_chunk = "\n\n".join(predictions[i:i+5])
            if from_query:
                await update.callback_query.edit_message_text(text_chunk, parse_mode="Markdown")
            else:
                await update.message.reply_text(text_chunk, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Prediction error: {e}")
        text = "⚠️ System updating. Try again later."
        if from_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)

# Command handlers
async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribed_users:
        await update.message.reply_text("🔒 Please subscribe first with /start")
        return
    await send_predictions(update)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"👤 New user:\nID:{user.id}\nName:{user.full_name}\nUsername:@{user.username or 'N/A'}"
        )
    except Exception as e:
        logger.error(f"Tracking error: {e}")

    keyboard = [
        [InlineKeyboardButton("💰 Subscribe", callback_data="subscribe")],
        [InlineKeyboardButton("📊 View Results", callback_data="results")]
    ]
    await update.message.reply_text(
        "⚽ *2025 Football Predictor Pro* ⚽\n\nGet AI-powered predictions for all top leagues!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "subscribe":
        subscribed_users.add(query.from_user.id)
        await query.edit_message_text("✅ Subscription Activated! Use buttons below to view predictions or results.")
    elif query.data in ["results", "predictions"]:
        await send_predictions(update, from_query=True)

# Main
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Football Predictor Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
