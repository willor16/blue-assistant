"""Hora, fecha y cuentas regresivas en español natural. Todo LOCAL: cero
tokens, cero internet. Lo usa la ruta rápida del router."""
from __future__ import annotations
import datetime
import re

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _franja(h24: int) -> str:
    if 5 <= h24 < 12:
        return "de la mañana"
    if 12 <= h24 < 20:
        return "de la tarde"
    return "de la noche"


def _hora_en_palabras(h24: int, m: int) -> str:
    h12 = h24 % 12 or 12
    intro = "Es la" if h12 == 1 else "Son las"
    if m == 0:
        cuerpo = f"{h12} en punto"
    elif m == 15:
        cuerpo = f"{h12} y cuarto"
    elif m == 30:
        cuerpo = f"{h12} y media"
    elif m == 45:
        nxt = (h24 + 1) % 12 or 12
        return f"Son cuarto para las {nxt} {_franja((h24 + 1) % 24)}"
    else:
        cuerpo = f"{h12} y {m}"
    return f"{intro} {cuerpo} {_franja(h24)}"


def now_phrase() -> str:
    n = datetime.datetime.now()
    return _hora_en_palabras(n.hour, n.minute)


def date_phrase() -> str:
    n = datetime.datetime.now()
    return (f"Hoy es {_DIAS[n.weekday()]} {n.day} de {_MESES[n.month - 1]} "
            f"de {n.year}")


def _parse_target(text: str) -> datetime.datetime | None:
    """Saca una hora objetivo de frases como 'las 8', 'las 8 am', 'la una',
    'las 15:30', 'las 8 de la noche'. Devuelve el próximo momento futuro."""
    t = text.lower()
    palabras = {"una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
                "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
                "once": 11, "doce": 12, "mediodía": 12, "medianoche": 0}
    h, m = None, 0
    mnum = re.search(r"\b(\d{1,2})(?::(\d{2}))?\b", t)
    if mnum:
        h = int(mnum.group(1))
        if mnum.group(2):
            m = int(mnum.group(2))
    else:
        for w, v in palabras.items():
            if re.search(rf"\b{w}\b", t):
                h = v
                break
    if h is None:
        return None
    # am/pm explícito o por franja hablada
    if re.search(r"\bp\.?\s?m\b|de la tarde|de la noche", t):
        if h < 12:
            h += 12
    elif re.search(r"\ba\.?\s?m\b|de la mañana|madrugada", t):
        if h == 12:
            h = 0
    elif h < 7:                     # heurística: "las 3" sin franja -> 15:00
        h += 12
    h = h % 24
    now = datetime.datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:              # ya pasó hoy -> mañana
        target += datetime.timedelta(days=1)
    return target


def countdown_phrase(text: str) -> str | None:
    target = _parse_target(text)
    if not target:
        return None
    delta = target - datetime.datetime.now()
    total_min = int(delta.total_seconds() // 60)
    horas, mins = divmod(total_min, 60)
    hh = _hora_en_palabras(target.hour, target.minute).lower()
    hh = re.sub(r"^(son las|es la)\s+", "las ", hh)
    if horas and mins:
        cuanto = f"{horas} hora{'s' if horas != 1 else ''} y {mins} minuto{'s' if mins != 1 else ''}"
    elif horas:
        cuanto = f"{horas} hora{'s' if horas != 1 else ''}"
    else:
        cuanto = f"{mins} minuto{'s' if mins != 1 else ''}"
    cuando = "mañana" if target.day != datetime.datetime.now().day else ""
    extra = f" ({cuando})" if cuando else ""
    return f"Faltan {cuanto} para {hh}{extra}"
