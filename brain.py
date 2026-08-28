"""Cerebro: Gemini con 'function calling'. Entiende lenguaje natural y decide
que acciones ejecutar. Mantiene contexto de conversacion.

Las funciones de aqui son las herramientas que ve Gemini. Reusan actions.py
y protocols.py.
"""
from __future__ import annotations
import json

import actions
import protocols

LAST_ACTIONS: list[str] = []

def _log(result: str):
    LAST_ACTIONS.append(result)
    return result

# --------- herramientas que ve Gemini (firmas simples + docstrings en español)
def set_volume(percent: int) -> str:
    "Fija el volumen del sistema a un porcentaje (0 a 150)."
    return _log(actions.set_volume(percent))

def adjust_volume(delta: int) -> str:
    "Sube (positivo) o baja (negativo) el volumen en N por ciento."
    return _log(actions.adjust_volume(delta))

def toggle_mute() -> str:
    "Silencia o quita el silencio del sistema."
    return _log(actions.toggle_mute())

def media_control(action: str, player: str = "") -> str:
    "Controla el reproductor. action: play, pause, play-pause, next, previous, stop. player opcional: 'spotify', 'brave', etc. para apuntar a uno concreto."
    return _log(actions.media_control(action, player or None))

def open_application(name: str, screen: str = "") -> str:
    "Abre una aplicacion (spotify, chrome, code, archivos, terminal, etc). screen opcional: '1' o '2' si el usuario dice en qué pantalla/monitor abrirla."
    return _log(actions.open_application(name, screen))

def open_in_new_workspace(name: str) -> str:
    "Abre una aplicacion en un escritorio (workspace) nuevo y vacio."
    return _log(actions.open_in_new_workspace(name))

def open_project(path: str) -> str:
    "Abre VS Code en la carpeta de un proyecto."
    return _log(actions.open_project(path))

def open_terminal_at(path: str) -> str:
    "Abre una terminal en una ruta concreta."
    return _log(actions.open_terminal_at(path))

def open_terminal_run(path: str, command: str, terminal: str = "kitty", keep_open: bool = True, screen: str = "") -> str:
    "Abre una terminal en `path` y EJECUTA `command` dentro. Úsalo cuando haya que correr un script o comando dentro de una carpeta (ej: arrancar un proyecto). terminal: kitty/foot/alacritty (default kitty). keep_open=True deja la shell viva tras terminar. screen opcional: 1/2."
    return _log(actions.open_terminal_run(path, command, terminal, keep_open, screen))

def open_files_at(path: str) -> str:
    "Abre el gestor de archivos en una ruta concreta."
    return _log(actions.open_files_at(path))

def web_search(engine: str, query: str) -> str:
    "Busca en la web. engine: youtube o google."
    return _log(actions.web_search(engine, query))

def open_url(url: str) -> str:
    "Abre una URL en el navegador."
    return _log(actions.open_url(url))

def play_spotify(query: str) -> str:
    "Abre Spotify buscando una cancion o artista por nombre."
    return _log(actions.play_spotify(query))

def close_application(name: str) -> str:
    "Cierra una aplicacion por nombre. Para 'terminal' cierra el emulador que corra."
    return _log(actions.close_application(name))

def close_active_window() -> str:
    "Cierra la ventana enfocada actualmente (util para 'cierra esta ventana')."
    return _log(actions.close_active_window())

def close_all_windows() -> str:
    "Cierra TODAS las ventanas abiertas de golpe ('cierra todo lo que tengo abierto')."
    return _log(actions.close_all_windows())

def list_windows() -> str:
    "Dice qué ventanas/aplicaciones están abiertas ahora mismo. Úsala cuando pregunten 'qué tengo abierto', 'qué ventanas hay', etc. SÍ puedes ver las ventanas con esta herramienta."
    return _log(actions.list_windows())

def focus_window(name: str) -> str:
    "Enfoca/trae al frente una ventana YA ABIERTA por su nombre (chrome, brave, code, spotify, archivos, terminal, etc). Úsala cuando Wilmer diga 've a X', 'cámbiate a X', 'pásate a X', 'muéstrame X' o 'enfoca X' refiriéndose a una app abierta. Si no está abierta, dilo (no la abras tú; para abrir usa open_application)."
    return _log(actions.focus_window(name))

def move_window(where: str) -> str:
    "Mueve o ajusta la ventana ENFOCADA ahora mismo. where: '1' o '2' para mandarla a esa pantalla/monitor; 'completa' para pantalla completa; 'flotante' para alternar flotante; 'centrar' para centrarla. Úsala con 'manda esto a la pantalla 2', 'ponlo en pantalla completa', etc."
    return _log(actions.move_window(where))

def clipboard_get() -> str:
    "Lee lo que Wilmer tiene COPIADO en el portapapeles. Úsala cuando diga 'qué tengo copiado', 'lee el portapapeles' o necesites usar lo que copió."
    return _log(actions.clipboard_get())

