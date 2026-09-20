#!/usr/bin/env swift
import AppKit

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: generate_app_icon.swift <output.png>\n", stderr)
    exit(2)
}

let outputPath = CommandLine.arguments[1]
let size = 1024
let rect = NSRect(x: 0, y: 0, width: size, height: size)

let colorSpace = CGColorSpaceCreateDeviceRGB()
let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue)

guard let cgContext = CGContext(
    data: nil,
    width: size,
    height: size,
    bitsPerComponent: 8,
    bytesPerRow: size * 4,
    space: colorSpace,
    bitmapInfo: bitmapInfo.rawValue
) else {
    fatalError("Unable to create RGB CGContext")
}

let context = NSGraphicsContext(cgContext: cgContext, flipped: false)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context

// Full-bleed background. iOS applies the rounded app-icon mask itself.
let background = NSGradient(colors: [
    NSColor(calibratedRed: 0.03, green: 0.13, blue: 0.31, alpha: 1.0),
    NSColor(calibratedRed: 0.05, green: 0.06, blue: 0.19, alpha: 1.0),
    NSColor(calibratedRed: 0.01, green: 0.03, blue: 0.09, alpha: 1.0),
])!
background.draw(in: rect, angle: -90)

func roundedStroke(
    from: NSPoint,
    to: NSPoint,
    width: CGFloat,
    color: NSColor
) {
    let p = NSBezierPath()
    p.move(to: from)
    p.line(to: to)
    p.lineWidth = width
    p.lineCapStyle = .round
    color.setStroke()
    p.stroke()
}

func arc(
    center: NSPoint,
    radius: CGFloat,
    start: CGFloat,
    end: CGFloat,
    width: CGFloat,
    color: NSColor
) {
    let p = NSBezierPath()
    p.appendArc(
        withCenter: center,
        radius: radius,
        startAngle: start,
        endAngle: end,
        clockwise: false
    )
    p.lineWidth = width
    p.lineCapStyle = .round
    color.setStroke()
    p.stroke()
}

// Subtle inner glow.
let glow = NSGradient(colors: [
    NSColor(calibratedRed: 0.05, green: 0.45, blue: 0.85, alpha: 0.23),
    NSColor(calibratedRed: 0.02, green: 0.08, blue: 0.20, alpha: 0.0),
])!
glow.draw(
    fromCenter: NSPoint(x: 512, y: 545),
    radius: 40,
    toCenter: NSPoint(x: 512, y: 545),
    radius: 430,
    options: []
)

// Rainbow bulb outline, intentionally broad and saturated so the icon remains
// readable at SpringBoard sizes.
let center = NSPoint(x: 512, y: 590)
let colors: [NSColor] = [
    NSColor(calibratedRed: 0.96, green: 0.20, blue: 0.83, alpha: 1),
    NSColor(calibratedRed: 1.00, green: 0.39, blue: 0.22, alpha: 1),
    NSColor(calibratedRed: 1.00, green: 0.83, blue: 0.08, alpha: 1),
    NSColor(calibratedRed: 0.50, green: 0.94, blue: 0.20, alpha: 1),
    NSColor(calibratedRed: 0.00, green: 0.88, blue: 0.96, alpha: 1),
    NSColor(calibratedRed: 0.15, green: 0.47, blue: 1.00, alpha: 1),
    NSColor(calibratedRed: 0.48, green: 0.25, blue: 1.00, alpha: 1),
]

let start: CGFloat = 205
let end: CGFloat = 515
let segment = (end - start) / CGFloat(colors.count)
for (index, color) in colors.enumerated() {
    arc(
        center: center,
        radius: 278,
        start: start + CGFloat(index) * segment,
        end: start + CGFloat(index + 1) * segment - 2.0,
        width: 66,
        color: color
    )
}

// Bulb neck.
let neck = NSBezierPath()
neck.move(to: NSPoint(x: 350, y: 390))
neck.curve(
    to: NSPoint(x: 430, y: 300),
    controlPoint1: NSPoint(x: 365, y: 345),
    controlPoint2: NSPoint(x: 400, y: 315)
)
neck.line(to: NSPoint(x: 594, y: 300))
neck.curve(
    to: NSPoint(x: 674, y: 390),
    controlPoint1: NSPoint(x: 624, y: 315),
    controlPoint2: NSPoint(x: 659, y: 345)
)
neck.lineWidth = 66
neck.lineCapStyle = .round
neck.lineJoinStyle = .round
NSColor(calibratedRed: 0.05, green: 0.72, blue: 1.00, alpha: 1).setStroke()
neck.stroke()

let cyan = NSColor(calibratedRed: 0.04, green: 0.69, blue: 1.00, alpha: 1)
roundedStroke(
    from: NSPoint(x: 415, y: 250),
    to: NSPoint(x: 609, y: 250),
    width: 58,
    color: cyan
)
roundedStroke(
    from: NSPoint(x: 458, y: 184),
    to: NSPoint(x: 566, y: 184),
    width: 50,
    color: NSColor(calibratedRed: 0.05, green: 0.52, blue: 1.00, alpha: 1)
)

// House.
let houseColor = NSColor(calibratedRed: 0.89, green: 0.96, blue: 1.00, alpha: 1)
houseColor.setFill()

let roof = NSBezierPath()
roof.move(to: NSPoint(x: 350, y: 545))
roof.line(to: NSPoint(x: 512, y: 700))
roof.line(to: NSPoint(x: 674, y: 545))
roof.close()
roof.fill()

NSBezierPath(
    roundedRect: NSRect(x: 390, y: 410, width: 244, height: 160),
    xRadius: 22,
    yRadius: 22
).fill()

let cutout = NSColor(calibratedRed: 0.03, green: 0.13, blue: 0.28, alpha: 1)
cutout.setFill()
NSBezierPath(
    roundedRect: NSRect(x: 482, y: 410, width: 60, height: 98),
    xRadius: 12,
    yRadius: 12
).fill()

// Light rays.
let rays: [(NSPoint, NSPoint, NSColor)] = [
    (NSPoint(x: 512, y: 915), NSPoint(x: 512, y: 855), colors[2]),
    (NSPoint(x: 260, y: 835), NSPoint(x: 215, y: 880), colors[0]),
    (NSPoint(x: 764, y: 835), NSPoint(x: 809, y: 880), colors[3]),
    (NSPoint(x: 174, y: 610), NSPoint(x: 108, y: 610), colors[6]),
    (NSPoint(x: 850, y: 610), NSPoint(x: 916, y: 610), colors[4]),
]
for (a, b, color) in rays {
    roundedStroke(from: a, to: b, width: 32, color: color)
}

context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()

guard let cgImage = cgContext.makeImage() else {
    fatalError("Unable to create CGImage")
}
let bitmap = NSBitmapImageRep(cgImage: cgImage)
guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fatalError("Unable to encode PNG")
}

let url = URL(fileURLWithPath: outputPath)
try FileManager.default.createDirectory(
    at: url.deletingLastPathComponent(),
    withIntermediateDirectories: true
)
try png.write(to: url, options: .atomic)
print("Generated app icon: \(url.path)")
