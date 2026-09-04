"""Ruta rapida: SOLO comandos cortos e inequívocos -> ejecucion directa, 0 tokens.
Devuelve la respuesta hablada, o None si hay que pasar al cerebro (Gemini).

Diseño conservador: ante la duda, devuelve None y deja que piense el cerebro.
Así evitamos falsos positivos como 'haga lo siguiente' -> siguiente canción.
"""
from __future__ import annotations
import re

import actions
import lines
import protocols
import timeinfo

# si aparece algo de esto, NUNCA es comando rápido (es creación/conversación)
_BRAIN_WORDS = re.compile(
    r"\b(protocolo|crea\w*|agrega\w*|añad\w*|nuevo|haga|hacer|haz que|"
    r"cuando|si\s|abre|abrir|busca|buscar|escribe|dime|cu[aá]l|qu[eé]\s|c[oó]mo)\b")


# verbos con los que se pide ARRANCAR un protocolo/proyecto guardado
_RUN_VERBS = (r"(?:ejec[uú]ta\w*|inicia\w*|in[ií]cia\w*|corre|c[oó]rre\w*|"
              r"activa\w*|act[ií]va\w*|lanza\w*|l[aá]nza\w*|arranca\w*|"
              r"dispara\w*|pon|ponme|p[oó]nme|p[oó]n|mete\w*|echa\w*|dale\s+a)")
# verbos de GESTIÓN (crear/editar/listar/borrar): esos van al cerebro, NO ejecutar
_MANAGE = re.compile(r"\b(crea\w*|gua?rd\w*|nuev[oa]|elimina\w*|borra\w*|qu[ií]ta\w*|"
                     r"lista|list\w*|mu[eé]stra\w*|edita\w*|modifica\w*|"
                     r"cambia\w*|a[ñn]ad\w*|agrega\w*)\b")


def _protocol_route(t: str) -> str | None:
    """Ejecuta un protocolo/proyecto guardado de forma DETERMINISTA (0 tokens).

    Antes solo 'activa el protocolo X' funcionaba; 'ejecuta/inicia/corre/pon X'
    caía al cerebro chico (a veces no lo hallaba o se comía el cierre gracioso).
    Aquí lo resolvemos directo y run_protocol narra cada paso + cierra con vibra.
    """
    if _MANAGE.search(t):                 # 'crea/edita/lista protocolo' -> cerebro
        return None
    # forma explícita: <verbo> [el/la/mi] (protocolo|proyecto|rutina|entorno) <nombre>
    m = re.search(_RUN_VERBS + r"\s+(?:el\s+|la\s+|mi\s+|un\s+|los\s+|las\s+)?"
                  r"(?:protocolo|proyecto|rutina|entorno|modo)\s+(.+)", t)
    if m:
        return protocols.run_protocol(m.group(1).strip())   # ya trae su cierre
    # forma corta: <verbo> <nombre> -> solo si coincide con un protocolo guardado
    m = re.match(r"^" + _RUN_VERBS + r"\s+(?:el\s+|la\s+|mi\s+)?(.+)", t)
    if m:
        cand = m.group(1).strip()
        if protocols._resolve(cand, protocols.load_protocols()):
            return protocols.run_protocol(cand)
    return None


# --- espacio de trabajo: activar/abandonar un proyecto-contexto (0 tokens) ---
_WS_VERB = re.compile(
    r"^(?:blue,?\s*)?(?:trabaj\w+|ponte\s+a\s+trabajar|vamos\s+a\s+trabajar|"
    r"p[oó]ngamonos\s+a\s+trabajar|sigamos\s+(?:con|en)|continuemos\s+(?:con|en)|"
    r"retomemos|metamonos\s+(?:en|con))\b\s*(.*)")
_WS_LEAVE = re.compile(
    r"\b(?:sal(?:gamos|ir|te)?\s+del\s+proyecto|deja\s+el\s+proyecto|"
    r"cierra\s+el\s+proyecto|modo\s+general|sin\s+proyecto|"
    r"abandona\s+el\s+proyecto|terminamos\s+(?:el\s+)?proyecto)\b")
