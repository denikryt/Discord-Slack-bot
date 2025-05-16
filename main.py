from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException
from slack_bot import slack_events, handle_button_click, set_last_message_user_id
from discord_bot import discord_client
import logging
import os
from threading import Thread
import json
from starlette.responses import JSONResponse
from logging.handlers import RotatingFileHandler
from slack_sdk.signature import SignatureVerifier
from config import SIGNING_SECRET
import config

# Create the logs folder if it does not exist
os.makedirs("logs", exist_ok=True)

# Remove the current app.log file when the program starts
log_file_path = os.path.join("logs", "app.log")
with open(log_file_path, 'w', encoding='utf-8'):
    pass 

# Set up log rotation
rotating_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=10 * 1024 * 1024,
    backupCount=5, # Number of backup log files
    encoding='utf-8'
)

# Set up log formatting
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
rotating_handler.setFormatter(formatter)

# Set up the root logger
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
    body = await request.body()
    try:
        event_data = json.loads(body)
        # Check for the presence of bot_id to avoid logging requests from the bot
        if event_data.get('event', {}).get('bot_id') == config.SLACK_BOT_ID:
            response = await call_next(request)
            return response
    except (json.JSONDecodeError, TypeError):
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
    event_data = await request.json()
    body = await request.body()
    event = event_data.get("event", {})
    user_id=event.get('user')

    # Check if the request is a URL verification request
    if not signature_verifier.is_valid_request(body.decode('utf-8'), {'X-Slack-Signature': x_slack_signature, 'X-Slack-Request-Timestamp': x_slack_request_timestamp}):
        logger.error("Invalid Slack signature")
        raise HTTPException(status_code=400, detail="Invalid request signature")    
    
    # Handle Slack URL verification in a more concise way
    if event_data.get('type') == 'url_verification':
        logger.info("URL verification request received")
        return JSONResponse(content={"challenge": event_data.get('challenge')}, status_code=200)

    # Log the incoming event data
    if 'event' in event_data:
        # Check if the event is a bot message
        if 'bot_id' in event_data['event'] and event_data['event'].get('user') == config.SLACK_BOT_ID:
            # Ignore the request from this bot but save the last message user ID
            
            if event.get('thread_ts'):
                # If the event is a thread message, use thread_ts as channel_id
                channel_id = event.get('thread_ts')
            else:
                channel_id = event.get('channel')

            background_tasks.add_task(set_last_message_user_id, user_id, channel_id)

            print("***Ignoring request from this bot")
            return JSONResponse(content={"status": "ignored"}, status_code=200)
        else:
            # Else, process the event
            background_tasks.add_task(slack_events, event_data)
            logger.info("***Slack event processing started in the background")
            return JSONResponse(content={"status": "ok"}, status_code=200)
    else:
        logger.info("***Unexpected request structure")
        return JSONResponse(content={"status": "ignored"}, status_code=200)

# Run the FastAPI server in a separate thread
def run():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

def keep_alive():
    t = Thread(target=run)
    t.start()

if __name__ == '__main__':
    keep_alive()
    discord_client.run(os.environ['TOKEN_DISCORD'])
