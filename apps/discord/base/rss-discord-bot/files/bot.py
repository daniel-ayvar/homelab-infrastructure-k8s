import asyncio
import logging
from typing import List

import discord

from config import load_config
from rss import compile_filters, fetch_entries, format_message, normalize_entries, should_mention
from state import load_state, save_state

logger = logging.getLogger("rss-discord-bot")


def _entry_ids(entries: List[tuple]) -> List[str]:
    return [entry_id for entry_id, _ in entries]


class RssDiscordBot:
    def __init__(self, client: discord.Client):
        self.client = client
        self.state = load_state()
        self.lock = asyncio.Lock()

    async def _post_updates(self, channel_id: str, role_id: str, feed: dict):
        feed_url = feed["rss_feed_url"]
        filter_regex = feed.get("filter_regex")
        compiled = compile_filters(filter_regex)
        entries = await asyncio.to_thread(fetch_entries, feed_url)
        if not entries:
            return
        normalized_entries = normalize_entries(entries)
        if not normalized_entries:
            return
        async with self.lock:
            seen_list = self.state.get(feed_url, [])
            seen = set(seen_list)
            if feed_url not in self.state:
                self.state[feed_url] = _entry_ids(normalized_entries)[:200]
                save_state(self.state)
                logger.info("seeded state for %s with %d entries", feed_url, len(normalized_entries))
                return
            new_entries = [
                (entry_id, entry)
                for entry_id, entry in normalized_entries
                if entry_id not in seen
            ]
            if not new_entries:
                return
            channel = self.client.get_channel(int(channel_id))
            if channel is None:
                logger.warning("channel %s not found", channel_id)
                return
            new_entries.reverse()
            for entry_id, entry in new_entries:
                mention = should_mention(entry, compiled)
                payload = format_message(role_id, entry, mention)
                embed = discord.Embed(
                    title=payload["title"],
                    url=payload["link"] or None,
                    description=payload["summary"] or None,
                    color=discord.Color.blue() if mention else discord.Embed.Empty,
                )
                if payload.get("author"):
                    embed.set_author(name=payload["author"])
                if payload.get("published"):
                    embed.timestamp = payload["published"]
                if payload["image_url"]:
                    embed.set_thumbnail(url=payload["image_url"])
                await channel.send(payload["content"], embed=embed)
                seen_list.append(entry_id)
            self.state[feed_url] = seen_list[-200:]
            save_state(self.state)

    async def run_loop(self, poll_seconds: int):
        while True:
            try:
                config = load_config()
            except Exception:
                logger.exception("failed to load config")
                await asyncio.sleep(poll_seconds)
                continue
            subscriptions = config.get("subscriptions", [])
            if not subscriptions:
                await asyncio.sleep(poll_seconds)
                continue
            for subscription in subscriptions:
                try:
                    channel_id = subscription["channel_id"]
                    role_id = subscription.get("role_id", "")
                    for feed in subscription.get("feeds", []):
                        await self._post_updates(channel_id, role_id, feed)
                except Exception:
                    logger.exception("failed processing feed %s", subscription)
            await asyncio.sleep(poll_seconds)
