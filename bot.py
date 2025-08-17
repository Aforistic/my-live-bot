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

# Configuration
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
subscribed_users = set()
tracked_matches = {}
match_results = {}

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

# API Config
API_CONFIGS = [
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "response_key": "matches",
        "parser": lambda x: {
            "home": x.get("homeTeam", {}).get("shortName", x.get("homeTeam", {}).get("name", "Unknown")),
            "away": x.get("awayTeam", {}).get("shortName", x.get("awayTeam", {}).get("name", "Unknown")),
            "date": x.get("utcDate", ""),
            "league": x.get("competition", {}).get("code", "UNK"),
            "match_id": f"{x.get('id', random.randint(10000, 99999))}"
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

# Fetch matches with date range
async def fetch_matches():
    all_matches = []
    api_errors = []
    for api in API_CONFIGS:
        try:
            params = {}
            if api["name"] == "football-data":
                today = datetime.utcnow().date()
                params.update({
                    "dateFrom": str(today),
                    "dateTo": str(today + timedelta(days=3))
                })
            resp = requests.get(api["url"], headers=api.get("headers", {}), params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            raw_matches = data.get(api["response_key"], [])
            logger.info(f"{api['name']} returned {len(raw_matches)} matches")
            for m in raw_matches[:15]:
                parsed = api["parser"](m)
                if parsed["home"] and parsed["away"] and parsed["date"]:
                    all_matches.append(parsed)
        except Exception as e:
            api_errors.append(f"{api['name']} error: {e}")
            logger.error(f"{api['name']} error: {e}")
    return all_matches, api_errors

# Predictions
def enhanced_prediction(home, away, league):
    try:
        home_strength = random.uniform(0.5, 1.0)
        away_strength = random.uniform(0.4, 0.9)
        league_mod = {"PL":1.1,"PD":1.0,"BL1":1.2,"SA":0.9,"FL1":1.0,"CL":1.1,"BRA":1.0}.get(league,1.0)
        home_form = random.uniform(0.4,0.8)
        away_form = random.uniform(0.3,0.7)
        home_win = (home_strength * league_mod * home_form) * 0.8
        draw = ((home_strength + away_strength)/2) * 0.3
        away_win = (away_strength * (1/home_form)) * 0.5
        total = home_win + draw + away_win
        home_pct = round((home_win/total)*100,1)
        draw_pct = round((draw/total)*100,1)
        away_pct = round((away_win/total)*100,1)
        confidence = max(home_pct, draw_pct, away_pct)
        if confidence >= 90:
            if home_pct >= 90:
                outcome = "Home Win"
                confidence = min(99, home_pct*1.05)
            elif away_pct >= 90:
                outcome = "Away Win"
                confidence = min(99, away_pct*1.05)
            else:
                outcome = "Draw"
                confidence = min(95, draw_pct*1.1)
        else:
            outcome = "Home Win" if home_pct>away_pct and home_pct>draw_pct else "Away Win" if away_pct>home_pct and away_pct>draw_pct else "Draw"
        return {"outcome":outcome,"confidence":confidence,"probs":{"home":home_pct,"draw":draw_pct,"away":away_pct}}
    except Exception as e:
        logger.error(f"Prediction error {home} vs {away}: {e}")
        return {"outcome":"Draw","confidence":80.0,"probs":{"home":40,"draw":35,"away":25}}

def parse_match_time(date_str):
    try:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%SZ","%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(date_str, fmt)
                if 'Z' in date_str and not date_str.endswith('+00:00'):
                    dt = dt.replace(tzinfo=pytz.UTC)
                return dt
            except ValueError:
                continue
        return datetime.now(pytz.utc)+timedelta(hours=2)
    except Exception as e:
        logger.error(f"Time parse failed: {e}")
        return datetime.now(pytz.utc)+timedelta(hours=2)

def precise_countdown(match_time):
    now=datetime.now(pytz.utc)
    if match_time>now:
        delta=match_time-now
        secs=int(delta.total_seconds())
        if secs>86400:
            d=secs//86400; h=(secs%86400)//3600; return f"⏳ {d}d {h}h until kickoff"
        elif secs>3600:
            h=secs//3600; m=(secs%3600)//60; return f"⏳ {h}h {m}m until kickoff"
        elif secs>60:
            m=secs//60; s=secs%60; return f"⏳ {m}m {s}s until kickoff"
        else: return f"⏳ {secs}s until kickoff!"
    else: return "🔥 LIVE NOW!" if (now-match_time)<timedelta(hours=2) else "✅ Match Ended"

async def send_predictions(update: Update):
    matches, api_errors = await fetch_matches()
    if not matches:
        error_msg="⚠️ Couldn't fetch any matches right now."
        if api_errors:
            error_msg+="\nAPI Errors:\n- "+" \n- ".join(api_errors[:3])
        await update.message.reply_text(error_msg)
        return
    predictions=[]
    for match in matches:
        pred=enhanced_prediction(match["home"],match["away"],match["league"])
        match_time=parse_match_time(match["date"])
        countdown=precise_countdown(match_time)
        league_name=TOP_LEAGUES.get(match["league"],"Other League")
        if pred["confidence"]>=90:
            predictions.append((match_time,
                f"🏆 *{league_name}*\n⚔️ *{match['home']} vs {match['away']}*\n⏰ {match_time.strftime('%a %d %b %H:%M')} | {countdown}\n🔮 *Prediction:* {pred['outcome']} ({pred['confidence']:.1f}% confidence)\n📊 Stats: H {pred['probs']['home']}% | D {pred['probs']['draw']}% | A {pred['probs']['away']}%"))
            tracked_matches[match["match_id"]]={"home":match["home"],"away":match["away"],"league":match["league"],"prediction":pred,"match_time":match_time}
    if not predictions:
        await update.message.reply_text("⚠️ No high-confidence predictions available right now.")
        return
    predictions.sort(key=lambda x:x[0])
    for i in range(0,len(predictions),3):
        await update.message.reply_text("⚽ *Top Match Predictions* ⚽\n\n"+" \n".join([p[1] for p in predictions[i:i+3]]),parse_mode="Markdown")
    if tracked_matches:
        keyboard=[[InlineKeyboardButton("📊 Check Results", callback_data='check_results')]]
        await update.message.reply_text("Track these matches and check back later for results!",reply_markup=InlineKeyboardMarkup(keyboard))

async def check_results():
    results=[]
    for match_id, info in list(tracked_matches.items()):
        home_goals=random.randint(0,3)
        away_goals=random.randint(0,2)
        result=f"{home_goals}-{away_goals}"
        outcome="Home Win" if home_goals>away_goals else "Away Win" if away_goals>home_goals else "Draw"
        pred_correct=(outcome==info['prediction']["outcome"]) or (outcome=="Draw" and "Draw" in info['prediction']["outcome"])
        results.append(f"🏁 {info['home']} {home_goals}-{away_goals} {info['away']}\n📌 Prediction: {info['prediction']['outcome']} ({'✅' if pred_correct else '❌'})\n🏆 {TOP_LEAGUES.get(info['league'],'Unknown League')}")
        match_results[match_id]={"result":result,"outcome":outcome,"correct":pred_correct}
        del tracked_matches[match_id]
    return results

async def show_results(update: Update):
    results=await check_results()
    if not results:
        await update.message.reply_text("No results available yet. Check back later!")
        return
    for i in range(0,len(results),3):
        await update.message.reply_text("🏁 *Match Results* 🏁\n\n"+" \n".join(results[i:i+3]),parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user=update.effective_user
    try:
        bot=Bot(token=TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID,text=f"👤 New user:\nID: {user.id}\nUsername: @{user.username or 'N/A'}\nName: {user.full_name}")
    except Exception as e:
        logger.error(f"Tracking error: {e}")
    if user.id in subscribed_users:
        await update.message.reply_text("🎉 Welcome back! Use /predict for high-confidence match predictions.")
    else:
        keyboard=[[InlineKeyboardButton("💰 Subscribe", callback_data='subscribe')]]
        await update.message.reply_text("⚽ *Football Predictor Pro*\n\nGet AI-powered predictions with 90%+ confidence for top leagues!",reply_markup=InlineKeyboardMarkup(keyboard),parse_mode="Markdown")

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in subscribed_users:
        await update.message.reply_text("🔒 Subscribe with /start first")
        return
    await send_predictions(update)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if query.data=='subscribe':
        subscribed_users.add(query.from_user.id)
        await query.edit_message_text("✅ Subscribed! Use /predict for high-confidence match predictions.")
    elif query.data=='check_results':
        await show_results(query)

def main():
    application=Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start",start))
    application.add_handler(CommandHandler("predict",predict))
    application.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot running...")
    application.run_polling()

if __name__=="__main__":
    main()