_WS_FILLER = re.compile(
    r"^(?:a\s+trabajar\s+)?(?:en|con|sobre)?\s*(?:el|la|los|las|mi|al)?\s*"
    r"(?:proyecto|repo|repositorio|entorno|carpeta)?\s*")


def _workspace_route(t: str) -> str | None:
    """Activar un proyecto como espacio de trabajo o salir de él (determinista).

    'trabajemos en X' / 'ponte a trabajar en X' -> enfoca contexto (workspace).
    Solo si X resuelve a un proyecto guardado; si no hay nombre, deja que el
    cerebro pregunte en cuál.
    """
    import workspace
    if _WS_LEAVE.search(t):
        return workspace.deactivate()
    m = _WS_VERB.match(t)
    if m:
        cand = _WS_FILLER.sub("", m.group(1).strip()).strip()
        if cand and protocols._resolve(cand, protocols.load_protocols()):
            return workspace.work_on(cand)
    return None


def _datetime_route(t: str) -> str | None:
    """Hora, fecha y cuentas regresivas: respuesta LOCAL con vibra (0 tokens)."""
    # cuánto falta para las X
    if re.search(r"\bcu[aá]nto\s+(falta|queda)\b", t) and re.search(r"\bpara\b", t):
        ans = timeinfo.countdown_phrase(t)
        if ans:
            return lines.datetime_say(ans)
    # qué hora es / dime la hora
    if re.search(r"\bqu[eé]\s+hora\b", t) or re.search(r"\b(dime|dame)\s+la\s+hora\b", t) \
            or re.fullmatch(r"(la\s+)?hora", t):
        return lines.datetime_say(timeinfo.now_phrase())
    # qué día / fecha es hoy
    if re.search(r"\bqu[eé]\s+(d[ií]a|fecha)\b", t) or re.search(r"\bqu[eé]\s+fecha\b", t) \
            or re.search(r"\ben\s+qu[eé]\s+d[ií]a\b", t) or re.search(r"\bfecha\s+de\s+hoy\b", t):
        return lines.datetime_say(timeinfo.date_phrase())
    return None


# --- memoria persistente: detectores deterministas (0 tokens) ---
# expresión de tiempo => es un RECORDATORIO (va a la agenda), no un hecho a recordar
_MEM_TIME = re.compile(
    r"\b(hoy|ma[ñn]ana|pasado\s+ma[ñn]ana|ayer|lunes|martes|mi[eé]rcoles|jueves|"
    r"viernes|s[aá]bado|domingo|a\s+las?\s*\d|\d{1,2}:\d{2}|"
    r"en\s+\d+\s*(min|minuto|minutos|hora|horas|d[ií]a|d[ií]as|semana|semanas))\b")
# guardar un hecho: "recuerda que X", "ten en cuenta que X", "memoriza X"...
_MEM_STORE = re.compile(
    r"^(?:blue,?\s*)?(?:recuerda|memoriza|ten\s+en\s+cuenta|tenme\s+presente|"
    r"que\s+sepas|no\s+olvides|gu[aá]rdate|gu[aá]rda)\b\s*"
    r"(?:que\s+|esto:?\s*|de\s+que\s+|en\s+tu\s+memoria\s+(?:que\s+)?)?(.+)")
# consultar la memoria
_MEM_RECALL = re.compile(
    r"\bqu[eé]\s+(recuerdas|sabes|tienes\s+anotado|tienes\s+en\s+tu\s+memoria|"
    r"tienes\s+apuntado)\b")
_MEM_RECALL_TOPIC = re.compile(r"\bqu[eé]\s+sabes\s+(?:de|sobre|acerca\s+de)\s+(.+)")
# olvidar
_MEM_FORGET = re.compile(r"\bolvida(?:te)?\b|\bborra\s+de\s+tu\s+memoria\b")


