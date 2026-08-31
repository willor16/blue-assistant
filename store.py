"""Estado compartido en memoria entre el hilo de voz y la interfaz."""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_status = "idle"
_detail = ""
_last_user = ""
_last_reply = ""
_pulse = 0                # se incrementa por cada paso narrado (estallido del anillo)
_log: list[dict] = []
MAX_LOG = 60

CONFIG_DIR = Path.home() / ".config" / "blue"
STATE_FILE = CONFIG_DIR / "state"        # formato simple (orbe Quickshell viejo)
UI_FILE = CONFIG_DIR / "ui.json"         # estado rico para la ventana flotante


def _write_files():
    """Escribe el estado a disco para que la ventana QML lo lea/vigile."""
    try:
        STATE_FILE.write_text(f"{_status}\n{_detail}")
    except OSError:
        pass
    try:
        import usage
        count = usage.today()
    except Exception:
        count = 0
    try:
        UI_FILE.write_text(json.dumps({
            "status": _status,
            "detail": _detail,
            "user": _last_user,
            "reply": _last_reply,
            "count": count,
            "pulse": _pulse,
            "ts": time.time(),
        }))
    except OSError:
        pass


def narrate(text: str):
    """Marca un paso narrado en vivo: estado 'speaking' + texto + pulso (estallido)."""
    global _status, _detail, _last_reply, _pulse
    if not text:
        return
    with _lock:
        _status = "speaking"
        _detail = text
        _last_reply = text
        _pulse += 1
        _write_files()


# ---------------------------------------------------------------- cancelacion
# El testigo de "Wilmer ha pedido parar" vive AQUI y no en voice.py porque
# brain.py tambien tiene que mirarlo, y no puede arrastrar sounddevice ni torch
# solo para consultar una bandera. store.py es stdlib puro.
_abortado = threading.Event()


def abortar():
    """Pedir que el turno en curso muera cuanto antes."""
    _abortado.set()


def abortado() -> bool:
    return _abortado.is_set()


def limpiar_aborto():
    _abortado.clear()


def get_status() -> str:
    with _lock:
        return _status


def set_status(status: str, detail: str = ""):
    global _status, _detail
    with _lock:
        _status = status
        _detail = detail
        _write_files()


def add(role: str, text: str):
    global _last_user, _last_reply
    if not text:
        return
    with _lock:
        _log.append({"role": role, "text": text,
                     "time": time.strftime("%H:%M:%S")})
        if len(_log) > MAX_LOG:
            del _log[:-MAX_LOG]
        if "asistente" in role:
            _last_reply = text
        else:
            _last_user = text
        _write_files()


def snapshot() -> dict:
    with _lock:
        return {"status": _status, "detail": _detail,
                "user": _last_user, "reply": _last_reply, "log": list(_log)}
