import requests
import hmac
import hashlib
import pandas as pd
import time
import threading
import webbrowser
from flask import Flask, render_template, jsonify
import ta
from flask_socketio import SocketIO
import key_details
import json

app = Flask(__name__)
socketio = SocketIO(app)  # Enable real-time communication

# CoinDCX API Configuration
key = key_details.key
secret = key_details.secret
BASE_URL = "https://api.coindcx.com"
PUBLIC_URL = "https://public.coindcx.com"

# Trading Parameters
SYMBOL = "B-SOL_USDT"
FAST_EMA = 9
SLOW_EMA = 21
ADX_PERIOD = 14
LEVERAGE = 5
TRADE_SIZE = 10  # Amount to trade in USDT

# Global Variables
bot_running = False
log_messages = []
open_position = None  
entry_price = None  
stop_loss = None  
take_profit = None  
highest_price = None  # Tracks highest price for trailing SL (long)
lowest_price = None   # Tracks lowest price for trailing SL (short)
def open_browser():
	webbrowser.open_new("http://127.0.0.1:5000/")
def get_market_data():
    """Fetch latest OHLCV data for trading"""
    url = f"{PUBLIC_URL}/market_data/candles"
    params = {"pair": SYMBOL, "interval": "15m", "limit": 100}
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame(data)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df.set_index("time", inplace=True)
        df["close"] = df["close"].astype(float)
        return df
    return None
def calculate_signals():
    """Calculate EMA crossover and ADX indicators"""
    df = get_market_data()
    if df is None:
        return None, None
    df["ema_fast"] = ta.trend.ema_indicator(df["close"], window=FAST_EMA)
    df["ema_slow"] = ta.trend.ema_indicator(df["close"], window=SLOW_EMA)
    df["adx"] = ta.trend.adx(df["high"], df["low"], df["close"], window=ADX_PERIOD)
    latest = df.iloc[-1]
    return latest, df
def place_order(side):
    global open_position, entry_price, stop_loss, take_profit, highest_price, lowest_price    
    url = f"{BASE_URL}/exchange/v1/orders/create"
    secret_bytes = bytes(secret, encoding='utf-8')
    timeStamp = int(round(time.time() * 1000))
    body = {
        "timestamp":timeStamp , # EPOCH timestamp in seconds
        "order": {
        "side": side, # buy OR sell
        "pair": SYMBOL, # instrument.string
        "order_type": "market_order", # market_order OR limit_order 
        "price": "0.0", #numeric value        
        "total_quantity": 3, #numerice value
        "leverage": 10, #numerice value
        "notification": "email_notification", # no_notification OR email_notification OR push_notification
        "time_in_force": "good_till_cancel", # good_till_cancel OR fill_or_kill OR immediate_or_cancel
        "hidden": False, # True or False
        "post_only": False # True or False
        }
        }
    json_body = json.dumps(body, separators = (',', ':'))
    signature = hmac.new(secret_bytes, json_body.encode(), hashlib.sha256).hexdigest()
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': key,
        'X-AUTH-SIGNATURE': signature
    }
    response = requests.post(url, data = json_body, headers = headers)
    data = response.json()
    print(data['message'])
    return response.status_code, response.json()
    if response.status_code == 200:
        order_info = data
        entry_price = float(order_info.get("price"))  # Get executed price
        log_trade(f"Order placed: {side} {TRADE_SIZE} USDT at {entry_price}")
        if side == "buy":
            stop_loss = entry_price * 0.98  # SL = 2% below
            take_profit = entry_price * 1.05  # TP = 5% above
            highest_price = entry_price  # Initialize highest price for TSL
        elif side == "sell":
            stop_loss = entry_price * 1.02  # SL = 2% above
            take_profit = entry_price * 0.95  # TP = 5% below
            lowest_price = entry_price  # Initialize lowest price for TSL
        open_position = side
        log_trade(f"SL: {stop_loss}, TP: {take_profit} (Trailing SL Enabled)")
        return True
    else:
        log_trade(f"Order failed: {response.json()}")
        return False
