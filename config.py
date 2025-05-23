import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SIGNING_SECRET = os.environ.get('SIGNING_SECRET')
TOKEN_DISCORD = os.environ.get('TOKEN_DISCORD')
MONGO_DB = os.environ.get('MONGO_DB')
DB_COLLECTION = os.environ.get('DB_COLLECTION')

SLACK_CHANNEL_DISCORD = os.environ.get('SLACK_CHANNEL_DISCORD')
DISCORD_NEWBIES_WEBHOOK_URL = os.environ.get('DISCORD_NEWBIES_WEBHOOK_URL')

SLACK_CHANNEL_LAST_USER = {}
DISCORD_CHANNEL_LAST_USER = {}

SLACK_BOT_ID = None
DISCORD_BOT_ID = None