"""Protocolos: rutinas con nombre que el usuario crea hablando y se guardan
en disco para siempre.  Ej: 'KSS' = abre VS Code + terminal + archivos + Spotify.

Cada protocolo es una lista de pasos; cada paso usa una accion del registro
ACTIONS de actions.py.
"""
from __future__ import annotations
import json
import re
import time
import unicodedata
from pathlib import Path

import actions

PROTOCOLS_FILE = Path.home() / ".config" / "blue" / "protocols.json"


def load_protocols() -> dict:
    if PROTOCOLS_FILE.exists():
        try:
            return json.loads(PROTOCOLS_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def save_protocols(data: dict):
    PROTOCOLS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def create_protocol(name: str, steps: list[dict], description: str = "",
                    category: str = "general", workdir: str = "",
                    kind: str = "") -> str:
    """steps = [{'action': 'open_project', 'params': {'path': '~/proj'}}, ...]
    category: 'general' (protocolo normal) o 'proyecto' (entorno de trabajo).
    workdir/kind (solo proyectos): carpeta donde vive y tipo 'code'|'mecanica',
    para que el proyecto sea un contenedor de contexto (ver workspace.py)."""
    data = load_protocols()
    key = name.lower().strip()
    # validar que las acciones existan
    bad = [s.get("action") for s in steps if s.get("action") not in actions.ACTIONS]
    if bad:
        return f"No reconozco estas acciones: {bad}. Protocolo no guardado."
    # validar las CLAVES de params contra la firma real de cada acción, para no
    # guardar pasos que reventarían al ejecutarse (p.ej. {'application'} vs {'name'})
    import inspect
    for s in steps:
        fn = actions.ACTIONS[s["action"]]
        sig = inspect.signature(fn)
        valid = set(sig.parameters)
        required = {n for n, p in sig.parameters.items()
                    if p.default is inspect.Parameter.empty}
        given = set((s.get("params") or {}).keys())
        unknown, missing = given - valid, required - given
        if unknown or missing:
            return (f"Paso '{s['action']}': "
                    + (f"params inexistentes {sorted(unknown)}. " if unknown else "")
                    + (f"faltan obligatorios {sorted(missing)}. " if missing else "")
                    + f"Claves válidas: {sorted(valid)}. Protocolo no guardado.")
    entry = {"name": name, "description": description,
             "category": category, "steps": steps}
    if workdir:
        entry["workdir"] = workdir
    if kind:
        entry["kind"] = kind
    data[key] = entry
    save_protocols(data)
    tipo = "Proyecto" if category == "proyecto" else "Protocolo"
    return f"{tipo} {name} guardado con {len(steps)} pasos"

# palabras de relleno que no aportan al nombre del protocolo
_STOP = {"el", "la", "los", "las", "un", "una", "mi", "mis", "de", "del", "porfavor",
         "por", "favor", "ya", "ahora", "blue", "protocolo", "proyecto", "rutina",
         "entorno", "modo"}

def _norm(s: str) -> str:
    """minúsculas, sin acentos, sin signos: para comparar nombres con tolerancia."""
    s = unicodedata.normalize("NFD", (s or "").lower().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()

def _resolve(name: str, data: dict):
    """Encuentra el protocolo aunque el nombre no sea exacto: tolera acentos,
    artículos, palabras de más y orden distinto (voz transcribe variado)."""
    if not data:
        return None
    key = name.lower().strip()
    if key in data:                                   # match exacto literal
        return data[key]
    nk = _norm(name)
    if not nk:
        return None
    norms = {k: _norm(k) for k in data}
    for k, nkk in norms.items():                      # exacto ya normalizado
        if nkk == nk:
            return data[k]
    # inclusión en ambos sentidos (normalizado)
    cands = [data[k] for k, nkk in norms.items() if nkk and (nkk in nk or nk in nkk)]
    if len(cands) == 1:
        return cands[0]
    # solapamiento de palabras significativas (ignora relleno); gana el único mejor
    nwords = {w for w in nk.split() if w not in _STOP}
    best, score, tie = None, 0, False
    for k, nkk in norms.items():
        kw = {w for w in nkk.split() if w not in _STOP}
        ov = len(nwords & kw)
        if ov > score:
            best, score, tie = data[k], ov, False
        elif ov == score and ov > 0:
            tie = True
    if best is not None and score > 0 and not tie:
        return best
    return cands[0] if cands else None

# Narrador en vivo (lo pone el assistant): NARRATOR(texto) -> habla ese paso.
# Si es None (p.ej. modo texto), no narra en vivo y el modelo narra al final.
NARRATOR = None

def set_narrator(fn):
    global NARRATOR
    NARRATOR = fn

def run_protocol(name: str) -> str:
    """Ejecuta el protocolo. Si hay NARRATOR, habla CADA paso en vivo mientras lo
    ejecuta (sin tokens) y el modelo solo da un cierre corto."""
    data = load_protocols()
    proto = _resolve(name, data)
    if not proto:
        avail = ", ".join(p["name"] for p in data.values()) or "ninguno"
        return f"No tengo el protocolo {name}. Tengo: {avail}"
    results = []
    steps = proto["steps"]
    for step in steps:
        r = actions.run_action(step["action"], step.get("params", {}))
        results.append(r)
        if NARRATOR:                          # habla este paso en el momento
            try:
                NARRATOR(r)
            except Exception:
                pass
        else:
            time.sleep(0.4)
    if NARRATOR:
        # ya se narró en voz alta paso por paso: devolver un cierre listo y breve
        try:
            import lines
            return lines.protocol_done()
        except Exception:
            return "Todo listo."
    detalle = "; ".join(results) if results else "sin pasos"
    return (f"Protocolo '{proto['name']}' ejecutado ({len(results)} pasos). "
            f"Resultado de cada paso: {detalle}")

def list_protocols(category: str | None = None) -> str:
    data = load_protocols()
    items = [p for p in data.values()
             if category is None or p.get("category", "general") == category]
    if not items:
        if category == "proyecto":
            return "Aún no tienes proyectos. Crea uno diciendo: crea un proyecto."
        return "Aun no tienes protocolos. Puedes crear uno diciendo: crea un protocolo."
    lines = [f"{p['name']}: {p.get('description') or str(len(p['steps'])) + ' pasos'}"
             for p in items]
    etiqueta = "Tus proyectos: " if category == "proyecto" else "Tus protocolos: "
    return etiqueta + "; ".join(lines)

def delete_protocol(name: str) -> str:
    data = load_protocols()
    key = name.lower().strip()
    if key in data:
        del data[key]
        save_protocols(data)
        return f"Protocolo {name} eliminado"
    return f"No encontre el protocolo {name}"
