"""Assistant: orquesta voz/texto, ruta rapida y cerebro. Thread-safe."""
from __future__ import annotations
import threading

import config as config_mod
import router
import store


class Assistant:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or config_mod.load()
        self._lock = threading.Lock()
        self._busy = threading.Lock()      # 1 sola conversación a la vez (mic)
        self._brain = None
        self._pending_task = None          # tarea esperando un 'sí' (borrar/instalar)
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
        return self._brain

    def preload(self):
        import voice
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

    # ------------------------------------------------ comando por texto
    def handle_text(self, text: str, speak: bool = False) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        with self._lock:
            import lines
            import tasks
            store.add("tú", text)
            # confirmación pendiente de una tarea (borrar/instalar)
            if self._pending_task and self._is_affirmation(text):
                instr, self._pending_task = self._pending_task, None
                reply = self._compose_task_reply(tasks.run_task(instr, confirmed=True))
            elif self._pending_task and self._is_negation(text):
                self._pending_task = None
                reply = "Va, lo dejo así, Wilmer. Tú mandas."
            else:
                # ¿llamó a un motor por su nombre clave? ARGOS y los caídos se
                # cierran aquí; ORFEO e ÍCARO reescriben `text` para que sea
                # PROMETEO quien lo cuente. No se sale por la puerta de atrás:
                # la respuesta tiene que pasar igual por el bloque que habla.
                text, cerrada = self._escalafon(text)
                if cerrada is not None:
                    reply = cerrada
                else:
                    reply = router.fast_route(text)   # ya viene con personalidad
                    if reply is None:
                        instr = tasks.detect(text)
                        if instr:                 # tarea pesada -> Claude Code
                            reply = self._compose_task_reply(tasks.run_task(instr), instr)
                        else:
                            try:
                                reply = self.brain().think(text)
                            except Exception as e:
                                reply = f"{lines.error_line()} ({e})"
            store.add("asistente", reply)
            if speak:
                import voice
                store.set_status("speaking")
                v, eng = self._tts()
                voice.speak(reply, v, eng)
                store.set_status("idle")
            return reply

    # --------------------------------------- pensar una respuesta (texto->texto)
    def _respond(self, text: str) -> str:
        import lines
        store.add("tú (voz)", text)
        text, cerrada = self._escalafon(text)   # ¿llamó a un motor por su nombre?
        if cerrada is not None:
            store.add("asistente", cerrada)
            return cerrada
        reply = router.fast_route(text)       # ya viene con personalidad si aplica
        if reply is None:
            try:
                reply = self.brain().think(text)
            except Exception as e:
                reply = f"{lines.error_line()} ({e})"
        store.add("asistente", reply)
        return reply

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
            detalle = estado.get(nombre, {}).get("detalle", "")
            quien = cerebros.BONITO.get(nombre, nombre)
            return text, (f"{quien} no está disponible ahora mismo: {detalle}. "
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
    _YES = ("si", "sí", "dale", "hazlo", "házlo", "confirmo", "claro", "adelante",
            "ok", "okay", "va", "procede", "sip", "hágalo", "hagalo", "obvio",
            "por supuesto", "afirmativo", "sí hazlo", "si hazlo")
    _NO = ("no", "mejor no", "déjalo", "dejalo", "cancela", "olvídalo", "olvidalo",
           "nel", "negativo", "para", "detente", "no hagas")

    def _is_affirmation(self, text: str) -> bool:
        t = text.lower().strip(" .!?¡¿")
        return any(t == y or t.startswith(y + " ") for y in self._YES)

    def _is_negation(self, text: str) -> bool:
        t = text.lower().strip(" .!?¡¿")
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
    def handle_voice(self) -> bool:
        if not self._busy.acquire(blocking=False):
            return False                       # ya hay una conversación activa
        try:
            import voice
            store.set_status("listening")
            audio = voice.record_until_silence()
            if audio.size == 0:
                store.set_status("idle")
                return False
            store.set_status("thinking")
            text = voice.transcribe(audio, self.cfg["whisper_size"])
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
            reply = self._responder_avisando(text, v, eng)
            store.set_status("speaking")
            voice.speak(reply, v, eng)
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
        store.set_status("listening")
        try:
            voice.ptt_start()
        except Exception as e:
            print(f"(ptt) no pude grabar: {e}")
            store.set_status("idle")
            self._ptt_on = False
            self._busy.release()

    def ptt_stop(self) -> None:
        """Suelta Super+J: corta grabación, transcribe, piensa y responde."""
        import voice
        if not getattr(self, "_ptt_on", False):
            return
        self._ptt_on = False
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
        import voice
        import store
        voice.stop_speaking()
        store.set_status("idle")
