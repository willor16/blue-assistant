"""Voz local: grabacion (sounddevice) + STT (faster-whisper) + TTS (piper).

Todo corre en local. El modelo de Whisper se descarga la primera vez.
"""
from __future__ import annotations
import io
import os
import queue
import subprocess
import sys
import threading
import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000          # whisper espera 16k mono
BLOCK = 1024
CONFIG_DIR = Path.home() / ".config" / "blue"
VOICES_DIR = CONFIG_DIR / "voices"

# ---------------------------------------------------------------- grabacion
def _ajustes_escucha():
    """Los tres números de escuchar, desde config.toml."""
    try:
        import config
        c = config.load()
    except Exception:
        c = {}
    return (float(c.get("escucha_max_s", 45.0)),
            float(c.get("escucha_silencio_s", 1.8)),
            c.get("escucha_umbral", "auto"))


def record_until_silence(max_seconds: float | None = None,
                         silence_threshold: float | None = None,
                         silence_hang: float | None = None,
                         start_timeout: float = 4.0) -> np.ndarray:
    """Graba del micrófono hasta que Wilmer termine de hablar de verdad.

    Los valores por defecto vienen de config.toml. Antes estaban clavados en el
    código y cortaban a media pregunta: el tope era de 12 segundos —por reloj,
    aunque no hubiera ni una pausa— y bastaban 1.1 s de silencio para dar la
    frase por terminada, que es justo lo que tarda uno en pensar a mitad de una
    pregunta larga.

    El umbral de voz, si está en "auto", se saca del ruido de fondo del cuarto
    en vez de ser un número fijo: un micro apagado y una habitación con el
    ventilador puesto no tienen el mismo silencio.

    Devuelve audio float32 mono a 16 kHz.
    """
    cfg_max, cfg_hang, cfg_umbral = _ajustes_escucha()
    max_seconds = cfg_max if max_seconds is None else max_seconds
    silence_hang = cfg_hang if silence_hang is None else silence_hang

    auto = silence_threshold is None and cfg_umbral == "auto"
    if silence_threshold is None:
        silence_threshold = 0.012 if auto else float(cfg_umbral)

    q: queue.Queue = queue.Queue()

    def cb(indata, frames, time_, status):
        q.put(indata.copy())

    frames: list[np.ndarray] = []
    speaking = False
    silent_blocks = 0
    spoken_blocks = 0
    blocks_per_sec = SAMPLE_RATE / BLOCK
    max_blocks = int(max_seconds * blocks_per_sec)
    hang_blocks = int(silence_hang * blocks_per_sec)
    start_blocks = int(start_timeout * blocks_per_sec)

    # Calibrado: los primeros bloques suelen ser el ruido de fondo del cuarto.
    # "Suelen": si Wilmer empieza a hablar de inmediato, esa ventana lleva voz
    # y no sirve. Se detecta y se descarta, porque un umbral sacado de la propia
    # voz queda por encima de ella y el micro se queda sordo.
    calibrar = int(0.4 * blocks_per_sec) if auto else 0
    fondo: list[float] = []

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK,
                        dtype="float32", callback=cb):
        for i in range(max_blocks):
            try:
                block = q.get(timeout=1.0)
            except queue.Empty:
                break
            frames.append(block)
            rms = float(np.sqrt(np.mean(block ** 2)))

            # Durante el calibrado se sigue escuchando con el umbral por
            # defecto: si habla desde el primer segundo, no se pierde nada.
            if calibrar and i < calibrar:
                fondo.append(rms)
            elif calibrar and i == calibrar and fondo:
                calibrar = 0
                suelo = float(np.percentile(fondo, 10))
                pico = max(fondo)
                if pico > suelo * 5.0:
                    pass          # esa ventana llevaba voz: no me fío, dejo el fijo
                else:
                    silence_threshold = max(0.006, min(0.05, suelo * 3.0))

            if rms > silence_threshold:
                speaking = True
                spoken_blocks += 1
                silent_blocks = 0
            else:
                silent_blocks += 1

            if not speaking and i > start_blocks:
                break                      # nunca habló
            if speaking and silent_blocks > hang_blocks:
                break                      # terminó de hablar

    if not frames or spoken_blocks < 3:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(frames).flatten()


# ------------------------------------------------- push-to-talk (mantener tecla)
_ptt_stream = None
_ptt_frames: list = []

def ptt_start():
    """Empieza a grabar (al presionar Super+J). No bloquea."""
    global _ptt_stream, _ptt_frames
    if _ptt_stream is not None:
        return
    _ptt_frames = []

    def cb(indata, frames, time_, status):
        _ptt_frames.append(indata.copy())

    _ptt_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 blocksize=BLOCK, dtype="float32", callback=cb)
    _ptt_stream.start()

