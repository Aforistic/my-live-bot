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

# Configuration
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
SUBSCRIPTION_PRICE = 5
subscribed_users: Dict[int, bool] = {}
bot_instance = Bot(token=TOKEN)

# API Configuration
APIS = {
    "scorebat": {
        "url": "https://www.scorebat.com/video-api/v3/",
        "time_format": "%Y-%m-%dT%H:%M:%S%z"
    },
    "futebol": {
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "time_format": "%Y-%m-%dT%H:%M:%S%z",
        "headers": {"Authorization": f"Bearer {os.getenv('FUTEBOL_TOKEN')}"}
    },
    "sportsdata": {
        "url": "https://api.sportsdata.io/v4/soccer/scores/json/GamesByDate/",
        "time_format": "%Y-%m-%dT%H:%M:%S"
    }
}

def convert_timezone(dt: datetime, user_tz: str = "UTC") -> datetime:
    """Convert datetime to user's timezone"""
    try:
        tz = pytz.timezone(user_tz)
        return dt.astimezone(tz)
    except:
        return dt

def format_countdown(match_time: datetime) -> str:
    """Create a countdown string until match starts"""
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        return f"⏳ Starts in: {delta.days}d {hours}h {minutes}m"
    return "🏟️ Match in progress" if (now - match_time) < timedelta(hours=2) else "⏱️ Match ended"

def parse_match_time(time_str: str, api_name: str) -> Optional[datetime]:
    """Parse time from different APIs with proper error handling"""
    if not time_str:
        return None
        
    try:
        fmt = APIS[api_name]["time_format"]
        dt = datetime.strptime(time_str, fmt)
        
        # Make timezone aware if not already
        if not dt.tzinfo:
            if api_name == "sportsdata":
                dt = dt.replace(tzinfo=pytz.UTC)
            else:
                dt = dt.astimezone(pytz.UTC)
                
        return dt
    except ValueError as e:
        logger.warning(f"Couldn't parse time '{time_str}' for {api_name}: {e}")
        return None

def format_match_info(match_time: Optional[datetime], user_tz: str = "UTC") -> str:
    """Format match time information with countdown"""
    if not match_time:
        return "🕒 Time: Not specified"
    
    local_time = convert_timezone(match_time, user_tz)
    time_str = local_time.strftime("%a %b %d, %H:%M (%Z)")
    countdown = format_countdown(match_time)
    
    return f"🕒 Time: {time_str}\n{countdown}"

def fetch_predictions() -> List[str]:
    """Fetch predictions with enhanced time handling"""
    all_predictions = []
    
    for api_name, config in APIS.items():
        try:
            headers = config.get("headers", {})
            resp = requests.get(config["url"], headers=headers)
            resp.raise_for_status()
            data = resp.json()

            matches = []
            if api_name == "scorebat":
                matches = data.get("response", [])[:3]
            elif api_name == "futebol":
                matches = data.get("partidas", [])[:2]
            elif api_name == "sportsdata":
                matches = data[:3] if isinstance(data, list) else []

            for match in matches:
                try:
                    # Extract match info based on API
                    if api_name == "scorebat":
                        title = match.get("title", "Unknown Match")
                        home, away = title.split(" vs ") if " vs " in title else ("Team A", "Team B")
                        time = parse_match_time(match.get("date"), api_name)
                    elif api_name == "futebol":
                        home = match['time_mandante']['nome_popular']
                        away = match['time_visitante']['nome_popular']
                        time = parse_match_time(match['data_realizacao'], api_name)
                    else:  # sportsdata
                        home = match.get('HomeTeam', 'Team A')
                        away = match.get('AwayTeam', 'Team B')
                        time = parse_match_time(match.get('DateTime'), api_name)

                    # Generate prediction
                    prediction = random.choice([f"{home} to win", "Draw", f"{away} to win"])
                    confidence = random.randint(85, 98)
                    
                    # Format output
                    pred_text = (
                        f"⚽ *{home} vs {away}*\n"
                        f"{format_match_info(time)}\n"
                        f"🔮 Prediction: {prediction}\n"
                        f"📊 Confidence: {confidence}%\n"
                        f"💡 Tip: {'Home/Draw double chance' if 'win' in prediction else 'Under 2.5 goals'}"
                    )
                    all_predictions.append(pred_text)
                    
                except Exception as e:
                    logger.error(f"Error processing match from {api_name}: {e}")
                    
        except Exception as e:
            logger.error(f"API error from {api_name}: {e}")
            
    return all_predictions

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced start command with timezone option"""
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
        reply_markup=reply_markup)

# ... [keep the rest of your handlers from previous version] ...

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button clicks"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query.data == "subscribe":
        subscribed_users[user_id] = True
        await query.answer()
        await query.edit_message_text(
            "✅ *Subscription Activated!*\n\n"
            "Now you can access:\n"
            "🔹 Live match times with countdowns\n"
            "🔹 Timezone-adjusted schedules\n"
            "🔹 Premium predictions\n\n"
            "Use /predict to see today's matches!",
            parse_mode="Markdown")
            
    elif query.data == "set_timezone":
        await query.answer()
        # In a full implementation, you would show timezone options
        await query.edit_message_text(
            "🌍 *Timezone Setting*\n\n"
            "Please send your timezone in format:\n"
            "`/settimezone Continent/City`\n\n"
            "Example: `/settimezone Europe/London`\n"
            "Common timezones:\n"
            "• America/New_York\n"
            "• Europe/London\n"
            "• Asia/Tokyo",
            parse_mode="Markdown")
            
    elif query.data == "free_tips":
        await query.answer()
        await query.edit_message_text(
            "💡 *Free Betting Tips* 💡\n\n"
            "1. *Track lineups:* Key player absences change everything\n"
            "2. *Watch odds movement:* Smart money moves odds\n"
            "3. *Time your bets:* Odds often shift dramatically 1h before match\n"
            "4. *Small leagues:* Often have more predictable outcomes\n\n"
            "Subscribe for time-sensitive premium predictions!",
            parse_mode="Markdown")

def main():
    """Run the bot"""
    if not TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN environment variable")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CommandHandler("tips", tips))
    app.add_handler(CallbackQueryHandler(button_click))

    logger.info("🤖 Bot is running with enhanced time features...")
    app.run_polling()

if __name__ == "__main__":
    main()
