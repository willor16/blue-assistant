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
    "EREBO":    r"[hj]?ere[bv][oa]s?|[hj]?ere[bv]u[ms]|[hj]?ereb",
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
_ENTRAR_MODO = {
    "ICARO": re.compile(
        r"^\s*(?:" + _ALIAS["ICARO"] + r")\b[\s,:.\-—]*"
        r"(?:es\s+tu\s+turno(?:[\s,:.\-—]+hazte\s+cargo)?|hazte\s+cargo|"
        r"toma\s+el\s+control|encargate(?:\s+tu)?)\b", re.IGNORECASE),
    "ORFEO": re.compile(
        r"^\s*(?:" + _ALIAS["ORFEO"] + r")\b[\s,:.\-—]*"
        r"(?:es\s+tu\s+turno(?:[\s,:.\-—]+hazte\s+cargo)?|hazte\s+cargo|"
        r"toma\s+el\s+control|encargate(?:\s+tu)?)\b|"
        r"^\s*cambia(?:\s+de\s+cerebro)?\s+a\s+(?:" + _ALIAS["ORFEO"] + r")\b",
        re.IGNORECASE),
}

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
    for nombre, rx in _ENTRAR_MODO.items():
        if rx.search(plano):
            return nombre
    return None


def pide_salir_del_modo(texto: str) -> bool:
    """¿Esta frase pide VOLVER a la normalidad?"""
    plano = _sin_tildes((texto or "").strip()).lower()
    return bool(_SALIR_MODO.search(plano))


# Se dirige a uno de dos maneras. O lo llama por delante ("Orfeo, explícame…"),
# o lo nombra a mitad de frase para decir QUIÉN debe hacerlo ("...utilizando el
# cerebro de Érebo"). En el segundo caso el encargo NO es lo que viene detrás
# del nombre: es la frase entera quitándole el "utilizando el cerebro de X".
_DELEGA = (r"(?:preg[uú]ntale\s+a|preg[uú]ntaselo\s+a|p[aá]saselo\s+a|"
           r"p[aá]sale\s+(?:esto\s+)?a|d[ií]le\s+a|d[eé]ja(?:selo|lo)?\s+a|"
           r"mand[aá](?:selo)?\s+a|encarg\w*\s+(?:esto\s+)?a|delega\w*\s+en|"
           r"que\s+(?:lo|la|esto)\s+(?:vea|haga|hagas|resuelva|programe|escriba)|"
           r"que\s+se\s+encargue(?:\s+de)?|a\s+cargo\s+de|tira\s+de|"
           r"(?:us(?:a|ame|ando)|utiliza(?:ndo)?|ocupa(?:ndo)?)\s*"
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
                     "detalle": f"{cfg.get('model', '?')} vía {cfg.get('provider', '?')}"},
        # ORFEO corre en el MISMO modelo que PROMETEO (ver consultar_orfeo): se
        # comprueba ese, no "jarvis-heavy". Preguntar por un nombre que ya no se
        # usa daria a ORFEO por caido teniendo el motor delante.
        "ORFEO": {"ok": _motor_de_casa()[0] in modelos,
                  "detalle": (_motor_de_casa()[0] + " en " + ollama_host())
                             if _motor_de_casa()[0] in modelos
                             else "la otra PC no responde"},
        "ARGOS": {"ok": False, "detalle": "reservado, aún no existe"},
        "ICARO": {"ok": bool(shutil.which("hermes")) and HERMES_PERFIL.exists(),
                  "detalle": "Hermes Agent" if shutil.which("hermes") else "hermes no instalado"},
        "EREBO": {"ok": bool(shutil.which("claude")), "detalle": "Claude Code"},
    }
    if shutil.which("hermes") and not HERMES_PERFIL.exists():
        estado["ICARO"]["detalle"] = "hermes instalado pero sin perfil de BLUE"
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
_ORFEO_GUARD = (
    "Eres ORFEO, el motor de razonamiento pesado de BLUE. Te llega una consulta "
    "de Wilmer a través de BLUE. Piensa a fondo y responde en español, en prosa "
    "corrida, sin listas, sin markdown, sin asteriscos y sin emojis, porque tu "
    "respuesta se va a leer en voz alta. Ve al grano: dos o tres párrafos como "
    "mucho. Si no sabes algo, dilo."
)


def consultar_orfeo(pregunta: str, timeout: float = 240.0) -> str:
    """Le pasa la pregunta al modelo de casa con el guard de ORFEO, en crudo.

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
    # esta caliente. Lo que hace a ORFEO distinto no son los pesos, es
    # _ORFEO_GUARD, y ese viaja en la peticion.
    modelo, ventana = _motor_de_casa()
    cuerpo = json.dumps({
        "model": modelo,
        "think": False,
        "stream": False,
        "options": {"temperature": 0.4, "num_ctx": ventana},
        "messages": [
            {"role": "system", "content": _ORFEO_GUARD},
            {"role": "user", "content": (pregunta or "").strip()},
        ],
    }).encode()
    _t0 = time.time()
    req = urllib.request.Request(ollama_host() + "/api/chat", data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except urllib.error.URLError as e:
        return f"(ORFEO no contesta: {e.reason})"
    except Exception as e:
        return f"(ORFEO falló: {e})"
    # Telemetria, como la de PROMETEO. Sin esto una consulta a ORFEO era un
    # agujero negro en el log: solo se veia el "pensar 47 s" del turno de voz,
    # sin poder saber si el tiempo se iba en cargar el modelo, en releer el
    # prefijo o en generar.
    _ld = d.get("load_duration", 0) / 1e9
    _ped = d.get("prompt_eval_duration", 0) / 1e9
    _ev, _evd = d.get("eval_count", 0), d.get("eval_duration", 0) / 1e9
    print(f"(ORFEO {time.time() - _t0:.1f} s [{modelo} ctx{ventana}] | "
          + (f"cargar modelo {_ld:.1f} s | " if _ld > 1 else "")
          + f"prefijo {d.get('prompt_eval_count', 0)} tok en {_ped:.1f} s "
          + f"{'FRIO' if _ped > 3 else 'caliente'} | "
          + f"genera {_ev} tok en {_evd:.1f} s)", flush=True)
    texto = (d.get("message", {}) or {}).get("content", "").strip()
    return texto or "(ORFEO devolvió una respuesta vacía)"


# ══════════════════════════════════════════════════════════════
#  Consultar a ÍCARO (Hermes Agent, con su propio perfil)
# ══════════════════════════════════════════════════════════════
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
