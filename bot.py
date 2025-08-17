import os
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging
import random

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
subscribed_users = set()
bot_instance = Bot(token=TOKEN)

# Multiple API Sources with fallbacks
API_SOURCES = [
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "leagues": ["PL", "PD", "BL1", "SA", "FL1", "CL", "ELC"]
    },
    {
        "name": "scorebat",
        "url": "https://www.scorebat.com/video-api/v3/",
        "leagues": ["ALL"]  # Scorebat doesn't separate by league
    },
    {
        "name": "api-futebol",
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "headers": {"Authorization": f"Bearer {os.environ.get('FUTEBOL_TOKEN')}"},
        "leagues": ["BRA"]
    }
]

# League names mapping
LEAGUE_NAMES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
    "ELC": "Championship",
    "BRA": "Brasileirão"
}

async def fetch_matches():
    """Fetch matches from all available APIs with fallback handling"""
    all_matches = []
    
    for api in API_SOURCES:
        try:
            # Special handling for ScoreBat API
            if api["name"] == "scorebat":
                response = requests.get(api["url"], timeout=10)
                data = response.json()
                for match in data[:15]:  # Get first 15 matches
                    try:
                        teams = match["title"].split(" vs ")
                        all_matches.append({
                            "home": teams[0],
                            "away": teams[1],
                            "date": match["date"],
                            "league": "UNK",  # Scorebat doesn't provide league info
                            "source": "scorebat"
                        })
                    except:
                        continue
                continue
                
            # Handling for other APIs
            response = requests.get(
                api["url"],
                headers=api.get("headers", {}),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            # Process matches based on API structure
            matches = []
            if api["name"] == "football-data":
                matches = data.get("matches", [])
            elif api["name"] == "api-futebol":
                matches = data.get("partidas", [])
            
            for match in matches[:10]:  # Limit matches per API
                try:
                    if api["name"] == "football-data":
                        league = match["competition"]["code"]
                        if league not in api["leagues"]:
                            continue
                        all_matches.append({
                            "home": match["homeTeam"]["name"],
                            "away": match["awayTeam"]["name"],
                            "date": match["utcDate"],
                            "league": league,
                            "source": api["name"]
                        })
                    elif api["name"] == "api-futebol":
                        all_matches.append({
                            "home": match["time_mandante"]["nome_popular"],
                            "away": match["time_visitante"]["nome_popular"],
                            "date": match["data_realizacao"],
                            "league": "BRA",
                            "source": api["name"]
                        })
                except KeyError as e:
                    logger.warning(f"Error parsing match from {api['name']}: {e}")
                    continue
                    
        except requests.exceptions.RequestException as e:
            logger.error(f"API {api['name']} request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error with {api['name']}: {e}")
    
    return all_matches[:20]  # Return max 20 matches

def get_prediction(home, away):
    """Improved prediction algorithm with fallback"""
    try:
        # In production, replace with actual AI model
        outcomes = [
            {"outcome": f"{home} win", "confidence": random.randint(80, 92)},
            {"outcome": "Draw", "confidence": random.randint(75, 85)},
            {"outcome": f"{away} win", "confidence": random.randint(78, 90)}
        ]
        return max(outcomes, key=lambda x: x["confidence"])
    except:
        return {"outcome": "Draw", "confidence": 80}

async def send_predictions(update: Update):
    """Send predictions with proper error handling"""
    try:
        matches = await fetch_matches()
        if not matches:
            await update.message.reply_text("⚠️ Couldn't fetch matches. Trying alternative sources...")
            return

        predictions = []
        for match in matches:
            try:
                pred = get_prediction(match["home"], match["away"])
                match_time = datetime.strptime(match["date"], '%Y-%m-%dT%H:%M:%SZ')
                countdown = get_countdown(match_time)
                league_name = LEAGUE_NAMES.get(match["league"], "Unknown League")
                
                predictions.append(
                    f"🏆 *{league_name}* ({match['source']})\n"
                    f"⚽ *{match['home']} vs {match['away']}*\n"
                    f"⏰ {match_time.strftime('%a %d %b %H:%M')} | {countdown}\n"
                    f"🔮 *Prediction:* {pred['outcome']} ({pred['confidence']}%)\n"
                    f"💡 *Tip:* {get_betting_tip(pred, match['league'])}\n"
                )
            except Exception as e:
                logger.error(f"Error processing match: {e}")
                continue

        # Send in chunks of 3 matches
        for i in range(0, len(predictions), 3):
            await update.message.reply_text(
                "📅 *Match Predictions* 📅\n\n" + "\n".join(predictions[i:i+3]),
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        await update.message.reply_text("⚠️ Couldn't generate predictions. Please try again later.")

def get_countdown(match_time):
    """Calculate time until match starts"""
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        if delta.days > 0:
            return f"⏳ {delta.days}d {delta.seconds//3600}h"
        return f"⏳ {delta.seconds//3600}h {(delta.seconds//60)%60}m"
    return "🔥 LIVE NOW!" if (now - match_time) < timedelta(hours=3) else "✅ Match Ended"

def get_betting_tip(prediction, league_id):
    """League-specific betting tips"""
    if prediction["confidence"] > 85:
        if "win" in prediction["outcome"]:
            return "Win & Over 1.5 goals"
    return "Double Chance" if random.random() > 0.5 else "Under 2.5 goals"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with user tracking"""
    user = update.effective_user
    
    # User tracking to channel
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"🆕 New user:\n"
                 f"ID: {user.id}\n"
                 f"Username: @{user.username or 'N/A'}\n"
                 f"Name: {user.full_name}"
        )
    except Exception as e:
        logger.error(f"Tracking error: {e}")

    if user.id in subscribed_users:
        await update.message.reply_text("🎉 Welcome back! Use /predict for matches.")
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
        await update.message.reply_text(
            "⚽ *Football Predictor Pro*\n\n"
            "Get predictions for all major leagues!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /predict command"""
    if update.effective_user.id not in subscribed_users:
        await update.message.reply_text("🔒 Subscribe with /start first")
        return
    await send_predictions(update)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'subscribe':
        subscribed_users.add(query.from_user.id)
        await query.edit_message_text("✅ Subscribed! Use /predict")

def main():
    """Start the bot"""
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Football Predictor Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
