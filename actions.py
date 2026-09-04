"""Acciones reales sobre el sistema (Hyprland / PipeWire / apps).

Cada accion devuelve un texto corto de confirmacion (para que el asistente
lo diga por voz). El mismo registro ACTIONS lo usan: (1) las herramientas que
ve Gemini y (2) los pasos guardados en los protocolos.
"""
from __future__ import annotations
import os
import re
import shlex
import subprocess
import urllib.parse
from pathlib import Path

def _primero_instalado(*candidatos: str) -> str:
    """El primero de la lista que exista de verdad en esta maquina."""
    import shutil
    return next((c for c in candidatos if shutil.which(c)), "")


def _navegador_del_sistema() -> str:
    """El navegador que Wilmer usa de verdad, preguntandoselo al sistema.

    Estaba escrito `google-chrome-stable` a pelo y en esta maquina NO ESTA
    INSTALADO: hay brave y firefox. O sea que "abre el navegador" no abria
    nada. Es el mismo agujero de `nautilus` que ya se tapo para los archivos,
    solo que en el navegador nadie lo miro.

    Se pregunta primero por el predeterminado (aqui contesta brave-browser) y
    si eso falla se coge el primero instalado.
    """
    try:
        d = subprocess.run(["xdg-settings", "get", "default-web-browser"],
                           capture_output=True, text=True, timeout=3)
        nombre = (d.stdout or "").strip().removesuffix(".desktop")
        # brave-browser.desktop -> el binario se llama `brave`
        for cand in (nombre, nombre.split("-")[0]):
            if cand and _primero_instalado(cand):
                return cand
    except (OSError, subprocess.SubprocessError):
        pass
    return _primero_instalado("brave", "google-chrome-stable", "google-chrome",
                              "chromium", "firefox") or "xdg-open"


TERMINAL = _primero_instalado("foot", "kitty", "alacritty", "wezterm",
                              "ghostty", "konsole", "gnome-terminal") or "foot"
BROWSER = _navegador_del_sistema()


# El gestor de archivos NO se puede dar por sentado. Estaba escrito "nautilus"
# a pelo, y en la maquina de Wilmer no esta instalado (hay dolphin y thunar):
# "abre la carpeta de archivos" lanzaba un binario inexistente y BLUE contestaba
# "Archivos abiertos" igual de contenta. El silencio venia de _exec_detached, que
# da por bueno el intento en cuanto hyprctl acepta la peticion —y hyprctl la
# acepta aunque el programa no exista, porque solo hace el fork—. Por eso aqui
# se comprueba ANTES de lanzar, como ya hacia open_application.
#
# Tampoco vale tirar de `xdg-open`: en esta maquina el manejador por defecto de
# inode/directory es kitty-open.desktop, o sea que abriria una terminal.
FILE_MANAGER = _primero_instalado("nautilus", "dolphin", "thunar", "nemo",
                                  "caja", "pcmanfm-qt", "pcmanfm")

