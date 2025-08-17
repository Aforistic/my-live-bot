import os
import requests
import numpy as np
from datetime import datetime, timedelta
import pytz
from sklearn.ensemble import VotingClassifier
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging
import joblib
from collections import defaultdict

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
subscribed_users = set()

# All Data Sources
API_URLS = [
    {
        "name": "scorebat",
        "url": "https://www.scorebat.com/video-api/v3/",
        "parser": lambda x: (x["title"].split(" vs ")[0], x["title"].split(" vs ")[1], x["date"])
    },
    {
        "name": "futebol",
        "url": "https://api.api-futebol.com.br/v1/campeonatos/10/partidas",
        "headers": {"Authorization": f"Bearer {os.environ.get('FUTEBOL_TOKEN')}"},
        "parser": lambda x: (x["time_mandante"]["nome_popular"], x["time_visitante"]["nome_popular"], x["data_realizacao"])
    },
    {
        "name": "football-data",
        "url": "https://api.football-data.org/v4/matches",
        "headers": {"X-Auth-Token": os.environ.get("FOOTBALL_DATA_KEY")},
        "parser": lambda x: (x["homeTeam"]["name"], x["awayTeam"]["name"], x["utcDate"])
    },
    {
        "name": "odds-api",
        "url": "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        "params": {"apiKey": os.environ.get("ODDS_API_KEY"), "regions": "eu"}
    }
]

# AI Ensemble Model
class PredictionEnsemble:
    def __init__(self):
        self.models = {
            "random_forest": joblib.load("rf_model.joblib"),
            "logistic_reg": joblib.load("lr_model.joblib")
        }
        self.ensemble = VotingClassifier([
            ('rf', self.models["random_forest"]),
            ('lr', self.models["logistic_reg"])
        ], voting='soft')

    def predict(self, features):
        # Get predictions from all models
        predictions = {}
        for name, model in self.models.items():
            pred = model.predict_proba(features)[0]
            predictions[name] = {
                "outcome": ["Home Win", "Draw", "Away Win"][pred.argmax()],
                "confidence": pred.max()
            }
        
        # Ensemble prediction
        ensemble_pred = self.ensemble.predict_proba(features)[0]
        predictions["ensemble"] = {
            "outcome": ["Home Win", "Draw", "Away Win"][ensemble_pred.argmax()],
            "confidence": ensemble_pred.max(),
            "probs": {
                "home": ensemble_pred[0],
                "draw": ensemble_pred[1],
                "away": ensemble_pred[2]
            }
        }
        return predictions

# Data Aggregator
class DataAggregator:
    @staticmethod
    def fetch_all():
        matches = defaultdict(dict)
        
        # Fetch from all APIs
        for api in API_URLS:
            try:
                response = requests.get(
                    api["url"],
                    headers=api.get("headers", {}),
                    params=api.get("params", {})
                ).json()
                
                if api["name"] == "odds-api":
                    for odd in response:
                        key = f"{odd['home_team']}_{odd['away_team']}"
                        matches[key]["odds"] = odd["bookmakers"][0]["markets"][0]["outcomes"]
                else:
                    for item in response[:10]:  # Limit to 10 matches per API
                        home, away, date = api["parser"](item)
                        key = f"{home}_{away}"
                        matches[key].update({
                            "home": home,
                            "away": away,
                            "date": date,
                            "source": api["name"]
                        })
            except Exception as e:
                logger.error(f"API {api['name']} error: {e}")
        
        return list(matches.values())

# Prediction Engine
def generate_prediction(match_data):
    ensemble = PredictionEnsemble()
    
    # Prepare features from multiple sources
    features = np.array([
        match_data.get("home_rank", 10),
        match_data.get("away_rank", 10),
        match_data.get("home_form", 1.5),
        match_data.get("away_form", 1.5),
        len(match_data.get("home_missing", "").split(",")),
        len(match_data.get("away_missing", "").split(",")),
        match_data.get("home_goals_avg", 1.2),
        match_data.get("away_goals_avg", 1.2),
        1 if "important" in match_data.get("home_missing", "") else 0,
        1 if "important" in match_data.get("away_missing", "") else 0
    ]).reshape(1, -1)
    
    return ensemble.predict(features)

# Telegram Bot
async def send_predictions(update: Update):
    try:
        aggregator = DataAggregator()
        matches = aggregator.fetch_all()
        predictions = []
        
        for match in matches[:15]:  # Show top 15 matches
            if not all(k in match for k in ["home", "away", "date"]):
                continue
                
            # Get AI predictions
            preds = generate_prediction(match)
            main_pred = preds["ensemble"]
            
            # Format output
            predictions.append(
                f"⚽ *{match['home']} vs {match['away']}*\n"
                f"📅 {datetime.strptime(match['date'], '%Y-%m-%dT%H:%M:%SZ').strftime('%a %d %b %H:%M')}\n"
                f"🔮 *AI Prediction:* {main_pred['outcome']} ({main_pred['confidence']*100:.1f}%)\n"
                f"📊 *Confidence Breakdown:*\n"
                f"- Random Forest: {preds['random_forest']['confidence']*100:.1f}%\n"
                f"- Logistic Reg: {preds['logistic_reg']['confidence']*100:.1f}%\n"
                f"💡 *Recommended Bet:* {get_betting_tip(main_pred)}"
            )
        
        await update.message.reply_text(
            "🤖 *Multi-Source AI Predictions* 🤖\n\n" + 
            "\n\n".join(predictions),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        await update.message.reply_text("⚠️ System optimizing predictions. Try again in 5 mins.")

def get_betting_tip(prediction):
    if prediction["confidence"] > 0.9:
        if prediction["outcome"] == "Home Win":
            return "Home win & Over 1.5 goals"
        elif prediction["outcome"] == "Away Win":
            return "Away win or Draw No Bet"
    return "Double Chance (Home/Draw)" if prediction["probs"]["home"] + prediction["probs"]["draw"] > 0.65 else "Under 2.5 goals"

# Command handlers (same structure as before)
# ... [keep your existing start/predict/button_handler functions] ...

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
