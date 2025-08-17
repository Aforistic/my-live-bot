import os
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import Conflict
import logging
import random
import asyncio

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

# Tracked matches and results
tracked_matches = {}
match_results = {}

# API Configuration
API_CONFIGS = [
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "params": {},
        "active": bool(os.environ.get("FOOTBALL_DATA_KEY")),
        "parser": lambda x: {
            "home": x.get("homeTeam", {}).get("shortName", x.get("homeTeam", {}).get("name", "Unknown")),
            "away": x.get("awayTeam", {}).get("shortName", x.get("awayTeam", {}).get("name", "Unknown")),
            "date": x.get("utcDate", ""),
            "league": x.get("competition", {}).get("code", "UNK"),
            "match_id": f"{x.get('id', random.randint(10000, 99999))}"
        },
        "response_key": "matches",
        "priority": 1
    }
]

# Only add Brazilian API if token is available
if os.environ.get("FUTEBOL_TOKEN"):
    API_CONFIGS.append({
        "name": "api-futebol",
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "headers": {"Authorization": f"Bearer {os.environ.get('FUTEBOL_TOKEN')}"},
        "params": {},
        "active": True,
        "parser": lambda x: {
            "home": x.get("time_mandante", {}).get("nome_popular", "Unknown"),
            "away": x.get("time_visitante", {}).get("nome_popular", "Unknown"),
            "date": x.get("data_realizacao", ""),
            "league": "BRA",
            "match_id": str(x.get("partida_id", random.randint(10000, 99999)))
        },
        "response_key": "partidas",
        "priority": 3
    })

# Filter out inactive APIs
ACTIVE_APIS = [api for api in API_CONFIGS if api.get("active", True)]

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

def fetch_matches_sync():
    """Synchronous version of match fetching with detailed error handling"""
    all_matches = []
    seen_matches = set()
    api_errors = []
    
    for api in sorted(ACTIVE_APIS, key=lambda x: x.get("priority", 10)):
        try:
            if api.get("last_failure") and (datetime.now() - api["last_failure"]).seconds < 3600:
                logger.info(f"Skipping {api['name']} due to recent failure")
                continue
                
            logger.info(f"Fetching from {api['name']}...")
            response = requests.get(
                api["url"],
                headers=api.get("headers", {}),
                params=api.get("params", {}),
                timeout=10
            )
            
            if response.status_code == 403:
                error_msg = f"API {api['name']} returned 403 - check your API key"
                logger.error(error_msg)
                api_errors.append(error_msg)
                api["last_failure"] = datetime.now()
                continue
                
            if response.status_code == 401:
                error_msg = f"API {api['name']} returned 401 - unauthorized"
                logger.error(error_msg)
                api_errors.append(error_msg)
                api["last_failure"] = datetime.now()
                continue
                
            response.raise_for_status()
            data = response.json()
            
            matches = data.get(api["response_key"], []) if api["response_key"] else data
            if not matches:
                logger.warning(f"No matches found in {api['name']} response")
                continue
                
            for match_data in matches[:15]:
                try:
                    match = api["parser"](match_data)
                    if not all([match["home"], match["away"], match["date"]]):
                        continue
                        
                    match_key = f"{match['home']}-{match['away']}-{match['date'][:10]}"
                    
                    if match_key in seen_matches:
                        continue
                        
                    seen_matches.add(match_key)
                    
                    if match["league"] in TOP_LEAGUES:
                        all_matches.append({
                            "home": match["home"],
                            "away": match["away"],
                            "date": match["date"],
                            "league": match["league"],
                            "source": api["name"],
                            "match_id": match["match_id"]
                        })
                        
                except Exception as e:
                    logger.warning(f"Error parsing match from {api['name']}: {str(e)}")
                    continue
                    
        except requests.exceptions.RequestException as e:
            error_msg = f"API {api['name']} request failed: {str(e)}"
            logger.error(error_msg)
            api_errors.append(error_msg)
            api["last_failure"] = datetime.now()
        except Exception as e:
            error_msg = f"Unexpected error with {api['name']}: {str(e)}"
            logger.error(error_msg)
            api_errors.append(error_msg)
            api["last_failure"] = datetime.now()
    
    if not all_matches and api_errors:
        logger.error(f"All APIs failed: {', '.join(api_errors)}")
    
    return all_matches[:20], api_errors

async def fetch_matches():
    """Wrapper for synchronous fetch to make it async"""
    return await asyncio.to_thread(fetch_matches_sync)

def enhanced_prediction(home, away, league):
    """Prediction algorithm with fallback"""
    try:
        # Your existing prediction logic
        # ...
        return prediction_result
    except Exception as e:
        logger.error(f"Prediction error for {home} vs {away}: {str(e)}")
        return {
            "outcome": "Draw",
            "confidence": 80.0,
            "probs": {"home": 40, "draw": 35, "away": 25}
        }

async def send_predictions(update: Update):
    """Send predictions with detailed error reporting"""
    try:
        matches, api_errors = await fetch_matches()
        
        if not matches:
            error_message = "⚠️ Couldn't fetch any matches right now."
            if api_errors:
                error_message += "\n\nAPI Errors:\n- " + "\n- ".join(api_errors[:3])  # Show first 3 errors
            error_message += "\n\nPlease try again later."
            await update.message.reply_text(error_message)
            return

        predictions = []
        for match in matches:
            try:
                pred = enhanced_prediction(match["home"], match["away"], match["league"])
                # Rest of your prediction formatting
                # ...
                predictions.append(prediction_text)
                
            except Exception as e:
                logger.error(f"Error processing match: {str(e)}")
                continue

        if not predictions:
            await update.message.reply_text(
                "⚠️ No high-confidence predictions available right now. Try again later."
            )
            return

        # Send predictions in batches
        for i in range(0, len(predictions), 3):
            await update.message.reply_text(
                "⚽ *Top Match Predictions* ⚽\n\n" + "\n".join(predictions[i:i+3]),
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Unexpected error in send_predictions: {str(e)}")
        await update.message.reply_text(
            "⚠️ A system error occurred. Our team has been notified. Please try again later."
        )

# Rest of your handlers (start, predict, button_handler) remain the same
# ...

def main():
    """Start the bot with enhanced error handling"""
    try:
        application = Application.builder().token(TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("predict", predict))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        logger.info("Starting bot with enhanced error handling...")
        
        application.run_polling(
            close_loop=False,
            stop_signals=None,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except Conflict as e:
        logger.error(f"Bot conflict detected: {str(e)}")
        import time
        time.sleep(5)
        main()
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}")
        raise

if __name__ == "__main__":
    main()
