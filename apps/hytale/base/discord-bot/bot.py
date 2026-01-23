import asyncio
import json
import logging
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import discord
import kubernetes.client as k8s_client
import kubernetes.config as k8s_config


def _get_env(name, default=None):
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


TOKEN = _get_env("DISCORD_TOKEN")
CHANNEL_ID = int(_get_env("DISCORD_CHANNEL_ID"))
AUTHOR_ID = int(_get_env("DISCORD_AUTHOR_ID"))
PREFIX = os.getenv("COMMAND_PREFIX", "!hytale")
SERVER_URL = "hytale.danielayvar.com"
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hytale")
K8S_API = "https://kubernetes.default.svc"
K8S_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
K8S_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
SERVER_LABEL = "app=hytale-server"
STATEFULSET_NAME = "hytale-server"
PLAYER_LOG_LINES = 5000
STATUS_UPDATE_SECONDS = int(os.getenv("STATUS_UPDATE_SECONDS", "60"))
LOG_LINES_DEFAULT = 10
LOG_LINES_MAX = 200
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PLAYER_JOIN_PATTERNS = [
    re.compile(r"Player\s+(.+?)\s+joined", re.IGNORECASE),
    re.compile(r"(.+?)\s+joined the game", re.IGNORECASE),
    re.compile(r"Player\s+(.+?)\s+connected", re.IGNORECASE),
    re.compile(r"User\s+(.+?)\s+connected", re.IGNORECASE),
    re.compile(r"Player\s+'(.+?)'\s+joined world", re.IGNORECASE),
    re.compile(r"Adding player\s+'(.+?)'\s+to world", re.IGNORECASE),
]
PLAYER_LEAVE_PATTERNS = [
    re.compile(r"Player\s+(.+?)\s+left", re.IGNORECASE),
    re.compile(r"(.+?)\s+left the game", re.IGNORECASE),
    re.compile(r"Player\s+(.+?)\s+disconnected", re.IGNORECASE),
    re.compile(r"User\s+(.+?)\s+disconnected", re.IGNORECASE),
    re.compile(r"-\s+(.+?)\s+at .* left with reason", re.IGNORECASE),
    re.compile(r"Removing player\s+'(.+?)'", re.IGNORECASE),
]

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
discord.utils.setup_logging(handler=logging.StreamHandler(sys.stdout), level=logging.INFO)
logger = logging.getLogger("hytale-discord-bot")

intents = discord.Intents.default()
intents.message_content = True

discord_client = discord.Client(intents=intents)
presence_task = None
player_state = {}
player_last_ts = None
player_lock = asyncio.Lock()


