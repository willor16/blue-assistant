"""Contador de peticiones a la API del cerebro, por día y proveedor.

Sirve para que Wilmer VEA cuántas lleva y qué tan cerca está de cualquier
límite gratuito, en vez de adivinar. Se guarda en ~/.config/blue/usage.json.
"""
from __future__ import annotations
import datetime
import json
import threading
from pathlib import Path

USAGE_FILE = Path.home() / ".config" / "blue" / "usage.json"
_lock = threading.Lock()


def _today() -> str:
    return datetime.date.today().isoformat()


def _load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict):
    try:
        USAGE_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def bump(provider: str = "", n: int = 1):
    """Suma n peticiones al día de hoy (y al proveedor)."""
    with _lock:
        data = _load()
        day = _today()
        d = data.setdefault(day, {"requests": 0, "by_provider": {}})
        d["requests"] += n
        d["by_provider"][provider] = d["by_provider"].get(provider, 0) + n
        # conserva solo los últimos 14 días
        for k in sorted(data.keys())[:-14]:
            data.pop(k, None)
        _save(data)


def today() -> int:
    return _load().get(_today(), {}).get("requests", 0)


def today_detail() -> dict:
    return _load().get(_today(), {"requests": 0, "by_provider": {}})
