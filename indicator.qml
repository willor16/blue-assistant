// Indicador flotante del asistente. Lee ~/.config/jarvis/state y muestra
// un orbe de color: gris=reposo, azul=escuchando, amarillo=pensando, verde=hablando.
//
// Probar (sin tocar Caelestia):   qs -p ~/.local/share/jarvis/indicator.qml
// Si te gusta, añade a autostart:  exec-once = qs -p ~/.local/share/jarvis/indicator.qml
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    PanelWindow {
        id: win
        anchors { bottom: true; right: true }
        margins { bottom: 60; right: 60 }
        implicitWidth: 22
        implicitHeight: 22
        color: "transparent"
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

        property string st: "idle"

        FileView {
            id: stateFile
            path: Qt.resolvedUrl("file://" + Quickshell.env("HOME") + "/.config/jarvis/state")
            watchChanges: true
            onFileChanged: reload()
            onLoaded: win.st = text().split("\n")[0].trim() || "idle"
        }

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: win.st === "listening" ? "#4aa3ff"
                 : win.st === "thinking"  ? "#ffcc44"
                 : win.st === "speaking"  ? "#46d160"
                 : "#555555"
            opacity: win.st === "idle" ? 0.35 : 0.95

            // pulso suave cuando esta activo
            SequentialAnimation on scale {
                running: win.st !== "idle"
                loops: Animation.Infinite
                NumberAnimation { from: 1.0; to: 1.25; duration: 600; easing.type: Easing.InOutQuad }
                NumberAnimation { from: 1.25; to: 1.0; duration: 600; easing.type: Easing.InOutQuad }
            }
            Behavior on color { ColorAnimation { duration: 200 } }
        }
    }
}
