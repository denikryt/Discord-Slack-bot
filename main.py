import asyncio
import re
import os
import discord

from flask import Flask, jsonify, request
from threading import Thread
from pymongo import MongoClient
from discord import Intents, Client, Message, Forbidden, MessageType
from discord.ext import commands
from dotenv import load_dotenv
from pathlib import Path
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SIGNING_SECRET = os.environ.get('SIGNING_SECRET')
TOKEN_DISCORD = os.environ.get('TOKEN_DISCORD')

SLACK_CHANNEL_ID_GENERAL = os.environ.get('SLACK_CHANNEL_ID_GENERAL')
SLACK_CHANNEL_ID_RANDOM = os.environ.get('SLACK_CHANNEL_ID_RANDOM')
SLACK_CHANNEL_ID_DISCORD = os.environ.get('SLACK_CHANNEL_ID_DISCORD')
SLACK_CHANNEL_ID_TEST = os.environ.get('SLACK_CHANNEL_ID_TEST')

DISCORD_CHANNEL_ID_GENERAL = os.environ.get('DISCORD_CHANNEL_ID_GENERAL')
DISCORD_CHANNEL_ID_RANDOM = os.environ.get('DISCORD_CHANNEL_ID_RANDOM')
DISCORD_CHANNEL_ID_TEST = os.environ.get('DISCORD_CHANNEL_ID_TEST')

# ----------- MongoDB Configuration -----------
mongo_client = MongoClient(os.environ['MONGO_DB'])  # MongoDB URI из переменных окружения
db = mongo_client['HACKLAB']  # Имя базы данных
messages_collection = db['Slack-Discord messages']  # Имя коллекции

# -----------Flask app Configuration -----------
app = Flask('')

# ----------- Slack Bot Configuration -----------
slack_client = WebClient(token=SLACK_TOKEN)
signature_verifier = SignatureVerifier(signing_secret=SIGNING_SECRET)
BOT_ID = slack_client.api_call("auth.test")['user_id']

@app.route("/slack/events", methods=["POST"])
def slack_events():
    # Validate the request signature
    if not signature_verifier.is_valid_request(request.get_data(), request.headers):
        return jsonify({"error": "invalid request"}), 403

    # Handle URL verification challenge
    event_data = request.json

    if "type" in event_data and event_data["type"] == "url_verification":
        return jsonify({"challenge": event_data["challenge"]})
    
    # Process event data
    event = event_data.get("event", {})
    user_id = event.get('user')
    channel_id = event.get('channel')
    
    print('NEW MESSAGE FROM SLACK', event.get('text'))

    if event.get('text') == None:
        return jsonify({"status": "no text found"})

    if user_id != BOT_ID:
        if channel_id == SLACK_CHANNEL_ID_GENERAL:
            print('SLACK - MESSAGE FROM GENERAL')
            discord_channel = discord_client.get_channel(int(DISCORD_CHANNEL_ID_GENERAL))

        elif channel_id == SLACK_CHANNEL_ID_RANDOM:
            print('SLACK - MESSAGE FROM RANDOM')
            discord_channel = discord_client.get_channel(int(DISCORD_CHANNEL_ID_RANDOM))
        
        elif channel_id == SLACK_CHANNEL_ID_TEST:
            print('SLACK - MESSAGE FROM TEST')
            discord_channel = discord_client.get_channel(int(DISCORD_CHANNEL_ID_TEST))

        else:
            print('SLACK - MESSAGE FROM OTHER CHANNEL')
            return jsonify({"status": "channel not handled"})
        
        if event.get('thread_ts'):
            print('SLACK - MESSAGE IN THREAD, MESSAGE_ID', event.get('thread_ts'))

            try:
                # Пытаемся получить Discord message ID по Slack message ID
                discord_message_id = get_discord_message_id(event.get('thread_ts'))
                send_thread_message_to_discord(event, discord_channel=discord_channel)
            except KeyError:
                # Если Slack message ID не найден, выводим сообщение об ошибке
                print("Error: Discord message ID not found for this Slack message.")
                send_new_message_to_discord(event, discord_channel=discord_channel, slack_message_id=event.get('thread_ts'))

        elif event.get('ts'):
            print('SLACK - MESSAGE IN CHANNEL, MESSAGE_ID', event.get('ts'))
            send_new_message_to_discord(event, discord_channel=discord_channel, slack_message_id=event.get('ts'))
        else:
            print('UNKNOWN MESSAGE FROM SLACK')
            return jsonify({"status": "unknown message type"})

        return jsonify({"status": "ok"})
    
    return jsonify({"status": "ignored"})

