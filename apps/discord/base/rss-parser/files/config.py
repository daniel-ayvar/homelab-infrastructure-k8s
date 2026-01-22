import os
from typing import Dict

import yaml

CONFIG_PATH = os.getenv("RSS_PARSER_CONFIG_PATH", "/app/config.yaml")
SITE_DEFAULTS = {
    "pokemon-zone": "https://www.pokemon-zone.com",
    "hytale": "https://hytale.com",
    "dokkaninfo": "https://dokkaninfo.com",
}
PORT_DEFAULTS = {
    "pokemon-zone": 8081,
    "hytale": 8082,
    "dokkaninfo": 8083,
}


def load_config() -> Dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise RuntimeError("config must be a mapping")
    feeds = data.get("feeds", [])
    if not isinstance(feeds, list):
        raise RuntimeError("feeds must be a list")
    cleaned = []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        name = str(feed.get("name", "")).strip()
        site = str(feed.get("site", "")).strip()
        port = int(feed.get("port", 0) or 0)
        parser_entry = feed.get("parser")
        if parser_entry is None:
            parser_entry = feed.get("parsers", [])
        if not parser_entry:
            parser_entry = {"name": f"{name}-news", "type": name}
        if isinstance(parser_entry, dict):
            parsers = [parser_entry]
        else:
            parsers = parser_entry
        if not name or not isinstance(parsers, list):
            continue
        if port <= 0:
            continue
        cleaned_parsers = []
        parser_types = []
        for parser in parsers:
            if not isinstance(parser, dict):
                continue
            parser_name = str(parser.get("name", "")).strip()
            parser_type = str(parser.get("type", "placeholder")).strip()
            if not parser_name:
                continue
            cleaned_parser = dict(parser)
            cleaned_parser["name"] = parser_name
            cleaned_parser["type"] = parser_type or "placeholder"
            cleaned_parsers.append(cleaned_parser)
            parser_types.append(cleaned_parser["type"])
        if not cleaned_parsers:
            continue
        if len(cleaned_parsers) > 1:
            cleaned_parsers = [cleaned_parsers[0]]
            parser_types = [parser_types[0]]
        if not site:
            inferred = {SITE_DEFAULTS.get(p_type, "") for p_type in parser_types}
            inferred.discard("")
            if len(inferred) == 1:
                site = inferred.pop()
        if not site:
            site = SITE_DEFAULTS.get(name, "")
        if not site:
            continue
        cleaned.append(
            {
                "name": name,
                "site": site,
                "port": port,
                "parsers": cleaned_parsers,
            }
        )
    return {"feeds": cleaned}
