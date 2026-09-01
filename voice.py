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

# ------------------------------------------------- silenciar mientras escucha
# Wilmer, con Spotify sonando: "le dije pausa la musica pero como esta
# escuchando creo que la musica no permitio que mi instruccion se escuchara".
# Exacto: el microfono oye los altavoces, y la musica entra en la misma senal
# que la voz. Encima el umbral se calibra con el cuarto tal y como suena, asi
# que con musica sube y hace falta gritar por encima de ella.
#
# Se silencia la SALIDA mientras BLUE escucha y se devuelve al soltar. Si ya
# estaba silenciado por Wilmer, no se toca al terminar: reactivarle el sonido
# que el habia quitado seria peor que el problema.
_audio_lo_silencie_yo = False

def _silenciar_salida() -> None:
    global _audio_lo_silencie_yo
    _audio_lo_silencie_yo = False
    try:
        r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                           capture_output=True, text=True, timeout=2)
        if "MUTED" in (r.stdout or "").upper():
            return                       # ya estaba mudo: no es cosa mia
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
                       capture_output=True, timeout=2)
        _audio_lo_silencie_yo = True
    except (OSError, subprocess.SubprocessError):
        pass                             # sin wpctl se escucha igual, solo peor


def _restaurar_salida() -> None:
    global _audio_lo_silencie_yo
    if not _audio_lo_silencie_yo:
        return
    _audio_lo_silencie_yo = False
    try:
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
                       capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass


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

    umbral_a_mano = silence_threshold is not None   # solo las pruebas lo fijan
    auto = silence_threshold is None and cfg_umbral == "auto"
    if silence_threshold is None:
        silence_threshold = 0.012 if auto else float(cfg_umbral)

    q: queue.Queue = queue.Queue()

    def cb(indata, frames, time_, status):
        q.put(indata.copy())

    frames: list[np.ndarray] = []
    nivel: list[float] = []      # el RMS de cada bloque, para el rescate de abajo
    speaking = False
    silent_blocks = 0
    spoken_blocks = 0
    blocks_per_sec = SAMPLE_RATE / BLOCK
    max_blocks = int(max_seconds * blocks_per_sec)
    hang_blocks = int(silence_hang * blocks_per_sec)
    start_blocks = int(start_timeout * blocks_per_sec)
    # Ventana del rescate por umbral hundido (ver abajo). Siete segundos porque
    # nadie habla siete segundos seguidos sin una sola respiracion: si en toda
    # la ventana no ha bajado ni un bloque, no es que Wilmer no calle, es que el
    # umbral esta por debajo del ruido del cuarto.
    rescate_blocks = int(7.0 * blocks_per_sec)

    # Calibrado: los primeros bloques suelen ser el ruido de fondo del cuarto.
    # "Suelen": si Wilmer empieza a hablar de inmediato, esa ventana lleva voz
    # y no sirve. Se detecta y se descarta, porque un umbral sacado de la propia
    # voz queda por encima de ella y el micro se queda sordo.
    # Se mide el cuarto en CADA escucha, no solo con umbral "auto". Un numero
    # fijo en config.toml solo vale mientras el ruido no se mueva, y se mueve:
    # medido el 31/08/2026 con el umbral en 0,02, nueve de cada setenta y ocho
    # bloques de PURO RUIDO ya lo superaban. Con eso el ruido marca "esta
    # hablando" en el primer bloque, y eso apaga el corte por start_timeout —el
    # que existe justo para cuando Wilmer aun no ha abierto la boca—, asi que
    # todo lo que tarde en arrancar se graba. Medido: 13,25 s de grabacion para
    # una frase de unos cinco, y Whisper cobrandolos otra vez al transcribir.
    calibrar = 0 if umbral_a_mano else int(0.8 * blocks_per_sec)
    fondo: list[float] = []

    motivo = "se acabo el tope"     # si nada lo cambia, salio por max_seconds
    _cancelada.clear()      # una cancelacion vieja no puede matar esta escucha

    _silenciar_salida()
    try:
      with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK,
                        dtype="float32", callback=cb):
        for i in range(max_blocks):
            if _cancelada.is_set():
                # Le dio a parar. Se devuelve vacio, y quien llama (handle_voice
                # y la charla continua) ya sabe abortar el turno con eso: no
                # transcribe, no piensa y no contesta.
                return np.zeros(0, dtype=np.float32)
            try:
                block = q.get(timeout=1.0)
            except queue.Empty:
                motivo = "el microfono dejo de dar audio"
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
                    # Por encima del ruido MEDIDO, no del que hubo el dia de la
                    # calibracion. El pico y no la mediana: basta un parpadeo por
                    # encima para reiniciar la cuenta del silencio y que la frase
                    # no termine nunca.
                    medido = max(0.006, min(0.12, pico * 1.3))
                    # En "auto" manda el cuarto. Con un numero en config.toml,
                    # ese numero es un SUELO: se sube si el cuarto suena mas de
                    # lo que se calibro, nunca se baja.
                    silence_threshold = (medido if auto
                                         else max(silence_threshold, medido))
                    # Y lo que el ruido habia marcado como voz durante esta
                    # ventana no era voz: se borra. Si Wilmer estaba hablando de
                    # verdad, el bloque siguiente lo vuelve a marcar. Sin esto,
                    # el latigazo inicial del ruido deja 'speaking' encendido y
                    # start_timeout sigue sin poder cortar.
                    speaking = False
                    spoken_blocks = 0
                    silent_blocks = 0

            nivel.append(rms)

            # RESCATE: el umbral se hundio por debajo del ruido del cuarto.
            #
            # El umbral de config.toml es un numero absoluto, y eso solo vale
            # mientras el ruido no se mueva. Se mueve: el 31/08/2026 estaba
            # calibrado en 0,02 sobre un fondo de 0,007, y bastaron la ganancia
            # del micro subida al 57 % y los ventiladores a tope para dejar el
            # fondo en 0,072. Con eso NINGUN bloque cuenta como silencio, la
            # grabacion no puede cortar nunca y se come los 45 s enteros de
            # escucha_max_s. Medido: 45,19 s de escucha con nadie hablando.
            # Eso era la mitad de los "70 s para un hola" de los que se quejaba.
            #
            # El sintoma es inconfundible y no se puede confundir con alguien
            # hablando mucho: en siete segundos de voz real SIEMPRE hay bloques
            # que bajan —entre frases, al respirar—, mientras que un ruido
            # constante nunca baja de su propio suelo. Asi que si el minimo de
            # la ventana entera sigue por encima del umbral, se sube el umbral
            # al ruido que se esta midiendo de verdad y se sigue escuchando.
            # Se corrige solo y no hace falta recalibrar nada a mano.
            # El disparo NO puede ser "ni un bloque bajo del umbral". Eso solo
            # pilla el ruido perfectamente constante. Con ruido que fluctua —un
            # ventilador que sube y baja, musica de fondo, la calle— basta UN
            # bache aislado en los siete segundos para que min() caiga por
            # debajo y el rescate no dispare nunca; y como tampoco llegan a
            # juntarse 1,8 s seguidos de silencio, la grabacion se come los 45 s
            # enteros. Medido en el log de Wilmer: "grabar 42.3 s, sin audio".
            #
            # Se mira la PROPORCION. Hablando de verdad, entre frase y frase y
            # al respirar, cae por debajo del umbral bastante mas del 15 % de
            # los bloques de una ventana de siete segundos. Si caen menos, lo
            # que hay debajo del umbral es el cuarto, no una pausa.
            if speaking and len(nivel) >= rescate_blocks:
                reciente = nivel[-rescate_blocks:]
                bajos = sum(1 for x in reciente if x <= silence_threshold)
                if bajos < len(reciente) * 0.15:
                    subido = float(np.percentile(reciente, 20)) * 1.25
                    if subido > silence_threshold:
                        silence_threshold = subido

            if rms > silence_threshold:
                speaking = True
                spoken_blocks += 1
                silent_blocks = 0
            else:
                silent_blocks += 1

            if not speaking and i > start_blocks:
                motivo = "nadie hablo"
                break
            if speaking and silent_blocks > hang_blocks:
                motivo = "silencio"        # terminó de hablar
                break

    finally:
        _restaurar_salida()

    # Por que termino, con los numeros. Sin esto, una escucha que se va a los
    # 45 s solo deja "sin audio" y no hay forma de saber si fue el ruido del
    # cuarto, un umbral mal puesto o que el microfono no daba nada.
    if nivel:
        print(f"(escucha: {motivo} tras {len(nivel)/blocks_per_sec:.1f} s | "
              f"umbral final {silence_threshold:.4f} | "
              f"ruido mediano {float(np.median(nivel)):.4f} | "
              f"bloques con voz {spoken_blocks})", flush=True)

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

    _silenciar_salida()
    _ptt_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 blocksize=BLOCK, dtype="float32", callback=cb)
    _ptt_stream.start()

