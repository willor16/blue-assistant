"""Cap 3 — Ver la pantalla.

Blue captura la pantalla con `grim` (Wayland/Hyprland) y se la manda a Gemini
multimodal en una llamada one-shot aparte. Devuelve TEXTO, así que encaja con el
patrón normal de herramientas del cerebro (el proveedor principal puede ser groq
solo-texto sin problema).

Pensado para lo que estudia/trabaja Wilmer: leer diagramas (Mollier, p-h),
gráficos, datasheets, tablas, código o errores que tenga en el monitor.
"""
from __future__ import annotations
import base64
import json
import os
import subprocess
import tempfile
import time

import config

# modelo de visión por defecto si el chain no trae uno de gemini
_VISION_MODEL_FALLBACK = "gemini-2.5-flash"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

# no re-capturar más de una vez por segundo si llaman seguido
_last_shot = {"path": "", "ts": 0.0}


def _gemini_creds() -> tuple[str, str]:
    """Saca (api_key, model) del backend gemini del chain de config."""
    c = config.load()
    for b in (c.get("brain") or []):
        if b.get("provider") == "gemini" and b.get("api_key"):
            model = b.get("model") or _VISION_MODEL_FALLBACK
            # los modelos -lite ven imágenes, pero el flash normal lee mejor
            # diagramas/tablas densas; subimos si está en lite
            if "lite" in model:
                model = _VISION_MODEL_FALLBACK
            return b["api_key"], model
    # último recurso: clave de nivel superior si fuese gemini
    if c.get("provider") == "gemini" and c.get("api_key"):
        return c["api_key"], c.get("model") or _VISION_MODEL_FALLBACK
    return "", _VISION_MODEL_FALLBACK


def available() -> bool:
    """True si hay con qué capturar (grim) y a quién preguntarle (gemini)."""
    from shutil import which
    key, _ = _gemini_creds()
    return bool(which("grim")) and bool(key)


def _focused_monitor() -> str | None:
    """Nombre del monitor enfocado en Hyprland, o None para capturar todo."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"],
                             capture_output=True, text=True, timeout=3)
        for m in json.loads(out.stdout or "[]"):
            if m.get("focused"):
                return m.get("name")
    except Exception:
        pass
    return None


def capture() -> str | None:
    """Captura el monitor enfocado a un PNG temporal. Devuelve la ruta o None."""
    now = time.time()
    if _last_shot["path"] and now - _last_shot["ts"] < 1.0 \
            and os.path.exists(_last_shot["path"]):
        return _last_shot["path"]
    from shutil import which
    if not which("grim"):
        return None
    path = os.path.join(tempfile.gettempdir(), "blue_screen.png")
    cmd = ["grim"]
    mon = _focused_monitor()
    if mon:
        cmd += ["-o", mon]
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except Exception:
        return None
    if r.returncode != 0 or not os.path.exists(path):
        return None
    _last_shot["path"], _last_shot["ts"] = path, now
    return path


def look(question: str = "") -> str:
    """Captura la pantalla y responde una pregunta sobre lo que se ve."""
    key, model = _gemini_creds()
    if not key:
        return "No tengo configurada la visión, Wilmer (falta la clave de Gemini)."
    path = capture()
    if not path:
        return "No pude capturar la pantalla (¿está grim instalado?)."
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        return f"No pude leer la captura: {e}"

    q = (question or "").strip() or "Describe brevemente qué hay en la pantalla."
    instr = (
        "Eres los ojos de BLUE, el asistente de Wilmer (programador e ingeniero "
        "mecánico). Mira la captura de su pantalla y responde su pregunta de forma "
        "directa, en español, para leerse en voz alta: 1 a 4 frases, sin markdown "
        "ni listas ni asteriscos. Si hay diagramas, gráficos, tablas, código o "
        "errores, interprétalos con criterio técnico. Si lo que pide no se ve en "
        "la imagen, dilo claro.\n\nPregunta de Wilmer: " + q)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=_GEMINI_BASE, timeout=45.0)
        resp = client.chat.completions.create(
            model=model, temperature=0.3,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": instr},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + b64}},
            ]}])
        try:
            import usage
            usage.bump("gemini-vision")
        except Exception:
            pass
        return (resp.choices[0].message.content or "").strip() or \
            "Vi la pantalla pero no supe qué decir."
    except Exception as e:
        s = str(e).lower()
        if any(k in s for k in ("429", "quota", "exhausted", "rate limit")):
            return "Se me agotó la cuota de visión por ahora, Wilmer."
        return f"No pude analizar la pantalla: {str(e)[:160]}"
