import os
from typing import Dict

import yaml


def _get_env(name, default=None):
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


CONFIG_PATH = _get_env("RSS_CONFIG_PATH", "/app/config.yaml")


def load_config() -> Dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise RuntimeError("config must be a mapping")
    subscriptions = data.get("subscriptions", [])
    if not isinstance(subscriptions, list):
        raise RuntimeError("subscriptions must be a list")
    cleaned = []
    for item in subscriptions:
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("channel_id", "")).strip()
        role_id = str(item.get("role_id", "")).strip()
        feeds = item.get("feeds", [])
        if not channel_id or not isinstance(feeds, list):
            continue
        cleaned_feeds = []
        for feed in feeds:
            if not isinstance(feed, dict):
                continue
            rss_feed_url = str(feed.get("rss_feed_url", "")).strip()
            if not rss_feed_url:
                continue
            filter_regex = feed.get("filter_regex")
            if isinstance(filter_regex, list):
                filter_regex = [
                    str(item).strip()
                    for item in filter_regex
                    if str(item).strip()
                ]
            elif isinstance(filter_regex, str):
                filter_regex = filter_regex.strip() or None
            elif filter_regex is not None:
                filter_regex = str(filter_regex).strip() or None
            cleaned_feeds.append(
                {"rss_feed_url": rss_feed_url, "filter_regex": filter_regex}
            )
        if not cleaned_feeds:
            continue
        cleaned.append(
            {
                "channel_id": channel_id,
                "role_id": role_id,
                "feeds": cleaned_feeds,
            }
        )
    return {"subscriptions": cleaned}
