import QtQuick
import "Model.js" as Model

// Compact panel body, shared by the Omarchy plugin and the standalone
// Quickshell config. Pure QtQuick: the host passes in its theme colors and font
// and reacts to the signals. Text is always plain, because file names are
// untrusted input. The detailed charts live in the terminal UI.
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
  property int itemCount: 5

  signal rescanRequested()
  signal openTuiRequested()

  // ---- derived theme palette --------------------------------------------
  // Hues are rotated from the theme accent so they follow theme changes.
  readonly property real lightness: Math.min(0.72, Math.max(0.5, foreground.hslLightness))
  readonly property color dim: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.55)
  readonly property color track: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.14)

  function tierColor(tier) {
    if (tier === "safe") return Qt.hsla(0.36, 0.5, lightness, 1)
    if (tier === "keep") return Qt.hsla(0.58, 0.5, lightness, 1)
    return Qt.hsla(0.11, 0.65, lightness, 1)
  }
  function usageColor(pct) {
    if (pct >= criticalPercent) return urgent
    if (pct >= warnPercent) return Qt.hsla(0.11, 0.65, lightness, 1)
    return Qt.hsla(0.36, 0.5, lightness, 1)
  }

  readonly property var home: payload ? payload.home : null
  readonly property var rows: Model.diskRows(payload)
  readonly property var topItems: Model.topBySize(payload, itemCount)
  readonly property var homeDisk: Model.homeDisk(payload)

  spacing: 14 * unit
  width: parent ? parent.width : 280

  // ---- small building blocks --------------------------------------------
  component Label: Text {
    textFormat: Text.PlainText
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: 12 * root.unit
    elide: Text.ElideRight
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

  component Pill: Rectangle {
    id: pill
    property string label: ""
    signal clicked()
    implicitWidth: pillText.implicitWidth + 22 * root.unit
    implicitHeight: pillText.implicitHeight + 10 * root.unit
    radius: height / 2
    color: area.containsMouse ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.2) : root.track
    Label { id: pillText; anchors.centerIn: parent; text: pill.label; font.pixelSize: 11 * root.unit; font.bold: true }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: pill.clicked() }
  }

  // ---- hero: a little ring and the number that matters ------------------
  Row {
    spacing: 14 * root.unit
    anchors.horizontalCenter: parent.horizontalCenter

    Donut {
      id: donut
      width: 68 * root.unit
      height: width
      thickness: 0.16
      rounded: true
      fontFamily: root.fontFamily
      textColor: root.foreground
      subColor: root.dim
      trackColor: root.track
      segments: root.homeDisk
        ? [{ fraction: root.homeDisk.used, color: root.usageColor(root.homeDisk.percent) },
           { fraction: root.homeDisk.free, color: "transparent" }]
        : []
      centerText: root.homeDisk ? Math.round(root.homeDisk.percent) + "%" : ""
    }

    Column {
      anchors.verticalCenter: parent.verticalCenter
      spacing: 2 * root.unit
      Label {
        text: root.homeDisk ? Model.humanSize(root.homeDisk.free) + " free" : (root.failed ? "no data" : "...")
        font.pixelSize: 22 * root.unit
        font.bold: true
        color: root.homeDisk ? root.usageColor(root.homeDisk.percent) : root.dim
      }
      Label {
        visible: !!root.homeDisk
        text: root.homeDisk ? "of " + Model.humanSize(root.homeDisk.total) : ""
        color: root.dim
        font.pixelSize: 11 * root.unit
      }
    }
  }

  // ---- the two mounts that matter ---------------------------------------
  Column {
    width: parent.width
    spacing: 9 * root.unit
    visible: root.rows.length > 0

    Repeater {
      model: root.rows
      Column {
        required property var modelData
        width: root.width
        spacing: 4 * root.unit
        Item {
          width: parent.width
          height: mountLabel.implicitHeight
          Label { id: mountLabel; text: modelData.label; font.bold: true; font.pixelSize: 11 * root.unit }
          Label {
            anchors.right: parent.right
            text: Model.humanSize(modelData.used) + " / " + Model.humanSize(modelData.total)
            color: root.dim
            font.pixelSize: 11 * root.unit
          }
        }
        Bar { width: parent.width; fraction: modelData.percent / 100; fill: root.usageColor(modelData.percent) }
      }
    }
  }

  // ---- top storage users: the biggest items in home ---------------------
  Column {
    width: parent.width
    spacing: 7 * root.unit
    visible: root.topItems.length > 0

    Label { text: "space hogs"; color: root.dim; font.pixelSize: 10.5 * root.unit; font.letterSpacing: 0.8 }
    Repeater {
      model: root.topItems
      Item {
        required property var modelData
        width: root.width
        height: nameText.implicitHeight
        Rectangle {
          id: dot
          width: 7 * root.unit
          height: width
          radius: width / 2
          color: root.tierColor(modelData.tier)
          anchors.verticalCenter: parent.verticalCenter
        }
        Label {
          id: nameText
          x: dot.width + 8 * root.unit
          width: parent.width - x - 44 * root.unit
          text: modelData.rel
          elide: Text.ElideMiddle
          font.pixelSize: 11.5 * root.unit
        }
        Label {
          anchors.right: parent.right
          text: Model.humanSize(modelData.size)
          font.bold: true
          font.pixelSize: 11.5 * root.unit
        }
      }
    }
  }

  Label {
    width: parent.width
    visible: root.scanning && !root.home
    text: "looking around your home folder..."
    color: root.dim
    font.pixelSize: 11 * root.unit
    horizontalAlignment: Text.AlignHCenter
  }

  // ---- actions -----------------------------------------------------------
  Row {
    spacing: 8 * root.unit
    anchors.horizontalCenter: parent.horizontalCenter
    Pill { label: root.scanning ? "scanning..." : "rescan"; onClicked: if (!root.scanning) root.rescanRequested() }
    Pill { label: "open tui"; onClicked: root.openTuiRequested() }
  }
}