def _memory_route(t: str) -> str | None:
    """Memoria persistente por voz: guardar / consultar / olvidar (0 tokens).

    Convive con la agenda: si la frase trae una HORA es un recordatorio y se deja
    pasar (return None) para que _info_route lo agende. "recuérdame ..." (con -me)
    también se deja a la agenda; aquí solo capturamos hechos a recordar a futuro.
    """
    import memory
    # nunca tratamos protocolos/proyectos como memoria (los crea el cerebro)
    if re.search(r"\b(protocolo|proyecto|rutina|entorno)\b", t):
        return None
    # --- olvidar (de la memoria, no de la agenda) ---
    if _MEM_FORGET.search(t) and not re.search(r"\bagenda\b", t):
        m = (re.search(r"borra\s+de\s+tu\s+memoria\s+(.+)", t) or
             re.search(r"olvida(?:te)?\s+(?:lo\s+de\s+|que\s+|de\s+)?(.+)", t))
        if m:
            return memory.forget(m.group(1).strip())
    # --- consultar la memoria ---
    if _MEM_RECALL.search(t) or _MEM_RECALL_TOPIC.search(t):
        m = _MEM_RECALL_TOPIC.search(t)
        return memory.recall(m.group(1).strip() if m else "")
    # --- guardar un hecho (sin hora => no es recordatorio de agenda) ---
    m = _MEM_STORE.match(t)
    if m and not _MEM_TIME.search(t):
        fact = m.group(1).strip()
        if len(fact.split()) >= 2:        # evita capturar "recuerda" suelto
            return memory.add(fact)
    return None


def _info_route(t: str) -> str | None:
    """Correo (revisar) y agenda local: rutas rápidas, cero tokens."""
    import mailbox
    import agenda
    # --- correo: revisar bandeja (no enviar; enviar lo arma el cerebro) ---
    if re.search(r"\b(correo|correos|email|mail|bandeja|inbox)\b", t) and \
       re.search(r"\b(revisa|revísame|checa|ch[eé]came|mira|tengo|hay|nuevo|"
                 r"nuevos|le[eé]me|lee|cu[aá]ntos)\b", t) and \
       not re.search(r"\b(env[ií]a|manda|redacta|escribe|responde|contesta)\b", t):
        return mailbox.check_unread()
    # --- agenda: consultar ---
    if re.search(r"\b(agenda|agendado|pendiente|pendientes|recordatorio"
                 r"|recordatorios)\b", t) and \
       re.search(r"\b(qu[eé]|cu[aá]l|mi|tengo|hay|mu[eé]strame|dime|lista)\b", t) and \
       not re.search(r"\b(ag[eé]nda\w*\s+\w|recu[eé]rda\w*\s+\w|anota|apunta|borra|limpia)\b", t):
        return agenda.list_events()
    # --- agenda: borrar ---
    if re.search(r"\b(borra|limpia|vac[ií]a|elimina)\b.*\bagenda\b", t):
        return agenda.clear_events()
    # --- agenda: agregar (agéndame X / recuérdame X / anota X) ---
    m = re.search(r"^(?:ag[eé]nda(?:me)?|recu[eé]rda(?:me)?|anota(?:me)?|"
                  r"ap[uú]nta(?:me)?)\s+(?:que\s+|lo\s+de\s+|el\s+|la\s+)?(.+)", t)
    if m:
        return agenda.add_event(m.group(1).strip())
    return None


def _close_target(t: str) -> str | None:
    """¿A que app se refiere "cierra X"? Solo si la reconoce de verdad.

    Conservador a proposito: o es un nombre que BLUE sabe traducir, o hay una
    ventana abierta que encaja. Si no, devuelve None y que piense el cerebro,
    porque cerrar lo que no era es de las pocas cosas que no se pueden deshacer.
    """
    conocidos = set(actions._WIN_ALIASES) | set(actions.APP_MAP)
    # los nombres largos primero: "gestor de archivos" antes que "archivos"
    for nombre in sorted(conocidos, key=len, reverse=True):
        if re.search(r"\b" + re.escape(nombre) + r"\b", t):
            return nombre
    # no esta en la lista: ¿hay alguna ventana abierta que se llame asi?
    for palabra in re.findall(r"[a-záéíóúñ]{4,}", t):
        if palabra in _NO_ES_APP:
            continue
        if actions._find_client(palabra):
            return palabra
    return None


