#!/usr/bin/env bash
# Instala BLUE en este equipo. Se puede volver a lanzar sin miedo: no repite
# lo que ya esté hecho y no pisa tu configuración si ya existe.
#
#   git clone https://github.com/willor16/blue-assistant.git ~/.local/share/blue
#   cd ~/.local/share/blue && ./install.sh
set -euo pipefail

CODIGO="$HOME/.local/share/blue"
DATOS="$HOME/.config/blue"
BIN="$HOME/.local/bin"
AQUI="$(cd "$(dirname "$0")" && pwd)"

paso() { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$1"; }
avisa(){ printf '    \033[33m!\033[0m %s\n' "$1"; }

# ── 1. Dónde vive el código ────────────────────────────────────────────────
paso "Comprobando dónde está el código"
if [ "$AQUI" != "$CODIGO" ]; then
    avisa "Estás en $AQUI, pero BLUE espera vivir en $CODIGO"
    avisa "Muévelo ahí y vuelve a lanzar esto, o los atajos no funcionarán."
    exit 1
fi
ok "$CODIGO"

# ── 2. Dependencias del sistema ────────────────────────────────────────────
paso "Dependencias del sistema"
FALTAN=()
for c in python git ffmpeg; do command -v "$c" >/dev/null || FALTAN+=("$c"); done
command -v uv >/dev/null || FALTAN+=("uv")
if [ ${#FALTAN[@]} -gt 0 ]; then
    if command -v pacman >/dev/null; then
        avisa "Faltan: ${FALTAN[*]} — instalando con pacman"
        sudo pacman -S --needed --noconfirm python uv git portaudio ffmpeg \
             playerctl wl-clipboard grim slurp libnotify
    else
        avisa "Faltan: ${FALTAN[*]}"
        avisa "No es Arch: instálalas con el gestor de tu distro y repite."
        exit 1
    fi
fi
ok "todo lo necesario está"
for c in playerctl wl-copy grim slurp notify-send fd; do
    command -v "$c" >/dev/null || avisa "opcional ausente: $c (algo funcionará peor)"
done

# ── 3. El entorno de Python ────────────────────────────────────────────────
paso "Entorno de Python (unos 2,8 GB, tarda)"
if [ ! -x "$CODIGO/.venv/bin/python" ]; then
    uv venv .venv --python 3.12
    ok "venv creado"
else
    ok "el venv ya estaba"
fi
uv pip install --quiet --python .venv/bin/python -r requirements.txt
ok "dependencias instaladas"

# ── 4. Tu configuración ────────────────────────────────────────────────────
paso "Configuración"
mkdir -p "$DATOS"
if [ -f "$DATOS/config.toml" ]; then
    ok "ya tenías config.toml, no lo toco"
else
    cp config.example.toml "$DATOS/config.toml"
    ok "creado $DATOS/config.toml a partir del ejemplo"
    avisa "ÁBRELO y pon tu clave de Groq (gratis: console.groq.com/keys)"
fi

# ── 5. El lanzador ─────────────────────────────────────────────────────────
paso "Lanzador"
mkdir -p "$BIN"
install -m 755 bin/blue "$BIN/blue"
ok "$BIN/blue"
case ":$PATH:" in
    *":$BIN:"*) ok "$BIN está en tu PATH" ;;
    *) avisa "$BIN NO está en tu PATH — añádelo a tu shell" ;;
esac

# ── 6. ¿Hay un Ollama en la red? ───────────────────────────────────────────
paso "Buscando un Ollama en la red local"
ENCONTRADO="$(.venv/bin/python -c "
import cerebros
print(cerebros.buscar_ollama_en_la_red() or '')
" 2>/dev/null || true)"
if [ -n "$ENCONTRADO" ]; then
    ok "encontrado en $ENCONTRADO"
    avisa "Si es tuyo, ponlo en config.toml como ollama_host (mejor por nombre .local)"
    avisa "y déjalo el PRIMERO de la cadena: es gratis y sin tope por minuto."
else
    avisa "no hay ninguno; BLUE usará la nube (necesitas la clave de Groq)"
    avisa "si enciendes uno más tarde, lo encontrará sola."
fi

# ── 7. Comprobación ────────────────────────────────────────────────────────
paso "Comprobando que arranca"
if .venv/bin/python -c "import blue" 2>/dev/null; then
    ok "el código carga bien"
else
    avisa "algo falla al importar; mira los errores de arriba"
    exit 1
fi

cat <<FIN

  Listo. Falta una cosa que no puedo hacer por ti: los atajos.

  Añade esto a tu configuración de Hyprland (en Caelestia suele ser
  ~/.config/caelestia/hypr-user.conf; si no, ~/.config/hypr/hyprland.conf):

    exec-once = ~/.local/bin/blue daemon
    bind = Super, J, exec, ~/.local/bin/blue trigger        # escuchar
    bind = Super+Shift, J, exec, ~/.local/bin/blue panel    # el panel
    bind = Super+Ctrl, J, exec, ~/.local/bin/blue toggle    # encender/apagar
    bind = Super+Alt, J, exec, ~/.local/bin/blue converse   # conversar

    windowrule = match:class ^(blue-panel)$, float 1
    windowrule = match:class ^(blue-panel)$, size 900 620
    windowrule = match:class ^(blue-panel)$, center 1
    windowrule = match:class ^(blue-panel)$, rounding 16
    windowrule = match:class ^(blue-bubble)$, float 1
    windowrule = match:class ^(blue-bubble)$, size 320 380
    windowrule = match:class ^(blue-bubble)$, pin 1
    windowrule = match:class ^(blue-bubble)$, rounding 22

  Para probarla ya, sin reiniciar la sesión:

    blue daemon &        # la deja corriendo
    blue text "hola"     # le hablas por texto, sin micrófono

  La primera vez se descargan los modelos de voz (Kokoro y Whisper),
  así que la primera respuesta tarda más.

FIN
