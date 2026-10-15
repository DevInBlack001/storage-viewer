import QtQuick
import "Model.js" as Model

// The panel body, shared by the Omarchy plugin and the standalone Quickshell
// config. Pure QtQuick: the host passes in its theme colors and font, and reacts
// to the signals. All text is rendered as plain text, because file names are
// untrusted input.
Column {
  id: root

  // ---- inputs ------------------------------------------------------------
  property var payload: null
  property bool scanning: false
  property bool failed: false
  property color foreground: "#cacccc"
  property color accent: "#6aa0d0"
  property color urgent: "#a55555"
  property string fontFamily: ""
  property real unit: 1.0                // UI scale
  property real warnPercent: 75
  property real criticalPercent: 90
  property real nowSeconds: Date.now() / 1000

  signal rescanRequested()
  signal openTuiRequested()

  // ---- derived theme palette --------------------------------------------
  // Chart hues are rotated from the theme accent, so they follow theme
  // changes. Greys have no hue of their own, so fall back to a fixed start.
  readonly property real baseHue: accent.hslSaturation > 0.12 ? Math.max(0, accent.hslHue) : 0.58
  readonly property real lightness: Math.min(0.72, Math.max(0.5, foreground.hslLightness))
  readonly property color dim: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.55)
  readonly property color track: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.14)

  function seg(i) { return Qt.hsla((baseHue + i * 0.13) % 1, 0.55, lightness, 1) }
  function tierColor(tier) {
    if (tier === "safe") return Qt.hsla(0.36, 0.5, lightness, 1)
    if (tier === "keep") return Qt.hsla(0.58, 0.5, lightness, 1)
    return Qt.hsla(0.11, 0.65, lightness, 1)
  }
  function ageColor(i, n) {
    var t = n <= 1 ? 0 : i / (n - 1)
    return Qt.hsla(0.36 - 0.36 * t, 0.5, lightness, 1)   // green (recent) to red (old)
  }
  function usageColor(pct) {
    if (pct >= criticalPercent) return urgent
    if (pct >= warnPercent) return Qt.hsla(0.11, 0.65, lightness, 1)
    return Qt.hsla(0.36, 0.5, lightness, 1)
  }

  readonly property var home: payload ? payload.home : null
  readonly property var disks: (payload && payload.disks) ? payload.disks : []
  readonly property var mainDisk: Model.homeDisk(payload)

  spacing: 16 * unit
  width: parent ? parent.width : 440

  // ---- small building blocks --------------------------------------------
  component Label: Text {
    textFormat: Text.PlainText
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: 12 * root.unit
    elide: Text.ElideRight
  }

  component Header: Label {
    color: root.dim
    font.pixelSize: 10.5 * root.unit
    font.bold: true
    font.letterSpacing: 1.2
  }

  component Rule: Rectangle {
    width: parent ? parent.width : 0
    height: 1
    color: root.track
  }

  component Bar: Item {
    property real fraction: 0
    property color fill: root.accent
    height: 6 * root.unit
    Rectangle { anchors.fill: parent; radius: height / 2; color: root.track }
    Rectangle {
      width: Math.max(parent.height, parent.width * Math.min(1, Math.max(0, parent.fraction)))
      height: parent.height
      radius: height / 2
      color: parent.fill
      visible: parent.fraction > 0
    }
  }

  component Button: Rectangle {
    id: btn
    property string label: ""
    signal clicked()
    implicitWidth: btnText.implicitWidth + 28 * root.unit
    implicitHeight: btnText.implicitHeight + 12 * root.unit
    radius: 6 * root.unit
    color: area.containsMouse ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.18) : root.track
    Label { id: btnText; anchors.centerIn: parent; text: btn.label; font.bold: true }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: btn.clicked() }
  }

  // ---- hero: donut + headline -------------------------------------------
  Item {
    width: parent.width
    height: donut.height

    Donut {
      id: donut
      width: 104 * root.unit
      height: width
      fontFamily: root.fontFamily
      textColor: root.foreground
      subColor: root.dim
      trackColor: root.track
      segments: {
        var d = root.mainDisk
        if (!d) return []
        var h = root.home ? Math.min(root.home.total, d.used) : 0
        return [
          { fraction: h, color: root.seg(0) },
          { fraction: Math.max(0, d.used - h), color: root.seg(2) },
          { fraction: d.free, color: "transparent" }
        ]
      }
      centerText: root.mainDisk ? Math.round(root.mainDisk.percent) + "%" : "-"
      subText: "used"
    }

    Column {
      anchors.left: donut.right
      anchors.leftMargin: 18 * root.unit
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: 6 * root.unit

      Label {
        width: parent.width
        text: "Storage"
        font.pixelSize: 18 * root.unit
        font.bold: true
      }
      Label {
        width: parent.width
        visible: !!root.mainDisk
        text: root.mainDisk ? Model.humanSize(root.mainDisk.free) + " free of " + Model.humanSize(root.mainDisk.total) : ""
        color: root.mainDisk ? root.usageColor(root.mainDisk.percent) : root.foreground
        font.bold: true
      }
      Label {
        width: parent.width
        visible: !!root.home
        text: root.home ? "Home uses " + Model.humanSize(root.home.total) : ""
        color: root.dim
      }
      Label {
        width: parent.width
        visible: !root.payload
        text: root.failed ? "Could not read storage data." : "Reading disks..."
        color: root.failed ? root.urgent : root.dim
      }
    }
  }

  // ---- disks -------------------------------------------------------------
  Column {
    width: parent.width
    spacing: 10 * root.unit
    visible: root.disks.length > 0

    Rule {}
    Header { text: "DISKS" }
    Repeater {
      model: root.disks
      Column {
        required property var modelData
        width: root.width
        spacing: 5 * root.unit
        Item {
          width: parent.width
          height: mountLabel.implicitHeight
          Label { id: mountLabel; text: modelData.mount; font.bold: true; width: parent.width * 0.4 }
          Label {
            anchors.right: parent.right
            text: Model.humanSize(modelData.used) + " / " + Model.humanSize(modelData.total) + "  " + Math.round(modelData.percent) + "%"
            color: root.dim
          }
        }
        Bar { width: parent.width; fraction: modelData.percent / 100; fill: root.usageColor(modelData.percent) }
      }
    }
  }

  // ---- home breakdown ----------------------------------------------------
  Column {
    width: parent.width
    spacing: 10 * root.unit
    visible: !!root.home

    Rule {}
    Header { text: "HOME" }
    Row {
      width: parent.width
      height: 10 * root.unit
      spacing: 2
      Repeater {
        model: root.home ? root.home.breakdown : []
        Rectangle {
          required property var modelData
          required property int index
          width: Math.max(3, (root.width - 2 * ((root.home ? root.home.breakdown.length : 1) - 1)) * modelData.size / Math.max(1, root.home.total))
          height: parent.height
          radius: 3
          color: root.seg(index)
        }
      }
    }
    Repeater {
      model: root.home ? root.home.breakdown : []
      Item {
        required property var modelData
        required property int index
        width: root.width
        height: nameLabel.implicitHeight
        Rectangle { id: swatch; width: 9 * root.unit; height: width; radius: width / 2; color: root.seg(index); anchors.verticalCenter: parent.verticalCenter }
        Label { id: nameLabel; x: swatch.width + 10 * root.unit; width: parent.width * 0.6; text: modelData.name }
        Label {
          anchors.right: parent.right
          text: Model.humanSize(modelData.size) + "  " + Math.round(Model.percent(modelData.size, root.home.total)) + "%"
          color: root.dim
        }
      }
    }
  }

  // ---- size by last modified ---------------------------------------------
  Column {
    width: parent.width
    spacing: 10 * root.unit
    visible: !!root.home && !!root.home.age && root.home.age.bytes.length > 0

    Rule {}
    Header { text: "SIZE BY LAST MODIFIED" }
    Repeater {
      model: root.home && root.home.age ? Model.bucketLabels(root.home.age.bounds_days) : []
      Item {
        required property string modelData
        required property int index
        readonly property real value: root.home.age.bytes[index] || 0
        readonly property real peak: Math.max.apply(null, root.home.age.bytes) || 1
        width: root.width
        height: 18 * root.unit
        Label { text: modelData; color: root.dim; width: 78 * root.unit; anchors.verticalCenter: parent.verticalCenter }
        Bar {
          x: 86 * root.unit
          width: parent.width - 86 * root.unit - 62 * root.unit
          anchors.verticalCenter: parent.verticalCenter
          fraction: parent.value / parent.peak
          fill: root.ageColor(parent.index, root.home.age.bytes.length)
        }
        Label { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: Model.humanSize(parent.value) }
      }
    }
  }

  // ---- ranked list -------------------------------------------------------
  Column {
    width: parent.width
    spacing: 12 * root.unit
    visible: !!root.home

    Rule {}
    Header { text: "TOP ITEMS, MOST REMOVABLE FIRST" }
    Repeater {
      model: root.home ? root.home.items : []
      Column {
        required property var modelData
        required property int index
        width: root.width
        spacing: 3 * root.unit

        Item {
          width: parent.width
          height: Math.max(chip.height, nameText.implicitHeight)

          Rectangle {
            id: chip
            width: 58 * root.unit
            height: chipText.implicitHeight + 6 * root.unit
            radius: 4 * root.unit
            color: Qt.rgba(root.tierColor(modelData.tier).r, root.tierColor(modelData.tier).g, root.tierColor(modelData.tier).b, 0.22)
            Label { id: chipText; anchors.centerIn: parent; text: Model.tierLabel(modelData.tier); color: root.tierColor(modelData.tier); font.pixelSize: 10 * root.unit; font.bold: true }
          }
          Label { id: sizeText; x: chip.width + 10 * root.unit; width: 48 * root.unit; anchors.verticalCenter: chip.verticalCenter; text: Model.humanSize(modelData.size); font.bold: true }
          Label {
            id: nameText
            x: chip.width + 64 * root.unit
            width: parent.width - x - 40 * root.unit
            anchors.verticalCenter: chip.verticalCenter
            text: "~/" + modelData.rel
            elide: Text.ElideMiddle
          }
          Label { anchors.right: parent.right; anchors.verticalCenter: chip.verticalCenter; text: Model.ageLabel(modelData.mtime, root.nowSeconds); color: root.dim }
        }
        Label {
          x: chip.width
          width: parent.width - 58 * root.unit
          text: modelData.reason + (modelData.blocked ? " (some contents unreadable)" : "")
          color: root.dim
          font.pixelSize: 10.5 * root.unit
          leftPadding: 10 * root.unit
        }
      }
    }

    Label {
      width: parent.width
      visible: !!root.home && root.home.items.length === 0
      text: "Nothing above the size threshold found."
      color: root.dim
    }
  }

  // ---- status + actions --------------------------------------------------
  Column {
    width: parent.width
    spacing: 10 * root.unit

    Rule {}
    Label {
      width: parent.width
      wrapMode: Text.WordWrap
      color: (root.home && (root.home.truncated || root.home.blocked.length > 0)) ? root.usageColor(root.warnPercent) : root.dim
      font.pixelSize: 10.5 * root.unit
      text: {
        if (root.scanning) return "Scanning your home directory..."
        if (!root.home) return ""
        var parts = ["Scanned " + Model.agoLabel(root.home.scanned_at, root.nowSeconds) + ", " + root.home.entries.toLocaleString(Qt.locale(), "f", 0) + " entries"]
        if (root.home.truncated) parts.push("partial: " + root.home.truncated_reason)
        if (root.home.blocked.length > 0) parts.push(root.home.blocked.length + " folders unreadable (permission denied)")
        return parts.join(". ")
      }
    }
    Row {
      spacing: 10 * root.unit
      Button { label: root.scanning ? "Scanning..." : "Rescan"; onClicked: if (!root.scanning) root.rescanRequested() }
      Button { label: "Open TUI"; onClicked: root.openTuiRequested() }
    }
    Label {
      width: parent.width
      text: "Read-only: nothing is ever deleted."
      color: root.dim
      font.pixelSize: 10 * root.unit
    }
  }
}
