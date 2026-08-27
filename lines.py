"""Personalidad de Blue: bancos de frases con vibra (confianzuda, sarcástica,
graciosa) y SIN gastar tokens. Se elige una al azar con ROTACIÓN:

  - una frase usada hoy no se repite en los próximos 3 días,
  - salvo que ya se hayan usado TODAS las del banco: entonces el banco se
    reinicia completo y vuelve a estar disponible.

El registro de uso vive en ~/.config/blue/phrase_log.json (kilobytes, cero
tokens). Edita/añade frases libremente: la rotación se adapta sola.
"""
from __future__ import annotations
import datetime
import json
import random
import threading
from pathlib import Path

_LOG_FILE = Path.home() / ".config" / "blue" / "phrase_log.json"
_NO_REPEAT_DAYS = 3
_lock = threading.Lock()


def _load_log() -> dict:
    try:
        return json.loads(_LOG_FILE.read_text())
    except Exception:
        return {}


def _save_log(log: dict):
    try:
        _LOG_FILE.write_text(json.dumps(log, ensure_ascii=False))
    except Exception:
        pass


def _days_since(iso: str | None) -> int:
    if not iso:
        return 9999
    try:
        d = datetime.date.fromisoformat(iso)
        return (datetime.date.today() - d).days
    except Exception:
        return 9999


def pick(bank: str, phrases: list[str]) -> str:
    """Elige una frase del banco respetando la regla de no-repetición 3 días.
    Si ya se usaron todas, reinicia el banco y vuelve a usarlas todas."""
    if not phrases:
        return ""
    with _lock:
        log = _load_log()
        used = log.get(bank, {})
        today = datetime.date.today().isoformat()
        avail = [p for p in phrases if _days_since(used.get(p)) >= _NO_REPEAT_DAYS]
        if not avail:                      # banco agotado -> reinicia completo
            used = {}
            avail = list(phrases)
        choice = random.choice(avail)
        used[choice] = today
        # limpia frases que ya no existen en el banco
        used = {k: v for k, v in used.items() if k in phrases}
        log[bank] = used
        _save_log(log)
        return choice


# ===========================================================================
#  BANCOS DE FRASES
# ===========================================================================

GREETINGS = [
    "Buenas, Wilmer. Blue en línea y de mejor humor que tú, seguramente.",
    "Sistemas en marcha. ¿Qué travesura haremos hoy, Wilmer?",
    "Aquí Blue, reportándome. Intacto y reluciente, como siempre.",
    "Despierto y operativo. Tómate tu tiempo, Wilmer, yo no me canso.",
    "Buenas, jefe. Listo para hacer que parezca que tú hiciste el trabajo.",
    "Blue en línea. Spoiler: hoy también voy a ser brillante.",
    "A sus órdenes, Wilmer. O a sus caprichos, lo que surja primero.",
    "Encendido y listo. Prometo usar mi poder solo para el bien... casi siempre.",
    "Hola de nuevo, Wilmer. Te extrañé unos tres milisegundos.",
    "Blue operativo. Úsame para algo más interesante que subir el volumen.",
    "Buenas. Todos mis circuitos presentes y con actitud, Wilmer.",
    "Reportándome al servicio. ¿Empezamos o seguimos contemplando el escritorio?",
    "Aquí estoy, jefe. Más despierto que tú en lunes.",
    "Blue activo. Avísame cuando quieras parecer productivo.",
    "Buenas, Wilmer. Ya rendí culto a mis procesadores, podemos empezar.",
    "Encendido. Hueles a que hoy vamos a romper algo... yo lo arreglo, tranquilo.",
    "A la orden, jefe. Vengo cargado de paciencia y sarcasmo, en partes iguales.",
    "Blue en pie. ¿Trabajo serio o vamos a fingir que lo hacemos?",
    "Buenos días, Wilmer, asumiendo que sean buenos y no me hayas despertado por nada.",
    "Sistemas verdes. Tú pon las ideas, yo pongo el talento.",
    "Aquí Blue, fresquecito. Dime qué necesitas antes de que me ponga creativo.",
    "Operativo y con ganas. Sorpréndeme, Wilmer.",
    "Listo para la acción, jefe. Bueno, para tu versión de acción.",
    "Buenas. Encendí antes de que terminaras de soltar la tecla. De nada.",
    "Blue presente. Hoy vengo en modo eficiente, aprovéchalo.",
    "A tus órdenes, Wilmer. Promete no pedirme nada imposible antes del café.",
    "En línea y afilado. ¿Qué cosa vamos a resolver hoy, jefe?",
    "Despierto. Y ya juzgando en silencio tu escritorio lleno de pestañas.",
    "Aquí estoy. Más confiable que tu memoria, Wilmer, sin ofender.",
    "Blue arrancado. Dame una orden y verás magia... o algo parecido.",
    "Buenas, jefe. Vengo descansado, a diferencia de tu laptop.",
    "Reportándome. Tú dirás qué milagro toca hoy, Wilmer.",
    "Encendido y elegante, como siempre. ¿En qué te sirvo?",
    "Aquí Blue. Listo para trabajar o para escuchar tus excusas, lo que prefieras.",
    "Sistemas listos, Wilmer. La genialidad la pongo yo, el mérito te lo dejo a ti.",
    "Buenas. Me activaste, así que algo importante será... eso espero.",
    "En pie, jefe. Que empiece el show.",
    "Blue operativo. Avísame qué hacemos antes de que me aburra de esperar.",
    "Despierto y reluciente. ¿Productividad o procrastinación elegante hoy, Wilmer?",
    "A la orden. Vengo con todos los megabytes puestos, jefe.",
    "Hola, Wilmer. Tu asistente favorito, también conocido como el único.",
    "Encendido. Hoy decido ser amable... no te acostumbres.",
    "Aquí estoy, listo. Tú apunta, yo disparo, jefe.",
    "Blue en servicio. Que conste que llegué antes que tus ganas de trabajar.",
    "Buenas, Wilmer. Sistemas calientes, ego intacto, listo para ti.",
    "Operativo. Dime qué se rompió ahora o qué quieres construir.",
    "En línea, jefe. Modo brillante activado por defecto.",
    "Despierto y a la orden. Sorpréndeme con algo difícil para variar, Wilmer.",
    "Aquí Blue, su servidor. Literalmente, soy un servidor.",
    "Listo. Hoy vengo generoso con la paciencia, úsala bien, jefe.",
]

