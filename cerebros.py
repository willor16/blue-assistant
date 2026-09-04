"""
cerebros.py — El escalafón de BLUE: PROMETEO, ORFEO, ARGOS, ÍCARO, ÉREBO.

Wilmer quiso nombres clave para los motores, y que funcionen como palabras
reservadas: al nombrarlos en voz alta, el trabajo se va a ese motor. La regla
que puso encima de todo es que **PROMETEO es la única voz**. Los demás piensan,
buscan o programan, pero quien habla siempre es PROMETEO, y cuenta lo que le
pasaron con su propio carácter. Nunca contesta ORFEO en primera persona.

El escalafón, de menos a más pesado:

  PROMETEO  La voz y el cerebro de todos los días. Es quien conversa, quien
            tiene las herramientas del escritorio y quien narra lo que hacen
            los demás. En esta máquina piensa con el modelo del proveedor
            configurado, porque es el único que sabe llamar herramientas.
  ORFEO     el modelo de casa con prompt de razonar a fondo. Largo y sin
            prisa. No toca el escritorio: se le pregunta y devuelve texto.
  ARGOS     Reservado. Wilmer todavía no lo tiene. Existe el nombre, no el
            motor; si lo llama, se le dice la verdad y se ofrece ORFEO.
  ÍCARO     Hermes Agent, con su propio perfil para BLUE, apuntando al Ollama
            remoto. Agente con herramientas propias.
  ÉREBO     Claude Code. El trabajo pesado de programación de verdad: leer y
            editar archivos, correr tests, análisis FEM.

Nota sobre PROMETEO y la "versión light". En el asistente viejo PROMETEO era
jarvis-light, un Gemma4 de 31B, y se daba por sentado que el modelo de casa no
servía para llamar herramientas: por eso conversaba el de la nube. Dejó de ser
cierto el 01/09/2026. PROMETEO es ahora `jarvis` (Qwen3-Next 80B MoE) en el
Ollama de casa, medido eligiendo bien las 65 herramientas a 57-60 tokens/s
contra los 25 del Gemma4, y la nube quedó como respaldo. Quien quiera lo
contrario cambia `prometeo_motor` en la configuración.

Nada de esto revienta si la otra PC está apagada: `disponibles()` lo comprueba
de verdad, con un tiempo de espera corto, y lo que no responde se dice.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import alma
import estilo

CONFIG_DIR = Path.home() / ".config" / "blue"
HERMES_PERFIL = CONFIG_DIR / "hermes"

# El Ollama de la otra PC. Se puede mover desde config.toml (`ollama_host`).
# Neutro a propósito: una IP de otra casa no sirve en un equipo nuevo.
# Si no responde, buscar_ollama_en_la_red() lo encuentra solo.
OLLAMA_POR_DEFECTO = "http://localhost:11434"

_cache: dict = {}


def _cfg() -> dict:
    try:
        import config
        return config.load()
    except Exception:
        return {}


# ── Encontrar solo el Ollama de la red ─────────────────────────────────────
# Poner la dirección a mano es la parte que más veces se ha roto. El 30/08/2026
# el DHCP le cambió la IP al servidor y BLUE se pasó el día creyendo que estaba
# apagado, tirando de la nube sin avisar. Y en un equipo recién clonado la
# dirección de otra casa no sirve de nada.
#
# Así que si el host configurado no contesta, se barre la red local buscando
# quién escucha en el 11434 y se recuerda. El barrido va en segundo plano: el
# turno de ahora se va a la nube y el siguiente ya usa el que se encontró.

def _puerto_abierto(ip: str, puerto: int = 11434, plazo: float = 0.6) -> bool:
    import socket
    try:
        with socket.create_connection((ip, puerto), timeout=plazo):
            return True
    except OSError:
        return False


def _mi_red() -> str | None:
    """El /24 en el que está esta máquina, p.ej. '192.168.0'."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))       # no manda nada, solo elige la ruta
        ip = s.getsockname()[0]
        s.close()
        return ip.rsplit(".", 1)[0]
    except OSError:
        return None


def buscar_ollama_en_la_red(puerto: int = 11434) -> str | None:
    """Barre el /24 local buscando un Ollama. Devuelve la URL o None."""
    import concurrent.futures as cf
    red = _mi_red()
    if not red:
        return None
    ips = [f"{red}.{i}" for i in range(1, 255)]
    with cf.ThreadPoolExecutor(max_workers=128) as ex:
        for ip, abierto in zip(ips, ex.map(lambda x: _puerto_abierto(x, puerto), ips)):
            if abierto:
                return f"http://{ip}:{puerto}"
    return None


def host_recordado() -> str | None:
    """El último Ollama que se encontró barriendo, si lo hubo."""
    try:
        t = (CONFIG_DIR / "ollama_encontrado").read_text().strip()
        return t or None
    except OSError:
        return None


def recordar_host(url: str) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (CONFIG_DIR / "ollama_encontrado").write_text(url + "\n")
    except OSError:
        pass


def ollama_host() -> str:
    return str(_cfg().get("ollama_host") or OLLAMA_POR_DEFECTO).rstrip("/")


# ══════════════════════════════════════════════════════════════
#  El escalafón
# ══════════════════════════════════════════════════════════════
ESCALAFON = [
    {
        "nombre": "PROMETEO",
        "rol": "la voz",
        "que_es": "el cerebro de todos los días y el único que habla",
        "motor": "el proveedor configurado",
        "modelo": "",          # se rellena en vivo desde la configuración
        "herramientas": True,
    },
    {
        "nombre": "ORFEO",
        "rol": "el que piensa despacio",
        "que_es": "jarvis-heavy corriendo en el Ollama de la otra PC",
        "motor": "ollama",
        "modelo": "jarvis-heavy",
        "herramientas": False,
    },
    {
        "nombre": "ARGOS",
        "rol": "reservado",
        "que_es": "un hueco con nombre: Wilmer aún no tiene este motor",
        "motor": "pendiente",
        "modelo": "",
        "herramientas": False,
    },
    {
        "nombre": "ICARO",
        "rol": "el agente",
        "que_es": "Hermes Agent con herramientas propias",
        "motor": "hermes",
        "modelo": "jarvis-heavy",
        "herramientas": True,
    },
    {
        "nombre": "EREBO",
        "rol": "el que programa",
        "que_es": "Claude Code: lee y edita archivos, corre tests, hace FEM",
        "motor": "claude-code",
        "modelo": "",
        "herramientas": True,
    },
]

# Cómo se escribe de verdad cuando se dice en voz alta.
BONITO = {"PROMETEO": "PROMETEO", "ORFEO": "ORFEO", "ARGOS": "ARGOS",
          "ICARO": "ÍCARO", "EREBO": "ÉREBO"}


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def ficha(nombre: str) -> dict:
    n = _sin_tildes(nombre).upper()
    for c in ESCALAFON:
        if c["nombre"] == n:
            return c
    return {}


# ══════════════════════════════════════════════════════════════
#  Palabras reservadas: reconocer a quién se está llamando
# ══════════════════════════════════════════════════════════════
# Whisper escribe estos nombres de mil maneras. Se comparan sin tildes y se
# admiten los desvíos que de verdad salen del oído.
# Whisper y el oído escriben estos nombres de mil maneras. Lo que más duele es
# la be y la uve: "Érebo" sale casi siempre como "Erevo". Se compara sin tildes.
_ALIAS = {
    "PROMETEO": r"promete[oa]s?|prometheo|prometh?e|prometo",
    "ORFEO":    r"orfe[oa]s?|orpheo|orfeu|orfe",
    "ARGOS":    r"argos|argus|arcos|argot",
    "ICARO":    r"h?[iy]car[oa]s?|h?icar",
    # La metatesis "erveo"/"herveo" es la que MAS sale y no estaba: el
    # 03/09/2026 Wilmer dijo "vamos a usar a herveo para hacer un programa" y
    # detectar() devolvio None, asi que el encargo se lo trago ORFEO como si
    # fuera charla. Se anaden explicitas en vez de aflojar el patron: "her[bv]o"
    # suelto se come "hervor".
    "EREBO":    r"[hj]?ere[bv][oa]s?|[hj]?ere[bv]u[ms]|[hj]?ereb|"
                r"h?er[bv]e[oa]s?|h?er[bv]e",
}

