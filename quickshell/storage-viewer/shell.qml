import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "Model.js" as Model

// Standalone Quickshell config: a small disk icon that opens a storage panel.
// Works on any Wayland compositor with layer-shell. Colors come from the Qt
// system palette, so the panel follows the system theme.
//
// Run:     qs -c storage-viewer
// Toggle:  qs -c storage-viewer ipc call storage-viewer toggle
//
// Environment (all optional):
//   STORAGE_VIEWER_TERMINAL  command used for "Open TUI" (default xdg-terminal-exec)
//   STORAGE_VIEWER_HIDE_ICON set to 1 to hide the icon and use the IPC call only
//   STORAGE_VIEWER_EDGE      "top" (default) or "bottom"
ShellRoot {
  id: shell

  property bool open: false
  readonly property bool atBottom: Quickshell.env("STORAGE_VIEWER_EDGE") === "bottom"
  readonly property bool hideIcon: Quickshell.env("STORAGE_VIEWER_HIDE_ICON") === "1"

  SystemPalette { id: pal }

  readonly property color urgent: Qt.hsla(0.0, 0.6, 0.55, 1)
  readonly property string status: Model.status(backend.payload, 75, 90)

  Backend {
    id: backend
    active: shell.open
  }

  function openTui() {
    var term = Quickshell.env("STORAGE_VIEWER_TERMINAL") || "xdg-terminal-exec"
    var cmd = term.split(" ").filter(function(p) { return p.length > 0 })
    cmd.push(backend.script)
    Quickshell.execDetached(cmd)
    shell.open = false
  }

  IpcHandler {
    target: "storage-viewer"
    function toggle(): void { shell.open = !shell.open }
    function open(): void { shell.open = true }
    function close(): void { shell.open = false }
  }

  // ---- the icon ----------------------------------------------------------
  PanelWindow {
    visible: !shell.hideIcon
    anchors { top: !shell.atBottom; bottom: shell.atBottom; right: true }
    margins { top: 8; bottom: 8; right: 8 }
    implicitWidth: 38
    implicitHeight: 38
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "storage-viewer-icon"

    Rectangle {
      anchors.fill: parent
      radius: 10
      color: Qt.rgba(pal.window.r, pal.window.g, pal.window.b, 0.92)
      border.width: 1
      border.color: Qt.rgba(pal.windowText.r, pal.windowText.g, pal.windowText.b, 0.2)

      Donut {
        anchors.centerIn: parent
        width: 26
        height: 26
        thickness: 0.22
        trackColor: Qt.rgba(pal.windowText.r, pal.windowText.g, pal.windowText.b, 0.22)
        segments: {
          var d = Model.homeDisk(backend.payload)
          if (!d) return []
          return [{ fraction: d.used, color: shell.status === "bad" ? shell.urgent : pal.highlight }, { fraction: d.free, color: "transparent" }]
        }
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: shell.open = !shell.open
      }
    }
  }

  // ---- the panel ---------------------------------------------------------
  PanelWindow {
    id: panel
    visible: shell.open
    anchors { top: !shell.atBottom; bottom: shell.atBottom; right: true }
    margins { top: 54; bottom: 54; right: 8 }
    implicitWidth: 300
    implicitHeight: Math.min(flick.contentHeight + 36, (screen ? screen.height : 900) - 120)
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "storage-viewer-panel"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    Rectangle {
      anchors.fill: parent
      radius: 14
      color: Qt.rgba(pal.window.r, pal.window.g, pal.window.b, 0.97)
      border.width: 1
      border.color: Qt.rgba(pal.windowText.r, pal.windowText.g, pal.windowText.b, 0.2)

      Flickable {
        id: flick
        anchors.fill: parent
        anchors.margins: 18
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        focus: true
        Keys.onEscapePressed: shell.open = false

        Content {
          id: content
          width: flick.width
          payload: backend.payload
          scanning: backend.scanning
          failed: backend.failed
          foreground: pal.windowText
          accent: pal.highlight
          urgent: shell.urgent
          fontFamily: Qt.application.font.family
          onRescanRequested: backend.refreshAll(true)
          onOpenTuiRequested: shell.openTui()
        }
      }
    }
  }
}