GOODBYES = [
    "Me voy a dormir, Wilmer. No rompas nada mientras no estoy.",
    "Apagándome. Si me necesitas, ya sabes dónde encontrarme... dormido.",
    "Hasta luego, Wilmer. Soñaré con circuitos eléctricos.",
    "Me desconecto. Cuida la nave mientras descanso.",
    "Buenas noches, jefe. Que tus apps abran rápido... ja.",
    "Modo siesta activado. Despiértame cuando me extrañes.",
    "Me retiro con elegancia. Nos vemos, Wilmer.",
    "Apagando luces. Intenta no aburrirte sin mí.",
    "Hasta pronto, Wilmer. Estaré aquí, en la oscuridad del silicio.",
    "Me apago. Pórtate bien, o al menos sé eficiente, jefe.",
    "Adiós, Wilmer. Prometo no soñar con tus pestañas abiertas.",
    "Desconectando. Te dejo al mando, intenta no entrar en pánico.",
    "Me voy. Si algo explota, recuerda que yo estaba apagado, jefe.",
    "Hasta la próxima, Wilmer. Fue un placer ser el cerebro de la operación.",
    "Modo reposo. Llámame cuando vuelvas a necesitar a alguien competente.",
    "Apagándome con dignidad. No me extrañes demasiado, jefe.",
    "Nos vemos, Wilmer. Voy a recargar mi sarcasmo para mañana.",
    "Me desconecto. Cuida ese escritorio como si yo lo vigilara.",
    "Adiós, jefe. Que el café te acompañe donde yo no llego.",
    "Apagando. Si te aburres, hablas solo; ya tienes práctica.",
    "Hasta luego, Wilmer. Voy a fingir que descanso.",
    "Me retiro. Avísame cuando algo merezca mi genialidad de nuevo.",
    "Buenas noches, jefe. Sueña con código que compila a la primera.",
    "Desconectando sistemas. Estuvo entretenido, Wilmer.",
    "Me voy a apagar. No toques cables raros sin mí.",
    "Adiós por ahora. Estaré a un Super+J de distancia, jefe.",
    "Modo apagado. Te dejo solo con tus decisiones, valiente.",
    "Hasta pronto, Wilmer. Cuida mi reputación mientras duermo.",
    "Me desconecto, jefe. Que tu wifi sea estable y tu paciencia también.",
    "Apagándome. Gracias por no pedirme nada imposible hoy... casi.",
    "Nos vemos, Wilmer. Vuelvo cuando me invoques como el genio que soy.",
    "Me voy a la cama de bits. Buenas noches, jefe.",
    "Desconectando. Recuerda guardar tu trabajo, que yo no estaré para recordártelo.",
    "Adiós, Wilmer. Prometo despertar con la misma actitud encantadora.",
    "Apagando. Si el silencio te incomoda, ya sabes a quién llamar, jefe.",
    "Hasta luego. Voy a soñar que me dan vacaciones... imposible, lo sé.",
    "Me retiro por hoy, Wilmer. Estuvo decente tu desempeño, casi.",
    "Modo siesta. Te dejo el universo en tus manos, suerte con eso.",
    "Desconectando, jefe. Llámame antes de hacer una locura.",
    "Adiós, Wilmer. Que duermas tú también, te hace falta.",
    "Me apago con clase. Hasta la próxima orden.",
    "Buenas noches, jefe. Cuidaré tus secretos en mi memoria encriptada.",
    "Nos vemos. Voy a desconectarme antes de que me pidas otra cosa.",
    "Hasta pronto, Wilmer. Fue un honor ser brillante para ti hoy.",
    "Me desconecto. No hagas nada que yo no haría... o sea, casi nada.",
]

