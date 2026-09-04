"""Assistant: orquesta voz/texto, ruta rapida y cerebro. Thread-safe."""
from __future__ import annotations
import threading

import config as config_mod
import router
import store


# Tope del push-to-talk. Si nadie suelta la tecla en este tiempo se cierra solo.
PTT_MAX_S = 120.0


class Assistant:
    def __init__(self, cfg: dict | None = None):
        self._pendiente_orfeo = None     # pregunta que se ofreció subir a ORFEO
        self.cfg = cfg or config_mod.load()
        self._lock = threading.Lock()
        self._busy = threading.Lock()      # 1 sola conversación a la vez (mic)
        self._brain = None
        self._pending_task = None          # tarea esperando un 'sí' (borrar/instalar)
        self._modo = None                  # None | "ICARO" | "ORFEO" (ver _modo_intercepta)
        self._modo_hechos = []             # lo pedido y lo respondido dentro del modo
        self._modo_historial = []          # la conversación tal cual, para ORFEO
        # narrador en vivo de protocolos: habla cada paso al ejecutarlo (sin tokens)
        try:
            import protocols
            protocols.set_narrator(self._narrate_step)
        except Exception:
            pass
        # avisos del pomodoro (cambios de fase) -> habla + ventana, sin tokens
        try:
            import pomodoro
            pomodoro.set_announcer(self._pomodoro_say)
        except Exception:
            pass

    # voz activa segun el motor configurado -> (voice_id, engine)
    def _tts(self):
        engine = self.cfg.get("tts", "kokoro")
        if engine == "kokoro":
            return self.cfg.get("kokoro_voice", "ef_dora"), "kokoro"
        if engine == "edge":
            return self.cfg.get("edge_voice", "es-MX-DaliaNeural"), "edge"
        return self.cfg.get("voice", "es_MX-claude-high.onnx"), "piper"

    # ------------------------------------------------ cerebro perezoso
    def brain(self):
        if self._brain is None:
            from brain import Brain
            chain = self.cfg.get("brain")
            if chain:                          # cadena de failover (recomendado)
                self._brain = Brain(chain=chain)
            else:                              # compat: un solo proveedor
                if not self.cfg.get("api_key"):
                    raise RuntimeError("Falta la API key del modelo en config.toml")
                self._brain = Brain(api_key=self.cfg["api_key"],
                                    model=self.cfg["model"],
                                    provider=self.cfg.get("provider", "groq"))
            # Que las consultas pesadas puedan avisar por voz ANTES de empezar.
            # Cambiar de modelo cuesta 15-20 s y quedarse mudo ese rato parece
            # un cuelgue; el brain no sabe con qué voz habla BLUE, así que se
            # le pasa desde aquí.
            import brain as _brainmod
            import voice as _voice

            def _decir(frase, _s=self):
                v, eng = _s._tts()
                try:
                    store.set_status("thinking")
                except Exception:
                    pass
                _voice.speak(frase, v, eng)

            _brainmod.AVISAR = _decir
        return self._brain

    @staticmethod
    def _limpiar_espeak_huerfanos():
        """Borra los libespeak-ng.so temporales que dejó Kokoro en arranques
        anteriores.

        El cargador de espeak extrae su .so a un directorio temporal nuevo cada
        vez que arranca Kokoro y nunca lo limpia: dos por reinicio, 648 KB cada
        uno. En /tmp, que es tmpfs, o sea RAM. No afecta al rendimiento ni a lo
        que Blue sabe hacer —cada proceso mapea solo el suyo— pero si se
        reinicia a menudo va sumando y no se libera hasta reiniciar el equipo.

        Solo se borra lo que NO tiene mapeado ningún proceso vivo. El de este
        arranque, y el de cualquier otro programa que use espeak, se quedan."""
        from pathlib import Path
        en_uso = set()
        for mapa in Path("/proc").glob("[0-9]*/maps"):
            try:
                for linea in mapa.read_text().splitlines():
                    if "libespeak-ng.so" in linea and "/tmp/" in linea:
                        en_uso.add(linea.rsplit(" ", 1)[-1].strip())
            except OSError:
                continue                  # el proceso murió mientras leíamos
        borrados = 0
        for d in Path("/tmp").glob("tmp*"):
            so = d / "libespeak-ng.so"
            try:
                if not d.is_dir() or not so.is_file():
                    continue
                if [p.name for p in d.iterdir()] != ["libespeak-ng.so"]:
                    continue              # tiene más cosas: no es lo que busco
                if str(so) in en_uso:
                    continue              # alguien lo está usando ahora mismo
                so.unlink()
                d.rmdir()
                borrados += 1
            except OSError:
                continue
        return borrados

    def preload(self):
        import voice
        try:
            n = self._limpiar_espeak_huerfanos()
            if n:
                print(f"(limpiados {n} temporales de voz de arranques previos)",
                      flush=True)
        except Exception:
            pass                          # limpiar nunca puede impedir arrancar
        voice._get_whisper(self.cfg["whisper_size"])
        if self.cfg.get("tts", "kokoro") == "kokoro":
            try:
                voice._get_kokoro()        # baja el modelo la 1a vez
            except Exception as e:
                print(f"(aviso) Kokoro no disponible, usaré piper: {e}")
        if self.cfg.get("api_key"):
            try:
                self.brain()
            except Exception as e:
                print(f"(aviso) cerebro no disponible: {e}")
        # Aquí había un vigilante que cada 20 s mandaba un /api/chat entero solo
        # para dejar caliente la caché de prompt. Se quitó el 01/09/2026, por
        # dos razones y las dos medidas:
        #
        #  - Ya no hace falta tanto. Con el Gemma4 de 31B el prefijo en frío
        #    costaba 30-44 s, y evitarlo justificaba el vigilante. Con `jarvis`
        #    (80B MoE) el mismo prefijo cuesta 8,9 s en frío y 0,8 s en
        #    caliente: la primera pregunta tras un silencio pasa de ~1 s a ~9 s,
        #    y solo esa.
        #  - Y salía caro en la otra punta. Cada sondeo obligaba al Mac a
        #    mantener 52 GB de modelo residentes, que es memoria que Wilmer
        #    quiere para otras cosas.
        #
        # Lo que NO se quitó es calentar() a secas: _recalentar_titular() lo
        # sigue llamando al volver de una consulta pesada a ORFEO o a ÍCARO,
        # que es cuando de verdad se pierde la caché.

        # Y el toolbox de ingeniería (pint, CoolProp, fluids, ht, Pynite). Son
        # 2 s de importación y ~119 MB que, si no se hacen aquí, se los come la
        # primera cuenta que pida Wilmer. El ahorro es de un segundo escaso, no
        # de los treinta que llegué a suponer: los picos de 30 s de la primera
        # pregunta de ingeniería eran el modelo escribiendo el código, no estos
        # imports. Se hace igualmente porque el segundo se lo ahorra él y la
        # memoria sobra, pero conviene no vender esto como una gran mejora.
        def _precargar_ingenieria():
            try:
                import engineering
                engineering._toolbox_ns()
            except Exception as e:
                print(f"(aviso) no pude precargar el toolbox: {e}", flush=True)

        threading.Thread(target=_precargar_ingenieria, daemon=True).start()

    # ------------------------------------------------ comando por texto
    def handle_text(self, text: str, speak: bool = False) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        import voice
        voice.nuevo_turno()          # turno nuevo: se levanta el silencio
        with self._lock:
            import lines
            import tasks
            store.add("tú", text)
            # Los modos van ANTES que nada: entrar, salir y contestar dentro de
            # uno no puede depender de que ningún motor esté libre.
            _modo = self._modo_intercepta(text)
            if _modo is not None:
                store.add("asistente", _modo)
                if speak:
                    import voice
                    store.set_status("speaking")
                    _v, _eng = self._tts()
                    voice.speak(_modo, _v, _eng)
                    store.set_status("idle")
                return _modo
            # confirmación pendiente de una tarea (borrar/instalar)
            if self._pending_task and self._is_affirmation(text):
                instr, self._pending_task = self._pending_task, None
                reply = self._compose_task_reply(tasks.run_task(instr, confirmed=True))
            elif self._pending_task and self._is_negation(text):
                self._pending_task = None
                reply = "Va, lo dejo así, Wilmer. Tú mandas."
            elif (_subir := self._acepta_orfeo(text)) is not None:
                reply = _subir            # dijo que sí a subirlo a ORFEO
            else:
                # ¿llamó a un motor por su nombre clave? ARGOS y los caídos se
                # cierran aquí; ORFEO e ÍCARO reescriben `text` para que sea
                # PROMETEO quien lo cuente. No se sale por la puerta de atrás:
                # la respuesta tiene que pasar igual por el bloque que habla.
                original = text
                text, cerrada = self._escalafon(text)
                if cerrada is not None:
                    reply = cerrada
                else:
                    propio = (text is original)
                    reply = router.fast_route(text)   # ya viene con personalidad
                    if reply is None:
                        instr = tasks.detect(text)
                        if instr:                 # tarea pesada -> ÉREBO
                            reply = self._compose_task_reply(tasks.run_task(instr), instr)
                            propio = False
                        else:
                            try:
                                reply = self.brain().think(text)
                            except Exception as e:
                                reply = f"{lines.error_line()} ({e})"
                                propio = False
                    reply = self._quiza_ofrecer_orfeo(original, reply, propio)
            store.add("asistente", reply)
            if speak:
                import voice
                store.set_status("speaking")
                v, eng = self._tts()
                voice.speak(reply, v, eng)
                store.set_status("idle")
            return reply

    # --------------------------------------- pensar una respuesta (texto->texto)
    # ═══════════════════════════════════════════════════════════
    #  Modos: un motor que se queda PUESTO hasta que se le releva
    # ═══════════════════════════════════════════════════════════
    def _modo_intercepta(self, text: str):
        """Entrar en un modo, salir de él, o contestar estando dentro.

        Devuelve la respuesta, o None para que siga el camino de siempre.

        Nombrar a un motor ("Orfeo, explícame X") enruta ESA frase y ya. Un modo
        es distinto: se queda puesto y todo lo que digas va ahí hasta que lo
        releves. Wilmer lo pidió para ÍCARO —"es como tener un asistente al
        teléfono: mientras llama, no le pido otras cosas"— y de paso arregla que
        "cambia a ORFEO" no hiciera nada.

        Entrar y salir se reconocen con una regla de texto AQUÍ, en el portátil.
        Para la salida no es un lujo: si la frase de "terminamos" hubiera que
        mandársela al motor de turno, habría que esperar a que acabara su
        encargo —minutos— solo para poder salir.
        """
        import cerebros
        if self._modo and cerebros.pide_salir_del_modo(text):
            return self._salir_del_modo()
        if not self._modo:
            pedido = cerebros.modo_pedido(text)
            return self._entrar_en_modo(pedido) if pedido else None
        # Dentro del modo. Los atajos que NO tocan ningún modelo siguen valiendo:
        # subir el volumen o cerrar una ventana no tiene por qué esperar a que
        # ÍCARO termine de compilar.
        rapida = router.fast_route(text)
        if rapida is not None:
            return rapida
        import cerebros as _c
        if self._modo == "ICARO":
            # Se apunta lo que se pide y lo que sale, para poder contárselo a
            # PROMETEO al salir sin depender de que nadie lo recuerde.
            r = _c.consultar_icaro(text)
            self._modo_hechos.append((text, (r or "")[:180]))
            return r
        if self._modo == "ORFEO":
            # Contesta ÉL, sin que PROMETEO lo vuelva a contar. Esa regla cuesta
            # una generación entera de más (medido: 2,1 s de ORFEO + 1,9 s de
            # PROMETEO repitiéndolo) y aquí no aporta: Wilmer ha pedido
            # expresamente hablar con ORFEO.
            return _c.consultar_orfeo(text)
        return _c.consultar_icaro(text)

    def _entrar_en_modo(self, nombre: str) -> str:
        self._modo = nombre
        self._modo_hechos = []
        self._modo_historial = []
        print(f"(modo {nombre} ACTIVADO)", flush=True)
        if nombre == "ICARO":
            return ("Me hago cargo, Wilmer. A partir de ahora hablas conmigo, "
                    "ÍCARO, y todo lo que digas va al proyecto. Dime «Ícaro, "
                    "terminamos» cuando quieras que devuelva el mando.")
        return ("Aquí ORFEO, Wilmer. Pregunta lo que quieras y lo pienso a "
                "fondo. Dime «terminamos» cuando quieras volver.")

    def _salir_del_modo(self) -> str:
        anterior, self._modo = self._modo, None
        self._modo_historial = []
        print(f"(modo {anterior} CERRADO)", flush=True)
        # Vale para los DOS modos. Antes ORFEO salia por aqui con un "vuelvo a
        # ser yo" y se perdia todo lo hablado: Wilmer podia estar veinte minutos
        # razonando algo con ORFEO, volver, preguntar "¿y lo que dijimos?" y
        # encontrarse a PROMETEO en blanco. Lo que se hablo con un motor es
        # suyo, pero tambien es de la conversacion.
        quien = "ÍCARO" if anterior == "ICARO" else "ORFEO"
        # PROMETEO no se ha enterado de NADA de lo que paso en el modo: su
        # historial se quedo congelado donde lo dejamos. Sin esto, Wilmer sale,
        # pregunta "¿que hicimos?" y se encuentra un cerebro en blanco.
        #
        # El resumen se arma AQUI, con lo que de verdad se pidio y lo que de
        # verdad contesto ICARO. Se probo pidiendoselo a el y salio mal dos
        # veces: contesto con una pregunta ("¿a que proyecto te refieres?"), esa
        # pregunta entro en el historial, y lo siguiente que dijo Wilmer se leyo
        # como su respuesta —una vez acabo creando una carpeta que nadie pidio—.
        # Un registro de lo que paso no puede inventarse; un resumen generado,
        # si. Y de paso salir del modo es instantaneo, sin esperar otra ronda.
        try:
            hechos = getattr(self, "_modo_hechos", [])
            if hechos:
                lineas = "; ".join(f"le pediste «{p}» y respondió: {r}"
                                   for p, r in hechos[-6:])
                resumen = (f"Mientras {quien} estuvo al mando, " + lineas)
                # El resumen se mete como CONTEXTO, y la conversación se cierra
                # con un asentimiento soso.
                #
                # Antes se metía el texto de ÍCARO tal cual como turno del
                # asistente, y eso mordió: el resumen terminaba con una pregunta
                # ("¿en qué carpeta está?"), así que la siguiente frase de
                # Wilmer se leyó como la RESPUESTA a esa pregunta. Preguntó
                # "¿qué hicimos con ÍCARO?" y PROMETEO, creyendo que le estaba
                # dando un nombre, llamó a crear_carpeta y creó una carpeta de
                # verdad. Dejar el historial colgando de una pregunta ajena
                # convierte lo siguiente que digas en una orden.
                b = self.brain()
                b.messages.append({
                    "role": "user",
                    "content": ("(Contexto, no es una orden ni una pregunta: "
                                f"mientras {quien} estuvo al mando pasó esto. "
                                + resumen + ")")})
                b.messages.append({"role": "assistant", "content": "Anotado."})
                # Al historial va el detalle; en voz, una frase. Leer el
                # registro entero en alto seria interminable.
                n = len(hechos)
                if quien == "ÍCARO":
                    cosa = "encargo" if n == 1 else "encargos"
                    return (f"Te devuelvo el mando, Wilmer. ÍCARO se ocupó de "
                            f"{n} {cosa}; pregúntame por ellos si quieres el "
                            "detalle.")
                cosa = "pregunta" if n == 1 else "preguntas"
                return (f"Vuelvo a ser yo, Wilmer. Me quedo con lo que hablaste "
                        f"con ORFEO: {n} {cosa}. Pregúntame si quieres.")
        except Exception as e:
            print(f"(no pude traer el resumen de {quien}: {e})", flush=True)
        return "Te devuelvo el mando, Wilmer. Vuelvo a ser PROMETEO."

    def _respond(self, text: str) -> str:
        import lines
        store.add("tú (voz)", text)

        modo = self._modo_intercepta(text)
        if modo is not None:
            store.add("asistente", modo)
            return modo

        # ¿está diciendo que sí a un "¿se la mando a ORFEO?" de hace un momento?
        subir = self._acepta_orfeo(text)
        if subir is not None:
            store.add("asistente", subir)
            return subir

        original = text
        text, cerrada = self._escalafon(text)   # ¿llamó a un motor por su nombre?
        if cerrada is not None:
            store.add("asistente", cerrada)
            return cerrada
        propio = (text is original)             # nadie del escalafón se lo llevó
        reply = router.fast_route(text)       # ya viene con personalidad si aplica
        if reply is None:
            try:
                reply = self.brain().think(text)
            except Exception as e:
                reply = f"{lines.error_line()} ({e})"
        reply = self._quiza_ofrecer_orfeo(original, reply, propio)
        store.add("asistente", reply)
        return reply

    # ------------------------------- ¿esto le queda grande a PROMETEO?
    def _quiza_ofrecer_orfeo(self, pregunta: str, reply: str, propio: bool) -> str:
        """Contesta PROMETEO y, si la pregunta pedía más cabeza, ofrece pasársela
        a ORFEO diciendo POR QUÉ. Nunca sube de cerebro por su cuenta: Wilmer
        quiere decidirlo él, que ORFEO tarda un minuto largo."""
        self._pendiente_orfeo = None
        if not propio or not reply:
            return reply
        try:
            import cerebros
            c = cerebros.complejidad(pregunta)
            if c["banda"] != "ofrecer":
                return reply
            self._pendiente_orfeo = pregunta
            return reply.rstrip() + cerebros.ofrecimiento(c["razon"])
        except Exception:
            return reply

    def _acepta_orfeo(self, text: str):
        """Si había un ofrecimiento en el aire y dice que sí, se lo manda."""
        pendiente = getattr(self, "_pendiente_orfeo", None)
        if not pendiente:
            return None
        if self._is_negation(text):
            self._pendiente_orfeo = None
            return "Va, lo dejamos así."
        if not self._is_affirmation(text):
            return None                      # no era respuesta al ofrecimiento
        self._pendiente_orfeo = None
        try:
            import cerebros
            crudo = cerebros.consultar_orfeo(pendiente)
            return self.brain().think(
                "Wilmer le encargó esto a ORFEO: " + pendiente
                + "\n\nORFEO ha devuelto esto:\n" + crudo
                + "\n\nCuéntaselo tú, como PROMETEO, con tus palabras y sin leer "
                  "su texto tal cual.")
        except Exception as e:
            return f"ORFEO no me contestó bien: {e}"

    # -------------------------------------------- palabras reservadas: el escalafón
    def _escalafon(self, text: str):
        """PROMETEO, ORFEO, ARGOS, ÍCARO, ÉREBO — nombrarlos manda el trabajo allí.

        Devuelve (texto_para_el_cerebro, respuesta_ya_cerrada). Si lo segundo no
        es None, ya está todo dicho.

        La regla de Wilmer manda: trabaje quien trabaje por debajo, la voz es
        siempre PROMETEO. Por eso lo que devuelven ORFEO e ÍCARO no se suelta
        tal cual; se le entrega al cerebro para que lo cuente con su carácter.
        ÉREBO no pasa por aquí: lo caza tasks.detect() antes, y así se queda con
        toda la maquinaria de tarea pesada y sus avisos hablados.
        """
        try:
            import cerebros
        except Exception:
            return text, None
        encontrado = cerebros.detectar(text)
        if not encontrado:
            return text, None
        nombre, encargo = encontrado

        if nombre == "PROMETEO":               # ya eres tú: sigue como siempre
            return (encargo or text), None

        if nombre == "ARGOS":
            return text, ("ARGOS de momento es solo el nombre, Wilmer. Lo tienes "
                          "apartado pero todavía no hay motor detrás. Si quieres "
                          "algo pensado a fondo te lo paso a ORFEO, que para eso "
                          "es el que hay.")

        if not encargo:
            quien = {"ORFEO": "ORFEO", "ICARO": "ÍCARO"}.get(nombre, nombre)
            return text, f"Te escucho, pero no me dijiste qué le encargo a {quien}."

        estado = cerebros.disponibles()
        if not estado.get(nombre, {}).get("ok"):
            quien = cerebros.BONITO.get(nombre, nombre)
            return text, (f"{quien} no está disponible ahora mismo. "
                          f"¿Quieres que lo resuelva yo?")

        if nombre == "ORFEO":
            crudo = cerebros.consultar_orfeo(encargo)
            return ("Wilmer le encargó esto a ORFEO: " + encargo
                    + "\n\nORFEO ha devuelto esto:\n" + crudo
                    + "\n\nAhora cuéntaselo tú, como PROMETEO. No leas su texto tal "
                      "cual ni hables en su nombre: quédate con lo que importa y "
                      "dilo con tus palabras. Menciona de pasada que lo consultaste "
                      "con ORFEO."), None

        if nombre == "ICARO":
            crudo = cerebros.consultar_icaro(encargo)
            return ("Wilmer le encargó esto a ÍCARO: " + encargo
                    + "\n\nÍCARO ha devuelto esto:\n" + crudo
                    + "\n\nCuéntaselo tú, como PROMETEO, con tus palabras y breve."), None

        return text, None

    # ---------------------------------------- afirmación / negación (confirmaciones)
    # Sí y no. Van en dos listas por un motivo: "no, así está bien" empieza por
    # "no," con coma, y el startswith("no ") de antes no lo veía, así que una
    # negación clarísima se colaba como pregunta nueva.
    #
    # Y las palabras ambiguas solo valen SOLAS. "para" estaba entre los noes con
    # startswith, así que "para qué sirve esto" contaba como negativa; "va" y
    # "ya" tienen el mismo problema al revés.
    _YES = ("si", "sí", "dale", "hazlo", "házlo", "confirmo", "adelante",
            "ok", "okay", "procede", "sip", "hágalo", "hagalo", "obvio",
            "por supuesto", "afirmativo", "sí hazlo", "si hazlo", "sí dale",
            "claro que sí", "claro que si", "claro sí", "claro si",
            "si dale", "venga", "vale", "de una", "por favor", "mándala",
            "mandala", "mándasela", "mandasela", "pásasela", "pasasela",
            "sí por favor", "si por favor", "sí claro", "si claro", "hazlo ya")
    _YES_SOLO = ("va", "ya", "sale", "perfecto", "listo", "correcto", "exacto",
                 "claro")
    _NO = ("no", "mejor no", "déjalo", "dejalo", "déjala", "dejala", "cancela",
           "olvídalo", "olvidalo", "nel", "negativo", "detente", "no hagas",
           "no hace falta", "no gracias", "no importa", "así está bien",
           "asi esta bien", "está bien así", "esta bien asi", "ya está",
           "ya esta", "para nada", "nada", "quita", "anula", "bórralo", "borralo")
    _NO_SOLO = ("para", "párale", "parale", "nop", "nah", "tampoco")

    @staticmethod
    def _limpia_respuesta(text: str) -> str:
        """minúsculas y sin puntuación, para que la coma no rompa la comparación."""
        import re as _re
        t = _re.sub(r"[,.;:!?¡¿…\-—\"'']+", " ", (text or "").lower())
        return " ".join(t.split())

    def _is_affirmation(self, text: str) -> bool:
        t = self._limpia_respuesta(text)
        if not t:
            return False
        if t in self._YES_SOLO:
            return True
        return any(t == y or t.startswith(y + " ") for y in self._YES)

    # "no sé cómo va esto" empieza por no y no es un rechazo: es la pregunta.
    _NO_FALSOS = ("no se ", "no sé ", "no entiendo", "no recuerdo", "no me acuerdo",
                  "no tengo ni idea", "no estoy seguro")

    def _is_negation(self, text: str) -> bool:
        t = self._limpia_respuesta(text)
        if not t:
            return False
        if any(t.startswith(f) for f in self._NO_FALSOS):
            return False
        if t in self._NO_SOLO:
            return True
        return any(t == n or t.startswith(n + " ") for n in self._NO)

    # ----------------------------------------- componer respuesta de tarea (texto)
    def _compose_task_reply(self, res: dict, instruction: str = "") -> str:
        import lines
        txt = (res.get("text") or "").strip()
        if res.get("confirm"):
            if instruction:
                self._pending_task = instruction
            return ("Oye Wilmer, para esto necesito tu permiso: " + txt +
                    " ¿Lo hago?")
        if res.get("ok"):
            return (lines.task_done() + (" " + txt if txt else "")).strip()
        return (lines.task_failed() + (" " + txt if txt else "")).strip()

    # frases con las que cierras la charla ("ya, gracias", "adiós blue"...)
    _END_PHRASES = ("gracias", "adios", "adiós", "ya no", "eso es todo",
                    "nada mas", "nada más", "olvidalo", "olvídalo", "ya nada",
                    "hasta luego", "es todo")

    def _is_end_phrase(self, text: str) -> bool:
        t = text.lower().strip(" .!?¡¿")
        return len(t) <= 18 and any(p in t for p in self._END_PHRASES)

    # ------------------------------------------------ una sola escucha (Super+J)
    def _avisar_ocupada(self) -> None:
        """Super+J con un turno ya en marcha. Decirlo, en vez de no hacer nada."""
        import subprocess
        estado = store.get_status()
        que = {"listening": "te estoy escuchando",
               "thinking": "estoy pensando todavía",
               "speaking": "estoy hablando"}.get(estado, "estoy ocupada")
        subprocess.run(["notify-send", "-a", "Blue", "-t", "2000",
                        "Blue está ocupada", que.capitalize()], check=False)

    def handle_voice(self, espera: float = 0.0) -> bool:
        """`espera` = segundos de gracia para tomar el cerrojo.

        Super+J manda primero SIGUSR1 (corta la voz) y despues "listen". Entre
        las dos cosas el turno anterior todavia se esta desmontando y aun tiene
        `_busy`, asi que con acquire() a secas la orden se perdia y Blue
        contestaba "estoy hablando" al que acababa de mandarla callar. Un par de
        segundos de gracia bastan para que el barge-in termine de surtir efecto.
        Sin espera (0.0) el comportamiento es el de antes."""
        tomado = (self._busy.acquire(timeout=espera) if espera > 0
                  else self._busy.acquire(blocking=False))
        if not tomado:
            # Antes esto era mudo: pulsabas Super+J, no pasaba nada, y no habia
            # forma de saber si te habia oido. Ahora al menos lo dice.
            self._avisar_ocupada()
            return False                       # ya hay una conversación activa
        try:
            import time as _t
            import voice
            # Cronometro por fases. La lentitud de un turno se reparte entre
            # cuatro cosas —esperar a que Wilmer calle, transcribir, pensar y
            # empezar a hablar— y hasta ahora no habia forma de saber cual
            # pesaba. Sin este desglose cada diagnostico era una conjetura.
            _t0 = _t.time()
            voice.nuevo_turno()          # turno nuevo: se levanta el silencio
            store.set_status("listening")
            audio = voice.record_until_silence()
            _t_grab = _t.time() - _t0
            if audio.size == 0:
                store.set_status("idle")
                print(f"(turno de voz: grabar {_t_grab:.1f} s, sin audio)",
                      flush=True)
                return False
            store.set_status("thinking")
            _t1 = _t.time()
            text = voice.transcribe(audio, self.cfg["whisper_size"])
            _t_trans = _t.time() - _t1
            print(f"(turno de voz: grabar {_t_grab:.1f} s | "
                  f"transcribir {_t_trans:.1f} s [{self.cfg['whisper_size']}] "
                  f"-> {text!r})", flush=True)
            v, eng = self._tts()
            if not text:
                import lines
                store.set_status("speaking")
                voice.speak(lines.no_understand(), v, eng)
                store.set_status("idle")
                return False
            import tasks
            # ¿confirmación pendiente de una tarea (borrar/instalar)?
            if self._pending_task and self._is_affirmation(text):
                instr, self._pending_task = self._pending_task, None
                self._run_task_voice(instr, confirmed=True)
                return True
            if self._pending_task and self._is_negation(text):
                import lines
                self._pending_task = None
                store.set_status("speaking")
                voice.speak("Va, lo dejo así, Wilmer. Tú mandas.", v, eng)
                store.set_status("idle")
                return True
            # ¿tarea pesada para Claude Code? (con relleno hablado mientras trabaja)
            instr = tasks.detect(text)
            if instr:
                self._run_task_voice(instr)
                return True
            _t2 = _t.time()
            reply = self._responder_avisando(text, v, eng)
            _t_pensar = _t.time() - _t2
            if store.abortado() or not reply:
                store.set_status("idle")     # le dio a parar mientras pensaba
                return False
            store.set_status("speaking")
            _t3 = _t.time()
            voice.speak(reply, v, eng)
            print(f"(turno de voz COMPLETO {_t.time() - _t0:.1f} s = "
                  f"grabar {_t_grab:.1f} + transcribir {_t_trans:.1f} + "
                  f"pensar {_t_pensar:.1f} + hablar {_t.time() - _t3:.1f})",
                  flush=True)
            store.set_status("idle")
            return True
        finally:
            self._busy.release()

    # --------------------------- pensar sin quedarse mudo
    def _responder_avisando(self, text: str, v, eng) -> str:
        """Como _respond(), pero dando señales de vida si tarda.

        Una consulta normal puede irse a treinta segundos si el modelo encadena
        varias herramientas, y quedarse callada todo ese rato parece un cuelgue.
        """
        import avisos
        import voice

        avisador = avisos.Avisador(
            lambda f: (store.set_status("thinking"), voice.speak(f, v, eng)),
            escala=avisos.ESCALA_NORMAL,
            cortar=voice.stop_speaking,
        )
        with avisador:
            reply = self._respond(text)
        return avisos.remate(avisador.prometio_avisar) + reply

    # --------------------------- tarea pesada con relleno hablado (Claude Code)
    def _run_task_voice(self, instruction: str, confirmed: bool = False) -> None:
        """Habla un 'manos a la obra', suelta frases de relleno mientras Claude
        Code trabaja (puede tardar), y al final dice el resultado con vibra."""
        import threading
        import lines
        import tasks
        import voice
        v, eng = self._tts()
        holder: dict = {}

        def _work():
            try:
                holder.update(tasks.run_task(instruction, confirmed=confirmed))
            except Exception as e:
                holder.update({"ok": False, "confirm": False, "text": str(e)[:160]})

        import avisos

        th = threading.Thread(target=_work, daemon=True)
        th.start()
        store.set_status("thinking")
        voice.speak(lines.task_running(), v, eng)

        # Avisos espaciados mientras Claude Code trabaja. Antes esto era un
        # bucle que soltaba una frase de relleno tras otra sin pausa durante
        # toda la tarea, porque speak() bloquea. Ahora habla de tanto en tanto.
        avisador = avisos.Avisador(
            lambda f: (store.set_status("thinking"), voice.speak(f, v, eng)),
            escala=avisos.ESCALA_TAREA,
            cortar=voice.stop_speaking,
        )
        with avisador:
            th.join()

        res = holder or {"ok": False, "confirm": False, "text": ""}
        reply = self._compose_task_reply(res, instruction)
        store.add("asistente", reply)
        store.set_status("speaking")
        # Si llegó a prometer que avisaría, se cumple.
        voice.speak(avisos.remate(avisador.prometio_avisar) + reply, v, eng)
        store.set_status("idle")

    # ------------------------------------------- push-to-talk (mantener Super+J)
    def ptt_start(self) -> None:
        """Empieza a grabar al presionar Super+J."""
        import voice
        if not self._busy.acquire(blocking=False):
            return                              # ya hay algo en curso
        self._ptt_on = True
        voice.nuevo_turno()              # turno nuevo: se levanta el silencio
        store.set_status("listening")
        try:
            voice.ptt_start()
        except Exception as e:
            print(f"(ptt) no pude grabar: {e}")
            store.set_status("idle")
            self._ptt_on = False
            self._busy.release()
            return
        # Vigia. _busy solo lo soltaba ptt_stop(), asi que si el evento de
        # soltar la tecla no llegaba nunca (atajo mal puesto, proceso muerto),
        # Blue quedaba tomada PARA SIEMPRE —todo Super+J posterior devolvia
        # False en silencio— y el stream seguia acumulando en _ptt_frames a
        # 64 KB/s. Esto lo cierra solo pasado el tope.
        import threading as _th
        self._ptt_watchdog = _th.Timer(PTT_MAX_S, self._ptt_rescate)
        self._ptt_watchdog.daemon = True
        self._ptt_watchdog.start()

    def _ptt_rescate(self) -> None:
        """Nadie solto la tecla en PTT_MAX_S: cerrar y TIRAR lo grabado.

        Se descarta a proposito en vez de llamar a ptt_stop(): eso pondria a
        Whisper a masticar dos minutos de audio que casi seguro son la sala
        vacia, y dejaria _busy tomado todo ese rato — o sea, cambiar un cuelgue
        por otro mas lento. Un rescate tiene que devolver el control YA.
        """
        import voice
        if not getattr(self, "_ptt_on", False):
            return
        self._ptt_on = False
        self._ptt_watchdog = None
        print(f"(ptt) nadie solto la tecla en {PTT_MAX_S:.0f}s: cierro y descarto")
        try:
            voice.ptt_stop()                    # cierra el stream y vacia frames
        except Exception:
            pass
        store.set_status("idle")
        try:
            self._busy.release()
        except RuntimeError:
            pass                                # ya estaba suelto

    def ptt_stop(self) -> None:
        """Suelta Super+J: corta grabación, transcribe, piensa y responde."""
        import voice
        if not getattr(self, "_ptt_on", False):
            return
        self._ptt_on = False
        w = getattr(self, "_ptt_watchdog", None)
        if w is not None:
            w.cancel()                          # llego a tiempo: no hace falta
            self._ptt_watchdog = None
        try:
            audio = voice.ptt_stop()
            v, eng = self._tts()
            if audio.size < voice.SAMPLE_RATE * 0.3:   # < 0.3s = no dijo nada
                store.set_status("idle")
                return
            store.set_status("thinking")
            text = voice.transcribe(audio, self.cfg["whisper_size"])
            if not text:
                import lines
                store.set_status("speaking")
                voice.speak(lines.no_understand(), v, eng)
                store.set_status("idle")
                return
            reply = self._responder_avisando(text, v, eng)
            if store.abortado() or not reply:
                store.set_status("idle")
                return
            store.set_status("speaking")
            voice.speak(reply, v, eng)
            store.set_status("idle")
        finally:
            self._busy.release()

    # ------------------------------- conversación continua (tras "Hey Blue")
    def converse(self, on_start=None) -> None:
        """Despierta y platica de corrido: responde y sigue escuchando sin
        repetir la palabra. Termina si te quedas callado o te despides."""
        if not self._busy.acquire(blocking=False):
            return                              # ya hay una conversación activa
        try:
            import voice
            if on_start:
                try:
                    on_start()                  # ej. abrir la burbuja
                except Exception:
                    pass
            v, eng = self._tts()
            turns = int(self.cfg.get("converse_turns", 6))
            timeout = float(self.cfg.get("converse_timeout", 7.0))
            # ack breve para que sepas que despertó
            store.set_status("speaking")
            voice.speak("¿Sí, Wilmer?", v, eng)
            for _ in range(turns):
                voice.nuevo_turno()      # cada vuelta es un turno: se puede cortar
                store.set_status("listening")
                audio = voice.record_until_silence(start_timeout=timeout)
                if audio.size == 0:
                    break                       # te quedaste callado -> a dormir
                store.set_status("thinking")
                text = voice.transcribe(audio, self.cfg["whisper_size"])
                if not text:
                    continue
                if self._is_end_phrase(text):
                    store.set_status("speaking")
                    voice.speak("Aquí estaré.", v, eng)
                    break
                import tasks
                instr = tasks.detect(text)
                if instr:                       # tarea pesada dentro de la charla
                    self._run_task_voice(instr)
                    continue
                reply = self._responder_avisando(text, v, eng)
                if store.abortado() or not reply:
                    break                    # le dio a parar: se acaba la charla
                store.set_status("speaking")
                voice.speak(reply, v, eng)
            store.set_status("idle")
        finally:
            self._busy.release()

    def _narrate_step(self, text: str):
        """Narra un paso de protocolo en vivo: muestra+estalla en la ventana y lo
        dice en voz alta. Cero tokens (la frase ya viene de la acción)."""
        import voice
        import lines
        text = lines.flavor_step(text)     # toque ligero de personalidad
        store.narrate(text)                # estado speaking + texto + pulso (estallido)
        v, eng = self._tts()
        voice.speak(text, v, eng)

    def _pomodoro_say(self, text: str):
        """Aviso del pomodoro desde el hilo de fondo: lo muestra en la ventana
        (estallido) y lo dice en voz alta. Cero tokens."""
        import voice
        store.narrate(text)                # estado speaking + texto + pulso
        v, eng = self._tts()
        voice.speak(text, v, eng)
        store.set_status("idle")

    def speak(self, text: str):
        import voice
        v, eng = self._tts()
        voice.speak(text, v, eng)

    def stop_speaking(self):
        """El parar de Wilmer (botón de la burbuja, panel, Super+J). Se recuerda:
        no basta con cortar el audio de ahora, hay que impedir lo que venía
        detrás. Lo interno que solo corta un aviso usa voice.stop_speaking()."""
        import voice
        import store
        voice.interrumpir()
        # Antes esto ponia "idle" siempre, incluso con un pensamiento en vuelo:
        # la interfaz decia "Listo" mientras Blue seguia trabajando minutos. Una
        # peticion HTTP ya lanzada no se puede cortar, asi que se aborta en la
        # ronda siguiente (brain.py) y hasta entonces se dice la verdad.
        if store.get_status() == "thinking":
            store.set_status("thinking", "cancelando…")
        else:
            store.set_status("idle")
