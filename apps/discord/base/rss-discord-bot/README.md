# rss-discord-bot

This app runs a lightweight Discord bot that reads RSS feeds and posts updates.

## Why the code lives in this repo
The bot code is stored directly in this infrastructure repo and delivered via a
ConfigMap so it can be deployed quickly without a separate build pipeline. This
keeps the setup simple and makes small changes easy to ship.

## Future refactor
We plan to split the bot into its own repository and build a dedicated container
image. That will make dependency management and releases cleaner as the bot
grows.