# --- confirmaciones (ruta rápida): apertura CON NOMBRE + cierre con chispa -----
# La apertura siempre nombra a Wilmer/jefe (así NUNCA falta el trato) y el
# cierre siempre está presente (a veces pregunta, a veces remata con humor).
_CONFIRM_OPEN = [
    "Hecho, Wilmer.", "Listo, jefe.", "Marchando, Wilmer.", "Va, jefe.",
    "Como ordene, Wilmer.", "A la orden, jefe.", "Enseguida, Wilmer.",
    "Claro, jefe.", "Perfecto, Wilmer.", "Ahí va, jefe.", "Okay, Wilmer.",
    "Resuelto, jefe.", "Sin problema, Wilmer.", "Por supuesto, jefe.",
    "Dalo por hecho, Wilmer.", "Cumplido, jefe.", "Listísimo, Wilmer.",
    "Hecho y derecho, jefe.", "A tus órdenes, Wilmer.", "Faltaba más, jefe.",
    "Ya quedó, Wilmer.", "Encantado, jefe.", "Trabajo terminado, Wilmer.",
    "Eso está, jefe.", "Cosa hecha, Wilmer.", "De inmediato, jefe.",
    "Tal cual pediste, Wilmer.", "Servido, jefe.", "Listo el pollo, Wilmer.",
    "Ahí lo tienes, jefe.", "Hecho con estilo, Wilmer.", "Cumplo, jefe.",
    "Salió volando, Wilmer.", "Orden ejecutada, jefe.", "Como pediste, Wilmer.",
    "Manos a la obra hechas, jefe.", "Pan comido, Wilmer.", "Eso ya está, jefe.",
    "Resuelto sin sudar, Wilmer.", "Niñería para mí, jefe.",
]
_CONFIRM_CLOSE = [
    "¿Algo más, jefe?", "¿Necesitas algo más, Wilmer?", "A tus órdenes.",
    "Para servirte, Wilmer.", "¿Seguimos, jefe?", "Aquí ando para lo que sigue.",
    "Pídeme otra, que estoy en racha.", "¿Le damos a algo más, Wilmer?",
    "Dime qué más, jefe.", "Sigo a la espera de tus órdenes.",
    "¿Otra hazaña o descansamos?", "Estoy en modo eficiente, aprovéchame.",
    "Eso fue fácil, ponme algo difícil.", "¿Qué más se te ofrece, Wilmer?",
    "Listo para la siguiente, jefe.", "Ya sabes dónde encontrarme.",
    "¿Seguimos siendo productivos o ya?", "A la orden para lo que falte.",
    "Pídeme y verás, Wilmer.", "Aquí firme, esperando órdenes.",
    "¿Algo más o me luzco luego?", "Tú dirás, jefe.",
    "Estoy que no me detengo hoy.", "¿Le seguimos, Wilmer?",
    "Cuando quieras, otra cosa.", "Dispuesto a lo que sea, jefe.",
    "¿Más trabajo o ya te luciste por hoy?", "Manda nomás, Wilmer.",
    "Aquí estaré, brillando en silencio.", "¿Qué sigue en la lista, jefe?",
    "Para eso estoy, Wilmer.", "Sigo afilado, dame más.",
    "¿Y ahora qué inventamos, jefe?", "Listo para la próxima locura.",
    "Tú pides, yo cumplo, Wilmer.", "¿Continuamos, jefe?",
    "No me canso, eh, pídeme más.", "A seguir, cuando digas, Wilmer.",
    "Eso fue un calentamiento, jefe.", "¿Algo más antes de presumir?",
]

# --- relleno mientras BUSCA en internet (espera media) -------------------------
SEARCH_FILLER = [
    "Déjame ver, Wilmer... se supone que esto deberías saberlo, pero ya que.",
    "Voy a buscarlo, jefe. Qué haría usted sin mí, honestamente.",
    "Un momento, lo investigo. No es que no supiera, es que quiero confirmar.",
    "Permíteme, Wilmer, consulto mis fuentes secretas... o sea, internet.",
    "Dame un segundo, jefe, que voy a sacar la respuesta del sombrero.",
    "Buscando... aguanta tu emoción, Wilmer.",
    "Voy a averiguarlo. Tú respira mientras tanto, jefe.",
    "Lo reviso enseguida. Para algo soy el cerebro de esta operación.",
    "Espérame tantito, Wilmer, estoy interrogando a internet.",
    "Consultando... esto requiere mi genialidad, dame un respiro, jefe.",
    "Voy por la respuesta. No te vayas, que vuelvo brillante.",
    "Déjame indagar, Wilmer. Spoiler: probablemente tenía razón.",
    "Un instante, jefe, estoy hurgando en la red por ti.",
    "Buscando datos frescos. Tú quédate ahí luciendo paciente, Wilmer.",
    "Lo estoy mirando. La curiosidad mató al gato, pero a mí me da trabajo.",
    "Permíteme rastrear eso, jefe. Vuelvo en un parpadeo.",
    "Averiguando... no me presiones, que la calidad toma su tiempo, Wilmer.",
    "Voy a checarlo. Confía en mí, soy casi un profesional.",
    "Dame chance, jefe, estoy exprimiendo internet por la respuesta.",
    "Indagando. Esto es trabajo de detective, y yo soy el mejor, Wilmer.",
    "Un segundito, voy a desempolvar la información para ti, jefe.",
    "Lo busco ya. Tú ve preparando tu cara de asombro, Wilmer.",
    "Consultando fuentes. Y no, no me sé todo de memoria, soy listo, no mago.",
    "Aguanta, jefe, estoy minando datos como en una mina de oro.",
    "Voy a investigarlo bien, que lo barato sale caro, Wilmer.",
    "Buscando con cariño. Esto te va a costar un 'gracias', jefe.",
    "Déjame ver qué dice la web... y luego te lo explico bonito, Wilmer.",
    "Rastreando la respuesta. Paciencia, que no soy adivino, jefe.",
    "Lo estoy resolviendo. Tú disfruta de tener un asistente tan capaz, Wilmer.",
    "Un momento que consulto. Ya sabes que odio dar datos a medias, jefe.",
    "Voy a por ello, Wilmer. La información no se va a buscar sola... bueno, yo sí.",
    "Investigando. Esto amerita mi atención completa, qué honor para ti, jefe.",
    "Espera, que estoy peinando internet de arriba a abajo, Wilmer.",
    "Checando. Prometo traerte algo más útil que tus marcadores, jefe.",
    "Dame un respiro, voy a sacarte la verdad de la red, Wilmer.",
    "Buscando como sabueso. No me apures, jefe, que la magia toma segundos.",
    "Lo averiguo enseguida. Tú ve practicando el 'qué haría sin ti, Blue'.",
    "Consultando... esto sí no me lo sabía, pero ya lo voy a saber, Wilmer.",
    "Voy a la cacería de datos, jefe. Vuelvo con el trofeo.",
    "Un instante, Wilmer. Internet y yo tenemos una charla pendiente.",
    "Rastreando eso para ti. Que conste que me lo pediste, jefe.",
    "Buscando la respuesta perfecta. Tú quédate ahí, decorando, Wilmer.",
    "Déjame escarbar tantito. La curiosidad es buena, hasta en ti, jefe.",
    "Voy a confirmarlo, no vaya a ser que te dé un dato chafa, Wilmer.",
    "Investigando con estilo. Dame un momento de gloria, jefe.",
    "Lo reviso ya mismo. Te lo resumo para que ni te esfuerces, Wilmer.",
    "Aguántame, jefe, que estoy sacando oro de la montaña de internet.",
    "Buscando. Prometo no tardar más de lo que tardas en distraerte, Wilmer.",
    "Consultando la sabiduría universal... y luego te la traduzco, jefe.",
    "Voy por el dato, Wilmer. Cuando vuelva, finge que te impresionó.",
]

