import os
from flask import Flask
from threading import Thread
from slackeventsapi import SlackEventAdapter
import slack
from discord import Intents, Client, Message, Forbidden
from discord.ext import commands
from dotenv import load_dotenv
from pathlib import Path

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

SLACK_CHANNEL_ID_GENERAL = os.environ.get('SLACK_CHANNEL_ID_GENERAL')
SLACK_CHANNEL_ID_RANDOM = os.environ.get('SLACK_CHANNEL_ID_RANDOM')
SLACK_CHANNEL_ID_DISCORD = os.environ.get('SLACK_CHANNEL_ID_DISCORD')

DISCORD_CHANNEL_ID_GENERAL = os.environ.get('DISCORD_CHANNEL_ID_GENERAL')
DISCORD_CHANNEL_ID_RANDOM = os.environ.get('DISCORD_CHANNEL_ID_RANDOM')

# Flask app to handle both Slack and Discord events
app = Flask('')

# ----------- Slack Bot Configuration -----------
slack_event_adapter = SlackEventAdapter(os.environ['SIGNING_SECRET'], '/slack/events', app)
slack_client = slack.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = slack_client.api_call("auth.test")['user_id']

@slack_event_adapter.on('message')
def handle_slack_message(payload):
    event = payload.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')

    if user_id != BOT_ID:
        if channel_id == SLACK_CHANNEL_ID_GENERAL:
            discord_channel = discord_client.get_channel(int(DISCORD_CHANNEL_ID_GENERAL))

        elif channel_id == SLACK_CHANNEL_ID_RANDOM:
            discord_channel = discord_client.get_channel(int(DISCORD_CHANNEL_ID_RANDOM))

        # Forward message to Discord
        send_message_to_discord(event, discord_channel)

# ----------- Discord Bot Configuration -----------
intents = Intents.default()
intents.message_content = True 
discord_client = Client(intents=intents)
bot = commands.Bot(command_prefix='!', intents=intents)
# SLACK_CHANNEL_DISCORD = discord_client.get_channel(int(os.environ['DISCORD_TEST_CHANNEL_ID']))

@discord_client.event
async def on_ready():
    print(f'{discord_client.user} is now running!')

@discord_client.event
async def on_message(message: Message):
    if message.author == discord_client.user:
        return
    
    send_message_to_slack(message)
        
# ----------- Helper functions  -----------
# Helper function to send message to Slack
def send_message_to_slack(message):
    user_name = message.author.name
    channel_name = message.channel.name
    user_message = str(message.content)

    if channel_name == 'general':
        text = f'*USER: _{user_name}_*\n {user_message}'
        slack_client.chat_postMessage(channel=SLACK_CHANNEL_ID_GENERAL, text=text)

    elif channel_name == 'random':
        text = f'*USER: _{user_name}_*\n {user_message}'
        slack_client.chat_postMessage(channel=SLACK_CHANNEL_ID_RANDOM, text=text)

    else:
        text = f'*CHANNEL: _#{channel_name}_*\n*USER: _{user_name}_*\n {user_message}'
        slack_client.chat_postMessage(channel=SLACK_CHANNEL_ID_DISCORD, text=text)

# Helper function to send message to Discord
def send_message_to_discord(event, discord_channel):
    channel_id = event.get('channel')
    user_id = event.get('user')
    user_text = event.get('text')

    channel_info = slack_client.conversations_info(channel=channel_id)
    channel_name = channel_info['channel']['name']
    user_info = slack_client.users_info(user=user_id)
    user_name = user_info['user']['real_name']

    text = f'**CHANNEL: _#{channel_name}_**\n**USER: _{user_name}_**\n {user_text}'

    if discord_channel:
        discord_client.loop.create_task(discord_channel.send(text))

# ----------- Flask Web Server for Render -----------
@app.route('/')
def home():
    return 'Both bots are running'

def run():
    app.run(host="0.0.0.0", port=5000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Keep the server alive and run both bots
keep_alive()
discord_client.run(os.environ['TOKEN_DISCORD'])
