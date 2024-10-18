import slack
import os
from flask import Flask
from slackeventsapi import SlackEventAdapter
from dotenv import load_dotenv
from pathlib import Path

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)

SLACK_CHANNEL_ID_TEST = os.environ.get('SLACK_CHANNEL_ID_TEST')

print('SIGNING_SECRET', os.environ['SIGNING_SECRET'])
print('SLACK_TOKEN', os.environ['SLACK_TOKEN'])

slack_event_adapter = SlackEventAdapter(os.environ.get('SIGNING_SECRET'), '/slack/events', app)
slack_client = slack.WebClient(token=os.environ.get('SLACK_TOKEN'))
BOT_ID = slack_client.api_call("auth.test")['user_id']

# slack_client.chat_postMessage(channel='#test-bots', text='💂*_choikak_* 🔉*_#random_*')
 
@slack_event_adapter.on('message')
def message(payload):
    event = payload.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')
    # thread_ts = event.get('thread_ts') or event.get('ts')
    # channel_id = event.get('channel')

    if user_id != BOT_ID:
        if channel_id == SLACK_CHANNEL_ID_TEST:
            slack_client.chat_postMessage(channel=channel_id, text=text) 
            return
    else:
        pass
        # print('!---------------!')
        # print('BOT-EVENT', event)
        # print('---------------')

    # if user_id != BOT_ID:
    #     slack_client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts) 

if __name__ == "__main__":
    app.run(debug=True, port=5000)