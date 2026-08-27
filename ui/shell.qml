//  BLUE — ventana flotante (Quickshell / QML)
//  Anillos orbitales animados por estado. Lee ~/.config/blue/ui.json.
import Quickshell
import Quickshell.Wayland
import Quickshell.Io
import QtQuick
import QtQuick.Shapes

ShellRoot {
    PanelWindow {
        id: win
        WlrLayershell.namespace: "blue-bubble"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

        anchors { top: true; right: true }
        margins { top: 60; right: 30 }
        implicitWidth: 300
        implicitHeight: 380
        color: "transparent"

        // -------- estado leído de ui.json --------
        property string status: "idle"
        property string detail: ""
        property string userText: ""
        property string replyText: ""
        property int count: 0
        property int pulse: 0
        property double lastActive: Date.now()

        onPulseChanged: burst.restart()      // estallido del anillo en cada paso

        readonly property color cyan: "#67d6ff"
        readonly property color blue: "#4a9eff"
        // cada estado tiene su propio color para que se distingan a simple vista
        readonly property color accent: status === "thinking" ? "#9b8cff"   // violeta = procesando
                                       : status === "speaking" ? "#7af0ff"   // cian brillante = hablando
                                       : status === "listening" ? "#67d6ff"  // cian = escuchando
                                       : "#3f6fa5"                            // azul tenue = reposo

        onStatusChanged: {
            if (status !== "idle")
                lastActive = Date.now();
            if (status === "speaking" || status === "thinking")
                burst.restart();
        }

        function spin(base) {
            // duración de giro según estado (menor = más rápido)
            if (status === "thinking") return base * 0.35;
            if (status === "speaking") return base * 0.6;
            if (status === "listening") return base * 0.8;
            return base;                       // idle
        }
        function label() {
            if (status === "listening") return "Escuchando…";
            if (status === "thinking")  return "Pensando…";
            if (status === "speaking")  return "Hablando…";
            return "Listo";
        }

        // -------- estado leído de ui.json (nativo, en vivo) --------
        FileView {
            id: stateFile
            path: "/home/wilmer/.config/blue/ui.json"
            watchChanges: true
            onFileChanged: reload()
            onLoaded: {
                try {
                    var d = JSON.parse(stateFile.text());
                    win.status = d.status || "idle";
                    win.detail = d.detail || "";
                    win.userText = d.user || "";
                    win.replyText = d.reply || "";
                    win.count = d.count || 0;
                    win.pulse = d.pulse || 0;
                } catch (e) {}
            }
        }
        // respaldo: recarga periódica por si watchChanges pierde un cambio
        Timer {
            interval: 400; running: true; repeat: true
            onTriggered: stateFile.reload()
        }
        // auto-cierre tras 8s en idle
        Timer {
            interval: 1000; running: true; repeat: true
            onTriggered: {
                if (win.status === "idle" && (Date.now() - win.lastActive) > 8000)
                    Qt.quit();
            }
        }

        // ================= TARJETA GLASS =================
        Rectangle {
            anchors.fill: parent
            radius: 26
            color: Qt.rgba(0.04, 0.06, 0.09, 0.55)
            border.color: Qt.rgba(win.cyan.r, win.cyan.g, win.cyan.b, 0.25)
            border.width: 1

            Column {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 8

                // título
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "B L U E"
                    color: win.cyan
                    font.pixelSize: 18
                    font.letterSpacing: 4
                    font.bold: true
                }

                // ---------- anillos ----------
                Item {
                    id: ringField
                    width: parent.width
                    height: 170

                    Item {
                        id: rings
                        anchors.centerIn: parent
                        width: 150; height: 150
                        property bool active: win.status === "listening" || win.status === "speaking"

                        // explosión + rearmado elástico (al pensar/hablar)
                        SequentialAnimation {
                            id: burst
                            NumberAnimation { target: rings; property: "scale"; to: 1.34; duration: 150; easing.type: Easing.OutQuad }
                            NumberAnimation { target: rings; property: "scale"; to: 1.0; duration: 650; easing.type: Easing.OutBack; easing.overshoot: 2.4 }
                        }

                        component Ring: Shape {
                            property real r: 60
                            property real sweep: 270
                            property color col: win.cyan
                            property real sw: 3
                            anchors.centerIn: parent
                            width: r * 2 + sw * 2; height: width
                            antialiasing: true
                            ShapePath {
                                strokeColor: col
                                strokeWidth: sw
                                fillColor: "transparent"
                                capStyle: ShapePath.RoundCap
                                PathAngleArc {
                                    centerX: width / 2; centerY: height / 2
                                    radiusX: r; radiusY: r
                                    startAngle: 0; sweepAngle: sweep; moveToStart: true
                                }
                            }
                        }

                        // marcas tipo radar (anillo punteado girando) — resalta al PENSAR
                        Shape {
                            anchors.centerIn: parent
                            width: 150; height: 150
                            antialiasing: true
                            opacity: win.status === "thinking" ? 0.9 : 0.4
                            Behavior on opacity { NumberAnimation { duration: 300 } }
                            RotationAnimator on rotation { from: 0; to: 360; loops: Animation.Infinite; running: true; duration: win.spin(13000) }
                            ShapePath {
                                strokeColor: win.accent
                                strokeWidth: 6
                                fillColor: "transparent"
                                strokeStyle: ShapePath.DashLine
                                dashPattern: [0.35, 3.2]
                                capStyle: ShapePath.FlatCap
                                PathAngleArc { centerX: 75; centerY: 75; radiusX: 63; radiusY: 63; startAngle: 0; sweepAngle: 360; moveToStart: true }
                            }
                        }

                        // ondas de voz que se expanden (al escuchar/hablar)
                        Repeater {
                            model: 2
                            Ring {
                                r: 34; sweep: 360; col: win.accent; sw: 2
                                property real t: 0
                                visible: rings.active
                                scale: 0.6 + t * 1.3
                                opacity: rings.active ? (1 - t) * 0.5 : 0
                                SequentialAnimation on t {
                                    loops: Animation.Infinite; running: rings.active
                                    PauseAnimation { duration: index * (win.status === "speaking" ? 480 : 850) }
                                    NumberAnimation { from: 0; to: 1; duration: win.status === "speaking" ? 950 : 1700; easing.type: Easing.OutQuad }
                                }
                            }
                        }

                        Ring {
                            r: 70; sweep: 250; col: win.accent; sw: 2.5
                            opacity: 0.9
                            Behavior on col { ColorAnimation { duration: 350 } }
                            RotationAnimator on rotation {
                                from: 0; to: 360; loops: Animation.Infinite; running: true
                                duration: win.spin(7000)
                            }
                        }
                        Ring {
                            r: 54; sweep: 200; col: Qt.darker(win.accent, 1.5); sw: 3
                            RotationAnimator on rotation {
                                from: 360; to: 0; loops: Animation.Infinite; running: true
                                duration: win.spin(5000)
                            }
                        }
                        Ring {
                            r: 38; sweep: 300; col: win.accent; sw: 2
                            opacity: 0.7
                            RotationAnimator on rotation {
                                from: 0; to: 360; loops: Animation.Infinite; running: true
                                duration: win.spin(3500)
                            }
                        }

                        // puntos orbitando
                        Item {
                            anchors.centerIn: parent
                            width: 150; height: 150
                            RotationAnimator on rotation { from: 0; to: 360; loops: Animation.Infinite; running: true; duration: win.spin(4500) }
                            Repeater {
                                model: 4
                                Rectangle {
                                    width: 5; height: 5; radius: 2.5
                                    color: win.accent
                                    property real ang: index * Math.PI / 2
                                    x: 75 + 47 * Math.cos(ang) - 2.5
                                    y: 75 + 47 * Math.sin(ang) - 2.5
                                }
                            }
                        }

                        // núcleo — latido distinto por estado
                        Rectangle {
                            id: core
                            anchors.centerIn: parent
                            width: 26; height: 26; radius: 13
                            color: win.accent
                            Behavior on color { ColorAnimation { duration: 350 } }
                            property int beat: win.status === "thinking" ? 240
                                             : win.status === "speaking" ? 420
                                             : win.status === "listening" ? 750 : 1600
                            SequentialAnimation on opacity {
                                loops: Animation.Infinite; running: true
                                NumberAnimation { from: 0.45; to: 1.0; duration: core.beat }
                                NumberAnimation { from: 1.0; to: 0.45; duration: core.beat }
                            }
                            Rectangle {     // halo
                                anchors.centerIn: parent
                                width: 44; height: 44; radius: 22
                                color: "transparent"
                                border.color: win.accent; border.width: 2; opacity: 0.4
                            }
                        }
                    }
                }

                // estado
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: win.label()
                    color: "white"; font.pixelSize: 15; font.bold: true
                }
                // texto (lo que dijiste o respondió)
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: win.status === "speaking" ? win.replyText
                          : (win.userText ? "“" + win.userText + "”" : "")
                    color: Qt.rgba(1, 1, 1, 0.6)
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }

                Item { width: 1; height: 4 }

                // ---------- botones ----------
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 14

                    component Btn: Rectangle {
                        property string glyph: ""
                        property var act: (function(){})
                        property color tint: win.cyan
                        width: 46; height: 46; radius: 23
                        color: ma.containsMouse ? Qt.rgba(tint.r, tint.g, tint.b, 0.22)
                                                : Qt.rgba(1, 1, 1, 0.06)
                        border.color: Qt.rgba(tint.r, tint.g, tint.b, 0.4); border.width: 1
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Text { anchors.centerIn: parent; text: parent.glyph; color: "white"; font.pixelSize: 18 }
                        MouseArea {
                            id: ma; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: parent.act()
                        }
                    }

                    Btn {
                        glyph: "🎙"; tint: win.cyan
                        act: function() { Quickshell.execDetached(["/home/wilmer/.local/bin/blue", "trigger"]); }
                    }
                    Btn {
                        glyph: "⏹"; tint: "#ff6b6b"
                        act: function() { Quickshell.execDetached(["/home/wilmer/.local/bin/blue", "interrupt"]); }
                    }
                    Btn {
                        glyph: "✕"; tint: "#aaaaaa"
                        act: function() { Qt.quit(); }
                    }
                }

                // contador del día
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Hoy: " + win.count + " peticiones"
                    color: Qt.rgba(1, 1, 1, 0.35); font.pixelSize: 10
                }
            }
        }
    }
}
