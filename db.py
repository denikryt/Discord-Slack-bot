from pymongo import MongoClient
import logging
import config

# MongoDB configuration
mongo_client = MongoClient(config.MONGO_DB)  
db = mongo_client['HACKLAB']
messages_collection = db[config.DB_COLLECTION]

def save_message_to_db(slack_message_id, discord_message_id):
    messages_collection.insert_one({
        "slack_message_id": slack_message_id,
        "discord_message_id": discord_message_id
    })
    logger(f'Message saved to database: {slack_message_id:} : {discord_message_id}')


def get_discord_message_id(slack_message_id):
    result = messages_collection.find_one({"slack_message_id": slack_message_id})
    if result:
        logger("Discord message ID have been found for this Slack message ID")
        return result['discord_message_id']
    logger("Discord message ID not found for this Slack message ID")
    raise KeyError("Discord message ID not found for this Slack message ID")

def get_slack_message_id(discord_message_id):
    result = messages_collection.find_one({"discord_message_id": discord_message_id})
    if result:
        logger("Slack message ID have been found for this Discord message ID")
        return result['slack_message_id']
    logger("Slack message ID not found for this Discord message ID")
    raise KeyError("Slack message ID not found for this Discord message ID")

def logger(log_text):
    print(log_text) 
    logging.info(log_text)