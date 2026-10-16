import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Model.js" as Model

// Storage Viewer for the Omarchy bar. All data comes from the bundled
// `bin/storage-viewer` CLI (read-only, local only); the body is the shared
// Content.qml, themed from Omarchy's own colors.
Panel {
  id: root
  moduleName: "devinblack001.storage-viewer"
  ipcTarget: "devinblack001.storage-viewer"
  manageIpc: false

  readonly property string overallStatus: Model.status(backend.payload, 75, 90)

  function statusColor() {
    if (overallStatus === "bad") return root.bar.urgent
    if (overallStatus === "warn") return Color.accent
    return root.bar.foreground
  }

  function openTui() {
    var term = Quickshell.env("STORAGE_VIEWER_TERMINAL") || "xdg-terminal-exec"
    var cmd = term.split(" ").filter(function(p) { return p.length > 0 })
    cmd.push(backend.script)
    Quickshell.execDetached(cmd)
    root.close()
  }

  Backend {
    id: backend
    active: root.opened
  }

  IpcHandler {
    target: "devinblack001.storage-viewer"
    function open() { root.open() }
    function close() { root.close() }
    function toggle() { root.toggle() }
    function show() { root.open() }
    function hide() { root.close() }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) backend.refreshDisks()

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf0a0"  // nf-fa-hdd_o (U+F0A0)
    active: root.overallStatus === "bad" || root.overallStatus === "warn"
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(300))
    contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(520))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: scrollArea
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Content {
          id: content
          width: scrollArea.width
          payload: backend.payload
          scanning: backend.scanning
          failed: backend.failed
          foreground: root.bar.foreground
          accent: Color.accent
          urgent: root.bar.urgent
          fontFamily: root.bar.fontFamily
          unit: Style.space(1)
          onRescanRequested: backend.refreshAll(true)
          onOpenTuiRequested: root.openTui()
        }
      }
    }
  }
}
