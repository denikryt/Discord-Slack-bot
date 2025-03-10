import discord
from discord import Intents, Client, Message, MessageType
from discord.ext import commands
from slack_sdk.errors import SlackApiError
import config
import db
import urllib.parse
import aiohttp
import os
import time
import re
import json
import logging

intents = Intents.default()
intents.message_content = True 
intents.members = True
discord_client = Client(intents=intents)

@discord_client.event
async def on_ready():
    logger(f'{discord_client.user} is now running!')

@discord_client.event
async def on_member_join(member):
    logger('New member!')

    user_name = member.name
    user_id = member.id
    send_greet_message(user_id, user_name)

@discord_client.event
async def on_message(message: Message):
    if message.author == discord_client.user:
        return json.dumps({"status":"ignored"})  

    # Игнорировать сообщения типа new_member
    if message.type == discord.MessageType.new_member:
        return  # Игнорируем это сообщение, оно будет обработано в on_member_join

    logger(f'--------------')
    logger(f'DISCORD INCOMING REQUEST: {message}') 

    # Проверяем тип канала
    if isinstance(message.channel, discord.TextChannel):
        logger(f'-------DISCORD - NEW MESSAGE-------')
        logger(f'---> {message.content}')
        result = await send_new_message_to_slack(message)
        return result

    elif isinstance(message.channel, discord.Thread):
        if message.type == MessageType.default:
            logger(f'-------DISCORD - THREAD MESSAGE-------')
            logger(f'---> {message.content}')
            result = await send_thread_message_to_slack(message)
            return result

        elif message.type == MessageType.reply:
            logger(f'-------DISCORD - REPLY MESSAGE IN THREAD-------')
            logger(f'---> {message.content}')
            
            # Получение ссылки на сообщение, на которое был дан ответ
            replied_message = await message.channel.fetch_message(message.reference.message_id)
            logger(f'REPLIED MESSAGE: {replied_message.content}')

            result = await send_thread_message_to_slack(message)
            return result
        else:
            logger('UNKNOWN ACTION IN DISCORD THREAD')
            return json.dumps({"status":"unknown"})  
    else:
        logger('UNKNOWN ACTION IN DISCORD')
        return json.dumps({"status":"unknown"})  
 
#------------------------------------------
# Helper functions to send message to Slack
#------------------------------------------

def send_greet_message(user_id, user_name):
    import json
    from slack_bot import sync_slack_client

    # Функция для загрузки ID канала из JSON
    def get_channel_id_by_name(platform, channel_name):
        try:
            file_path = os.path.abspath('channels.json')
            with open(file_path, 'r', encoding='utf-8') as f:
                channels_data = json.load(f)
            for channel in channels_data['channels_mapping']:
                if channel['name'] == channel_name:
                    return channel[platform]
            return None
        except Exception as e:
            print(f'Error loading JSON from {file_path}: {str(e)}')
            raise e

    # Получаем ID канала для "новенькі"
    slack_channel_id = get_channel_id_by_name("slack_channel_id", "новенькі")
    if not slack_channel_id:
        raise ValueError('Channel with name "новенькі" not found in channels.json')

    slack_message = {
        "channel": slack_channel_id,
        "text": f"*_{user_name}_* доєднався на сервер!",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*_{user_name}_* доєднався на сервер!"
                }
            },
            {
                "type": "actions",
                "block_id": "greet_button_block",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "greet_button",
                        "text": {
                            "type": "plain_text",
                            "text": "👋 Помахай та привітайся!"
                        },
                        "value": f"{user_name},{user_id}"  # Сохраняем имя и ID
                    }
                ]
            }
        ]
    }

    # Отправляем сообщение в Slack
    response = sync_slack_client.chat_postMessage(**slack_message)
    return response