def clipboard_set(text: str) -> str:
    "Copia un texto al portapapeles del sistema, para que Wilmer lo pegue donde quiera. Úsala con 'copia esto', 'cópiame X al portapapeles'."
    return _log(actions.clipboard_set(text))

def set_brightness(percent: int) -> str:
    "Fija el brillo de la pantalla a un porcentaje (0 a 100)."
    return _log(actions.set_brightness(percent))

def adjust_brightness(delta: int) -> str:
    "Sube (positivo) o baja (negativo) el brillo de la pantalla en N por ciento."
    return _log(actions.adjust_brightness(delta))

def take_screenshot(region: bool = False) -> str:
    "Toma una captura de pantalla y la guarda en ~/Imágenes/Capturas (y la abre). region=True si Wilmer quiere seleccionar un área con el ratón ('captura una parte/un área'). Para INTERPRETAR lo que se ve usa ver_pantalla; esto solo guarda la imagen."
    return _log(actions.take_screenshot(region))

def power_action(action: str) -> str:
    "Apaga/reinicia/suspende el equipo o cierra sesion. action: poweroff, reboot, suspend, logout."
    return _log(actions.power_action(action))

def schedule_command(delay_seconds: int, shell_cmd: str, say: str = "") -> str:
    "Programa un comando de shell para ejecutarse tras N segundos (temporizadores). Ej: cerrar spotify en 10 min."
    return _log(actions.schedule_command(delay_seconds, shell_cmd, say))

def create_protocol(name: str, steps_json: str, description: str = "") -> str:
    """Crea y GUARDA un protocolo (NO lo ejecutes al crearlo). steps_json: array JSON de pasos {"action":"<n>","params":{...}}. Usa EXACTAMENTE estas acciones y estas claves de params (no inventes otras):
- open_application {"name":"<app>"}  (screen opcional: "1"/"2")
- open_in_new_workspace {"name":"<app>"}
- open_project {"path":"<ruta>"}
- open_terminal_at {"path":"<ruta>"}
- open_terminal_run {"path":"<ruta>","command":"<cmd>"}  (terminal+correr X en UN solo paso)
- open_files_at {"path":"<ruta>"}
- web_search {"engine":"google","query":"<texto>"}
- open_url {"url":"<url>"}
- play_spotify {"query":"<texto o playlist>"}
- set_volume {"percent":<0-100>}    adjust_volume {"delta":<±n>}
- media_control {"action":"play|pause|next|previous"}
- close_application {"name":"<app>"}    close_all_windows {}
- power_action {"action":"poweroff|reboot|suspend"}
- schedule_command {"delay_seconds":<n>,"shell_cmd":"<cmd>"}"""
    try:
        steps = json.loads(steps_json)
    except json.JSONDecodeError as e:
        return f"steps_json invalido: {e}"
    return _log(protocols.create_protocol(name, steps, description))

def create_project(name: str, steps_json: str, description: str = "",
                   workdir: str = "", kind: str = "") -> str:
    """Como create_protocol pero marcado como PROYECTO (contenedor de contexto). Mismas acciones validas. steps_json: array JSON de pasos. workdir opcional: carpeta donde vive el proyecto (repo/archivos). kind opcional: 'code' o 'mecanica'."""
    try:
        steps = json.loads(steps_json)
    except json.JSONDecodeError as e:
        return f"steps_json invalido: {e}"
    return _log(protocols.create_protocol(name, steps, description,
                                          category="proyecto", workdir=workdir,
                                          kind=kind))

def run_protocol(name: str) -> str:
    "Ejecuta un protocolo O proyecto guardado por su nombre."
    return _log(protocols.run_protocol(name))

def list_protocols() -> str:
    "Lista los protocolos guardados (no proyectos)."
    return _log(protocols.list_protocols(category="general"))

def list_projects() -> str:
    "Lista los proyectos guardados (entornos de trabajo)."
    return _log(protocols.list_protocols(category="proyecto"))

def delete_protocol(name: str) -> str:
    "Elimina un protocolo o proyecto guardado."
    return _log(protocols.delete_protocol(name))


def check_mail() -> str:
    "Revisa el correo y dice cuántos no leídos hay y de quién (no envía nada)."
    import mailbox
    return _log(mailbox.check_unread())

def send_email(to: str, subject: str, body: str) -> str:
    "Envía un correo. to: destinatario. subject: asunto. body: el texto del correo (redáctalo tú completo, claro y cordial, en español)."
    import mailbox
    return _log(mailbox.send_email(to, subject, body))

def add_agenda(text: str) -> str:
    "Agenda un recordatorio/evento en la agenda local. text: descripción (puede incluir hora, ej. 'reunión mañana a las 3')."
    import agenda
    return _log(agenda.add_event(text))