# Palabras que salen en cualquier orden de cerrar y no son el nombre de nada.
_NO_ES_APP = {
    "cierra", "cierras", "cierre", "cierres", "cierren", "cierralo", "cierrala",
    "cerrar", "cierrame", "quiero", "puedes", "favor", "ahora", "todas", "todos",
    "ventana", "ventanas", "abierta", "abiertas", "abierto", "abiertos", "tengo",
    "esta", "este", "esto", "programa", "aplicacion", "app", "porfa", "please",
}


def _window_route(t: str) -> str | None:
    """Ventanas: listar / cerrar todo / cerrar la activa. Directo, 0 tokens.

    Determinista a propósito: cerrar ventanas es una orden que Blue DEBE cumplir
    siempre igual, sin depender de que el modelo chico decida llamar la función.
    """
    # Todas las formas del verbo, no solo el imperativo. La lista vieja pedia
    # "cierra/cerrar" literal y se le escapaba el subjuntivo, que es justo como
    # se habla: "quiero que CIERRES todo lo que tengo abierto" no encajaba, caia
    # en la rama de LISTAR de mas abajo, y BLUE contestaba tan campante "tienes
    # tres ventanas abiertas" a alguien que le habia pedido cerrarlas. Un solo
    # patron cubre cierra, cierres, cierre, cierren, ciérralo, ciérrame y cerrar.
    cerrar = bool(re.search(r"\bc[ieé]+rr\w*", t))
    # "cierra sesión" es apagar, no una ventana: que lo vea el cerebro.
    if cerrar and not re.search(r"\bsesi[oó]n\b", t):
        # cerrar TODO (cierra todo / ciérralo todo / cierra todas las ventanas)
        if re.search(r"\b(todo|todas?|todito)\b", t):
            return lines.flavor(actions.close_all_windows())
        # cerrar una app por su nombre: "cierra Spotify", "ciérrame el navegador"
        app = _close_target(t)
        if app:
            return lines.flavor(actions.close_application(app))
        # cerrar la ventana actual (cierra esta/la ventana, ciérrala)
        if re.search(r"\bventana\b|\bc[ieé]+rra(la|lo)\b", t):
            return lines.flavor(actions.close_active_window())
        return None
    # --- listar ventanas abiertas (solo si NO se pidió cerrar) ---
    if re.search(r"\bventanas?\b", t) and \
       re.search(r"\b(abierta|abiertas|abierto|abiertos|tengo|hay|cu[aá]l|cu[aá]les|"
                 r"cu[aá]nt\w+|lista|list\w+|mu[eé]stra\w*|dime|ver|veo|qu[eé])\b", t):
        return lines.flavor(actions.list_windows())
    if re.search(r"\bqu[eé]\s+(tengo|hay|est[aá])\s+abierto", t) or \
       re.search(r"\bqu[eé]\s+aplicaciones?\b.*\babiert", t):
        return lines.flavor(actions.list_windows())
    return None


_VISION = re.compile(
    r"\b(mira|ve|fíjate|fijate|revisa|lee|l[eé]eme|checa|che[ck]a|analiza|"
    r"describe|qu[eé]\s+ves|qu[eé]\s+dice|puedes\s+ver|alcanzas?\s+a\s+ver)\b"
    r".*\b(pantalla|monitor|esto|aqu[ií]|imagen|diagrama|gr[aá]fico|gr[aá]fica|"
    r"tabla|datasheet|c[oó]digo|error|esta\s+ventana|lo\s+que\s+(ves|hay|tengo))\b",
    re.IGNORECASE)
