"""
texto.py — Limpieza de texto para pantalla y para voz.

Dos problemas distintos:

- **Emojis.** El modelo los mete solo, y el sintetizador no los ignora: los lee
  en voz, con su nombre entero, y arruina la frase. Se le pide al modelo que no
  los use, pero pedir no basta, así que se quitan también aquí. Y se quitan del
  texto que se enseña, no solo del que se habla, porque Wilmer no los quiere ver.

- **URLs y rutas.** Deletrear "hache te te pe ese dos puntos barra barra
  doble ve doble ve doble ve punto youtube punto com barra…" no es hablar. En
  voz, una URL se queda en su dominio y una ruta en su última carpeta:
  "abriendo youtube", "abriendo la carpeta Descargas".
"""

import re
import unicodedata

# Categorías Unicode que no son texto: símbolos varios (So), modificadores de
# símbolo (Sk) y formato invisible (Cf, el ZWJ que une los emojis compuestos).
_CATEGORIAS_FUERA = {"So", "Sk", "Cf"}

# Los selectores de variación (U+FE00-FE0F) son categoría Mn, NO Cf — di por
# hecho que caían con el resto y no: "⚠️" perdía el triángulo y dejaba el
# selector suelto, que el sintetizador se comía o leía. Van aparte.
# No se puede tirar todo Mn: en texto descompuesto, las tildes españolas
# también son Mn y se cargarían los acentos.
_INVISIBLES = set(range(0xFE00, 0xFE10)) | {0x200D, 0x20E3, 0xFE0F}

# Símbolos tipográficos que sí queremos conservar: no son emojis y se ven bien.
_SALVADOS = set("°±×÷–—―…‹›«»‘’“”†‡•·′″€$£¥¢©®™→←↑↓↔⇒⇔§¶")

# Comillas de todo tipo. En pantalla se quedan (se leen bien escritas); en voz
# se van, porque Kokoro las pronuncia: «cama» acaba sonando "comillas cama
# comillas". Incluye el acento grave, que también se lee.
_COMILLAS_RE = re.compile("[\"“”‘’«»„‹›`]")

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
# Una ruta entera de una pasada: las carpetas intermedias pueden llevar espacios
# ("asistente wilmer/"), el último tramo no, para no tragarse la frase siguiente.
_RUTA_RE = re.compile(r"(?:~/|/)(?:[\w.\- ]+/)*[\w.\-]+/?")


def sin_emojis(texto: str) -> str:
    """Quita emojis y pictogramas, deja la puntuación normal en paz."""
    if not texto:
        return ""
    fuera = []
    for c in texto:
        # ASCII nunca se toca. El acento grave es categoría Sk y sin esta línea
        # desaparecían los backticks del markdown; el circunflejo, igual.
        if ord(c) < 0x80 or c in _SALVADOS:
            fuera.append(c)
            continue
        if ord(c) in _INVISIBLES:
            continue
        if unicodedata.category(c) in _CATEGORIAS_FUERA:
            continue
        # Los bloques suplementarios de pictogramas no siempre caen en So.
        if ord(c) >= 0x1F000:
            continue
        fuera.append(c)
    # Un emoji suelto deja doble espacio donde estaba.
    return re.sub(r"[ \t]{2,}", " ", "".join(fuera)).strip()


def _nombre_de_url(m) -> str:
    """https://www.youtube.com/watch?v=xyz → youtube"""
    url = m.group(0)
    dominio = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    dominio = dominio.split("/")[0].lstrip("www.")
    partes = [p for p in dominio.split(".") if p not in ("com", "org", "net", "io",
                                                         "dev", "es", "mx", "co")]
    return partes[-1] if partes else dominio


def _nombre_de_ruta(m) -> str:
    """/home/wilmer/Descargas/asistente wilmer → asistente wilmer"""
    ruta = m.group(0).rstrip("/")
    hoja = ruta.split("/")[-1].strip()
    return hoja or "la carpeta"


def para_voz(texto: str) -> str:
    """
    Deja el texto como se debe decir en voz alta: sin emojis, sin markdown,
    sin código, y con las URLs y rutas reducidas a su nombre.
    """
    if not texto:
        return ""

    t = sin_emojis(texto)

    # Un bloque entero no se lee: se menciona. Pero `pacman -Syu` suelto sí
    # se dice — es el dato, no un ladrillo.
    t = re.sub(r"```[\s\S]*?```", " bloque de código ", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)

    # URLs y rutas, a su nombre.
    t = _URL_RE.sub(_nombre_de_url, t)
    t = _RUTA_RE.sub(_nombre_de_ruta, t)

    # Restos de markdown.
    t = re.sub(r"[*#_\[\]()]", " ", t)
    t = re.sub(r"^\s*[-–]\s+", " ", t, flags=re.MULTILINE)

    # Las comillas se ven bien escritas y suenan fatal dichas: Kokoro las
    # pronuncia ("comillas cama comillas"). En pantalla se quedan; aquí no.
    t = _COMILLAS_RE.sub("", t)

    # Un apóstrofo entre letras es parte de la palabra; el resto, fuera.
    t = re.sub(r"(?<![\w])'|'(?![\w])", "", t)

    # Escritura que no es la nuestra: fuera.
    #
    # El modelo de casa es Qwen3, entrenado con muchísimo chino, y de vez en
    # cuando se le cuela un token: el 01/09/2026 contestó "si necesitas que haga
    # algo具体" — dos ideogramas en mitad de una frase en español. Kokoro no
    # sabe leerlos y los pronuncia como puede, o se atasca. En pantalla se
    # quedarían, pero esto es solo para la voz.
    t = re.sub(r"[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef"
               r"\u0400-\u04ff\u0600-\u06ff\u0900-\u097f]+", " ", t)

    return re.sub(r"\s+", " ", t).strip()


def hay_emojis(texto: str) -> list:
    """
    Devuelve los caracteres no-texto que quedan. Sirve de red de seguridad.

    Existe por un fallo tonto y caro: durante un tiempo el propio prompt del
    sistema llevaba un emoji dentro de la regla que decía "no uses emojis", y
    el modelo lo copiaba. Con esto se comprueba en el arranque en vez de
    descubrirlo por el altavoz.
    """
    return [c for c in (texto or "")
            if ord(c) >= 0x80 and c not in _SALVADOS
            and (ord(c) in _INVISIBLES
                 or ord(c) >= 0x1F000
                 or unicodedata.category(c) in _CATEGORIAS_FUERA)]


# ── Prueba rápida ──
if __name__ == "__main__":
    pruebas = [
        "Listo, jefe \U0001F60F ahora puedes fingir que lo hiciste tú.",
        "Abriendo https://www.youtube.com/watch?v=dQw4w9WgXcQ para ti 🎵",
        "Guardé el archivo en /home/wilmer/Descargas/asistente wilmer/ui.py",
        "Mira ~/Descargas y dime si está 👀",
        "Usa `pacman -Syu` y luego ```bash\nsudo reboot\n``` ✅",
        "Temperatura: 38°C — subió un 5% 👍🏽",
    ]
    for p in pruebas:
        print(f"  original : {p}")
        print(f"  pantalla : {sin_emojis(p)}")
        print(f"  voz      : {para_voz(p)}\n")
