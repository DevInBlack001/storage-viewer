import QtQuick
import Quickshell.Io

// Runs the storage-viewer CLI (a sibling `bin/storage-viewer`) and keeps its
// JSON. Two cheap-to-expensive calls: disk usage on a timer, and the home scan
// on demand (the CLI caches it, so reopening the panel is instant).
Item {
  id: root

  // Resolved next to this file; never searched on $PATH.
  readonly property string script: String(Qt.resolvedUrl("bin/storage-viewer")).replace(/^file:\/\//, "")
  property bool active: false          // panel visible: poll faster
  property var payload: null
  property bool failed: false
  property bool scanning: false
  readonly property int maxPayloadBytes: 2 * 1024 * 1024

  function utf8Length(str) {
    var n = 0
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i)
      if (c >= 0xD800 && c <= 0xDBFF && i + 1 < str.length) { n += 4; i++ }
      else if (c <= 0x7F) n += 1
      else if (c <= 0x7FF) n += 2
      else n += 3
    }
    return n
  }

  function parse(raw) {
    raw = String(raw || "")
    if (utf8Length(raw) > maxPayloadBytes) { failed = true; return null }
    try {
      var data = JSON.parse(raw)
      failed = data === null
      return data
    } catch (e) {
      failed = true
      return null
    }
  }

  // Cheap: mounted filesystems only.
  function refreshDisks() {
    if (!disksProc.running) disksProc.running = true
  }

  // Full report. `force` bypasses the CLI's scan cache.
  function refreshAll(force) {
    if (scanProc.running) return
    scanProc.command = force ? [script, "--json", "--refresh"] : [script, "--json"]
    scanning = true
    scanProc.running = true
  }

  Process {
    id: disksProc
    command: [root.script, "--json", "--disks-only"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var d = root.parse(text)
        if (!d) return
        var merged = root.payload || {}
        merged.disks = d.disks
        merged.primary = d.primary
        merged.notes = d.notes
        merged.version = d.version
        root.payload = merged
        root.payloadChanged()
      }
    }
  }

  Process {
    id: scanProc
    command: [root.script, "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var d = root.parse(text)
        root.scanning = false
        if (d) root.payload = d
      }
    }
    onRunningChanged: if (!running) root.scanning = false
  }

  Timer {
    interval: root.active ? 5000 : 60000
    running: true
    repeat: true
    onTriggered: root.refreshDisks()
  }

  Component.onCompleted: { refreshDisks(); refreshAll(false) }
}
