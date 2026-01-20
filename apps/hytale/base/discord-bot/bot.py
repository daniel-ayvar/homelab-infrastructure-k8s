import asyncio
import os

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
    print(f"discord bot ready: {client.user}")


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
        await message.channel.send("No command provided.")
        return
    async with aiohttp.ClientSession() as session:
        status, text = await _post_command(session, command)
    if status != 200:
        await message.channel.send(f"Bridge error ({status}): {text or 'no body'}")
        return
    await message.channel.send("Command sent.")


async def main():
    async with client:
        await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