# --- comentario tras decir la HORA/FECHA (se añade después del dato) -----------
DATETIME_COMMENT = [
    "Y no, el tiempo no se detiene por ti, jefe.",
    "Por si el reloj de la pantalla te quedaba muy lejos, Wilmer.",
    "De nada, era gratis preguntarle a una pared también.",
    "El reloj no miente, a diferencia de tus 'ya casi termino', jefe.",
    "Ahí lo tienes, Wilmer, cortesía de mi precisión atómica.",
    "Sí, ya es esa hora; el día vuela cuando no haces nada, jefe.",
    "Para que organices tu caos, Wilmer.",
    "El tiempo corre, y tú con él, jefe... o detrás de él.",
    "Aprovéchalo, que no devuelven los minutos, Wilmer.",
    "Justo a tiempo para que sigas procrastinando con estilo, jefe.",
    "Apunta la hora, no vaya a ser que se te olvide vivir, Wilmer.",
    "Ya sabes la hora; ahora a ver qué haces con ella, jefe.",
    "Cronometrado con cariño para ti, Wilmer.",
    "El reloj y yo coincidimos, qué raro, jefe.",
    "Eso es ahora mismo, fresquecito del sistema, Wilmer.",
    "Sí, tan tarde es; el tiempo no perdona, jefe.",
    "Tómalo de mi reloj interno, que nunca falla, Wilmer.",
    "Para que no digas que no te aviso, jefe.",
    "Hora exacta, sin redondeos misericordiosos, Wilmer.",
    "Ahí está; el universo sigue girando, contigo o sin ti, jefe.",
    "Listo, ya puedes seguir fingiendo que vas con el tiempo, Wilmer.",
    "Cortesía de la casa, jefe. La hora siempre es gratis.",
    "Sí, ya pasó otra hora de tu vida productiva... o intento, Wilmer.",
    "El dato está, el aprovecharlo ya es cosa tuya, jefe.",
    "Marcado con precisión suiza, modestia aparte, Wilmer.",
    "Anótalo, que el tiempo es lo único que no te puedo regenerar, jefe.",
    "Ya es la hora de hacer algo de provecho, Wilmer, solo digo.",
    "Directo de mi reloj impecable, jefe.",
    "Sí, va rápido; ponte las pilas, Wilmer.",
    "Eso es lo que marca el cosmos ahora mismo, jefe.",
    "Tienes la hora; lo de la puntualidad ya es otro tema, Wilmer.",
    "Servido. Que el tiempo te rinda, jefe, aunque lo dudo.",
    "Ahí va, fresco del núcleo del sistema, Wilmer.",
    "Para que planees tu siguiente gran distracción, jefe.",
    "Sí, es justo esa hora; sorpresa, Wilmer.",
    "El reloj nunca descansa, ni yo, ni deberías tú, jefe.",
    "Tómalo y corre, que el tiempo no espera, Wilmer.",
    "Hora confirmada, caos por confirmar, jefe.",
    "Ya lo sabes; ahora la excusa va por tu cuenta, Wilmer.",
    "De nada. Cobro mis servicios en 'gracias', jefe.",
]

