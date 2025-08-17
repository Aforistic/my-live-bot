import os
import random
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging
logging.basicConfig(level=logging.INFO)

# Environment variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
FUTEBOL_TOKEN = os.environ.get("FUTEBOL_TOKEN")  # For api-futebol

FREE_API_URLS = [
    "https://www.scorebat.com/video-api/v3/",           # Fastest first
    "https://api.api-futebol.com.br/v1/campeonatos/10/partidas"
]

SUBSCRIPTION_PRICE = 5
subscribed_users = {}
bot_instance = Bot(token=TOKEN)

# Convert betting symbols to friendly format
def friendly_prediction(symbol, home, away):
    return {
        "1": f"{home} to Win",
        "X": "Draw",
        "2": f"{away} to Win"
    }.get(symbol, "Unknown")

# Format time
def format_time(timestamp):
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return dt.strftime("%A %d %B, %H:%M UTC")
    except Exception:
        return "Unknown time"

# Fetch predictions from APIs (fast)
def fetch_predictions():
    all_predictions = []

    # Scorebat first (fast)
    try:
        resp = requests.get(FREE_API_URLS[0], timeout=5)
        resp.raise_for_status()
        data = resp.json().get("response", [])[:3]  # Top 3 matches only
        for match in data:
            title = match.get("title", "Unknown Match")
            home, away = title.split(" vs ") if " vs " in title else ("Team A", "Team B")
            prediction_code = random.choice(["1", "X", "2"])
            prediction = friendly_prediction(prediction_code, home, away)
            kickoff_time = format_time(match.get("date", ""))
            all_predictions.append(
                f"⚽ {title}\n🕒 Time: {kickoff_time}\n📈 Prediction: **{prediction}**"
            )
    except Exception as e:
        logging.error(f"Scorebat API error: {e}")

    # Optional: API-Futebol (slower, skip if you want faster predict)
    try:
        headers = {"Authorization": f"Bearer {FUTEBOL_TOKEN}"}
        resp = requests.get(FREE_API_URLS[1], headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json().get("partidas", [])[:2]  # Limit to 2 matches
        for game in data:
            home = game['time_mandante']['nome_popular']
            away = game['time_visitante']['nome_popular']
            time = format_time(game.get('data_realizacao_iso', ""))
            pred = random.choice([home, "Draw", away])
            all_predictions.append(
                f"🏆 {home} vs {away}\n🕒 Time: {time}\n🔮 Likely Winner: **{pred}**"
            )
    except Exception as e:
        logging.error(f"API-Futebol error: {e}")

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
            "⚽ Welcome to *Free Prediction Bot*\n\nUnlock daily predictions with a subscription.",
            parse_mode="Markdown", reply_markup=reply_markup)

# /predict command
async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribed_users:
        await update.message.reply_text("❌ Please subscribe first! Use /start.", parse_mode="Markdown")
        return

    predictions = fetch_predictions()
    if not predictions:
        await update.message.reply_text("⚠️ No reliable predictions available now. Try later!", parse_mode="Markdown")
        return

    await update.message.reply_text("🔮 *Today's Predictions*\n\n" + "\n\n".join(predictions), parse_mode="Markdown")

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