def _load_k8s_token():
    try:
        with open(K8S_TOKEN_PATH, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""


def _fetch_pod_status():
    token = _load_k8s_token()
    if not token:
        return None, "missing service account token"
    data, error = _k8s_get(
        f"/api/v1/namespaces/{K8S_NAMESPACE}/pods?labelSelector="
        f"{urllib.parse.quote(SERVER_LABEL, safe='')}"
    )
    if error:
        return None, error
    items = data.get("items", [])
    if not items:
        return False, "no pods found"
    for item in items:
        conditions = item.get("status", {}).get("conditions", [])
        ready = any(
            cond.get("type") == "Ready" and cond.get("status") == "True"
            for cond in conditions
        )
        if ready:
            name = item.get("metadata", {}).get("name", "unknown")
            node = item.get("spec", {}).get("nodeName", "unknown")
            return True, f"ready (pod {name} on {node})"
    phase = items[0].get("status", {}).get("phase", "unknown")
    name = items[0].get("metadata", {}).get("name", "unknown")
    return False, f"not ready (pod {name}, phase {phase})"


def _k8s_request(method, path, body=None, headers=None):
    token = _load_k8s_token()
    if not token:
        return None, "missing service account token"
    url = f"{K8S_API}{path}"
    base_headers = {"Authorization": f"Bearer {token}"}
    if headers:
        base_headers.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        base_headers.setdefault("Content-Type", "application/json")
    context = ssl.create_default_context(cafile=K8S_CA_PATH)
    req = urllib.request.Request(url, data=data, headers=base_headers, method=method)
    try:
        with urllib.request.urlopen(req, context=context, timeout=8) as resp:
            raw = resp.read()
            if not raw:
                return {}, None
            return json.loads(raw.decode("utf-8")), None
    except Exception as exc:
        return None, f"request failed: {exc}"


def _k8s_get(path):
    return _k8s_request("GET", path)


def _get_first_pod():
    data, error = _k8s_get(
        f"/api/v1/namespaces/{K8S_NAMESPACE}/pods?labelSelector="
        f"{urllib.parse.quote(SERVER_LABEL, safe='')}"
    )
    if error:
        return None, error
    items = data.get("items", [])
    if not items:
        return None, "no pods found"
    return items[0], None


def _fetch_last_logs(lines=10):
    pod, error = _get_first_pod()
    if error:
        return None, error
    name = pod.get("metadata", {}).get("name")
    if not name:
        return None, "pod name not found"
    path = (
        f"/api/v1/namespaces/{K8S_NAMESPACE}/pods/{name}/log"
        f"?tailLines={lines}"
    )
    token = _load_k8s_token()
    if not token:
        return None, "missing service account token"
    url = f"{K8S_API}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    context = ssl.create_default_context(cafile=K8S_CA_PATH)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=context, timeout=8) as resp:
            text = resp.read().decode("utf-8", "ignore").strip()
            return text, None
    except Exception as exc:
        return None, f"request failed: {exc}"


def _estimate_players(logs_text):
    if not logs_text:
        return None
    players = {}
    seen = False
    for line in logs_text.splitlines():
        line = ANSI_ESCAPE.sub("", line)
        for pattern in PLAYER_JOIN_PATTERNS:
            match = pattern.search(line)
            if match:
                name = match.group(1).strip()
                if name:
                    players[name] = True
                    seen = True
                break
        else:
            for pattern in PLAYER_LEAVE_PATTERNS:
                match = pattern.search(line)
                if match:
                    name = match.group(1).strip()
                    if name:
                        players.pop(name, None)
                        seen = True
                    break
    if not seen:
        return None
    return sorted(players.keys(), key=str.lower)


def _parse_log_timestamp(line):
    match = re.search(r"\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalize_player_name(name):
    name = name.strip().strip("'\"")
    return name


def _apply_log_events(lines, last_ts):
    current = {}
    max_ts = last_ts
    for line in lines:
        line = ANSI_ESCAPE.sub("", line)
        ts = _parse_log_timestamp(line)
        if ts and last_ts and ts <= last_ts:
            continue
        for pattern in PLAYER_JOIN_PATTERNS:
            match = pattern.search(line)
            if match:
                name = _normalize_player_name(match.group(1))
                if name:
                    current[name.lower()] = name
                if ts and (max_ts is None or ts > max_ts):
                    max_ts = ts
                break
        else:
            for pattern in PLAYER_LEAVE_PATTERNS:
                match = pattern.search(line)
                if match:
                    name = _normalize_player_name(match.group(1))
                    if name:
                        current[name.lower()] = None
                    if ts and (max_ts is None or ts > max_ts):
                        max_ts = ts
                    break
    return current, max_ts


def _refresh_player_state_from_logs():
    global player_last_ts
    logs, error = _fetch_last_logs(PLAYER_LOG_LINES)
    if error:
        return None, error
    lines = (logs or "").splitlines()
    updates, max_ts = _apply_log_events(lines, player_last_ts)
    if max_ts and player_last_ts and max_ts < player_last_ts:
        player_state.clear()
    for key, value in updates.items():
        if value is None:
            player_state.pop(key, None)
        else:
            player_state[key] = value
    if max_ts:
        player_last_ts = max_ts
    return list(player_state.values()), None


async def _get_players_summary():
    async with player_lock:
        players, error = await asyncio.to_thread(_refresh_player_state_from_logs)
    if error:
        return None, error
    if players is None:
        return None, "no join/leave events"
    return len(players), None


async def _update_presence_loop():
    while True:
        ready, detail = await asyncio.to_thread(_fetch_pod_status)
        if ready is True:
            count, error = await _get_players_summary()
            if count is not None:
                text = f"Active players: {count}"
            else:
                text = "Active players: ?"
        elif ready is False:
            text = "Server: offline"
        else:
            text = "Server: unknown"
        text = f"{text} ({PREFIX})"
        activity = discord.Activity(type=discord.ActivityType.playing, name=text)
        try:
            await discord_client.change_presence(activity=activity)
        except Exception:
            logger.exception("presence update failed")
        await asyncio.sleep(STATUS_UPDATE_SECONDS)


def _scale_statefulset(replicas):
    body = {"spec": {"replicas": replicas}}
    headers = {"Content-Type": "application/merge-patch+json"}
    return _k8s_request(
        "PATCH",
        f"/apis/apps/v1/namespaces/{K8S_NAMESPACE}/statefulsets/{STATEFULSET_NAME}",
        body=body,
        headers=headers,
    )


def _restart_statefulset():
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                    }
                }
            }
        }
    }
    headers = {"Content-Type": "application/merge-patch+json"}
    return _k8s_request(
        "PATCH",
        f"/apis/apps/v1/namespaces/{K8S_NAMESPACE}/statefulsets/{STATEFULSET_NAME}",
        body=body,
        headers=headers,
    )


