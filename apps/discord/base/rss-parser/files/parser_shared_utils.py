import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests

DEFAULT_USER_AGENT = "rss-parser/1.0"


def fetch_html(
    url: str, timeout: int = 20, user_agent: Optional[str] = DEFAULT_USER_AGENT
) -> str:
    headers = {"User-Agent": user_agent} if user_agent else None
    resp = requests.get(url, timeout=timeout, headers=headers)
    resp.raise_for_status()
    return resp.text


def to_rfc822(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def strip_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def to_absolute(base: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(base, href)


def first_image_url(container, base_url: str) -> Optional[str]:
    if not container:
        return None
    img = container.find("img")
    if not img:
        return None
    src = img.get("src")
    if not src:
        return None
    return to_absolute(base_url, src)
