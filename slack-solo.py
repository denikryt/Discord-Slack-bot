import slack
import os
from flask import Flask
from slackeventsapi import SlackEventAdapter
from dotenv import load_dotenv
from pathlib import Path

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(os.environ['SIGNING_SECRET'], '/slack/events', app)

slack_client = slack.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = slack_client.api_call("auth.test")['user_id']

@slack_event_adapter.on('message')
def message(payload):
    event = payload.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')

    print('channel_id', channel_id)

    if user_id != BOT_ID:
        slack_client.chat_postMessage(channel=channel_id, text=text) 

if __name__ == "__main__":
    app.run(debug=True)