import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from pathlib import Path
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
import logging

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)

SLACK_CHANNEL_ID_TEST = os.environ.get('SLACK_CHANNEL_ID_TEST')
SIGNING_SECRET = os.environ.get('SIGNING_SECRET')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')

slack_client = WebClient(token=SLACK_TOKEN)
signature_verifier = SignatureVerifier(signing_secret=SIGNING_SECRET)
BOT_ID = slack_client.auth_test()['user_id']

@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json

    # Сначала проверяем, если это событие url_verification
    if data.get('type') == 'url_verification':
        return jsonify({'challenge': data.get('challenge')}), 200

    # Validate the request signature
    if not signature_verifier.is_valid_request(request.get_data(), request.headers):
        return jsonify({"error": "invalid request"}), 403
    
    if 'event' in data:
        event = data['event']
        channel_id = event.get('channel')
        user_id = event.get('user')
        text = event.get('text')

        if user_id and user_id != BOT_ID and channel_id == SLACK_CHANNEL_ID_TEST:
            try:
                slack_client.chat_postMessage(channel=channel_id, text=text)
            except SlackApiError as e:
                logging.error(f"Error posting message: {e.response['error']}")

    return jsonify({'status': 'ok'}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)