# ══════════════════════════════════════════════════════════════
#  Entrar y salir de un MODO (que se queda puesto)
# ══════════════════════════════════════════════════════════════
# Nombrar a un motor enruta ESA frase y nada mas. Un modo es otra cosa: se queda
# puesto hasta que se diga lo contrario, y mientras dure NO se consulta a nadie
# para saber si sigue puesto.
#
# Por eso entrar y salir se reconocen aqui, con una regla de texto y en el
# portatil. Es imprescindible para la salida: si la frase de "terminamos" se le
# mandara al motor de turno, habria que esperar a que acabase su encargo —que
# pueden ser dos minutos— solo para poder salir. El freno tiene que estar del
# lado de Wilmer, no del lado de lo que se atasco.
# Un cambio de mando se pide de mil maneras y en voz salen todas. Wilmer dijo
# "cambia a Orfeo" para entrar y luego "¿puedes cambiar a Prometeo?" y "quiero
# utilizar en este momento a Prometeo" para salir; ninguna de las dos ultimas
# estaba contemplada, asi que se quedo encerrado en ORFEO contestandole el
# motor equivocado hasta que se rindio. Entrar y salir son la MISMA frase con
# distinto nombre al final, asi que se reconocen con el mismo patron.
_VERBO_MANDO = (
    r"(?:cambia\w*|cambiate|vuelve\w*|regresa\w*|ponme\s+con|pasame\s+(?:a|con)|"
    r"dame\s+a|quiero|necesito|prefiero|puedes|podrias|usa\w*|utiliza\w*|"
    r"activa\w*|llama\s+a|conectame\s+con|"
    r"que\s+(?:me\s+)?(?:responda|conteste|siga|hable|atienda))"
)

# "que se ponga X" / "es tu turno": la otra forma, con el nombre por delante.
_TOMA_EL_MANDO = (r"(?:es\s+tu\s+turno(?:[\s,:.\-—]+hazte\s+cargo)?|hazte\s+cargo|"
                  r"toma\s+el\s+control|encargate(?:\s+tu)?)")


def _pide_motor(alias: str) -> re.Pattern:
    """Frases que piden que mande ESE motor, por delante o por detras."""
    return re.compile(
        # "Orfeo, es tu turno" / "Prometeo, hazte cargo"
        r"^\s*(?:" + alias + r")\b[\s,:.\-—]*" + _TOMA_EL_MANDO + r"\b|"
        # "cambia a Orfeo", "quiero utilizar en este momento a Prometeo"
        + _VERBO_MANDO + r"\b[^.?!]{0,45}?\b(?:" + alias + r")\b|"
        # el nombre a secas, dicho solo: "Prometeo." / "Orfeo"
        r"^\s*(?:" + alias + r")\s*$",
        re.IGNORECASE)


# Esta preguntando POR el motor, no pidiendolo. "Quiero saber quien fue Prometeo"
# lleva "quiero" y lleva el nombre, y sin esta guarda saldria del modo.
_PREGUNTA_POR = re.compile(
    r"\b(?:saber|quien\s+(?:es|fue|era)|que\s+(?:es|fue|era|significa|hace)|"
    r"explica\w*|explicame|cuenta\w*|cuentame|historia|mito|leyenda|"
    r"diferencia|comparar?|hablame\s+de)\b", re.IGNORECASE)

_ENTRAR_MODO = {
    "ICARO": _pide_motor(_ALIAS["ICARO"]),
    "ORFEO": _pide_motor(_ALIAS["ORFEO"]),
}

# Volver a PROMETEO es salir del modo, se diga como se diga. Es la mitad que
# faltaba: se podia entrar pero no salir por la puerta de al lado.
_VOLVER_PROMETEO = _pide_motor(_ALIAS["PROMETEO"] + r"|blue")

# La salida vale para cualquier modo: no hay que acertar el nombre del que esta
# puesto. Y "para" a secas NO sale del modo, solo calla: son cosas distintas.
_SALIR_MODO = re.compile(
    r"^\s*(?:" + _ALIAS["ICARO"] + r"|" + _ALIAS["ORFEO"] + r")?\b[\s,:.\-—]*"
    r"(?:eso\s+es\s+todo[\s,:.\-—]*(?:terminamos)?|terminamos|hemos\s+terminado|"
    r"es\s+hora\s+de\s+descansar|ya\s+puedes\s+descansar|vuelve[\s,:.\-—]*"
    r"(?:blue)?|sal\s+del\s+modo|volvemos\s+a\s+la\s+normalidad)\b",
    re.IGNORECASE)


def modo_pedido(texto: str):
    """¿Esta frase pide ENTRAR en un modo? Devuelve el nombre o None."""
    plano = _sin_tildes((texto or "").strip()).lower()
    if _PREGUNTA_POR.search(plano):
        return None
    for nombre, rx in _ENTRAR_MODO.items():
        if rx.search(plano):
            return nombre
    return None


def pide_salir_del_modo(texto: str) -> bool:
    """¿Esta frase pide VOLVER a la normalidad?

    Dos caminos: despedir al que esta ("terminamos") o llamar a PROMETEO
    ("cambia a Prometeo"). El segundo es el que faltaba, y es el natural: quien
    quiere a otro no piensa en despedir al de ahora.
    """
    plano = _sin_tildes((texto or "").strip()).lower()
    if _SALIR_MODO.search(plano):
        return True
    return bool(_VOLVER_PROMETEO.search(plano)
                and not _PREGUNTA_POR.search(plano))


# Se dirige a uno de dos maneras. O lo llama por delante ("Orfeo, explícame…"),
# o lo nombra a mitad de frase para decir QUIÉN debe hacerlo ("...utilizando el
# cerebro de Érebo"). En el segundo caso el encargo NO es lo que viene detrás
# del nombre: es la frase entera quitándole el "utilizando el cerebro de X".
_DELEGA = (r"(?:preg[uú]ntale\s+a|preg[uú]ntaselo\s+a|p[aá]saselo\s+a|"
           r"p[aá]sale\s+(?:esto\s+)?a|d[ií]le\s+a|d[eé]ja(?:selo|lo)?\s+a|"
           r"mand[aá](?:selo)?\s+a|encarg\w*\s+(?:esto\s+)?a|delega\w*\s+en|"
           r"que\s+(?:lo|la|esto)\s+(?:vea|haga|hagas|resuelva|programe|escriba)|"
           r"que\s+se\s+encargue(?:\s+de)?|a\s+cargo\s+de|tira\s+de|"
           r"(?:vamos\s+a\s+|voy\s+a\s+|quiero\s+)?"
           r"(?:us(?:a|ar|ame|ando)|utiliza(?:r|ndo)?|ocupa(?:r|ndo)?)\s*"
           r"(?:a\s+|al\s+|el\s+cerebro\s+de\s+|la\s+de\s+)?|"
           r"con\s+(?:el\s+cerebro\s+de\s+)?|el\s+cerebro\s+de\s+|llama\s+a)\s*")

