from pymongo import MongoClient
from config import MONGO_DB
import logging

# MongoDB configuration
mongo_client = MongoClient(MONGO_DB)  
db = mongo_client['HACKLAB']
messages_collection = db['Slack-Discord messages']

def save_message_to_db(slack_message_id, discord_message_id):
    messages_collection.insert_one({
        "slack_message_id": slack_message_id,
        "discord_message_id": discord_message_id
    })
    logger(f'Message saved to database: {slack_message_id:} : {discord_message_id}')


def get_discord_message_id(slack_message_id):
    result = messages_collection.find_one({"slack_message_id": slack_message_id})
    if result:
        return result['discord_message_id']
    logger("Discord message ID not found for this Slack message ID")
    raise KeyError("Discord message ID not found for this Slack message ID")

def logger(log_text):
    print(log_text)
    logging.info(log_text)