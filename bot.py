import os
import random
import logging
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging
logging.basicConfig(level=logging.INFO)

# Environment variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")  # e.g., @YourPublicChannel
FREE_API_URLS = [
    "https://www.scorebat.com/video-api/v3/",  # Free video highlight + match info
    "https://api.api-futebol.com.br/v1/",  # Brazil league
    "https://api.sportsdata.io/v4/soccer/scores/json/GamesByDate/"
]
SUBSCRIPTION_PRICE = 5
subscribed_users = {}
bot_instance = Bot(token=TOKEN)

def fetch_predictions():
    all_predictions = []
    for api_url in FREE_API_URLS:
        try:
            headers = {}
            if "scorebat" in api_url:
                resp = requests.get(api_url)
                data = resp.json().get("response", [])
                for match in data[:3]:
                    title = match.get("title", "Unknown Match")
                    prediction = random.choice(["1", "X", "2"])
                    all_predictions.append(f"⚽ {title}\n📈 Prediction: **{prediction}**")
            elif "api-futebol" in api_url:
                headers = {"Authorization": f"Bearer {os.getenv('FUTEBOL_TOKEN')}"}
                resp = requests.get(f"{api_url}campeonatos/10/partidas", headers=headers)
                data = resp.json().get("partidas", [])
                for game in data[:2]:
                    home = game['time_mandante']['nome_popular']
                    away = game['time_visitante']['nome_popular']
                    pred = random.choice([home, "Draw", away])
                    all_predictions.append(f"🏆 {home} vs {away}\n🔮 Likely Winner: **{pred}**")
        except Exception as e:
            logging.error(f"API error from {api_url}: {e}")
    return all_predictions

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"🆕 New user started the bot:\nID: {user.id}\nUsername: @{user.username or 'No username'}\nName: {user.full_name}"
        )
    except Exception as e:
        logging.error(f"Error sending message to channel: {e}")

    if user_id in subscribed_users:
        await update.message.reply_text(
            "🎉 Welcome back! Use /predict for today's match predictions.",
            parse_mode="Markdown")
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe ($5/month)", callback_data='subscribe')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚽ Welcome to **Free Prediction Bot**\n\nUnlock daily predictions with a subscription.",
            parse_mode="Markdown", reply_markup=reply_markup)

# /predict command
async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribed_users:
        await update.message.reply_text("❌ Please subscribe first! Use /start.", parse_mode="Markdown")
        return

    predictions = fetch_predictions()
    if not predictions:
        await update.message.reply_text("⚠️ No reliable predictions available now. Try later!")
        return

    await update.message.reply_text("🔮 **Today's Predictions**\n\n" + "\n\n".join(predictions), parse_mode="Markdown")

# Button click handler
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    if query.data == "subscribe":
        subscribed_users[user_id] = True
        await query.answer()
        await query.edit_message_text(
            "✅ Subscription Activated! Use /predict to see today's match predictions.",
            parse_mode="Markdown")

# Bot runner
def main():
    if not (TOKEN and CHANNEL_ID):
        logging.error("Missing required environment variables.")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_click))

    logging.info("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
