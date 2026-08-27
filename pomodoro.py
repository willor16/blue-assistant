"""Pomodoro por voz y ADAPTATIVO para las sesiones de estudio de Wilmer.

Un temporizador que corre en un hilo de fondo dentro del daemon y AVISA SOLO
(por voz + ventana) cuando cambia de fase: enfoque -> descanso -> enfoque...
No gasta tokens: el hilo llama a un "announcer" (callback que pone assistant.py,
igual que el narrador de protocolos) y las frases salen de aquí con la vibra de
Blue.

Adaptativo: mientras corre, Wilmer puede decir "estoy cansado" (acorta el bloque
y adelanta un descanso), "tengo prisa" (salta el descanso / alarga el enfoque),
"cuánto falta", "para el pomodoro". El router atrapa todo esto a 0 tokens.

Estadísticas: cada bloque de enfoque COMPLETADO suma minutos en
~/.config/blue/pomodoro.json (por día y por etiqueta/curso). Sirve para el
panel web y para el "plan de repaso pre-parcial".
"""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "blue"
STATS_FILE = CONFIG_DIR / "pomodoro.json"

# valores por defecto (minutos)
DEF_FOCUS = 25
DEF_BREAK = 5
DEF_LONG_BREAK = 15
CYCLES_TO_LONG = 4          # cada 4 bloques de enfoque, un descanso largo

_ANNOUNCER = None           # callback(text) que habla; lo pone assistant.py
_lock = threading.Lock()
_session: "_Session | None" = None


def set_announcer(fn) -> None:
    """assistant.py registra aquí cómo 'hablar' los avisos (voz + ventana)."""
    global _ANNOUNCER
    _ANNOUNCER = fn


def _say(text: str) -> None:
    if _ANNOUNCER:
        try:
            _ANNOUNCER(text)
        except Exception:
            pass


