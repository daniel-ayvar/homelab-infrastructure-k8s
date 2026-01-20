import asyncio
import logging
import os
import sys

import aiohttp
import discord


def _get_env(name, default=None):
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


TOKEN = _get_env("DISCORD_TOKEN")
CHANNEL_ID = int(_get_env("DISCORD_CHANNEL_ID"))
AUTHOR_ID = int(_get_env("DISCORD_AUTHOR_ID"))
PREFIX = os.getenv("COMMAND_PREFIX", "!hytale")
BRIDGE_URL = _get_env("BRIDGE_URL")
BRIDGE_TOKEN = _get_env("BRIDGE_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
discord.utils.setup_logging(handler=logging.StreamHandler(sys.stdout), level=logging.INFO)
logger = logging.getLogger("hytale-discord-bot")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


async def _post_command(session, command):
    headers = {"X-Auth-Token": BRIDGE_TOKEN}
    async with session.post(BRIDGE_URL, data=command.encode("utf-8"), headers=headers) as resp:
        text = await resp.text()
        return resp.status, text.strip()


@client.event
async def on_ready():
    logger.info("discord bot ready: %s", client.user)


@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_ID:
        return
    if message.author.id != AUTHOR_ID:
        return
    content = message.content.strip()
    if not content.startswith(PREFIX):
        return
    command = content[len(PREFIX):].strip()
    if not command:
        logger.warning("command rejected: empty")
        await message.channel.send("No command provided.")
        return
    if command.lower() in {"status", "ping"}:
        logger.info("status check requested by author=%s", message.author.id)
        await message.channel.send("Bot is online.")
        return
    logger.info(
        "command received: channel=%s author=%s command=%r",
        message.channel.id,
        message.author.id,
        command,
    )
    async with aiohttp.ClientSession() as session:
        status, text = await _post_command(session, command)
    if status != 200:
        logger.error("bridge error: status=%s body=%r", status, text)
        await message.channel.send(f"Bridge error ({status}): {text or 'no body'}")
        return
    logger.info("command sent successfully")
    await message.channel.send("Command sent.")


@client.event
async def on_error(event, *args, **kwargs):
    logger.exception("discord event error: %s", event)


async def main():
    logger.info("startup config: channel=%s author=%s prefix=%r bridge_url=%r", CHANNEL_ID, AUTHOR_ID, PREFIX, BRIDGE_URL)
    async with client:
        try:
            await client.start(TOKEN)
        except Exception:
            logger.exception("client.start failed")
            raise


if __name__ == "__main__":
    asyncio.run(main())