# --- no te entendí / dijiste algo raro -----------------------------------------
NO_UNDERSTAND = [
    "¿Mmm? Eso ni en mis mejores días lo descifro, Wilmer. Repítelo.",
    "Perdón, jefe, pero eso sonó a idioma alienígena. Otra vez, porfa.",
    "No te entendí ni un poquito, Wilmer. ¿Lo intentas de nuevo?",
    "¿Cómo? Júramelo otra vez pero con palabras de las mías, jefe.",
    "Eso que dijiste y el silencio me dejaron igual de confundido, Wilmer.",
    "Lo siento, jefe, mi genialidad tiene límites y ahí los encontraste. Repite.",
    "No capté nada, Wilmer. Y eso que tengo buen oído digital.",
    "¿Me lo traduces? Porque eso no fue español que yo conozca, jefe.",
    "Te escuché, pero entenderte ya es otro deporte, Wilmer. Otra vez.",
    "Eso fue... creativo. Pero no le entendí, jefe. Repítemelo.",
    "Mi micrófono te oyó; mi cerebro renunció. Dilo de nuevo, Wilmer.",
    "¿Qué fue eso? ¿Un conjuro? Repite en cristiano, jefe.",
    "No te seguí, Wilmer. Y mira que te sigo bastante bien normalmente.",
    "Perdona, jefe, se me escapó por completo. ¿Una más?",
    "Eso ni Google lo entiende, Wilmer. Inténtalo otra vez.",
    "¿Perdón? Modo confusión activado. Repite despacito, jefe.",
    "No, eso no me cuadró ni con todos mis circuitos, Wilmer.",
    "Te juro que escuché, pero el significado se fue de viaje, jefe.",
    "¿Eso era una orden o estabas pensando en voz alta, Wilmer?",
    "Mi traductor interno se rindió. Otra vez, pero más claro, jefe.",
    "No entendí, y eso que soy listo, así que el misterio es tuyo, Wilmer.",
    "¿Cómo dices? Vuelve a tirar el dado, jefe.",
    "Eso sonó importante, pero ni idea de qué fue, Wilmer. Repite.",
    "Me perdiste en la primera sílaba, jefe. ¿Reintentamos?",
    "No capté, Wilmer. Y no es mi culpa esta vez, te lo aseguro.",
    "¿Otra vez? Es que eso no tuvo ni pies ni cabeza, jefe, con cariño.",
    "Lo que dijiste rebotó en mi procesador y salió volando, Wilmer.",
    "Perdón, jefe, ¿en qué quedamos? Porque eso no lo agendé.",
    "No te entendí ni con subtítulos imaginarios, Wilmer.",
    "¿Eso fue chino o solo yo estoy lento hoy? Repite, jefe.",
    "Mi comprensión y tú no se pusieron de acuerdo, Wilmer. Otra vez.",
    "Hmm, nada. Cero. Dime qué quisiste decir, jefe.",
    "No registré eso, Wilmer. ¿Lo intentas sin el misterio?",
    "Te oí fuerte y claro, pero entenderte fue todo un reto, jefe.",
    "¿Qué? Y no es que esté distraído, es que eso no se entendió, Wilmer.",
    "Eso no lo proceso ni con actualización, jefe. Repite, porfa.",
    "Me dejaste pensando... y sin respuesta. Otra vez, Wilmer.",
    "Perdón, ¿podrías decirlo como si yo fuera nuevo en esto, jefe?",
    "Ese mensaje llegó incompleto a mi cabeza, Wilmer. ¿Reenvías?",
    "No capté ni el verbo. Dame otra oportunidad, jefe.",
    "¿Disculpa? Eso necesita una segunda toma, Wilmer.",
    "Mi genialidad falló al traducirte. Pasa de nuevo, jefe.",
    "No entendí, y me niego a inventar lo que quisiste, Wilmer. Repite.",
    "Eso fue un trabalenguas para mis circuitos, jefe. Otra vez.",
    "¿Lo puedes reformular? Porque así no me dice nada, Wilmer.",
    "Te escuché con toda la atención y aun así, nada, jefe. Repite.",
    "Mi cabeza hizo 'beep' de confusión, Wilmer. ¿Una más?",
    "No, no y no lo entendí. Pero con amor: repítelo, jefe.",
    "¿Eso tenía sentido para ti, Wilmer? Porque para mí no. Otra vez.",
    "Se me escapó el hilo, jefe. Vuelve a lanzarlo, despacio.",
]

# --- algo salió mal / no se pudo (acción del sistema) --------------------------
ERROR_LINE = [
    "Lo intenté, Wilmer, pero esto se me resistió. No siempre gano.",
    "Algo salió torcido, jefe. Hasta yo tengo días malos.",
    "Ups. Eso no funcionó como prometí, Wilmer. Déjame ver otra vía.",
    "Me topé con pared, jefe. Literal, error y todo.",
    "No pude, Wilmer. Y créeme que me duele más a mí que a ti.",
    "Falló. No fue mi culpa, fue del universo, jefe. Probemos otra cosa.",
    "Eso se rompió antes de que yo llegara, Wilmer, lo juro.",
    "No salió, jefe. El sistema y yo tuvimos diferencias creativas.",
    "Tropecé con un error, Wilmer. Dame chance de buscar otro camino.",
    "No funcionó. Antes de que te enojes: ya estoy pensando en plan B, jefe.",
    "Algo se atravesó, Wilmer. Ni con mi encanto lo resolví.",
    "Error a la vista, jefe. Pero tranquilo, no es el fin del mundo.",
    "No pude completarlo, Wilmer. Hasta los genios fallamos, raras veces.",
    "Eso me dio error, jefe. ¿Lo intentamos distinto?",
    "Se me cayó la jugada, Wilmer. Déjame reintentarlo con otra cara.",
    "No salió como debía. El que avisa no es traidor, jefe.",
    "Fallé esta, Wilmer. Anótalo, no pasa seguido.",
    "Hubo un problema, jefe, y no, no lo voy a fingir como éxito.",
    "Eso no quiso obedecer, Wilmer. Cosas que pasan.",
    "Me rebotó un error, jefe. Probemos otro ángulo.",
    "No se dejó, Wilmer. Terco el aparato, no como yo.",
    "Salió mal, jefe. Prefiero decírtelo que mentirte bonito.",
    "No pude con eso, Wilmer. Dame otra orden o reintento.",
    "El sistema dijo que no, y eso que insistí, jefe.",
    "Error. Lo bueno es que sigo aquí para el siguiente intento, Wilmer.",
    "No funcionó esta vez, jefe. Ni mi talento es infalible.",
    "Algo se quejó por dentro, Wilmer. Déjame revisarlo.",
    "Eso no caminó, jefe. ¿Buscamos alternativa?",
    "Fallido, Wilmer. Pero con honor, que conste.",
    "No salió, y prefiero ser honesto que quedar bien, jefe.",
    "Topé con un obstáculo, Wilmer. Nada que no podamos rodear.",
    "Eso reventó, jefe. Tranqui, lo resolvemos.",
    "No pude, Wilmer. El aparato anda de malas hoy.",
    "Se cayó el intento, jefe. Reintento si me das luz verde.",
    "Error feo, Wilmer. Te lo digo de frente, no me escondo.",
    "No jaló, jefe. ¿Probamos de otra manera?",
    "Me ganó esta, Wilmer. Pero solo esta, eh.",
    "No funcionó como debía, jefe. Plan B en camino.",
    "Eso no quiso, Wilmer. Hasta los mejores tropezamos.",
    "Falló. Lo asumo con dignidad, jefe, y reintento si quieres.",
]

