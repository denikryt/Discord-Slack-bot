from discord import Intents, Client, Message,Forbidden
from discord.ext import commands
import webserver
import os


intents: Intents = Intents.default()
intents.message_content = True 
client: Client = Client(intents=intents)
bot = commands.Bot(command_prefix='!', intents=intents)


@client.event
async def on_ready() -> None:
    print(f'{client.user} is now running!')

@client.event
async def on_message(message: Message) -> None:
    if message.author == client.user:
        return
    
    if message.channel.id == int(os.environ['DISCORD_TEST_CHANNEL_ID']):    

        username: str = str(message.author)
        user_message: str = str(message.content)
        channel: str = str(message.channel)

        await message.channel.send(user_message)

        print(f'[{channel}] {username}: "{user_message}"')


webserver.keep_alive()
client.run(token=os.environ['TOKEN_DISCORD'])