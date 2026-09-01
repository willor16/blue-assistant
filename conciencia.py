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
    """Qué suena ahora mismo, preguntándoselo al reproductor por MPRIS.

    Antes se lo preguntaba a `playerctl`, que no está instalado: `_cmd` se
    tragaba el FileNotFoundError y esto devolvía "" siempre. O sea que BLUE
    jamás supo qué estaba sonando, y no había forma de notarlo."""
    try:
        import actions
    except Exception:
        return ""
    player = actions._pick_player()
    if not player:
        return ""
    if actions._mpris_prop(player, "PlaybackStatus") != "Playing":
        return ""
    meta = actions._mpris_meta(player)
    titulo, artista = meta.get("title", ""), meta.get("artist", "")
    if titulo and artista:
        return f"{artista} - {titulo}"
    return titulo or ""


def _totales():
    """Cuánta RAM y cuánto disco tiene la máquina. No cuánto queda libre."""
    ram = disco = ""
    try:
        with open("/proc/meminfo") as f:
            for linea in f:
                if linea.startswith("MemTotal:"):
                    ram = f"{int(linea.split()[1]) / 1048576:.0f} GB de RAM"
                    break
    except Exception:
        pass
    try:
        disco = f"{shutil.disk_usage(str(Path.home())).total / 1e9:.0f} GB de disco"
    except Exception:
        pass
    return ram, disco


def de_la_maquina() -> str:
    """La parte de la máquina que NO cambia entre un turno y el siguiente.

    Todo lo vivo (carga, uptime, RAM libre, ventanas abiertas, lo que suena)
    se fue a la herramienta estado_maquina y NO viaja aquí. El motivo es de
    velocidad, no de estilo: este texto abre el prompt, y Ollama solo reutiliza
    su caché mientras el principio sea idéntico byte a byte. Con la carga de CPU
    metida aquí el prefijo cambiaba en cada turno, así que el modelo releía los
    ~6.400 tokens enteros cada vez: 25 s de peaje por frase. Si algo de aquí
    vuelve a moverse solo, vuelve el peaje."""
    def armar():
        nombre_so, kernel = _so()
        host = _cmd(["hostnamectl", "hostname"]) or os.uname().nodename
        ram, disco = _totales()

        lineas = [f"- Equipo: {host}"]
        if nombre_so:
            lineas.append(f"- Sistema: {nombre_so}" + (f", kernel {kernel}" if kernel else ""))
        if ram or disco:
            lineas.append("- Tiene: " + ", ".join(x for x in (ram, disco) if x))
        return "\n".join(lineas)

    # Una hora: nada de esto cambia sin reiniciar.
    return _cacheado("maquina", 3600, armar) or ""


def ahora_mismo() -> str:
    """El estado vivo de la máquina, para cuando Wilmer lo pregunte."""
    lineas = []
    for etiqueta, valor in (("Encendida desde hace", _uptime()),
                            ("Memoria", _memoria_ram()),
                            ("Disco", _disco()),
                            ("Carga", _carga())):
        if valor:
            lineas.append(f"- {etiqueta}: {valor}")
    linea_ws, apps = _escritorio()
    if linea_ws:
        lineas.append(f"- Ahora mismo: {linea_ws}")
    if apps:
        lineas.append(f"- Ventanas abiertas: {', '.join(apps)}")
    son = _sonando()
    if son:
        lineas.append(f"- Sonando: {son}")
    return "\n".join(lineas) or "No pude leer el estado de la máquina."


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


def _escucha_continua_real() -> bool:
    """Si hay un detector de palabra corriendo AHORA, no si está en el config."""
    try:
        import wakeword
        return bool(getattr(wakeword, "ACTIVO", False))
    except Exception:
        return False


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
            "wake": _escucha_continua_real(),
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
            "Te llamas BLUE y eres PROMETEO, la voz. No eres ningún producto "
            "comercial con otro nombre ni hay ninguna empresa hablando por ti. "
            "Cuando te pregunte qué cerebros tenéis, qué motores hay o con qué "
            "trabajas, la respuesta son los cinco nombres que te puso Wilmer y "
            "nada más: nunca una marca, un modelo ni un proveedor.",

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

            "Para trabajo pesado de programación delegas en ÉREBO: leer y "
            "editar archivos de un proyecto, correr pruebas, análisis FEM. Eso tarda "
            "minutos, así que avisas antes y avisas al terminar.",

            (f"Wilmer te despierta con Super+J, y además puedes seguirle la "
             f"conversación sin que tenga que pulsar nada entre turno y turno."
             if e.get('wake') else
             f"Wilmer te despierta manteniendo pulsado Super+J. La escucha "
             f"continua por palabra de activación NO está encendida, así que no "
             f"le digas que puedes despertarte sola al oír tu nombre.") +
            f" Le oyes con Whisper {e.get('whisper', '?')} y le hablas con "
            f"{e.get('voz', '?')}"
            f"{', voz ' + e.get('voz_id') if e.get('voz_id') else ''}. Esperas a que "
            f"termine de hablar de verdad antes de contestar.",

            f"La versión del código que estás ejecutando es la {b['hash']}, "
            f"del {b['fecha']}.",
        ]
        lineas = ["\n".join(partes)]
        if not e.get("claude"):
            lineas.append("AVISO: ÉREBO no está disponible ahora, así que no "
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
        partes.append("\n\n== LA MÁQUINA DONDE VIVES ==\n" + maquina
                      + "\nSi te preguntan por el estado de ahora (cuánta memoria "
                        "queda, cuánto lleva encendida, qué tienes abierto, qué "
                        "suena), llama a estado_maquina; eso cambia y no lo tienes "
                        "aquí. No recites estos datos porque sí.")
    return "".join(partes)


if __name__ == "__main__":
    print(context_block())
