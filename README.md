# BLUE

Asistente de voz para Linux. Escucha, habla, y hace cosas de verdad en el
escritorio: abre y mueve ventanas, lleva agenda y correo, busca en internet,
consulta tus apuntes, resuelve cálculos de ingeniería y delega el trabajo
pesado de programación a Claude Code.

Pensado para CachyOS / Arch con Hyprland, pero el cerebro y las herramientas
funcionan en cualquier Linux; lo único atado a Hyprland es el control de
ventanas.

---

## Qué sabe hacer

**El escritorio.** Abrir y cerrar aplicaciones, enfocar y mover ventanas entre
pantallas, cambiar de escritorio, volumen, brillo, portapapeles, capturas,
apagar o suspender.

**Proyectos y protocolos.** Guardas una combinación ("abre el código, la
terminal y pon música") y la lanzas por voz. Un proyecto además es un
contenedor de contexto: su carpeta, su memoria y sus documentos.

**Tus archivos.** Crear carpetas, listar, buscar, leer, escribir, renombrar,
mover, copiar y borrar. Todo acotado a tu carpeta personal, y **borrar va
siempre a la papelera**, nunca destruye nada.

**Tus documentos.** Indexa tus apuntes y responde a partir de ellos, citando de
dónde salió. Acotado al proyecto activo.

**Ingeniería.** Conversión de unidades, propiedades termodinámicas, y cálculos
de termodinámica, fluidos, transferencia de calor y estructural, con gráficas.
Local e instantáneo.

**Ver la pantalla.** "Qué dice este error", "explícame este diagrama".

**Agenda y correo.** Anotar, listar, revisar la bandeja y enviar.

**Memoria.** Recuerda tus preferencias y decisiones entre sesiones.

**Trabajo pesado.** Lo delega a Claude Code: leer y editar archivos de un
proyecto, correr tests, análisis FEM en FreeCAD.

---

## El escalafón

Wilmer le puso nombre clave a cada motor, y son **palabras reservadas**: al
nombrarlos en voz alta el trabajo se va a ese motor. La regla que manda sobre
todas es que **PROMETEO es la única voz** — los demás piensan o programan, pero
quien habla siempre es ella, y cuenta lo suyo con su propio carácter.

| Nombre | Qué es | Para qué |
|---|---|---|
| **PROMETEO** | El cerebro del proveedor configurado (por defecto `gpt-oss-120b` en Groq) | La voz. Conversa, maneja el escritorio, tiene las 55 herramientas |
| **ORFEO** | `jarvis-heavy` en el Ollama de la otra PC | Razonar largo y sin prisa. No toca el escritorio |
| **ARGOS** | Reservado | El nombre está guardado; el motor no existe todavía |
| **ÍCARO** | Hermes Agent, con perfil propio en `~/.config/blue/hermes` | Agente con herramientas propias |
| **ÉREBO** | Claude Code | Programar de verdad: archivos, tests, FEM |

```
Orfeo, explícame por qué Bernoulli falla en flujo viscoso
pregúntale a Orfeo cómo se dimensiona una bomba centrífuga
Érebo, arregla los tests del proyecto
Ícaro, busca esto y déjamelo en un archivo
qué cerebros tenemos            ← pregunta por ellos, no los invoca
```

Preguntar **por** un motor no lo llama. "Qué es ORFEO" o "cuéntame el mito de
Prometeo" los contesta PROMETEO; hace falta dirigirse a ellos, al principio de
la frase o detrás de un encargo ("pregúntale a…", "que lo vea…", "pásaselo a…").

**Sobre PROMETEO y la "versión light".** En el asistente viejo PROMETEO era
`jarvis-light`, un Gemma4 de 31B, y se daba por hecho que un modelo local no
sabía llamar herramientas: por eso conversaba el de la nube. Eso dejó de ser
cierto. Hoy PROMETEO es `jarvis` (Qwen3-Next 80B MoE) en el Ollama de casa, y
se midió llamando correctamente las 65 herramientas a 57-60 tokens/s, contra
los 25 del Gemma4. La nube pasó a ser lo que siempre debió: el respaldo.

PROMETEO también puede consultarles por su cuenta, sin que se lo pidas: tiene
`consultar_orfeo` y `consultar_icaro` entre sus herramientas, y avisa antes de
llamarlas porque ORFEO tarda de veinte segundos a un par de minutos.

---

## Cómo se comporta

**Habla como alguien, no como un documento.** Lo que dice pasa por dos filtros
antes de sonar: `estilo.py` convierte las listas en prosa y quita los tics de
cierre ("en resumen", "¿en qué puedo ayudarte?"), y `texto.py` quita emojis,
comillas, markdown y reduce las URLs y rutas a su nombre — dice "abro YouTube",
no la dirección entera. **En pantalla se conserva el formato original**, que
ahí una tabla o una lista sí se leen bien.

**Te deja terminar de hablar.** Espera 1.8 segundos de silencio real antes de
dar tu frase por acabada, con un tope de 45 segundos por intervención. El
umbral de voz se calibra con el ruido de fondo de tu cuarto.

**Avisa cuando algo tarda.** A los 9, 28 y 70 segundos suelta una señal de vida,
y luego un latido cada minuto y pico. Con las tareas pesadas la escala es más
amplia. Si dijo "te aviso al terminar", cumple.

**Sabe quién es.** Conoce su modelo, sus capacidades reales y el estado de la
máquina donde vive.

---

## Instalación en otro equipo

**Un comando.** El instalador hace lo demás y se puede repetir sin miedo: no
pisa tu configuración ni rehace lo que ya esté.

```bash
git clone https://github.com/willor16/blue-assistant.git ~/.local/share/blue
cd ~/.local/share/blue && ./install.sh
```

Instala las dependencias del sistema (en Arch/CachyOS), monta el entorno de
Python, crea tu `config.toml` desde el ejemplo, deja el lanzador en
`~/.local/bin/blue`, **busca solo si hay un Ollama en tu red local** y te
imprime los atajos de Hyprland para pegar.

Tiene que vivir en `~/.local/share/blue`: es donde lo buscan el lanzador y los
atajos. Si lo clonas en otro sitio, el instalador te avisa y para.

Después, solo faltan dos cosas manuales:

1. **Tu clave de Groq** en `~/.config/blue/config.toml`. Es gratis:
   https://console.groq.com/keys
2. **Los atajos**, pegando en tu config de Hyprland lo que imprime el
   instalador.

Y ya:

```bash
blue daemon &          # la deja corriendo
blue text "hola"       # le hablas por texto, sin micrófono
```

La primera vez se descargan los modelos de voz (Kokoro y Whisper), así que esa
primera respuesta tarda más de lo normal.

### El cerebro

BLUE piensa con un modelo de lenguaje, y tienes dos caminos:

- **Un Ollama en tu red** (lo mejor): gratis, privado y sin tope por minuto. El
  instalador lo busca solo, y si enciendes la máquina más tarde **BLUE la
  encuentra sin que le digas nada** — barre la red y se queda con la dirección,
  así que un cambio de IP del router ya no la deja sin cerebro.
- **La nube** (Groq gratis, con Gemini y Claude detrás): funciona sin más que
  la clave, pero Groq limita a 8.000 tokens por minuto y modelo, así que va más
  lenta a ratos.

Puedes tener los dos: se ponen en orden en `config.toml` y BLUE cae al
siguiente sola cuando uno falla.

**Si usas Ollama, sube `num_ctx` a 32768** en su `[[brain]]`. Los Modelfile
suelen fijarlo en 8.192 y el prompt de BLUE con todas sus herramientas son
~9.600 tokens: no cabe. Ollama al desbordar trunca por el principio, se lleva
el prompt del sistema, y BLUE parece tonta cuando lo que está es sin
instrucciones.

### Si prefieres hacerlo a mano

### 1. Dependencias del sistema

```bash
# Arch / CachyOS
sudo pacman -S --needed python uv git portaudio ffmpeg glib2 \
                        wl-clipboard grim slurp libnotify

# Opcionales según lo que uses
sudo pacman -S --needed hyprland quickshell   # control de ventanas y burbuja
```

### 2. El código y su entorno

```bash
git clone https://github.com/willor16/blue-assistant.git ~/.local/share/blue
cd ~/.local/share/blue
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

Son unos 2.8 GB, la mayoría de torch (lo usan Kokoro y Whisper).

### 3. La configuración

```bash
mkdir -p ~/.config/blue
cp config.example.toml ~/.config/blue/config.toml
```

Edita `~/.config/blue/config.toml` y pon **tu** clave. La de Groq es gratis:
https://console.groq.com/keys

```toml
provider = "groq"
model    = "openai/gpt-oss-120b"
api_key  = "…"
```

Ese archivo **nunca se sube**: está en el `.gitignore` y vive fuera del repo.

**Si tienes un Ollama en la red local, ponlo el PRIMERO de la cadena.** Es
gratis, privado y sin tope por minuto; la nube queda de respaldo para cuando esa
máquina esté apagada. Dos detalles que cuestan caro si se pasan por alto:

```toml
# Por NOMBRE, no por IP: el DHCP cambia la dirección y entonces Blue da el
# servidor por apagado y se va a la nube sin decírtelo.
ollama_host = "http://mi-servidor.local:11434"

[[brain]]
provider   = "ollama"
model      = "jarvis"
num_ctx    = 32768   # OBLIGATORIO subirlo
```

`num_ctx` importa más de lo que parece. Los Modelfile suelen fijarlo en 8.192 y
el prompt de Blue con todas sus herramientas son ~9.600 tokens: **no cabe**.
Ollama al desbordar trunca por el principio, se lleva el prompt del sistema, y
Blue se queda sin saber quién es ni qué reglas sigue — sin dar ningún error.
Parece que el modelo se ha vuelto tonto y lo que pasa es que está sin
instrucciones.

### 4. El lanzador

```bash
cat > ~/.local/bin/blue << 'EOF'
#!/bin/sh
cd "$HOME/.local/share/blue" || exit 1
exec ./.venv/bin/python blue.py "$@"
EOF
chmod +x ~/.local/bin/blue
```

### 5. Los atajos (Hyprland)

```conf
exec-once = ~/.local/bin/blue daemon
bind = Super, J, exec, ~/.local/bin/blue trigger        # escuchar
bind = Super+Shift, J, exec, ~/.local/bin/blue panel    # el panel
bind = Super+Ctrl, J, exec, ~/.local/bin/blue toggle    # encender / apagar

windowrule = match:class ^(blue-panel)$, float 1
windowrule = match:class ^(blue-panel)$, size 900 620
windowrule = match:class ^(blue-panel)$, center 1
windowrule = match:class ^(blue-panel)$, rounding 16

windowrule = match:class ^(blue-bubble)$, float 1
windowrule = match:class ^(blue-bubble)$, size 320 380
windowrule = match:class ^(blue-bubble)$, pin 1
windowrule = match:class ^(blue-bubble)$, rounding 22
```

### 6. Comprobar

```bash
blue text "hola, ¿qué puedes hacer?"
```

La primera vez baja los modelos de Whisper y Kokoro, así que tarda.

---

## Uso

```bash
blue daemon        # residente: voz + panel web. Va en exec-once
blue trigger       # dispara una escucha           (Super+J)
blue panel         # la interfaz gráfica           (Super+Shift+J)
blue toggle        # enciende / apaga              (Super+Ctrl+J)
blue stop          # lo apaga
blue text "..."    # prueba por texto, sin micrófono
```

Hablando:

```
abre el código en la pantalla 2
pásate al navegador
qué tengo abierto
crea un protocolo llamado estudio que abra Obsidian y ponga música
trabajemos en termodinámica
indexa mis apuntes de fluidos
qué dicen mis apuntes sobre pérdidas por fricción
mira mi pantalla, qué dice este error
cuánto es 3 bar en psi
recuérdame a las seis revisar el correo
```

---

## Dónde está cada cosa

| Ruta | Qué hay |
|---|---|
| `~/.local/share/blue/` | El código y el entorno virtual |
| `~/.config/blue/config.toml` | Tu configuración y tus claves |
| `~/.config/blue/memory.json` | Lo que recuerda de ti |
| `~/.config/blue/protocols.json` | Tus protocolos y proyectos |
| `~/.config/blue/rag.db` | El índice de tus documentos |
| `~/.config/blue/agenda.json` | Tu agenda |
| `~/.config/blue/hermes/` | El perfil de Hermes que usa ÍCARO |

Nada de eso viaja al repositorio: son tuyos y de esa máquina.

Si quieres llevarte tu memoria y tus protocolos a otro equipo, copia esos
`.json` a mano. El índice de documentos conviene rehacerlo allí, porque apunta
a rutas locales.

---

## Ajustes que igual quieres tocar

En `~/.config/blue/config.toml`:

```toml
escucha_silencio_s = 1.8    # súbelo si te sigue cortando al pensar
escucha_max_s      = 45.0   # tope por intervención
escucha_umbral     = "auto" # o un número fijo, p.ej. 0.012

tts          = "kokoro"     # kokoro (local) | edge (online) | piper (ligero)
kokoro_voice = "ef_dora"    # ef_dora | em_alex | em_santa
whisper_size = "small"      # tiny | base | small | medium

ollama_host = "http://mi-servidor.local:11434"   # el cerebro de casa, por nombre
```

Y dentro del `[[brain]]` de Ollama, `num_ctx = 32768`. No lo bajes por debajo de
16.384 o el prompt no cabrá y Blue empezará a responder cosas raras.

---

## Cómo está montado

`blue.py` es la puerta de entrada y el daemon. `assistant.py` orquesta un turno:
escuchar, pensar, avisar si tarda, hablar. `brain.py` arma el prompt y llama al
modelo con sus 53 herramientas. `voice.py` graba y sintetiza. `web.py` sirve el
panel.

Lo demás son las herramientas por área: `actions.py` (escritorio),
`protocols.py`, `workspace.py`, `rag.py` (documentos), `engineering.py`,
`agenda.py`, `mailbox.py`, `memory.py`, `vision.py`, `tasks.py` (Claude Code).

Y tres piezas de comportamiento: `conciencia.py` (qué sabe de sí misma y de la
máquina), `avisos.py` (señales de vida cuando tarda),
`cerebros.py` (el escalafón: quién es cada motor y cómo se le llama), `estilo.py` + `texto.py`
(que suene a alguien hablando).