@discord_client.event
async def on_ready():
    logger.info("discord bot ready: %s", discord_client.user)
    global presence_task
    if presence_task is None:
        presence_task = asyncio.create_task(_update_presence_loop())


@discord_client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != CHANNEL_ID:
        return
    content = message.content.strip()
    if not content.startswith(PREFIX):
        return
    command = content[len(PREFIX):].strip()
    help_text = (
        "**Hytale Bot Commands**\n\n"
        "**Everyone**\n"
        "- `!hytale ping` — Bot health check\n"
        "- `!hytale status` — Server pod readiness\n"
        "- `!hytale url` — Server URL\n"
        "- `!hytale players` — Estimated players online (from recent logs)\n\n"
        "**Admin Only**\n"
        "- `!hytale logs [lines]` — Last N server log lines (default 10, max 200)\n"
        "- `!hytale start` — Scale server to 1\n"
        "- `!hytale stop` — Scale server to 0\n"
        "- `!hytale restart` — Roll the server pod\n\n"
        "The status for the Hytale Server Bot shows the player count and if the server is offline."
    )
    if not command:
        await message.channel.send(help_text)
        return
    command_lower = command.lower()
    if command_lower == "help":
        await message.channel.send(help_text)
        return
    if command_lower == "ping":
        logger.info("ping requested by author=%s", message.author.id)
        await message.channel.send("Pong! Bot is online.")
        return
    if command_lower == "url":
        await message.channel.send(f"Server URL: {SERVER_URL}")
        return
    if command_lower == "status":
        logger.info("status requested by author=%s", message.author.id)
        ready, detail = _fetch_pod_status()
        if ready is None:
            await message.channel.send(f"Hytale server status: unknown ({detail}).")
            return
        state = "ready" if ready else "not ready"
        await message.channel.send(f"Hytale server status: {state} ({detail}).")
        return
    if command_lower.startswith("logs"):
        if message.author.id != AUTHOR_ID:
            await message.channel.send("You are not allowed to use that command.")
            return
        parts = command.split()
        lines = LOG_LINES_DEFAULT
        if len(parts) > 1:
            try:
                lines = int(parts[1])
            except ValueError:
                await message.channel.send("Usage: `!hytale logs [lines]`.")
                return
        if lines < 1:
            lines = LOG_LINES_DEFAULT
        if lines > LOG_LINES_MAX:
            lines = LOG_LINES_MAX
        logs, error = _fetch_last_logs(lines)
        if error:
            await message.channel.send(f"Could not fetch logs: {error}.")
            return
        output = logs or "No logs returned."
        if len(output) > 1800:
            output = output[-1800:]
            output = "[truncated]\n" + output
        await message.channel.send(f"```\n{output}\n```")
        return
    if command_lower == "players":
        async with player_lock:
            players, error = await asyncio.to_thread(_refresh_player_state_from_logs)
        if error:
            await message.channel.send(f"Could not fetch logs: {error}.")
            return
        if players is None:
            await message.channel.send(
                "No player join/leave events found in recent logs."
            )
            return
        count = len(players)
        if count == 0:
            await message.channel.send("Players online: 0.")
            return
        names = ", ".join(sorted(players, key=str.lower))
        if len(names) > 1700:
            names = names[:1700] + "..."
        await message.channel.send(f"Players online: {count}\n```\n{names}\n```")
        return
    if command_lower in {"start", "stop", "restart"}:
        if message.author.id != AUTHOR_ID:
            await message.channel.send("You are not allowed to use that command.")
            return
        if command_lower == "restart":
            _, error = _restart_statefulset()
            if error:
                await message.channel.send(f"Restart failed: {error}.")
                return
            await message.channel.send("Restart requested.")
            return
        replicas = 1 if command_lower == "start" else 0
        _, error = _scale_statefulset(replicas)
        if error:
            await message.channel.send(f"Scale failed: {error}.")
            return
        await message.channel.send(f"Scale to {replicas} requested.")
        return
    await message.channel.send("Try `!hytale help` for available commands.")


@discord_client.event
async def on_error(event, *args, **kwargs):
    logger.exception("discord event error: %s", event)


async def main():
    logger.info(
        "startup config: channel=%s author=%s prefix=%r namespace=%s url=%s",
        CHANNEL_ID,
        AUTHOR_ID,
        PREFIX,
        K8S_NAMESPACE,
        SERVER_URL,
    )
    async with discord_client:
        try:
            await discord_client.start(TOKEN)
        except Exception:
            logger.exception("client.start failed")
            raise


if __name__ == "__main__":
    asyncio.run(main())
