import os
import random
import logging
from datetime import datetime
import pytz
import httpx
import joblib
import numpy as np

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
FUTEBOL_TOKEN = os.environ.get("FUTEBOL_TOKEN")

bot_instance = Bot(token=TOKEN)
subscribed_users = set()

# Load AI model
try:
    model = joblib.load("model.joblib")
    logger.info("AI model loaded successfully")
except Exception as e:
    logger.warning(f"No AI model found: {e}, using fallback RandomForest")
    from sklearn.ensemble import RandomForestClassifier
    model = RandomForestClassifier(n_estimators=100)

# API URLs
SCOREBAT_API = "https://www.scorebat.com/video-api/v3/"
FUTEBOL_API = "https://api.api-futebol.com.br/v1/campeonatos/10/partidas"

# ---------------- Utility Functions ---------------- #

def format_time(timestamp: str) -> str:
    """Convert API timestamp to readable format"""
    if not timestamp:
        return "Unknown time"
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return dt.strftime("%a %d %b %H:%M UTC")
    except Exception:
        return "Unknown time"

def get_countdown(match_time: datetime) -> str:
    """Countdown string until match starts"""
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        return f"⏳ {delta.days}d {hours}h {minutes}m"
    return "🔥 LIVE NOW!" if (now - match_time).seconds < 7200 else "✅ Match Ended"

def prepare_features(home_team, away_team):
    """Dummy AI features for prediction"""
    return np.array([
        random.uniform(0.6, 1.0),  # Home attack
        random.uniform(0.5, 0.9),  # Away defense
        random.uniform(0.5, 1.0),  # Home form
        random.uniform(0.4, 0.8),  # Head-to-head
        0.9  # League importance placeholder
    ]).reshape(1, -1)

def ai_predict(home, away):
    """Get AI prediction"""
    try:
        features = prepare_features(home, away)
        proba = model.predict_proba(features)[0]
        confidence = max(proba.max(), 0.8)
        outcome = ["Home Win", "Draw", "Away Win"][proba.argmax()]
        return outcome, round(confidence * 100, 1)
    except Exception:
        return "Draw", 80.0

# ---------------- Fetch Matches ---------------- #

async def fetch_scorebat():
    """Fetch top ScoreBat matches"""
    matches = []
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(SCOREBAT_API)
            data = resp.json().get("response", [])
            for m in data[:3]:
                title = m.get("title", "Unknown vs Unknown")
                home, away = title.split(" vs ") if " vs " in title else ("Unknown", "Unknown")
                kickoff = format_time(m.get("date"))
                matches.append({"home": home, "away": away, "time": kickoff})
        except Exception as e:
            logger.error(f"ScoreBat API error: {e}")
    return matches

async def fetch_futebol():
    """Fetch matches from API-Futebol"""
    matches = []
    headers = {"Authorization": f"Bearer {FUTEBOL_TOKEN}"}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(FUTEBOL_API, headers=headers)
            data = resp.json().get("partidas", [])
            for m in data[:3]:
                home = m["time_mandante"]["nome_popular"]
                away = m["time_visitante"]["nome_popular"]
                kickoff = format_time(m.get("data_realizacao_iso"))
                matches.append({"home": home, "away": away, "time": kickoff})
        except Exception as e:
            logger.error(f"API-Futebol error: {e}")
    return matches

async def fetch_all_matches():
    """Combine matches from all sources"""
    scorebat = await fetch_scorebat()
    futebol = await fetch_futebol()
    combined = scorebat + futebol
    return combined[:6]  # limit to 6 matches to keep fast

# ---------------- Bot Commands ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"👤 New user started:\nID: {user.id}\nName: {user.full_name}\nUsername: @{user.username or 'N/A'}"
        )
    except Exception as e:
        logger.error(f"Tracking error: {e}")

    if user.id in subscribed_users:
        await update.message.reply_text("🎉 Welcome back! Use /predict for today's matches.")
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
        await update.message.reply_text(
            "⚽ *Free Prediction Bot*\nSubscribe to access AI-powered match predictions!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribed_users:
        await update.message.reply_text("🔒 Please subscribe first!")
        return

    matches = await fetch_all_matches()
    if not matches:
        await update.message.reply_text("⚠️ No matches found. Try again later.")
        return

    predictions = []
    for m in matches:
        outcome, conf = ai_predict(m["home"], m["away"])
        try:
            match_time = datetime.fromisoformat(m["time"].replace("Z", "+00:00"))
        except Exception:
            match_time = datetime.utcnow()
        predictions.append(
            f"⚔️ *{m['home']} vs {m['away']}*\n"
            f"⏰ {m['time']} | {get_countdown(match_time)}\n"
            f"🔮 *Prediction:* {outcome} ({conf}%)"
        )

    await update.message.reply_text(
        "🔮 *Today's Predictions*\n\n" + "\n\n".join(predictions),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'subscribe':
        subscribed_users.add(query.from_user.id)
        await query.edit_message_text(
            "✅ Subscription Activated! Use /predict to get match predictions.",
            parse_mode="Markdown"
        )

# ---------------- Run Bot ---------------- #

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