def log_trade(message):
    """Log trades to file and update GUI"""
    global log_messages
    log_messages.append(message)
    with open("trade_log.txt", "a") as f:
        f.write(message + "\n")
def trading_bot():
    """Main trading loop with SL & TP."""
    global bot_running, open_position, entry_price, stop_loss, take_profit
    while bot_running:
        latest, df = calculate_signals()
        if latest is None:
            time.sleep(10)
            continue
        fast_ema, slow_ema, adx, current_price = (
            latest["ema_fast"],
            latest["ema_slow"],
            latest["adx"],
            latest["close"],
        )
        # Check SL & TP first
        if open_position == "buy":
            if current_price <= stop_loss:
                log_trade("Stop-Loss hit! Selling position.")
                place_order("sell")
                open_position = None
                continue
            elif current_price >= take_profit:
                log_trade("Take-Profit hit! Selling position.")
                place_order("sell")
                open_position = None
                continue
        elif open_position == "sell":
            if current_price >= stop_loss:
                log_trade("Stop-Loss hit! Closing short.")
                place_order("buy")
                open_position = None
                continue
            elif current_price <= take_profit:
                log_trade("Take-Profit hit! Closing short.")
                place_order("buy")
                open_position = None
                continue
        # Normal trading signals
        if fast_ema > slow_ema and adx > 25 and open_position is None:
            if place_order("buy"):
                log_trade("Entered Long Position")
        elif fast_ema < slow_ema and adx > 25 and open_position == "buy":
            if place_order("sell"):
                log_trade("Exited Long Position")
                open_position = None
        time.sleep(10)  # Wait before next check
# app = Flask(__name__)
@app.route("/")
def index():
    """Render HTML GUI"""
    return render_template("index.html")
@app.route("/connect", methods=["GET"])
def connect():
    """Initialize API connection"""
    # key = key_details.key
    # secret = key_details.secret
    try:
        secret_bytes = bytes(secret, encoding='utf-8')
        timeStamp = int(round(time.time() * 1000))
        body = {"timestamp": timeStamp}
        json_body = json.dumps(body, separators = (',', ':'))
        
        signature = hmac.new(secret_bytes, json_body.encode(), hashlib.sha256).hexdigest()
        headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': key,
                'X-AUTH-SIGNATURE': signature
                }
        url = f"{BASE_URL}/exchange/v1/users/info"
        # url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"   
        response = requests.post(url, data = json_body, headers = headers)
        data = response.json()      
        return jsonify({"status": "Connection Established", "data": data})
    except Exception as e:
            log_messages("Connection failed: Invalid API key/secret.") 

@app.route("/start", methods=["GET"])
def start():
    """Start trading bot"""
    global bot_running
    if not bot_running:
        try:
            bot_running = True
            threading.Thread(target=trading_bot).start()
            return jsonify({"status": "Bot Started"})
        except Exception as e:
            return jsonify("Bot not started")
@app.route("/stop", methods=["GET"])
def stop():
    """Stop trading bot"""
    global bot_running
    bot_running = False
    return jsonify({"status": "Bot Stopped"})
@app.route("/position", methods=["GET"])
def position():
    """Return current position"""
    return jsonify({"position": open_position})
@app.route("/logs", methods=["GET"])
def logs():
    """Return log messages"""
    return jsonify({"logs": log_messages})
def send_live_updates():
    """Send real-time price and indicator updates to the dashboard."""
    while True:
        latest, df = calculate_signals()
        if latest is None:
            time.sleep(5)
            continue
        data = {
            "price": latest["close"],
            "ema_fast": latest["ema_fast"],
            "ema_slow": latest["ema_slow"],
            "adx": latest["adx"],
            "position": open_position,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
        socketio.emit("update_data", data)  # Send data to the frontend
        time.sleep(5)  # Update every 5 seconds

threading.Thread(target=send_live_updates, daemon=True).start()

if __name__ == "__main__":
    threading.Timer(1.25, open_browser).start()
    app.run(debug=True, use_reloader=False)
