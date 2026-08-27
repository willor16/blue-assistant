"""Fase 3 — Agenda local de Blue. Recordatorios/eventos guardados en disco
(~/.config/blue/agenda.json). Cero tokens, cero internet, sin OAuth.

(La sincronización con Google Calendar necesitaría OAuth y queda para más
adelante; esto cubre 'agéndame', 'recuérdame' y 'qué tengo pendiente' ya.)
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path

import timeinfo

AGENDA_FILE = Path.home() / ".config" / "blue" / "agenda.json"


def _load() -> list:
    try:
        return json.loads(AGENDA_FILE.read_text())
    except Exception:
        return []


def _save(items: list):
    try:
        AGENDA_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    except Exception:
        pass


def add_event(text: str, when_iso: str = "") -> str:
    """Agenda un evento. when_iso opcional (ISO). Si no, intenta inferir hora
    del propio texto ('mañana a las 3')."""
    text = (text or "").strip()
    if not text:
        return "¿Qué quieres que agende, Wilmer? No me dijiste nada."
    when = when_iso
    if not when:
        try:
            tgt = timeinfo._parse_target(text)
            if tgt:
                if "mañana" in text.lower():
                    tgt = tgt + datetime.timedelta(days=1)
                when = tgt.isoformat()
        except Exception:
            when = ""
    items = _load()
    items.append({"text": text, "when": when,
                  "created": datetime.datetime.now().isoformat()})
    items.sort(key=lambda e: e.get("when") or "9999")
    _save(items)
    if when:
        try:
            dt = datetime.datetime.fromisoformat(when)
            cuando = f" para el {dt.day}/{dt.month} a las {dt.strftime('%H:%M')}"
        except Exception:
            cuando = ""
    else:
        cuando = ""
    return f"Anotado{cuando}, Wilmer: {text}. No se me olvida, tranquilo."


def list_events() -> str:
    items = _load()
    if not items:
        return "No tienes nada agendado, Wilmer. Agenda vacía, vida tranquila."
    out = []
    for e in items[:8]:
        when = e.get("when", "")
        prefijo = ""
        if when:
            try:
                dt = datetime.datetime.fromisoformat(when)
                prefijo = f"{dt.day}/{dt.month} {dt.strftime('%H:%M')}: "
            except Exception:
                prefijo = ""
        out.append(prefijo + e["text"])
    n = len(items)
    cab = "Tienes esto pendiente" if n > 1 else "Tienes esto pendiente"
    return f"{cab}, Wilmer: " + "; ".join(out) + "."


def clear_events() -> str:
    _save([])
    return "Agenda borrada, Wilmer. Borrón y cuenta nueva."
