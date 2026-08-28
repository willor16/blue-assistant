"""Espacio de trabajo activo: convierte un PROYECTO (de protocols.py) en un
CONTENEDOR DE CONTEXTO, no solo un lanzador.

Un proyecto puede tener además de sus pasos:
  - workdir: la carpeta donde vive (repo de código, carpeta de planos/cálculos)
  - kind: 'code' (programación) o 'mecanica' (ingeniería mecánica)

Al "trabajar en X" se marca como ACTIVO. Eso hace tres cosas, todas 0 tokens:
  1. Abre su entorno (corre sus pasos, narrados en vivo).
  2. Fija el workdir para las tareas pesadas (tasks.py lo lee de aquí).
  3. Acota la memoria: los hechos que guardes quedan ligados a este proyecto y
     se inyectan al cerebro solo cuando el proyecto está activo (memory.py).

El proyecto activo se guarda como su CLAVE en ~/.config/blue/active_project.
"""
from __future__ import annotations
from pathlib import Path

import protocols

CONFIG_DIR = Path.home() / ".config" / "blue"
ACTIVE_FILE = CONFIG_DIR / "active_project"

_KIND_LABEL = {"code": "programación", "mecanica": "ingeniería mecánica",
               "mecánica": "ingeniería mecánica"}


def _set_active_key(key: str):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVE_FILE.write_text(key.strip())
    except OSError:
        pass


def active_key() -> str:
    """Clave del proyecto activo ('' si no hay ninguno)."""
    try:
        return ACTIVE_FILE.read_text().strip()
    except OSError:
        return ""


def active() -> dict | None:
    """Dict del proyecto activo (re-resuelto desde protocols), o None."""
    key = active_key()
    if not key:
        return None
    data = protocols.load_protocols()
    return data.get(key) or protocols._resolve(key, data)


def active_name() -> str | None:
    p = active()
    return p["name"] if p else None


def active_workdir() -> str | None:
    """Carpeta del proyecto activo (expandida), o None si no tiene/está inactivo."""
    p = active()
    wd = (p or {}).get("workdir")
    if not wd:
        return None
    return str(Path(wd).expanduser())


def active_kind() -> str:
    """'code' | 'mecanica' | '' del proyecto activo."""
    return (active() or {}).get("kind", "") or ""


def deactivate() -> str:
    name = active_name()
    _set_active_key("")
    if not name:
        return "No estabas en ningún proyecto, Wilmer."
    return f"Cerramos {name}. Vuelvo a modo general, Wilmer."


def context_line() -> str:
    """Una línea para inyectar al cerebro: qué proyecto está activo y de qué tipo.
    Vacía si no hay proyecto activo."""
    p = active()
    if not p:
        return ""
    kind = _KIND_LABEL.get(p.get("kind", ""), "")
    wd = p.get("workdir")
    extra = f" Carpeta: {wd}." if wd else ""
    tipo = f" (proyecto de {kind})" if kind else ""
    return f"\n\nPROYECTO ACTIVO: {p['name']}{tipo}.{extra}"


def work_on(name: str) -> str:
    """Activa un proyecto como espacio de trabajo: lo marca activo, abre su
    entorno (narrando cada paso en vivo) y resume el contexto cargado."""
    data = protocols.load_protocols()
    proto = protocols._resolve(name, data)
    if not proto:
        try:
            import study
            containers = study.CONTAINER_CATS | {"proyecto"}
        except Exception:
            containers = {"proyecto"}
        proys = [p["name"] for p in data.values()
                 if p.get("category") in containers]
        disp = ", ".join(proys) if proys else "ninguno todavía"
        return (f"No tengo nada llamado {name}, Wilmer. "
                f"Tus espacios: {disp}.")
    _set_active_key(proto["name"].lower().strip())
    # abre el entorno (run_protocol narra cada paso en vivo si hay NARRATOR)
    if proto.get("steps"):
        try:
            protocols.run_protocol(proto["name"])
        except Exception:
            pass
    # resumen de contexto cargado (0 tokens)
    try:
        import memory
        n = memory.active_count()
    except Exception:
        n = 0
    kind = _KIND_LABEL.get(proto.get("kind", ""), "")
    wd = proto.get("workdir")
    parts = [f"Listo, Wilmer, estamos en {proto['name']}"]
    if kind:
        parts.append(f", tu proyecto de {kind}")
    parts.append(".")
    msg = "".join(parts)
    if wd:
        msg += " Las tareas pesadas las correré en esa carpeta."
    else:
        msg += (" Aún no me has dicho en qué carpeta vive; dímela cuando quieras "
                "para trabajar a fondo ahí.")
    if n:
        msg += f" Tengo {n} cosa{'s' if n != 1 else ''} de este proyecto en mente."
    return msg


def set_folder(name: str, path: str, kind: str = "") -> str:
    """Liga una carpeta (y opcionalmente el tipo) a un proyecto existente, o lo
    crea si no existe."""
    data = protocols.load_protocols()
    proto = protocols._resolve(name, data)
    p = Path(path).expanduser()
    if not p.exists():
        # Antes esto era un callejón sin salida: se lo soltaba a Wilmer tal cual
        # ("no existe esa ruta, revisa y me dices") aunque lo que él había pedido
        # fuese justamente crearla. Ahora el mensaje le dice al cerebro qué hacer.
        return (f"La carpeta {p} todavía no existe. Si Wilmer quería crearla, "
                f"llama primero a crear_carpeta con esa ruta y vuelve a intentarlo; "
                f"no le contestes que la ruta no existe.")
    k = {"código": "code", "programacion": "code", "programación": "code",
         "mecánica": "mecanica", "mecanico": "mecanica"}.get(kind.lower(), kind.lower())
    if proto is None:                       # no existe: créalo como proyecto vacío
        key = name.lower().strip()
        data[key] = {"name": name, "description": "", "category": "proyecto",
                     "steps": [], "workdir": str(p), "kind": k}
        proto = data[key]
    else:
        # localizar su clave real para escribir encima
        for kk, vv in data.items():
            if vv is proto:
                proto = vv
                break
        proto["workdir"] = str(p)
        proto.setdefault("category", "proyecto")
        if k:
            proto["kind"] = k
    protocols.save_protocols(data)
    tipo = _KIND_LABEL.get(k, "")
    cola = f", proyecto de {tipo}" if tipo else ""
    return f"Anotado: {proto['name']} vive en {p}{cola}, Wilmer."