# ----------- Discord Bot Configuration -----------
intents = Intents.default()
intents.message_content = True 
discord_client = Client(intents=intents)

@discord_client.event
async def on_ready():
    print(f'{discord_client.user} is now running!')

@discord_client.event
async def on_message(message: Message):
    if message.author == discord_client.user:
        return

    # Проверяем тип канала
    if isinstance(message.channel, discord.TextChannel):
        print('------> DISCORD - NEW MESSAGE IN CHANNEL:', message.channel)
        await send_new_message_to_slack(message)

    elif isinstance(message.channel, discord.Thread):
        if message.type == MessageType.default:
            print('------> DISCORD - MESSAGE IN THREAD:', message.channel)
            await send_thread_message_to_slack(message)
        
# ----------- Helper functions  -----------

# ----------- Helper functions for MongoDB -----------
def save_message_to_db(slack_message_id, discord_message_id):
    messages_collection.insert_one({
        "slack_message_id": slack_message_id,
        "discord_message_id": discord_message_id
    })

def get_discord_message_id(slack_message_id):
    result = messages_collection.find_one({"slack_message_id": slack_message_id})
    if result:
        return result['discord_message_id']
    raise KeyError("Discord message ID not found for this Slack message ID")

#------------------------------------------
# Helper functions to send message to Discord

def send_thread_message_to_discord(event, discord_channel):
    # Правильный запуск асинхронной функции с использованием event loop
    asyncio.ensure_future(send_thread_message_to_discord_async(event, discord_channel), loop=discord_client.loop)

def send_new_message_to_discord(event, discord_channel, slack_message_id):
    # Правильно запускаем асинхронную функцию с использованием event loop
    asyncio.ensure_future(send_new_message_to_discord_async(event, discord_channel, slack_message_id), loop=discord_client.loop)
    
def clean_and_format_thread_name(raw_text):
   # Убираем часть с именем пользователя и любые звёздочки перед текстом
    cleaned_text = re.sub(r'\*\*💂_.*?_\\*\*\s*', '', raw_text).strip()
    # Убираем возможные звёздочки в начале строки
    cleaned_text = cleaned_text.lstrip('*').strip()
    return cleaned_text

async def send_thread_message_to_discord_async(event, discord_channel):
    try:
        slack_message_id = event.get('thread_ts')
        discord_message_id = get_discord_message_id(slack_message_id)    
        # discord_channel = discord_client.get_channel(int(os.environ['DISCORD_CHANNEL_ID_TEST']))

        if discord_channel:
            # Извлекаем сообщение по его ID
            parent_message = await discord_channel.fetch_message(discord_message_id)

            if parent_message:
                user_text: str = event.get('text')
                user_name = slack_client.users_info(user=event.get('user'))['user']['real_name']
                text = f'**💂_{user_name}_**\n{user_text}'

                # Формируем часть текста из родительского сообщения для имени ветки (первые 5 слов)
                parent_text = parent_message.content
                thread_name = " ".join(parent_text.split()[:5])
                thread_name = clean_and_format_thread_name(thread_name) if thread_name else "Discussion"

                # Проверяем, есть ли уже ветка для этого сообщения
                if parent_message.thread:
                    # Если ветка уже существует, просто отправляем сообщение в существующую ветку
                    thread = parent_message.thread
                    await thread.send(text)
                    print(f'Message sent in existing thread: {text}')
                else:
                    # Создаём новую ветку, если её нет
                    thread = await parent_message.create_thread(
                        name=f"{thread_name}",
                    )
                    await thread.send(text)
                    print(f'Message sent in new thread: {text}')
            else:
                print("Message not found in Discord channel.")
    except Exception as e:
        print(f"Error: {e}")

async def send_new_message_to_discord_async(event, discord_channel, slack_message_id):
    user_id = event.get('user')
    user_text = event.get('text')
    user_info = slack_client.users_info(user=user_id)
    user_name = user_info['user']['real_name']

    text = f'**💂_{user_name}_**\n{user_text}'

    # discord_channel = discord_client.get_channel(int(DISCORD_CHANNEL_ID_TEST))

    if discord_channel:
        # Ожидаем отправки сообщения и получаем объект отправленного сообщения
        message = await discord_channel.send(text)
        # Получаем ID сообщения
        message_id = message.id
        print(f'New message sent to discord with ID: {message_id}')

        save_message_to_db(slack_message_id, message_id)