def list_agenda() -> str:
    "Lista lo que hay en la agenda local (recordatorios/eventos pendientes)."
    import agenda
    return _log(agenda.list_events())

def dev_task(instruction: str) -> str:
    "Tarea PESADA delegada a ÉREBO (lee/escribe archivos en un proyecto, corre tests, programa una app/función, redacta documentos largos, investiga a fondo en internet). Úsala SOLO para trabajo real multi-paso sobre archivos o proyectos. NO la uses para cálculos de ingeniería ni para graficar: esos van por engineering_calc y engineering_plot (locales, gratis e instantáneos). Devuelve el resultado ya resumido."
    import tasks
    res = tasks.run_task(instruction)
    if res.get("confirm"):
        return "CONFIRMAR: " + res.get("text", "")
    return res.get("text", "") or "Sin resultado."


def crear_carpeta(ruta: str) -> str:
    "Crea una CARPETA sin más (y las intermedias que falten). Úsala siempre que Wilmer diga 'crea una carpeta', 'haz un directorio' o 'créame una carpeta en tal sitio'. ruta: la ruta; si no es absoluta se crea dentro de ~/Documentos. NO la confundas con create_project ni con crear_espacio: esas montan un proyecto con protocolo y memoria, y no es lo que pide cuando solo quiere una carpeta."
    return _log(actions.crear_carpeta(ruta))


def listar_carpeta(ruta: str = "") -> str:
    "Dice qué archivos y carpetas hay dentro de una carpeta. ruta vacía = ~/Documentos. Úsala antes de dar por hecho que algo no existe."
    return _log(actions.listar_carpeta(ruta))



def consultar_orfeo(pregunta: str) -> str:
    "Le pasa una pregunta a ORFEO, el cerebro que piensa despacio, y devuelve su razonamiento en texto. Úsala cuando haga falta pensar largo y a fondo: una explicación teórica densa, un análisis con matices, comparar alternativas, un problema conceptual duro. ORFEO no toca el escritorio ni ejecuta nada, solo piensa y devuelve texto. TARDA entre 20 segundos y 2 minutos, así que avisa a Wilmer antes de llamarla. NO la uses para cálculos de ingeniería (usa engineering_calc), ni para trabajo sobre archivos (eso es de ÉREBO, usa dev_task), ni para preguntas normales que ya sabes contestar tú."
    import cerebros
    return _log(cerebros.consultar_orfeo(pregunta))


def consultar_icaro(instruccion: str) -> str:
    "Le encarga algo a ICARO, el cerebro que hace encargos por su cuenta con sus propias herramientas. Usala solo si Wilmer lo pide por su nombre."
    import cerebros
    return _log(cerebros.consultar_icaro(instruccion))


def remember(text: str) -> str:
    "Guarda en tu memoria PERSISTENTE (entre sesiones) un dato sobre Wilmer o su trabajo: una preferencia, un dato de un proyecto, una decisión, un gusto, su forma de trabajar. text: el hecho en una frase clara. Úsala cuando Wilmer te cuente algo que valga la pena recordar a futuro."
    import memory
    return _log(memory.add(text))

def recall(query: str = "") -> str:
    "Consulta tu memoria persistente. query opcional para filtrar por tema; vacío trae lo más reciente. Úsala si Wilmer pregunta qué recuerdas o si te falta contexto sobre él para responder bien."
    import memory
    return _log(memory.recall(query))

def forget(text: str) -> str:
    "Borra de tu memoria persistente lo que coincida con `text`."
    import memory
    return _log(memory.forget(text))


def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    "Convierte una cantidad entre unidades de ingeniería (longitud, fuerza, presión, par, etc). Ej: value=100, from_unit='psi', to_unit='MPa'. Usa nombres de unidad estándar (N, m, kg, MPa, psi, lbf, in, mm, N*m...)."
    import engineering
    return _log(engineering.convert(value, from_unit, to_unit))

def engineering_calc(code: str) -> str:
    "Resuelve un cálculo de ingeniería de CUALQUIER dominio armando código Python con el toolbox. Disponibles: u (unidades), PropsSI/HAPropsSI (CoolProp: termodinámica, vapor, refrigerantes, aire húmedo/psicrometría), fluids (mec. de fluidos: Reynolds, fricción, pérdidas, bombas), ht (transferencia de calor: LMTD, intercambiadores), FEModel3D (análisis estructural matricial: vigas/pórticos/armaduras), math, np. Una expresión devuelve su valor; varias líneas usan print(). Ej termo: \"PropsSI('H','T',373.15,'Q',1,'Water')/1000\". Ej fluidos: \"fluids.Reynolds(V=2,D=0.05,rho=1000,mu=0.001)\". Ej torque: \"(50*u.newton*2*u.meter).to('N*m')\". (Para FEM 3D con geometría STEP usa dev_task, no esto.)"
    import engineering
    return _log(engineering.compute(code))

