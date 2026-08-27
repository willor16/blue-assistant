"""
estilo.py — Que la respuesta suene a alguien hablando, no a un documento.

El prompt le pide a BLUE que no use listas ni markdown, que empiece por la
respuesta y que termine cuando termina. Y aun así, preguntas del tipo "¿qué
sabes hacer?" le salen en viñetas con negritas, un "En resumen" y un "¿en qué
puedo ayudarte hoy?" de despedida. Con este modelo, pedirlo no basta.

Así que aquí se normaliza después. Es deliberadamente conservador: solo toca la
FORMA, nunca el contenido. Quita las marcas de lista y de markdown, junta las
viñetas en prosa, y borra los dos tics de cierre — el conector de resumen y el
ofrecimiento genérico de ayuda — solo cuando están al final y solo si son eso.

Se aplica a la respuesta entera, así que arregla igual lo que se ve en el panel
y lo que se dice en voz.
"""

import re

# Marcadores de lista al principio de línea: viñeta, guion o numeración.
_VINETA_RE = re.compile(r"^[ \t]*(?:[-*•·+]|\d{1,2}[.)])[ \t]+", re.MULTILINE)
# Encabezados markdown.
_TITULO_RE = re.compile(r"^[ \t]*#{1,6}[ \t]*", re.MULTILINE)
# Negrita y cursiva, dejando el texto.
_ENFASIS_RE = re.compile(r"\*{1,3}([^*\n]+)\*{1,3}|__([^_\n]+)__")

# Conectores de resumen al empezar una frase: sobran al hablar.
_RESUMEN_RE = re.compile(
    r"(?:^|(?<=[.!?]\s))\s*(?:en\s+resumen|en\s+conclusi[oó]n|para\s+resumir|"
    r"en\s+s[ií]ntesis|dicho\s+de\s+otro\s+modo)\s*,?\s*",
    re.IGNORECASE)

# Palabras que delatan el ofrecimiento de ayuda de despedida. Se mira solo la
# ÚLTIMA frase: "¿en qué puedo ayudarte?" al final sobra, pero "¿quieres que lo
# abra?" en mitad de una respuesta es una pregunta de verdad.
_DESPEDIDA_PISTAS = (
    "ayudar", "ayudarte", "ayude", "ayudo", "servir", "servirte", "asistir",
    "estoy para", "aqui estoy", "aquí estoy", "no dudes", "avisame", "avísame",
    "te gustaria", "te gustaría", "algo mas", "algo más", "que mas", "qué más",
    "a la orden", "para lo que necesites",
)

_FRASE_RE = re.compile(r"[^.!?…]+[.!?…]*\s*")


def _unir_vinetas(texto: str) -> str:
    """Una lista suelta se convierte en prosa: las viñetas se encadenan."""
    lineas = texto.split("\n")
    salida, bloque = [], []

    def volcar():
        if not bloque:
            return
        # Cada punto acaba en su propia frase; si ya trae punto, no se dobla.
        piezas = []
        for b in bloque:
            b = b.strip()
            if b and b[-1] not in ".!?:;":
                b += "."
            piezas.append(b)
        salida.append(" ".join(piezas))
        bloque.clear()

    for linea in lineas:
        if _VINETA_RE.match(linea):
            bloque.append(_VINETA_RE.sub("", linea, count=1))
        else:
            volcar()
            salida.append(linea)
    volcar()
    return "\n".join(salida)


def _quitar_despedida(texto: str) -> str:
    """Borra la última frase si es un ofrecimiento genérico de ayuda.

    Solo la última, y solo si hay algo antes: si el texto ENTERO es eso, será
    que BLUE contestaba justamente eso y hay que dejarlo.
    """
    frases = [f for f in _FRASE_RE.findall(texto) if f.strip()]
    if len(frases) < 2:
        return texto.strip()

    ultima = frases[-1].strip().lower()
    if any(p in ultima for p in _DESPEDIDA_PISTAS):
        cuerpo = "".join(frases[:-1]).strip()
        if cuerpo:
            return cuerpo
    return texto.strip()


def _arreglar_costuras(texto: str) -> str:
    """Tras quitar un conector, la frase puede quedar empezando en minúscula."""
    def subir(m):
        return m.group(1) + m.group(2).upper()
    return re.sub(r"(^|[.!?…]\s+)([a-záéíóúñ])", subir, texto)


def hablado(texto: str) -> str:
    """Deja la respuesta como la diría una persona. Solo cambia la forma."""
    if not texto or not texto.strip():
        return texto

    t = _TITULO_RE.sub("", texto)
    t = _unir_vinetas(t)
    t = _ENFASIS_RE.sub(lambda m: m.group(1) or m.group(2) or "", t)
    t = _RESUMEN_RE.sub(" ", t)

    t = _quitar_despedida(t)

    t = _arreglar_costuras(t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


if __name__ == "__main__":
    ejemplo = """Wilmer, tenemos disponibles los siguientes cerebros:

*   **BLUE**: Yo, tu asistente de voz. Puedo manejar tu escritorio
*   **Claude Code**: Para tareas pesadas de programación

En resumen, yo me encargo de la operación general. ¿En qué te gustaría que te ayude hoy, jefe?"""
    print("── ANTES ──")
    print(ejemplo)
    print("\n── DESPUÉS ──")
    print(hablado(ejemplo))
