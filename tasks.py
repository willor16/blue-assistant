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
import time
from pathlib import Path

import config

# La ultima tarea: en que carpeta y cuando. Sirve para encadenar.
#
# Cada `claude -p` era una invocacion NUEVA sin memoria, asi que "edita la
# pagina que acabamos de hacer" no sabia que pagina era: tenia que buscarla, y
# con varios HTML en la carpeta podia editar el que no era.
#
# `--continue` retoma la ultima conversacion, y se comprobo que la continuidad
# es POR CARPETA: en el mismo directorio recuerda, en otro arranca limpio y no
# arrastra contexto ajeno. Por eso solo se encadena si la tarea anterior fue en
# ESTA misma carpeta y hace poco; si no, cada encargo en $HOME se pegaria al
# anterior para siempre.
_ultima_tarea = {"cwd": None, "cuando": 0.0}
SEGUIR_MINUTOS = 60

# disparadores explícitos: solo entra en "modo tarea" si lo pides claramente
_TRIGGERS = re.compile(
    r"^([hj]?[eé]rebo[,:\s]|tarea[:,]?\s|usa\s+claude\s+code|con\s+claude\s+code|usa\s+el\s+bueno|"
    r"usa\s+sonnet|investiga\b|invest[ií]game\b|invest[ií]ga\w*\s+(en|sobre)\b|"
    r"redacta\b|red[aá]ctame\b|escr[ií]beme\s+(un|una|el|la)\b|"
    r"hazme\s+(un|una|el|la)\s+(cronograma|documento|tabla|resumen|script|programa|"
    r"informe|reporte|ensayo|plan|c[oó]digo|funci[oó]n|archivo|"
    r"p[aá]gina|web|sitio|juego|app|aplicaci[oó]n|formulario)|"
    r"cr[eé]ame\s+(un|una)\b|gen[eé]rame\b|genera\s+(un|una)\b|"
    r"corre\s+(el|los|un|mis|las)\s+(test|prueba)|c[oó]rreme\s+(el|los|las)\b|"
    r"ejecuta\s+(el|los|las|un)\s+(test|prueba)|arregla\b|refactoriza\b|"
    r"revisa\s+(mi|el|este)\s+(proyecto|c[oó]digo|repo|repositorio))",
    re.IGNORECASE)

# Encargos de seguimiento: "edita la pagina que acabamos de hacer y ponle un
# contador". Van aparte porque piden DOS condiciones a la vez, y con una sola no
# se puede: el verbo tiene que abrir la frase Y tiene que hablarse de algo
# digital. Sin la segunda mitad, "ponle" se tragaria "ponle play a spotify", que
# es una orden de musica y no una tarea de Claude Code.
_EDITA = re.compile(
    r"^(edita|ed[ií]tame|modifica|mod[ií]f[ií]came|actualiza|act[uú]al[ií]zame|"
    r"a[ñn][aá]dele|a[ñn][aá]de|agr[eé]gale|agrega|ponle|c[aá]mbiale|cambia|"
    r"corr[ií]gele|corrige|mej[oó]rale|mejora)\b", re.IGNORECASE)
_COSA_DIGITAL = re.compile(
    r"\b(p[aá]gina|web|sitio|html|css|javascript|script|c[oó]digo|programa|"
    r"archivo|fichero|documento|juego|app|aplicaci[oó]n|proyecto|formulario|"
    r"funci[oó]n|clase|repo|repositorio)\b", re.IGNORECASE)

_STRIP_PREFIX = re.compile(
    r"^([hj]?[eé]rebo[,:.\s]+|tarea[:,]?\s+|usa\s+claude\s+code[,:]?\s+|con\s+claude\s+code[,:]?\s+|"
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
    # Donde se guarda lo que se genera se decide en run_task, porque depende de
    # si hay proyecto activo. Estaba fijo en "guardalo en ~/Documentos", y esa
    # linea PISABA la carpeta de trabajo: se comprobo el 01/09/2026 lanzando dos
    # tareas con cwd en una carpeta de prueba y las dos escribieron en
    # ~/Documentos igual, dejando la carpeta del proyecto vacia. O sea que fijar
    # un proyecto no servia de nada para las tareas.
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
    seguimiento = bool(_EDITA.match(t) and _COSA_DIGITAL.search(t))
    if not _TRIGGERS.search(t) and not fem and not seguimiento:
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
    if cwd and Path(cwd) != Path.home():
        prompt += (f"\n- ESTÁS TRABAJANDO DENTRO DE {cwd}. Guarda ahí lo que "
                   "generes y edita ahí lo que ya exista; no te lleves nada a "
                   "otra carpeta. Di la ruta al terminar.")
    else:
        prompt += ("\n- No hay carpeta de proyecto: guarda lo que generes en "
                   "~/Documentos y di la ruta.")
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
    seguir = (_ultima_tarea["cwd"] == cwd
              and time.time() - _ultima_tarea["cuando"] < SEGUIR_MINUTOS * 60)
    if seguir:
        cmd.append("--continue")
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                             timeout=timeout)
        _ultima_tarea["cwd"], _ultima_tarea["cuando"] = cwd, time.time()
        print(f"(tarea en {cwd}{' — sigue la anterior' if seguir else ''})",
              flush=True)
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
