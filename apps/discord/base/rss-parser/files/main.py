import json
import logging
import os
import sys
import time

from config import load_config
from http_server import start_servers

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rss-parser")

RELOAD_SECONDS = int(os.getenv("RSS_PARSER_RELOAD_SECONDS", "300"))


def main():
    servers = []
    current_signature = ""
    while True:
        try:
            config = load_config()
        except Exception:
            logger.exception("failed to load config")
            time.sleep(RELOAD_SECONDS)
            continue
        feeds = config.get("feeds", [])
        signature = json.dumps(feeds, sort_keys=True)
        if signature != current_signature:
            for server, _thread in servers:
                server.shutdown()
            servers = start_servers(feeds)
            current_signature = signature
            logger.info("started %d feed servers", len(servers))
        time.sleep(RELOAD_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("shutdown requested")
