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
# Whisper y el oído escriben estos nombres de mil maneras. Lo que más duele es
# la be y la uve: "Érebo" sale casi siempre como "Erevo". Se compara sin tildes.
_ALIAS = {
    "PROMETEO": r"promete[oa]s?|prometheo|prometh?e|prometo",
    "ORFEO":    r"orfe[oa]s?|orpheo|orfeu|orfe",
    "ARGOS":    r"argos|argus|arcos|argot",
    "ICARO":    r"h?[iy]car[oa]s?|h?icar",
    "EREBO":    r"[hj]?ere[bv][oa]s?|[hj]?ere[bv]u[ms]|[hj]?ereb",
}

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
#  Cambiar de cerebro cuesta tiempo: hay que DECIRLO antes
# ══════════════════════════════════════════════════════════════
# jarvis-light (20 GB) y jarvis-heavy (52 GB) no caben a la vez en la memoria
# de la Mac Studio, así que llamar a ORFEO obliga a Ollama a descargar uno y
# cargar el otro: entre 15 y 20 segundos en los que BLUE se quedaba MUDA. Y al
# volver, la siguiente pregunta normal pagaba la recarga de vuelta.
#
# Wilmer lo dijo claro: que le avise de que lo hará pero tardará. Un relleno
# genérico a los 9 segundos no sirve — para entonces ya lleva 9 segundos
# preguntándose si se colgó, y la frase no explica nada. Esto avisa ANTES de
# empezar y dice por qué.

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