async def send_new_message_to_slack(message: Message):
    from slack_bot import sync_slack_client
    discord_message_id = message.id

    try:
        channel_to_send = choose_channel(message)
        text = format_text(message)
    except ValueError:
        return
    
    if message.attachments:
        logger('MESSAGE WITH FILES')

        file_paths, files = await collect_files(message)

        response = sync_slack_client.files_upload_v2(
            channel=channel_to_send,
            initial_comment=text,
            file_uploads=[{
                'file': file['file'],
                'filename': file['filename']
            } for file in files]
            )      

        slack_message_id = wait_message_ID(sync_slack_client, response)
        delete_files(file_paths)
    else:
        logger('MESSAGE WITHOUT FILES')

        response = sync_slack_client.chat_postMessage(
            channel=channel_to_send,  # Укажите ID канала Slack, куда отправлять
            text=text
        ) 
        slack_message_id = response['ts']
    
    result = sync_slack_client.conversations_info(channel=channel_to_send)
    channel_name = result['channel']['name']

    logger(f'New message sent to Slack: #{channel_name}!')

    if slack_message_id:
        db.save_message_to_db(slack_message_id, discord_message_id)
        logger("---> 'send_new_message_to_slack' func is done")
        return json.dumps({"status":"ok"})  
    else:
        logger('---> slack_message_id is empty')
        return json.dumps({"status":"false"})

def wait_message_ID(sync_slack_client, response):
# Polling the files.info API to get the 'shares' property with ts and thread_ts
    file_id = response['files'][0]['id']

    while True:
        try:
            file_info = sync_slack_client.files_info(file=file_id)
            # print('----- file_info -----\n', file_info)
            shares = file_info['file'].get('shares')
            
            if shares:
                logger(f'----- SHARES -----\n%s: {shares}')

                if 'private' in shares and shares['private']:
                    shared_channels = list(shares['private'].keys())
                    if shared_channels:
                        channel = shared_channels[0]
                        ts = shares['private'][channel][0]['ts']  # Извлечение ts для private
                        logger(f"Parent message ts (private): {ts}")
                        return ts
                    
                elif 'public' in shares and shares['public']:
                    shared_channels = list(shares['public'].keys())
                    if shared_channels:
                        channel = shared_channels[0]
                        ts = shares['public'][channel][0]['ts']  # Извлечение ts для public
                        logger("Parent message ts (public): {ts}")
                        return ts
                else:
                    logger("No shares found in public or private sections.")
                    return None
                
            logger('NO SHARES YET')
            time.sleep(1)  # Wait 1 second before polling again
        except SlackApiError as e:
            logger(f"""Error retrieving file info: {e.response['error']}""")
            exit()

async def send_thread_message_to_slack(message: Message):
    from slack_bot import sync_slack_client

  # Получаем ID родительского сообщения
    discord_parent_message = await message.channel.parent.fetch_message(message.channel.id)
    discord_parent_message_id = discord_parent_message.id

    result = db.messages_collection.find_one({"discord_message_id": discord_parent_message_id})
    slack_parent_message_id = result['slack_message_id'] if result else None

    if slack_parent_message_id:
        try:
            channel_to_send = choose_channel(message)
            text = format_text(message)
        except ValueError:
            return

        if message.attachments:
            logger('MESSAGE WITH FILES')

            file_paths, files = await collect_files(message)

            # Upload all files at once using files_upload_v2
            response = sync_slack_client.files_upload_v2(
                channels=channel_to_send,
                initial_comment=text,
                file_uploads=[{
                    'file': file['file'],
                    'filename': file['filename']
                } for file in files], 
                thread_ts=slack_parent_message_id
            )

            delete_files(file_paths)

        else:
            logger('MESSAGE WITHOUT IMAGE')

            response = sync_slack_client.chat_postMessage(
                channel=channel_to_send,  # Укажите ID канала Slack, куда отправлять
                text=text,
                thread_ts=slack_parent_message_id
            ) 

        if response.get('ok'): 
            result = sync_slack_client.conversations_info(channel=channel_to_send)
            channel_name = result['channel']['name']

            logger(f'Thread message sent to Slack: #{channel_name}')
            logger("---> 'send_thread_message_to_slack' func is done")

            return json.dumps({"status":"ok"})  
        else:
            logger(f"""Ошибка при загрузке файла: {response.get('error')}""")
            return json.dumps({"status":"false"})  