# --------------------------------------------------------------- estadísticas
def _load_stats() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_stats(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    except OSError:
        pass


def _log_focus(minutes: int, label: str) -> None:
    """Suma minutos de enfoque COMPLETADOS al día de hoy y a la etiqueta."""
    if minutes <= 0:
        return
    data = _load_stats()
    day = time.strftime("%Y-%m-%d")
    d = data.setdefault(day, {"total": 0, "blocks": 0, "by_label": {}})
    d["total"] = d.get("total", 0) + minutes
    d["blocks"] = d.get("blocks", 0) + 1
    lab = label or "general"
    d["by_label"][lab] = d["by_label"].get(lab, 0) + minutes
    _save_stats(data)


def today_stats() -> dict:
    """{total, blocks, by_label} de hoy (para el panel web). Solo lee."""
    return _load_stats().get(time.strftime("%Y-%m-%d"),
                             {"total": 0, "blocks": 0, "by_label": {}})


def label_minutes(label: str, days: int = 14) -> int:
    """Minutos de enfoque dedicados a una etiqueta en los últimos `days` días.
    Lo usa el plan de repaso para saber a qué le has metido (o no) horas."""
    data = _load_stats()
    lab = (label or "general").lower()
    cutoff = time.time() - days * 86400
    total = 0
    for day, d in data.items():
        try:
            ts = time.mktime(time.strptime(day, "%Y-%m-%d"))
        except ValueError:
            continue
        if ts < cutoff:
            continue
        for k, v in d.get("by_label", {}).items():
            if k.lower() == lab:
                total += v
    return total


# --------------------------------------------------------------- la sesión
class _Session:
    """Temporizador en un hilo: enfoque/descanso alternados, avisos hablados."""

    def __init__(self, focus: int, label: str, brk: int, long_brk: int,
                 cycles: int):
        self.focus = focus
        self.brk = brk
        self.long_brk = long_brk
        self.label = label
        self.cycles = cycles            # 0 = indefinido (hasta que lo paren)
        self.phase = "focus"            # 'focus' | 'break'
        self.remaining = focus * 60     # segundos restantes de la fase
        self.done_focus = 0             # bloques de enfoque completados
        self.paused = False
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    # -- bucle del hilo: cuenta atrás en ticks de 1s, reacciona a ajustes --
    def _run(self):
        while not self._stop.is_set():
            with self._cond:
                if self.paused:
                    self._cond.wait(timeout=1.0)
                    continue
                if self.remaining > 0:
                    self.remaining -= 1
                    self._cond.wait(timeout=1.0)
                    continue
            # la fase llegó a 0 -> transición (fuera del lock, puede hablar)
            self._next_phase()

    def _next_phase(self):
        if self.phase == "focus":
            self.done_focus += 1
            _log_focus(self.focus, self.label)
            # ¿toca descanso largo?
            if self.cycles and self.done_focus >= self.cycles:
                self._finish_all()
                return
            is_long = self.done_focus % CYCLES_TO_LONG == 0
            mins = self.long_brk if is_long else self.brk
            with self._cond:
                self.phase = "break"
                self.remaining = mins * 60
            tag = f" de {self.label}" if self.label else ""
            kind = "largo" if is_long else ""
            _say(f"Bloque{tag} completo, Wilmer. Llevas {self.done_focus}. "
                 f"Tómate {mins} minutos de descanso {kind}.".replace("  ", " "))
        else:  # terminó el descanso -> de vuelta a enfoque
            with self._cond:
                self.phase = "focus"
                self.remaining = self.focus * 60
            tag = f" con {self.label}" if self.label else ""
            _say(f"Se acabó el descanso, Wilmer. De vuelta{tag}: "
                 f"{self.focus} minutos de enfoque. A darle.")

    def _finish_all(self):
        self._stop.set()
        tag = f" de {self.label}" if self.label else ""
        n = self.done_focus
        bloques = "el bloque" if n == 1 else f"los {n} bloques"
        _say(f"Terminaste {bloques}{tag}, Wilmer. "
             f"Sesión cumplida. Orgulloso de ti, aunque no lo parezca.")
        global _session
        with _lock:
            if _session is self:
                _session = None

    # -------- controles (se llaman desde el hilo principal, con _lock fuera) --
    def stop(self) -> int:
        """Detiene. Devuelve minutos de enfoque ya completados."""
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        return self.done_focus

    def status_phase(self) -> tuple[str, int, int]:
        with self._cond:
            return self.phase, self.remaining, self.done_focus

    def adjust(self, kind: str) -> str:
        """Ajuste adaptativo en caliente. kind: 'tired' | 'hurry'."""
        with self._cond:
            if kind == "tired":
                # cansado: corta el enfoque actual y manda a descanso ya,
                # con descanso un poco más largo
                if self.phase == "focus":
                    self.remaining = 1   # forzar transición a descanso pronto
                    self.brk = min(self.brk + 3, 15)
                    self._cond.notify_all()
                    return ("Te oigo cansado, Wilmer. Cierro este bloque y te "
                            f"doy {self.brk} minutos para respirar.")
                self.remaining += 5 * 60
                self._cond.notify_all()
                return "Va, te extiendo el descanso cinco minutos más, Wilmer."
            if kind == "hurry":
                # con prisa: si está en descanso, sáltalo; si enfoca, alárgalo
                if self.phase == "break":
                    self.remaining = 1
                    self._cond.notify_all()
                    return ("Sin descanso entonces, Wilmer. Volvemos al enfoque "
                            "de una vez. Tú sabrás.")
                self.remaining += 10 * 60
                self.brk = max(self.brk - 2, 2)
                self._cond.notify_all()
                return ("Modo prisa: te alargo el enfoque diez minutos y recorto "
                        "los descansos, Wilmer.")
        return ""

    def pause(self) -> str:
        with self._cond:
            self.paused = True
            self._cond.notify_all()
        return "Pausado, Wilmer. El reloj te espera. Dime 'reanuda' cuando sigas."

    def resume(self) -> str:
        with self._cond:
            self.paused = False
            self._cond.notify_all()
        return "Reanudando, Wilmer. Se acabó el descanso improvisado."


# --------------------------------------------------------------- API pública
def is_running() -> bool:
    with _lock:
        return _session is not None and not _session._stop.is_set()


def start(minutes: int = DEF_FOCUS, label: str = "", brk: int = DEF_BREAK,
          long_brk: int = DEF_LONG_BREAK, cycles: int = 0) -> str:
    """Arranca un pomodoro. Si ya hay uno corriendo, lo reemplaza."""
    global _session
    minutes = max(1, min(int(minutes or DEF_FOCUS), 180))
    label = (label or "").strip()
    # si no se dio etiqueta, usa el proyecto activo (curso) como contexto
    if not label:
        try:
            import workspace
            label = workspace.active_name() or ""
        except Exception:
            label = ""
    with _lock:
        if _session is not None and not _session._stop.is_set():
            _session.stop()
        _session = _Session(minutes, label, brk, long_brk, cycles)
        _session.start()
    tag = f" para {label}" if label else ""
    plan = f" Haré {cycles} bloques y aviso." if cycles else " Yo te aviso cada fase."
    return (f"Pomodoro arrancado{tag}, Wilmer: {minutes} minutos de enfoque."
            f"{plan} A concentrarse.")


def stop() -> str:
    global _session
    with _lock:
        if _session is None or _session._stop.is_set():
            return "No tienes ningún pomodoro corriendo, Wilmer."
        done = _session.stop()
        label = _session.label
        _session = None
    tag = f" de {label}" if label else ""
    if done:
        return (f"Pomodoro detenido, Wilmer. Alcanzaste {done} bloque(s){tag}. "
                "Algo es algo.")
    return "Pomodoro detenido, Wilmer. Ni un bloque completo, pero tú mandas."


def status() -> str:
    with _lock:
        s = _session
        if s is None or s._stop.is_set():
            return "No hay pomodoro activo, Wilmer. Dime 'pomodoro de 25' y arranco."
        phase, remaining, done = s.status_phase()
        paused = s.paused
        label = s.label
    mm, ss = divmod(max(remaining, 0), 60)
    falta = f"{mm} min" if ss == 0 else f"{mm} min {ss} s"
    fase = "enfoque" if phase == "focus" else "descanso"
    tag = f" de {label}" if label else ""
    extra = " (en pausa)" if paused else ""
    return (f"Vas en {fase}{tag}{extra}, Wilmer. Faltan {falta}. "
            f"Bloques completados: {done}.")


def adjust(kind: str) -> str:
    """Ajuste adaptativo: 'tired' (cansado) | 'hurry' (prisa)."""
    with _lock:
        s = _session
        if s is None or s._stop.is_set():
            return ""
    return s.adjust(kind)


def pause() -> str:
    with _lock:
        s = _session
        if s is None or s._stop.is_set():
            return "No hay pomodoro que pausar, Wilmer."
    return s.pause()


def resume() -> str:
    with _lock:
        s = _session
        if s is None or s._stop.is_set():
            return "No hay pomodoro pausado, Wilmer."
    return s.resume()


def snapshot() -> dict:
    """Estado en vivo para el panel/ui. Cero efectos."""
    with _lock:
        s = _session
        if s is None or s._stop.is_set():
            return {"active": False}
        phase, remaining, done = s.status_phase()
        return {"active": True, "phase": phase, "remaining": remaining,
                "done": done, "label": s.label, "paused": s.paused}
