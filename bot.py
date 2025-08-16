import requests
import random
import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Setup logging
logging.basicConfig(level=logging.INFO)

# Load from environment variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")
CHANNEL_ID = os.environ.get("CHANNEL_ID")  # e.g., '@YourPublicChannel'
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g., "https://yourrailwayapp.up.railway.app/"
PORT = int(os.environ.get("PORT", 8443))

SUBSCRIPTION_PRICE = 5  # USD

# In-memory subscription system (replace with DB for production)
subscribed_users = {}

# Bot instance for sending messages to the channel
bot_instance = Bot(token=TOKEN)

def get_upcoming_matches():
    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        matches = response.json().get("matches", [])
        return matches[:5]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching matches: {e}")
        return []

def predict_match(home_team, away_team):
    return {
        "prediction": f"{home_team} vs {away_team}",
        "likely_winner": home_team if random.random() > 0.5 else away_team,
        "odds": f"{random.uniform(1.5, 3.0):.2f}"
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "No username"
    first_name = user.first_name
    last_name = user.last_name or ""

    # Forward start info to your Telegram channel
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"🆕 New user started the bot:\n"
                 f"ID: {user_id}\n"
                 f"Username: {username}\n"
                 f"Name: {first_name} {last_name}"
        )
    except Exception as e:
        logging.error(f"Error sending to channel: {e}")

    if user_id in subscribed_users:
        await update.message.reply_text(
            "🔮 **Match Prediction Bot**\n\n"
            "You are subscribed! Use /predict to get today's match forecasts.",
            parse_mode="Markdown"
        )
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe ($5/month)", callback_data='subscribe')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🔮 **Welcome to Match Prediction Bot!**\n\n"
            "🚀 Get **AI-powered match predictions** before anyone else!\n"
            "🔒 **Subscription required:** $5/month\n\n"
            "Click below to subscribe:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribed_users:
        await update.message.reply_text("❌ You must **subscribe** first! Use /start.", parse_mode="Markdown")
        return
    
    matches = get_upcoming_matches()
    if not matches:
        await update.message.reply_text("⚽ No matches today. Check back later!")
        return

    predictions = []
    for match in matches:
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]
        pred = predict_match(home, away)
        predictions.append(
            f"⚽ **{home} vs {away}**\n"
            f"📊 Likely Winner: **{pred['likely_winner']}**\n"
            f"🎲 Odds: **{pred['odds']}**"
        )

    await update.message.reply_text(
        "🔮 **Today's Predictions**\n\n" + "\n\n".join(predictions),
        parse_mode="Markdown"
    )

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id

    if query.data == "subscribe":
        subscribed_users[user_id] = True
        await query.answer()
        await query.edit_message_text(
            "✅ **Subscription Successful!**\n\n"
            "You now have access to:\n"
            "- Daily match predictions\n"
            "- Winning odds analysis\n\n"
            "Use /predict to get started!",
            parse_mode="Markdown"
        )

def main():
    if not (TOKEN and FOOTBALL_API_KEY and CHANNEL_ID and WEBHOOK_URL):
        logging.error("Missing environment variables.")
        return

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('predict', predict))
    application.add_handler(CallbackQueryHandler(button_click))

    logging.info("✅ Bot is starting with webhook...")

    # Start webhook for Railway
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}{TOKEN}"
    )

if __name__ == "__main__":
    main()
