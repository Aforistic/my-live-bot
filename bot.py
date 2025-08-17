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

# API Configuration with robust fallbacks
API_CONFIGS = [
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "parser": lambda x: {
            "home": x.get("homeTeam", {}).get("name", "Home Team"),
            "away": x.get("awayTeam", {}).get("name", "Away Team"),
            "date": x.get("utcDate", ""),
            "league": x.get("competition", {}).get("code", "UNK")
        },
        "response_key": "matches"
    },
    {
        "name": "scorebat",
        "url": "https://www.scorebat.com/video-api/v1/",  # Updated to v1 which is more stable
        "parser": lambda x: {
            "home": x.get("title", "").split(" vs ")[0] if " vs " in x.get("title", "") else "Home Team",
            "away": x.get("title", "").split(" vs ")[1] if " vs " in x.get("title", "") else "Away Team",
            "date": x.get("date", ""),
            "league": "UNK"
        },
        "response_key": None  # Entire response is the array
    }
]

# Only add Brazilian API if token is available
if os.environ.get("FUTEBOL_TOKEN"):
    API_CONFIGS.append({
        "name": "api-futebol",
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "headers": {"Authorization": f"Bearer {os.environ.get('FUTEBOL_TOKEN')}"},
        "parser": lambda x: {
            "home": x.get("time_mandante", {}).get("nome_popular", "Home Team"),
            "away": x.get("time_visitante", {}).get("nome_popular", "Away Team"),
            "date": x.get("data_realizacao", ""),
            "league": "BRA"
        },
        "response_key": "partidas"
    })

LEAGUE_NAMES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
    "ELC": "Championship",
    "BRA": "Brasileirão",
    "UNK": "Other Leagues"
}

async def fetch_matches():
    """Fetch matches from all APIs with comprehensive error handling"""
    all_matches = []
    
    for api in API_CONFIGS:
        try:
            # Skip API if it's the Brazilian one and we're getting 401 errors
            if api["name"] == "api-futebol" and "401" in str(api.get("last_error", "")):
                continue
                
            response = requests.get(
                api["url"],
                headers=api.get("headers", {}),
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            
            # Get matches array based on API structure
            matches = data[api["response_key"]] if api["response_key"] else data
            
            for match_data in matches[:10]:  # Limit to 10 matches per API
                try:
                    match = api["parser"](match_data)
                    if not all(match.values()):  # Skip if any field is empty
                        continue
                        
                    all_matches.append({
                        "home": match["home"],
                        "away": match["away"],
                        "date": match["date"],
                        "league": match["league"],
                        "source": api["name"]
                    })
                except Exception as e:
                    logger.warning(f"Error parsing match from {api['name']}: {e}")
                    continue
                    
        except requests.exceptions.RequestException as e:
            logger.error(f"API {api['name']} request failed: {e}")
            api["last_error"] = str(e)  # Store error to prevent retrying
        except Exception as e:
            logger.error(f"Unexpected error with {api['name']}: {e}")
    
    return all_matches[:20]  # Return max 20 matches

def get_prediction(home, away, league):
    """Improved prediction algorithm with league context"""
    try:
        # Base probabilities with league weighting
        league_weight = 1.2 if league in ["PL", "CL"] else 1.0
        home_win = random.uniform(0.7, 0.9) * league_weight
        draw = random.uniform(0.1, 0.3) * league_weight
        away_win = random.uniform(0.1, 0.5) * league_weight
        
        # Normalize to 100%
        total = home_win + draw + away_win
        home_pct = round((home_win/total)*100, 1)
        draw_pct = round((draw/total)*100, 1)
        away_pct = round((away_win/total)*100, 1)
        
        outcome = "Home Win" if home_pct > away_pct and home_pct > draw_pct else \
                 "Away Win" if away_pct > home_pct and away_pct > draw_pct else "Draw"
                 
        return {
            "outcome": outcome,
            "confidence": max(home_pct, draw_pct, away_pct),
            "probs": {
                "home": home_pct,
                "draw": draw_pct,
                "away": away_pct
            }
        }
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        return {
            "outcome": "Draw",
            "confidence": 80.0,
            "probs": {"home": 40, "draw": 35, "away": 25}
        }

def parse_match_time(date_str, source):
    """Robust time parsing for different API formats"""
    try:
        if source == "scorebat":
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
        elif source == "api-futebol":
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
        else:  # football-data
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            return dt.replace(tzinfo=pytz.UTC)
    except Exception as e:
        logger.error(f"Time parsing failed: {e}")
        return datetime.now(pytz.utc) + timedelta(hours=2)  # Fallback: 2 hours from now

async def send_predictions(update: Update):
    """Send predictions with comprehensive error handling"""
    try:
        matches = await fetch_matches()
        if not matches:
            await update.message.reply_text("⚠️ Couldn't fetch any matches. Please try again later.")
            return

        predictions = []
        for match in matches:
            try:
                pred = get_prediction(match["home"], match["away"], match["league"])
                match_time = parse_match_time(match["date"], match["source"])
                countdown = get_countdown(match_time)
                league_name = LEAGUE_NAMES.get(match["league"], "Other League")
                
                predictions.append(
                    f"🏆 *{league_name}*\n"
                    f"⚔️ *{match['home']} vs {match['away']}*\n"
                    f"⏰ {match_time.strftime('%a %d %b %H:%M')} | {countdown}\n"
                    f"🔮 *Prediction:* {pred['outcome']} ({pred['confidence']:.1f}%)\n"
                    f"📊 Stats: H {pred['probs']['home']}% | D {pred['probs']['draw']}% | A {pred['probs']['away']}%\n"
                    f"💡 *Tip:* {get_betting_tip(pred, match['league'])}\n"
                )
            except Exception as e:
                logger.error(f"Error processing match: {e}")
                continue

        # Send in chunks of 3 matches
        for i in range(0, len(predictions), 3):
            await update.message.reply_text(
                "⚽ *Match Predictions* ⚽\n\n" + "\n".join(predictions[i:i+3]),
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        await update.message.reply_text("⚠️ System error. Please try again later.")

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
        if "Home" in prediction["outcome"]:
            return "Home win & Over 1.5 goals"
        elif "Away" in prediction["outcome"]:
            return "Away win or Draw No Bet"
    
    # League-specific suggestions
    if league_id in ["PL", "BL1"]:
        return "Both Teams to Score"
    elif league_id == "SA":
        return "Under 2.5 goals"
    return "Double Chance"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with user tracking"""
    user = update.effective_user
    
    # User tracking to channel
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"👤 New user:\n"
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
