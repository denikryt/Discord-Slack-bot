from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException
from slack_bot import slack_events, handle_button_click
from discord_bot import discord_client
import logging
import os
from threading import Thread
import json
from starlette.responses import JSONResponse
from logging.handlers import RotatingFileHandler
from slack_sdk.signature import SignatureVerifier
from config import SIGNING_SECRET

# Создаём папку logs, если она не существует
os.makedirs("logs", exist_ok=True)

# Удаляем текущий файл app.log при запуске программы
log_file_path = os.path.join("logs", "app.log")
with open(log_file_path, 'w', encoding='utf-8'):
    pass  # Открываем файл в режиме записи, чтобы очистить его

# Настраиваем ротацию логовпше
rotating_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=10 * 1024 * 1024, 
    backupCount=5,  # Количество резервных копий логов
    encoding='utf-8'
)

# Настраиваем формат логов
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
rotating_handler.setFormatter(formatter)

# Настраиваем корневой логгер
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(rotating_handler)

app = FastAPI()
signature_verifier = SignatureVerifier(signing_secret=SIGNING_SECRET)

def format_json(data):
    try:
        parsed = json.loads(data)
        return json.dumps(parsed, indent=4, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return data  

@app.middleware("http")
async def log_requests(request: Request, call_next):
    from slack_bot import BOT_ID

    body = await request.body()
    try:
        event_data = json.loads(body)
        # Проверка на наличие bot_id, чтобы не логировать запросы от бота
        if event_data.get('event', {}).get('bot_id') == BOT_ID:
            response = await call_next(request)
            return response
    except (json.JSONDecodeError, TypeError
            ):
        pass  

    formatted_body = format_json(body) if body else "No body"
    logger.info(f"Incoming request: {request.method} {request.url} - Body: {formatted_body}")
    
    response = await call_next(request)
    
    logger.info(f"Outgoing response: Status code {response.status_code}")
    
    return response

@app.get('/')
async def home():
    logger.info("Home endpoint accessed")
    return 'Both bots are running'

@app.post('/slack/button')
async def button_click(
    request: Request,
    background_tasks: BackgroundTasks,
):
    form_data = await request.form()  
    payload = form_data.get('payload')  
    payload = json.loads(payload)
    # result, status_code = await handle_button_click(payload)
    
    background_tasks.add_task(handle_button_click, payload)
    logger.info("***Slack event processing started in the background")
    
    return JSONResponse(content={}, status_code=200)

@app.post('/slack/events')
async def slack_events_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
):
    from slack_bot import BOT_ID

    # Проверка подписи Slack для безопасности
    body = await request.body()
    if not signature_verifier.is_valid_request(body.decode('utf-8'), {'X-Slack-Signature': x_slack_signature, 'X-Slack-Request-Timestamp': x_slack_request_timestamp}):
        logger.error("Invalid Slack signature")
        raise HTTPException(status_code=400, detail="Invalid request signature")

    # logger.info(f'BOT_ID: {BOT_ID}')
    event_data = await request.json()
    # logger.info(f'SLACK REQUEST:\n{event_data}')

    # Проверка типа запроса на url_verification
    if event_data.get('type') == 'url_verification':
        logger.info("URL verification request received")
        return {"challenge": event_data.get('challenge')}

    # Проверка на наличие bot_id, чтобы игнорировать события от ботов
    if 'event' in event_data: 
        if 'bot_id' in event_data['event'] and event_data['event'].get('user') == BOT_ID:
            logger.info("***Ignoring request from this bot")
            return JSONResponse(content={"status": "ignored"}, status_code=200)
        else:
            background_tasks.add_task(slack_events, event_data)
            logger.info("***Slack event processing started in the background")
            return JSONResponse(content={"status": "ok"}, status_code=200)
            
    else:
        logger.info("***Unexpected request structure")
        return JSONResponse(content={"status": "ignored"}, status_code=200)

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
