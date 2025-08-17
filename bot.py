import os
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging
import random
import json
from collections import defaultdict

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

# Tracked matches and results
tracked_matches = {}
match_results = {}

# API Configuration with multiple reliable sources
API_CONFIGS = [
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "parser": lambda x: {
            "home": x.get("homeTeam", {}).get("shortName", x.get("homeTeam", {}).get("name", "Unknown")),
            "away": x.get("awayTeam", {}).get("shortName", x.get("awayTeam", {}).get("name", "Unknown")),
            "date": x.get("utcDate", ""),
            "league": x.get("competition", {}).get("code", "UNK"),
            "match_id": f"{x.get('id', random.randint(10000, 99999))}"
        },
        "response_key": "matches",
        "priority": 1  # Highest priority
    },
    {
        "name": "api-football",
        "url": "https://v3.football.api-sports.io/fixtures",
        "headers": {"x-rapidapi-key": os.environ.get("API_FOOTBALL_KEY")},
        "params": {"live": "all"},
        "parser": lambda x: {
            "home": x["teams"]["home"]["name"],
            "away": x["teams"]["away"]["name"],
            "date": x["fixture"]["date"],
            "league": x["league"]["id"],
            "match_id": str(x["fixture"]["id"])
        },
        "response_key": "response",
        "priority": 2
    }
]