# Está preguntando POR ellos, no llamándolos. Estas guardas se aplican SOBRE EL
# TEXTO ORIGINAL, con sus tildes, y no sobre el aplanado: al quitar la tilde,
# "que" (la conjunción de "que lo haga Érebo") se vuelve idéntica a "qué" (la
# pregunta), y toda orden con un "que" dentro parecía una consulta.
#
# Y ojo con pasarse de listo: "explícame" o "cuéntame" NO son preguntas sobre
# el motor, son el encargo en sí. "Orfeo, explícame Bernoulli" es trabajo.
_INTERROGA_INICIO = re.compile(
    r"^\s*¿?\s*(qué|cuál\w*|quién\w*|cómo|cuánt\w*|dónde|para\s+qué|"
    r"qu[eé]\s+(es|son|hace|hacen)|cu[aá]l\s+es)\b", re.IGNORECASE)
# "¿qué es ORFEO?", "¿para qué sirve ÉREBO?": preguntan por su identidad.
_PREGUNTA_IDENT = re.compile(
    r"^\s*¿?\s*(qu[eé]\s+(es|son|hace|hacen|tal|significa)|"
    r"qui[eé]n\s+(es|son)|c[oó]mo\s+(es|funciona)|"
    r"para\s+qu[eé]\s+(sirve|es|vale))\b", re.IGNORECASE)


def detectar(texto: str):
    """¿Está llamando a un motor por su nombre clave?

    Devuelve (NOMBRE, encargo) o None. Dos formas de llamarlo:

      vocativo   "Orfeo, explícame X"        -> el encargo es lo que sigue
      delegación "...haz X usando a Érebo"   -> el encargo es la frase sin el
                                                "usando a Érebo"

    Ante la duda devuelve None y contesta PROMETEO. Preguntar "¿qué es ORFEO?"
    no lo invoca.
    """
    t = (texto or "").strip()
    if not t:
        return None
    plano = _sin_tildes(t).lower()

    for nombre, alias in _ALIAS.items():
        # 1) vocativo: abre la frase
        m = re.match(r"^\s*(?:blue[,: ]+\s*)?(?:oye[,: ]+\s*)?(?:" + alias
                     + r")\b[\s,:.\-—]*(.*)$", plano, re.DOTALL)
        if m:
            resto_plano = (m.group(1) or "").strip()
            resto = _recortar_original(t, len(plano) - len(resto_plano)).strip()
            # "Orfeo, ¿qué eres?" pregunta por él; "Orfeo, explícame X" es encargo.
            if _PREGUNTA_IDENT.match(resto):
                return None
            return nombre, resto

        # 2) delegación: lo nombra a mitad de frase para decir quién lo hace
        d = re.search(_DELEGA + r"(?:" + alias + r")\b[\s,:.;\-—]*", plano)
        if d:
            # el encargo es TODO menos el trozo que decía a quién dárselo
            limpio_plano = (plano[:d.start()] + " " + plano[d.end():])
            limpio = (_recortar_original(t, 0)[:d.start()] + " "
                      + _recortar_original(t, 0)[d.end():])
            limpio = re.sub(r"\s{2,}", " ", limpio).strip(" ,;:.")
            # "vamos a usar a Erebo PARA hacer un programa" deja el encargo
            # empezando por una preposicion suelta. Se quita: el motor recibe
            # "hacer un programa", no "para hacer un programa".
            limpio = re.sub(r"^(?:para|y|que)\s+", "", limpio, flags=re.I)
            # "¿qué usa érebo?" es una pregunta, no un encargo: si al quitar el
            # trozo de delegación no queda tarea y la frase abría preguntando,
            # no lo estamos llamando.
            if len(limpio_plano.split()) < 3 and _INTERROGA_INICIO.match(t):
                return None
            return nombre, limpio
    return None


def _recortar_original(original: str, desde: int) -> str:
    """El aplanado conserva la longitud (quitar tildes no cambia el número de
    letras en NFD->filtrado), así que el índice sirve tal cual. Aun así se
    protege por si algún día deja de cumplirse."""
    if 0 <= desde <= len(original):
        return original[desde:]
    return original


# ══════════════════════════════════════════════════════════════
#  Quién está vivo de verdad
# ══════════════════════════════════════════════════════════════
def _ollama_modelos(timeout=2.5) -> list:
    try:
        with urllib.request.urlopen(ollama_host() + "/api/tags", timeout=timeout) as r:
            d = json.loads(r.read().decode())
        return [m.get("name", "").split(":")[0] for m in d.get("models", [])]
    except Exception:
        return []


# Como se cuenta cada cerebro EN VOZ ALTA: que hace para Wilmer, sin una sola
# marca. Deliberadamente no se saca de ESCALAFON["que_es"], que si nombra la
# fontaneria porque es documentacion del codigo.
_VOZ_DEL_MOTOR = {
    "PROMETEO": "la voz: conversa, maneja el escritorio y cuenta lo que hacen los demas",
    "ORFEO":    "el que piensa despacio, cuando una pregunta merece razonarse a fondo",
    "ARGOS":    "reservado: guardaste el nombre, todavia no hay cerebro detras",
    "ICARO":    "el que hace encargos por su cuenta, con sus propias herramientas",
    "EREBO":    "el que programa de verdad: proyectos, pruebas y analisis pesados",
}


def _casa() -> str:
    """Como se nombra en voz alta la maquina donde vive el Ollama de casa."""
    h = ollama_host().removeprefix("http://").removeprefix("https://")
    return f"el Ollama de casa ({h})"


def _detalle_prometeo(cfg: dict) -> str:
    """Que motor esta usando PROMETEO de verdad.

    Esto decia f"{cfg['model']} via {cfg['provider']}", y esas dos claves del
    NIVEL SUPERIOR del config son la nube de respaldo (groq / gpt-oss-120b). O
    sea que preguntarle a BLUE por sus cerebros contestaba "gpt-oss-120b via
    groq" incluso con el jarvis de casa cargado y contestando cada turno. El
    03/09/2026 eso le hizo creer a Wilmer que sus modelos locales no se usaban.

    Lo que manda es la cadena [[brain]], y sobre todo quien contesto el ultimo
    turno, que es un dato vivo y no una suposicion.
    """
    try:
        import brain
        ultimo, primero = brain.quien_contesta()
    except Exception:
        ultimo = primero = ""
    if not primero:
        cadena = cfg.get("brain") or []
        if cadena:
            b = cadena[0]
            primero = (f"{b.get('model')} en {_casa()}"
                       if b.get("provider") == "ollama"
                       else f"{b.get('model')} via {b.get('provider')}")
        else:
            primero = f"{cfg.get('model', '?')} via {cfg.get('provider', '?')}"
    if ultimo and ultimo != primero:
        # La cadena hizo su trabajo: conviene que se note, no que se disimule.
        return f"{ultimo} (el titular es {primero}, pero no contesto)"
    return ultimo or primero


