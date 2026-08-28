"""Acciones reales sobre el sistema (Hyprland / PipeWire / apps).

Cada accion devuelve un texto corto de confirmacion (para que el asistente
lo diga por voz). El mismo registro ACTIONS lo usan: (1) las herramientas que
ve Gemini y (2) los pasos guardados en los protocolos.
"""
from __future__ import annotations
import os
import shlex
import subprocess
import urllib.parse
from pathlib import Path

TERMINAL = "foot"
BROWSER = "google-chrome-stable"

# nombre hablado -> comando a ejecutar
APP_MAP = {
    "spotify": "spotify-launcher",
    "chrome": BROWSER, "navegador": BROWSER, "google chrome": BROWSER,
    "brave": "brave",
    "firefox": "firefox",
    "code": "code", "vscode": "code", "visual studio code": "code", "editor": "code",
    "archivos": "nautilus", "files": "nautilus", "gestor de archivos": "nautilus",
    "dolphin": "dolphin",
    "terminal": TERMINAL, "consola": TERMINAL, "kitty": "kitty",
    "evince": "evince", "documentos": "evince", "lector": "evince", "pdf": "evince",
    "calculadora": "gnome-calculator", "calc": "gnome-calculator",
    "dolphin": "dolphin", "vlc": "vlc",
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)

def _exec_detached(cmd: str, workspace: str | None = None):
    """Lanza un programa via Hyprland (respeta reglas de ventana)."""
    rule = f"[workspace {workspace} silent] " if workspace else ""
    return _run(["hyprctl", "dispatch", "exec", f"{rule}{cmd}"])


# --------------------------------------------------------------- volumen
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
def _pick_player(prefer: str | None = None) -> str | None:
    """Elige el reproductor correcto cuando hay varios (Brave, Spotify, etc.)."""
    players = _run(["playerctl", "-l"]).stdout.split()
    if not players:
        return None
    if prefer:                                   # si pidieron uno concreto
        for p in players:
            if prefer.lower() in p.lower():
                return p
    for p in players:                            # el que esté REPRODUCIENDO
        if _run(["playerctl", "-p", p, "status"]).stdout.strip() == "Playing":
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
    target = _pick_player(player)
    if not target:
        return "No hay ningún reproductor activo"
    _run(["playerctl", "-p", target, cmd])
    name = target.split(".")[0]
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
    cmd = APP_MAP.get(key, key)        # si no esta mapeada, intenta el nombre tal cual
    binary = cmd.split()[0]
    if not shutil.which(binary):
        return f"No encontré la aplicación '{name}' instalada"
    ws = _screen_to_workspace(screen)
    _exec_detached(cmd, workspace=ws)
    if ws:
        return f"Abriendo {name} en la pantalla {screen}"
    return f"Abriendo {name}"

def open_in_new_workspace(name: str) -> str:
    """Abre la app en un escritorio (workspace) vacio y cambia a el."""
    key = name.lower().strip()
    cmd = APP_MAP.get(key, key)
    _run(["hyprctl", "dispatch", "workspace", "empty"])
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
    tail = "; exec bash" if keep_open else ""
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
    _exec_detached(f"nautilus {shlex.quote(p)}")
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
    target = APP_MAP.get(key, key)
    proc = Path(target).name
    _run(["pkill", "-f", proc])
    return f"Cerrando {name}"

def close_active_window() -> str:
    "Cierra la ventana actualmente enfocada."
    _run(["hyprctl", "dispatch", "killactive"])
    return "Ventana cerrada"

def close_all_windows() -> str:
    "Cierra TODAS las ventanas abiertas (el asistente sigue corriendo de fondo)."
    import json
    out = _run(["hyprctl", "clients", "-j"])
    try:
        clients = json.loads(out.stdout)
    except Exception:
        clients = []
    n = 0
    for c in clients:
        addr = c.get("address")
        if addr:
            _run(["hyprctl", "dispatch", "closewindow", f"address:{addr}"])
            n += 1
    return f"Cerrando {n} ventanas"

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
    "navegador": "chrome", "chrome": "chrome", "google chrome": "chrome",
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
    _run(["hyprctl", "dispatch", "focuswindow", f"address:{addr}"])
    return f"Ahí tienes {_nice_window_name(c.get('class') or '')}, Wilmer"

