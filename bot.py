import os
import random
import logging
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from pytz import timezone, utc

# Logging
logging.basicConfig(level=logging.INFO)

# Environment variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
FUTEBOL_TOKEN = os.environ.get("FUTEBOL_TOKEN")  # For API-Futebol

FREE_API_URLS = [
    "https://www.scorebat.com/video-api/v3/",
    "https://api.api-futebol.com.br/v1/campeonatos/10/partidas"
]

SUBSCRIPTION_PRICE = 5
subscribed_users = {}
message_tracker = {}  # To store message_id, chat_id, and match title
bot_instance = Bot(token=TOKEN)

# --- Utilities ---
def friendly_prediction(symbol, home, away):
    return {
        "1": f"{home} to Win",
        "X": "Draw",
        "2": f"{away} to Win"
    }.get(symbol, "Unknown")

def format_time(timestamp, user_tz_str="UTC"):
    try:
        dt_utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        user_tz = timezone(user_tz_str)
        local_dt = dt_utc.astimezone(user_tz)
        now = datetime.now(user_tz)
        delta = local_dt - now
        time_remaining = f"Starts in {delta.seconds // 60} min" if delta.total_seconds() > 0 else "Already Started"
        return local_dt.strftime("%A %d %B, %H:%M") + f" ({time_remaining})"
    except Exception:
        return "Unknown time"

def ai_prediction(home, away):
    # Simulate aggregated AI model from multiple sources
    base_probs = {
        "home": random.uniform(60, 95),
        "draw": random.uniform(2, 20),
        "away": random.uniform(2, 20)
    }
    outcome = max(base_probs, key=base_probs.get)
    confidence = base_probs[outcome]
    tips = "Over 2.5 Goals" if confidence > 85 else "Both Teams to Score" if base_probs['draw'] > 10 else "1X Double Chance"
    return {
        "outcome": f"{home if outcome=='home' else away if outcome=='away' else 'Draw'}",
        "confidence": round(confidence, 1),
        "probs": {k: round(v, 1) for k, v in base_probs.items()},
        "tips": tips
    }

def fetch_predictions(user_tz="UTC"):
    all_predictions = []

    # Scorebat
    try:
        resp = requests.get(FREE_API_URLS[0], timeout=5)
        resp.raise_for_status()
        data = resp.json().get("response", [])[:5]
        for match in data:
            title = match.get("title", "Unknown Match")
            home, away = title.split(" vs ") if " vs " in title else ("Team A", "Team B")
            kickoff_time = format_time(match.get("date", ""), user_tz)
            pred = ai_prediction(home, away)
            all_predictions.append({
                "title": title,
                "home": home,
                "away": away,
                "time": kickoff_time,
                "prediction": pred
            })
    except Exception as e:
        logging.error(f"Scorebat API error: {e}")

    # API-Futebol
    try:
        headers = {"Authorization": f"Bearer {FUTEBOL_TOKEN}"}
        resp = requests.get(FREE_API_URLS[1], headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json().get("partidas", [])[:5]
        for game in data:
            home = game['time_mandante']['nome_popular']
            away = game['time_visitante']['nome_popular']
            kickoff_time = format_time(game.get('data_realizacao_iso', ""), user_tz)
            pred = ai_prediction(home, away)
            all_predictions.append({
                "title": f"{home} vs {away}",
                "home": home,
                "away": away,
                "time": kickoff_time,
                "prediction": pred
            })
    except Exception as e:
        logging.error(f"API-Futebol error: {e}")

    return all_predictions

# --- Telegram Commands ---
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
        await update.message.reply_text("🎉 Welcome back! Use /predict for today's match predictions.", parse_mode="Markdown")
    else:
        keyboard = [[InlineKeyboardButton(f"💰 Subscribe (${SUBSCRIPTION_PRICE}/month)", callback_data='subscribe')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚽ Welcome to *AI Prediction Bot*\n\nUnlock daily AI-powered predictions.",
            parse_mode="Markdown", reply_markup=reply_markup
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_tz = "Africa/Lagos"  # In production, ask user for this
    if user_id not in subscribed_users:
        await update.message.reply_text("❌ Please subscribe first! Use /start.", parse_mode="Markdown")
        return

    predictions = fetch_predictions(user_tz)
    if not predictions:
        await update.message.reply_text("⚠️ No predictions available now. Try later!", parse_mode="Markdown")
        return

    for match in predictions:
        keyboard = [[InlineKeyboardButton("📊 View Result", callback_data=f"result|{match['title']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        pred = match["prediction"]
        msg = (
            f"⚽ *{match['title']}*\n"
            f"🕒 Kickoff: {match['time']}\n"
            f"🔮 Prediction: *{pred['outcome']}* ({pred['confidence']}%)\n"
            f"📊 Probabilities: H {pred['probs']['home']}% | D {pred['probs']['draw']}% | A {pred['probs']['away']}%\n"
            f"💡 Tips: {pred['tips']}"
        )
        sent_msg = await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
        message_tracker[match['title']] = {"chat_id": update.effective_chat.id, "message_id": sent_msg.message_id}

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data

    if data == "subscribe":
        subscribed_users[user_id] = True
        await query.answer()
        await query.edit_message_text(
            "✅ Subscription Activated! Use /predict to see today's AI match predictions.",
            parse_mode="Markdown"
        )
    elif data.startswith("result|"):
        match_title = data.split("|")[1]
        result_text = await fetch_live_result(match_title)
        await query.answer()
        await query.edit_message_text(f"📊 Result for *{match_title}*: {result_text}", parse_mode="Markdown")

async def fetch_live_result(match_title):
    return random.choice(["Home Win", "Draw", "Away Win"])

async def update_results_job(context: ContextTypes.DEFAULT_TYPE):
    for title, info in message_tracker.items():
        result_text = await fetch_live_result(title)
        try:
            await bot_instance.edit_message_text(
                chat_id=info['chat_id'],
                message_id=info['message_id'],
                text=f"⚽ *{title}*\n📊 Final Result: {result_text}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Error updating message for {title}: {e}")

def main():
    if not (TOKEN and CHANNEL_ID):
        logging.error("Missing required environment variables.")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_click))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(update_results_job, interval=300, first=10)

    logging.info("🤖 AI Prediction Bot (Advanced) running...")
    app.run_polling()

if __name__ == "__main__":
    main()