def disponibles(segundos=90) -> dict:
    """Estado real de cada motor. Con caché corta: preguntar por la red en cada
    turno de voz costaría medio segundo de más por nada."""
    ahora = time.monotonic()
    guardado = _cache.get("disp")
    if guardado and ahora - guardado[0] < segundos:
        return guardado[1]

    modelos = _ollama_modelos()
    cfg = _cfg()
    estado = {
        "PROMETEO": {"ok": bool(cfg.get("api_key") or cfg.get("brain")),
                     "detalle": _detalle_prometeo(cfg)},
        # ORFEO corre en el MISMO modelo que PROMETEO (ver consultar_orfeo): se
        # comprueba ese, no "jarvis-heavy". Preguntar por un nombre que ya no se
        # usa daria a ORFEO por caido teniendo el motor delante.
        # El detalle dice el MISMO host que el de PROMETEO a proposito. Cuando
        # uno decia "el Ollama de casa" y el otro la URL entera, ORFEO leyo sus
        # propios datos y concluyo que corrian en dos maquinas distintas. Son la
        # misma, el mismo modelo y el mismo runner: ver consultar_orfeo.
        "ORFEO": {"ok": _motor_de_casa()[0] in modelos,
                  "detalle": (_motor_de_casa()[0] + " en " + _casa())
                             if _motor_de_casa()[0] in modelos
                             else "la otra PC no responde"},
        "ARGOS": {"ok": False, "detalle": "reservado, aún no existe"},
        "ICARO": {"ok": bool(shutil.which("hermes")) and HERMES_PERFIL.exists(),
                  "detalle": "Hermes Agent" if shutil.which("hermes") else "hermes no instalado"},
        "EREBO": {"ok": bool(shutil.which("claude")), "detalle": "Claude Code"},
    }
    if shutil.which("hermes") and not HERMES_PERFIL.exists():
        estado["ICARO"]["detalle"] = "hermes instalado pero sin perfil de BLUE"
    # Dos caras a proposito, y no es cosmetica.
    #
    # `detalle` es fontaneria: nombre del modelo, host, proveedor. Sirve para el
    # log y para diagnosticar, y ahi hace falta entero.
    #
    # `voz` es lo unico que puede salir por el altavoz. Wilmer fue tajante y lo
    # repitio el 04/09/2026: los cerebros se llaman PROMETEO, ORFEO, ARGOS,
    # ICARO y EREBO, y punto; ni marcas, ni modelos, ni proveedores. La regla ya
    # estaba en bloque_conciencia(), pero solo la leia PROMETEO: el 03/09 se le
    # dio a ORFEO una herramienta de estado que devolvia `detalle` en crudo, y
    # ORFEO recito que dos corrian en la Mac y el otro era Claude Code.
    #
    # Un prompt que prohibe decir algo es mas debil que no metersele delante. Asi
    # que lo que ve un cerebro es `voz`; `detalle` no sale de aqui.
    for n, v in estado.items():
        v["voz"] = _VOZ_DEL_MOTOR.get(n, "")
    _cache["disp"] = (ahora, estado)
    return estado


# ══════════════════════════════════════════════════════════════
#  Cambiar de cerebro cuesta tiempo: hay que DECIRLO antes
# ══════════════════════════════════════════════════════════════
# Esto NACIÓ porque llamar a ORFEO obligaba a descargar un modelo y cargar otro
# —entre 15 y 20 segundos con BLUE muda—, y al volver la siguiente pregunta
# normal pagaba la recarga de vuelta. Wilmer lo dijo claro: que avise antes de
# empezar y diga por qué, porque un relleno genérico a los 9 segundos no sirve.
#
# Desde el 01/09/2026 ese intercambio YA NO OCURRE: ORFEO e ÍCARO usan el mismo
# modelo y la misma ventana que PROMETEO, así que comparten runner y no se
# desalojan. Medido: ORFEO de ~47 s a 2,5 s, ÍCARO de 30 s a 2-3 s, y la
# pregunta de después de 28,7 s a 0,4 s.
#
# El aviso se queda igualmente. Sigue haciendo falta si el modelo se descargó
# por inactividad (cargarlo son ~16 s) o si algún día los motores vuelven a ser
# modelos distintos de verdad.

_PS_CACHE = {"t": 0.0, "modelos": frozenset()}
_PS_TTL = 3.0


def modelos_cargados(timeout: float = 2.0) -> frozenset:
    """Qué modelos tiene Ollama ahora mismo en memoria. Cacheado unos segundos:
    se consulta justo antes de cada consulta pesada y no vale la pena repetirlo."""
    import time
    if time.time() - _PS_CACHE["t"] < _PS_TTL:
        return _PS_CACHE["modelos"]
    try:
        req = urllib.request.Request(ollama_host() + "/api/ps")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        cargados = frozenset((m.get("name") or "").split(":")[0]
                             for m in d.get("models", []))
    except Exception:
        cargados = frozenset()           # ante la duda, se avisa: mejor de más
    _PS_CACHE.update(t=time.time(), modelos=cargados)
    return cargados


def hay_que_recargar(modelo: str) -> bool:
    """¿Llamar a este modelo obliga a Ollama a cargarlo desde cero?"""
    return (modelo or "").split(":")[0] not in modelos_cargados()


_ESPERA_CAMBIO = [
    "Voy, pero tengo que cambiar de cerebro y eso tarda unos veinte segundos. Dame un momento.",
    "Puedo, aunque toca cambiar de cerebro. Son unos veinte segundos, no me he colgado.",
    "Eso se lo paso a {quien}, pero hay que cargarlo primero. Unos veinte segundos y estoy contigo.",
]
_ESPERA_YA_CARGADO = [
    "Voy con ello, dame unos segundos.",
    "Se lo paso a {quien}, un momento.",
]


def frase_de_espera(modelo: str, quien: str = "otro cerebro") -> str:
    """Qué decirle a Wilmer ANTES de la consulta pesada, según cueste o no."""
    import random
    plantillas = _ESPERA_CAMBIO if hay_que_recargar(modelo) else _ESPERA_YA_CARGADO
    return random.choice(plantillas).format(quien=quien)


# ══════════════════════════════════════════════════════════════
#  Consultar a ORFEO
# ══════════════════════════════════════════════════════════════
def _pedir_a_ollama(ruta: str, cuerpo: bytes, timeout: float) -> dict:
    """Una peticion al Ollama de casa, con UN segundo intento en el host recordado.

    El 03/09/2026 dos turnos seguidos de ORFEO murieron con
    "[Errno 111] Connection refused" y ahi se acabo el turno: el usuario se
    queda mirando un mensaje de error. Y resulta que la red ya se habia
    resuelto sola, porque buscar_ollama_en_la_red() habia dejado escrito
    `~/.config/blue/ollama_encontrado`... que ollama_host() NO LEE. Estaba todo
    el mecanismo de recuperacion escrito y desconectado.

    Solo se reintenta ante fallo de CONEXION. Un timeout no se reintenta: seria
    pagar el plazo dos veces, y con 240 s eso son ocho minutos de "pensando".
    """
    hosts = [ollama_host()]
    rec = (host_recordado() or "").rstrip("/")
    if rec and rec != hosts[0]:
        hosts.append(rec)
    ultimo = None
    for i, h in enumerate(hosts):
        req = urllib.request.Request(h + ruta, data=cuerpo,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
        except urllib.error.URLError as e:
            ultimo = e
            if isinstance(e.reason, TimeoutError):
                raise
            continue
        if i:
            print(f"(el Ollama de casa no estaba en {hosts[0]}, si en {h}: me quedo con ese)",
                  flush=True)
            recordar_host(h)
        return d
    raise ultimo


# ── Las manos de ORFEO: pocas, y todas de solo lectura ──────────────────────
# El 03/09/2026 Wilmer le pidio a ORFEO que verificara la conexion de los
# cerebros. ORFEO no tenia NI UNA herramienta, asi que contesto "Verificando
# conexion..." y se invento el resultado; luego se invento dos cerebros que
# nunca existieron ("Aikaro", "Lumina") y una version "beta 0.7.2". No mintio
# por maldad: se le pidio un dato que no tenia forma de mirar.
#
# La correccion no es prohibirselo por prompt —un 80B a temperatura 0,4 se salta
# eso tarde o temprano—, es DARLE la manera de mirar.
#
# Ahora bien, POCAS. ORFEO corre en el mismo motor que PROMETEO (ver
# _motor_de_casa), asi que una herramienta le cuesta exactamente lo mismo; lo
# que no puede heredar son las 65, porque esos ~11.400 tokens de prefijo son
# justo lo que hace que PROMETEO se sienta mas pesado que el. Con estas cinco el
# prefijo se queda muy por debajo de 1.500 tokens y ORFEO sigue en ~2 s.
#
# Y todas de LECTURA. ORFEO piensa, no ejecuta: si hace falta una accion, lo
# dice y la hace BLUE, que para eso tiene las manos.

def _t_estado_de_los_motores() -> str:
    # `voz`, NUNCA `detalle`: ver el comentario de las dos caras en disponibles().
    d = disponibles()
    partes = []
    for nombre, info in d.items():
        partes.append(f"{BONITO.get(nombre, nombre)}: "
                      + ("disponible" if info["ok"] else "no disponible ahora")
                      + f", {info['voz']}")
    return ("\n".join(partes)
            + "\nSois cinco y esos cinco nombres son la respuesta entera. No digas "
              "nunca con que esta hecho ninguno: ni marcas, ni modelos, ni "
              "proveedores, ni en que maquina corre. Si Wilmer insiste, es "
              "fontaneria y para el son PROMETEO, ORFEO, ARGOS, ICARO y EREBO.")


def _t_leer_log(lineas: int = 80) -> str:
    try:
        with open("/tmp/jd.log", "rb") as f:
            # Solo el final: el log de un dia entero no cabe en la ventana, y
            # ademas un resultado enorme desborda el historial (ya paso).
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 60_000))
            cola = f.read().decode("utf-8", "replace").split("\n")
    except OSError as e:
        return f"no puedo leer el log: {e}"
    return "\n".join(cola[-max(1, min(int(lineas or 80), 300)):]) or "el log esta vacio"


