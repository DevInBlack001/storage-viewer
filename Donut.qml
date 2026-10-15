import QtQuick

// Ring chart. `segments` is [{ fraction, color }], drawn clockwise from the top.
Canvas {
  id: root
  property var segments: []
  property color trackColor: "#33808080"
  property real thickness: 0.2  // ring width as a fraction of the diameter
  property string centerText: ""
  property string subText: ""
  property color textColor: "white"
  property color subColor: "gray"
  property string fontFamily: ""
  property real gap: 0.02  // radians left between segments

  implicitWidth: 96
  implicitHeight: 96

  onSegmentsChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()
  onTrackColorChanged: requestPaint()

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    var size = Math.min(width, height)
    var lw = size * root.thickness
    var r = size / 2 - lw / 2 - 1
    var cx = width / 2, cy = height / 2
    var start = -Math.PI / 2
    ctx.lineWidth = lw
    ctx.lineCap = "butt"

    ctx.strokeStyle = root.trackColor
    ctx.beginPath()
    ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.stroke()

    var total = 0
    for (var i = 0; i < segments.length; i++) total += Math.max(0, segments[i].fraction)
    if (total <= 0) return
    var angle = start
    for (var j = 0; j < segments.length; j++) {
      var sweep = Math.max(0, segments[j].fraction) / total * Math.PI * 2
      if (sweep <= 0.001) continue
      var a0 = angle + (sweep > root.gap * 3 ? root.gap / 2 : 0)
      var a1 = angle + sweep - (sweep > root.gap * 3 ? root.gap / 2 : 0)
      ctx.strokeStyle = segments[j].color
      ctx.beginPath()
      ctx.arc(cx, cy, r, a0, a1)
      ctx.stroke()
      angle += sweep
    }
  }

  Column {
    anchors.centerIn: parent
    spacing: 0
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: root.centerText
      color: root.textColor
      font.family: root.fontFamily
      font.pixelSize: Math.max(10, root.height * 0.19)
      font.bold: true
    }
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: root.subText
      color: root.subColor
      font.family: root.fontFamily
      font.pixelSize: Math.max(8, root.height * 0.1)
    }
  }
}