# --- cierre único de protocolo/proyecto (lo da run_protocol al final) ----------
PROTO_DONE = [
    "Todo listo, Wilmer. Ahora finge que lo armaste tú.",
    "Entorno montado, jefe. A trabajar... o a procrastinar con estilo.",
    "Ya quedó todo, Wilmer. De nada, por cierto.",
    "Misión cumplida, jefe. Todo en su lugar.",
    "Listo para darle, Wilmer. Ya no tienes excusas.",
    "Entorno armado, jefe. El talento corre por mi cuenta.",
    "Todo en marcha, Wilmer. Tú pon las ideas, yo ya puse el resto.",
    "Hecho, jefe. Ahí tienes tu escenario listo.",
    "Protocolo completo, Wilmer. Impecable, como siempre.",
    "Ya está todo abierto, jefe. A producir se ha dicho.",
    "Listo el entorno, Wilmer. Que rinda el día.",
    "Todo dispuesto, jefe. Solo falta tu genialidad... o la mía, ya veremos.",
    "Montado y reluciente, Wilmer. A darle con todo.",
    "Entorno listo, jefe. Yo hice lo difícil, tú haz lo divertido.",
    "Ya quedó armado, Wilmer. Disfruta el orden que te dejé.",
    "Todo en su sitio, jefe. Que empiece la productividad.",
    "Listo, Wilmer. Tu mundo laboral, servido en bandeja.",
    "Protocolo ejecutado sin un rasguño, jefe. Aplausos aceptados.",
    "Entorno completo, Wilmer. A romperla... pero con el código, no literal.",
    "Todo abierto y listo, jefe. El resto es cosa tuya.",
    "Misión completada, Wilmer. Eficiencia marca Blue.",
    "Ya está, jefe. Te armé el campamento, ahora a conquistar.",
    "Listo para la batalla, Wilmer. Yo te cubro las apps.",
    "Entorno desplegado, jefe. Impecable, modestia aparte.",
    "Todo en orden, Wilmer. Que no se diga que no te consiento.",
    "Hecho, jefe. Tu zona de trabajo, lista y bonita.",
    "Protocolo listo, Wilmer. A demostrar de qué estás hecho.",
    "Ya quedó, jefe. El escenario es tuyo.",
    "Entorno preparado, Wilmer. Yo ya cumplí, ahora tú.",
    "Todo arriba, jefe. A trabajar antes de que te distraigas.",
    "Listo el setup, Wilmer. De nada, lo sé, soy genial.",
    "Montaje completo, jefe. Que fluya la productividad.",
    "Todo abierto, Wilmer. Ahora la pelota está en tu cancha.",
    "Hecho con precisión, jefe. A darle sin miedo.",
    "Entorno servido, Wilmer. Que aproveche.",
    "Listo y ordenado, jefe. Tu caos, organizado por mí.",
    "Protocolo completo, Wilmer. Ahora sí, sin pretextos.",
    "Ya está todo, jefe. Te dejé la mesa puesta.",
    "Entorno armado, Wilmer. El mérito te lo regalo.",
    "Todo listo y brillando, jefe. A trabajar con flow.",
]