def format_mentions(message):
    user_message = str(message.content)
    mentions = message.mentions
    if mentions:
        logger('Mentions were found!')
        for mention in mentions:
            user_message = user_message.replace(f'<@{mention.id}>', f'@{mention.display_name}')
        return user_message
    else:
        logger('Mentions were not found!')
        return user_message

def choose_channel(message):
    # Загрузка маппинга каналов
    discord_channels_dict = load_channels_mapping()

    channel_id, channel_name = get_channel_id_and_name(message)

    # Проверка наличия канала в словаре и создание текста для отправки
    if channel_id in discord_channels_dict:
        slack_channel = discord_channels_dict[channel_id]
        return slack_channel 
    else:
        logger(f'DISCORD - MESSAGE FROM OTHER CHANNEL - #{channel_name}')
        if channel_name != None:
            channel_to_send = config.SLACK_CHANNEL_DISCORD
            return channel_to_send
        else:
            logger('UNKNOWN CHANNEL NAME')
            return
        
def format_text(message):
    discord_channels_dict = load_channels_mapping()
    channel_id, channel_name = get_channel_id_and_name(message)

    if message.stickers:
        sticker_urls = [sticker.url for sticker in message.stickers]
        sticker_text = "\n".join(sticker_urls)
        user_message = f":dancing-penguin:"
    else:
        user_message = format_mentions(message)

    user_name = message.author.display_name

    logger(f'Message from user: {user_name}')
    logger(f'Message in channel: {channel_name}, ID: {channel_id}')

    if channel_id in discord_channels_dict:
        text = f'💂*_{user_name}_*\n{user_message}'
    else:
        text = f'💂*_{user_name}_* 🔉*_#{channel_name}_*\n{user_message}'

    return text

def load_channels_mapping():
    # Функция для загрузки маппинга из JSON
    try:
        file_path = os.path.abspath('channels.json')
        with open(file_path, 'r', encoding='utf-8') as f:
            channels_data = json.load(f)
        discord_to_slack = {item['discord_channel_id']: item['slack_channel_id'] for item in channels_data['channels_mapping']}
        return discord_to_slack
    except Exception as e:
        print(f'Error loading JSON from {file_path}: {str(e)}')
        raise e

def get_channel_id_and_name(message):
    # Получаем имя канала
    if hasattr(message.channel, 'parent'):
        channel_name = str(message.channel.parent)
        channel_id = str(message.channel.parent.id)
    else:
        channel_name = message.channel.name
        channel_id = str(message.channel.id)

    return channel_id, channel_name

async def collect_files(message):
    # Download images to disk
    file_paths = []
    for attachment in message.attachments:
        if attachment.url:
            image_path = await download_image_from_discord(attachment.url)
            if image_path:
                file_paths.append(image_path)

    # Prepare the files to be uploaded
    if file_paths :
        files = []
        for file_path in file_paths:
            with open(file_path, 'rb') as file:
                files.append({
                    'file': file.read(),  # Read the file content into memory
                    'filename': os.path.basename(image_path)
                })

    return file_paths, files

async def download_image_from_discord(image_url):
    # Sanitize the image URL to remove query parameters and other invalid characters for filenames
    sanitized_name = urllib.parse.unquote(image_url.split("/")[-1].split("?")[0])
    
    # Ensure the file name is safe by removing invalid characters
    sanitized_name = re.sub(r'[<>:"/\\|?*]', '_', sanitized_name)
    
    os.makedirs("temp_files", exist_ok=True)
    image_path = f"temp_files/{sanitized_name}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status == 200:
                    with open(image_path, 'wb') as f:
                        f.write(await response.read())
                    logger(f"Downloaded image from Discord: {image_url}")
                    return image_path
                else:
                    logger(f"Failed to download image: {image_url}")
    except Exception as e:
        logger(f"Error downloading image from {image_url}: {e}")
    return None

def delete_files(file_paths):

    """Delete files after they have been used."""
    for file_path in file_paths:
        try:
            os.remove(file_path)
            logger(f"Deleted image: {file_path}")
        except Exception as e:
            logger(f"Error deleting image {file_path}: {e}")

def logger(log_text):
    print(log_text)
    logging.info(log_text)