from flask import Flask, request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
from slack_sdk.web.async_client import AsyncWebClient
from config import SLACK_TOKEN, SIGNING_SECRET, SLACK_CHANNELS_DICT
import db
import asyncio
import re
import os
import aiohttp
import discord
import time
import logging

slack_client = AsyncWebClient(token=SLACK_TOKEN)
sync_slack_client = WebClient(token=SLACK_TOKEN)
signature_verifier = SignatureVerifier(signing_secret=SIGNING_SECRET)
BOT_ID = sync_slack_client.api_call("auth.test")['user_id']

processed_files = set()
file_timestamps = {}  # Словарь для хранения времени добавления файлов
EXPIRATION_TIME = 300  # Время жизни записи в секундах (например, 5 минут)

async def slack_events(event_data):
    global processed_files
    # print('\n------ REQUEST ------\n', json.dumps(request.json, indent=4))

    # Validate the request signature
    # if not signature_verifier.is_valid_request(request.get_data(), request.headers):
    #     logging.error("Invalid request signature")
    #     return jsonify({"error": "invalid request"}), 403

    if "type" in event_data and event_data["type"] == "url_verification":
        logging.error("Challenge verification accepted")
        return {"challenge": event_data["challenge"]}

    event = event_data.get("event", {})
    user_id = event.get('user')

    if user_id != BOT_ID:
        # Проверяем, если это запрос типа file_share
        if event.get('subtype') == 'file_share':
            if not check_file_id_existance(event):
                # Обрабатываем первый запрос типа file_share
                    logger(f"""-------NEW FILE MESSAGE FROM SLACK-------""")
                    logger(f"""---> {event.get('text')}""")
                    slack_message_operator_async(event)
                    return #jsonify({"status": "file sent"})
            else:
                logger('file_share request ignored')
                return #jsonify({"status": "file_share request ignored"})

        # Игнорируем все запросы типа file_change
        elif event_data['event'].get('subtype') == 'file_change':
            logger("file_change request ignored.")
            return #jsonify({"status": "file_change request ignored."})

        elif event.get('text') != None:
            logger(f"""-------NEW TEXT MESSAGE FROM SLACK-------""")
            logger(f"""---> {event.get('text')}""")
            await slack_message_operator_async(event)
            # return jsonify({"status": "ok"})
        
        else:
            return #jsonify({"status": "no text found"})
    else:
        logger('Request from this bot!')
        return #jsonify({"status": "bot text"})

#------------------------------------------
# Helper functions to send message to Discord
#------------------------------------------


async def slack_message_operator_async(event):
    from discord_bot import discord_client

    channel_id = event.get('channel')
    logger(f'channel_id: {channel_id}')
    channel_name = get_channel_name(channel_id)
    logger(f'channel_name: {channel_name}')

    if channel_id in SLACK_CHANNELS_DICT:
        logger(f'SLACK - MESSAGE FROM - #{channel_name}')
        discord_channel_id = SLACK_CHANNELS_DICT[channel_id]
        discord_channel = discord_client.get_channel(int(discord_channel_id))
    else:
        logger(f'SLACK - MESSAGE FROM OTHER CHANNEL - #{channel_name}')
        return #jsonify({"status": "channel not handled"})
        
    if 'files' in event:  # Check if the message contains files
        logger('MESSAGE WITH IMAGE')
        file_paths = await process_files_async(event)
    else:
        logger('MESSAGE WITHOUT IMAGE')
        file_paths = None

    if event.get('thread_ts'):
        logger(f'SLACK - MESSAGE IN THREAD')

        try:
            # Пытаемся получить Discord message ID по Slack message ID
            result = db.get_discord_message_id(event.get('thread_ts'))
            logger("Discord message ID was found for this Slack message.")
            send_thread_message_to_discord(event, discord_channel=discord_channel, discord_client=discord_client, file_paths=file_paths)
        except KeyError:
            # Если Slack message ID не найден, выводим сообщение об ошибке
            logger("Error: Discord message ID not found for this Slack message.")
            send_new_message_to_discord(event, discord_channel=discord_channel, slack_message_id=event.get('thread_ts'), discord_client=discord_client, file_paths=file_paths)

    elif event.get('ts'):
        logger(f'SLACK - NEW MESSAGE IN CHANNEL')
        send_new_message_to_discord(event, discord_channel=discord_channel, slack_message_id=event.get('ts'), discord_client=discord_client, file_paths=file_paths)
        
    else:
        logger('UNKNOWN MESSAGE FROM SLACK')
        return #jsonify({"status": "unknown message type"})

