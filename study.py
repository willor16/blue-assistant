"""Taxonomía de estudio/trabajo de Wilmer.

Organiza sus contenedores de contexto en cuatro buckets, cada uno con su carpeta:
  - curso     -> ~/Documentos/Cursos/<nombre>            (estudio universidad)
  - proyecto  -> ~/Documentos/Proyectos Universidad/<nombre>
  - trabajo   -> ~/Documentos/Trabajos/<nombre>
  - externo   -> ~/Documentos/Estudio externo/<nombre>   (cursos de otros lugares)

Cada contenedor se registra como un PROYECTO en protocols.json (con su workdir,
category y kind), así hereda gratis todo lo de workspace.py: "trabajemos en X" lo
activa, su memoria queda en ámbito propio y el RAG indexa/consulta solo lo suyo.

Wilmer puede decir por voz "tengo un nuevo curso X" / "nuevo proyecto X" / "nuevo
trabajo X" y Blue crea la carpeta + lo registra. Luego suelta archivos ahí y dice
"indexa mis apuntes de X".
"""
from __future__ import annotations
import re
from pathlib import Path

import protocols

BASE = Path.home() / "Documentos"

# bucket -> carpeta, tipo por defecto, etiqueta hablada, valor de 'category'
CATS = {
    "curso":    {"dir": "Cursos",                 "kind": "mecanica",
                 "label": "curso",                 "cat": "curso"},
    "proyecto": {"dir": "Proyectos Universidad",  "kind": "",
                 "label": "proyecto de la universidad", "cat": "proyecto"},
    "trabajo":  {"dir": "Trabajos",               "kind": "",
                 "label": "trabajo",               "cat": "trabajo"},
    "externo":  {"dir": "Estudio externo",        "kind": "",
                 "label": "estudio externo",       "cat": "externo"},
}
CONTAINER_CATS = {c["cat"] for c in CATS.values()}

# palabras habladas -> bucket
_WORD2CAT = {
    "curso": "curso", "cursos": "curso", "materia": "curso", "asignatura": "curso",
    "clase": "curso", "ramo": "curso",
    "proyecto": "proyecto", "proyectos": "proyecto",
    "trabajo": "trabajo", "trabajos": "trabajo", "tarea": "trabajo",
    "externo": "externo", "afuera": "externo", "fuera": "externo",
}


def categorize(word: str) -> str | None:
    """Mapea una palabra hablada a un bucket ('curso'/'proyecto'/...)."""
    return _WORD2CAT.get((word or "").lower().strip())


def _slug(name: str) -> str:
    """Nombre de carpeta legible y seguro (conserva acentos, quita lo raro)."""
    s = re.sub(r"[\\/:*?\"<>|]+", " ", (name or "").strip())
    s = re.sub(r"\s+", " ", s).strip()
    return s or "sin nombre"


def ensure_base() -> None:
    """Crea las cuatro carpetas raíz si no existen (idempotente)."""
    for c in CATS.values():
        (BASE / c["dir"]).mkdir(parents=True, exist_ok=True)


def folder_for(category: str, name: str) -> Path:
    return BASE / CATS[category]["dir"] / _slug(name)


def new(category: str, name: str) -> str:
    """Crea la carpeta del nuevo curso/proyecto/trabajo y lo registra como
    proyecto-contenedor. category: clave de CATS o palabra hablada."""
    cat = category if category in CATS else categorize(category)
    if not cat:
        return (f"No sé en qué grupo va '{category}', Wilmer. Dime si es un curso, "
                f"un proyecto, un trabajo o estudio externo.")
    name = (name or "").strip()
    if not name:
        return f"¿Qué nombre le pongo al {CATS[cat]['label']}, Wilmer?"
    meta = CATS[cat]
    ensure_base()
    folder = folder_for(cat, name)
    existed = folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    # registrar/actualizar como proyecto-contenedor en protocols.json
    data = protocols.load_protocols()
    key = name.lower().strip()
    entry = data.get(key, {})
    entry.update({"name": name, "category": meta["cat"], "steps": entry.get("steps", []),
                  "description": entry.get("description", ""),
                  "workdir": str(folder)})
    if meta["kind"]:
        entry["kind"] = meta["kind"]
    data[key] = entry
    protocols.save_protocols(data)
    verbo = "Ya tenías" if existed else "Listo, creé"
    extra = (" Suelta ahí tus archivos y dime 'indexa mis apuntes de "
             f"{name}' cuando quieras que los lea." if cat in ("curso", "externo")
             else "")
    return (f"{verbo} el {meta['label']} {name}. Su carpeta es {folder}.{extra}")


def list_by(category: str) -> str:
    """Lista los contenedores de un bucket ('curso'/'proyecto'/...)."""
    cat = category if category in CATS else categorize(category)
    if not cat:
        return "¿De qué grupo, Wilmer: cursos, proyectos, trabajos o estudio externo?"
    data = protocols.load_protocols()
    names = [p["name"] for p in data.values()
             if p.get("category") == CATS[cat]["cat"]]
    label = CATS[cat]["label"]
    if not names:
        return f"No tienes ningún {label} todavía, Wilmer."
    plural = label + ("s" if not label.endswith("s") else "")
    return f"Tus {plural}: {', '.join(names)}."


def index_notes(name: str = "") -> str:
    """Indexa la carpeta de un curso/proyecto (por nombre, o el activo)."""
    import rag
    if name.strip():
        data = protocols.load_protocols()
        proto = protocols._resolve(name, data)
        if not proto:
            return f"No tengo un curso o proyecto llamado {name}, Wilmer."
        wd = proto.get("workdir")
        if not wd:
            return f"{proto['name']} no tiene carpeta asignada todavía, Wilmer."
        # indexar en el ámbito de ESE proyecto (aunque no esté activo)
        return rag.index(wd, project=proto["name"].lower().strip())
    # sin nombre: usa el proyecto activo
    import workspace
    wd = workspace.active_workdir()
    if not wd:
        return ("No me dijiste qué carpeta indexar y no hay proyecto activo, "
                "Wilmer. Dime 'indexa mis apuntes de <curso>'.")
    return rag.index(wd)
