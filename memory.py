"""Memoria persistente de Blue: hechos que recuerda ENTRE sesiones.

Guardado en ~/.config/blue/memory.json (lista de hechos). Cero dependencias.
Guardar/listar/olvidar por voz lo hace el router => 0 tokens. El cerebro recibe
un bloque compacto de hechos en su contexto para "saber" lo que recuerda sin
tener que preguntarlo (también 0 tokens extra de ida y vuelta).

Cada hecho: {"id", "text", "tag", "ts", "project"}. project="" => hecho GLOBAL
(siempre presente); project="<clave>" => ligado a un proyecto (se inyecta solo
cuando ese proyecto está activo, ver workspace.py).
"""
from __future__ import annotations
import json
import threading
import time
import unicodedata
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "blue"
MEM_FILE = CONFIG_DIR / "memory.json"

_lock = threading.Lock()
MAX_FACTS = 60                 # tope duro: no crecer sin límite (los más viejos caen)
CONTEXT_MAX = 40               # cuántos hechos inyectar al cerebro como mucho
CONTEXT_CHARS = 1100           # tope de caracteres del bloque inyectado (cuida tokens)

# relleno que no aporta al hacer match de palabras
_STOP = {"el", "la", "los", "las", "un", "una", "de", "del", "que", "y", "o",
         "a", "en", "mi", "mis", "me", "es", "son", "por", "para", "con", "se",
         "su", "sus", "lo", "le", "al", "blue", "recuerda", "acuerdate",
         "anota", "apunta", "olvida", "borra", "ten", "cuenta", "sabes",
         "tienes", "anotado", "memoria", "jefe", "wilmer"}


def _norm(s: str) -> str:
    """minúsculas, sin acentos, sin signos -> para comparar nombres/palabras."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c if (c.isalnum() or c.isspace()) else " " for c in s)


def _tokens(s: str) -> set[str]:
    return {w for w in _norm(s).split() if len(w) > 2 and w not in _STOP}


def _load() -> list[dict]:
    if MEM_FILE.exists():
        try:
            data = json.loads(MEM_FILE.read_text())
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return []


def _save(facts: list[dict]):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        MEM_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=1))
    except OSError:
        pass


def _active_key() -> str:
    """Clave del proyecto activo (import perezoso para evitar ciclos)."""
    try:
        import workspace
        return workspace.active_key()
    except Exception:
        return ""


def add(text: str, tag: str = "", project: str | None = None) -> str:
    """Guarda un hecho. Evita duplicados casi idénticos. Devuelve confirmación
    hablada (con la vibra de Blue). Si hay un proyecto activo y no se indica
    `project`, el hecho queda ligado a ese proyecto."""
    text = (text or "").strip().rstrip(" .")
    if not text:
        return "No oí qué querías que recordara, Wilmer."
    proj = _active_key() if project is None else project
    with _lock:
        facts = _load()
        nt = _tokens(text)
        for f in facts:                       # ¿ya lo sé? (mismo ámbito + solapamiento)
            if f.get("project", "") != proj:
                continue
            ft = _tokens(f.get("text", ""))
            if nt and ft and len(nt & ft) / len(nt | ft) > 0.7:
                return f"Eso ya lo tengo apuntado, Wilmer: «{f['text']}»."
        facts.append({"id": int(time.time() * 1000) % 1_000_000,
                      "text": text, "tag": tag, "project": proj,
                      "ts": time.strftime("%Y-%m-%d")})
        if len(facts) > MAX_FACTS:
            facts = facts[-MAX_FACTS:]
        _save(facts)
    if proj:
        import workspace
        return (f"Anotado para {workspace.active_name() or 'este proyecto'}, "
                f"Wilmer. No se me olvida: {text}.")
    return f"Anotado en mi memoria, Wilmer. Que conste que yo no olvido: {text}."


def _in_scope(f: dict, proj: str) -> bool:
    """True si el hecho aplica al ámbito actual: global o del proyecto activo."""
    fp = f.get("project", "")
    return fp == "" or fp == proj


def forget(query: str) -> str:
    """Borra los hechos (del ámbito actual: global + proyecto activo) que
    coincidan bien con `query`."""
    query = (query or "").strip()
    if not query:
        return "¿Y qué quieres que olvide, Wilmer? Sé más específico."
    proj = _active_key()
    with _lock:
        facts = _load()
        if not facts:
            return "No tengo nada apuntado todavía, Wilmer."
        qt = _tokens(query)
        kept, removed = [], []
        for f in facts:
            ft = _tokens(f.get("text", ""))
            if _in_scope(f, proj) and qt and ft and len(qt & ft) / len(qt) >= 0.6:
                removed.append(f)
            else:
                kept.append(f)
        if not removed:
            return f"No hallé nada parecido a «{query}» en mi memoria, Wilmer."
        _save(kept)
    if len(removed) == 1:
        return f"Listo, lo borré de mi memoria: {removed[0]['text']}."
    return f"Borré {len(removed)} cosas de mi memoria, Wilmer. Tabula rasa."


def recall(query: str = "") -> str:
    """Frase hablada con los hechos relevantes del ámbito actual (global +
    proyecto activo), o los recientes si no hay query."""
    proj = _active_key()
    facts = [f for f in _load() if _in_scope(f, proj)]
    if not facts:
        return ("Aún no tengo nada apuntado de ti, Wilmer. Dime «recuerda que...» "
                "y lo guardo para siempre.")
    if query.strip():
        qt = _tokens(query)
        scored = [(len(qt & _tokens(f.get("text", ""))), f) for f in facts]
        scored = [s for s in scored if s[0] > 0]
        if scored:
            scored.sort(key=lambda x: -x[0])
            picked = [f["text"] for _, f in scored[:6]]
        else:
            return (f"De «{query}» no tengo nada apuntado, Wilmer. "
                    "Pero pregúntame qué más recuerdo.")
    else:
        picked = [f["text"] for f in facts[-8:]]
    if len(picked) == 1:
        return f"Lo que recuerdo, Wilmer: {picked[0]}."
    return "Esto es lo que tengo de ti, Wilmer: " + "; ".join(picked) + "."


def context_block() -> str:
    """Bloque compacto de hechos (global + proyecto activo) para inyectar al
    cerebro. Vacío si no hay nada."""
    proj = _active_key()
    facts = [f for f in _load() if _in_scope(f, proj)]
    if not facts:
        return ""
    out, total = [], 0
    for f in facts[-CONTEXT_MAX:]:
        line = "- " + f.get("text", "")
        total += len(line)
        if total > CONTEXT_CHARS:
            break
        out.append(line)
    if not out:
        return ""
    return ("\n\nMEMORIA (lo que sabes de Wilmer de sesiones pasadas; úsala con "
            "naturalidad cuando venga al caso, NO la recites entera):\n"
            + "\n".join(out))


def inventory() -> list[dict]:
    """Hechos guardados con su ámbito (para el panel web). Solo lee, no habla."""
    return [{"text": f.get("text", ""), "project": f.get("project", ""),
             "ts": f.get("ts", "")} for f in _load()]


def count() -> int:
    return len(_load())


def active_count() -> int:
    """Cuántos hechos están ligados al proyecto activo (no globales)."""
    proj = _active_key()
    if not proj:
        return 0
    return sum(1 for f in _load() if f.get("project", "") == proj)
