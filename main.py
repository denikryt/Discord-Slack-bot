from fastapi import FastAPI, Request, BackgroundTasks
from slack_bot import slack_events
from discord_bot import discord_client
import logging
import os
import json
import asyncio
from threading import Thread
from starlette.responses import StreamingResponse

# Настройка основного логгера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("app.log", mode='w', encoding="utf-8")]
)

# Настройка логгера для HTTP-запросов
http_logger = logging.getLogger("http_logger")
http_handler = logging.FileHandler("http_requests.log", mode='w', encoding="utf-8")
http_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
http_logger.addHandler(http_handler)
http_logger.setLevel(logging.INFO)

app = FastAPI()

async def format_json(data):
    """Функция для форматирования JSON данных с отступами."""
    try:
        parsed = json.loads(data)
        return json.dumps(parsed, indent=4, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return data  # Если данные не являются JSON, возвращаем как есть

@app.middleware("http")
async def log_request(request: Request, call_next):
    body = await request.body()
    formatted_body = await format_json(body) if body else "No body"
    headers = json.dumps(dict(request.headers), indent=4, ensure_ascii=False)

    http_logger.info(
        f"Incoming request:\n"
        f"Method: {request.method}\n"
        f"URL: {request.url}\n"
        f"Headers:\n{headers}\n"
        f"Body:\n{formatted_body}"
    )
    
    response = await call_next(request)
    
    # Check if the response is a StreamingResponse
    if isinstance(response, StreamingResponse):
        # For StreamingResponse, do not attempt to access the body, as it is streamed
        formatted_response = "Streaming response, no body"
    else:
        # For non-streaming responses, try to access the body
        try:
            formatted_response = await format_json(await response.body())
        except Exception as e:
            formatted_response = f"Error formatting response body: {str(e)}"

    headers = json.dumps(dict(response.headers), indent=4, ensure_ascii=False)

    http_logger.info(
        f"Outgoing response:\n"
        f"Status: {response.status_code}\n"
        f"Headers:\n{headers}\n"
        f"Body:\n{formatted_response}"
    )
    
    return response



@app.get('/')
async def home():
    return 'Both bots are running'

@app.post('/slack/events')
async def slack_events_handler(request: Request, background_tasks: BackgroundTasks):
    event_data = await request.json()

    # Немедленно отправляем ответ, пока продолжаем обработку в фоновом режиме
    background_tasks.add_task(slack_events, event_data)

    return {"status": "processing"}

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