#------------------------------------------
# Helper functions to send message to Slack

async def send_new_message_to_slack(message: Message):
    user_message = message.content
    channel_name = message.channel.name
    user_name = message.author.display_name

    if channel_name == 'general':
        print('DISCORD - MESSAGE FROM GENERAL')
        text = f'💂*_{user_name}_*\n{user_message}'
        # Отправляем сообщение в Slack
        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID_GENERAL,  # Укажите ID канала Slack, куда отправлять
            text=text
        )     
    elif channel_name == 'random':
        print('DISCORD - MESSAGE FROM RANDOM')
        text = f'💂*_{user_name}_*\n{user_message}'
        # Отправляем сообщение в Slack
        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID_RANDOM,  # Укажите ID канала Slack, куда отправлять
            text=text
        ) 
    elif channel_name == 'tests':
        print('DISCORD - MESSAGE FROM TESTS')
        text = f'💂*_{user_name}_*\n{user_message}'
        # Отправляем сообщение в Slack
        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID_TEST,  # Укажите ID канала Slack, куда отправлять
            text=text
        ) 
    else:
        print('DISCORD - MESSAGE FROM OTHER CHANEL')
        text = f'💂*_{user_name}_* 🔉*_#{channel_name}_*\n{user_message}'
        # Отправляем сообщение в Slack
        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID_DISCORD,  # Укажите ID канала Slack, куда отправлять
            text=text
        )

    print('Message sent to Slack:', text)
    save_message_to_db(response['ts'], message.id)

async def send_thread_message_to_slack(message: Message):
  # Получаем ID родительского сообщения
    discord_parent_message = await message.channel.parent.fetch_message(message.channel.id)
    discord_parent_message_id = discord_parent_message.id

    print('------> DISCORD PARENT MESSAGE ID', discord_parent_message_id)

    result = messages_collection.find_one({"discord_message_id": discord_parent_message_id})
    slack_parent_message_id = result['slack_message_id'] if result else None

    if slack_parent_message_id:
        channel_name = str(message.channel.parent)
        user_message = str(message.content)
        user_name = message.author.display_name
    
        print('------> DISCORD CHANNEL NAME', channel_name)

        if channel_name == 'general':
            print('DISCORD - MESSAGE FROM GENERAL')
            text = f'💂*_{user_name}_*\n{user_message}'
            # Отправляем сообщение в Slack
            response = slack_client.chat_postMessage(
                channel=SLACK_CHANNEL_ID_GENERAL,  # Укажите ID канала Slack, куда отправлять
                text=text,
                thread_ts=slack_parent_message_id
            )     
        elif channel_name == 'random':
            print('DISCORD - MESSAGE FROM RANDOM')
            text = f'💂*_{user_name}_*\n{user_message}'
            # Отправляем сообщение в Slack
            response = slack_client.chat_postMessage(
                channel=SLACK_CHANNEL_ID_RANDOM,  # Укажите ID канала Slack, куда отправлять
                text=text,
                thread_ts=slack_parent_message_id
            ) 
        elif channel_name == 'tests':
            print('DISCORD - MESSAGE FROM RANDOM')
            text = f'💂*_{user_name}_*\n{user_message}'
            # Отправляем сообщение в Slack
            response = slack_client.chat_postMessage(
                channel=SLACK_CHANNEL_ID_TEST,  # Укажите ID канала Slack, куда отправлять
                text=text,
                thread_ts=slack_parent_message_id
            ) 
        else:
            print('DISCORD - MESSAGE FROM OTHER CHANNEL')
            text = f'💂*_{user_name}_* 🔉*_#{channel_name}_*\n{user_message}'
            # Отправляем сообщение в Slack
            response = slack_client.chat_postMessage(
                channel=SLACK_CHANNEL_ID_DISCORD,  # Укажите ID канала Slack, куда отправлять
                text=text
            )

        print('Thread message sent to Slack:', text)
    else:
        print("!send_thread_message_to_slack!")
        print("Error: Slack message ID not found for the Discord parent message.")

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
discord_client.run(TOKEN_DISCORD)