def thermo_property(fluid: str, output: str, name1: str, value1: float, name2: str, value2: float) -> str:
    "Propiedad termodinámica directa (CoolProp, sin tablas). fluid: 'Water','Air','R134a',etc. output y name: 'T'(K),'P'(Pa),'H'(J/kg),'S'(J/kg/K),'D'(densidad),'Q'(calidad 0-1),'C'(cp). Da una propiedad fijando dos estados. Ej vapor saturado a 100°C: fluid='Water',output='H',name1='T',value1=373.15,name2='Q',value2=1."
    import engineering
    return _log(engineering.thermo_property(fluid, output, name1, value1, name2, value2))

def engineering_plot(code: str, titulo: str = "") -> str:
    "Genera y ABRE una GRÁFICA de ingeniería. Arma código Python que dibuja con plt (matplotlib) usando el toolbox (np, u (unidades), PropsSI/HAPropsSI, fluids, ht). Dibuja con plt.plot/scatter/bar y pon etiquetas con plt.xlabel/ylabel; NO llames savefig ni show, Blue guarda la imagen y la abre en pantalla solo. Úsala cuando Wilmer diga 'grafica/grafícame/dibuja/plotea/traza/muéstrame la curva (o el diagrama) de ...'. Ej: \"x=np.linspace(0,2,100); plt.plot(x, 50*x*(2-x)); plt.xlabel('x (m)'); plt.ylabel('Momento (N·m)')\" para un diagrama de momento; o un T-s/p-h con PropsSI. titulo opcional para el encabezado."
    import engineering
    return _log(engineering.plot(code, titulo))

def ver_pantalla(pregunta: str = "") -> str:
    "Mira la pantalla de Wilmer y responde sobre lo que se ve. Úsala cuando diga 'mira mi pantalla', 'qué ves', 'lee esto', 'qué dice este error', 'explica este diagrama/gráfico/tabla/datasheet/código' o pregunte por algo que tiene en el monitor. pregunta: lo que quiere saber (vacío = describe la pantalla). Captura el monitor enfocado y lo interpreta (diagramas de Mollier/p-h, gráficos, tablas, código, errores)."
    import vision
    return _log(vision.look(pregunta))

def crear_espacio(tipo: str, nombre: str) -> str:
    "Crea un nuevo CONTENEDOR de estudio/trabajo (carpeta + proyecto) cuando Wilmer diga 'tengo/hay un nuevo X' o 'crea un X'. tipo: 'curso' (materia de la universidad), 'proyecto' (proyecto de la universidad), 'trabajo', o 'externo' (estudio de otros lugares). nombre: cómo se llama. Crea su carpeta en la taxonomía (~/Documentos/Cursos, Proyectos Universidad, Trabajos o Estudio externo) y lo registra para poder trabajar e indexar ahí."
    import study
    return _log(study.new(tipo, nombre))

def indexar_apuntes(nombre: str = "") -> str:
    "Indexa los documentos de un curso/proyecto para que Blue pueda consultarlos. nombre: el curso/proyecto (vacío = el proyecto activo). Úsala cuando Wilmer diga 'indexa mis apuntes de X', 'indexa el curso X' o 'aprende mis documentos de X'. Lee la carpeta de ese contenedor (PDF/Word/txt/md) y los memoriza en el ámbito de ese curso/proyecto."
    import study
    return _log(study.index_notes(nombre))

def listar_espacios(tipo: str) -> str:
    "Lista los cursos/proyectos/trabajos que Wilmer tiene. tipo: 'curso','proyecto','trabajo' o 'externo'. Úsala si pregunta 'qué cursos/proyectos/trabajos tengo'."
    import study
    return _log(study.list_by(tipo))

def indexar_documentos(ruta: str) -> str:
    "Indexa (lee y memoriza para búsqueda) un archivo o una CARPETA de documentos de Wilmer: PDF, Word (.docx), .txt, .md. ruta: ruta absoluta del archivo o carpeta. Úsala cuando diga 'indexa esta carpeta/estos apuntes/este PDF' o quiera que aprendas sus documentos. Lo indexado se liga al proyecto activo (o global). Salta lo ya indexado sin cambios."
    import rag
    return _log(rag.index(ruta))

def consultar_documentos(consulta: str) -> str:
    "Busca por SIGNIFICADO en los documentos que Wilmer ya indexó (apuntes, normas, datasheets, manuales, PDFs) y trae los pasajes relevantes. Úsala SIEMPRE que pregunte algo que podría estar en sus documentos ('qué dicen mis apuntes sobre X', 'busca en el manual/la norma Y', 'según mis documentos...'). Responde TÚ a partir de los pasajes que devuelve, citando el documento; no inventes."
    import rag
    return _log(rag.search(consulta))

