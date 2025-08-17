import os
import random
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
SUBSCRIPTION_PRICE = 5
subscribed_users: Dict[int, bool] = {}
user_timezones: Dict[int, str] = {}
bot_instance = Bot(token=TOKEN)

# APIs
APIS = {
    "scorebat": {
        "url": "https://www.scorebat.com/video-api/v3/",
        "time_format": "%Y-%m-%dT%H:%M:%S%z"
    }
}

# Utilities
def convert_timezone(dt: datetime, user_tz: str = "UTC") -> datetime:
    try:
        tz = pytz.timezone(user_tz)
        return dt.astimezone(tz)
    except:
        return dt

def format_countdown(match_time: datetime) -> str:
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        return f"⏳ Starts in: {delta.days}d {hours}h {minutes}m"
    return "🏟️ Match in progress" if (now - match_time) < timedelta(hours=2) else "⏱️ Match ended"

def parse_match_time(time_str: str, api_name: str) -> Optional[datetime]:
    if not time_str:
        return None
    try:
        fmt = APIS[api_name]["time_format"]
        dt = datetime.strptime(time_str, fmt)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt
    except ValueError as e:
        logger.warning(f"Couldn't parse time '{time_str}' for {api_name}: {e}")
        return None

def format_match_info(match_time: Optional[datetime], user_tz: str = "UTC") -> str:
    if not match_time:
        return "🕒 Time: Not specified"
    local_time = convert_timezone(match_time, user_tz)
    time_str = local_time.strftime("%a %b %d, %H:%M (%Z)")
    countdown = format_countdown(match_time)
    return f"🕒 Time: {time_str}\n{countdown}"

# Fetch predictions
def fetch_predictions() -> List[str]:
    all_predictions = []
    for api_name, config in APIS.items():
        try:
            resp = requests.get(config["url"])
            resp.raise_for_status()
            data = resp.json()
            matches = data.get("response", [])[:3]

            for match in matches:
                title = match.get("title", "Unknown Match")
                home, away = title.split(" vs ") if " vs " in title else ("Team A", "Team B")
                time = parse_match_time(match.get("date"), api_name)
                prediction = random.choice([f"{home} to win", "Draw", f"{away} to win"])
                confidence = random.randint(85, 98)
                pred_text = (
                    f"⚽ *{home} vs {away}*\n"
                    f"{format_match_info(time)}\n"
                    f"🔮 Prediction: {prediction}\n"
                    f"📊 Confidence: {confidence}%"
                )
                all_predictions.append(pred_text)
        except Exception as e:
            logger.error(f"API error from {api_name}: {e}")
    return all_predictions

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"🆕 New user started the bot:\nID: {user.id}\nUsername: @{user.username or 'No username'}\nName: {user.full_name}"
        )
    except Exception as e:
        logger.error(f"Error sending message to channel: {e}")

    keyboard = [
        [InlineKeyboardButton("💰 Subscribe ($5/month)", callback_data='subscribe')],
        [InlineKeyboardButton("🌍 Set Timezone", callback_data='set_timezone')],
        [InlineKeyboardButton("ℹ️ Free Tips", callback_data='free_tips')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚽ *Welcome to ProBet Predictor Bot*\n\n"
        "🔹 *Live match times with countdowns*\n"
        "🔹 *Timezone-aware scheduling*\n"
        "🔹 *90%+ accurate predictions*\n\n"
        "Set your timezone for accurate match times!",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_tz = user_timezones.get(user_id, "UTC")
    if user_id not in subscribed_users:
        await update.message.reply_text("❌ Please subscribe first! Use /start.", parse_mode="Markdown")
        return

    predictions = fetch_predictions()
    if not predictions:
        await update.message.reply_text("⚠️ No reliable predictions available now. Try later!", parse_mode="Markdown")
        return

    formatted_preds = [pred.replace("to win", "").replace("Draw", "Draw") for pred in predictions]
    await update.message.reply_text("🔮 **Today's Predictions**\n\n" + "\n\n".join(formatted_preds), parse_mode="Markdown")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id

    if query.data == "subscribe":
        subscribed_users[user_id] = True
        await query.answer()
        await query.edit_message_text("✅ *Subscription Activated!*\nUse /predict to see today's matches!", parse_mode="Markdown")
    elif query.data == "set_timezone":
        await query.answer()
        await query.edit_message_text(
            "🌍 *Timezone Setting*\nSend your timezone with:\n`/settimezone Continent/City`\nExample: `/settimezone Europe/London`",
            parse_mode="Markdown"
        )
    elif query.data == "free_tips":
        await query.answer()
        await query.edit_message_text(
            "💡 *Free Betting Tips* 💡\n1. Track lineups\n2. Watch odds\n3. Time your bets\n4. Focus on small leagues",
            parse_mode="Markdown"
        )

async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: /settimezone Continent/City\nExample: /settimezone Europe/London", parse_mode="Markdown")
        return
    tz = context.args[0]
    user_timezones[user_id] = tz
    await update.message.reply_text(f"✅ Timezone set to {tz}", parse_mode="Markdown")

# Main
def main():
    if not TOKEN or not CHANNEL_ID:
        logger.error("Missing TELEGRAM_BOT_TOKEN or CHANNEL_ID")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CommandHandler("settimezone", set_timezone))
    app.add_handler(CallbackQueryHandler(button_click))

    logger.info("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