def ptt_stop() -> np.ndarray:
    """Detiene la grabación (al soltar) y devuelve el audio float32 mono 16k."""
    global _ptt_stream, _ptt_frames
    if _ptt_stream is not None:
        try:
            _ptt_stream.stop()
            _ptt_stream.close()
        except Exception:
            pass
        _ptt_stream = None
    if not _ptt_frames:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(_ptt_frames).flatten()
    _ptt_frames = []
    return audio


# ------------------------------------------------------------------- STT
_whisper = None

def _get_whisper(model_size: str = "small"):
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        # int8 = rapido y ligero en CPU
        _whisper = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _whisper

def transcribe(audio: np.ndarray, model_size: str = "small") -> str:
    if audio.size == 0:
        return ""
    model = _get_whisper(model_size)
    segments, _ = model.transcribe(audio, language="es", beam_size=1,
                                   vad_filter=True)
    return "".join(s.text for s in segments).strip()


# ------------------------------------------------------------------- TTS
# Dos motores: 'kokoro' (neural, cálido) y 'piper' (ligero). Se elige por config.
_voice = None
_voice_name = None
_kokoro = None           # pipeline de Kokoro (pesado, se carga una vez)

def _get_voice(voice_file: str):
    global _voice, _voice_name
    if _voice is None or _voice_name != voice_file:
        from piper import PiperVoice
        path = VOICES_DIR / voice_file
        _voice = PiperVoice.load(str(path), str(path) + ".json"
                                 if not str(path).endswith(".onnx")
                                 else str(path).replace(".onnx", ".onnx.json"))
        _voice_name = voice_file
    return _voice

def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro import KPipeline
        _kokoro = KPipeline(lang_code="e")   # 'e' = español
    return _kokoro

def _synth_kokoro(text: str, voice: str, wav_path: str):
    """Sintetiza con Kokoro y escribe un wav a 24kHz."""
    import numpy as np
    import soundfile as sf
    pipe = _get_kokoro()
    chunks = []
    for _gs, _ps, audio in pipe(text, voice=voice, speed=1.0):
        arr = audio if isinstance(audio, np.ndarray) else audio.detach().cpu().numpy()
        chunks.append(arr)
    if not chunks:
        return False
    sf.write(wav_path, np.concatenate(chunks), 24000)
    return True

def _synth_piper(text: str, voice_file: str, wav_path: str):
    voice = _get_voice(voice_file)
    with wave.open(wav_path, "wb") as wf:
        voice.synthesize_wav(text, wf)
    return True

def _synth_edge(text: str, voice: str, wav_path: str):
    """Sintetiza con Microsoft Edge TTS (online, gratis, voces neurales).
    Descarga mp3 y lo deja en wav_path con extensión .mp3 — paplay lo reproduce
    igual, pero renombramos para claridad."""
    import asyncio
    import edge_tts
    mp3_path = wav_path[:-4] + ".mp3" if wav_path.endswith(".wav") else wav_path + ".mp3"
    async def _go():
        com = edge_tts.Communicate(text, voice)
        await com.save(mp3_path)
    asyncio.run(_go())
    # devuelve la ruta real (mp3); el caller la usa para reproducir
    return mp3_path


# --- Catálogo de voces ------------------------------------------------------
# Etiquetas legibles para el panel web. Si añades más, agrégalas aquí.
VOICE_CATALOG = {
    "kokoro": {
        "ef_dora":  "Dora — femenina, cálida (ES)",
        "em_alex":  "Alex — masculina, neutra (ES)",
        "em_santa": "Santa — masculina, grave (ES)",
    },
    "edge": {
        # México
        "es-MX-DaliaNeural":   "Dalia — femenina, joven (México)",
        "es-MX-JorgeNeural":   "Jorge — masculino, claro (México)",
        "es-MX-CecilioNeural": "Cecilio — masculino, locutor (México)",
        "es-MX-RenataNeural":  "Renata — femenina, conversacional (México)",
        # Colombia
        "es-CO-SalomeNeural":  "Salomé — femenina (Colombia)",
        "es-CO-GonzaloNeural": "Gonzalo — masculino (Colombia)",
        # Chile
        "es-CL-CatalinaNeural": "Catalina — femenina (Chile)",
        "es-CL-LorenzoNeural":  "Lorenzo — masculino (Chile)",
        # Perú
        "es-PE-CamilaNeural":  "Camila — femenina (Perú)",
        "es-PE-AlexNeural":    "Alex — masculino (Perú)",
        # Argentina
        "es-AR-ElenaNeural":   "Elena — femenina (Argentina)",
        "es-AR-TomasNeural":   "Tomás — masculino (Argentina)",
    },
}


_play_proc = None        # proceso paplay/ffplay actual (para poder interrumpirlo)

