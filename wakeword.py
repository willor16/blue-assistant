"""Palabra de activación "Hey Blue".

Dos motores:
  - WakeWord       -> Porcupine (preciso, necesita llave + .ppn). Opcional.
  - WhisperWake    -> casero: reusa Whisper para detectar "blue" en ráfagas
                      cortas de voz. Sin cuentas ni RAM extra.

Ambos escuchan en un hilo aparte y, al detectar, cierran su stream y llaman a
`on_wake()` (la conversación) con el micrófono libre, así nunca hay dos
lectores del micro a la vez.
"""
from __future__ import annotations
import threading
import unicodedata

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK = 1024


def _norm(text: str) -> str:
    """minúsculas y sin acentos, para comparar palabras."""
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


class WhisperWake:
    """Detector de palabra casero con Whisper. Escucha ráfagas cortas de voz y,
    si la transcripción contiene la palabra clave (p.ej. 'blue'), despierta."""

    def __init__(self, transcribe_fn, on_wake,
                 words=("blue", "blu", "blus", "blues", "blew", "bloo",
                        "azul", "blou", "blu"),
                 energy_threshold: float = 0.02,
                 max_utter: float = 2.5):
        self.transcribe = transcribe_fn
        self.on_wake = on_wake
        self.words = tuple(_norm(w) for w in words)
        self.energy = energy_threshold
        self.max_blocks = int(max_utter * SAMPLE_RATE / BLOCK)
        self.hang_blocks = int(0.5 * SAMPLE_RATE / BLOCK)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _matches(self, text: str) -> bool:
        toks = _norm(text).replace(",", " ").replace(".", " ").split()
        return any(tok in self.words for tok in toks)

    def _listen_until_wake(self) -> bool:
        """Escucha hasta cazar una ráfaga corta cuya transcripción tenga la
        palabra. Devuelve True al despertar; False si se pidió parar."""
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK,
                            dtype="float32") as stream:
            buf: list[np.ndarray] = []
            collecting = False
            silent = 0
            while not self._stop.is_set():
                block, _ = stream.read(BLOCK)
                block = block.reshape(-1)
                rms = float(np.sqrt(np.mean(block ** 2)))
                if rms > self.energy:
                    collecting = True
                    buf.append(block)
                    silent = 0
                elif collecting:
                    buf.append(block)
                    silent += 1
                fin = collecting and (silent > self.hang_blocks
                                      or len(buf) > self.max_blocks)
                if fin:
                    audio = np.concatenate(buf).astype(np.float32)
                    buf, collecting, silent = [], False, 0
                    try:
                        text = self.transcribe(audio)
                    except Exception:
                        text = ""
                    if text and self._matches(text):
                        return True
        return False

    def _run(self):
        while not self._stop.is_set():
            try:
                if self._listen_until_wake():
                    try:
                        self.on_wake()
                    except Exception as e:
                        print(f"(wake) error en conversación: {e}")
            except Exception as e:
                print(f"(wake) error de micrófono: {e}")
                self._stop.wait(1.0)


class WakeWord:
    def __init__(self, access_key: str, keyword_path: str, on_wake,
                 sensitivity: float = 0.6):
        import pvporcupine
        self._pv = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[keyword_path],
            sensitivities=[float(sensitivity)],
        )
        self.on_wake = on_wake
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -- escucha hasta detectar la palabra; True si despertó, False si paró --
    def _listen_until_wake(self) -> bool:
        fl = self._pv.frame_length
        with sd.RawInputStream(samplerate=self._pv.sample_rate, channels=1,
                               dtype="int16", blocksize=fl) as stream:
            while not self._stop.is_set():
                data, overflowed = stream.read(fl)
                pcm = np.frombuffer(data, dtype=np.int16)
                if pcm.shape[0] != fl:
                    continue
                if self._pv.process(pcm) >= 0:
                    return True
        return False

    def _run(self):
        while not self._stop.is_set():
            try:
                if self._listen_until_wake():
                    try:
                        self.on_wake()
                    except Exception as e:
                        print(f"(wake) error en conversación: {e}")
            except Exception as e:
                # error de audio puntual: pausa breve y reintenta
                print(f"(wake) error de micrófono: {e}")
                self._stop.wait(1.0)
        try:
            self._pv.delete()
        except Exception:
            pass
