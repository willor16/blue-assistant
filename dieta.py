"""
dieta.py — Enviar solo lo que hace falta en cada turno.

El problema medido: cada llamada al cerebro arrastraba unos 9.400 tokens fijos
(3.100 de prompt y 6.250 de los esquemas de las 57 herramientas), y el cupo
diario gratuito son 200.000 por modelo. Salían unos 21 turnos al día, y cada
herramienta que BLUE usa gasta otra vuelta entera. Por eso se quedaba sin
cerebro a media tarde y contestaba sin poder ejecutar nada.

La grasa no está en las descripciones: son densas pero necesarias, y recortarlas
empeora la elección de herramienta. Está en mandarlas TODAS SIEMPRE. Cuando
Wilmer dice "abre spotify" no hacen falta las de termodinámica, ni las del
índice de documentos, ni el párrafo del prompt que las explica.

Así que cada grupo especializado viaja solo si la frase lo pide, y su párrafo
del prompt viaja con él (nunca se describe una herramienta que no va).

Dos seguros contra quedarse corto:
  - Las expresiones son generosas: ante la duda, el grupo entra.
  - Un grupo que se usó sigue disponible unos turnos más, para que las
    preguntas de seguimiento ("y grafícalo", "¿y eso qué dice?") funcionen.

El núcleo (escritorio, ventanas, protocolos, memoria, carpetas, agenda, tareas
pesadas) va SIEMPRE. Nada de lo de todos los días depende de acertar una regex.
"""

from __future__ import annotations

import re

# Cuántos turnos sigue disponible un grupo después de hacer falta.
PEGAJOSO = 3

# nombre -> (herramientas, cabecera de la sección del prompt, cuándo entra)
GRUPOS = {
    "ingenieria": (
        ("convert_units", "engineering_calc", "thermo_property", "engineering_plot"),
        "INGENIERÍA:",
        r"calcul\w*|cuent\w*|convier\w*|conversi[oó]n|cu[aá]nto\s+(es|son|da|vale)|"
        r"termo\w*|entalp\w*|entrop\w*|presi[oó]n|temperatura|caudal|"
        r"fluid\w*|reynolds|bernoulli|bomba|tuber[ií]a|p[eé]rdida\w*\s+de\s+carga|"
        r"viga|momento|cortante|esfuerzo|torque|par\b|estructur\w*|fem\b|"
        r"transferencia\s+de\s+calor|intercambiador|lmtd|psicrom\w*|"
        r"vapor|refrigerante|r134a|coolprop|"
        r"grafic\w*|gr[aá]fic\w*|plote\w*|dibuj\w*|traza\w*|curva|diagrama|"
        r"\b(bar|psi|kpa|mpa|pascal|newton|kilonewton|kw|kwh|hp|rpm|"
        r"celsius|kelvin|fahrenheit|litros?|galones?|metros?\s+c[uú]bicos)\b"
    ),
    "documentos": (
        ("crear_espacio", "listar_espacios", "indexar_apuntes",
         "indexar_documentos", "consultar_documentos"),
        "DOCUMENTOS Y ESPACIOS (RAG):",
        r"apunte\w*|mis\s+document\w*|document\w*\s+(de|sobre|del)|"
        r"indexa\w*|[ií]ndice|pdf|word|docx|"
        r"curso\w*|materia\w*|asignatura\w*|semestre|universidad|"
        r"seg[uú]n\s+mis|en\s+mis\s+(apuntes|documentos|archivos)|"
        r"qu[eé]\s+dicen\s+mis|busca\s+en\s+(la\s+norma|el\s+manual|mis)|"
        r"norma\w*|manual\w*|datasheet|libro\w*|material\s+de\s+estudio"
    ),
    "vision": (
        ("ver_pantalla",),
        "VISIÓN:",
        r"mi\s+pantalla|la\s+pantalla|qu[eé]\s+ves|mira\b|fíjate|f[ií]jate|"
        r"lee\s+(esto|esta|este)|qu[eé]\s+dice\s+(esto|este|esta|aqu[ií])|"
        r"este\s+error|el\s+error\s+(de|que)|captura|screenshot|"
        r"qu[eé]\s+hay\s+en\s+(la\s+)?pantalla|interpreta"
    ),
    "correo": (
        ("check_mail", "send_email"),
        None,                       # su párrafo va en el núcleo, es corto
        r"correo\w*|email|e-mail|mail\b|bandeja|inbox|gmail|"
        r"escr[ií]bele\s+a|m[aá]ndale\s+(un|el)|env[ií]a\w*\s+(un\s+)?(correo|mail)"
    ),
    "escalafon": (
        ("consultar_orfeo", "consultar_icaro"),
        None,
        r"promete[oa]|orfe[oa]|argos|[iy]car[oa]|[hj]?ere[bv][oa]|"
        r"cerebro\w*|motor(es)?\b|piensa\s+(despacio|a\s+fondo)|"
        r"anal[ií]za\w*\s+a\s+fondo|razona\w*\s+(largo|a\s+fondo)|"
        r"expl[ií]ca\w*\s+a\s+fondo|en\s+profundidad|te[oó]ric\w*"
    ),
    "crear_protocolos": (
        ("create_protocol", "create_project", "set_project_folder"),
        None,
        r"protocolo\w*|proyecto\w*|rutina\w*|espacio\s+de\s+trabajo|"
        r"entorno\s+de\s+trabajo|vive\s+en|est[aá]\s+en\s+la\s+carpeta"
    ),
}

_COMPILADAS = {k: re.compile(v[2], re.IGNORECASE) for k, v in GRUPOS.items()}

# Todo lo que pertenece a algún grupo: lo demás es núcleo y viaja siempre.
_DE_GRUPO = {h for v in GRUPOS.values() for h in v[0]}


def nucleo(nombres_todos) -> list:
    """Las herramientas que van en cada llamada, pase lo que pase."""
    return [n for n in nombres_todos if n not in _DE_GRUPO]


def grupos_para(texto: str) -> set:
    """Qué grupos pide esta frase."""
    t = texto or ""
    return {k for k, rx in _COMPILADAS.items() if rx.search(t)}


class Dieta:
    """Lleva la cuenta de qué grupos siguen calientes de turnos anteriores."""

    def __init__(self):
        self._calor: dict = {}          # grupo -> turnos que le quedan

    def elegir(self, texto: str) -> set:
        pedidos = grupos_para(texto)
        for g in pedidos:
            self._calor[g] = PEGAJOSO
        activos = set(pedidos)
        for g, quedan in list(self._calor.items()):
            if quedan > 0:
                activos.add(g)
                self._calor[g] = quedan - 1
            else:
                self._calor.pop(g, None)
        return activos

    def herramientas(self, texto: str, nombres_todos) -> tuple:
        """Devuelve (nombres de herramientas para esta llamada, grupos activos)."""
        activos = self.elegir(texto)
        permitidas = set(nucleo(nombres_todos))
        for g in activos:
            permitidas.update(GRUPOS[g][0])
        return [n for n in nombres_todos if n in permitidas], activos


def secciones_de(grupos_activos: set) -> set:
    """Las cabeceras de las secciones del prompt que acompañan a esos grupos."""
    return {GRUPOS[g][1] for g in grupos_activos if GRUPOS[g][1]}


def secciones_gobernadas() -> set:
    """Todas las cabeceras que esta dieta controla (para poder quitarlas)."""
    return {v[1] for v in GRUPOS.values() if v[1]}
