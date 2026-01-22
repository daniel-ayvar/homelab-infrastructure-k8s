import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import feedparser

logger = logging.getLogger("rss-discord-bot")

def fetch_entries(url: str):
    parsed = feedparser.parse(url)
    return parsed.entries or []


def entry_id(entry) -> str:
    return str(
        entry.get("guid")
        or entry.get("id")
        or entry.get("link")
        or entry.get("title")
    )


def compile_filters(filter_regex):
    if not filter_regex:
        return []
    patterns = filter_regex if isinstance(filter_regex, list) else [filter_regex]
    compiled = []
    for pattern in patterns:
        if not pattern:
            continue
        try:
            compiled.append(re.compile(str(pattern), re.IGNORECASE))
        except re.error:
            logger.warning("invalid regex: %s", pattern)
    return compiled


def normalize_entries(entries) -> List[Tuple[str, object]]:
    normalized = []
    for entry in entries:
        entry_key = entry_id(entry)
        if not entry_key:
            continue
        normalized.append((entry_key, entry))
    return normalized


def should_mention(entry, compiled_filters) -> bool:
    if not compiled_filters:
        return False
    haystack = " ".join(
        [
            str(entry.get("title", "") or ""),
            str(entry.get("summary", "") or ""),
            str(entry.get("description", "") or ""),
        ]
    )
    return any(pattern.search(haystack) for pattern in compiled_filters)


def extract_image_url(entry) -> Optional[str]:
    enclosures = entry.get("enclosures") or []
    for enclosure in enclosures:
        url = enclosure.get("href") or enclosure.get("url")
        if url:
            return url
    media = entry.get("media_content") or []
    for item in media:
        url = item.get("url")
        if url:
            return url
    return None


def format_message(role_id: str, entry, mention: bool) -> dict:
    title = entry.get("title", "(untitled)").strip()
    link = entry.get("link", "").strip()
    role = f"<@&{role_id}> " if role_id and mention else ""
    summary = (entry.get("summary") or entry.get("description") or "").strip()
    author = (entry.get("author") or "").strip()
    published = None
    published_parsed = entry.get("published_parsed")
    updated_parsed = entry.get("updated_parsed")
    if published_parsed:
        published = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    elif updated_parsed:
        published = datetime(*updated_parsed[:6], tzinfo=timezone.utc)
    command_hint = ""
    if role:
        command_hint = "\n\nToggle your mention:\n```\n!role subscribe\n!role unsubscribe\n```"
    message = f"{role}{command_hint}"
    return {
        "title": f"News: {title}",
        "link": link,
        "summary": summary,
        "content": message,
        "image_url": extract_image_url(entry),
        "author": author or None,
        "published": published,
    }
