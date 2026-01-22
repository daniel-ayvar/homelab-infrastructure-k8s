import asyncio
import logging
import os
import sys

import discord

from bot import RssDiscordBot
from discord_handlers import handle_role_command

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rss-discord-bot")


def _get_env(name, default=None):
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


POLL_SECONDS = int(os.getenv("RSS_POLL_SECONDS", "300"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)
bot = RssDiscordBot(client)


@client.event
async def on_ready():
    logger.info("discord bot ready: %s", client.user)
    client.loop.create_task(bot.run_loop(POLL_SECONDS))


@client.event
async def on_message(message):
    await handle_role_command(message)


async def main():
    token = _get_env("DISCORD_TOKEN")
    async with client:
        await client.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("shutdown requested")
