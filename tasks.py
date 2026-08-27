"""Fase 2 — Tareas pesadas delegadas a Claude Code (suscripción de Wilmer).

Blue le pasa una instrucción a `claude -p` con Sonnet por defecto: puede leer y
escribir archivos, correr tests, redactar documentos, buscar en internet, etc.

SEGURIDAD: no borra archivos ni instala/desinstala paquetes salvo que se haya
pedido EXPLÍCITAMENTE. Si la tarea lo requiere y no estaba claro, NO lo hace:
devuelve una línea 'CONFIRMAR:' y Blue te pide permiso antes de proceder.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

import config

# disparadores explícitos: solo entra en "modo tarea" si lo pides claramente
_TRIGGERS = re.compile(
    r"^(tarea[:,]?\s|usa\s+claude\s+code|con\s+claude\s+code|usa\s+el\s+bueno|"
    r"usa\s+sonnet|investiga\b|invest[ií]game\b|invest[ií]ga\w*\s+(en|sobre)\b|"
    r"redacta\b|red[aá]ctame\b|escr[ií]beme\s+(un|una|el|la)\b|"
    r"hazme\s+(un|una|el|la)\s+(cronograma|documento|tabla|resumen|script|programa|"
    r"informe|reporte|ensayo|plan|c[oó]digo|funci[oó]n|archivo)|"
    r"cr[eé]ame\s+(un|una)\b|gen[eé]rame\b|genera\s+(un|una)\b|"
    r"corre\s+(el|los|un|mis|las)\s+(test|prueba)|c[oó]rreme\s+(el|los|las)\b|"
    r"ejecuta\s+(el|los|las|un)\s+(test|prueba)|arregla\b|refactoriza\b|"
    r"revisa\s+(mi|el|este)\s+(proyecto|c[oó]digo|repo|repositorio))",
    re.IGNORECASE)

_STRIP_PREFIX = re.compile(
    r"^(tarea[:,]?\s+|usa\s+claude\s+code[,:]?\s+|con\s+claude\s+code[,:]?\s+|"
    r"usa\s+el\s+bueno[,:]?\s+|usa\s+sonnet[,:]?\s+)", re.IGNORECASE)

_GUARD = (
    "Eres el motor de tareas de BLUE, el asistente de Wilmer, en su PC Linux "
    "(CachyOS/Hyprland). Ejecuta la TAREA que sigue. Reglas:\n"
    "- Puedes leer/escribir archivos, correr comandos, tests y buscar en la web.\n"
    "- BORRAR archivos o INSTALAR/DESINSTALAR paquetes SIEMPRE requiere "
    "confirmación: aunque el usuario lo haya pedido, NO lo ejecutes todavía. En su "
    "lugar responde UNA sola línea que empiece con 'CONFIRMAR:' describiendo en "
    "español la acción exacta. Solo si más adelante recibes permiso explícito, "
    "procede.\n"
    "- Los documentos/archivos que generes, guárdalos en la carpeta del usuario "
    "(por ejemplo ~/Documentos) y di la ruta.\n"
    "- Al terminar, responde en 1 a 3 frases, en español, qué hiciste o "
    "encontraste, para que se lea en voz alta. Sin markdown, sin listas, sin "
    "asteriscos. Si fallaste, dilo claro y breve."
)


# si habla de correo/agenda, NO es tarea de Claude Code: lo maneja el cerebro
# (redactar+enviar con send_email) o la ruta rápida (revisar/agenda).
_NOT_TASK = re.compile(r"\b(correo|correos|email|e-mail|mail|bandeja|inbox|"
                       r"agenda|agéndame|agendame|recu[eé]rdame|recordatorio)\b",
                       re.IGNORECASE)


def detect(text: str) -> str | None:
    """Devuelve la instrucción de tarea (limpia) si el texto la dispara, o None."""
    t = (text or "").strip()
    if not t or _NOT_TASK.search(t):
        return None
    # un análisis FEM (con FreeCAD disponible) también es tarea para Claude Code
    fem = False
    try:
        import engineering
        fem = engineering.is_fem_request(t)
    except Exception:
        fem = False
    if not _TRIGGERS.search(t) and not fem:
        return None
    return _STRIP_PREFIX.sub("", t).strip() or t


def run_task(instruction: str, confirmed: bool = False,
             model: str | None = None, timeout: int = 600) -> dict:
    """Lanza Claude Code. Devuelve {ok, confirm, text}.
    confirmed=True añade permiso explícito (para reintentar tras un 'CONFIRMAR:')."""
    cfg = config.load()
    model = model or cfg.get("task_model", "sonnet")
    # prioridad: carpeta del PROYECTO ACTIVO > task_workdir global > home
    cwd = None
    try:
        import workspace
        cwd = workspace.active_workdir()
    except Exception:
        cwd = None
    cwd = cwd or cfg.get("task_workdir") or str(Path.home())

    prompt = _GUARD
    try:                                   # pista de dominio si hay proyecto activo
        import workspace
        kind = workspace.active_kind()
        if kind == "mecanica":
            prompt += ("\n- Contexto: proyecto de INGENIERÍA MECÁNICA. Si hay "
                       "cálculos, muestra fórmulas, unidades y supuestos; guarda "
                       "resultados en la carpeta del proyecto.\n"
                       "- TOOLBOX disponible en el venv de Blue "
                       "(/home/wilmer/.local/share/blue/.venv/bin/python): "
                       "CoolProp (termo/vapor/refrigerantes/aire húmedo), fluids "
                       "(mec. fluidos), ht (transf. calor), thermo, pint "
                       "(unidades), Pynite (estructural), numpy/scipy. Úsalo con "
                       "ese intérprete; instala con `uv pip install --python "
                       "<ese_python> <lib>` si falta algo.")
        elif kind == "code":
            prompt += ("\n- Contexto: proyecto de PROGRAMACIÓN. Respeta el estilo "
                       "del repo, no rompas la build y corre los tests si los hay.")
    except Exception:
        pass
    try:                                   # ¿es un análisis FEM? -> guía FreeCAD
        import engineering
        if engineering.is_fem_request(instruction):
            prompt += engineering.fem_brief()
    except Exception:
        pass
    if confirmed:
        prompt += ("\n- El usuario YA CONFIRMÓ: tienes permiso para realizar la "
                   "acción descrita (incluido borrar o instalar si aplica).")
    prompt += "\n\nTAREA: " + instruction

    cmd = ["claude", "-p", prompt, "--model", model,
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Bash Read Edit Write Glob Grep WebSearch WebFetch",
           "--output-format", "text"]
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                             timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "confirm": False,
                "text": "Se me acabó el tiempo con esa tarea."}
    except Exception as e:
        return {"ok": False, "confirm": False, "text": str(e)[:200]}

    try:
        import usage
        usage.bump("claude-task")
    except Exception:
        pass

    reply = (out.stdout or "").strip()
    if not reply:
        return {"ok": False, "confirm": False,
                "text": (out.stderr or "Sin respuesta de Claude Code.")[:200]}
    if reply.upper().startswith("CONFIRMAR:"):
        return {"ok": True, "confirm": True,
                "text": reply.split(":", 1)[1].strip()}
    return {"ok": True, "confirm": False, "text": reply}