# Interrumpir tenía un agujero de carrera: speak() sintetiza el audio ENTERO
# antes de crear el proceso que suena, y con Kokoro eso son segundos. Si Wilmer
# le daba a parar durante ese rato, stop_speaking() no encontraba proceso que
# matar, no pasaba nada, y BLUE se ponía a hablar acto seguido. Faltaba que la
# orden de callar se RECORDARA. Eso es _callada: se pone al interrumpir y solo
# la limpia el turno siguiente.
_callada = threading.Event()
_turno = 0
_turno_lock = threading.Lock()


def nuevo_turno() -> int:
    """Abre un turno nuevo. Levanta el silencio y deja obsoleto lo que quedara
    por decir del turno anterior."""
    global _turno
    with _turno_lock:
        _turno += 1
        _callada.clear()
        return _turno


def interrumpir():
    """Wilmer ha pedido callar. A diferencia de stop_speaking(), esto se
    recuerda: lo que venga detrás tampoco se dice, hasta el turno siguiente."""
    _callada.set()
    stop_speaking()


def silenciada() -> bool:
    return _callada.is_set()

def speak(text: str, voice: str = "ef_dora", engine: str = "kokoro"):
    """Habla 'text'. engine='kokoro' (cálida local) | 'edge' (neural online) | 'piper' (ligero local).
    'voice' es el id correspondiente al motor (ef_dora, es-MX-DaliaNeural, etc)."""
    global _play_proc

    # Lo que se dice no es lo que se escribe.
    # 1) estilo: las viñetas se vuelven prosa y se caen los tics de cierre
    #    ("en resumen", "¿en qué puedo ayudarte?"). Solo aquí: en el panel la
    #    lista y la tabla se quedan, que ahí sí se leen bien.
    # 2) texto: fuera emojis (el sintetizador los lee con su nombre entero),
    #    comillas ("comillas cama comillas") y las URLs y rutas deletreadas.
    import estilo as _estilo
    import texto as _texto
    text = _texto.para_voz(_estilo.hablado(text))

    if not text.strip():
        return
    if _callada.is_set():            # le dio a parar: ni se sintetiza
        return
    with _turno_lock:
        mi_turno = _turno
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    audio_path = wav_path
    try:
        if engine == "kokoro":
            try:
                ok = _synth_kokoro(text, voice, wav_path)
            except Exception:
                ok = _synth_piper(text, "es_MX-claude-high.onnx", wav_path)
        elif engine == "edge":
            try:
                audio_path = _synth_edge(text, voice, wav_path)
                ok = True
            except Exception:
                # si edge falla (sin internet, etc), cae a kokoro
                try:
                    ok = _synth_kokoro(text, "ef_dora", wav_path)
                    audio_path = wav_path
                except Exception:
                    ok = _synth_piper(text, "es_MX-claude-high.onnx", wav_path)
                    audio_path = wav_path
        else:
            ok = _synth_piper(text, voice, wav_path)
        if not ok:
            return
        # Sintetizar tarda. Entre que empezó y ahora, Wilmer ha podido pedir
        # callar o empezar otra pregunta: en ambos casos esto ya no se dice.
        if _callada.is_set() or mi_turno != _turno:
            return
        # paplay maneja wav; para mp3 (edge) usamos ffplay si está, si no mpv, si no paplay con conversión
        if audio_path.endswith(".mp3"):
            import shutil
            if shutil.which("ffplay"):
                _play_proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path])
            elif shutil.which("mpv"):
                _play_proc = subprocess.Popen(
                    ["mpv", "--really-quiet", "--no-video", audio_path])
            else:
                # convertir mp3 → wav con ffmpeg si está disponible
                if shutil.which("ffmpeg"):
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                                    "-i", audio_path, wav_path], check=False)
                    _play_proc = subprocess.Popen(["paplay", wav_path])
                else:
                    _play_proc = subprocess.Popen(["paplay", audio_path])
        else:
            _play_proc = subprocess.Popen(["paplay", audio_path])
        _play_proc.wait()
    except Exception:
        pass
    finally:
        _play_proc = None
        for p in (wav_path, audio_path):
            try:
                os.unlink(p)
            except OSError:
                pass

def stop_speaking():
    """Corta la voz que esté sonando ahora mismo."""
    global _play_proc
    p = _play_proc
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    # por si acaso quedó algún paplay huérfano
    subprocess.run(["pkill", "-x", "paplay"], check=False)


# ----------------------------------------------------------------- pruebas
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "say":
        speak(" ".join(sys.argv[2:]) or "Hola, soy tu asistente.")
    elif len(sys.argv) > 1 and sys.argv[1] == "listen":
        print("Habla ahora...")
        audio = record_until_silence()
        print(f"Audio capturado: {audio.size/SAMPLE_RATE:.1f}s")
        txt = transcribe(audio)
        print("Entendi:", repr(txt))
        if txt:
            speak(f"Entendi: {txt}")
    else:
        print("uso: voice.py say <texto> | voice.py listen")