def logger(log_text):
    print(log_text)
    logging.info(log_text)

async def send_thread_message_to_discord_async(event, discord_channel, file_paths):
    slack_message_id = event.get('thread_ts')
    discord_message_id = db.get_discord_message_id(slack_message_id)    
    user_text, user_name = get_user_data(event)
    logger(f'Message from {user_name}')

    if discord_channel:
        # Извлекаем сообщение по его ID
        try:
            parent_message = await discord_channel.fetch_message(discord_message_id)
        except Exception as e:
            logger(f'Error: {e}')
            return
        
        if parent_message:
            user_text = format_mentions(event)
            text = f'**💂_{user_name}_**\n{user_text}'

            # Формируем часть текста из родительского сообщения для имени ветки (первые 5 слов)
            parent_text = parent_message.content
            thread_name = " ".join(parent_text.split()[:5])
            thread_name = clean_and_format_thread_name(thread_name) if thread_name else "Discussion"
            
            # Проверяем, есть ли уже ветка для этого сообщения
            if parent_message.thread:
                # Если ветка уже существует, просто отправляем сообщение в существующую ветку
                thread = parent_message.thread    
                result = await send_thread_message_operator(file_paths, text, thread)

                logger('Message sent in existing thread')
            else:
                # Создаём новую ветку, если её нет
                thread = await parent_message.create_thread(
                    name=f"{thread_name}",
                )
                result = await send_thread_message_operator(file_paths, text, thread)

                logger('Message sent in new thread')

            if result:
                logger("---> 'send_thread_message_to_discord_async' func is done")

                return #jsonify({"status":"ok"})
        else:
            logger("Message not found in Discord channel.")
    else:
        logger("Discord_channel not found.")

async def send_thread_message_operator(file_paths, text, thread):
    max_length = 2000
    logger(f'len text is {len(text)}!')

    if len(text) >= max_length:
        logger(f'Text is longer than {max_length}!')
        result = await send_thread_message_by_parts(file_paths, thread, text, max_length)
        return result
    else:
        logger(f'Text is less than {max_length}')
        if file_paths:
            logger('But the text has files')
            result = await send_thread_message_with_files(file_paths, thread, text)
            return result
        else:
            logger('And it has no files')
            result = await thread.send(text)
            return result

async def send_thread_message_by_parts(file_paths, thread, text, max_length):
    parts = split_text_by_parts(text, max_length)
    logger(f'len texts is {len(parts)}')

    for i, text in enumerate(parts):
        if i == len(parts)-1:
            if file_paths:
                logger(f'Text is longer than {max_length} and it has files!')
                result = await send_thread_message_with_files(file_paths, thread, text)
                return result
            else:
                logger(f'Text is longer than {max_length} and it has no files!')
                result = await thread.send(text)
                return result
        else:
            await thread.send(text)
            logger(f'---> Message sent:\n{text}')

async def send_thread_message_with_files(file_paths, thread, text):
    logger('Sending files in thread message')

    files = [discord.File(path, filename=os.path.basename(path)) for path in file_paths]
    result = await thread.send(text, files=files)
    delete_files(file_paths)
    return result

def get_user_data(event):
    user_id = event.get('user')
    user_text = format_mentions(event)
    user_info = sync_slack_client.users_info(user=user_id)['user']
    user_name = user_info['profile']['display_name'] or user_info['real_name']
    return user_text, user_name