def move_window(where: str) -> str:
    """Mueve/ajusta la VENTANA ENFOCADA. where: '1'/'2' (mandarla a esa pantalla),
    'completa'/'maximizar', 'flotante' o 'centrar'."""
    w = (where or "").lower().strip()
    ws = _screen_to_workspace(w)
    if ws:
        _run(["hyprctl", "dispatch", "movetoworkspace", ws])
        return f"Ventana movida a la pantalla {where}"
    if w in ("completa", "pantalla completa", "fullscreen", "maximizar",
             "maximiza", "máximo", "maximo"):
        _run(["hyprctl", "dispatch", "fullscreen", "1"])
        return "Ventana a pantalla completa"
    if w in ("flotante", "flota", "flotar", "floating"):
        _run(["hyprctl", "dispatch", "togglefloating"])
        return "Listo, alterné el modo flotante"
    if w in ("centrar", "centra", "centrada", "centro", "center"):
        _run(["hyprctl", "dispatch", "centerwindow"])
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


def power_action(action: str = "poweroff") -> str:
    "Apaga/reinicia/suspende el equipo o cierra sesión."
    m = {
        "poweroff": (["systemctl", "poweroff"], "Apagando la computadora"),
        "apagar":   (["systemctl", "poweroff"], "Apagando la computadora"),
        "reboot":   (["systemctl", "reboot"], "Reiniciando"),
        "reiniciar":(["systemctl", "reboot"], "Reiniciando"),
        "suspend":  (["systemctl", "suspend"], "Suspendiendo"),
        "suspender":(["systemctl", "suspend"], "Suspendiendo"),
        "logout":   (["hyprctl", "dispatch", "exit"], "Cerrando sesión"),
        "cerrar sesion": (["hyprctl", "dispatch", "exit"], "Cerrando sesión"),
    }
    cmd, msg = m.get(action.lower().strip(), m["poweroff"])
    # retraso para que Blue alcance a narrar/confirmar por voz antes de apagar
    subprocess.Popen(["bash", "-c", f"sleep 15; {' '.join(cmd)}"],
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


# ── carpetas sueltas ───────────────────────────────────────────────────────
# Faltaba lo más simple. BLUE sabía crear "proyectos" y "espacios de estudio",
# que son contenedores con protocolo y memoria propia, pero no una carpeta y
# ya. Así que "crea una carpeta en Documentos que se llame feria tecnológica"
# se colaba por la maquinaria de proyectos y acababa en Proyectos Universidad.
def crear_carpeta(ruta: str) -> str:
    """Crea una carpeta (y las intermedias que falten) dentro de la casa."""
    from pathlib import Path
    p = Path(str(ruta).strip().strip('"').strip("'")).expanduser()
    if not p.is_absolute():                       # "feria tecnológica" -> Documentos
        p = Path.home() / "Documentos" / p
    casa = Path.home().resolve()
    try:
        destino = p.resolve()
        destino.relative_to(casa)                 # nada fuera de /home/wilmer
    except (ValueError, OSError):
        return f"No creo carpetas fuera de tu carpeta personal: {p}"
    if destino.is_file():
        return f"Ahí ya hay un archivo con ese nombre, no una carpeta: {destino}"
    if destino.is_dir():
        return f"Esa carpeta ya existía: {destino}"
    try:
        destino.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"No pude crear la carpeta: {e}"
    return f"Carpeta creada: {destino}"


def listar_carpeta(ruta: str = "") -> str:
    """Dice qué hay dentro de una carpeta."""
    from pathlib import Path
    p = Path(str(ruta).strip() or str(Path.home() / "Documentos")).expanduser()
    if not p.is_absolute():
        p = Path.home() / "Documentos" / p
    if not p.is_dir():
        return f"No existe esa carpeta: {p}"
    cosas = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    if not cosas:
        return f"{p} está vacía."
    nombres = [(c.name + "/" if c.is_dir() else c.name) for c in cosas[:40]]
    extra = f" y {len(cosas) - 40} cosas más" if len(cosas) > 40 else ""
    return f"En {p}: " + ", ".join(nombres) + extra + "."