_VISION_SHORT = re.compile(
    r"^(qu[eé]\s+ves|qu[eé]\s+estoy\s+viendo|mira\s+(mi\s+)?pantalla|"
    r"ve\s+(mi\s+)?pantalla|lee\s+(mi\s+)?pantalla)\b", re.IGNORECASE)


def _vision_route(t: str, original: str) -> str | None:
    """Ver la pantalla: captura + interpreta. Determinista, sin pasar por el LLM
    de tools (que el modelo chico no se niegue a 'ver'). 0 tokens del cerebro."""
    if _VISION.search(t) or _VISION_SHORT.search(t):
        import vision
        if not vision.available():
            return None                  # sin grim/clave: que lo maneje el cerebro
        return vision.look(original.strip())
    return None


# --- taxonomía de estudio: crear espacio / indexar apuntes / listar ---
_NEW_INTENT = re.compile(
    r"\b(tengo|hay|crea\w*|cre[ae]me|agrega\w*|a[ñn]ad\w*|registra\w*|anota\w*|"
    r"apunta\w*|nuev[oa])\b", re.IGNORECASE)
_CAT_NAME = re.compile(
    r"\b(cursos?|materias?|asignaturas?|clases?|ramos?|proyectos?|trabajos?|"
    r"tareas?|estudio\s+externo|externos?)\b\s*"
    r"(?:nuev[oa]\s+)?(?:de\s+|llamad[oa]\s+|sobre\s+|:\s*)?(.+)?", re.IGNORECASE)
_INDEX = re.compile(
    r"\b(indexa\w*|index[ae]me|aprende\w*|apr[eé]nd\w*|l[eé]ete|leete)\b", re.IGNORECASE)
_INDEX_NOUN = re.compile(
    r"\b(apuntes|documentos|docs|curso|proyecto|carpeta|archivos?|pdf\w*|material)\b"
    r"\s*(?:de\s+|del\s+|:\s*)?(.+)?", re.IGNORECASE)
_LIST_SPACES = re.compile(
    r"\b(cursos|materias|asignaturas|proyectos|trabajos)\b", re.IGNORECASE)
_FILLER_TAIL = re.compile(r"^(un[ao]?\s+|el\s+|la\s+|mis?\s+|los\s+|las\s+)+",
                          re.IGNORECASE)


def _clean_name(s: str) -> str:
    s = (s or "").strip(" .,;:!¡¿?")
    s = _FILLER_TAIL.sub("", s).strip()
    return s


def _study_route(t: str, original: str) -> str | None:
    """Crear curso/proyecto/trabajo, indexar apuntes, listar espacios. 0 tokens."""
    import study
    # indexar apuntes ("indexa mis apuntes de X" / "indexa el curso X")
    if _INDEX.search(t):
        m = _INDEX_NOUN.search(original)
        name = _clean_name(m.group(2)) if (m and m.group(2)) else ""
        # quita verbos/relleno que se hayan colado en el nombre
        name = re.sub(r"^(mis?|los|las|el|la)\s+", "", name, flags=re.IGNORECASE).strip()
        return study.index_notes(name)
    # listar espacios ("qué cursos/proyectos/trabajos tengo")
    if re.search(r"\bqu[eé]\b", t) and _LIST_SPACES.search(t) and \
       re.search(r"\b(tengo|hay|ten[ée]s|son|hice|cre[ée])\b", t):
        cat = _LIST_SPACES.search(t).group(1)
        return study.list_by(cat.rstrip("s"))
    # crear nuevo contenedor (requiere intención + categoría)
    if _NEW_INTENT.search(t):
        m = _CAT_NAME.search(original)
        if m:
            cat = study.categorize(m.group(1).split()[0])
            name = _clean_name(m.group(2)) if m.group(2) else ""
            if cat and name:
                return study.new(cat, name)
    return None


