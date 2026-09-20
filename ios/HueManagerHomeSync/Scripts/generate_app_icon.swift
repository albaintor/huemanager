#!/usr/bin/env swift

import AppKit

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: generate_app_icon.swift <output.png>\n", stderr)
    exit(2)
}

let output = CommandLine.arguments[1]
let size = 1024
guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: size,
    pixelsHigh: size,
    bitsPerSample: 8,
    samplesPerPixel: 3,
    hasAlpha: false,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 24
) else {
    fatalError("Unable to create icon bitmap")
}

NSGraphicsContext.saveGraphicsState()
guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
    fatalError("Unable to create graphics context")
}
NSGraphicsContext.current = context

let canvas = NSRect(x: 0, y: 0, width: size, height: size)
let background = NSGradient(colors: [
    NSColor(calibratedRed: 0.02, green: 0.05, blue: 0.12, alpha: 1),
    NSColor(calibratedRed: 0.02, green: 0.12, blue: 0.25, alpha: 1),
    NSColor(calibratedRed: 0.01, green: 0.03, blue: 0.08, alpha: 1),
])!
background.draw(in: canvas, angle: -90)

func strokeArc(
    center: NSPoint,
    radius: CGFloat,
    start: CGFloat,
    end: CGFloat,
    color: NSColor,
    width: CGFloat
) {
    let path = NSBezierPath()
    path.appendArc(
        withCenter: center,
        radius: radius,
        startAngle: start,
        endAngle: end,
        clockwise: false
    )
    path.lineWidth = width
    path.lineCapStyle = .round
    color.setStroke()
    path.stroke()
}

let center = NSPoint(x: 512, y: 590)
let arcColors: [NSColor] = [
    NSColor(calibratedRed: 1.00, green: 0.25, blue: 0.67, alpha: 1),
    NSColor(calibratedRed: 1.00, green: 0.55, blue: 0.15, alpha: 1),
    NSColor(calibratedRed: 1.00, green: 0.90, blue: 0.05, alpha: 1),
    NSColor(calibratedRed: 0.25, green: 0.88, blue: 0.52, alpha: 1),
    NSColor(calibratedRed: 0.12, green: 0.78, blue: 1.00, alpha: 1),
    NSColor(calibratedRed: 0.25, green: 0.38, blue: 1.00, alpha: 1),
]

let startAngle: CGFloat = 200
let endAngle: CGFloat = 520
let segment = (endAngle - startAngle) / CGFloat(arcColors.count)
for (index, color) in arcColors.enumerated() {
    strokeArc(
        center: center,
        radius: 285,
        start: startAngle + CGFloat(index) * segment,
        end: startAngle + CGFloat(index + 1) * segment - 3,
        color: color,
        width: 58
    )
}

// Bulb neck and base.
let neck = NSBezierPath()
neck.move(to: NSPoint(x: 345, y: 375))
neck.line(to: NSPoint(x: 420, y: 285))
neck.line(to: NSPoint(x: 604, y: 285))
neck.line(to: NSPoint(x: 679, y: 375))
neck.lineWidth = 54
neck.lineJoinStyle = .round
neck.lineCapStyle = .round
NSColor(calibratedRed: 0.18, green: 0.55, blue: 1.0, alpha: 1).setStroke()
neck.stroke()

let baseColor = NSColor(calibratedRed: 0.12, green: 0.48, blue: 0.98, alpha: 1)
baseColor.setFill()
NSBezierPath(
    roundedRect: NSRect(x: 398, y: 224, width: 228, height: 62),
    xRadius: 30,
    yRadius: 30
).fill()
NSBezierPath(
    roundedRect: NSRect(x: 440, y: 158, width: 144, height: 48),
    xRadius: 24,
    yRadius: 24
).fill()

// House inside the bulb.
let white = NSColor(calibratedWhite: 1, alpha: 0.96)
white.setFill()
let roof = NSBezierPath()
roof.move(to: NSPoint(x: 370, y: 535))
roof.line(to: NSPoint(x: 512, y: 680))
roof.line(to: NSPoint(x: 654, y: 535))
roof.close()
roof.fill()
NSBezierPath(
    roundedRect: NSRect(x: 400, y: 402, width: 224, height: 150),
    xRadius: 18,
    yRadius: 18
).fill()

let blue = NSColor(calibratedRed: 0.12, green: 0.48, blue: 0.95, alpha: 1)
blue.setFill()
NSBezierPath(
    roundedRect: NSRect(x: 486, y: 402, width: 52, height: 92),
    xRadius: 10,
    yRadius: 10
).fill()
NSBezierPath(
    roundedRect: NSRect(x: 437, y: 500, width: 40, height: 40),
    xRadius: 7,
    yRadius: 7
).fill()
NSBezierPath(
    roundedRect: NSRect(x: 547, y: 500, width: 40, height: 40),
    xRadius: 7,
    yRadius: 7
).fill()

// Light rays.
let raySpecs: [(NSPoint, NSPoint, NSColor)] = [
    (NSPoint(x: 512, y: 936), NSPoint(x: 512, y: 884), arcColors[2]),
    (NSPoint(x: 222, y: 829), NSPoint(x: 184, y: 865), arcColors[0]),
    (NSPoint(x: 802, y: 829), NSPoint(x: 840, y: 865), arcColors[4]),
    (NSPoint(x: 155, y: 600), NSPoint(x: 105, y: 600), arcColors[5]),
    (NSPoint(x: 869, y: 600), NSPoint(x: 919, y: 600), arcColors[3]),
]
for (from, to, color) in raySpecs {
    let ray = NSBezierPath()
    ray.move(to: from)
    ray.line(to: to)
    ray.lineWidth = 28
    ray.lineCapStyle = .round
    color.setStroke()
    ray.stroke()
}

context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fatalError("Unable to encode icon as PNG")
}
let url = URL(fileURLWithPath: output)
try FileManager.default.createDirectory(
    at: url.deletingLastPathComponent(),
    withIntermediateDirectories: true
)
try png.write(to: url, options: .atomic)