# nombre hablado -> comando a ejecutar
APP_MAP = {
    "spotify": "spotify-launcher",
    "chrome": BROWSER, "navegador": BROWSER, "google chrome": BROWSER,
    "brave": "brave",
    "firefox": "firefox",
    "code": "code", "vscode": "code", "visual studio code": "code", "editor": "code",
    "archivos": FILE_MANAGER, "files": FILE_MANAGER,
    "gestor de archivos": FILE_MANAGER, "carpeta": FILE_MANAGER,
    "carpetas": FILE_MANAGER, "explorador": FILE_MANAGER,
    "terminal": TERMINAL, "consola": TERMINAL, "kitty": "kitty",
    "evince": "evince", "documentos": "evince", "lector": "evince", "pdf": "evince",
    "calculadora": "gnome-calculator", "calc": "gnome-calculator",
    "dolphin": "dolphin", "vlc": "vlc",
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _lua(s: str) -> str:
    """Un texto metido dentro de una cadena Lua sin que reviente la sintaxis."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _cerrar_lua(addr: str) -> str:
    """Cerrar UNA ventana concreta, y que sea esa.

    El selector va en tabla —`close({ window = "address:0x..." })`— y no como
    cadena suelta. La cadena tambien devuelve "ok", pero Hyprland la ignora y
    cierra LA VENTANA ENFOCADA. Probado con dos ventanas de prueba: pidiendo
    cerrar la segunda por cadena, seguia viva y la que se iba era la de al
    lado. Un "ok" que cierra otra cosa es peor que un error.
    """
    return f'hl.dsp.window.close({{ window = "address:{_lua(addr)}" }})'


def _dispatch(lua: str, *respaldo: str) -> bool:
    """Manda un dispatcher a Hyprland hablando el idioma de ESTA maquina.

    `hyprctl dispatch <verbo> <args>` esta roto AQUI, y no solo para `exec`
    como se creia: la config de Wilmer es la Lua de Caelestia, asi que hyprctl
    envuelve lo que le des en `return hl.dispatch(...)` y eso deja de ser Lua
    valido en cuanto el dispatcher lleva argumentos:

        error: [string "return hl.dispatch(closewindow address:0x55...)"]:1:
               ')' expected near 'address'

    O sea que CERRAR, ENFOCAR, MOVER y pantalla completa no funcionaban
    NINGUNA: BLUE contestaba "Ventana cerrada" con la ventana ahi delante.
    Es el mismo agujero que ya tapo `_exec_detached` para abrir apps, pero
    nadie lo llevo al resto.

    La forma que si entiende es `hyprctl eval` con la llamada Lua ya escrita
    (`hl.dispatch(hl.dsp.focus({ workspace = "empty" }))`), y esa va primero.
    El `dispatch` de toda la vida queda de respaldo para una maquina con
    hyprland.conf normal, donde el `eval` no existiria. Ojo con los selectores:
    van en tabla, no como cadena suelta; ver _cerrar_lua.

    Devuelve si de verdad se acepto, para no volver a jurar en vano.
    """
    intentos = [["hyprctl", "eval", f"hl.dispatch({lua})"]]
    if respaldo:
        intentos.append(["hyprctl", "dispatch", *respaldo])
    for cmd in intentos:
        try:
            r = _run(cmd)
        except OSError:
            return False              # no hay hyprctl: no hay nada que hacer
        salida = ((r.stdout or "") + (r.stderr or "")).lower()
        if r.returncode == 0 and "error" not in salida:
            return True
    return False


def _exec_detached(cmd: str, workspace: str | None = None) -> bool:
    """Lanza un programa. Devuelve si se lanzo DE VERDAD.

    Esto estaba roto entero y en silencio. Se usaba
    `hyprctl dispatch exec <cmd>`, pero el Hyprland de Wilmer corre la config
    Lua de Caelestia y ahi ese comando se interpreta como Lua:

        error: [string "return hl.dispatch(exec gnome-calculator)"]:1:
               ')' expected near 'gnome'

    O sea que NINGUNA app se abria nunca —ni la calculadora, ni el navegador,
    ni la terminal, ni los archivos, ni una URL—, y como nadie miraba el
    resultado, BLUE contestaba "Abriendo la calculadora" tan tranquila. Peor
    que no funcionar es jurar que funciono.

    Tres intentos, del que mejor se porta al que nunca falla:
      1. hl.dsp.exec_cmd, que es la forma que entiende la config Lua.
      2. `dispatch exec`, para un Hyprland con hyprland.conf de toda la vida.
      3. lanzarlo aqui mismo, que funciona hasta sin Hyprland.
    Los dos primeros respetan las reglas de ventana y el workspace; el tercero
    no, pero abre la aplicacion, que es lo que se habia pedido."""
    rule = f"[workspace {workspace} silent] " if workspace else ""
    entero = f"{rule}{cmd}"
    lua = entero.replace("\\", "\\\\").replace('"', '\\"')
    for intento in (["hyprctl", "eval",
                     f'hl.dispatch(hl.dsp.exec_cmd("{lua}"))'],
                    ["hyprctl", "dispatch", "exec", entero]):
        try:
            r = _run(intento)
        except OSError:
            break                     # no hay hyprctl: al plan C
        salida = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and "error" not in salida.lower():
            return True
    try:
        subprocess.Popen(shlex.split(cmd), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, ValueError):
        return False


# --------------------------------------------------------------- volumen
def _verdad(v) -> bool:
    """Un booleano dicho por un modelo, entendido de verdad.

    Los esquemas ya declaran el tipo bien, pero un modelo despistado sigue
    pudiendo mandar la cadena "false", y en Python eso es VERDADERO. Donde eso
    decide si se pisa un archivo o si se captura media pantalla, no se puede
    dejar al azar."""
    if isinstance(v, str):
        return v.strip().lower() not in ("", "false", "no", "0", "none", "null")
    return bool(v)


def set_volume(percent: int) -> str:
    percent = max(0, min(150, int(percent)))
    _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent/100:.2f}"])
    return f"Volumen al {percent} por ciento"

def adjust_volume(delta: int) -> str:
    sign = "+" if int(delta) >= 0 else "-"
    _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{abs(int(delta))}%{sign}"])
    return f"Volumen {'subido' if sign=='+' else 'bajado'} {abs(int(delta))} por ciento"

def toggle_mute() -> str:
    _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
    return "Listo, silencio alternado"


# ----------------------------------------------------------------- media
# Control de musica por MPRIS (D-Bus), no por playerctl.
#
# Todo esto llamaba a `playerctl`, que NO esta instalado en la maquina de
# Wilmer. `_run` no atrapa OSError, asi que la primera linea de _pick_player
# levantaba FileNotFoundError: "pausa la musica" no fallaba con un mensaje util,
# reventaba, y lo unico que le llegaba al cerebro era "(error en media_control:
# [Errno 2] No such file or directory: 'playerctl')". Por eso ninguna orden de
# musica funciono nunca.
#
# MPRIS es el mismo protocolo que playerctl usa por debajo, y se habla con
# `gdbus`, que viene dentro de glib y ya esta en el sistema. Asi se arregla
# dentro de BLUE, sin instalar paquetes.
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_IFACE = "org.mpris.MediaPlayer2.Player"


def _gdbus(*args: str) -> subprocess.CompletedProcess | None:
    """Una llamada a gdbus. None si ni siquiera se pudo lanzar."""
    try:
        return _run(["gdbus", "call", "--session", *args])
    except OSError:
        return None


def _mpris_players() -> list[str]:
    """Los reproductores que ahora mismo estan en el bus de sesion."""
    r = _gdbus("-d", "org.freedesktop.DBus", "-o", "/org/freedesktop/DBus",
               "-m", "org.freedesktop.DBus.ListNames")
    if r is None or r.returncode != 0:
        return []
    return re.findall(r"org\.mpris\.MediaPlayer2\.[\w.-]+", r.stdout or "")


def _mpris_prop(player: str, prop: str) -> str:
    r = _gdbus("-d", player, "-o", MPRIS_PATH,
               "-m", "org.freedesktop.DBus.Properties.Get", MPRIS_IFACE, prop)
    if r is None or r.returncode != 0:
        return ""
    m = re.search(r"'(.*)'", r.stdout or "")
    return m.group(1) if m else ""


def _mpris_meta(player: str) -> dict:
    """Artista y titulo de lo que suena. gdbus lo devuelve como texto GVariant,
    y de ahi solo hacen falta dos campos:
        'xesam:artist': <['OneRepublic']>, 'xesam:title': <'Something I Need'>
    """
    r = _gdbus("-d", player, "-o", MPRIS_PATH,
               "-m", "org.freedesktop.DBus.Properties.Get", MPRIS_IFACE,
               "Metadata")
    if r is None or r.returncode != 0:
        return {}
    texto = r.stdout or ""
    out = {}
    for campo, clave in (("xesam:title", "title"), ("xesam:artist", "artist")):
        m = re.search(re.escape(campo) + r"': <\[?'([^']*)'", texto)
        if m:
            out[clave] = m.group(1)
    return out


def _mpris_call(player: str, metodo: str) -> bool:
    r = _gdbus("-d", player, "-o", MPRIS_PATH, "-m", f"{MPRIS_IFACE}.{metodo}")
    return r is not None and r.returncode == 0


def _pick_player(prefer: str | None = None) -> str | None:
    """Elige el reproductor correcto cuando hay varios (Brave, Spotify, etc.)."""
    players = _mpris_players()
    if not players:
        return None
    if prefer:                                   # si pidieron uno concreto
        for p in players:
            if prefer.lower() in p.lower():
                return p
    for p in players:                            # el que esté REPRODUCIENDO
        if _mpris_prop(p, "PlaybackStatus") == "Playing":
            return p
    for p in players:                            # si no, prefiere Spotify
        if "spotify" in p.lower():
            return p
    return players[0]

def media_control(action: str, player: str | None = None) -> str:
    action = action.lower().strip()
    mapping = {
        "play": "play", "reproducir": "play", "reanudar": "play",
        "pause": "pause", "pausa": "pause", "pausar": "pause",
        "play-pause": "play-pause", "alternar": "play-pause",
        "next": "next", "siguiente": "next", "adelantar": "next",
        "previous": "previous", "anterior": "previous", "atras": "previous",
        "stop": "stop", "detener": "stop",
    }
    cmd = mapping.get(action, "play-pause")
    metodos = {"play": "Play", "pause": "Pause", "play-pause": "PlayPause",
               "next": "Next", "previous": "Previous", "stop": "Stop"}
    target = _pick_player(player)
    if not target:
        return "No hay ningún reproductor activo"
    # Y se comprueba que la orden se aceptara, en vez de darla por buena.
    if not _mpris_call(target, metodos[cmd]):
        return f"No pude {action} la música: el reproductor no aceptó la orden"
    # El nombre bonito es el ULTIMO trozo del nombre del bus. Con `split(".")[0]`
    # sobre "org.mpris.MediaPlayer2.spotify" BLUE decia "Pausado en org".
    name = target.rsplit(".", 1)[-1]
    verbs = {"pause": "Pausado", "play": "Reproduciendo", "next": "Siguiente",
             "previous": "Anterior", "stop": "Detenido", "play-pause": "Listo"}
    return f"{verbs.get(cmd, 'Listo')} en {name}"


# ------------------------------------------------------------------ apps
def _screen_to_workspace(screen) -> str | None:
    """Mapea 'pantalla 1/2' (o uno/dos/principal/secundaria) a su workspace.
    ws1 = monitor principal (DP-1), ws2 = el otro (HDMI-A-1)."""
    s = str(screen or "").lower().strip()
    if s in ("1", "uno", "primera", "primer", "principal", "main"):
        return "1"
    if s in ("2", "dos", "segunda", "segundo", "secundaria", "otra"):
        return "2"
    return None

def open_application(name: str, screen: str = "") -> str:
    import shutil
    key = name.lower().strip()
    # El mapa es una preferencia, no un dogma. Estaba "spotify" ->
    # "spotify-launcher", que es como lo empaqueta Arch en unas instalaciones y
    # no en otras: en la de Wilmer el binario es /usr/bin/spotify, asi que el
    # mapa mandaba a un sitio vacio y BLUE contestaba "No encontré la
    # aplicación 'spotify' instalada" con Spotify instalado y sonando. Se
    # prueban las dos, y gana la que exista de verdad.
    candidatos = [APP_MAP.get(key, key)]
    if key != candidatos[0]:
        candidatos.append(key)
    cmd = next((c for c in candidatos if shutil.which(c.split()[0])), None)
    if cmd is None:
        return f"No encontré la aplicación '{name}' instalada"
    ws = _screen_to_workspace(screen)
    # Y se mira si se lanzo. Antes se ignoraba el resultado y se contestaba que
    # si pasara lo que pasara.
    if not _exec_detached(cmd, workspace=ws):
        return f"No pude abrir {name}: falló el lanzamiento"
    if ws:
        return f"Abriendo {name} en la pantalla {screen}"
    return f"Abriendo {name}"

def open_in_new_workspace(name: str) -> str:
    """Abre la app en un escritorio (workspace) vacio y cambia a el."""
    key = name.lower().strip()
    cmd = APP_MAP.get(key, key)
    _dispatch('hl.dsp.focus({ workspace = "empty" })', "workspace", "empty")
    _exec_detached(cmd)
    return f"Abriendo {name} en un escritorio nuevo"

def open_terminal_at(path: str = "~") -> str:
    p = os.path.expanduser(path)
    _exec_detached(f"{TERMINAL} -D {shlex.quote(p)}")
    return f"Terminal abierta en {path}"

def open_terminal_run(path: str = "~", command: str = "", terminal: str = "kitty",
                     keep_open: bool = True, screen: str = "") -> str:
    """Abre una terminal en `path` y EJECUTA `command` dentro.
    Soluciona el caso de un solo proyecto: cd <path> && <command>.
    `keep_open=True` deja la shell abierta tras terminar para leer la salida.
    """
    import shutil
    p = os.path.expanduser(os.path.expandvars(path))
    term = (terminal or "kitty").lower().strip()
    if not shutil.which(term):
        term = TERMINAL  # fallback al terminal por defecto
    cmd = (command or "").strip()
    tail = "; exec bash" if _verdad(keep_open) else ""
    inner = f"{cmd}{tail}" if cmd else "exec bash"
    if term == "kitty":
        full = f"kitty --directory {shlex.quote(p)} -- bash -lc {shlex.quote(inner)}"
    elif term in ("foot", "alacritty", "wezterm", "ghostty"):
        # estos aceptan -e <cmd...>; usamos bash para soportar `cd` y &&
        full = f"{term} -e bash -lc {shlex.quote(f'cd {shlex.quote(p)} && {inner}')}"
    else:
        full = f"{term} -e bash -lc {shlex.quote(f'cd {shlex.quote(p)} && {inner}')}"
    ws = _screen_to_workspace(screen)
    _exec_detached(full, workspace=ws)
    if cmd:
        return f"Lanzando {cmd.split()[0]} en {term}"
    return f"Terminal {term} abierta en {path}"

def open_files_at(path: str = "~") -> str:
    p = os.path.expanduser(path)
    if not FILE_MANAGER:
        return ("No tengo ningún gestor de archivos que abrir: no encontré "
                "nautilus, dolphin, thunar, nemo, caja ni pcmanfm")
    if not _exec_detached(f"{FILE_MANAGER} {shlex.quote(p)}"):
        return f"No pude abrir la carpeta {path}: falló el lanzamiento"
    return f"Archivos abiertos en {path}"

def open_project(path: str) -> str:
    """Abre VS Code en la carpeta del proyecto."""
    p = os.path.expanduser(path)
    _exec_detached(f"code {shlex.quote(p)}")
    return f"Proyecto abierto en VS Code: {path}"


# ------------------------------------------------------------------- web
def web_search(engine: str, query: str) -> str:
    q = urllib.parse.quote(query)
    urls = {
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "google": f"https://www.google.com/search?q={q}",
    }
    url = urls.get(engine.lower(), urls["google"])
    _exec_detached(f"{BROWSER} --new-window {shlex.quote(url)}")
    return f"Buscando '{query}' en {engine}"

def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _exec_detached(f"{BROWSER} --new-window {shlex.quote(url)}")
    return f"Abriendo {url}"


# --------------------------------------------------------------- spotify
def play_spotify(query: str) -> str:
    """Abre Spotify en la busqueda de la cancion. Si ydotool esta disponible,
    intenta reproducir el primer resultado con una pulsacion de tecla."""
    uri = f"spotify:search:{query}"
    _run(["xdg-open", uri])
    # intento de auto-play (opcional, requiere ydotool + ydotoold)
    import shutil, time
    if shutil.which("ydotool"):
        try:
            time.sleep(3.0)            # esperar a que cargue la busqueda
            # bajar a resultados y reproducir (heuristica del cliente de Spotify)
            subprocess.run(["ydotool", "key", "15:1", "15:0"], timeout=3)  # Tab
            subprocess.run(["ydotool", "key", "28:1", "28:0"], timeout=3)  # Enter
        except Exception:
            pass
    return f"Buscando '{query}' en Spotify"


# ------------------------------------------------------ tiempo / temporizadores
def schedule_command(delay_seconds: int, shell_cmd: str, say: str = "") -> str:
    """Ejecuta un comando de shell tras un retraso (temporizadores)."""
    n = max(1, int(delay_seconds))
    subprocess.Popen(["bash", "-c", f"sleep {n}; {shell_cmd}"],
                     start_new_session=True)
    mins = n / 60
    return say or f"Hecho, lo hare en {mins:.0f} minutos" if mins >= 1 else \
        say or f"Hecho, en {n} segundos"

_TERMINALS = ["kitty", "foot", "alacritty", "wezterm", "ghostty", "konsole",
              "gnome-terminal"]

def close_application(name: str) -> str:
    """Cierra una app por su nombre hablado: "cierra Spotify".

    Va por la VENTANA primero y por `pkill` solo si no hay ninguna. Antes era
    `pkill -f <lo que abre la app>` a secas y eso fallaba justo en el caso mas
    pedido: Spotify se lanza con `spotify-launcher`, pero el proceso que queda
    corriendo se llama `spotify`, asi que el pkill no encontraba nada y BLUE
    contestaba "Cerrando Spotify" con Spotify sonando. Cerrar la ventana ademas
    es lo educado: la app guarda lo suyo y se va, en vez de morir de golpe.
    """
    key = name.lower().strip()
    # "terminal/consola" es ambiguo: cierra el emulador que realmente corre
    if key in ("terminal", "consola"):
        running = [t for t in _TERMINALS
                   if _run(["pgrep", "-x", t]).returncode == 0]
        if not running:
            return "No veo ninguna terminal abierta"
        for t in running:
            _run(["pkill", "-x", t])
        return f"Cerrando {', '.join(running)}"

    ventanas = _clients_de(key)
    if ventanas:
        for c in ventanas:
            _dispatch(_cerrar_lua(c["address"]),
                      "closewindow", f"address:{c['address']}")
        quedan = _esperar_cierre({c["address"] for c in ventanas})
        if not quedan:
            return f"Cerré {name}"
        return f"{name} no se deja cerrar, Wilmer: te está pidiendo algo"

    # Sin ventana: o no esta abierta, o corre sin ventana propia. Se intenta el
    # proceso, y se comprueba, que es lo que faltaba.
    target = APP_MAP.get(key, key)
    proc = Path(target).name
    candidatos = {proc, key}
    if proc.endswith("-launcher"):
        candidatos.add(proc[:-len("-launcher")])   # spotify-launcher -> spotify
    vivos = [c for c in candidatos if _run(["pgrep", "-x", c]).returncode == 0]
    if not vivos:
        return f"No veo {name} abierto, Wilmer"
    for c in vivos:
        _run(["pkill", "-x", c])
    return f"Cerré {name}"


def _clients_de(key: str) -> list:
    """Todas las ventanas abiertas de una app, por su nombre hablado."""
    frag = _WIN_ALIASES.get(key, key)
    fuera = []
    for c in _clients():
        if not c.get("address") or c.get("hidden"):
            continue
        cls = (c.get("class") or c.get("initialClass") or "").lower()
        if frag and frag in cls:
            fuera.append(c)
    return fuera

def close_active_window() -> str:
    "Cierra la ventana actualmente enfocada."
    if not _dispatch("hl.dsp.window.close()", "killactive"):
        return "No pude cerrar la ventana, Wilmer"
    return "Ventana cerrada"

def close_all_windows() -> str:
    """Cierra TODAS las ventanas abiertas (el asistente sigue de fondo).

    Y COMPRUEBA que se cerraron. Antes contaba cuantas peticiones habia mandado
    y decia "Cerrando 3 ventanas" aunque no se cerrara ninguna —que era el caso
    siempre, porque iba por `dispatch closewindow`—. Una ventana tambien puede
    quedarse abierta por su cuenta (un editor preguntando si guardas), y eso hay
    que decirlo en vez de dar el parte de una victoria que no hubo.
    """
    antes = [c for c in _clients() if c.get("address")]
    if not antes:
        return "No tienes ninguna ventana abierta, Wilmer"
    for c in antes:
        _dispatch(_cerrar_lua(c["address"]),
                  "closewindow", f"address:{c['address']}")
    # Cerrar no es instantaneo: la app recibe el aviso y se va cuando puede.
    quedan = _esperar_cierre({c["address"] for c in antes})
    n = len(antes) - len(quedan)
    if not quedan:
        return f"Listo, cerré {n} {'ventana' if n == 1 else 'ventanas'}"
    if n == 0:
        return "No se dejaron cerrar, Wilmer. Están pidiendo algo en pantalla"
    resisten = ", ".join(sorted({_nice_window_name(c.get("class") or "")
                                 for c in _clients()
                                 if c.get("address") in quedan}))
    return (f"Cerré {n}, pero {resisten} sigue ahí: te está pidiendo algo")


def _esperar_cierre(direcciones: set, plazo: float = 2.5) -> set:
    """Las que SIGUEN abiertas pasado el plazo. Sondea, no duerme a ciegas."""
    import time
    fin = time.time() + plazo
    quedan = set(direcciones)
    while quedan and time.time() < fin:
        time.sleep(0.15)
        vivas = {c.get("address") for c in _clients()}
        quedan &= vivas
    return quedan

# nombre técnico de ventana (clase) -> nombre hablado bonito
_NICE_NAMES = {
    "brave-browser": "Brave", "brave": "Brave",
    "google-chrome": "Chrome", "chromium": "Chrome",
    "firefox": "Firefox", "code": "VS Code", "code-oss": "VS Code",
    "spotify": "Spotify", "vlc": "VLC", "mpv": "el reproductor",
    "kitty": "una terminal", "foot": "una terminal", "alacritty": "una terminal",
    "wezterm": "una terminal", "ghostty": "una terminal", "konsole": "una terminal",
    "org.gnome.nautilus": "los archivos", "nautilus": "los archivos",
    "dolphin": "los archivos", "evince": "un PDF",
    "org.gnome.calculator": "la calculadora", "gnome-calculator": "la calculadora",
}

def _nice_window_name(cls: str) -> str:
    c = (cls or "").lower().strip()
    return _NICE_NAMES.get(c, cls or "una ventana")

def list_windows() -> str:
    "Lista las ventanas/apps abiertas ahora mismo (lee Hyprland, 0 tokens)."
    import json
    out = _run(["hyprctl", "clients", "-j"])
    try:
        clients = json.loads(out.stdout)
    except Exception:
        clients = []
    nombres: list[str] = []
    for c in clients:
        if not c.get("mapped", True) or c.get("hidden"):
            continue
        cls = c.get("class") or c.get("initialClass") or ""
        if not cls:
            continue
        nombres.append(_nice_window_name(cls))
    if not nombres:
        return "Ahora mismo no tienes ninguna ventana abierta"
    # contar repetidas: "dos de Brave"
    from collections import Counter
    cuenta = Counter(nombres)
    partes = []
    _NUM = {2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"}
    for nombre, n in cuenta.items():
        if n == 1:
            partes.append(nombre)
        else:
            partes.append(f"{_NUM.get(n, str(n))} de {nombre}")
    total = len(nombres)
    if len(partes) == 1:
        return f"Tienes abierto {partes[0]}"
    lista = ", ".join(partes[:-1]) + " y " + partes[-1]
    return f"Tienes {total} ventanas abiertas: {lista}"

# ------------------------------------------------- enfocar / mover ventanas
# nombre hablado -> fragmento que aparece en la CLASS de la ventana
_WIN_ALIASES = {
    # "navegador" apunta al que de verdad esta puesto: buscar "chrome" en las
    # clases de ventana no encontraba nunca el Brave de Wilmer.
    "navegador": BROWSER.split("-")[0] or "chrome",
    "chrome": "chrome", "google chrome": "chrome",
    "brave": "brave",
    "firefox": "firefox",
    "código": "code", "codigo": "code", "code": "code", "vscode": "code",
    "visual studio code": "code", "vs code": "code", "editor": "code",
    "spotify": "spotify",
    "archivos": "nautilus", "files": "nautilus", "gestor de archivos": "nautilus",
    "nautilus": "nautilus", "dolphin": "dolphin",
    "terminal": "kitty", "consola": "kitty", "kitty": "kitty", "foot": "foot",
    "pdf": "evince", "documento": "evince", "lector": "evince", "evince": "evince",
    "calculadora": "calculator", "calc": "calculator",
    "vlc": "vlc",
}

def _clients() -> list:
    import json
    out = _run(["hyprctl", "clients", "-j"])
    try:
        return json.loads(out.stdout)
    except Exception:
        return []

def _find_client(name: str) -> dict | None:
    """Busca una ventana abierta cuyo class/title encaje con `name` (hablado)."""
    key = (name or "").lower().strip()
    frag = _WIN_ALIASES.get(key, key)
    best = None
    for c in _clients():
        if not c.get("mapped", True) or c.get("hidden"):
            continue
        cls = (c.get("class") or c.get("initialClass") or "").lower()
        title = (c.get("title") or "").lower()
        if frag and (frag in cls or frag in title):
            return c
        if key and (key in cls or key in title):
            best = best or c
    return best

def focus_window(name: str) -> str:
    "Enfoca/trae al frente una ventana ya abierta por su nombre."
    c = _find_client(name)
    if not c:
        return f"No veo ninguna ventana de {name} abierta, Wilmer"
    addr = c.get("address")
    if not addr:
        return f"No pude ubicar la ventana de {name}"
    if not _dispatch(f'hl.dsp.focus({{ window = "address:{_lua(addr)}" }})',
                     "focuswindow", f"address:{addr}"):
        return f"No pude traer la ventana de {name}, Wilmer"
    return f"Ahí tienes {_nice_window_name(c.get('class') or '')}, Wilmer"

def move_window(where: str) -> str:
    """Mueve/ajusta la VENTANA ENFOCADA. where: '1'/'2' (mandarla a esa pantalla),
    'completa'/'maximizar', 'flotante' o 'centrar'."""
    w = (where or "").lower().strip()
    ws = _screen_to_workspace(w)
    if ws:
        if not _dispatch(f'hl.dsp.window.move({{ workspace = "{_lua(ws)}" }})',
                         "movetoworkspace", ws):
            return "No pude mover la ventana, Wilmer"
        return f"Ventana movida a la pantalla {where}"
    if w in ("completa", "pantalla completa", "fullscreen", "maximizar",
             "maximiza", "máximo", "maximo"):
        if not _dispatch('hl.dsp.window.fullscreen({ mode = "maximized" })',
                         "fullscreen", "1"):
            return "No pude ponerla a pantalla completa, Wilmer"
        return "Ventana a pantalla completa"
    if w in ("flotante", "flota", "flotar", "floating"):
        if not _dispatch("hl.dsp.window.float()", "togglefloating"):
            return "No pude cambiar el modo flotante, Wilmer"
        return "Listo, alterné el modo flotante"
    if w in ("centrar", "centra", "centrada", "centro", "center"):
        if not _dispatch("hl.dsp.window.center()", "centerwindow"):
            return "No pude centrarla, Wilmer"
        return "Ventana centrada"
    return f"No entendí a dónde mover la ventana ('{where}'), Wilmer"


# ------------------------------------------------------------- portapapeles
def clipboard_get() -> str:
    "Lee lo que hay en el portapapeles (texto copiado)."
    import shutil
    if not shutil.which("wl-paste"):
        return "No tengo cómo leer el portapapeles, Wilmer (falta wl-paste)"
    out = _run(["wl-paste", "-n"])
    text = (out.stdout or "").strip()
    if not text:
        return "El portapapeles está vacío, Wilmer"
    if len(text) > 600:
        text = text[:600] + "…"
    return text

def clipboard_set(text: str) -> str:
    "Copia un texto al portapapeles del sistema."
    import shutil
    if not shutil.which("wl-copy"):
        return "No tengo cómo copiar al portapapeles, Wilmer (falta wl-copy)"
    try:
        subprocess.run(["wl-copy", text], timeout=5)
    except Exception as e:
        return f"No pude copiar: {e}"
    return "Copiado al portapapeles, Wilmer"


# -------------------------------------------------------------------- brillo
def _brightness_pct() -> int | None:
    out = _run(["brightnessctl", "-m"])           # ej: name,class,cur,40%,max
    try:
        for field in out.stdout.strip().split(","):
            if field.endswith("%"):
                return int(field[:-1])
    except Exception:
        pass
    return None

def set_brightness(percent: int) -> str:
    "Fija el brillo de la pantalla a un porcentaje (0 a 100)."
    import shutil
    if not shutil.which("brightnessctl"):
        return "No tengo control de brillo, Wilmer (falta brightnessctl)"
    p = max(1, min(100, int(percent)))            # 1% mínimo, no apagar del todo
    _run(["brightnessctl", "set", f"{p}%"])
    return f"Brillo al {p} por ciento"

def adjust_brightness(delta: int) -> str:
    "Sube (positivo) o baja (negativo) el brillo en N por ciento."
    import shutil
    if not shutil.which("brightnessctl"):
        return "No tengo control de brillo, Wilmer (falta brightnessctl)"
    d = int(delta)
    sign = "+" if d >= 0 else "-"
    _run(["brightnessctl", "set", f"{abs(d)}%{sign}"])
    cur = _brightness_pct()
    base = f"Brillo {'subido' if sign=='+' else 'bajado'} {abs(d)} por ciento"
    return f"{base}, al {cur} por ciento" if cur is not None else base


# --------------------------------------------------------- captura a archivo
def take_screenshot(region: bool = False) -> str:
    """Guarda una captura de pantalla en ~/Imágenes/Capturas. region=True deja
    seleccionar un área con el ratón (slurp)."""
    import shutil, time
    region = _verdad(region)
    if not shutil.which("grim"):
        return "No tengo cómo capturar, Wilmer (falta grim)"
    folder = Path.home() / "Imágenes" / "Capturas"
    folder.mkdir(parents=True, exist_ok=True)
    path = str(folder / f"captura_{time.strftime('%Y%m%d_%H%M%S')}.png")
    cmd = ["grim"]
    if region:
        if not shutil.which("slurp"):
            return "No puedo seleccionar área, Wilmer (falta slurp)"
        sel = _run(["slurp"])
        geo = (sel.stdout or "").strip()
        if not geo:
            return "Cancelaste la selección, Wilmer"
        cmd += ["-g", geo]
    else:
        mon = None
        import json
        try:
            for m in json.loads(_run(["hyprctl", "monitors", "-j"]).stdout or "[]"):
                if m.get("focused"):
                    mon = m.get("name")
        except Exception:
            mon = None
        if mon:
            cmd += ["-o", mon]
    cmd.append(path)
    r = _run(cmd)
    if r.returncode != 0 or not os.path.exists(path):
        return "No pude tomar la captura, Wilmer"
    # copiar la ruta al portapapeles es de más; la abrimos para que la vea
    try:
        subprocess.Popen(["xdg-open", path], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return f"Captura guardada en {path}"


# Salir de la sesion. Se arma aqui y no en linea porque power_action lo mete en
# un `bash -c` con retraso, y hay que citarlo entero.
_SALIR_SESION = ["hyprctl", "eval", "hl.dispatch(hl.dsp.exit())"]


def power_action(action: str = "poweroff") -> str:
    "Apaga/reinicia/suspende el equipo o cierra sesión."
    m = {
        "poweroff": (["systemctl", "poweroff"], "Apagando la computadora"),
        "apagar":   (["systemctl", "poweroff"], "Apagando la computadora"),
        "reboot":   (["systemctl", "reboot"], "Reiniciando"),
        "reiniciar":(["systemctl", "reboot"], "Reiniciando"),
        "suspend":  (["systemctl", "suspend"], "Suspendiendo"),
        "suspender":(["systemctl", "suspend"], "Suspendiendo"),
        # Cerrar sesion va por `eval` como todo lo demas: ver _dispatch.
        "logout":   (_SALIR_SESION, "Cerrando sesión"),
        "cerrar sesion": (_SALIR_SESION, "Cerrando sesión"),
    }
    cmd, msg = m.get(action.lower().strip(), m["poweroff"])
    # retraso para que Blue alcance a narrar/confirmar por voz antes de apagar
    subprocess.Popen(["bash", "-c", f"sleep 15; {shlex.join(cmd)}"],
                     start_new_session=True)
    return msg


# ------------------------------------------------------- registro central
ACTIONS = {
    "set_volume": set_volume,
    "adjust_volume": adjust_volume,
    "toggle_mute": toggle_mute,
    "media_control": media_control,
    "open_application": open_application,
    "open_in_new_workspace": open_in_new_workspace,
    "open_terminal_at": open_terminal_at,
    "open_terminal_run": open_terminal_run,
    "open_files_at": open_files_at,
    "open_project": open_project,
    "web_search": web_search,
    "open_url": open_url,
    "play_spotify": play_spotify,
    "schedule_command": schedule_command,
    "close_application": close_application,
    "close_active_window": close_active_window,
    "close_all_windows": close_all_windows,
    "list_windows": list_windows,
    "focus_window": focus_window,
    "move_window": move_window,
    "clipboard_get": clipboard_get,
    "clipboard_set": clipboard_set,
    "set_brightness": set_brightness,
    "adjust_brightness": adjust_brightness,
    "take_screenshot": take_screenshot,
    "power_action": power_action,
}


def run_action(name: str, params: dict) -> str:
    fn = ACTIONS.get(name)
    if not fn:
        return f"(accion desconocida: {name})"
    try:
        return fn(**params)
    except Exception as e:
        return f"(error en {name}: {e})"


# ── archivos y carpetas ────────────────────────────────────────────────────
# Faltaba lo más simple. BLUE sabía crear "proyectos" y "espacios de estudio",
# que son contenedores con protocolo y memoria propia, pero no una carpeta y
# ya. Así que "crea una carpeta en Documentos que se llame feria tecnológica"
# se colaba por la maquinaria de proyectos y acababa en Proyectos Universidad.
#
# Y durante un tiempo eso fue TODO lo que sabía hacer con archivos: crear una
# carpeta y listarla. No había borrar, mover, renombrar, copiar, leer ni
# escribir, así que "borra esto" no fallaba, es que no existía la mano. El
# modelo, sin herramienta, contestaba que ya estaba hecho. De ahí la queja de
# que fingía. Todo lo de aquí abajo se acota a la carpeta personal, y borrar
# es SIEMPRE a la papelera: una orden dicha a medias no puede costar trabajo.

_CASA_INTOCABLE = {"", "Documentos", "Descargas", "Escritorio", "Imágenes",
                   "Música", "Vídeos", "Videos", "Plantillas", "Público"}


# Como escribe un modelo el nombre de una carpeta y como se llama de verdad son
# dos cosas distintas: sin tildes, en minusculas, o directamente en ingles.
_ALIAS_CARPETAS = {
    "documents": "Documentos",   "downloads": "Descargas",
    "desktop":   "Escritorio",   "pictures":  "Imágenes",
    "music":     "Música",       "videos":    "Vídeos",
    "templates": "Plantillas",   "public":    "Público",
}


def _plano(s: str) -> str:
    """En minusculas y sin tildes, para comparar nombres de archivo."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def _casar_en_disco(p):
    """La ruta REAL de p cuando el nombre no casa letra a letra. None si no hay.

    Solo se usa cuando la ruta exacta NO existe, asi que nunca pisa un acierto:
    en esta casa conviven `Music` y `Música`, y `Pictures` e `Imágenes`, y pedir
    `Music` tiene que seguir abriendo `Music`.
    """
    from pathlib import Path
    if p.exists():
        return p
    partes = list(p.parts)
    if not partes:
        return None
    actual = Path(partes[0])
    for seg in partes[1:]:
        if (actual / seg).exists():
            actual = actual / seg
            continue
        if not actual.is_dir():
            return None
        objetivo = _plano(seg)
        elegido = None
        try:
            for hijo in actual.iterdir():
                if _plano(hijo.name) == objetivo:
                    elegido = hijo
                    break
        except OSError:
            return None
        if elegido is None:
            # El alias de idioma va el ULTIMO y solo si el nombre espanol existe:
            # llegar aqui ya prueba que el ingles no.
            esp = _ALIAS_CARPETAS.get(objetivo)
            if esp and (actual / esp).exists():
                elegido = actual / esp
        if elegido is None:
            return None
        actual = elegido
    return actual


def _ruta_casa(ruta: str, base: str = "Documentos"):
    """Resuelve una ruta dicha en voz alta y la encierra en la carpeta personal.

    Devuelve (Path, None) si vale, o (None, motivo) si no. Lo relativo cuelga
    de `base` porque Wilmer nombra las cosas por su nombre a secas ("borra el
    presupuesto"), no por su ruta completa."""
    from pathlib import Path
    txt = str(ruta or "").strip().strip('"').strip("'")
    if not txt:
        return None, "No me dijiste cuál."
    p = Path(txt).expanduser()
    if not p.is_absolute():
        raiz = Path(base)
        p = (raiz if raiz.is_absolute() else Path.home() / base) / p
        # Puede que no nombrara algo DENTRO de Documentos sino una carpeta de la
        # casa ("las descargas", "el escritorio"). Si por la base no sale nada,
        # se prueba colgando de la casa antes de rendirse.
        if not p.exists() and _casar_en_disco(p) is None:
            desde_casa = _casar_en_disco(Path.home() / Path(txt).expanduser())
            if desde_casa is not None:
                p = desde_casa
    # Ultimo intento antes de dar la ruta por mala: casarla con lo que hay de
    # verdad en el disco. El 03/09/2026 un cerebro pidio "/home/wilmer/Documents"
    # y luego "/home/wilmer/documentos"; la carpeta se llama "Documentos", el
    # sistema de archivos distingue mayusculas, y las dos fallaron. Wilmer se
    # quedo con que no tenia carpeta de documentos.
    real = _casar_en_disco(p)
    if real is not None:
        p = real
    casa = Path.home().resolve()
    try:
        # resolve(strict=False) sigue los symlinks: así un enlace que apunte
        # fuera de la casa tampoco cuela.
        destino = p.resolve()
        destino.relative_to(casa)
    except (ValueError, OSError):
        return None, f"Eso está fuera de tu carpeta personal y no lo toco: {p}"
    return destino, None


def _protegida(p) -> bool:
    """¿Es la casa misma o una de las carpetas grandes del sistema?"""
    from pathlib import Path
    casa = Path.home().resolve()
    if p == casa:
        return True
    rel = p.relative_to(casa).as_posix() if p != casa else ""
    return rel in _CASA_INTOCABLE


def _breve(p) -> str:
    """La ruta como se dice en voz alta, sin el /home/wilmer delante."""
    from pathlib import Path
    casa = Path.home().resolve()
    if p == casa:
        return "tu carpeta personal"
    try:
        return "~/" + str(p.relative_to(casa))
    except ValueError:
        return str(p)


def crear_carpeta(ruta: str) -> str:
    """Crea una carpeta (y las intermedias que falten) dentro de la casa."""
    destino, err = _ruta_casa(ruta)
    if err:
        return err
    if destino.is_file():
        return f"Ahí ya hay un archivo con ese nombre, no una carpeta: {_breve(destino)}"
    if destino.is_dir():
        return f"Esa carpeta ya existía: {_breve(destino)}"
    try:
        destino.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"No pude crear la carpeta: {e}"
    return f"Carpeta creada: {_breve(destino)}"


def listar_carpeta(ruta: str = "") -> str:
    """Dice qué hay dentro de una carpeta."""
    from pathlib import Path
    if not str(ruta or "").strip():
        destino, err = Path.home().resolve() / "Documentos", None
    else:
        destino, err = _ruta_casa(ruta)
    if err:
        return err
    if not destino.is_dir():
        return f"No existe esa carpeta: {_breve(destino)}"
    cosas = sorted(destino.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    if not cosas:
        return f"{_breve(destino)} está vacía."
    nombres = [(c.name + "/" if c.is_dir() else c.name) for c in cosas[:40]]
    extra = f" y {len(cosas) - 40} cosas más" if len(cosas) > 40 else ""
    return f"En {_breve(destino)}: " + ", ".join(nombres) + extra + "."


def borrar(ruta: str) -> str:
    """Manda algo a la PAPELERA. Nunca borra de verdad: se puede deshacer."""
    import shutil
    import subprocess
    destino, err = _ruta_casa(ruta)
    if err:
        return err
    if not destino.exists():
        return (f"No encuentro {_breve(destino)}. Mira antes con listar_carpeta "
                f"o buscar_archivo, no des por hecho que ya no está.")
    if _protegida(destino):
        return (f"No mando a la papelera {_breve(destino)}: es una de tus carpetas "
                f"grandes. Dime qué hay dentro que quieres borrar.")
    # gio deja el archivo recuperable desde el gestor de archivos y guarda de
    # dónde salió. Es la papelera de verdad del escritorio, no un apaño.
    if shutil.which("gio"):
        try:
            out = subprocess.run(["gio", "trash", str(destino)],
                                 capture_output=True, text=True, timeout=30)
            if out.returncode == 0:
                return f"A la papelera: {_breve(destino)}. Se puede recuperar."
            fallo = (out.stderr or "").strip()
        except (subprocess.SubprocessError, OSError) as e:
            fallo = str(e)
    else:
        fallo = "no hay gio"
    # Sin gio, papelera a mano según la spec de freedesktop, con su .trashinfo
    # para que el gestor de archivos sepa restaurarlo a su sitio.
    from datetime import datetime
    from pathlib import Path
    papelera = Path.home() / ".local/share/Trash"
    try:
        (papelera / "files").mkdir(parents=True, exist_ok=True)
        (papelera / "info").mkdir(parents=True, exist_ok=True)
        nombre, n = destino.name, 1
        while (papelera / "files" / nombre).exists():
            nombre, n = f"{destino.stem}.{n}{destino.suffix}", n + 1
        (papelera / "info" / f"{nombre}.trashinfo").write_text(
            "[Trash Info]\n"
            f"Path={destino}\n"
            f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
        shutil.move(str(destino), str(papelera / "files" / nombre))
    except OSError as e:
        return f"No pude mandarlo a la papelera ({fallo}): {e}"
    return f"A la papelera: {_breve(destino)}. Se puede recuperar."


def mover(origen: str, destino: str) -> str:
    """Mueve un archivo o carpeta a otro sitio de la casa."""
    import shutil
    o, err = _ruta_casa(origen)
    if err:
        return err
    if not o.exists():
        return f"No encuentro {_breve(o)}."
    if _protegida(o):
        return f"No muevo {_breve(o)}: es una de tus carpetas grandes."
    d, err = _ruta_casa(destino, base=str(o.parent))
    if err:
        return err
    if d.is_dir():                      # "mueve el informe a Descargas"
        d = d / o.name
    if d == o:
        return f"{_breve(o)} ya está ahí."
    if d.exists():
        return f"Ya hay algo llamado {d.name} en {_breve(d.parent)}. Dime otro nombre."
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(o), str(d))
    except OSError as e:
        return f"No pude moverlo: {e}"
    return f"Movido a {_breve(d)}."


def renombrar(ruta: str, nombre_nuevo: str) -> str:
    """Le cambia el nombre a un archivo o carpeta, sin sacarlo de su sitio."""
    o, err = _ruta_casa(ruta)
    if err:
        return err
    if not o.exists():
        return f"No encuentro {_breve(o)}."
    if _protegida(o):
        return f"No renombro {_breve(o)}: es una de tus carpetas grandes."
    nuevo = str(nombre_nuevo or "").strip().strip('"').strip("'")
    if not nuevo or "/" in nuevo:
        return "Dime solo el nombre nuevo, sin rutas."
    # Si dicta "informe" para un "informe.pdf", se le conserva la extensión:
    # al oído no se le dice ".pdf" y perderla rompe con qué app abre.
    if o.is_file() and o.suffix and not nuevo.endswith(o.suffix):
        nuevo += o.suffix
    d = o.parent / nuevo
    if d == o:
        return f"Ya se llama así: {o.name}."
    if d.exists():
        return f"Ya hay algo llamado {nuevo} ahí. Dime otro nombre."
    try:
        o.rename(d)
    except OSError as e:
        return f"No pude renombrarlo: {e}"
    return f"Renombrado a {nuevo}, en {_breve(d.parent)}."


def copiar(origen: str, destino: str) -> str:
    """Copia un archivo o carpeta, dejando el original donde está."""
    import shutil
    o, err = _ruta_casa(origen)
    if err:
        return err
    if not o.exists():
        return f"No encuentro {_breve(o)}."
    # Un destino sin ruta ("cópialo a copia.txt") quiere decir AL LADO del
    # original, no en ~/Documentos. Resolverlo contra Documentos hacía que la
    # copia apareciera lejos del archivo del que salió.
    d, err = _ruta_casa(destino, base=str(o.parent))
    if err:
        return err
    if d.is_dir() and o.name != d.name:
        d = d / o.name
    if d.exists():
        return f"Ya hay algo llamado {d.name} en {_breve(d.parent)}. Dime otro nombre."
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        if o.is_dir():
            shutil.copytree(str(o), str(d))
        else:
            shutil.copy2(str(o), str(d))
    except OSError as e:
        return f"No pude copiarlo: {e}"
    return f"Copiado en {_breve(d)}."


def buscar_archivo(nombre: str, dentro: str = "") -> str:
    """Busca por nombre dentro de la carpeta personal. Sirve para localizar
    algo antes de moverlo o borrarlo."""
    from pathlib import Path
    patron = str(nombre or "").strip().strip('"').strip("'").lower()
    if not patron:
        return "Dime qué busco."
    if str(dentro or "").strip():
        raiz, err = _ruta_casa(dentro)
        if err:
            return err
    else:
        raiz = Path.home().resolve()
    if not raiz.is_dir():
        return f"No existe esa carpeta: {_breve(raiz)}"
    saltar = {".git", ".venv", "node_modules", "__pycache__", ".cache",
              ".local", ".config", ".mozilla", ".steam", "Trash"}
    # `fd` está en C y recorre en paralelo: la misma búsqueda que en Python
    # tardaba 24 s la resuelve en décimas. Se le pasa el patrón como texto
    # literal (--fixed-strings), que es como lo dicta Wilmer, no como regex.
    import shutil as _sh
    import subprocess as _sp
    if _sh.which("fd"):
        # SIN --hidden a propósito. Cuando Wilmer dice "busca el archivo
        # pendientes" se refiere a lo suyo, no a la configuración de sus
        # programas, y fd salta los directorios ocultos por defecto. Además de
        # ser lo correcto es lo rápido: con --hidden y media docena de
        # --exclude, fd ya no puede cortar pronto y recorría la casa entera en
        # 15 s; sin ocultos, la misma búsqueda tarda 0,02 s.
        cmd = ["fd", "--fixed-strings", "--ignore-case", "--absolute-path",
               "--max-results", "25"]
        for s in ("node_modules", "__pycache__", ".venv", ".git"):
            cmd += ["--exclude", s]
        cmd += [patron, str(raiz)]
        try:
            out = _sp.run(cmd, capture_output=True, text=True, timeout=20)
            rutas = [Path(l) for l in out.stdout.splitlines() if l.strip()]
            if not rutas:
                return f"No hay nada que se llame así en {_breve(raiz)}."
            filas = [_breve(p) + ("/" if p.is_dir() else "") for p in rutas]
            return f"Encontré {len(filas)}: " + ", ".join(filas) + "."
        except (_sp.SubprocessError, OSError):
            pass                          # si fd falla, se recorre a mano
    encontrados = []
    for base, dirs, ficheros in __import__("os").walk(raiz):
        dirs[:] = [d for d in dirs if d not in saltar and not d.startswith(".")]
        for nom in dirs + ficheros:
            if patron in nom.lower():
                encontrados.append(Path(base) / nom)
                if len(encontrados) >= 25:
                    break
        if len(encontrados) >= 25:
            break
    if not encontrados:
        return f"No hay nada que se llame así en {_breve(raiz)}."
    filas = [_breve(p) + ("/" if p.is_dir() else "") for p in encontrados]
    return f"Encontré {len(filas)}: " + ", ".join(filas) + "."


def leer_archivo(ruta: str, lineas: int = 200) -> str:
    """Lee un archivo de texto y devuelve su contenido."""
    destino, err = _ruta_casa(ruta)
    if err:
        return err
    if destino.is_dir():
        return (f"{_breve(destino)} es una carpeta, no un archivo. "
                f"Para ver qué hay dentro, usa listar_carpeta.")
    if not destino.is_file():
        return f"No encuentro ese archivo: {_breve(destino)}"
    if destino.stat().st_size > 2_000_000:
        return (f"{_breve(destino)} pesa demasiado para leerlo entero. "
                f"Si hay que trabajarlo, pásaselo a ÉREBO con dev_task.")
    try:
        texto = destino.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return f"{_breve(destino)} no es un archivo de texto."
    filas = texto.splitlines()
    corte = filas[:max(1, int(lineas))]
    extra = f"\n(...y {len(filas) - len(corte)} líneas más)" if len(filas) > len(corte) else ""
    return f"{_breve(destino)}:\n" + "\n".join(corte) + extra


def escribir_archivo(ruta: str, contenido: str, anexar: bool = False) -> str:
    """Escribe un archivo de texto. No pisa nada existente salvo que se anexe."""
    destino, err = _ruta_casa(ruta)
    if err:
        return err
    anexar = _verdad(anexar)
    if destino.is_dir():
        return f"{_breve(destino)} es una carpeta, no un archivo."
    if destino.exists() and not anexar:
        return (f"Ya existe {_breve(destino)} y no lo piso. Dime otro nombre, "
                f"o si quieres que le añada esto al final.")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "a" if anexar else "w") as f:
            f.write(str(contenido or ""))
    except OSError as e:
        return f"No pude escribirlo: {e}"
    verbo = "Añadido al final de" if anexar else "Escrito"
    return f"{verbo} {_breve(destino)}."


def estado_maquina() -> str:
    """Estado de ESTA computadora ahora mismo: cuánto lleva encendida, memoria y disco libres, carga de CPU, en qué escritorio estás, qué ventanas hay abiertas y qué música suena. Úsala cuando Wilmer pregunte por el estado del equipo; esos datos no están en tu contexto porque cambian a cada segundo."""
    import conciencia
    return conciencia.ahora_mismo()