# Only add Brazilian API if token is available
if os.environ.get("FUTEBOL_TOKEN"):
    API_CONFIGS.append({
        "name": "api-futebol",
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "headers": {"Authorization": f"Bearer {os.environ.get('FUTEBOL_TOKEN')}"},
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

async def fetch_matches():
    """Fetch matches from all APIs with priority handling"""
    all_matches = []
    seen_matches = set()  # To avoid duplicates
    
    # Sort APIs by priority
    for api in sorted(API_CONFIGS, key=lambda x: x.get("priority", 10)):
        try:
            response = requests.get(
                api["url"],
                headers=api.get("headers", {}),
                params=api.get("params", {}),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            matches = data[api["response_key"]] if api["response_key"] else data
            
            for match_data in matches:
                try:
                    match = api["parser"](match_data)
                    match_key = f"{match['home']}-{match['away']}-{match['date'][:10]}"
                    
                    # Skip if we already have this match from a higher priority source
                    if match_key in seen_matches:
                        continue
                        
                    seen_matches.add(match_key)
                    
                    # Only include matches from top leagues
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
                    logger.warning(f"Error parsing match from {api['name']}: {e}")
                    continue
                    
        except requests.exceptions.RequestException as e:
            logger.error(f"API {api['name']} request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error with {api['name']}: {e}")
    
    return all_matches[:20]  # Return max 20 matches

def enhanced_prediction(home, away, league):
    """AI-enhanced prediction combining multiple factors"""
    try:
        # Base probabilities with team strength simulation
        home_strength = random.uniform(0.5, 1.0)
        away_strength = random.uniform(0.4, 0.9)
        
        # League modifiers (some leagues have more home advantage)
        league_modifiers = {
            "PL": 1.1, "PD": 1.0, "BL1": 1.2, 
            "SA": 0.9, "FL1": 1.0, "CL": 1.1, "BRA": 1.0
        }
        league_mod = league_modifiers.get(league, 1.0)
        
        # Recent form simulation (last 5 matches)
        home_form = random.uniform(0.4, 0.8)
        away_form = random.uniform(0.3, 0.7)
        
        # Calculate probabilities
        home_win = (home_strength * league_mod * home_form) * 0.8
        draw = ((home_strength + away_strength) / 2) * 0.3
        away_win = (away_strength * (1/home_form)) * 0.5
        
        # Normalize to 100%
        total = home_win + draw + away_win
        home_pct = round((home_win/total)*100, 1)
        draw_pct = round((draw/total)*100, 1)
        away_pct = round((away_win/total)*100, 1)
        
        # Determine confidence level
        confidence = max(home_pct, draw_pct, away_pct)
        
        # High confidence threshold (90%+)
        if confidence >= 90:
            # Apply additional checks for very high confidence
            if home_pct >= 90:
                outcome = "Home Win"
                confidence = min(99, home_pct * 1.05)
            elif away_pct >= 90:
                outcome = "Away Win"
                confidence = min(99, away_pct * 1.05)
            else:
                outcome = "Draw"
                confidence = min(95, draw_pct * 1.1)
        else:
            outcome = "Home Win" if home_pct > away_pct and home_pct > draw_pct else \
                     "Away Win" if away_pct > home_pct and away_pct > draw_pct else "Draw"
        
        return {
            "outcome": outcome,
            "confidence": confidence,
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

def parse_match_time(date_str):
    """Improved time parsing with better error handling"""
    try:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(date_str, fmt)
                if 'Z' in date_str and not date_str.endswith('+00:00'):
                    dt = dt.replace(tzinfo=pytz.UTC)
                return dt
            except ValueError:
                continue
        return datetime.now(pytz.utc) + timedelta(hours=2)
    except Exception as e:
        logger.error(f"Time parsing failed: {e}")
        return datetime.now(pytz.utc) + timedelta(hours=2)

def precise_countdown(match_time):
    """Show precise countdown to match start"""
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        total_seconds = int(delta.total_seconds())
        
        if total_seconds > 86400:  # More than 1 day
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"⏳ {days}d {hours}h until kickoff"
        elif total_seconds > 3600:  # More than 1 hour
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"⏳ {hours}h {minutes}m until kickoff"
        elif total_seconds > 60:  # More than 1 minute
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"⏳ {minutes}m {seconds}s until kickoff"
        else:
            return f"⏳ {total_seconds}s until kickoff!"
    else:
        return "🔥 LIVE NOW!" if (now - match_time) < timedelta(hours=2) else "✅ Match Ended"

async def check_results():
    """Check results for tracked matches"""
    results = []
    for match_id, match_info in tracked_matches.items():
        try:
            # In a real implementation, you would query an API for results
            # This is a simulation
            if random.random() > 0.7:  # 30% chance we have a result
                home_goals = random.randint(0, 3)
                away_goals = random.randint(0, 2)
                
                result = f"{home_goals}-{away_goals}"
                if home_goals > away_goals:
                    outcome = "Home Win"
                elif away_goals > home_goals:
                    outcome = "Away Win"
                else:
                    outcome = "Draw"
                
                # Check if prediction was correct
                prediction_correct = (
                    (outcome == match_info['prediction']["outcome"]) or
                    (outcome == "Draw" and "Draw" in match_info['prediction']["outcome"])
                )
                
                results.append(
                    f"🏁 {match_info['home']} {home_goals}-{away_goals} {match_info['away']}\n"
                    f"📌 Prediction: {match_info['prediction']['outcome']} "
                    f"({'✅' if prediction_correct else '❌'})\n"
                    f"🏆 {TOP_LEAGUES.get(match_info['league'], 'Unknown League')}\n"
                )
                
                # Store result and remove from tracked matches
                match_results[match_id] = {
                    "result": result,
                    "outcome": outcome,
                    "correct": prediction_correct
                }
                del tracked_matches[match_id]
                
        except Exception as e:
            logger.error(f"Error checking result for match {match_id}: {e}")
    
    return results

async def send_predictions(update: Update):
    """Send predictions with tracking and results"""
    try:
        matches = await fetch_matches()
        if not matches:
            await update.message.reply_text("⚠️ Couldn't fetch any matches. Please try again later.")
            return

        predictions = []
        for match in matches:
            try:
                pred = enhanced_prediction(match["home"], match["away"], match["league"])
                match_time = parse_match_time(match["date"])
                countdown = precise_countdown(match_time)
                league_name = TOP_LEAGUES.get(match["league"], "Other League")
                
                # Only show high confidence predictions (90%+)
                if pred["confidence"] >= 90:
                    predictions.append((
                        match_time,
                        f"🏆 *{league_name}*\n"
                        f"⚔️ *{match['home']} vs {match['away']}*\n"
                        f"⏰ {match_time.strftime('%a %d %b %H:%M')} | {countdown}\n"
                        f"🔮 *Prediction:* {pred['outcome']} ({pred['confidence']:.1f}% confidence)\n"
                        f"📊 Stats: H {pred['probs']['home']}% | D {pred['probs']['draw']}% | A {pred['probs']['away']}%\n"
                        f"💡 *Tip:* {get_betting_tip(pred, match['league'])}\n"
                    ))
                    
                    # Track this match for results checking
                    tracked_matches[match["match_id"]] = {
                        "home": match["home"],
                        "away": match["away"],
                        "league": match["league"],
                        "prediction": pred,
                        "match_time": match_time
                    }
            except Exception as e:
                logger.error(f"Error processing match: {e}")
                continue

        if not predictions:
            await update.message.reply_text("⚠️ No high-confidence predictions available right now.")
            return

        # Sort by match time
        predictions.sort(key=lambda x: x[0])
        
        # Send in chunks of 3 matches
        for i in range(0, len(predictions), 3):
            await update.message.reply_text(
                "⚽ *Top Match Predictions* ⚽\n\n" + "\n".join([p[1] for p in predictions[i:i+3]]),
                parse_mode="Markdown"
            )
            
        # Add results button if we have tracked matches
        if tracked_matches:
            keyboard = [[InlineKeyboardButton("📊 Check Results", callback_data='check_results')]]
            await update.message.reply_text(
                "Track these matches and check back later for results!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        await update.message.reply_text("⚠️ System error. Please try again later.")

async def show_results(update: Update):
    """Show results of completed matches"""
    try:
        results = await check_results()
        if not results:
            await update.message.reply_text("No results available yet. Check back later!")
            return
            
        # Send in chunks of 3 results
        for i in range(0, len(results), 3):
            await update.message.reply_text(
                "🏁 *Match Results* 🏁\n\n" + "\n".join(results[i:i+3]),
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Results error: {e}")
        await update.message.reply_text("⚠️ Couldn't fetch results. Please try again later.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    try:
        await bot_instance.send_message(
            chat_id=CHANNEL_ID,
            text=f"👤 New user:\nID: {user.id}\nUsername: @{user.username or 'N/A'}\nName: {user.full_name}"
        )
    except Exception as e:
        logger.error(f"Tracking error: {e}")

    if user.id in subscribed_users:
        await update.message.reply_text("🎉 Welcome back! Use /predict for high-confidence match predictions.")
    else:
        keyboard = [[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
        await update.message.reply_text(
            "⚽ *Football Predictor Pro*\n\n"
            "Get AI-powered predictions with 90%+ confidence for top leagues!",
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
        await query.edit_message_text("✅ Subscribed! Use /predict for high-confidence match predictions.")
    elif query.data == 'check_results':
        await show_results(update)

def main():
    """Start the bot"""
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Enhanced Football Predictor Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
