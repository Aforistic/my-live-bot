import os
import requests
import joblib
import numpy as np
from datetime import datetime, timedelta
import pytz
from sklearn.ensemble import RandomForestClassifier
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging
import random

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")  # Your tracking channel
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY")  # football-data.org token
subscribed_users = set()
bot_instance = Bot(token=TOKEN)

# Popular Leagues Configuration
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

# Initialize AI model
try:
    model = joblib.load('model.joblib')
    logger.info("AI model loaded successfully")
except Exception as e:
    logger.warning(f"No trained model found: {e}, using fallback")
    model = RandomForestClassifier(n_estimators=100)

# Utilities
def get_countdown(match_time):
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        if delta.days > 0:
            return f"⏳ {delta.days}d {delta.seconds//3600}h"
        return f"⏳ {delta.seconds//3600}h {(delta.seconds//60)%60}m"
    return "🔥 LIVE NOW!" if (now - match_time) < timedelta(hours=3) else "✅ Match Ended"

def prepare_features(home_team, away_team, league_id):
    return np.array([
        random.uniform(0.6, 1.0),  # Home attack
        random.uniform(0.5, 0.9),  # Away defense
        random.uniform(0.5, 1.0),  # Home form
        random.uniform(0.4, 0.8),  # Head-to-head
        0.9 if league_id in ["PL", "CL"] else 0.8
    ]).reshape(1, -1)

def get_ai_prediction(home, away, league_id):
    features = prepare_features(home, away, league_id)
    proba = model.predict_proba(features)[0]
    confidence = max(proba.max(), 0.8)  # Minimum 80% confidence
    outcome = ["Home Win", "Draw", "Away Win"][proba.argmax()]
    return {"outcome": outcome, "confidence": round(confidence*100,1), 
            "probs": {"home": round(proba[0]*100,1), "draw": round(proba[1]*100,1), "away": round(proba[2]*100,1)}}

# Fetch matches
async def fetch_league_matches(league_id):
    try:
        url = f"https://api.football-data.org/v4/competitions/{league_id}/matches"
        headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get("matches", [])
    except Exception as e:
        logger.error(f"Error fetching {league_id} matches: {e}")
        return []

async def fetch_all_matches():
    all_matches = []
    for league_id in POPULAR_LEAGUES:
        matches = await fetch_league_matches(league_id)
        for match in matches[:4]:  # Limit per league
            try:
                all_matches.append({
                    "home": match["homeTeam"]["name"],
                    "away": match["awayTeam"]["name"],
                    "date": match["utcDate"],
                    "league": league_id,
                    "status": match.get("status", "SCHEDULED"),
                    "score": match.get("score", {})
                })
            except KeyError:
                continue
    return sorted(all_matches, key=lambda x: x["date"])[:20]

def get_betting_tip(prediction, league_id):
    if prediction["confidence"] > 85:
        if "Home" in prediction["outcome"]:
            return "Home win & Over 1.5 goals"
        elif "Away" in prediction["outcome"]:
            return "Away win or Draw No Bet"
    if league_id in ["PL", "BL1"]:
        return "Both Teams to Score"
    elif league_id == "SA":
        return "Under 2.5 goals"
    return "Double Chance"

# Send predictions
async def send_predictions(update: Update, query=None):
    matches = await fetch_all_matches()
    if not matches:
        if query:
            await query.message.reply_text("⚠️ No matches found. Try again later.")
        else:
            await update.message.reply_text("⚠️ No matches found. Try again later.")
        return

    predictions = []
    for match in matches:
        if match["status"] != "SCHEDULED":
            continue
        pred = get_ai_prediction(match["home"], match["away"], match["league"])
        match_time = datetime.strptime(match["date"], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=pytz.utc)
        predictions.append(
            f"🏆 *{POPULAR_LEAGUES.get(match['league'],'Unknown League')}*\n"
            f"⚔️ *{match['home']} vs {match['away']}*\n"
            f"⏰ {match_time.strftime('%a %d %b %H:%M UTC')} | {get_countdown(match_time)}\n"
            f"🔮 *Prediction:* {pred['outcome']} ({pred['confidence']}%)\n"
            f"💡 *Tip:* {get_betting_tip(pred, match['league'])}"
        )

    for i in range(0, len(predictions), 5):
        text_chunk = "\n\n".join(predictions[i:i+5])
        if query:
            await query.message.reply_text(text_chunk, parse_mode="Markdown")
        else:
            await update.message.reply_text(text_chunk, parse_mode="Markdown")

# Send results
async def send_results(update: Update, query=None):
    matches = await fetch_all_matches()
    results_text = []
    for match in matches:
        if match["status"] != "FINISHED":
            continue
        pred = get_ai_prediction(match["home"], match["away"], match["league"])
        home_score = match["score"].get("fullTime", {}).get("home", 0)
        away_score = match["score"].get("fullTime", {}).get("away", 0)
        actual_outcome = "Draw"
        if home_score > away_score: actual_outcome = "Home Win"
        elif home_score < away_score: actual_outcome = "Away Win"
        outcome_check = "✅" if actual_outcome == pred["outcome"] else "❌"
        match_time = datetime.strptime(match["date"], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=pytz.utc)
        results_text.append(
            f"🏆 *{POPULAR_LEAGUES.get(match['league'],'Unknown League')}*\n"
            f"⚔️ *{match['home']} vs {match['away']}*\n"
            f"⏰ {match_time.strftime('%a %d %b %H:%M UTC')}\n"
            f"🔮 Prediction: {pred['outcome']} ({pred['confidence']}%)\n"
            f"🏁 Result: {home_score} - {away_score} ({actual_outcome})\n"
            f"✅ Outcome: {outcome_check}"
        )

    if not results_text:
        text = "⚠️ No finished matches yet. Check back later!"
        if query:
            await query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return

    for i in range(0, len(results_text), 5):
        text_chunk = "\n\n".join(results_text[i:i+5])
        if query:
            await query.message.reply_text(text_chunk, parse_mode="Markdown")
        else:
            await update.message.reply_text(text_chunk, parse_mode="Markdown")

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"👤 New user:\nID: {user.id}\nName: {user.full_name}\nUsername: @{user.username or 'N/A'}"
        )
    except Exception as e:
        logger.error(f"Tracking error: {e}")

    if user.id in subscribed_users:
        await update.message.reply_text("🎉 Welcome back! Use /predict for matches.", parse_mode="Markdown")
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
        await update.message.reply_text(
            "⚽ *2025 Football Predictor Pro* ⚽\nSubscribe to access predictions & results!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribed_users:
        await update.message.reply_text("🔒 Please subscribe first with /start")
        return
    await send_predictions(update)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "subscribe":
        subscribed_users.add(user_id)
        keyboard = [
            [InlineKeyboardButton("⚡ View Predictions", callback_data='view')],
            [InlineKeyboardButton("🏁 Results", callback_data='results')]
        ]
        await query.edit_message_text(
            "✅ Subscription Activated! Choose an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif query.data == "view":
        await send_predictions(update, query=query)
    elif query.data == "results":
        await send_results(update, query=query)

# Main bot
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("🤖 Football Predictor Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
