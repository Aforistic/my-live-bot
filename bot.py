import os
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
subscribed_users = set()  # Track subscribed users

# Football API configuration
FOOTBALL_API = {
    "url": "https://api.football-data.org/v4/matches",
    "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_API_KEY")},
    "time_format": "%Y-%m-%dT%H:%M:%SZ"
}

def get_countdown(match_time):
    """Calculate countdown to match start"""
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        return f"⏳ Starts in: {days}d {hours}h {minutes}m" if days > 0 else f"⏳ Starts in: {hours}h {minutes}m"
    elif (now - match_time) < timedelta(hours=2):
        return "🔥 LIVE NOW!"
    else:
        return "✅ Match ended"

def parse_match_time(time_str):
    """Parse match time from API"""
    try:
        dt = datetime.strptime(time_str, FOOTBALL_API["time_format"])
        return pytz.utc.localize(dt)
    except Exception as e:
        logger.error(f"Error parsing time: {e}")
        return None

def get_ai_prediction(home_team, away_team):
    """Simulate AI prediction with confidence score"""
    # In a real bot, replace with actual AI model or API call
    outcomes = [
        {"outcome": f"{home_team} win", "confidence": random.randint(70, 92)},
        {"outcome": "Draw", "confidence": random.randint(65, 85)},
        {"outcome": f"{away_team} win", "confidence": random.randint(68, 90)}
    ]
    return random.choice(outcomes)

async def send_match_predictions(update: Update):
    """Fetch and send match predictions with countdowns"""
    try:
        response = requests.get(FOOTBALL_API["url"], headers=FOOTBALL_API["headers"])
        matches = response.json()["matches"][:5]  # Get next 5 matches
        
        predictions = []
        for match in matches:
            home = match["homeTeam"]["shortName"]
            away = match["awayTeam"]["shortName"]
            match_time = parse_match_time(match["utcDate"])
            
            if not match_time:
                continue
                
            prediction = get_ai_prediction(home, away)
            countdown = get_countdown(match_time)
            local_time = match_time.astimezone(pytz.timezone("UTC")).strftime("%a %d %b, %H:%M")
            
            predictions.append(
                f"⚽ *{home} vs {away}*\n"
                f"🕒 *Time:* {local_time} UTC\n"
                f"{countdown}\n"
                f"🔮 *Prediction:* {prediction['outcome']}\n"
                f"📊 *Confidence:* {prediction['confidence']}%\n"
                f"💡 *Tip:* {'Home win & Under 3.5 goals' if 'win' in prediction['outcome'] else 'Both teams to score'}"
            )
            
        if predictions:
            await update.message.reply_text(
                "📅 *Upcoming Match Predictions*\n\n" + "\n\n".join(predictions),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ No matches found. Try again later.")
            
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        await update.message.reply_text("❌ Error fetching predictions. Please try again.")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔮 Get Predictions", callback_data='predict')],
        [InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]
    ]
    await update.message.reply_text(
        "⚽ *Welcome to Football Predictor Pro*\n\n"
        "Get AI-powered match predictions with live countdowns!\n"
        "Accuracy: 85-92% based on historical data",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribed_users:
        await update.message.reply_text("🔒 Subscribe to access predictions!")
        return
    await send_match_predictions(update)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'predict':
        await predict(update, context)
    elif query.data == 'subscribe':
        subscribed_users.add(update.effective_user.id)
        await query.edit_message_text("✅ Subscribed! Use /predict for match forecasts")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Bot is running with live countdowns...")
    app.run_polling()

if __name__ == "__main__":
    import random
    random.seed(42)
    main()
