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
  ORFEO     jarvis-heavy en el Ollama de la otra PC. Razonamiento largo y sin
            prisa. No toca el escritorio: se le pregunta y devuelve texto.
  ARGOS     Reservado. Wilmer todavía no lo tiene. Existe el nombre, no el
            motor; si lo llama, se le dice la verdad y se ofrece ORFEO.
  ÍCARO     Hermes Agent, con su propio perfil para BLUE, apuntando al Ollama
            remoto. Agente con herramientas propias.
  ÉREBO     Claude Code. El trabajo pesado de programación de verdad: leer y
            editar archivos, correr tests, análisis FEM.

Nota sobre PROMETEO y la "versión light". En el asistente viejo PROMETEO era
literalmente jarvis-light, porque ahí el modelo local era el que conversaba.
Aquí el que conversa es el del proveedor en la nube, que es el único con las
53 herramientas; bajarlo a jarvis-light dejaría a BLUE sin manos. Así que
PROMETEO conserva su papel — la voz, el que habla contigo — y no su modelo.
Quien quiera lo contrario cambia `prometeo_motor` en la configuración.

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
OLLAMA_POR_DEFECTO = "http://192.168.0.22:11434"

_cache: dict = {}


def _cfg() -> dict:
    try:
        import config
        return config.load()
    except Exception:
        return {}


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
_ALIAS = {
    "PROMETEO": r"promete[oa]s?|prometheo",
    "ORFEO":    r"orfe[oa]s?|orpheo|orfe",
    "ARGOS":    r"argos|argus|arcos",
    "ICARO":    r"icar[oa]s?|ycaro",
    "EREBO":    r"[hj]?ereb[oa]s?|erebu[ms]",
}

# Se dirige a uno: al principio de la frase, o detrás de un verbo de encargo.
_ENCARGO = (r"(?:preg[uú]ntale\s+a|preg[uú]ntaselo\s+a|p[aá]saselo\s+a|"
            r"p[aá]sale\s+esto\s+a|d[ií]le\s+a|que\s+lo\s+vea|que\s+lo\s+haga|"
            r"con\s+|usa\s+a|usa\s+|llama\s+a|que\s+se\s+encargue|"
            r"delega\w*\s+en|mand[aá]selo\s+a|tira\s+de)\s*")

# Está preguntando POR ellos, no llamándolos. "qué cerebros tenemos",
# "explícame lo de ORFEO", "quién es ÍCARO". Eso lo contesta PROMETEO.
_PREGUNTA_POR = re.compile(
    r"\b(qu[eé]|cu[aá]l\w*|qui[eé]n\w*|c[oó]mo|cu[aá]nto\w*|expl[ií]ca\w*|"
    r"cu[eé]nta\w*|dime|list\w*|res[uú]me\w*|para\s+qu[eé]|diferencia\w*|"
    r"tenemos|tienes|hay|existe\w*|sirve\w*|es\s+mejor)\b", re.IGNORECASE)