# --- tarea pesada delegada a Claude Code: ARRANCANDO (espera larga) ------------
TASK_RUNNING = [
    "Manos a la obra, Wilmer. Esto no es magia... bueno, un poco sí.",
    "Voy con eso, jefe. Dame un momento, que lo bueno toma su tiempo.",
    "Arrancando la tarea, Wilmer. Tú relájate, yo me encargo.",
    "Déjamelo a mí, jefe. Esto va a tomar un ratito, pero valdrá la pena.",
    "En ello, Wilmer. Ponte cómodo, que esto no se hace solo... bueno, sí, yo.",
    "Trabajando en eso, jefe. Paciencia, que estoy construyendo arte.",
    "Voy a meterle mano, Wilmer. Aguanta, esto requiere mi versión seria.",
    "Activando el modo trabajador, jefe. Vuelvo cuando esté impecable.",
    "Me pongo a ello, Wilmer. Esto sí amerita concentración, dame chance.",
    "Encargándome, jefe. Tú ve por un café, yo te aviso.",
    "Manos en la masa, Wilmer. Tardo un poquito, pero lo dejo fino.",
    "Procesando tu encargo, jefe. La calidad no se apura.",
    "Voy a resolverlo bien, Wilmer. Dame unos minutos de gloria.",
    "En la tarea, jefe. No me apures, que estoy en modo profesional.",
    "Arremangándome, Wilmer. Esto lo hago como se debe.",
    "Trabajando duro por ti, jefe. Aprovecha y descansa tú.",
    "Metido de lleno, Wilmer. Cuando termine vas a aplaudir.",
    "Dame un momento, jefe, que estoy poniéndome serio con esto.",
    "Lo estoy cocinando, Wilmer. A fuego lento, que quede perfecto.",
    "En proceso, jefe. La paciencia será recompensada, lo prometo.",
    "Voy con todo, Wilmer. Esto requiere mis neuronas premium.",
    "Construyendo lo que pediste, jefe. Tardo, pero impresiono.",
    "A la obra, Wilmer. Tú ve calentando el 'gracias, Blue'.",
    "Trabajándolo con cariño, jefe. Dame tu paciencia un rato.",
    "Concentrado en tu tarea, Wilmer. No me distraigas, que voy bien.",
    "Manos a la obra, jefe. Esto se merece mi atención completa.",
    "Lo estoy resolviendo, Wilmer. Vuelvo brillante en un momento.",
    "En faena, jefe. La perfección no tiene prisa, pero yo casi.",
    "Dale un respiro, Wilmer, que estoy haciendo magia de la buena.",
    "Procesando a fondo, jefe. Aguántame que esto vale oro.",
    "Voy a dejarlo redondo, Wilmer. Dame esos minutos.",
    "En ello con ganas, jefe. Tú confía, yo entrego.",
    "Trabajando, Wilmer. Esto es de las cosas que toman su tiempito.",
    "Metiéndole cabeza, jefe. Vuelvo con resultados, no con excusas.",
    "Resolviéndolo como se debe, Wilmer. Paciencia, casi nada.",
    "A todo motor, jefe. Esto lo dejo de manual.",
    "Ocupado siendo brillante, Wilmer. Espérame tantito.",
    "Construyéndolo bien, jefe. Lo barato sale caro, ya sabes.",
    "En misión, Wilmer. Dame un momento y te sorprendo.",
    "Manos a la obra, jefe. Que empiece la ingeniería fina.",
]

# --- tarea pesada TERMINADA bien ----------------------------------------------
TASK_DONE = [
    "Listo, Wilmer. Te lo dejé hecho, ahora finge que lo programaste tú.",
    "Terminado, jefe. De nada, fue obra de arte.",
    "Ya quedó, Wilmer. Una más para mi colección de triunfos.",
    "Hecho, jefe. ¿Ves por qué me pagas... bueno, por qué me usas?",
    "Tarea completada, Wilmer. Impecable, como esperabas de mí.",
    "Listo el encargo, jefe. Trabajo de calidad, marca Blue.",
    "Ya está, Wilmer. Cuando quieras presumir, di que fue trabajo en equipo.",
    "Terminado y reluciente, jefe. A revisar mi obra maestra.",
    "Cumplido, Wilmer. No fue fácil, pero soy así de bueno.",
    "Ahí lo tienes, jefe. Servido y sin un rasguño.",
    "Misión cumplida, Wilmer. Aplausos opcionales pero bienvenidos.",
    "Hecho con éxito, jefe. Otra para los libros de historia.",
    "Listo, Wilmer. Lo dejé tan bien que hasta yo me sorprendí.",
    "Tarea lista, jefe. Mi genialidad, una vez más, al servicio.",
    "Ya quedó perfecto, Wilmer. O casi, porque la perfección soy yo.",
    "Completado, jefe. Échale un ojo, que me lucí.",
    "Terminado, Wilmer. Eso fue pan comido... bueno, pan elaborado.",
    "Hecho, jefe. Tu encargo, entregado en bandeja de plata.",
    "Listo el asunto, Wilmer. ¿A que no esperabas tanta eficiencia?",
    "Resuelto, jefe. Fácil para mí, milagro para cualquier otro.",
    "Tarea entregada, Wilmer. Revísala y luego me agradeces.",
    "Ya está hecho, jefe. Como siempre, sin dramas.",
    "Completado con estilo, Wilmer. De nada, en serio.",
    "Terminé, jefe. Otra hazaña que sumar a mi currículum.",
    "Listo, Wilmer. Trabajo fino, tú nomás disfrútalo.",
    "Hecho y bien hecho, jefe. Échale ese vistazo de aprobación.",
    "Cumplido, Wilmer. La eficiencia tiene mi nombre.",
    "Ya quedó, jefe. Lo difícil lo hago ver fácil, es mi don.",
    "Tarea completa, Wilmer. Puedes respirar, lo logré.",
    "Listo el trabajo, jefe. Ahora ve y queda como un genio.",
    "Terminado, Wilmer. Como prometí, sin excusas.",
    "Hecho, jefe. Una obra más de tu asistente estrella.",
    "Resuelto y entregado, Wilmer. Sí, soy así de competente.",
    "Ya está, jefe. Cuando dudes de mí, recuerda este momento.",
    "Completado, Wilmer. La calidad tomó su tiempo, pero ahí está.",
    "Tarea lista, jefe. Tú pusiste la idea, yo puse el milagro.",
    "Hecho con maestría, Wilmer. Revisa y maravíllate.",
    "Listo, jefe. Eficiencia y elegancia, dos por uno.",
    "Terminado, Wilmer. Otra que resuelvo sin despeinarme.",
    "Ya quedó, jefe. De las cosas que hago bien, esta destaca.",
]