async def send_new_message_to_discord_async(event, discord_channel, slack_message_id, file_paths):
    try:
        user_text, user_name = get_user_data(event)
        logger(f'Message from {user_name}')

        text = f'**💂_{user_name}_**\n{user_text}'

        if discord_channel:
            message = await send_new_message_operator(file_paths, discord_channel, text)
            logger('New message sent to discord')

            message_id = message.id
            db.save_message_to_db(slack_message_id, message_id)

            logger("---> 'send_new_message_to_discord_async' func is done")
            return #jsonify({"status":"ok"})
        
    except Exception as e:
        logger(f"Error: {e}")

async def send_new_message_operator(file_paths, discord_channel, text):
    max_length =2000
    logger(f'len text is {len(text)}')
    if len(text) >= max_length:
        logger(f'Text is longer than {max_length}!')
        result = await send_new_message_by_parts(file_paths, discord_channel, text, max_length)
        return result
    else:
        logger(f'Text is less than {max_length}')
        if file_paths:
            logger('But the text has files')
            result = await send_new_message_with_files(file_paths, discord_channel, text)
            return result 
        else:
            logger('And it has no files')
            result  = await discord_channel.send(text)
            return result 

async def send_new_message_by_parts(file_paths, discord_channel, text, max_length):
    parts = split_text_by_parts(text, max_length)
    logger(f'len texts is {len(parts)}')
    for i, text in enumerate(parts):
        if i == len(parts)-1:
            if file_paths:
                logger(f'Text is longer than {max_length} and it has files!')
                result = await send_new_message_with_files(file_paths, discord_channel, text)
                return result
            else:
                logger(f'Text is longer than {max_length} and it has no files!')
                result = await discord_channel.send(text)
                return result
        else:
            await discord_channel.send(text)
            logger(f'---> Message sent:\n{text}')

async def send_new_message_with_files(file_paths, discord_channel, text):
    logger('Sending files in new message')

    files = [discord.File(path, filename=os.path.basename(path)) for path in file_paths]
    result = await discord_channel.send(text, files=files)
    delete_files(file_paths)
    return result 

async def process_files_async(event):
    # Извлекаем файлы и текст из сообщения Slack
    file_urls = []
    files = event.get('files', [])

    # Извлекаем URL файлов
    for file in files:
        if file.get('url_private'):
            file_urls.append((file['url_private'], file['mimetype']))

    if not file_urls:
        logger("No files found in the message.")
        return None

    # Скачиваем файлы
    file_paths = await download_files(file_urls)

    if not file_paths:
        logger("No files were successfully downloaded.")
        return None
    
    return file_paths

async def download_files(file_urls):
    os.makedirs("temp_files", exist_ok=True)
    file_paths = []

    async with aiohttp.ClientSession() as session:
        for url, mimetype in file_urls:
            try:
                headers = {'Authorization': f'Bearer {SLACK_TOKEN}'}
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        # Создаем временный файл с правильным расширением
                        ext = mimetype.split('/')[-1]
                        file_name = f"temp_files/{url.split('/')[-1].split('?')[0]}"
                        if not file_name.endswith(ext):
                            file_name += f".{ext}"

                        with open(file_name, 'wb') as f:
                            f.write(await response.read())
                        file_paths.append(file_name)
                        logger(f"Downloaded file from Slack: {url}")
                    else:
                        logger(f"Failed to download file: {url}, Status: {response.status}")
            except Exception as e:
                logger(f"Error downloading file from {url}: {e}")

    return file_paths


# ----------- Helper functions  -----------
def slack_message_operator(event):
    loop = asyncio.new_event_loop()  # Create a new event loop for this thread
    asyncio.set_event_loop(loop)     # Set it as the current event loop
    loop.run_until_complete(slack_message_operator_async(event))  # Run the async function
       