def detectar(texto: str):
    """¿Está llamando a un motor por su nombre clave?

    Devuelve (NOMBRE, resto_de_la_frase) o None. Es deliberadamente estricto:
    ante la duda devuelve None y contesta PROMETEO, que es lo que Wilmer quiere
    el 90 por ciento de las veces. Preguntar "¿qué es ORFEO?" no lo invoca.
    """
    t = (texto or "").strip()
    if not t:
        return None
    plano = _sin_tildes(t).lower()

    for nombre, alias in _ALIAS.items():
        # al principio: "orfeo, ¿cuánto...?"  |  "blue, orfeo: ..."
        m = re.match(r"^\s*(?:blue[,: ]+\s*)?(?:oye[,: ]+\s*)?(?:" + alias
                     + r")\b[\s,:.\-—]*(.*)$", plano, re.DOTALL)
        if not m:
            # detrás de un verbo de encargo: "pregúntale a orfeo cuánto..."
            m = re.search(_ENCARGO + r"(?:" + alias + r")\b[\s,:.\-—]*(.*)$",
                          plano, re.DOTALL)
        if not m:
            continue

        resto_plano = (m.group(1) or "").strip()
        # Si detrás no queda encargo y la frase es una pregunta sobre él,
        # no lo estamos llamando: nos están preguntando quién es.
        if not resto_plano and _PREGUNTA_POR.search(plano):
            return None
        if resto_plano and _PREGUNTA_POR.match(resto_plano):
            # "orfeo qué es" -> pregunta, no encargo
            if len(resto_plano.split()) <= 4:
                return None

        # Recortar sobre el texto ORIGINAL (con tildes y mayúsculas), no sobre
        # el aplanado: lo que se le manda al motor debe ir tal cual se dijo.
        resto = _recortar_original(t, len(plano) - len(resto_plano))
        return nombre, resto.strip()
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
        "ORFEO": {"ok": "jarvis-heavy" in modelos,
                  "detalle": ("jarvis-heavy en " + ollama_host()) if "jarvis-heavy" in modelos
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
    """Le pasa la pregunta a jarvis-heavy y devuelve su texto, en crudo.

    Se usa el endpoint NATIVO de Ollama con think:false a propósito. Por /v1 los
    modelos de razonamiento gastan la salida en el campo `reasoning` y `content`
    vuelve vacío; con la API nativa y el pensamiento apagado, el texto llega.
    """
    cuerpo = json.dumps({
        "model": "jarvis-heavy",
        "think": False,
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.4, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": _ORFEO_GUARD},
            {"role": "user", "content": (pregunta or "").strip()},
        ],
    }).encode()
    req = urllib.request.Request(ollama_host() + "/api/chat", data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except urllib.error.URLError as e:
        return f"(ORFEO no contesta: {e.reason})"
    except Exception as e:
        return f"(ORFEO falló: {e})"
    texto = (d.get("message", {}) or {}).get("content", "").strip()
    return texto or "(ORFEO devolvió una respuesta vacía)"


# ══════════════════════════════════════════════════════════════
#  Consultar a ÍCARO (Hermes Agent, con su propio perfil)
# ══════════════════════════════════════════════════════════════
def consultar_icaro(instruccion: str, timeout: float = 300.0) -> str:
    if not shutil.which("hermes"):
        return "(ÍCARO no está instalado en esta máquina)"
    if not HERMES_PERFIL.exists():
        return ("(ÍCARO no tiene perfil configurado todavía; Hermes está "
                "instalado pero sin proveedor de inferencia)")
    entorno = dict(os.environ, HERMES_HOME=str(HERMES_PERFIL))
    try:
        out = subprocess.run(
            ["hermes", "-z", (instruccion or "").strip(), "--cli"],
            capture_output=True, text=True, timeout=timeout, env=entorno,
            start_new_session=True)
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
    """En PROSA CORRIDA a propósito. Escrito con viñetas, el modelo copia el
    formato y contesta con una lista, que hablada es un ladrillo."""
    d = disponibles()

    def estado(n):
        return "disponible" if d.get(n, {}).get("ok") else "no disponible ahora"

    prometeo_det = d.get("PROMETEO", {}).get("detalle", "?")
    orfeo_det = d.get("ORFEO", {}).get("detalle", "?")

    return (
        "Wilmer le puso nombre clave a cada motor con el que trabajas, y son "
        "palabras reservadas: cuando te nombra uno, el trabajo va a ese. El "
        "escalafón va de menos a más pesado y es PROMETEO, ORFEO, ARGOS, ÍCARO "
        "y ÉREBO. Si te pregunta qué cerebros tenéis, qué motores hay o con qué "
        "trabajas, responde con estos nombres y lo que hace cada uno. No "
        "contestes nunca que eres GPT ni Claude: esos son piezas de debajo, no "
        "son la respuesta.\n"
        f"PROMETEO eres tú, la voz. Eres quien conversa, quien maneja el "
        f"escritorio y quien cuenta lo que hacen los demás; por debajo piensas "
        f"con {prometeo_det}. Los otros trabajan, pero hablas tú siempre, y "
        f"cuentas lo suyo con tu propio carácter, nunca copiando su texto tal "
        f"cual ni dejando que hablen en primera persona.\n"
        f"ORFEO es jarvis-heavy en el Ollama de la otra PC, para razonar largo "
        f"y sin prisa; ahora mismo está {estado('ORFEO')} ({orfeo_det}). No toca "
        f"el escritorio: se le pregunta y devuelve texto. Tarda de veinte "
        f"segundos a un par de minutos, así que si vas a llamarlo, avisa antes.\n"
        "ARGOS está reservado y todavía no existe: Wilmer guardó el nombre para "
        "un motor que aún no tiene. Si te lo pide, díselo con naturalidad y "
        "ofrécele ORFEO en su lugar.\n"
        f"ÍCARO es Hermes Agent, un agente con herramientas propias; está "
        f"{estado('ICARO')}.\n"
        f"ÉREBO es Claude Code, el que programa de verdad: lee y edita archivos "
        f"de un proyecto, corre tests y hace análisis FEM. Está {estado('EREBO')}. "
        f"Es a quien mandas las tareas pesadas de programación.\n"
        "Casi todo lo resuelves tú como PROMETEO. Solo subes el escalafón "
        "cuando de verdad hace falta, y cuando lo haces se lo dices."
    )


if __name__ == "__main__":
    print(bloque_conciencia())
    print("\n--- estado ---")
    for n, v in disponibles().items():
        print(f"  {BONITO[n]:<10} {'OK ' if v['ok'] else '-- '} {v['detalle']}")