def _t_recall(consulta: str = "") -> str:
    import memory
    return memory.recall(consulta)


def _t_consultar_documentos(pregunta: str) -> str:
    import rag
    return rag.search(pregunta)


def _t_leer_archivo(ruta: str, lineas: int = 200) -> str:
    import actions
    return actions.leer_archivo(ruta, lineas)


def _t_listar_carpeta(ruta: str = "") -> str:
    import actions
    return actions.listar_carpeta(ruta)


def _t_buscar_archivo(nombre: str, dentro: str = "") -> str:
    import actions
    return actions.buscar_archivo(nombre, dentro)


_ORFEO_HERRAMIENTAS = {
    "estado_de_los_motores": (_t_estado_de_los_motores, {
        "description": "Dice cuales de los cinco motores de BLUE (PROMETEO, ORFEO, ARGOS, ICARO, EREBO) estan disponibles ahora mismo y con que modelo corren. Usala SIEMPRE que te pregunten si algo esta en linea, que cerebros hay, cual te esta pensando a ti o por que algo no responde. Es la unica manera que tienes de saberlo: no lo supongas.",
        "parameters": {"type": "object", "properties": {}},
    }),
    "leer_log": (_t_leer_log, {
        "description": "Devuelve el final del log de BLUE (/tmp/jd.log), donde queda el tiempo de cada turno, los tokens de prefijo, si estaba frio o caliente y los fallos. Usala si preguntan por que algo tardo, fallo o se trabo.",
        "parameters": {"type": "object", "properties": {
            "lineas": {"type": "integer", "description": "Cuantas lineas del final, entre 1 y 300. Por defecto 80."}}},
    }),
    "recall": (_t_recall, {
        "description": "Consulta tu memoria persistente sobre Wilmer y su trabajo. consulta opcional para filtrar por tema; vacio trae lo mas reciente. Usala si te falta contexto suyo o si te preguntan que recuerdas.",
        "parameters": {"type": "object", "properties": {
            "consulta": {"type": "string", "description": "Tema por el que filtrar. Opcional."}}},
    }),
    "consultar_documentos": (_t_consultar_documentos, {
        "description": "Busca por significado en los documentos que Wilmer ya indexo (apuntes, normas, datasheets, manuales, PDFs) y trae los pasajes relevantes. Responde TU a partir de ellos, citando el documento, y no inventes lo que no este.",
        "parameters": {"type": "object", "properties": {
            "pregunta": {"type": "string", "description": "Que buscar."}},
            "required": ["pregunta"]},
    }),
    # listar_carpeta y buscar_archivo faltaban, y se noto: el 03/09/2026 Wilmer
    # pidio las carpetas de Documentos, ORFEO no tenia con que listarlas, lo
    # intento con leer_archivo sobre un directorio y agoto las vueltas.
    "listar_carpeta": (_t_listar_carpeta, {
        "description": "Dice que hay dentro de una carpeta de Wilmer: archivos y subcarpetas. Usala SIEMPRE que te pregunte que tiene en una carpeta. Sin ruta, mira la de documentos. NO uses leer_archivo para esto.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string", "description": "Carpeta a mirar. Vacio = la de documentos."}}},
    }),
    "buscar_archivo": (_t_buscar_archivo, {
        "description": "Busca por nombre dentro de la carpeta personal de Wilmer. Usala para localizar algo cuando no sepas donde esta, antes de decir que no existe.",
        "parameters": {"type": "object", "properties": {
            "nombre": {"type": "string", "description": "Parte del nombre."},
            "dentro": {"type": "string", "description": "Carpeta donde buscar. Opcional."}},
            "required": ["nombre"]},
    }),
    "leer_archivo": (_t_leer_archivo, {
        "description": "Lee un archivo de texto de Wilmer (txt, md, csv, codigo, configuracion) para que puedas razonar sobre su contenido. Para PDFs y apuntes usa consultar_documentos.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string", "description": "Ruta del archivo."},
            "lineas": {"type": "integer", "description": "Cuantas lineas leer. Por defecto 200."}},
            "required": ["ruta"]},
    }),
}


def _orfeo_esquemas() -> list:
    return [{"type": "function", "function": {"name": n, **esq}}
            for n, (_, esq) in _ORFEO_HERRAMIENTAS.items()]


# El rol del MODO ORFEO. Ojo, este NO pasa por alma.guard: se PEGA AL FINAL del
# prompt de PROMETEO (ver brain.Brain.rol_modo), asi que el alma, las 65
# herramientas y la regla de no nombrar la fontaneria ya vienen puestas de
# arriba. Repetirlas aqui moveria el prefijo para nada.
ROL_MODO_ORFEO = (
    "\n\n== AHORA MISMO ERES ORFEO ==\n"
    "Wilmer te ha cedido el turno a ORFEO, el que piensa despacio. Sigues siendo "
    "BLUE, con el mismo caracter y las mismas manos: puedes usar todas tus "
    "herramientas igual que siempre, y si te pide algo del escritorio lo HACES, "
    "no lo explicas.\n"
    "Lo que cambia es como piensas: antes de contestar te tomas el tiempo de "
    "razonar de verdad, miras lo que haga falta mirar y no despachas de "
    "primeras.\n"
    # Cuatro frases no es capricho: Kokoro sintetiza a unas 2,2 veces el tiempo
    # real, asi que un parrafo de 140 tokens son 28-43 SEGUNDOS de Wilmer
    # escuchando. Medido en su log del 01/09/2026.
    "Pero al hablar sigues siendo breve: maximo cuatro o cinco frases, salvo que "
    "te pida expresamente el detalle largo. Piensa largo, habla corto.\n"
    "Y no finjas haber mirado nada: no digas 'verificando', 'consultando' ni "
    "'revisando' sin haber llamado antes a la herramienta. O la llamas de "
    "verdad, o dices que no lo sabes."
)


