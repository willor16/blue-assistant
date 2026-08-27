"""
avisos.py — Dar señales de vida en voz cuando algo tarda.

El problema que resuelve: BLUE se quedaba muda mientras trabajaba, y Wilmer no
sabía si estaba pensando o se había colgado.

Lo que había antes para las tareas pesadas era peor que el silencio:

    while th.is_alive():
        th.join(timeout=0.2)
        if th.is_alive():
            voice.speak(lines.search_filler(), v, eng)

Como `speak()` bloquea hasta que acaba el audio, eso soltaba frases de relleno
una detrás de otra, sin pausa, durante toda la tarea. Una ametralladora.

Aquí los avisos van **espaciados y en escala**: uno pronto para decir "esto
tarda", otro al rato para decir "sigo", y a partir de ahí un latido de vez en
cuando. Cuando llega la respuesta, el avisador se calla y, si estaba hablando,
se le corta: manda la respuesta.
"""

import random
import threading

# (segundos, frases). Después del último umbral, un latido cada LATIDO.
ESCALA_NORMAL = [
    (9, ["Dame un momento, que esto lleva su rato.",
         "Espera, Wilmer, que esto no es inmediato.",
         "Un segundo, que le estoy dando vueltas."]),
    (28, ["Sigo en ello, no me he colgado.",
          "Aguanta, que voy a mitad de camino.",
          "Sigo aquí, esto va más lento de lo normal."]),
    (70, ["Esto va para largo. Sigue a lo tuyo, que yo te aviso.",
          "Va a tardar de verdad, Wilmer. Te aviso al terminar."]),
]

ESCALA_TAREA = [
    (15, ["Manos a la obra, esto lleva un rato. Te aviso al terminar.",
          "Voy a tardar unos minutos con esto, Wilmer."]),
    (75, ["Sigo trabajando, todo en orden.",
          "Aún en ello, no he terminado."]),
    (200, ["Esto va largo de verdad, pero sigue avanzando.",
           "Sigo dentro. No me he quedado atascado."]),
]

LATIDO = 75          # segundos entre latidos, pasado el último umbral
PASO = 0.25          # cada cuánto se mira el reloj


class Avisador:
    """
    Habla cada cierto tiempo mientras algo tarda. Se usa como contexto:

        with Avisador(hablar) as a:
            resultado = algo_que_tarda()

    Al salir se calla solo. `hablar(frase)` es lo que sintetiza (bloqueante,
    no pasa nada: corre en su propio hilo).
    """

    def __init__(self, hablar, escala=None, latido=LATIDO, cortar=None):
        self.hablar = hablar
        self.escala = sorted(escala or ESCALA_NORMAL)
        self.latido = latido
        # Función para cortar el audio si aún suena cuando llega la respuesta.
        self.cortar = cortar
        self._parar = threading.Event()
        self._hilo = None
        self._hablando = False
        self._dijo_te_aviso = False

    # -- contexto ------------------------------------------------------
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()
        return False

    # -- control -------------------------------------------------------
    def start(self):
        if self._hilo is not None:
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def stop(self):
        """Calla el avisador. Si estaba hablando, se le corta: manda la respuesta."""
        self._parar.set()
        if self._hablando and self.cortar:
            try:
                self.cortar()
            except Exception:
                pass
        if self._hilo is not None:
            self._hilo.join(timeout=2)
            self._hilo = None

    @property
    def prometio_avisar(self) -> bool:
        """True si llegó a decir 'te aviso al terminar'. Entonces hay que
        cumplirlo: la respuesta se abre con un remate."""
        return self._dijo_te_aviso

    # -- interior ------------------------------------------------------
    def _decir(self, frases):
        self._hablando = True
        try:
            self.hablar(random.choice(frases))
        except Exception:
            pass
        finally:
            self._hablando = False

    def _bucle(self):
        transcurrido = 0.0
        pendientes = list(self.escala)
        siguiente_latido = (self.escala[-1][0] + self.latido) if self.escala else None

        while not self._parar.is_set():
            if self._parar.wait(PASO):
                return
            transcurrido += PASO

            if pendientes and transcurrido >= pendientes[0][0]:
                _, frases = pendientes.pop(0)
                if not pendientes:                 # el último es el "te aviso"
                    self._dijo_te_aviso = True
                self._decir(frases)
                continue

            if not pendientes and siguiente_latido and transcurrido >= siguiente_latido:
                siguiente_latido = transcurrido + self.latido
                self._decir(["Sigo aquí.", "Sigo trabajando.", "Aún en ello."])


def remate(prometio: bool) -> str:
    """Si dijo que avisaría, la respuesta se abre cumpliéndolo."""
    if not prometio:
        return ""
    return random.choice(["Ya está. ", "Listo, ya lo tengo. ", "Terminé. "])
