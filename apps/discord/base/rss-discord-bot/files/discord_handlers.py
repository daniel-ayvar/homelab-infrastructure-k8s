import logging

import discord

from config import load_config

logger = logging.getLogger("rss-discord-bot")


async def handle_role_command(message):
    if message.author.bot:
        return
    if message.guild is None:
        return
    content = message.content.strip()
    if not content.lower().startswith("!role"):
        return
    parts = content.split()
    if len(parts) < 2 or parts[1].lower() not in {"subscribe", "unsubscribe"}:
        await message.channel.send("Usage: `!role subscribe` or `!role unsubscribe`.")
        return
    try:
        config = load_config()
    except Exception:
        logger.exception("failed to load config for role command")
        await message.channel.send("Bot config error. Try again later.")
        return
    channel_id = str(message.channel.id)
    role_id = ""
    for sub in config.get("subscriptions", []):
        if sub.get("channel_id") == channel_id:
            role_id = str(sub.get("role_id", "")).strip()
            break
    if not role_id:
        await message.channel.send("No role configured for this channel.")
        return
    role = message.guild.get_role(int(role_id))
    if role is None:
        await message.channel.send("Role not found in this server.")
        return
    member = message.author
    if not isinstance(member, discord.Member):
        await message.channel.send("Member information not available.")
        return
    try:
        if parts[1].lower() == "subscribe":
            await member.add_roles(role, reason="rss-discord-bot subscribe")
            await message.channel.send(f"Subscribed to <@&{role_id}> updates.")
        else:
            await member.remove_roles(role, reason="rss-discord-bot unsubscribe")
            await message.channel.send(f"Unsubscribed from <@&{role_id}> updates.")
    except Exception:
        logger.exception("failed to update role for %s", member.id)
        await message.channel.send("Could not update your role. Check bot permissions.")
