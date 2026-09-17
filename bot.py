import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from datetime import datetime, timezone, timedelta
import pytz

TELEGRAM_TOKEN = "8993132236:AAGBisNWRqoesoNJzGRgjGRJY2le-h6ovVc"
ODDSBLAZE_KEY = "1266751b-3116-41ac-bb96-89a93579b2c1"

# 1. Ψεύτικος Web Server για να μην διαμαρτύρεται το Render
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# 2. Η λογική για το OddsBlaze
def fetch_and_filter_matches():
    value_picks = []
    greece_tz = pytz.timezone('Europe/Athens')
    now = datetime.now(greece_tz)
    
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_window = (start_of_today + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)

    url = "https://api.oddsblaze.com/v1/odds"
    params = {
        "key": ODDSBLAZE_KEY,
        "sport": "soccer"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if not response.ok:
            return []
            
        data = response.json()
        matches = data if isinstance(data, list) else data.get('games', data.get('matches', data.get('events', [])))
        
        for match in matches:
            time_str = match.get('commence_time', match.get('date', match.get('time', '')))
            if not time_str:
                continue
                
            try:
                if 'T' in str(time_str):
                    match_time_utc = datetime.strptime(str(time_str).split('.')[0].replace('Z', ''), '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                else:
                    match_time_utc = datetime.strptime(str(time_str), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            except Exception:
                continue
                    
            match_time_gr = match_time_utc.astimezone(greece_tz)
            
            if not (start_of_today <= match_time_gr <= end_of_window):
                continue
                
            home_team = match.get('home_team', match.get('home', ''))
            away_team = match.get('away_team', match.get('away', ''))
            league_name = match.get('league', match.get('competition', 'Football'))
            
            odds_1 = odds_2 = over_25 = None
            
            bookmakers = match.get('bookmakers', match.get('odds', []))
            for bm in bookmakers:
                markets = bm.get('markets', bm.get('bets', []))
                for market in markets:
                    m_key = str(market.get('key', market.get('name', ''))).lower()
                    
                    if 'h2h' in m_key or 'moneyline' in m_key or '1x2' in m_key:
                        for outcome in market.get('outcomes', []):
                            name = outcome.get('name', '')
                            price = outcome.get('price', outcome.get('odds', 0))
                            if name == home_team: odds_1 = float(price)
                            elif name == away_team: odds_2 = float(price)
                            
                    elif 'total' in m_key or 'goals' in m_key:
                        for outcome in market.get('outcomes', []):
                            name = outcome.get('name', '')
                            point = outcome.get('point', outcome.get('line', 2.5))
                            price = outcome.get('price', outcome.get('odds', 0))
                            if 'over' in name.lower() and float(point) == 2.5:
                                over_25 = float(price)
                                
                if odds_1 and odds_2 and over_25:
                    break
            
            if odds_1 and odds_2 and over_25:
                if (odds_1 <= 1.60 or odds_2 <= 1.60) and over_25 <= 2.00:
                    pick_type = "1" if odds_1 <= 1.60 else "2"
                    pick_odd = odds_1 if odds_1 <= 1.60 else odds_2
                    
                    value_picks.append({
                        "time": match_time_gr.strftime('%H:%M'),
                        "league": str(league_name).title(),
                        "match": f"{home_team} - {away_team}",
                        "pick": pick_type,
                        "odd": pick_odd,
                        "over": over_25
                    })
    except Exception:
        pass
        
    return value_picks

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    requests.post(url, json=payload)

# 3. Το Telegram Bot Polling
def run_bot():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {"offset": offset, "timeout": 30}
            response = requests.get(url, params=params, timeout=35)
            
            if response.ok:
                data = response.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "").strip()
                    
                    if text.lower() in ["/picks", "/check", "ελεγχος", "picks"]:
                        send_message(chat_id, "⏳ <b>Εκτελείται σάρωση αγορών με OddsBlaze...</b>")
                        picks = fetch_and_filter_matches()
                        
                        if not picks:
                            reply = "📅 Δεν βρέθηκε κανένα σημερινό ματς που να πληροί τα κριτήρια (Σημείο ≤ 1.60 και Over ≤ 2.00)."
                        else:
                            picks = sorted(picks, key=lambda x: x['time'])
                            reply = f"📅 <b>Βρέθηκαν Value Picks ({len(picks)})</b>\n\n"
                            for idx, p in enumerate(picks, 1):
                                reply += f"{idx}. ⏰ {p['time']} | 🏆 {p['league']}\n⚽ <b>{p['match']}</b>\n🔥 Σημείο {p['pick']}: <b>{p['odd']}</b> | Over 2.5: <b>{p['over']}</b>\n\n"
                        
                        send_message(chat_id, reply)
                    elif text.lower() in ["/start", "help"]:
                        send_message(chat_id, "Στείλε <b>/picks</b> για άμεσο έλεγχο αποδόσεων.")
        except Exception:
            import time
            time.sleep(5)

if __name__ == "__main__":
    # Ξεκινάει τον web server στο background για το Render
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()
    
    # Ξεκινάει το Telegram Bot
    run_bot()
