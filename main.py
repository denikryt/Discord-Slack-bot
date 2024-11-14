from flask import Flask, request, Response
from threading import Thread
from slack_bot import slack_events
from discord_bot import discord_client
import os
import logging
import json

# Настройка основного логгера
logging.basicConfig(
    level=logging.INFO,  # Уровень логирования
    format='%(asctime)s - %(levelname)s - %(message)s',  # Формат лога
    handlers=[
        logging.FileHandler("app.log", mode='w', encoding="utf-8"),  # Логирование в файл app.log
    ]
)

# Настройка логгера для HTTP-запросов
http_logger = logging.getLogger("http_logger")
http_handler = logging.FileHandler("http_requests.log", mode='w', encoding="utf-8")
http_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
http_logger.addHandler(http_handler)
http_logger.setLevel(logging.INFO)

app = Flask(__name__)

def format_json(data):
    try:
        parsed = json.loads(data)
        return json.dumps(parsed, indent=4, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return data  # Если не JSON, вернуть как есть

@app.before_request
def log_request():
    body = request.get_data(as_text=True)
    formatted_body = format_json(body) if body else "No body"
    headers = json.dumps(dict(request.headers), indent=4, ensure_ascii=False)
    
    http_logger.info(
        f"Incoming request:\n"
        f"Method: {request.method}\n"
        f"URL: {request.url}\n"
        f"Headers:\n{headers}\n"
        f"Body:\n{formatted_body}"
    )

@app.after_request
def log_response(response: Response):
    formatted_response = format_json(response.get_data(as_text=True))
    headers = json.dumps(dict(response.headers), indent=4, ensure_ascii=False)

    http_logger.info(
        f"Outgoing response:\n"
        f"Status: {response.status_code}\n"
        f"Headers:\n{headers}\n"
        f"Body:\n{formatted_response}"
    )
    return response

@app.route('/')
def home():
    return 'Both bots are running'

# Flask route for Slack events
app.add_url_rule('/slack/events', view_func=slack_events, methods=['POST'])

# Start Flask server in a separate thread
def run():
    app.run(host="0.0.0.0", port=5000)
    
def keep_alive():
    t = Thread(target=run)
    t.start()

if __name__ == '__main__':
    keep_alive()
    discord_client.run(os.environ['TOKEN_DISCORD'])
