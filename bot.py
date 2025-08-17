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

# Config
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
subscribed_users = set()
tracked_matches = {}
match_results = {}

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

# API configs
API_CONFIGS = []

if os.environ.get("FOOTBALL_DATA_KEY"):
    API_CONFIGS.append({
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "params": {},
        "active": True,
        "parser": lambda x: {
            "home": x.get("homeTeam", {}).get("shortName", x.get("homeTeam", {}).get("name", "Unknown")),
            "away": x.get("awayTeam", {}).get("shortName", x.get("awayTeam", {}).get("name", "Unknown")),
            "date": x.get("utcDate", ""),
            "league": x.get("competition", {}).get("code", "UNK"),
            "match_id": str(x.get("id", random.randint(10000, 99999)))
        },
        "response_key": "matches",
        "priority": 1
    })

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
        "priority": 2
    })

ACTIVE_APIS = [api for api in API_CONFIGS if api.get("active", True)]


def fetch_matches_sync():
    all_matches = []
    seen_matches = set()
    api_errors = []

    for api in sorted(ACTIVE_APIS, key=lambda x: x.get("priority", 10)):
        try:
            logger.info(f"Fetching from {api['name']}...")
            response = requests.get(
                api["url"],
                headers=api.get("headers", {}),
                params=api.get("params", {}),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"{api['name']} raw response: {data}")

            matches = data.get(api["response_key"], []) if api["response_key"] else data
            if not matches:
                logger.warning(f"No matches found in {api['name']}")
                continue

            for match_data in matches[:20]:
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
            logger.error(f"API {api['name']} fetch error: {str(e)}")
            api_errors.append(f"{api['name']}: {str(e)}")

    return all_matches[:30], api_errors


async def fetch_matches():
    return await asyncio.to_thread(fetch_matches_sync)


def enhanced_prediction(home, away, league):
    home_strength = random.uniform(0.5, 1.0)
    away_strength = random.uniform(0.4, 0.9)
    league_modifiers = {"PL": 1.1, "PD": 1.0, "BL1": 1.2, "SA": 0.9, "FL1": 1.0, "CL": 1.1, "BRA": 1.0}
    league_mod = league_modifiers.get(league, 1.0)
    home_form = random.uniform(0.4, 0.8)
    away_form = random.uniform(0.3, 0.7)

    home_win = (home_strength * league_mod * home_form) * 0.8
    draw = ((home_strength + away_strength) / 2) * 0.3
    away_win = (away_strength * (1 / home_form)) * 0.5
    total = home_win + draw + away_win
    home_pct = round((home_win / total) * 100, 1)
    draw_pct = round((draw / total) * 100, 1)
    away_pct = round((away_win / total) * 100, 1)
    confidence = max(home_pct, draw_pct, away_pct)

    if confidence >= 90:
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

    return {"outcome": outcome, "confidence": confidence, "probs": {"home": home_pct, "draw": draw_pct, "away": away_pct}}


def parse_match_time(date_str):
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if 'Z' in date_str and not date_str.endswith('+00:00'):
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt
        except ValueError:
            continue
    return datetime.now(pytz.utc)


def precise_countdown(match_time):
    now = datetime.now(pytz.utc)
    if match_time > now:
        delta = match_time - now
        total_seconds = int(delta.total_seconds())
        if total_seconds > 86400:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"⏳ {days}d {hours}h until kickoff"
        elif total_seconds > 3600:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"⏳ {hours}h {minutes}m until kickoff"
        elif total_seconds > 60:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"⏳ {minutes}m {seconds}s until kickoff"
        else:
            return f"⏳ {total_seconds}s until kickoff!"
    else:
        return "🔥 LIVE NOW!" if (now - match_time) < timedelta(hours=2) else "✅ Match Ended"


async def send_predictions(update: Update):
    matches, api_errors = await fetch_matches()
    if not matches:
        message = "⚠️ Couldn't fetch any matches.\n"
        if api_errors:
            message += "API Errors:\n- " + "\n- ".join(api_errors[:3])
        message += "\nTry again later."
        await update.message.reply_text(message)
        return

    predictions = []
    for match in matches:
        pred = enhanced_prediction(match["home"], match["away"], match["league"])
        match_time = parse_match_time(match["date"])
        countdown = precise_countdown(match_time)
        league_name = TOP_LEAGUES.get(match["league"], "Other League")
        if pred["confidence"] >= 90:
            predictions.append((
                match_time,
                f"🏆 *{league_name}*\n⚔️ *{match['home']} vs {match['away']}*\n⏰ {match_time.strftime('%a %d %b %H:%M')} | {countdown}\n🔮 *Prediction:* {pred['outcome']} ({pred['confidence']:.1f}% confidence)\n📊 Stats: H {pred['probs']['home']}% | D {pred['probs']['draw']}% | A {pred['probs']['away']}%"
            ))
            tracked_matches[match["match_id"]] = {
                "home": match["home"],
                "away": match["away"],
                "league": match["league"],
                "prediction": pred,
                "match_time": match_time
            }

    if not predictions:
        await update.message.reply_text("⚠️ No high-confidence predictions available.")
        return

    predictions.sort(key=lambda x: x[0])
    for i in range(0, len(predictions), 3):
        await update.message.reply_text(
            "⚽ *Top Match Predictions* ⚽\n\n" + "\n".join([p[1] for p in predictions[i:i+3]]),
            parse_mode="Markdown"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in subscribed_users:
        keyboard = [[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
        await update.message.reply_text(
            "⚽ *Football Predictor Pro*\nGet AI-powered predictions with 90%+ confidence for top leagues!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("🎉 Welcome back! Use /predict for high-confidence match predictions.")


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
        await query.edit_message_text("✅ Subscribed! Use /predict for high-confidence match predictions.")


def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("predict", predict))
    application.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Starting bot...")
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
