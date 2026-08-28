"""
conciencia.py — Lo que BLUE sabe de sí misma y de la máquina.

Un modelo recibe los esquemas de sus 53 herramientas, pero eso no es lo mismo
que saber quién es. Preguntado a bocajarro "¿qué puedes hacer?" o "¿qué usas por
debajo?", tira de lo que aprendió en el entrenamiento y contesta cualquier cosa
— llegó a decir que era GPT-4 con Claude Code de ayudante.

Aquí se arma el bloque que lo aterriza: cómo se llama, con qué motor piensa, qué
sabe hacer agrupado por áreas, **qué subsistemas están vivos de verdad** (no lo
que dice el código, lo que responde ahora), y en qué máquina vive.

Nada de listar las 53 herramientas una por una: eso ya va en los esquemas y
gastar el prompt repitiéndolo no aporta. Aquí van las áreas y el estado.

Todo con caché corta y a prueba de fallos: si `hyprctl` no responde o el disco
de la memoria no está, esa línea desaparece y BLUE contesta igual. Que no sepa
qué canción suena no es motivo para quedarse callada.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "blue"

_cache = {}


def _cacheado(clave, segundos, fn):
    ahora = time.monotonic()
    guardado = _cache.get(clave)
    if guardado and ahora - guardado[0] < segundos:
        return guardado[1]
    try:
        valor = fn()
    except Exception:
        valor = None
    _cache[clave] = (ahora, valor)
    return valor


def _cmd(args, timeout=2):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════
#  La máquina, ahora mismo
# ══════════════════════════════════════════════════════════════
def _uptime():
    try:
        with open("/proc/uptime") as f:
            seg = float(f.read().split()[0])
    except Exception:
        return ""
    horas, minutos = int(seg // 3600), int((seg % 3600) // 60)
    if horas >= 24:
        return f"{horas // 24} días y {horas % 24} horas"
    return f"{horas} horas y {minutos} minutos" if horas else f"{minutos} minutos"


def _memoria_ram():
    try:
        datos = {}
        with open("/proc/meminfo") as f:
            for linea in f:
                clave, _, resto = linea.partition(":")
                datos[clave] = int(resto.split()[0])
        total = datos["MemTotal"] / 1048576
        libre = datos["MemAvailable"] / 1048576
        return f"{total - libre:.1f} de {total:.1f} GB usados"
    except Exception:
        return ""


def _disco():
    try:
        u = shutil.disk_usage(str(Path.home()))
        return f"{u.free / 1e9:.0f} GB libres de {u.total / 1e9:.0f}"
    except Exception:
        return ""


def _carga():
    try:
        with open("/proc/loadavg") as f:
            uno = f.read().split()[0]
        return f"{uno} (de {os.cpu_count()} núcleos)"
    except Exception:
        return ""


def _so():
    nombre = ""
    try:
        with open("/etc/os-release") as f:
            for linea in f:
                if linea.startswith("PRETTY_NAME="):
                    nombre = linea.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass
    try:
        return nombre, os.uname().release
    except Exception:
        return nombre, ""


def _escritorio():
    ws = _cmd(["hyprctl", "activeworkspace", "-j"])
    ventanas = _cmd(["hyprctl", "clients", "-j"])
    linea_ws, apps = "", []
    try:
        if ws:
            d = json.loads(ws)
            linea_ws = f"escritorio {d.get('name', '?')} en {d.get('monitor', '?')}"
    except Exception:
        pass
    try:
        if ventanas:
            vistos = []
            for c in json.loads(ventanas):
                n = (c.get("class") or "").strip()
                if n and n not in vistos:
                    vistos.append(n)
            apps = vistos[:12]
    except Exception:
        pass
    return linea_ws, apps


def _sonando():
    m = _cmd(["playerctl", "metadata", "--format", "{{artist}} - {{title}}"])
    if m and _cmd(["playerctl", "status"]).lower().startswith("playing"):
        return m
    return ""


def de_la_maquina() -> str:
    def armar():
        nombre_so, kernel = _so()
        host = _cmd(["hostnamectl", "hostname"]) or os.uname().nodename
        linea_ws, apps = _escritorio()

        lineas = [f"- Equipo: {host}"]
        if nombre_so:
            lineas.append(f"- Sistema: {nombre_so}" + (f", kernel {kernel}" if kernel else ""))
        for etiqueta, valor in (("Encendida desde hace", _uptime()),
                                ("Memoria", _memoria_ram()),
                                ("Disco", _disco()),
                                ("Carga", _carga())):
            if valor:
                lineas.append(f"- {etiqueta}: {valor}")
        if linea_ws:
            lineas.append(f"- Ahora mismo: {linea_ws}")
        if apps:
            lineas.append(f"- Ventanas abiertas: {', '.join(apps)}")
        son = _sonando()
        if son:
            lineas.append(f"- Sonando: {son}")
        return "\n".join(lineas)

    # 15 s: lo justo para no repetir el trabajo en una ráfaga de mensajes, y lo
    # bastante corto para que "¿qué tengo abierto?" conteste la verdad.
    return _cacheado("maquina", 15, armar) or ""


# ══════════════════════════════════════════════════════════════
#  Qué versión del código corre
# ══════════════════════════════════════════════════════════════
def build() -> dict:
    def calcular():
        aqui = Path(__file__).resolve().parent
        h = hashlib.sha256()
        ultima = 0.0
        for ruta in sorted(aqui.glob("*.py")):
            try:
                h.update(ruta.name.encode())
                h.update(ruta.read_bytes())
                ultima = max(ultima, ruta.stat().st_mtime)
            except Exception:
                continue
        return {"hash": h.hexdigest()[:8],
                "fecha": datetime.fromtimestamp(ultima).strftime("%d/%m %H:%M") if ultima else "?"}

    if "build" not in _cache:
        _cache["build"] = (time.monotonic(), calcular())
    return _cache["build"][1]


# ══════════════════════════════════════════════════════════════
#  Qué subsistemas están vivos de verdad
# ══════════════════════════════════════════════════════════════
def _docs_indexados() -> int:
    try:
        con = sqlite3.connect(str(CONFIG_DIR / "rag.db"))
        n = con.execute("select count(*) from docs").fetchone()[0]
        con.close()
        return int(n)
    except Exception:
        return 0


def _cuenta_json(nombre, clave=None) -> int:
    try:
        datos = json.loads((CONFIG_DIR / nombre).read_text())
        if clave:
            datos = datos.get(clave, [])
        return len(datos)
    except Exception:
        return 0


def estado() -> dict:
    def mirar():
        import config
        c = config.load()
        return {
            "modelo": c.get("model", "?"),
            "proveedor": c.get("provider", "?"),
            "cerebro_ok": bool(c.get("api_key")),
            "voz": c.get("tts", "?"),
            "voz_id": c.get("kokoro_voice", ""),
            "whisper": c.get("whisper_size", "?"),
            "wake": bool(c.get("wake_enabled")),
            "claude": bool(shutil.which("claude")),
            "docs": _docs_indexados(),
            "protocolos": _cuenta_json("protocols.json"),
            "agenda": _cuenta_json("agenda.json"),
            "recuerdos": _cuenta_json("memory.json"),
        }

    return _cacheado("estado", 60, mirar) or {}


def de_si_misma() -> str:
    def armar():
        e = estado()
        b = build()

        # En prosa corrida y a propósito: si esto va con viñetas, el modelo
        # copia el formato y contesta con una lista, que hablada es un ladrillo.
        partes = [
            f"Te llamas BLUE. No eres ningún modelo comercial con otro nombre: no hay "
            f"GPT ni Claude haciéndose pasar por ti. Dentro del escalafón que montó "
            f"Wilmer eres PROMETEO, la voz. Por debajo piensas con "
            f"{e.get('modelo', '?')} a través de {e.get('proveedor', '?')}, pero eso es "
            f"fontanería: cuando te pregunte qué cerebros tenéis, qué motores hay o con "
            f"qué trabajas, la respuesta son los nombres del escalafón, nunca el modelo.",

            "Manejas su escritorio entero: abres y cierras aplicaciones, mueves y "
            "enfocas ventanas, cambias de escritorio, subes el volumen y el brillo, "
            "lees y escribes el portapapeles, tomas capturas y puedes apagar el "
            "equipo. También ves su pantalla cuando hace falta mirar algo.",

            f"Guardas sus proyectos y protocolos, y los ejecutas cuando te los pide; "
            f"ahora mismo tienes {e.get('protocolos', 0)} protocolos. Buscas en "
            f"internet y abres páginas. Llevas su agenda y su correo, con "
            f"{e.get('agenda', 0)} cosas agendadas. Y recuerdas cosas suyas entre "
            f"conversaciones: llevas {e.get('recuerdos', 0)} apuntadas.",

            "Haces ingeniería de verdad y en local: conviertes unidades, sacas "
            "propiedades termodinámicas y resuelves termo, fluidos, transferencia de "
            "calor y estructural, además de gráficas. Es instantáneo y gratis, así "
            "que nunca mandes una cuenta de ingeniería a una tarea pesada.",

            f"Tienes sus apuntes y documentos indexados, {e.get('docs', 0)} ahora "
            f"mismo, y respondes a partir de ellos cuando pregunta por su material.",

            "Para trabajo pesado de programación delegas en Claude Code: leer y "
            "editar archivos de un proyecto, correr tests, análisis FEM. Eso tarda "
            "minutos, así que avisas antes y avisas al terminar.",

            f"Wilmer te despierta con Super+J, o diciendo tu nombre si la escucha "
            f"continua está activa, que ahora {'sí' if e.get('wake') else 'no'} lo "
            f"está. Le oyes con Whisper {e.get('whisper', '?')} y le hablas con "
            f"{e.get('voz', '?')}"
            f"{', voz ' + e.get('voz_id') if e.get('voz_id') else ''}. Esperas a que "
            f"termine de hablar de verdad antes de contestar.",

            f"La versión del código que estás ejecutando es la {b['hash']}, "
            f"del {b['fecha']}.",
        ]
        lineas = ["\n".join(partes)]
        if not e.get("claude"):
            lineas.append("AVISO: Claude Code no está disponible ahora, así que no "
                          "prometas tareas pesadas de programación.")
        if not e.get("cerebro_ok"):
            lineas.append("AVISO: no hay clave del proveedor configurada.")
        return "\n".join(lineas)

    return _cacheado("si_misma", 60, armar) or ""


# ══════════════════════════════════════════════════════════════
#  El bloque que se pega al prompt
# ══════════════════════════════════════════════════════════════
def context_block() -> str:
    partes = []
    yo = de_si_misma()
    if yo:
        partes.append("\n\n== QUIÉN ERES Y QUÉ PUEDES ==\n" + yo)
    # El escalafón de motores: PROMETEO, ORFEO, ARGOS, ÍCARO, ÉREBO. Sin esto,
    # preguntada por sus cerebros contestaba "GPT y Claude", que es la
    # fontanería de debajo y no lo que Wilmer llama por su nombre.
    try:
        import cerebros
        bloque = cerebros.bloque_conciencia()
        if bloque:
            partes.append("\n\n== EL ESCALAFÓN: TUS MOTORES ==\n" + bloque)
    except Exception:
        pass
    maquina = de_la_maquina()
    if maquina:
        partes.append("\n\n== LA MÁQUINA DONDE VIVES (ahora mismo) ==\n" + maquina
                      + "\nSon datos reales de este momento. Úsalos si vienen a "
                        "cuento; no los recites porque sí.")
    return "".join(partes)


if __name__ == "__main__":
    print(context_block())