def ptt_stop() -> np.ndarray:
    """Detiene la grabación (al soltar) y devuelve el audio float32 mono 16k."""
    global _ptt_stream, _ptt_frames
    _restaurar_salida()
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
_whisper_size = None      # que tamano hay cargado ahora mismo

def _get_whisper(model_size: str = "small"):
    """El modelo de Whisper, cacheado POR TAMANO.

    Antes la cache era un solo global y se ignoraba `model_size` a partir de la
    primera llamada: quien pidiera "base" despues de que alguien hubiera cargado
    "small" se llevaba "small" sin enterarse. Se veia clarisimo al medirlos —los
    dos tardaban lo mismo y devolvian exactamente el mismo texto, porque eran el
    mismo modelo—, y significa que comparar tamanos era imposible y que cambiar
    `whisper_size` en config.toml podia no surtir efecto."""
    global _whisper, _whisper_size
    if _whisper is None or _whisper_size != model_size:
        import os as _os
        from faster_whisper import WhisperModel
        # Un hilo por NUCLEO FISICO, no por hilo logico. El i7-7700HQ de Wilmer
        # son 4 nucleos con hyperthreading (8 logicos), y medido sobre la misma
        # frase de 3 s: por defecto 3,27 s, con 4 hilos 2,69 s, con 8 3,22 s y
        # con 12 3,41 s. Pasado el numero de nucleos reales, los hilos se pelean
        # por la misma ALU y transcribir va A PEOR. Mismo texto en los cuatro
        # casos: son 0,6 s gratis en cada turno, sin tocar la precision.
        try:
            import config as _cfg
            hilos = int(_cfg.load().get("whisper_hilos", 0))
        except Exception:
            hilos = 0
        if hilos <= 0:
            hilos = max(1, (_os.cpu_count() or 4) // 2)
        # int8 = rapido y ligero en CPU
        _whisper = WhisperModel(model_size, device="cpu", compute_type="int8",
                                cpu_threads=hilos)
        _whisper_size = model_size
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
# _callada solo impedia HABLAR. Si Wilmer le daba a parar mientras BLUE
# ESCUCHABA, no pasaba nada: record_until_silence seguia grabando hasta agotar
# los 45 s del tope, la interfaz ya decia "Listo" (mentira, el micro seguia
# abierto), y al terminar transcribia y pensaba un turno que luego no se decia
# —porque _callada seguia puesto—. Los tres sintomas eran esto. _cancelada
# corta la grabacion de verdad.
_cancelada = threading.Event()
_turno = 0
_turno_lock = threading.Lock()


def nuevo_turno() -> int:
    """Abre un turno nuevo. Levanta el silencio y deja obsoleto lo que quedara
    por decir del turno anterior."""
    global _turno
    with _turno_lock:
        _turno += 1
        _callada.clear()
        _cancelada.clear()
        import store
        store.limpiar_aborto()
        return _turno


def interrumpir():
    """Wilmer ha pedido parar: aborta el turno ENTERO.

    A diferencia de stop_speaking(), esto se recuerda: lo que venga detrás
    tampoco se dice, hasta el turno siguiente. Y corta la grabación en curso,
    que es lo que faltaba: parar mientras escuchaba no paraba nada."""
    _callada.set()
    _cancelada.set()
    import store
    store.abortar()          # que brain.py deje de pensar en la ronda siguiente
    stop_speaking()


def escucha_cancelada() -> bool:
    return _cancelada.is_set()


def silenciada() -> bool:
    return _callada.is_set()

_FIN = object()          # centinela: no quedan más frases por sintetizar

# Cuando empezo el speak() actual, para medir el silencio previo a la voz.
#
# `hablar` en el log mide la locucion ENTERA, o sea que incluye el audio
# sonando: una respuesta de 76 tokens da "hablar 20.8 s" y eso no es espera, es
# que esta hablando. Lo que Wilmer nota como "tarda en empezar a hablar" es otra
# cosa —el hueco entre que deja de oirse a si mismo y suena la primera silaba—
# y no se estaba midiendo en ningun sitio.
_t_habla = None


def _marcar_primer_audio() -> None:
    """Lo llama quien arranca la reproduccion, la primera vez de cada turno."""
    global _t_habla
    if _t_habla is None:
        return
    import time as _t
    print(f"(primera palabra a los {_t.time() - _t_habla:.1f} s de decidir hablar)",
          flush=True)
    _t_habla = None


def _primer_bocado(frase: str, minimo: int = 25, maximo: int = 70) -> list:
    """Parte UNA frase larga en (principio, resto) por una junta natural.

    Solo se corta en coma, punto y coma o conjuncion: cortar a mitad de sintagma
    se oye raro, y aqui lo que se gana no compensa. Si no hay junta en el tramo
    util, se devuelve la frase entera y no se gana nada, que es lo correcto."""
    import re
    for m in re.finditer(r",\s+|;\s+|\s+(?:y|pero|aunque|porque|mientras)\s+",
                         frase):
        corte = m.end()
        if minimo <= corte <= maximo:
            return [frase[:corte].strip(), frase[corte:].strip()]
    return [frase]


def _partir_en_frases(texto: str, primera: int = 25, resto: int = 110) -> list:
    """Trocea la respuesta en bocados que se puedan sintetizar por separado.

    El primero se hace CORTO a propósito: es el que decide cuánto tarda BLUE en
    abrir la boca. Los siguientes se juntan más largos, porque Kokoro entona
    mejor con una frase entera delante y para entonces ya hay audio sonando que
    tapa la síntesis.

    Medido el 01/09/2026: Kokoro sintetiza a unas 2,2 veces el tiempo real, o
    sea que la espera antes de la primera silaba es proporcional a lo que se le
    manda de golpe. Una frase de 50 caracteres son 2,0 s de silencio. Y como
    esto solo cortaba en PUNTOS, una respuesta de una sola frase —que es la
    mayoria de las de BLUE— no se troceaba nunca: se sintetizaba entera y luego
    sonaba. Por eso `primera` baja de 45 a 25 y por eso una frase larga suelta
    se parte por su primera coma."""
    import re
    piezas = re.split(r"(?<=[.!?…:])\s+|\n+", texto)
    piezas = [p.strip() for p in piezas if p.strip()]
    if not piezas:
        return []
    if len(piezas) == 1 and len(piezas[0]) > 60:
        piezas = _primer_bocado(piezas[0])
    bloques, actual = [], ""
    for p in piezas:
        minimo = primera if not bloques else resto
        actual = f"{actual} {p}".strip() if actual else p
        if len(actual) >= minimo:
            bloques.append(actual)
            actual = ""
    if actual:
        # Una cola muy corta suena cortada: se pega al bloque anterior.
        if bloques and len(actual) < 25:
            bloques[-1] += " " + actual
        else:
            bloques.append(actual)
    return bloques


def _hablar_por_frases(text: str, voz: str, mi_turno: int) -> bool:
    """Habla mientras sintetiza, en vez de sintetizar y luego hablar.

    Kokoro devuelve UN solo trozo por llamada, dé igual lo larga que sea la
    frase: medido, una respuesta explicativa son 6,35 s de silencio antes de
    que suene nada, y luego 20,6 s de audio. Pero sintetiza como tres veces más
    rápido de lo que se escucha, así que troceando por frases se puede empezar
    a hablar tras la primera (~0,6 s) y sintetizar el resto mientras suena, sin
    que la reproducción se quede nunca sin material.

    De regalo, interrumpir se vuelve fino: entre frase y frase se mira si Wilmer
    mandó callar, así que el ⏹ corta en menos de una frase en vez de esperar a
    que acabe el audio entero."""
    global _play_proc
    bloques = _partir_en_frases(text)
    if len(bloques) < 2:
        return False                      # una sola frase: no hay nada que ganar

    cola: queue.Queue = queue.Queue(maxsize=2)

    def productor():
        for b in bloques:
            if _callada.is_set() or mi_turno != _turno:
                break
            ruta = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    ruta = tmp.name
                if not _synth_kokoro(b, voz, ruta):
                    raise RuntimeError("kokoro no devolvio audio")
            except Exception:
                if ruta:
                    try:
                        os.unlink(ruta)
                    except OSError:
                        pass
                ruta = None
            cola.put(ruta)
        cola.put(_FIN)

    hilo = threading.Thread(target=productor, daemon=True)
    hilo.start()
    sono = False
    try:
        while True:
            item = cola.get()
            if item is _FIN:
                break
            if item is None:
                continue                  # esa frase no se pudo sintetizar
            try:
                if _callada.is_set() or mi_turno != _turno:
                    continue              # se sigue vaciando la cola para limpiar
                _marcar_primer_audio()
                _play_proc = subprocess.Popen(["paplay", item])
                _play_proc.wait()
                sono = True
            except Exception:
                pass
            finally:
                _play_proc = None
                try:
                    os.unlink(item)
                except OSError:
                    pass
    finally:
        _callada_ya = _callada.is_set() or mi_turno != _turno
        if _callada_ya:
            # que el productor no se quede colgado en un put() con la cola llena
            while True:
                try:
                    it = cola.get_nowait()
                except queue.Empty:
                    break
                if it not in (None, _FIN):
                    try:
                        os.unlink(it)
                    except OSError:
                        pass
        hilo.join(timeout=1.0)
    return sono or _callada.is_set() or mi_turno != _turno


def speak(text: str, voice: str = "ef_dora", engine: str = "kokoro"):
    """Habla 'text'. engine='kokoro' (cálida local) | 'edge' (neural online) | 'piper' (ligero local).
    'voice' es el id correspondiente al motor (ef_dora, es-MX-DaliaNeural, etc)."""
    global _play_proc, _t_habla
    import time as _t
    _t_habla = _t.time()        # arranca la cuenta hasta la primera palabra

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
            # Primero por frases: empieza a sonar a los ~0,6 s en vez de esperar
            # a tener la respuesta entera sintetizada. Si no aplica (una sola
            # frase) o falla, se cae al camino de siempre.
            try:
                if _hablar_por_frases(text, voice, mi_turno):
                    return
            except Exception:
                pass
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
                _marcar_primer_audio()
                _play_proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path])
            elif shutil.which("mpv"):
                _marcar_primer_audio()
                _play_proc = subprocess.Popen(
                    ["mpv", "--really-quiet", "--no-video", audio_path])
            else:
                # convertir mp3 → wav con ffmpeg si está disponible
                if shutil.which("ffmpeg"):
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                                    "-i", audio_path, wav_path], check=False)
                    _marcar_primer_audio()
                    _play_proc = subprocess.Popen(["paplay", wav_path])
                else:
                    _marcar_primer_audio()
                    _play_proc = subprocess.Popen(["paplay", audio_path])
        else:
            _marcar_primer_audio()
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