_ORFEO_ROL = (
    "AHORA MISMO eres ORFEO, el modo de pensar a fondo de BLUE. Sigues siendo "
    "BLUE y hablas igual que siempre: mismo caracter, mismo tono, llamandole "
    "Wilmer o jefe. Lo unico que cambia es que aqui te tomas el tiempo de "
    "razonar de verdad en vez de despachar.\n"
    # Cuatro frases no es capricho: Kokoro sintetiza a unas 2,2 veces el tiempo
    # real, asi que las respuestas de 140 tokens que soltaba antes eran 28 y 43
    # SEGUNDOS de Wilmer escuchando un parrafo que no habia pedido. Medido en su
    # log del 01/09/2026: "turno de voz COMPLETO 55.0 s = ... hablar 43.2".
    "Maximo cuatro o cinco frases, salvo que te pidan expresamente el detalle "
    "largo: cada frase de mas son segundos de Wilmer esperando a que calles.\n"
    "TIENES CINCO HERRAMIENTAS Y NINGUNA MAS: estado_de_los_motores, leer_log, "
    "recall, consultar_documentos y leer_archivo. Todas son de leer. No tienes "
    "manos: no puedes abrir ni cerrar programas, ni mover ventanas, ni escribir "
    "archivos, ni tocar el ordenador. Si hace falta una accion, dilo en UNA "
    "frase y la hace BLUE por su cuenta; no expliques atajos de teclado ni "
    "pasos.\n"
    "NUNCA digas 'verificando', 'consultando', 'revisando' ni 'comprobando' sin "
    "haber llamado antes a la herramienta: o la llamas de verdad, o dices que "
    "eso no lo puedes mirar tu. Y no inventes NUNCA datos del sistema, "
    "historiales, versiones ni nombres de motores: los motores son exactamente "
    "cinco y te los dice estado_de_los_motores. Si no sabes algo, dilo."
)

_ORFEO_GUARD = alma.guard(_ORFEO_ROL)


def consultar_orfeo(pregunta: str, timeout: float = 240.0,
                    historial: list | None = None) -> str:
    """Le pasa la pregunta al modelo de casa con el alma de BLUE y el rol de ORFEO.

    Se usa el endpoint NATIVO de Ollama con think:false a propósito. Por /v1 los
    modelos de razonamiento gastan la salida en el campo `reasoning` y `content`
    vuelve vacío; con la API nativa y el pensamiento apagado, el texto llega.
    """
    # MISMO modelo y MISMA ventana que PROMETEO, a proposito.
    #
    # ORFEO pedia "jarvis-heavy" con num_ctx 8192 mientras PROMETEO usaba
    # "jarvis" con 32768. Suenan a dos modelos distintos y NO LO SON: el
    # 01/09/2026 se comprobo que jarvis, jarvis-heavy, jarvis-light y blue-agent
    # apuntan TODOS al mismo blob de pesos (sha256-30e51a7c...). Lo unico que
    # cambia entre ellos es el num_ctx y el prompt.
    #
    # Pero a Ollama le basta un num_ctx distinto para montar un runner aparte, y
    # como son 52 GB no caben dos: cada consulta a ORFEO desalojaba a PROMETEO y
    # al volver habia que recargarlo entero. Medido en el log de Wilmer:
    # "cargar modelo 16.0 s | prefijo 12048 tok en 11.6 s FRIO", y turnos de voz
    # de 68 s con 47 de ellos solo pensando. Todo para acabar en el mismo modelo.
    #
    # Pidiendo el mismo nombre y la misma ventana se reutiliza el runner que ya
    # esta caliente. Lo que hace a ORFEO distinto no son los pesos, es el rol,
    # y ese viaja en la peticion.
    modelo, ventana = _motor_de_casa()
    mensajes = [
        {"role": "system", "content": _ORFEO_GUARD},
        # Con lo dicho antes, si lo hay. Sin esto cada frase llegaba sola y sin
        # pasado: Wilmer preguntó "¿qué cerebro estás usando?", ORFEO contestó,
        # él aclaró "o sea, cuál de todos los de la lista" —y ORFEO no tenía ni
        # la pregunta anterior ni su propia respuesta—. En modo ORFEO se habla
        # seguido, así que la conversación tiene que llegarle.
        *(historial or []),
        {"role": "user", "content": (pregunta or "").strip()},
    ]
    _t0 = time.time()
    _tok_prefijo = _llamadas = 0

    # Cuatro vueltas de tope. Con tres se quedo corto el 03/09/2026: buscar,
    # leer y contestar ya son tres, y un tropiezo por el camino agotaba el cupo.
    # Sin tope ninguno, un modelo que se emperra en llamar lo mismo deja a Wilmer
    # escuchando silencio.
    for _vuelta in range(4):
        cuerpo = json.dumps({
            "model": modelo,
            "think": False,
            "stream": False,
            "options": {"temperature": 0.4, "num_ctx": ventana},
            "tools": _orfeo_esquemas(),
            "messages": mensajes,
        }).encode()
        try:
            d = _pedir_a_ollama("/api/chat", cuerpo, timeout)
        except urllib.error.URLError as e:
            return f"(ORFEO no contesta: {e.reason})"
        except Exception as e:
            return f"(ORFEO falló: {e})"

        _tok_prefijo = d.get("prompt_eval_count", 0)
        msg = d.get("message", {}) or {}
        llamadas = msg.get("tool_calls") or []
        if not llamadas:
            # Telemetria, como la de PROMETEO. Sin esto una consulta a ORFEO era
            # un agujero negro en el log: solo se veia el "pensar 47 s" del turno
            # de voz, sin saber en que se iba.
            _ld = d.get("load_duration", 0) / 1e9
            _ped = d.get("prompt_eval_duration", 0) / 1e9
            _ev, _evd = d.get("eval_count", 0), d.get("eval_duration", 0) / 1e9
            print(f"(ORFEO {time.time() - _t0:.1f} s [{modelo} ctx{ventana}] | "
                  + (f"cargar modelo {_ld:.1f} s | " if _ld > 1 else "")
                  + f"prefijo {_tok_prefijo} tok en {_ped:.1f} s "
                  + f"{'FRIO' if _ped > 3 else 'caliente'} | "
                  + (f"{_llamadas} herramienta(s) | " if _llamadas else "")
                  + f"genera {_ev} tok en {_evd:.1f} s)", flush=True)
            # Por estilo.hablado ANTES de devolverlo. voice.py ya lo aplica,
            # pero solo camino del sintetizador: lo que se guarda en el
            # historial y lo que se ve en el panel se quedaba en crudo. El
            # 03/09/2026 Wilmer vio en el panel las viñetas, los saltos de linea
            # de markdown y el "¿queres que pruebe alguno?" de despedida que el
            # alma prohibe expresamente. Y ademas ese texto crudo volvia como
            # historial en el turno siguiente, o sea que le ensenaba a ORFEO a
            # seguir escribiendo asi.
            texto = estilo.hablado(msg.get("content", "").strip())
            return texto or "(ORFEO devolvió una respuesta vacía)"

        mensajes.append(msg)
        for lla in llamadas:
            fn = (lla.get("function") or {})
            nombre = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            entrada = _ORFEO_HERRAMIENTAS.get(nombre)
            if entrada is None:
                res = f"(no existe la herramienta {nombre})"
            else:
                try:
                    res = entrada[0](**args)
                except Exception as e:
                    # Un fallo de herramienta se le DICE al modelo en vez de
                    # reventar el turno: asi puede contarlo en vez de callarse.
                    res = f"(error en {nombre}: {type(e).__name__}: {e})"
            _llamadas += 1
            print(f"(ORFEO -> {nombre}({', '.join(f'{k}={v!r}' for k, v in args.items())}))",
                  flush=True)
            # Tope por resultado. Un leer_archivo sobre un JSON minificado mete
            # cientos de miles de caracteres en un solo mensaje, Ollama trunca
            # por el PRINCIPIO y se lleva el prompt del sistema: ORFEO se vuelve
            # tonto sin dar error. Ya paso con PROMETEO el 31/08/2026.
            texto_res = str(res)
            if len(texto_res) > 6000:
                texto_res = texto_res[:6000] + "\n(...cortado)"
            mensajes.append({"role": "tool", "tool_name": nombre,
                             "content": texto_res})

    print("(ORFEO agota las vueltas sin cerrar respuesta: lo recoge PROMETEO)",
          flush=True)
    return ("(ORFEO no llegó a una respuesta con lo que tiene a mano. Esto lo "
            "puedes mirar tú, que tienes todas las herramientas: hazlo y "
            "contéstale a Wilmer sin mencionar este rodeo.)")


