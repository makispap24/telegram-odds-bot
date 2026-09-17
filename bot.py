import time
import requests
from datetime import datetime, timezone, timedelta
import pytz

TELEGRAM_TOKEN = "8993132236:AAGBisNWRqoesoNJzGRgjGRJY2le-h6ovVc"
ODDSBLAZE_KEY = "1266751b-3116-41ac-bb96-89a93579b2c1"

def fetch_and_filter_matches():
    value_picks = []
    greece_tz = pytz.timezone('Europe/Athens')
    now = datetime.now(greece_tz)
    
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_window = (start_of_today + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)

    LEAGUES = ["soccer", "epl", "champions-league", "europa-league", "la-liga", "serie-a", "bundesliga", "ligue-1", "super-league-greece"]
    BOOKMAKERS = ["draftkings", "fanduel", "betmgm", "pinnacle"]

    for bookmaker in BOOKMAKERS:
        for league in LEAGUES:
            url = f"https://api.oddsblaze.com/v2/odds/{bookmaker}/{league}.json"
            params = {"key": ODDSBLAZE_KEY}
            
            try:
                response = requests.get(url, params=params, timeout=10)
                if not response.ok:
                    continue
                    
                data = response.json()
                events = data.get('events', data.get('games', []))
                
                for match in events:
                    time_str = match.get('date', match.get('commence_time', ''))
                    if not time_str:
                        continue
                        
                    try:
                        match_time_utc = datetime.strptime(time_str.split('.')[0].replace('Z', ''), '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                    except Exception:
                        continue
                        
                    match_time_gr = match_time_utc.astimezone(greece_tz)
                    
                    if not (start_of_today <= match_time_gr <= end_of_window):
                        continue
                        
                    teams = match.get('teams', {})
                    home_team = teams.get('home', {}).get('name', match.get('home', ''))
                    away_team = teams.get('away', {}).get('name', match.get('away', ''))
                    
                    odds_1 = odds_2 = over_25 = None
                    markets = match.get('odds', match.get('markets', []))
                    
                    for market in markets:
                        m_name = str(market.get('name', market.get('key', ''))).lower()
                        if 'moneyline' in m_name or '1x2' in m_name or 'h2h' in m_name:
                            for outcome in market.get('outcomes', []):
                                name = outcome.get('name', '')
                                price = outcome.get('price', outcome.get('odds', 0))
                                if name == home_team: odds_1 = float(price)
                                elif name == away_team: odds_2 = float(price)
                        elif 'total' in m_name or 'goals' in m_name:
                            for outcome in market.get('outcomes', []):
                                name = outcome.get('name', '')
                                point = outcome.get('point', outcome.get('line', 2.5))
                                price = outcome.get('price', outcome.get('odds', 0))
                                if 'over' in name.lower() and float(point) == 2.5:
                                    over_25 = float(price)
                    
                    if odds_1 and odds_2 and over_25:
                        if (odds_1 <= 1.60 or odds_2 <= 1.60) and over_25 <= 2.00:
                            pick_type = "1" if odds_1 <= 1.60 else "2"
                            pick_odd = odds_1 if odds_1 <= 1.60 else odds_2
                            
                            match_key = f"{home_team} - {away_team}"
                            if not any(p['match'] == match_key for p in value_picks):
                                value_picks.append({
                                    "time": match_time_gr.strftime('%H:%M'),
                                    "league": league.replace('-', ' ').title(),
                                    "match": match_key,
                                    "pick": pick_type,
                                    "odd": pick_odd,
                                    "over": over_25
                                })
            except Exception:
                continue
                
    return value_picks

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    requests.post(url, json=payload)

def run_bot():
    print("Το Telegram Bot είναι ενεργό και περιμένει εντολές...")
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
                        send_message(chat_id, "⏳ <b>Εκτελείται σάρωση αγορών...</b> Παρακαλώ περιμένετε μερικά δευτερόλεπτα.")
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
                        send_message(chat_id, "Γεια σου! Στείλε μου την εντολή <b>/picks</b> για να σαρώσω τα σημερινά παιχνίδια και να σου στείλω τα value picks άμεσα.")
        except Exception as e:
            print(f"Σφάλμα στο loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_bot()