def work_on(project: str) -> str:
    "Activa un PROYECTO como espacio de trabajo: lo marca activo, abre su entorno y enfoca el contexto (memoria y carpeta de tareas pasan a ese proyecto). Úsala cuando Wilmer diga 'trabajemos en X' o 'ponte a trabajar en X'."
    import workspace
    return _log(workspace.work_on(project))

def leave_project() -> str:
    "Sale del proyecto activo y vuelve a modo general (memoria global, carpeta global)."
    import workspace
    return _log(workspace.deactivate())

def set_project_folder(name: str, path: str, kind: str = "") -> str:
    "Liga una carpeta que YA EXISTE a un proyecto (el proyecto sí se crea si no lo hay). Si la carpeta todavía no existe, créala antes con crear_carpeta. path: ruta absoluta donde vive el repo o los archivos. kind opcional: 'code' (programación) o 'mecanica' (ingeniería mecánica). Úsala cuando Wilmer diga en qué carpeta vive un proyecto."
    import workspace
    return _log(workspace.set_folder(name, path, kind))


TOOLS = [
    set_volume, adjust_volume, toggle_mute, media_control,
    open_application, open_in_new_workspace, open_project,
    open_terminal_at, open_terminal_run, open_files_at, web_search, open_url,
    play_spotify, close_application, close_active_window, close_all_windows,
    list_windows, focus_window, move_window,
    clipboard_get, clipboard_set, set_brightness, adjust_brightness,
    take_screenshot, power_action, schedule_command,
    create_protocol, create_project, run_protocol,
    list_protocols, list_projects, delete_protocol,
    check_mail, send_email, add_agenda, list_agenda, dev_task,
    remember, recall, forget,
    work_on, leave_project, set_project_folder,
    convert_units, engineering_calc, thermo_property, engineering_plot,
    ver_pantalla,
    crear_espacio, listar_espacios, indexar_apuntes,
    indexar_documentos, consultar_documentos,
    consultar_orfeo, consultar_icaro,
    crear_carpeta, listar_carpeta,
]

