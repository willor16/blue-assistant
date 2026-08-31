#!/usr/bin/env python
"""Asistente de voz de Wilmer.

Modos:
  blue.py daemon     residente: voz (Super+J) + interfaz web. Lo normal.
  blue.py trigger    dispara una escucha (lo llama Super+J)
  blue.py panel      abre la interfaz grafica (ventana flotante)
  blue.py stop       apaga el asistente
  blue.py text "..." prueba por texto, sin microfono
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import config

CONFIG_DIR = Path.home() / ".config" / "blue"
FIFO = CONFIG_DIR / "trigger"
PID_FILE = CONFIG_DIR / "daemon.pid"
PANEL_URL = "http://127.0.0.1:8777"


def notify(title: str, body: str = ""):
    subprocess.run(["notify-send", "-a", "Asistente", "-t", "3000", title, body],
                   check=False)

# Navegadores de la familia Chromium: todos aceptan --app= (ventana sin barras).
# Se prueba en orden y se usa el primero que exista, en vez de exigir
# google-chrome-stable, que en muchos equipos no esta (aqui hay Brave).
# OJO con --class: en Wayland estos navegadores lo IGNORAN y se ponen de app_id
# "<navegador>-<host>__-<perfil>" (p.ej. "brave-127.0.0.1__-Default"). Se pasa
# igual porque en X11 si funciona, pero la window rule de Hyprland tiene que
# casar ese otro patron o el panel sale tilado.
_NAVEGADORES_APP = ("google-chrome-stable", "google-chrome", "chromium",
                    "brave", "brave-browser", "vivaldi-stable",
                    "microsoft-edge-stable")


def _lanzar(cmd: list[str]) -> None:
    """Arranca algo y lo desliga de este proceso, que muere en cuanto termina.

    Antes esto se hacia con `hyprctl dispatch exec "cmd con args"`, y dejo de
    funcionar: Hyprland ya interpreta el argumento de dispatch como Lua, asi que
    `exec qs -p ...` reventaba con "')' expected near 'qs'" y ni la burbuja ni
    el panel llegaban a abrirse. Lanzarlo directo no depende de ese parser y
    ademas funciona fuera de Hyprland.
    """
    subprocess.Popen(cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_panel():
    for navegador in _NAVEGADORES_APP:
        ruta = shutil.which(navegador)
        if ruta:
            _lanzar([ruta, f"--app={PANEL_URL}", "--class=blue-panel"])
            return
    # Firefox no tiene --app, pero --kiosk deja la ventana limpia parecida.
    ruta = shutil.which("firefox")
    if ruta:
        _lanzar([ruta, "--kiosk", "--class=blue-panel", PANEL_URL])
        return
    import webbrowser
    webbrowser.open(PANEL_URL)

def _window_open(cls: str) -> bool:
    import json
    out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True)
    try:
        return any(c.get("class") == cls for c in json.loads(out.stdout))
    except Exception:
        return False

BUBBLE_QML = str(Path.home() / ".local/share/blue/ui/shell.qml")
JARVIS_DIR = Path(__file__).resolve().parent

LOCK_FILE = CONFIG_DIR / "daemon.lock"
_cerrojo = None            # se guarda aquí para que el fd viva todo el proceso


def _es_blue(pid: int) -> bool:
    """¿Ese PID es de verdad un daemon nuestro, o un número reciclado?"""
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
    except Exception:
        return False
    return "blue.py" in cmd and "daemon" in cmd


def _daemon_alive() -> bool:
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)                    # señal 0 = solo comprueba que existe
        return _es_blue(pid)
    except Exception:
        return False


def tomar_cerrojo() -> bool:
    """Coge el cerrojo del daemon. False = ya hay otro corriendo.

    Es un flock: lo suelta el kernel cuando el proceso muere, así que no se
    queda atascado ni aunque el daemon se caiga de mala manera. El PID_FILE
    sirve para hablar con él (señales); el cerrojo es quien manda.
    """
    global _cerrojo
    import fcntl
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _cerrojo = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_cerrojo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _cerrojo.close()
        _cerrojo = None
        return False
    _cerrojo.write(f"{os.getpid()}\n")
    _cerrojo.flush()
    return True

def ensure_daemon() -> bool:
    """Arranca el daemon si está apagado. Devuelve True si tuvo que arrancarlo."""
    if _daemon_alive():
        return False
    log = open("/tmp/jd.log", "ab", buffering=0)
    subprocess.Popen([sys.executable, "blue.py", "daemon"],
                     cwd=str(JARVIS_DIR), stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    return True

def open_bubble():
    """Abre la ventana flotante nativa de Blue (Quickshell), si no está ya abierta."""
    r = subprocess.run(["pgrep", "-f", "blue/ui/shell.qml"], capture_output=True)
    if r.returncode == 0:
        return
    qs = shutil.which("qs") or shutil.which("quickshell")
    if qs:
        _lanzar([qs, "-p", BUBBLE_QML])


def main():
    cfg = config.load()
    mode = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    if mode == "text":
        from assistant import Assistant
        a = Assistant(cfg)
        print(a.handle_text(" ".join(sys.argv[2:]), speak=False))
        return

    if mode == "trigger":
        # si Blue está apagado, lo enciende (saludará) y termina
        if ensure_daemon():
            notify("Encendiendo a Blue", "Dame unos segundos y vuelve a tocar Super+J")
            return
        # 1) interrumpe cualquier voz en curso (barge-in)
        try:
            import signal
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGUSR1)
        except Exception:
            pass
        # 2) muestra la burbuja flotante (feedback visual de estado)
        open_bubble()
        # 3) pide escuchar (handle_voice graba hasta detectar silencio)
        if FIFO.exists():
            with open(FIFO, "w") as f:
                f.write("listen\n")
        return

    if mode == "converse":
        # Charla de corrido: responde y sigue escuchando sin volver a pulsar.
        # El método existía desde hacía tiempo en assistant.py y no lo llamaba
        # nadie: era código muerto, así que Wilmer nunca pudo conversar.
        if ensure_daemon():
            notify("Encendiendo a Blue", "Dame unos segundos y vuelve a intentar")
            return
        try:
            import signal
            os.kill(int(PID_FILE.read_text().strip()), signal.SIGUSR1)
        except Exception:
            pass
        open_bubble()
        if FIFO.exists():
            with open(FIFO, "w") as f:
                f.write("converse\n")
        return

    if mode in ("ptt-start", "ptt-stop"):
        # push-to-talk: ptt-start al presionar Super+J, ptt-stop al soltar
        if mode == "ptt-start":
            if ensure_daemon():                # estaba apagado: lo despierta (saludará)
                notify("Encendiendo a Blue", "Dame unos segundos y vuelve a intentar")
                return                          # esta pulsación no graba aún
            open_bubble()                       # muestra la ventana flotante
        if FIFO.exists():
            with open(FIFO, "w") as f:
                f.write(mode + "\n")
        return

    if mode == "toggle":
        # encender/apagar Blue (atajo dedicado). Apaga con despedida.
        if _daemon_alive():
            try:
                urllib.request.urlopen(PANEL_URL + "/api/stop", data=b"", timeout=2)
            except Exception:
                pass
        else:
            ensure_daemon()
            notify("Encendiendo a Blue", "Dame unos segundos...")
        return

    if mode == "interrupt":
        # detener la voz que esté sonando (lo usa el botón ⏹ de la ventana)
        try:
            import signal
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGUSR1)
        except Exception:
            pass
        return

    if mode == "panel":
        if ensure_daemon():
            notify("Encendiendo a Blue", "El panel cargará en unos segundos")
        open_panel()
        return

    if mode == "stop":
        try:
            urllib.request.urlopen(PANEL_URL + "/api/stop", data=b"", timeout=2)
        except Exception:
            pass
        print("Asistente apagado.")
        return

    if mode == "daemon":
        import signal
        import store
        import voice
        from assistant import Assistant
        import web

        if not tomar_cerrojo():
            otro = ""
            try:
                otro = f" (PID {PID_FILE.read_text().strip()})"
            except Exception:
                pass
            print(f"Ya hay un asistente en marcha{otro}. No arranco otro.")
            return

        if FIFO.exists():
            FIFO.unlink()
        os.mkfifo(FIFO)
        PID_FILE.write_text(str(os.getpid()))

        # SIGUSR1 = interrumpe la voz en curso (lo manda Super+J)
        signal.signal(signal.SIGUSR1, lambda *_: voice.interrumpir())

        assistant = Assistant(cfg)
        # servidor web (interfaz) en un hilo
        threading.Thread(target=web.run_server, args=(assistant,),
                         daemon=True).start()
        # precargar modelos para respuesta rápida
        assistant.preload()
        store.set_status("idle")

        # (El wake-word "Hey Blue" se retiró: consumía RAM/CPU sin parar y tenía
        #  fuga de memoria. Ahora se activa con push-to-talk: mantener Super+J.)

        notify("Blue está listo", "Mantén Super+J para hablar · Super+Shift+J: panel")
        print(f"Blue listo. Interfaz en {PANEL_URL}")
        try:
            import lines
            assistant.speak(lines.greeting())
        except Exception:
            pass
        try:
            while True:
                with open(FIFO) as f:
                    cmd = f.read().strip()
                try:
                    if cmd.startswith("ptt-start"):
                        assistant.ptt_start()
                    elif cmd.startswith("ptt-stop"):
                        assistant.ptt_stop()
                    elif cmd.startswith("converse"):
                        assistant.converse()
                    elif cmd.startswith("listen"):
                        assistant.handle_voice()
                except Exception as e:
                    print(f"(error en interacción: {e})")
                    store.set_status("idle")
        except KeyboardInterrupt:
            store.set_status("idle")
            FIFO.unlink(missing_ok=True)
            PID_FILE.unlink(missing_ok=True)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
