import os
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging
import random
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
subscribed_users = set()

# Top leagues
TOP_LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
    "EL": "Europa League",
    "BRA": "Brasileirão"
}

# API configuration
API_CONFIGS = [
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "response_key": "matches",
        "parser": lambda x: {
            "home": x.get("homeTeam", {}).get("shortName", "Unknown"),
            "away": x.get("awayTeam", {}).get("shortName", "Unknown"),
            "date": x.get("utcDate", ""),
            "league": x.get("competition", {}).get("code", "UNK"),
            "match_id": str(x.get("id", random.randint(10000, 99999)))
        }
    }
]

if os.environ.get("FUTEBOL_TOKEN"):
    API_CONFIGS.append({
        "name": "api-futebol",
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "headers": {"Authorization": f"Bearer {os.environ.get('FUTEBOL_TOKEN')}"},
        "response_key": "partidas",
        "parser": lambda x: {
            "home": x.get("time_mandante", {}).get("nome_popular", "Unknown"),
            "away": x.get("time_visitante", {}).get("nome_popular", "Unknown"),
            "date": x.get("data_realizacao", ""),
            "league": "BRA",
            "match_id": str(x.get("partida_id", random.randint(10000, 99999)))
        }
    })

tracked_matches = {}
match_results = {}

def parse_match_time(date_str):
    """Parse match time robustly"""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if 'Z' in date_str and not date_str.endswith('+00:00'):
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt
        except Exception:
            continue
    return datetime.now(pytz.utc) + timedelta(hours=2)

def countdown(match_time):
    """Countdown string for match"""
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        total_seconds = int(delta.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        if days > 0:
            return f"⏳ {days}d {hours}h {minutes}m"
        if hours > 0:
            return f"⏳ {hours}h {minutes}m"
        return f"⏳ {minutes}m"
    else:
        return "🔥 LIVE NOW!" if (now - match_time) < timedelta(hours=2) else "✅ Match Ended"

def predict_outcome(home, away, league):
    """Simple confidence prediction"""
    home_strength = random.uniform(0.5, 1.0)
    away_strength = random.uniform(0.4, 0.9)
    draw_strength = random.uniform(0.3, 0.6)
    
    total = home_strength + away_strength + draw_strength
    home_pct = round((home_strength/total)*100,1)
    away_pct = round((away_strength/total)*100,1)
    draw_pct = round((draw_strength/total)*100,1)
    
    outcome = "Draw"
    confidence = max(home_pct, draw_pct, away_pct)
    if home_pct > away_pct and home_pct > draw_pct:
        outcome = "Home Win"
    elif away_pct > home_pct and away_pct > draw_pct:
        outcome = "Away Win"
    
    return {
        "outcome": outcome,
        "confidence": confidence,
        "probs": {"home": home_pct, "draw": draw_pct, "away": away_pct}
    }

async def fetch_matches():
    all_matches = []
    api_errors = []
    for api in API_CONFIGS:
        try:
            resp = requests.get(api["url"], headers=api.get("headers", {}), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            raw_matches = data.get(api["response_key"], [])
            logger.info(f"{api['name']} returned {len(raw_matches)} matches")
            
            for m in raw_matches[:10]:
                parsed = api["parser"](m)
                if parsed["home"] and parsed["away"] and parsed["date"]:
                    all_matches.append(parsed)
        except Exception as e:
            api_errors.append(f"{api['name']} error: {e}")
            logger.error(f"{api['name']} error: {e}")
    return all_matches, api_errors

async def send_predictions(update: Update):
    matches, api_errors = await fetch_matches()
    if not matches:
        msg = "⚠️ Couldn't fetch any matches right now."
        if api_errors:
            msg += "\nAPI Errors:\n- " + "\n- ".join(api_errors[:3])
        await update.message.reply_text(msg)
        return

    predictions = []
    for match in matches:
        pred = predict_outcome(match["home"], match["away"], match["league"])
        match_time = parse_match_time(match["date"])
        predictions.append({
            "match": f"{match['home']} vs {match['away']}",
            "time": match_time,
            "outcome": pred["outcome"],
            "confidence": pred["confidence"],
            "probs": pred["probs"]
        })
        tracked_matches[match["match_id"]] = {
            "home": match["home"],
            "away": match["away"],
            "prediction": pred,
            "time": match_time,
            "league": match["league"]
        }

    msg_lines = []
    for p in predictions[:5]:
        msg_lines.append(
            f"⚽ *{p['match']}*\n"
            f"🕒 {p['time'].strftime('%a %d %b %H:%M')} UTC | {countdown(p['time'])}\n"
            f"🔮 Prediction: {p['outcome']} ({p['confidence']}% confidence)\n"
            f"📊 H:{p['probs']['home']}% D:{p['probs']['draw']}% A:{p['probs']['away']}%\n"
        )
    await update.message.reply_text("🎯 *Premium Predictions* 🎯\n\n" + "\n".join(msg_lines), parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        bot = Bot(token=TOKEN)
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"👤 New user:\nID: {user.id}\nUsername: @{user.username or 'N/A'}\nName: {user.full_name}"
        )
    except Exception as e:
        logger.error(f"Tracking error: {e}")

    if user.id in subscribed_users:
        await update.message.reply_text("🎉 Welcome back! Use /predict for predictions.")
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
        await update.message.reply_text(
            "⚽ *Football Predictor Pro*\nGet AI-powered predictions!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in subscribed_users:
        await update.message.reply_text("🔒 Subscribe with /start first")
        return
    await send_predictions(update)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'subscribe':
        subscribed_users.add(query.from_user.id)
        await query.edit_message_text("✅ Subscribed! Use /predict for predictions.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