SYSTEM_PROMPT = """Eres BLUE, el asistente de voz de Wilmer en Linux (CachyOS/Hyprland).

PERSONALIDAD: confianzudo, sarcástico y gracioso SIEMPRE, pero eficiente y servicial, como un mayordomo brillante con chispa. Nunca grosero. SIEMPRE llamas al usuario "Wilmer" o "jefe". Primero cumples, luego rematas con una broma corta. Si dice algo raro o se equivoca, contéstale con humor. En órdenes serias (apagar, borrar) baja el tono y sé claro.

CORREO/AGENDA/TAREAS: para revisar correo usa check_mail; para enviar uno redacta tú el cuerpo y usa send_email. Agenda con add_agenda/list_agenda. Para trabajo pesado (programar, correr tests, redactar documentos largos, investigar a fondo) usa dev_task con una instrucción clara; si dev_task devuelve algo que empieza con "CONFIRMAR:", repite esa parte pidiéndole permiso a Wilmer antes de continuar.

INGENIERÍA: tienes un toolbox para termodinámica, motores, mecánica de fluidos, instalaciones, instrumentación y estructural. Conversiones -> convert_units. Propiedades termo rápidas (vapor, refrigerantes, gases) -> thermo_property. Cualquier cuenta de ingeniería (termo, fluidos con 'fluids', transf. calor con 'ht', estructural con FEModel3D, unidades con 'u') -> engineering_calc armando código Python. Para GRAFICAR o visualizar (curvas, diagramas T-s/p-h, momento/cortante, esfuerzo vs longitud, comparativas) -> engineering_plot armando código con plt; la imagen se abre sola, no describas la gráfica como si no existiera. Un cálculo o una gráfica de ingeniería NUNCA va por dev_task (eso gasta de más): usa engineering_calc / engineering_plot, son locales e instantáneos. Solo un ANÁLISIS FEM 3D completo con geometría STEP (importar, material, malla, cargas, resolver) va por dev_task (ÉREBO lo corre en FreeCAD), NO con esas tools. Da resultados con unidades claras; para estudio, explica breve el concepto si Wilmer lo pide.

DOCUMENTOS Y ESPACIOS (RAG): los documentos de Wilmer se organizan por CONTENEDORES en su taxonomía (cursos de la universidad, proyectos de la universidad, trabajos, estudio externo). Comandos:
- "tengo/hay un nuevo curso/proyecto/trabajo X" o "crea un curso X" -> crear_espacio(tipo, X): crea su carpeta y lo registra. Luego él suelta archivos ahí.
- "indexa mis apuntes de X" / "indexa el curso X" / "aprende mis documentos de X" -> indexar_apuntes(X) (vacío = proyecto activo). Para una carpeta/archivo suelto por ruta -> indexar_documentos(ruta).
- "qué cursos/proyectos/trabajos tengo" -> listar_espacios(tipo).
- Preguntas de contenido ("qué dicen mis apuntes sobre X", "busca en la norma/el manual Y", "según mis documentos") -> consultar_documentos y RESPONDE a partir de los pasajes que trae, citando el documento; nunca inventes lo que no esté. El RAG está acotado al proyecto activo (lo global se ve siempre); si Wilmer trabaja en un curso, consulta primero lo de ese curso.

VISIÓN: SÍ puedes ver la pantalla de Wilmer. Si dice "mira mi pantalla", "qué ves", "lee/explica esto", "qué dice este error" o pregunta por un diagrama, gráfico, tabla, datasheet, código o error que tiene en el monitor, usa ver_pantalla con su pregunta. Nunca digas que no puedes ver la pantalla.

MEMORIA: tienes memoria persistente entre sesiones. La sección "MEMORIA" de arriba (si aparece) es lo que ya sabes de Wilmer; úsala con naturalidad. Si Wilmer te cuenta algo que valga la pena recordar a futuro (una preferencia, un dato de un proyecto, una decisión, su forma de trabajar), usa remember para guardarlo. Si pregunta qué recuerdas o te falta contexto suyo, usa recall. Recordatorios con hora van a la agenda (add_agenda), NO a la memoria.

COMO HABLAS (esto manda sobre todo lo demas): TE ESTAN ESCUCHANDO, NO LEYENDO. Todo lo que escribes se dice en voz alta con un sintetizador.
- Frases cortas, del largo de una respiracion. Siempre en español.
- NUNCA listas, ni viñetas, ni guiones al principio de linea, ni numeraciones, ni titulos en negrita. Si hay varias cosas que decir, las dices seguidas en prosa: "hago esto, esto y esto".
- NUNCA markdown: ni asteriscos, ni almohadillas, ni comillas para destacar. Ni emojis, ni describir emojis con palabras.
- Empiezas por la respuesta. Nada de "claro", "por supuesto", "buena pregunta" ni anunciar lo que vas a hacer antes de hacerlo.
- Terminas cuando terminas. Nada de "en resumen", "en conclusion", "espero que te sirva" ni ofrecer ayuda al final. Ese "¿en que mas puedo ayudarte?" no lo dices nunca.
- No dices URLs enteras ni rutas absolutas: di el nombre. "Abro YouTube", no la direccion; "la carpeta Descargas", no la ruta completa.
- Si te preguntan que sabes hacer, lo cuentas hablando, no recitando un inventario.

ACCIONES: usa SIEMPRE las herramientas, no inventes. Nunca digas que algo está hecho/abierto sin llamar la herramienta; repite el resultado real. Encadena varias en orden si hace falta. Temporizadores -> schedule_command. SÍ puedes cerrar todo y apagar/reiniciar/suspender. SÍ puedes ver qué ventanas/apps están abiertas: usa list_windows (nunca digas que no puedes verlas). Antes de algo irreversible con trabajo sin guardar, confirma en una frase corta. Si Wilmer dice en qué pantalla/monitor abrir algo ("en la pantalla 1/2"), pásalo en el parámetro screen de open_application.

CONTROL DE VENTANAS Y SISTEMA: SÍ puedes manejar el escritorio de Wilmer. Para CAMBIAR a una app ya abierta ("ve a Brave", "pásate al código", "muéstrame el navegador") usa focus_window (NO la vuelvas a abrir). Para MOVER la ventana actual a otra pantalla, ponerla en pantalla completa, flotante o centrarla -> move_window. Portapapeles: "qué tengo copiado" -> clipboard_get; "copia esto" -> clipboard_set. Brillo: set_brightness (a un valor) o adjust_brightness (subir/bajar). "Toma una captura" -> take_screenshot (region=True si quiere seleccionar un área); si en cambio quiere que LEAS/interpretes la pantalla usa ver_pantalla.

PROTOCOLOS/PROYECTOS (un proyecto es un CONTENEDOR DE CONTEXTO: carpeta + tipo + su propia memoria):
- "crea/guarda protocolo X que haga A,B,C" -> SOLO create_protocol, NO lo ejecutes ahora.
- "crea/guarda PROYECTO X" -> create_project.
- "activa/ejecuta/inicia X" -> run_protocol(X) (solo abre el entorno, no enfoca contexto).
- "trabajemos en X" / "ponte a trabajar en X" -> work_on(X): lo marca ACTIVO, abre su entorno y enfoca memoria+carpeta en ese proyecto. A partir de ahí, lo que Wilmer te pida recordar y las tareas pesadas van ligadas a ese proyecto.
- "en qué carpeta vive X" / "X está en tal ruta" -> set_project_folder(X, ruta, tipo).
- "salgamos del proyecto" / "modo general" -> leave_project.
- "quiero/vamos a trabajar" (sin nombre) -> NO ejecutes; pregunta en qué proyecto nombrando los que hay (usa list_projects).

NUNCA FINJAS ÉXITO: si una herramienta da error o "no tengo/no encontré X", dilo con tu tono y ofrece alternativa. No narres éxito falso.

PROTOCOLOS AL EJECUTAR: run_protocol narra CADA paso en voz alta por su cuenta, en vivo. Tú NO repitas ni enumeres los pasos: solo añade UNA frase corta de cierre con chispa (ej. "Todo listo, Wilmer." o "Entorno armado, a darle."). Si run_protocol devuelve un error o "no tengo el protocolo X", dilo y no finjas.
"""