def _pomodoro_route(t: str, original: str) -> str | None:
    """Pomodoro por voz + adaptativo: arrancar / parar / estado / pausar /
    reanudar, y ajustes 'estoy cansado' / 'tengo prisa' (solo si hay sesión).
    Determinista, 0 tokens."""
    import pomodoro
    # --- adaptativo: solo tiene sentido con un pomodoro EN MARCHA ---
    if pomodoro.is_running():
        if re.search(r"\b(cansad\w*|agotad\w*|fundid\w*|rendid\w*|ya\s+no\s+puedo|"
                     r"me\s+cans[eé]|estoy\s+muerto)\b", t):
            return pomodoro.adjust("tired")
        if re.search(r"\b(prisa|apurad\w*|apuro|voy\s+tarde|poco\s+tiempo|"
                     r"ando\s+corto|r[aá]pido)\b", t):
            return pomodoro.adjust("hurry")
    has_kw = "pomodoro" in t or "modo enfoque" in t or "modo de enfoque" in t
    if not has_kw:
        return None
    # --- pausar / reanudar ---
    if re.search(r"\bpaus\w*\b", t):
        return pomodoro.pause()
    if re.search(r"\b(reanud\w*|contin[uú]a\w*|retoma\w*)\b", t):
        return pomodoro.resume()
    # --- parar / cancelar (verbo inequívoco, o 'para ...' al inicio) ---
    if re.search(r"\b(det[eé]n\w*|cancela\w*|termina\w*|acaba\w*|quita\w*|"
                 r"olv[ií]da\w*|m[aá]tal\w*)\b", t) or \
       re.match(r"^(?:blue,?\s*)?p[aá]ra\b", t):
        return pomodoro.stop()
    # --- estado / cuánto falta ---
    if re.search(r"\b(cu[aá]nto|c[oó]mo\s+va|estado|queda|falta|voy|llevo)\b", t):
        return pomodoro.status()
    # --- arrancar: extrae minutos y etiqueta ---
    mins = None
    m = re.search(r"\bde\s+(\d{1,3})\b", t) or re.search(r"(\d{1,3})\s*min", t)
    if m:
        mins = int(m.group(1))
    label = ""
    ml = re.search(r"\bpara\s+(.+)$", original, re.IGNORECASE)
    if ml:
        label = ml.group(1)
    else:
        md = re.search(r"\bde\s+([a-zA-ZáéíóúñÁÉÍÓÚÑ].+)$", original)
        if md:
            label = md.group(1)
    label = _clean_name(label) if label else ""
    return pomodoro.start(mins or pomodoro.DEF_FOCUS, label)


# --- control de escritorio: enfocar ventana / brillo / captura (0 tokens) ---
_FOCUS_VERB = re.compile(
    r"^(?:blue,?\s*)?(?:ve(?:te)?|anda|[aá]nd\w*|cambi\w*|c[aá]mbi\w*|p[aá]sa\w*|"
    r"pasa|enf[oó]c\w*|mu[eé]stra\w*|saca\w*|tr[aá]e\w*|ll[eé]v\w*|ens[eé][ñn]\w*)"
    r"\s+(.+)")

def _focus_target(s: str) -> str:
    s = (s or "").strip(" .,;:!¡¿?")
    s = re.sub(r"\bal\s+frente\b", "", s)
    s = re.sub(r"\b(la\s+)?ventana\s+(de\s+|del\s+)?", "", s)
    for _ in range(2):                    # quita conectores encadenados al inicio
        s = re.sub(r"^(?:a|al|el|la|los|las|me|mi|hacia|para|un|una|lo)\s+",
                   "", s, flags=re.IGNORECASE).strip()
    return s.strip()


