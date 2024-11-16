from fastapi import FastAPI, Request, BackgroundTasks
from slack_bot import slack_events
from discord_bot import discord_client
import logging
import os
from threading import Thread
import json

# Очистка содержимого файла app.log при запуске программы
with open('app.log', 'w', encoding='utf-8'):
    pass  # Открываем файл в режиме записи, чтобы очистить его

logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8',
)
logger = logging.getLogger(__name__)

app = FastAPI()


def format_json(data):
    try:
        parsed = json.loads(data)
        return json.dumps(parsed, indent=4, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return data  # Если не JSON, вернуть как есть

@app.middleware("http")
async def log_requests(request: Request, call_next):
    body = await request.body()
    try:
        event_data = json.loads(body)
        # Проверка на наличие bot_id, чтобы не логировать запросы от бота
        if event_data.get('event', {}).get('bot_id'):
            response = await call_next(request)
            return response
    except (json.JSONDecodeError, TypeError):
        pass  # Если тело не является JSON, продолжаем обработку как есть

    formatted_body = format_json(body) if body else "No body"
    logger.info(f"Incoming request: {request.method} {request.url} - Body: {formatted_body}")
    
    response = await call_next(request)
    
    logger.info(f"Outgoing response: Status code {response.status_code}")
    
    return response


@app.get('/')
async def home():
    logger.info("Home endpoint accessed")
    return 'Both bots are running'

@app.post('/slack/events')
async def slack_events_handler(request: Request, background_tasks: BackgroundTasks):
    event_data = await request.json()

    # Проверка на наличие bot_id, чтобы игнорировать события от ботов
    if 'event' in event_data and 'bot_id' in event_data['event']:
        logger.info("Ignoring request from a bot")
        return {"status": "ignored"}

    background_tasks.add_task(slack_events, event_data)
    logger.info("Slack event processing started in the background")
    
    print('RETURN')
    return {"status": "processing"}


# # Очередь для запросов от Slack
# slack_queue = asyncio.Queue()
# # Блокировка для синхронизации
# slack_lock = asyncio.Lock()

# @app.post('/slack/events')
# async def slack_events_handler(request: Request, background_tasks: BackgroundTasks):
#     event_data = await request.json()

#     # Добавляем запрос в очередь
#     await slack_queue.put(event_data)
#     logger.info("Slack event added to the queue for processing")

#     # Немедленно отправляем ответ
#     return {"status": "queued for processing"}

# # Функция для обработки запросов от Slack
# async def process_slack_events():
#     while True:
#         event_data = await slack_queue.get()
#         try:
#             async with slack_lock:
#                 logger.info(f"Processing Slack event: {json.dumps(event_data, ensure_ascii=False)}")
#                 await slack_events(event_data)
#                 logger.info("Slack event processing completed")
#         except Exception as e:
#             logger.error(f"Error processing Slack event: {e}")
#         finally:
#             slack_queue.task_done()
#         time.sleep(5)


# Запуск сервера FastAPI в отдельном потоке
def run():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

def keep_alive():
    t = Thread(target=run)
    t.start()

if __name__ == '__main__':
    keep_alive()
    discord_client.run(os.environ['TOKEN_DISCORD'])