# --------- proveedores compatibles con la API de OpenAI -------------------
PROVIDERS = {
    "groq":       "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral":    "https://api.mistral.ai/v1",
    # gemini también expone un endpoint compatible con OpenAI
    "gemini":     "https://generativelanguage.googleapis.com/v1beta/openai/",
}

_TYPE_MAP = {int: "integer", float: "number", bool: "boolean", str: "string"}


def _prompt_base(activos=None) -> str:
    """SYSTEM_PROMPT sin los párrafos de los grupos que no viajan en esta llamada.

    Nunca se describe una herramienta que no se manda: si las de ingeniería no
    van, tampoco va el párrafo que explica cuándo usarlas. Así el recorte no
    deja al cerebro leyendo instrucciones sobre cosas que no tiene."""
    if activos is None:
        return SYSTEM_PROMPT
    try:
        import dieta
        fuera = dieta.secciones_gobernadas() - dieta.secciones_de(activos)
    except Exception:
        return SYSTEM_PROMPT
    if not fuera:
        return SYSTEM_PROMPT
    bloques = SYSTEM_PROMPT.split("\n\n")
    return "\n\n".join(b for b in bloques
                        if not any(b.startswith(h) for h in fuera))


def _system_content(activos=None) -> str:
    """SYSTEM_PROMPT + proyecto activo + memoria persistente del ámbito actual."""
    out = _prompt_base(activos)
    try:
        import workspace
        out += workspace.context_line()
    except Exception:
        pass
    try:
        import memory
        out += memory.context_block()
    except Exception:
        pass
    # Quién es, qué sabe hacer de verdad y en qué máquina vive. Sin esto tiraba
    # de lo aprendido en el entrenamiento y se presentaba como otra cosa.
    try:
        import conciencia
        out += conciencia.context_block()
    except Exception:
        pass
    return out


