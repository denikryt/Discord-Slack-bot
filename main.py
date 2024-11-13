from flask import Flask
from threading import Thread
from slack_bot import slack_events
from discord_bot import discord_client
import os
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,  # Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Формат лога
    handlers=[
        logging.FileHandler("app.log", mode='w', encoding="utf-8"),  # Логирование в файл app.log
        # logging.StreamHandler()  # Логирование в консоль (по желанию)
    ]
)

app = Flask(__name__)

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