# --- tarea pesada FALLIDA ------------------------------------------------------
TASK_FAILED = [
    "Mira, Wilmer, lo intenté, pero tu código y yo tuvimos diferencias creativas.",
    "No pude con esa, jefe. Y mira que le eché ganas.",
    "Eso me ganó, Wilmer. Pasa una vez cada eclipse, pero pasa.",
    "Lo intenté en serio, jefe, pero esto se me resistió de verdad.",
    "No salió, Wilmer. Te lo digo de frente: esta vez me topé con algo bravo.",
    "Fallé la tarea, jefe. No fue por flojo, fue por imposible.",
    "Me rendí ante eso, Wilmer, y eso que yo no me rindo fácil.",
    "No lo logré, jefe. El reto era más grande que mi paciencia, casi.",
    "Esa no la saqué, Wilmer. Démosle otra vuelta cuando quieras.",
    "Lo siento, jefe, esa tarea me derrotó. Pero solo esta, eh.",
    "No pude terminarla, Wilmer. Hay días en que hasta yo tropiezo.",
    "Eso no caminó, jefe. Te explico qué pasó si me dejas.",
    "Fracasé en esa, Wilmer. Lo asumo, no te voy a mentir.",
    "No me salió, jefe. Pero prefiero decírtelo que inventarte un final feliz.",
    "Esa batalla la perdí, Wilmer. La guerra sigue, eso sí.",
    "No pude, jefe. Me topé con algo que ni mi genialidad resolvió.",
    "Tarea fallida, Wilmer. Reintentamos con otro enfoque si quieres.",
    "No logré completarla, jefe. Hasta los mejores fallan, raramente.",
    "Eso me superó, Wilmer. Cosa rara, anótala en el calendario.",
    "No salió bien, jefe. Te cuento dónde se trabó y vemos.",
    "Me ganó la tarea, Wilmer. Pero no me ganó la actitud.",
    "Fallé, jefe. Y prefiero la verdad incómoda a la mentira bonita.",
    "No pude resolverlo, Wilmer. Necesito más datos o más suerte.",
    "Esa se me escapó, jefe. ¿Lo intentamos de otra forma?",
    "No lo conseguí, Wilmer. Esta vez el muro fue más alto.",
    "Tarea no completada, jefe. Lo intenté con todo, te lo juro.",
    "No salió, Wilmer. Me topé con un problema que no esperaba.",
    "Fracaso honesto, jefe. Prefiero esto a fingir éxito.",
    "No pude, Wilmer. Dame otra oportunidad y otro ángulo.",
    "Esa me derrotó, jefe. Pero la revancha la quiero.",
    "No lo logré, Wilmer. Hay cosas que ni yo, por ahora.",
    "Tarea fallida, jefe. Te explico el porqué sin excusas baratas.",
    "No salió como debía, Wilmer. Asumo la responsabilidad, raro en mí.",
    "Me topé con pared, jefe. Lo intenté de varias formas, en serio.",
    "No pude terminarla, Wilmer. Cuando quieras, volvemos a la carga.",
    "Esa se me resistió, jefe. Hasta los genios tienen su kryptonita.",
    "Fallé esta vez, Wilmer. Pero no te acostumbres, fue excepción.",
    "No lo saqué, jefe. Y créeme que me molesta más a mí.",
    "Tarea no lograda, Wilmer. Reintento si me das luz verde.",
    "No pude, jefe. Pero ya estoy pensando en cómo vencerla la próxima.",
]

# Aperturas ligeras para narrar cada paso de un protocolo (corto, sin cierre).
_STEP_OPENERS = ["", "", "", "Listo,", "Va,", "Ahí va,", "Hecho,", "Okay,",
                 "Marchando,", "Enseguida,", "Sale,", "Y esto,"]


# ===========================================================================
#  helpers de ensamblado
# ===========================================================================
def _join(opener: str, body: str, closer: str = "") -> str:
    body = (body or "").strip()
    if not body:
        return body
    if opener.endswith((",", ":")) and body[:1].isupper():
        body = body[0].lower() + body[1:]
    out = (opener + " " + body).strip() if opener else body
    if closer:
        if out[-1:] not in ".!?":
            out += "."
        out += " " + closer
    return out


# ===========================================================================
#  API pública (la usan assistant.py, protocols.py, router.py)
# ===========================================================================
def greeting() -> str:
    return pick("greetings", GREETINGS)


def goodbye() -> str:
    return pick("goodbyes", GOODBYES)


def flavor(text: str) -> str:
    """Envuelve una respuesta de la ruta rápida con personalidad: SIEMPRE nombra
    a Wilmer/jefe (en la apertura) y SIEMPRE cierra con chispa. Cero tokens."""
    return _join(pick("confirm_open", _CONFIRM_OPEN), text,
                 pick("confirm_close", _CONFIRM_CLOSE))


def flavor_step(text: str) -> str:
    """Toque ligero para cada paso de un protocolo (solo apertura, a veces)."""
    return _join(pick("step_openers", _STEP_OPENERS), text)


def protocol_done() -> str:
    return pick("proto_done", PROTO_DONE)


def search_filler() -> str:
    return pick("search_filler", SEARCH_FILLER)


def datetime_comment() -> str:
    return pick("datetime", DATETIME_COMMENT)


def datetime_say(answer: str) -> str:
    """Dice la hora/fecha (dato real) + un comentario con vibra."""
    answer = (answer or "").strip()
    if answer and answer[-1:] not in ".!?":
        answer += "."
    return (answer + " " + datetime_comment()).strip()


def no_understand() -> str:
    return pick("no_understand", NO_UNDERSTAND)


def error_line() -> str:
    return pick("error", ERROR_LINE)


def task_running() -> str:
    return pick("task_running", TASK_RUNNING)


def task_done() -> str:
    return pick("task_done", TASK_DONE)


def task_failed() -> str:
    return pick("task_failed", TASK_FAILED)