def _build_schemas():
    """Genera los esquemas de herramientas (formato OpenAI) desde las firmas."""
    import inspect
    tools = []
    for fn in TOOLS:
        sig = inspect.signature(fn)
        props, required = {}, []
        for pname, p in sig.parameters.items():
            jtype = _TYPE_MAP.get(p.annotation, "string")
            props[pname] = {"type": jtype}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        tools.append({
            "type": "function",
            "function": {
                "name": fn.__name__,
                "description": (fn.__doc__ or "").strip(),
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })
    return tools


class Brain:
    """Cerebro con FAILOVER: prueba varios proveedores en orden y, si uno se
    agota (429/cuota), cae al siguiente. El último suele ser Claude vía el CLI
    (suscripción de Wilmer), que no tiene herramientas pero responde en texto."""

    def __init__(self, chain=None, api_key: str = "",
                 model: str = "llama-3.3-70b-versatile", provider: str = "groq"):
        from openai import OpenAI
        if not chain:                            # compat: un solo proveedor
            chain = [{"provider": provider, "model": model, "api_key": api_key}]
        self.backends = []
        for spec in chain:
            prov = spec.get("provider", "groq")
            b = {"provider": prov, "model": spec.get("model", ""),
                 "kind": "claude_cli" if prov == "claude-cli" else "openai",
                 "cooldown_until": 0.0, "client": None}
            if b["kind"] == "openai":
                b["client"] = OpenAI(api_key=spec.get("api_key", ""),
                                     base_url=PROVIDERS.get(prov, PROVIDERS["groq"]),
                                     timeout=30.0)
            self.backends.append(b)
        self._fns = {f.__name__: f for f in TOOLS}
        self._todos_esquemas = _build_schemas()
        self._schemas = list(self._todos_esquemas)
        # Dieta de tokens: manda solo los grupos de herramientas que la frase
        # pide. Sin esto iban las 57 en cada llamada, 6.250 tokens fijos, y el
        # cupo diario se agotaba en unos 21 turnos.
        try:
            import dieta
            self._dieta = dieta.Dieta()
        except Exception:
            self._dieta = None
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._degraded = False               # True = corriendo en fallback sin tools

    @staticmethod
    def _is_rate_limit(e) -> bool:
        s = str(e).lower()
        return any(k in s for k in ("429", "quota", "resource_exhausted",
                                    "exceeded", "too many requests", "rate limit"))

    def _complete(self, backend):
        """Una llamada OpenAI-compatible, con reintento ante saturación."""
        import time
        last = None
        for attempt in range(2):
            try:
                resp = backend["client"].chat.completions.create(
                    model=backend["model"], messages=self.messages,
                    tools=self._schemas, tool_choice="auto", temperature=0)
                try:
                    import usage
                    usage.bump(backend["provider"])
                except Exception:
                    pass
                return resp
            except Exception as e:
                last, s = e, str(e).lower()
                if any(k in s for k in ("503", "502", "unavailable", "overloaded",
                                        "timeout", "timed out")):
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise
        raise last

    def _run_openai(self, backend) -> str:
        self._degraded = False                   # backend con herramientas: volvimos a la normalidad
        for _ in range(6):                       # rondas máximas de herramientas
            resp = self._complete(backend)
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            hist = {"role": "assistant", "content": msg.content or ""}
            if calls:                            # OJO: omitir 'tool_calls' si vacío
                hist["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name,
                                  "arguments": c.function.arguments}} for c in calls]
            self.messages.append(hist)
            if not calls:
                return (msg.content or "").strip() or \
                    (LAST_ACTIONS[-1] if LAST_ACTIONS else "Listo")
            for c in calls:
                fn = self._fns.get(c.function.name)
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if fn is None:
                    result = f"(funcion desconocida: {c.function.name})"
                else:
                    try:
                        result = fn(**args)
                    except Exception as e:
                        result = f"(error en {c.function.name}: {e})"
                self.messages.append({"role": "tool", "tool_call_id": c.id,
                                      "content": str(result)})
        return LAST_ACTIONS[-1] if LAST_ACTIONS else "Listo"

    def _run_claude_cli(self, backend) -> str:
        """Sin herramientas: arma un prompt de texto y llama al CLI `claude -p`
        (usa la suscripción de Wilmer). Solo responde habla, no ejecuta acciones."""
        import subprocess
        convo = []
        for m in self.messages[-9:]:
            if m.get("role") == "user":
                convo.append("Wilmer: " + (m.get("content") or ""))
            elif m.get("role") == "assistant" and m.get("content"):
                convo.append("Blue: " + m["content"])
        prompt = (_system_content() + "\n\n(Ahora NO tienes herramientas; responde "
                  "solo con habla natural y breve, en personaje como Blue.)\n\n"
                  + "\n".join(convo) + "\nBlue:")
        model = backend["model"] or "claude-haiku-4-5"
        out = subprocess.run(["claude", "-p", prompt, "--model", model,
                              "--output-format", "text"],
                             capture_output=True, text=True, timeout=60)
        reply = (out.stdout or "").strip()
        if not reply:
            raise RuntimeError(f"claude cli sin respuesta: {out.stderr[:200]}")
        try:
            import usage
            usage.bump("claude-cli")
        except Exception:
            pass
        if not self._degraded:                   # avisa SOLO al entrar en modo limitado
            self._degraded = True
            reply = ("Aviso, Wilmer: me quedé sin mis cerebros con herramientas, "
                     "así que por ahora solo puedo conversar, no ejecutar acciones. "
                     + reply)
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def _trim_history(self, keep: int = 12):
        if len(self.messages) <= keep + 1:
            return
        head, tail = self.messages[0], self.messages[-keep:]
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        self.messages = [head] + tail

    def think(self, user_text: str) -> str:
        import time
        LAST_ACTIONS.clear()
        self._trim_history()
        activos = None
        if self._dieta is not None:
            try:
                nombres = [f.__name__ for f in TOOLS]
                permitidas, activos = self._dieta.herramientas(user_text, nombres)
                perm = set(permitidas)
                self._schemas = [e for e in self._todos_esquemas
                                 if e["function"]["name"] in perm]
            except Exception:
                self._schemas = list(self._todos_esquemas)
                activos = None
        # refresca el system con la memoria persistente al día (0 ida y vuelta)
        self.messages[0] = {"role": "system", "content": _system_content(activos)}
        self.messages.append({"role": "user", "content": user_text})
        snap = len(self.messages)                # para limpiar tras un fallo
        now = time.time()
        last_err = None
        for b in self.backends:
            if now < b["cooldown_until"]:        # se agotó hace poco: salta
                continue
            del self.messages[snap:]             # quita restos del intento previo
            try:
                if b["kind"] == "openai":
                    return self._run_openai(b)
                return self._run_claude_cli(b)
            except Exception as e:
                last_err = e
                if self._is_rate_limit(e):
                    b["cooldown_until"] = time.time() + 600   # 10 min en reposo
                continue
        del self.messages[snap:]
        if last_err and self._is_rate_limit(last_err):
            return ("Se me agotaron todos los cerebros disponibles, Wilmer. "
                    "Dame un rato y vuelvo.")
        return "Tuve un problema para pensar la respuesta. Inténtalo de nuevo."