def send_thread_message_to_discord(event, discord_channel, discord_client, file_paths):
    # Правильный запуск асинхронной функции с использованием event loop
    asyncio.ensure_future(send_thread_message_to_discord_async(event, discord_channel, file_paths), loop=discord_client.loop)

def send_new_message_to_discord(event, discord_channel, slack_message_id, discord_client, file_paths):
    # Правильно запускаем асинхронную функцию с использованием event loop
    asyncio.ensure_future(send_new_message_to_discord_async(event, discord_channel, slack_message_id, file_paths), loop=discord_client.loop)

def process_files(event, discord_client):
    # Правильный запуск асинхронной функции с использованием event loop
    asyncio.ensure_future(process_files_async(event), loop=discord_client.loop)

def clean_and_format_thread_name(raw_text):
   # Убираем часть с именем пользователя и любые звёздочки перед текстом
    cleaned_text = re.sub(r'\*\*💂_.*?_\\*\*\s*', '', raw_text).strip()
    # Убираем возможные звёздочки в начале строки
    cleaned_text = cleaned_text.lstrip('*').strip()
    return cleaned_text

def delete_files(file_paths):
    """Delete files after they have been used."""
    for file_path in file_paths:
        try:
            os.remove(file_path)
            logger(f"Deleted image: {file_path}")
        except Exception as e:
            logger(f"Error deleting image {file_path}: {e}")

def format_mentions(event):
    user_text = event.get('text')
    mentions = re.findall(r'<@(\w+)>', user_text)

    if mentions:  
        for mention in mentions:
            try:
                mention_info = sync_slack_client.users_info(user=mention)
                mention_name = mention_info['user']['real_name']
                user_text = user_text.replace(f'<@{mention}>', f'@{mention_name}')
            except Exception as e:
                # Логируем ошибку, если не удалось получить информацию о пользователе
                logger(f"Ошибка при получении информации для {mention}: {e}")
    else:
        logger("Упоминаний не найдено.")
    return user_text
    
def split_text_by_parts(text, max_length):
    parts = []

    while len(text) > 0:
        if len(text) <= max_length:
            parts.append(text.strip())
            break
        else:
            # Находим последнюю точку перед границей max_length
            cutoff_index = text.rfind('.', 0, max_length)
            if cutoff_index == -1:
                # Если точка не найдена, берем первые max_length символов
                cutoff_index = max_length
            else:
                # Увеличиваем индекс на 1, чтобы включить точку в часть
                cutoff_index += 1

            part = text[:cutoff_index].strip()
            parts.append(part)
            text = text[cutoff_index:].strip()

    return parts

def get_channel_name(channel_id):
    try:
        # Запрос к Slack API для получения информации о канале
        response = sync_slack_client.conversations_info(channel=channel_id)
        channel_name = response["channel"]["name"]
        return channel_name
    except SlackApiError as e:
        logger(f"Ошибка при получении информации о канале: {e.response['error']}")
        return None
    
def check_file_id_existance(event):
    global processed_files
    check_expired_files()
    new_files = False

    if 'files' in event:
        for file in event['files']:
            file_id = file.get('id')
            if file_id not in processed_files:
                add_file_to_processed(file_id)
                new_files = True
                logger('There is a new file!')
            else:
                logger('File already exists!', file_id)

        if new_files:
            logger('New files!')
            return False
        else:
            logger('No new files!')
            return True

def check_expired_files():
    """Удаляет старые записи из processed_files по разнице времени."""
    global processed_files

    current_time = time.time()
    expired_files = [file_id for file_id, timestamp in file_timestamps.items()
                        if current_time - timestamp > EXPIRATION_TIME]
    
    for file_id in expired_files:
        processed_files.remove(file_id)
        del file_timestamps[file_id]

def add_file_to_processed(file_id):
    """Добавляет ID файла в processed_files и сохраняет время добавления."""
    global processed_files

    processed_files.add(file_id)
    file_timestamps[file_id] = time.time()
