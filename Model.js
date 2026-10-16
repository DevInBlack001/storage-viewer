.pragma library

// Pure helpers shared by every front end. No UI, no colors, no I/O.

function humanSize(n) {
  n = Math.max(0, Number(n) || 0)
  var units = ["B", "K", "M", "G", "T", "P"]
  var i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  if (i === 0) return Math.floor(n) + "B"
  return (n < 10 ? n.toFixed(1) : Math.round(n).toString()) + units[i]
}

function percent(part, whole) {
  return whole > 0 ? Math.max(0, Math.min(100, part * 100 / whole)) : 0
}

function daysLabel(days) {
  if (days < 14) return Math.max(0, Math.floor(days)) + "d"
  if (days < 60) return Math.floor(days / 7) + "w"
  if (days < 730) return Math.round(days / 30.4) + "mo"
  return Math.floor(days / 365) + "y"
}

function ageLabel(mtime, nowSeconds) {
  if (!mtime || mtime <= 0) return "?"
  return daysLabel((nowSeconds - mtime) / 86400)
}

function bucketLabels(bounds) {
  if (!bounds || bounds.length === 0) return []
  var out = ["< " + daysLabel(bounds[0])]
  for (var i = 1; i < bounds.length; i++) out.push(daysLabel(bounds[i - 1]) + " - " + daysLabel(bounds[i]))
  out.push("> " + daysLabel(bounds[bounds.length - 1]))
  return out
}

function tierLabel(tier) {
  if (tier === "safe") return "SAFE"
  if (tier === "keep") return "KEEP"
  return "REVIEW"
}

// The two filesystems worth showing: where / lives and where your home lives.
function primaryDisks(payload) {
  if (!payload) return []
  if (payload.primary && payload.primary.length) return payload.primary
  return payload.disks && payload.disks.length ? [payload.disks[0]] : []
}

// "ok" | "warn" | "bad" | "unknown" for the bar icon, from the fullest of them.
function status(payload, warnPercent, criticalPercent) {
  var list = primaryDisks(payload)
  if (list.length === 0) return "unknown"
  var worst = 0
  for (var i = 0; i < list.length; i++) worst = Math.max(worst, list[i].percent)
  if (worst >= criticalPercent) return "bad"
  if (worst >= warnPercent) return "warn"
  return "ok"
}

// The filesystem the home directory lives on (the last of the primary pair).
function homeDisk(payload) {
  var list = primaryDisks(payload)
  return list.length ? list[list.length - 1] : null
}

function agoLabel(scannedAt, nowSeconds) {
  var s = Math.max(0, nowSeconds - scannedAt)
  if (s < 90) return "just now"
  if (s < 5400) return Math.round(s / 60) + " min ago"
  return Math.round(s / 3600) + " h ago"
}
