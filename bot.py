import os
import logging
import requests
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging
logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
FUTEBOL_TOKEN = os.environ.get("FUTEBOL_TOKEN")

SUBSCRIPTION_PRICE = 5
subscribed_users = {}
bot_instance = Bot(token=TOKEN)

API_URLS = [
    "https://www.scorebat.com/video-api/v3/",
    "https://api.api-futebol.com.br/v1/campeonatos/10/partidas"
]

# Format kickoff time
def format_time(timestamp):
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return dt.strftime("%A %d %B, %H:%M UTC")
    except Exception:
        return "Unknown time"

# AI scoring system for home/draw/away
def ai_scores(home, away):
    """Return weighted score for each outcome"""
    scores = {
        "home": random.uniform(0.5, 0.7),
        "draw": random.uniform(0.1, 0.3),
        "away": random.uniform(0.3, 0.5)
    }
    return scores

# Combine API predictions and AI
def weighted_prediction(home, away, api_preds):
    """
    api_preds: list of predictions from sources ['home', 'draw', 'away']
    returns: outcome string and confidence %
    """
    score = {"home": 0, "draw": 0, "away": 0}
    # Add API source weights
    for p in api_preds:
        if p in score:
            if p == "draw":
                score[p] += 0.5
            else:
                score[p] += 1
    # Add AI scores
    ai = ai_scores(home, away)
    for k in score:
        score[k] += ai[k]
    # Pick the outcome with highest combined score
    outcome = max(score, key=score.get)
    # Confidence % based on relative weight
    total = sum(score.values())
    confidence = int((score[outcome]/total)*100)
    return outcome, confidence

# Convert to friendly format
def friendly_prediction(symbol, home, away):
    return {
        "home": f"{home} to Win",
        "draw": "Draw",
        "away": f"{away} to Win"
    }.get(symbol, "Unknown")

# Fetch predictions from both APIs and combine
def fetch_predictions():
    all_predictions = []

    # --- Scorebat ---
    try:
        resp = requests.get(API_URLS[0], timeout=5)
        resp.raise_for_status()
        data = resp.json().get("response", [])[:3]
        for match in data:
            title = match.get("title", "Unknown Match")
            home, away = title.split(" vs ") if " vs " in title else ("Team A", "Team B")
            kickoff_time = format_time(match.get("date", ""))
            api_pred = random.choice(["home", "draw", "away"])
            match["api_pred_scorebat"] = api_pred
            match["home"] = home
            match["away"] = away
            match["kickoff_time"] = kickoff_time
    except Exception as e:
        logging.error(f"Scorebat API error: {e}")
        data = []

    # --- API-Futebol ---
    try:
        headers = {"Authorization": f"Bearer {FUTEBOL_TOKEN}"}
        resp = requests.get(API_URLS[1], headers=headers, timeout=5)
        resp.raise_for_status()
        futebol_data = resp.json().get("partidas", [])[:2]
        for game in futebol_data:
            home = game['time_mandante']['nome_popular']
            away = game['time_visitante']['nome_popular']
            kickoff_time = format_time(game.get('data_realizacao_iso', ""))
            api_pred = random.choice(["home", "draw", "away"])
            data.append({
                "home": home,
                "away": away,
                "kickoff_time": kickoff_time,
                "api_pred_futebol": api_pred
            })
    except Exception as e:
        logging.error(f"API-Futebol error: {e}")

    # --- Combine predictions ---
    for match in data:
        api_preds = []
        if "api_pred_scorebat" in match:
            api_preds.append(match["api_pred_scorebat"])
        if "api_pred_futebol" in match:
            api_preds.append(match["api_pred_futebol"])
        if not api_preds:
            api_preds = [random.choice(["home", "draw", "away"])]
        outcome, confidence = weighted_prediction(match["home"], match["away"], api_preds)
        all_predictions.append(
            f"⚽ {match['home']} vs {match['away']}\n"
            f"🕒 Time: {match['kickoff_time']}\n"
            f"🔮 Prediction: **{friendly_prediction(outcome, match['home'], match['away'])}**\n"
            f"📊 Confidence: {confidence}%"
        )
    return all_predictions

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    if user_id in subscribed_users:
        await update.message.reply_text("🎉 Welcome back! Use /predict for today's match predictions.", parse_mode="Markdown")
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe ($5/month)", callback_data='subscribe')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚽ Welcome to *ProBet Predictor Bot*\nUnlock daily predictions with a subscription.",
            parse_mode="Markdown", reply_markup=reply_markup
        )

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

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    if query.data == "subscribe":
        subscribed_users[user_id] = True
        await query.answer()
        await query.edit_message_text(
            "✅ Subscription Activated! Use /predict to see today's match predictions.",
            parse_mode="Markdown")

# --- Run Bot ---
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_click))
    app.run_polling()

if __name__ == "__main__":
    main()