def _control_route(t: str, original: str) -> str | None:
    """Enfocar una ventana abierta, brillo y captura a archivo. Determinista.

    Conservador: para enfocar, el destino debe resolver a una app conocida o a una
    ventana realmente abierta; si no, devuelve None y deja pensar al cerebro.
    """
    # --- brillo (palabra 'brillo' inequívoca) ---
    if re.search(r"\bbrillo\b", t):
        n = re.search(r"(\d{1,3})", t)
        if re.search(r"\b(sube|subir|s[uú]be\w*|aumenta\w*|m[aá]s)\b", t):
            return lines.flavor(actions.adjust_brightness(int(n.group(1)) if n else 15))
        if re.search(r"\b(baja|bajar|b[aá]ja\w*|disminuye\w*|reduce\w*|menos|aten[uú]a\w*)\b", t):
            return lines.flavor(actions.adjust_brightness(-(int(n.group(1)) if n else 15)))
        if n and re.search(r"\b(pon|ponlo|p[oó]n\w*|fija|deja|al?|en)\b", t):
            return lines.flavor(actions.set_brightness(int(n.group(1))))

    # --- captura de pantalla a archivo ---
    if re.search(r"\b(captura|capt[uú]r\w*|pantallazo|screenshot|screen\s*shot)\b", t):
        region = bool(re.search(r"\b([aá]rea|parte|trozo|porci[oó]n|selecc\w*|"
                                r"un\s+pedazo|recorte)\b", t))
        return lines.flavor(actions.take_screenshot(region))

    # --- enfocar / cambiar a una ventana abierta ---
    m = _FOCUS_VERB.match(t)
    if m:
        target = _focus_target(m.group(1))
        if target:
            key = target.lower()
            if key in actions._WIN_ALIASES or actions._find_client(target):
                return lines.flavor(actions.focus_window(target))
    return None


def _player_in(t: str):
    for p in ("spotify", "brave", "chrome", "firefox", "youtube"):
        if p in t:
            return "brave" if p in ("chrome", "youtube") else p
    return None


# ── ¿esto son MANOS o es cabeza? ───────────────────────────────────────────
# Dentro de un modo (ORFEO o ICARO) todo lo que se dice va a ese motor, y eso
# esta bien para pensar pero es absurdo para actuar: ORFEO no tiene manos. El
# 01/09/2026 Wilmer, con ORFEO puesto, pidio "cierra Spotify" y le contesto un
# modelo suelto explicandole que pulsara Alt+F4 y que en el movil deslizara la
# app hacia arriba. Ni Spotify se cerro ni BLUE se entero.
#
# fast_route ya salva volumen, musica y ventanas. Lo que queda —abrir apps,
# temporizadores, apagar, correo— necesita las herramientas de PROMETEO. Esto
# distingue una cosa de la otra: un verbo de mandar Y un objeto que solo esta
# maquina tiene. Las dos condiciones a la vez, para no robarle a ICARO su
# encargo ("crea un archivo" no lleva ningun objeto de esta lista).
_ORDEN_VERBO = re.compile(
    r"\b(abre|abre\w+|abrir|abreme|[aá]breme|pon|ponme|ponle|poner|quita|"
    r"c[ieé]+rr\w*|cerrar|sube|s[uú]be\w*|baja|b[aá]ja\w*|silencia|"
    r"reproduce|pausa|p[aá]usa\w*|det[eé]n|salta|adelanta|apaga|ap[aá]ga\w*|"
    r"reinicia|suspende|bloquea|captura|capt[uú]r\w*|enfoca|mueve|maximiza|"
    r"minimiza|manda|env[ií]a|recu[eé]rdame|av[ií]same|despi[eé]rtame|"
    r"programa|activa|dime|revisa|checa|mira)\b", re.IGNORECASE)
_ORDEN_OBJETO = re.compile(
    r"\b(volumen|m[uú]sica|canci[oó]n|spotify|reproductor|sonido|audio|"
    r"ventana\w*|pantalla|brillo|pantallazo|escritorio|navegador|chrome|"
    r"brave|firefox|terminal|consola|calculadora|archivos|explorador|"
    r"temporizador|cron[oó]metro|alarma|recordatorio|pomodoro|computadora|"
    r"equipo|sesi[oó]n|wifi|bluetooth|portapapeles|correo|agenda|bater[ií]a|"
    r"hora|clima|pc)\b", re.IGNORECASE)


