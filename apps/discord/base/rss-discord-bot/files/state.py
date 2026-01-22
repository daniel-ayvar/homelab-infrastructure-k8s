import json
import os
from typing import Dict, List

STATE_PATH = os.getenv("RSS_STATE_PATH", "/data/state.json")


def load_state() -> Dict[str, List[str]]:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return {
                key: [str(item) for item in value]
                for key, value in data.items()
                if isinstance(value, list)
            }
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def save_state(state: Dict[str, List[str]]):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp_path = f"{STATE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, STATE_PATH)
