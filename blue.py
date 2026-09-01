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


def _mandar(orden: str) -> bool:
    """Le pasa una orden al daemon por el FIFO, SIN quedarse colgado.

    Abrir un FIFO para escritura bloquea hasta que alguien lo lea. Si el daemon
    esta vivo pero atascado, el `with open(FIFO, "w")` de antes se quedaba ahi
    para siempre: cada pulsacion de Super+J dejaba un proceso colgado y no
    pasaba nada visible. O_NONBLOCK falla al instante con ENXIO si no hay
    lector, y asi se puede avisar en vez de fingir que todo va bien.
    """
    if not FIFO.exists():
        notify("Blue no está en marcha", "Enciéndela con Super+Ctrl+J")
        return False
    try:
        fd = os.open(str(FIFO), os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        notify("Blue no responde", "Está viva pero atascada. Super+Ctrl+J para reiniciarla")
        return False
    try:
        os.write(fd, (orden + "\n").encode())
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


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
        _mandar("listen")
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
        _mandar("converse")
        return

    if mode in ("ptt-start", "ptt-stop"):
        # push-to-talk: ptt-start al presionar Super+J, ptt-stop al soltar
        if mode == "ptt-start":
            if ensure_daemon():                # estaba apagado: lo despierta (saludará)
                notify("Encendiendo a Blue", "Dame unos segundos y vuelve a intentar")
                return                          # esta pulsación no graba aún
            open_bubble()                       # muestra la ventana flotante
        _mandar(mode)
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

        # Decia "Manten Super+J", que es push-to-talk, pero install.sh y el
        # README documentan `blue trigger`: se pulsa UNA vez y Blue detecta sola
        # cuando terminas. La notificacion contradecia a la documentacion y al
        # comportamiento real.
        notify("Blue está lista", "Super+J: hablar · Super+Shift+J: panel")
        print(f"Blue listo. Interfaz en {PANEL_URL}")
        try:
            import lines
            assistant.speak(lines.greeting())
        except Exception:
            pass
        # El turno se atiende en un HILO, no en este bucle.
        #
        # Antes se ejecutaba aqui mismo: mientras Blue grababa, pensaba o
        # hablaba, este bucle no volvia a `open(FIFO)` y el FIFO se quedaba SIN
        # LECTOR. Entonces Super+J caia en el O_NONBLOCK de _mandar(), daba
        # ENXIO y saltaba la notificacion "Blue no responde. Esta viva pero
        # atascada" — que era mentira: estaba trabajando, no atascada. Ese es el
        # motivo de que "pausa la musica" pulsado mientras Blue hablaba no
        # llegara nunca al daemon: la orden no se perdia dentro de Blue, es que
        # no entraba.
        #
        # No hace falta control de concurrencia aqui: handle_voice y converse ya
        # toman el cerrojo `_busy` y avisan en voz alta si hay un turno en curso.
        def _atender(cmd: str) -> None:
            try:
                if cmd.startswith("ptt-start"):
                    assistant.ptt_start()
                elif cmd.startswith("ptt-stop"):
                    assistant.ptt_stop()
                elif cmd.startswith("converse"):
                    assistant.converse()
                elif cmd.startswith("listen"):
                    # 2 s de gracia: Super+J acaba de mandar SIGUSR1 y el turno
                    # anterior todavia esta soltando el cerrojo.
                    assistant.handle_voice(espera=2.0)
            except Exception as e:
                print(f"(error en interacción: {e})", flush=True)
                store.set_status("idle")

        # El FIFO se abre UNA VEZ y en lectura-escritura, y no se cierra jamas.
        #
        # Antes se hacia `with open(FIFO) as f:` dentro del bucle. Eso deja un
        # hueco: al salir del `with` el descriptor se cierra, y hasta que la
        # vuelta siguiente lo reabre NO HAY LECTOR. Quien pulse Super+J justo en
        # ese instante cae en el O_NONBLOCK de _mandar(), recibe ENXIO y ve
        # "Blue no responde. Esta viva pero atascada" — con Blue perfectamente
        # sana y de brazos cruzados. Es una ventana de microsegundos, pero se
        # abre en CADA orden, asi que aparece sola con el uso.
        #
        # Con O_RDWR el propio daemon mantiene tambien un extremo de escritura
        # abierto: nunca hay "sin lector" para quien escribe, y del lado de la
        # lectura nunca llega EOF, asi que readline() simplemente espera. El
        # hueco desaparece del todo en vez de hacerse mas pequeno.
        fifo_fd = os.open(str(FIFO), os.O_RDWR)
        try:
            with os.fdopen(fifo_fd, "r", buffering=1) as f:
              while True:
                cmd = (f.readline() or "").strip()
                if not cmd:
                    continue
                if cmd.startswith("ptt-start"):
                    # En linea a proposito. Es instantaneo —abre el stream del
                    # microfono y vuelve— y asi queda garantizado que ocurre
                    # ANTES del ptt-stop que llega al soltar la tecla. En un
                    # hilo las dos ordenes podrian adelantarse entre si y
                    # pararia una grabacion que aun no habia empezado.
                    _atender(cmd)
                else:
                    threading.Thread(target=_atender, args=(cmd,),
                                     daemon=True).start()
        except KeyboardInterrupt:
            store.set_status("idle")
            FIFO.unlink(missing_ok=True)
            PID_FILE.unlink(missing_ok=True)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