def es_orden_de_manos(text: str) -> bool:
    """¿Esto se lo tiene que hacer PROMETEO al escritorio, no pensarlo un motor?"""
    t = (text or "").lower()
    return bool(_ORDEN_VERBO.search(t) and _ORDEN_OBJETO.search(t))


def fast_route(text: str) -> str | None:
    t = text.lower().strip(" .,!¡¿?")

    # 0) trabajar en un proyecto (enfocar contexto) / salir del proyecto
    ws = _workspace_route(t)
    if ws is not None:
        return ws

    # 0b) taxonomía de estudio: nuevo curso/proyecto/trabajo, indexar, listar
    st = _study_route(t, text)
    if st is not None:
        return st

    # 0c) pomodoro por voz + adaptativo (arrancar/parar/estado/cansado/prisa)
    pom = _pomodoro_route(t, text)
    if pom is not None:
        return pom

    # 1) ejecutar protocolo/proyecto guardado (determinista: ejecuta/inicia/corre/pon/activa)
    proto = _protocol_route(t)
    if proto is not None:
        return proto

    # 1b) hora / fecha / cuenta regresiva (local, 0 tokens, con vibra)
    dt = _datetime_route(t)
    if dt is not None:
        return dt

    # 1b2) memoria persistente: recuerda / qué recuerdas / olvida (antes de agenda)
    mem = _memory_route(t)
    if mem is not None:
        return mem

    # 1c) correo (revisar) y agenda local (consultar/agregar/borrar), 0 tokens
    info = _info_route(t)
    if info is not None:
        return info

    # 1d) ventanas: listar / cerrar todo / cerrar la activa (determinista, 0 tokens)
    win = _window_route(t)
    if win is not None:
        return win

    # 1e) ver la pantalla (captura + Gemini multimodal, 0 tokens del cerebro)
    vis = _vision_route(t, text)
    if vis is not None:
        return vis

    # 1f) control de escritorio: enfocar ventana / brillo / captura (0 tokens)
    ctl = _control_route(t, text)
    if ctl is not None:
        return ctl

    # 2) si huele a creación/pregunta/abrir algo -> al cerebro
    if _BRAIN_WORDS.search(t):
        return None

    # 3) solo seguimos si es una orden CORTA (<= 6 palabras)
    if len(t.split()) > 6:
        return None

    player = _player_in(t)

    # --- volumen (verbos al inicio, inequívocos) ---
    if re.fullmatch(r"(silencio|mute|sil[eé]ncia\w*)", t):
        return lines.flavor(actions.toggle_mute())
    if re.match(r"^(sube|subir|súbe\w*|aumenta)\b.*volumen", t):
        n = re.search(r"(\d{1,3})", t)
        return lines.flavor(actions.adjust_volume(int(n.group(1)) if n else 10))
    if re.match(r"^(baja|bajar|bája\w*|disminuye|reduce)\b.*volumen", t):
        n = re.search(r"(\d{1,3})", t)
        return lines.flavor(actions.adjust_volume(-(int(n.group(1)) if n else 10)))
    if re.match(r"^(pon|ponlo|deja|fija)\b.*volumen", t) or re.match(r"^volumen\b", t):
        n = re.search(r"(\d{1,3})", t)
        if n:
            return lines.flavor(actions.set_volume(int(n.group(1))))

    # --- media (el verbo debe ir al INICIO de la orden) ---
    if re.match(r"^(pausa|p[aá]usa\w*|detén|deten)\b", t):
        return lines.flavor(actions.media_control("pause", player))
    if re.match(r"^(reanuda\w*|contin[uú]a\w*|dale play|reproduce)\b", t) and "spotify" in t:
        return lines.flavor(actions.media_control("play", player))
    if re.match(r"^(siguiente|adelanta\w*|next|salta|p[aá]sa\w*)\b", t):
        return lines.flavor(actions.media_control("next", player))
    if re.match(r"^(anterior|atr[aá]s|regresa\w*|previa)\b", t):
        return lines.flavor(actions.media_control("previous", player))

    return None
