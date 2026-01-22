from datetime import datetime, timezone


def build_items(feed: dict, parser: dict):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    title = f"{feed['name']} parser: {parser['name']}"
    link = feed.get("site", "")
    guid = f"{feed['name']}:{parser['name']}"
    return [
        {
            "title": title,
            "link": link,
            "guid": guid,
            "pubDate": now,
            "description": f"Placeholder item for parser type {parser.get('type')}.",
        }
    ]