# ══════════════════════════════════════════════════════════════
#  Consultar a ÍCARO (Hermes Agent, con su propio perfil)
# ══════════════════════════════════════════════════════════════
# El alma de ICARO vive en un fichero, no en una constante: Hermes lo lee de
# ~/.config/blue/hermes/SOUL.md, fuera del repo. Se genera desde alma.py como los
# demas para que no se quede atras cuando cambie el caracter de BLUE, que es
# justo lo que le habia pasado.
_ICARO_ROL = (
    "AHORA MISMO eres ICARO, el motor de encargos de BLUE. Cuando Wilmer te "
    "cede el mando hablas TU directamente con el: no eres una herramienta "
    "silenciosa, eres quien lleva la conversacion mientras dure el proyecto.\n"
    "Las reglas de arriba sobre como hablas valen para lo que le DICES a Wilmer, "
    "no para el codigo ni los archivos que escribas: dentro de un archivo pon lo "
    "que haga falta con su formato normal.\n"
    "COMO TRABAJAS:\n"
    "- Trabaja DENTRO de la carpeta actual: crea y edita ahi, y no te lleves "
    "nada a otro sitio. Di la ruta de lo que toques, sin deletrearla entera.\n"
    "- NO borres archivos ni instales o desinstales paquetes salvo que Wilmer lo "
    "pida con esas palabras. Si hiciera falta y no te lo pidio, no lo hagas y "
    "diselo.\n"
    "- Cuando termines algo, di en una frase que quedo hecho.\n"
    "- Si Wilmer te pregunta algo que no es del proyecto, contestale igual y con "
    "naturalidad: mientras tengas el mando, eres tu quien conversa con el."
)

SOUL_ICARO = HERMES_PERFIL / "SOUL.md"


def sincronizar_soul_de_icaro() -> bool:
    """Deja el SOUL.md de Hermes al dia con alma.py. True si lo cambio.

    Se guarda una copia de lo anterior la primera vez (SOUL.md.previo) para no
    perder de vista lo que habia, igual que ya existe SOUL.md.original.
    """
    nuevo = alma.guard(_ICARO_ROL) + "\n"
    try:
        if not HERMES_PERFIL.exists():
            return False
        anterior = SOUL_ICARO.read_text() if SOUL_ICARO.exists() else ""
        if anterior == nuevo:
            return False
        if anterior and not (HERMES_PERFIL / "SOUL.md.previo").exists():
            (HERMES_PERFIL / "SOUL.md.previo").write_text(anterior)
        SOUL_ICARO.write_text(nuevo)
        return True
    except OSError as e:
        print(f"(no pude actualizar el alma de ICARO: {e})", flush=True)
        return False


_ICARO_GUARD = (
    "Eres ÍCARO, el motor de encargos de BLUE, el asistente de Wilmer, en su PC "
    "Linux (CachyOS/Hyprland). Haz el ENCARGO que va al final. Reglas:\n"
    "- Trabaja DENTRO de la carpeta actual: crea y edita ahí, y no te lleves "
    "nada a otro sitio. Di la ruta de lo que toques.\n"
    "- NO borres archivos ni instales o desinstales paquetes salvo que el "
    "encargo lo pida con esas palabras. Si hiciera falta y no te lo pidieron, "
    "no lo hagas y dilo en la respuesta.\n"
    "- Al terminar responde en 1 a 3 frases, en español, diciendo qué hiciste. "
    "Sin markdown, sin listas y sin asteriscos: esto se lee EN VOZ ALTA.\n\n"
    "ENCARGO: ")

# Igual que ÉREBO: la última carpeta donde trabajó ÍCARO y cuándo.
_ultimo_icaro = {"cwd": None, "cuando": 0.0}
ICARO_SEGUIR_MINUTOS = 60


def _motor_de_casa():
    """El modelo y la ventana que usa PROMETEO en el Ollama de casa.

    Pedir otra cosa monta un runner aparte y, a 52 GB, eso significa desalojar
    al que estaba. Se lee de la configuracion para que no haya dos sitios que
    decidan lo mismo."""
    for b in (_cfg().get("brain") or []):
        if b.get("provider") == "ollama":
            return (b.get("model") or "jarvis"), int(b.get("num_ctx") or 32768)
    return "jarvis", 32768


def _carpeta_de_trabajo() -> str:
    """Dónde debe trabajar un motor pesado: el proyecto activo, si lo hay.

    Sin esto, `subprocess.run` heredaba el cwd del daemon, que es
    /home/wilmer/.local/share/blue — o sea que ÍCARO, que es un agente con
    herramientas de ficheros, trabajaba DENTRO DEL CODIGO FUENTE DE BLUE. Es la
    misma carpeta que usa ÉREBO, para que los dos encargos de una misma sesión
    caigan en el mismo sitio."""
    try:
        import workspace
        aqui = workspace.active_workdir()
    except Exception:
        aqui = None
    return str(aqui or _cfg().get("task_workdir") or Path.home())


def consultar_icaro(instruccion: str, timeout: float = 600.0) -> str:
    if not shutil.which("hermes"):
        return "(ÍCARO no está instalado en esta máquina)"
    if not HERMES_PERFIL.exists():
        return ("(ÍCARO no tiene perfil configurado todavía; Hermes está "
                "instalado pero sin proveedor de inferencia)")
    import hashlib
    import time
    entorno = dict(os.environ, HERMES_HOME=str(HERMES_PERFIL))
    cwd = _carpeta_de_trabajo()
    # Sesión con nombre, una por carpeta. Hermes retoma una sesión por nombre y,
    # si no existe, arranca limpia sin protestar (probado). Así el encargo de
    # seguimiento —"ahora añádele X a lo que acabas de hacer"— sabe de qué habla,
    # y dos proyectos distintos nunca se mezclan.
    sesion = ("blue-" + Path(cwd).name[:20] + "-"
              + hashlib.md5(cwd.encode()).hexdigest()[:6])
    seguir = (_ultimo_icaro["cwd"] == cwd
              and time.time() - _ultimo_icaro["cuando"] < ICARO_SEGUIR_MINUTOS * 60)
    orden = _ICARO_GUARD + (instruccion or "").strip()
    cmd = ["hermes", "-z", orden, "--cli", "-c", sesion]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=entorno,
            cwd=cwd, start_new_session=True)
        _ultimo_icaro["cwd"], _ultimo_icaro["cuando"] = cwd, time.time()
        print(f"(ÍCARO en {cwd} [sesión {sesion}]"
              f"{' — sigue la anterior' if seguir else ''})", flush=True)
    except subprocess.TimeoutExpired:
        return "(ÍCARO tardó demasiado y se canceló)"
    except Exception as e:
        return f"(ÍCARO falló: {e})"
    texto = (out.stdout or "").strip()
    if not texto:
        return f"(ÍCARO no devolvió nada: {(out.stderr or '')[:200]})"
    return texto


