// Rasterize glyphs of a font file with CoreText (used by tools/hdpack.py).
//   swift glyphs.swift FONT_FILE|POSTSCRIPT_NAME PIXEL_SIZE < chars.txt
// stdin: one character per line. stdout per character: "<w> <h> <hex grey bytes> <left> <top>
// <advance>" – the glyph's ink box (row-major, 0 = paper, 255 = ink), the ink's left edge from
// the pen position, its top above the baseline and the advance width (pixels) – or "0 0 -"
// when the font has no glyph.
import CoreGraphics
import CoreText
import Foundation

let args = CommandLine.arguments
guard args.count >= 3 else {
    FileHandle.standardError.write("usage: glyphs.swift FONT_FILE|POSTSCRIPT_NAME PIXEL_SIZE\n".data(using: .utf8)!)
    exit(1)
}
let size = CGFloat(Double(args[2]) ?? 256)
let font: CTFont
if FileManager.default.fileExists(atPath: args[1]) {
    guard let provider = CGDataProvider(filename: args[1]), let cgFont = CGFont(provider) else {
        FileHandle.standardError.write("cannot load font file \(args[1])\n".data(using: .utf8)!); exit(1)
    }
    font = CTFontCreateWithGraphicsFont(cgFont, size, nil, nil)
} else {
    // a PostScript name, e.g. a face inside a collection (.ttc) such as "Charter-Bold"
    font = CTFontCreateWithName(args[1] as CFString, size, nil)
    if (CTFontCopyPostScriptName(font) as String) != args[1] {
        FileHandle.standardError.write("font \(args[1]) not installed\n".data(using: .utf8)!); exit(1)
    }
}
let input = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? ""
var out = ""
for line in input.split(separator: "\n", omittingEmptySubsequences: false) {
    if line.isEmpty { continue }
    let chars = Array(String(line).utf16)
    var glyphs = [CGGlyph](repeating: 0, count: chars.count)
    if !CTFontGetGlyphsForCharacters(font, chars, &glyphs, chars.count) || glyphs[0] == 0 {
        out += "0 0 -\n"; continue
    }
    var g = glyphs[0]
    var rect = CGRect.zero
    CTFontGetBoundingRectsForGlyphs(font, .horizontal, &g, &rect, 1)
    let pad: CGFloat = 4
    let w = Int(ceil(rect.width + 2 * pad)), h = Int(ceil(rect.height + 2 * pad))
    var adv0 = CGSize.zero
    CTFontGetAdvancesForGlyphs(font, .horizontal, &g, &adv0, 1)
    if w <= 2 * Int(pad) || h <= 2 * Int(pad) { out += "0 0 - 0 0 \(Double(adv0.width))\n"; continue }   // no ink (space)
    var buf = [UInt8](repeating: 0, count: w * h)
    let ctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
                        space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
    ctx.setFillColor(gray: 1, alpha: 1)
    ctx.setShouldAntialias(true)
    var pos = CGPoint(x: pad - rect.minX, y: pad - rect.minY)
    CTFontDrawGlyphs(font, &g, &pos, 1, ctx)
    // crop to ink
    var x0 = w, x1 = -1, y0 = h, y1 = -1
    for y in 0..<h { for x in 0..<w where buf[y * w + x] > 0 {
        x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y) } }
    if x1 < 0 { out += "0 0 - 0 0 \(Double(adv0.width))\n"; continue }
    var hex = ""
    hex.reserveCapacity((x1 - x0 + 1) * (y1 - y0 + 1) * 2)
    for y in y0...y1 { for x in x0...x1 { hex += String(format: "%02x", buf[y * w + x]) } }
    // metrics (pixels at PIXEL_SIZE): ink left edge from the pen position, ink top above the
    // baseline, advance width. Memory row 0 is the top of the bitmap.
    var adv = CGSize.zero
    CTFontGetAdvancesForGlyphs(font, .horizontal, &g, &adv, 1)
    let left = Double(x0) - Double(pad - rect.minX)
    let top = Double(h - y0) - Double(pad - rect.minY)
    out += "\(x1 - x0 + 1) \(y1 - y0 + 1) \(hex) \(left) \(top) \(Double(adv.width))\n"
}
FileHandle.standardOutput.write(out.data(using: .utf8)!)
