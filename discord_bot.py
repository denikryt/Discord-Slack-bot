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
discord_client = Client(intents=intents)

@discord_client.event
async def on_ready():
    logger(f'{discord_client.user} is now running!')

@discord_client.event
async def on_message(message: Message):
    if message.author == discord_client.user:
        return json.dumps({"status":"ignored"})  

    # Проверяем тип канала
    if isinstance(message.channel, discord.TextChannel):
        logger('\n-------DISCORD - NEW MESSAGE-------')
        result = await send_new_message_to_slack(message)
        return result

    elif isinstance(message.channel, discord.Thread):
        if message.type == MessageType.default:
            logger('\n-------DISCORD - THREAD MESSAGE-------')
            result = await send_thread_message_to_slack(message)
            return result

        elif message.type == MessageType.reply:
            logger('\n-------DISCORD - REPLY MESSAGE IN THREAD-------')
            
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

async def send_new_message_to_slack(message: Message):
    from slack_bot import slack_client
    discord_message_id = message.id

    try:
        channel_to_send, text = choose_channel(message)
    except ValueError:
        return
    
    if message.attachments:
        logger('MESSAGE WITH FILES')

        file_paths, files = await collect_files(message)

        response = slack_client.files_upload_v2(
            channel=channel_to_send,
            initial_comment=text,
            file_uploads=[{
                'file': file['file'],
                'filename': file['filename']
            } for file in files]
            )      

        slack_message_id = wait_message_ID(slack_client, response)
        delete_files(file_paths)
    else:
        logger('MESSAGE WITHOUT FILES')

        response = slack_client.chat_postMessage(
            channel=channel_to_send,  # Укажите ID канала Slack, куда отправлять
            text=text
        ) 
        slack_message_id = response['ts']
    
    result = slack_client.conversations_info(channel=channel_to_send)
    channel_name = result['channel']['name']

    logger(f'Message sent to Slack channel {channel_name}!')

    if slack_message_id:
        db.save_message_to_db(slack_message_id, discord_message_id)
        logger("---> 'send_new_message_to_slack' func is done")
        return json.dumps({"status":"ok"})  
    else:
        logger('---> slack_message_id is empty')
        return json.dumps({"status":"false"})

def wait_message_ID(slack_client, response):
# Polling the files.info API to get the 'shares' property with ts and thread_ts
    file_id = response['files'][0]['id']

    while True:
        try:
            file_info = slack_client.files_info(file=file_id)
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
    from slack_bot import slack_client

  # Получаем ID родительского сообщения
    discord_parent_message = await message.channel.parent.fetch_message(message.channel.id)
    discord_parent_message_id = discord_parent_message.id

    logger(f'DISCORD - PARENT MESSAGE ID: {discord_parent_message_id}')

    result = db.messages_collection.find_one({"discord_message_id": discord_parent_message_id})
    slack_parent_message_id = result['slack_message_id'] if result else None

    if slack_parent_message_id:
        try:
            channel_to_send, text = choose_channel(message)
        except ValueError:
            return

        if message.attachments:
            logger('MESSAGE WITH FILES')

            file_paths, files = await collect_files(message)

            # Upload all files at once using files_upload_v2
            response = slack_client.files_upload_v2(
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

            response = slack_client.chat_postMessage(
                channel=channel_to_send,  # Укажите ID канала Slack, куда отправлять
                text=text,
                thread_ts=slack_parent_message_id
            ) 

        if response.get('ok'): 
            result = slack_client.conversations_info(channel=channel_to_send)
            channel_name = result['channel']['name']

            logger(f'Thread message sent to Slack: {channel_name}')
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
            user_id = f'@{mention.id}'
            user_message = user_message.replace(f'<@{mention.id}>', f'@{mention.display_name}')
            return user_message
    else:
        logger('Mentions was not found!')
        return user_message

def choose_channel(message):
    if hasattr(message.channel, 'parent'):
        channel_name = str(message.channel.parent)
    else:
        channel_name = message.channel.name

    user_message = format_mentions(message)
    user_name = message.author.display_name

    channels = ['general', 'random', 'tests']

    if channel_name in channels:
        if channel_name == 'general':
            logger(f'DISCORD - MESSAGE FROM - #{channel_name}')

            channel_to_send = config.SLACK_CHANNEL_GENERAL
            text = f'💂*_{user_name}_*\n{user_message}'
            # return 

        elif channel_name == 'random':
            logger(f'DISCORD - MESSAGE FROM - #{channel_name}')

            channel_to_send = config.SLACK_CHANNEL_RANDOM
            text = f'💂*_{user_name}_*\n{user_message}'
            # return

        elif channel_name == 'tests':
            logger(f'DISCORD - MESSAGE FROM - #{channel_name}')

            channel_to_send = config.SLACK_CHANNEL_TEST
            text = f'💂*_{user_name}_*\n{user_message}'

        elif channel_name == 'made-in-hacklab':
            logger(f'DISCORD - MESSAGE FROM - #{channel_name}')

            channel_to_send = config.SLACK_CHANNEL_MADE_IN_HACKLAB
            text = f'💂*_{user_name}_*\n{user_message}'

        return channel_to_send, text 
    
    else:
        logger(f'DISCORD - MESSAGE FROM OTHER CHANNEL - #{channel_name}')
        if channel_name != None:
            channel_to_send = config.SLACK_CHANNEL_DISCORD
            text = f'💂*_{user_name}_* 🔉*_#{channel_name}_*\n{user_message}'
            return channel_to_send, text
        else:
            logger('UNKNOWN CHANNEL NAME')
            return

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