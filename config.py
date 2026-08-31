"""Carga la configuracion desde ~/.config/blue/config.toml"""
from __future__ import annotations
import tomllib
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "blue" / "config.toml"

DEFAULTS = {
    # proveedor del cerebro: groq | openrouter | mistral | gemini
    "provider": "groq",
    "api_key": "",
    "model": "llama-3.3-70b-versatile",
    # voz: motor 'kokoro' (cálida, neural local) | 'edge' (Microsoft Neural, online) | 'piper' (ligera)
    "tts": "kokoro",
    "kokoro_voice": "ef_dora",                # ef_dora | em_alex | em_santa
    "edge_voice": "es-MX-DaliaNeural",        # voz Edge-TTS (online)
    "voice": "es_MX-claude-high.onnx",        # voz piper (si tts='piper')
    "whisper_size": "small",
    "assistant_name": "Blue",
    # --- palabra de activación "Hey Blue" (Porcupine, opcional) ---
    "wake_enabled": True,                # si hay llave+modelo, escucha siempre
    "porcupine_access_key": "",          # AccessKey de console.picovoice.ai
    "porcupine_keyword": "",             # ruta al .ppn de "Hey Blue" (Linux)
    "porcupine_sensitivity": 0.6,        # 0-1: más alto = despierta más fácil
    "wake_energy": 0.02,                 # umbral de voz del detector Whisper
    # --- escuchar ---
    # Cuánto silencio significa "ya terminé". Por debajo de 1.5 s corta a quien
    # se para a pensar a mitad de una pregunta larga.
    "escucha_silencio_s": 1.8,
    # Tope duro de una intervención. Estaba en 12 s, y cortaba las preguntas
    # complejas por reloj aunque no hubiera ni una pausa.
    "escucha_max_s": 45.0,
    # Umbral de voz. "auto" lo calcula del ruido de fondo de tu cuarto; un
    # número fijo (p.ej. 0.012) lo deja clavado.
    "escucha_umbral": "auto",
    # --- el escalafón de motores (cerebros.py) ---
    # Dónde vive el Ollama de la otra PC: de ahí salen ORFEO (jarvis-heavy)
    # e ÍCARO (Hermes apuntando al mismo sitio).
    # Si no contesta, BLUE barre la red local buscando quien escuche en
    # el 11434 y se lo queda. Ponlo por NOMBRE (.local) si lo sabes.
    "ollama_host": "http://localhost:11434",
    # --- conversación continua ---
    "converse_turns": 6,                 # turnos seguidos antes de volver a dormir
    "converse_timeout": 7.0,             # seg. esperando que sigas hablando
}

def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            cfg.update(tomllib.load(f))
    return cfg