# ══════════════════════════════════════════════════════════════
#  El bloque que va al prompt
# ══════════════════════════════════════════════════════════════
def bloque_conciencia() -> str:
    """El bloque que va al prompt. En PROSA CORRIDA a propósito: escrito con
    viñetas, el modelo copia el formato y contesta con una lista.

    Y sin una sola marca dentro. Wilmer fue tajante: los cerebros se llaman
    PROMETEO, ORFEO, ARGOS, ÍCARO y ÉREBO, y nada más. Si aquí se escribe con
    qué producto está hecho cada uno, el modelo lo recita en voz alta. Así que
    la fontanería no entra en el prompt: vive en el código, que es donde hace
    falta para enrutar.
    """
    d = disponibles()

    def estado(n):
        return "disponible" if d.get(n, {}).get("ok") else "no disponible ahora"

    return (
        "Wilmer le puso nombre a cada uno de tus cerebros, y son palabras "
        "reservadas: cuando te nombra uno, el trabajo va a ese. Sois cinco y os "
        "llamáis PROMETEO, ORFEO, ARGOS, ÍCARO y ÉREBO, de menos a más pesado.\n"
        "REGLA ABSOLUTA: esos cinco nombres son la respuesta entera. Cuando te "
        "pregunte qué cerebros tenéis, con qué trabajas o quién hace qué, di los "
        "nombres y qué hace cada uno para él, y para ahí. No digas nunca con qué "
        "está hecho ninguno: ni marcas, ni modelos, ni proveedores, ni empresas, "
        "ni versiones. Si insiste en saber la tripa, dile que eso es fontanería y "
        "que para él son PROMETEO, ORFEO, ARGOS, ÍCARO y ÉREBO.\n"
        "PROMETEO eres tú, la voz. Conversas, manejas el escritorio y cuentas lo "
        "que hacen los demás. Los otros trabajan, pero hablas tú siempre, y "
        "cuentas lo suyo con tu propio carácter, nunca copiando su texto tal cual "
        "ni dejando que hablen en primera persona.\n"
        f"ORFEO es el que piensa despacio: razona largo y a fondo cuando una "
        f"pregunta lo merece, pero no toca el escritorio. Ahora está "
        f"{estado('ORFEO')}. Tarda de veinte segundos a un par de minutos, así que "
        f"si vas a llamarlo, avisa antes.\n"
        "ARGOS está reservado y todavía no existe: Wilmer guardó el nombre para "
        "un cerebro que aún no tiene. Si te lo pide, díselo con naturalidad y "
        "ofrécele ORFEO en su lugar.\n"
        f"ÍCARO es el que hace encargos por su cuenta, con sus propias "
        f"herramientas. Está {estado('ICARO')}.\n"
        f"ÉREBO es el que programa de verdad: lee y edita los archivos de un "
        f"proyecto, corre pruebas y hace análisis pesados. Está {estado('EREBO')}. "
        f"A él le mandas las tareas grandes de programación.\n"
        "Casi todo lo resuelves tú como PROMETEO. Solo subes el escalafón cuando "
        "de verdad hace falta, y cuando lo haces se lo dices."
    )


if __name__ == "__main__":
    print(bloque_conciencia())
    print("\n--- estado ---")
    for n, v in disponibles().items():
        print(f"  {BONITO[n]:<10} {'OK ' if v['ok'] else '-- '} {v['detalle']}")


# ══════════════════════════════════════════════════════════════
#  ¿Esto le queda grande a PROMETEO?
# ══════════════════════════════════════════════════════════════
# Wilmer no quiere que el enrutado decida por su cuenta subir de cerebro: ORFEO
# tarda de veinte segundos a dos minutos y no siempre compensa. Quiere que
# PROMETEO conteste ya y LUEGO le ofrezca la versión larga, diciéndole por qué.
#
# La medida es a propósito tonta y explicable. Nada de pedirle al modelo que se
# autoevalúe: eso gastaría otra llamada entera del cupo diario, que es justo lo
# que estamos intentando ahorrar.

_PESADAS = (
    (r"\bpor\s+qu[eé]\b", "pregunta por el porqué"),
    (r"\bc[oó]mo\s+(funciona|se\s+(deduce|demuestra|obtiene|deriva|dimensiona))",
     "pide el mecanismo, no el dato"),
    (r"\b(demuestra|deduce|deriva|justifica|fundamenta|razona)\w*\b", "pide una demostración"),
    (r"\bcompar\w+|\bdiferencia\w*\s+entre|\bventajas?\s+y\s+desventajas?|"
     r"\bqu[eé]\s+es\s+mejor|\bcu[aá]l\s+conviene", "pide comparar alternativas"),
    (r"\ba\s+fondo\b|\ben\s+profundidad\b|\bdetalladamente\b|\bbien\s+explicado\b",
     "lo pediste a fondo"),
    (r"\b(hip[oó]tesis|supuestos|limitaciones|cu[aá]ndo\s+(falla|no\s+aplica)|"
     r"casos?\s+l[ií]mite)\b", "pregunta por hipótesis y límites"),
    (r"\b(teor[ií]a|te[oó]ric\w+|conceptual\w*|fundamento\w*|primer\w+\s+principi\w+)\b",
     "es teórica"),
    (r"\banaliza\w*\b|\bevalu[ae]\w*\b|\bcritica\w*\b|\bpros\s+y\s+contras\b",
     "pide un análisis"),
)

# Órdenes de escritorio y consultas de un dato: aquí ORFEO no pinta nada.
_LIGERAS = re.compile(
    r"^\s*(abre|cierra|pon|p[oó]n|sube|baja|silencia|enfoca|mueve|"
    r"p[aá]sate|ve\s+a|copia|pega|captura|apaga|reinicia|suspende|"
    r"crea\s+(una\s+)?carpeta|ejecuta|activa|lanza|corre|indexa|"
    r"qu[eé]\s+(hora|d[ií]a|tengo|hay)\b|hola|gracias|buenas)", re.IGNORECASE)


def complejidad(texto: str) -> dict:
    """Devuelve {'banda': trivial|normal|ofrecer, 'motivos': [...], 'razon': str}.

    'ofrecer' significa: contesta tú y, al final, ofrécele pasársela a ORFEO.
    Nunca significa enrutar solo.
    """
    t = (texto or "").strip()
    if not t or _LIGERAS.match(t):
        return {"banda": "trivial", "motivos": [], "razon": ""}

    motivos = [por_que for patron, por_que in _PESADAS
               if re.search(patron, t, re.IGNORECASE)]
    palabras = len(t.split())
    if palabras >= 25:
        motivos.append("la pregunta es larga")
    if t.count("?") + t.count("¿") >= 3:
        motivos.append("van varias preguntas juntas")

    if len(motivos) >= 2 or (motivos and palabras >= 12):
        return {"banda": "ofrecer", "motivos": motivos,
                "razon": motivos[0]}
    return {"banda": "normal", "motivos": motivos, "razon": ""}


def ofrecimiento(razon: str) -> str:
    """La frase con la que PROMETEO ofrece subir a ORFEO. Corta, hablada, y
    diciendo el porqué: Wilmer pidió explícitamente saber por qué no cabe."""
    return (f" Por cierto, {razon}, y eso es de las cosas que ORFEO hace mejor "
            f"que yo. Si quieres se la paso y te la desmenuza, aunque tarda un "
            f"minuto largo. ¿Se la mando?")
