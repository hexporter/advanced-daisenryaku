# Draws the icons for players: 大, the first letter of the 大戦略 title logo, in the logo's colours
# – stone-grey face, brown 3-D edge down-right (colours taken from the title screen,
# docs/notes/release.md "Icon").
#   powershell -ExecutionPolicy Bypass -File tools\make_icon.ps1 [-Preview]
#     Windows launcher: release/windows/icon.ico, the letter on a transparent background, 16–256 px.
#   ... -Mac [-Preview]
#     Mac app: release/macos/AppIcon.iconset/ (icon_16x16.png … icon_512x512@2x.png), the letter on
#     a rounded square in the red of the logo's "Advanced" banner, on Apple's icon grid (824 of 1024
#     px, shadow below). tools/release.sh turns it into AppIcon.icns with iconutil.
# Windows only (System.Drawing, the font Yu Gothic Bold of Windows 10/11). -Preview writes preview
# PNGs on a light and a dark background next to the output (not for the repo).
param([switch]$Mac, [switch]$Preview)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$root   = Split-Path -Parent $PSScriptRoot
$glyph  = [string][char]0x5927            # 大
$family = New-Object System.Drawing.FontFamily('Yu Gothic')

function C([string]$hex) { [System.Drawing.ColorTranslator]::FromHtml("#$hex") }
$faceTop = C 'B8B8B8'; $faceMid = C '929292'; $faceBot = C '6E6E6E'      # stone (AEAEAE/929292/777777)
$edgeNear = C '927757'; $edgeFar = C '573100'                            # brown 3-D edge
$line = C '2A1800'                                                       # outline
$redTop = C 'CE0000'; $redMid = C 'A00000'; $redBot = C '770000'         # banner (CE0000…770000)
$redLine = C '4A0000'

function Pen([System.Drawing.Color]$c, [double]$w) { New-Object System.Drawing.Pen($c, [float]$w) }

# The letter fitted into the square (x0, y0, box): brown edge repeated down-right, then the stone
# face with a top-to-bottom gradient. $n = icon size, for line widths (outline from 32 px).
function Draw-Glyph($g, [double]$x0, [double]$y0, [double]$box, [int]$n) {
    $depth = [Math]::Max(1.0, $box * 0.07)
    $inner = $box - $depth
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddString($glyph, $family, [int][System.Drawing.FontStyle]::Bold, 100.0,
                    (New-Object System.Drawing.PointF(0, 0)), [System.Drawing.StringFormat]::GenericTypographic)
    $b = $path.GetBounds()
    $s = $inner / [Math]::Max($b.Width, $b.Height)
    $m = New-Object System.Drawing.Drawing2D.Matrix
    $m.Translate($x0 + ($inner - $b.Width * $s) / 2, $y0 + ($inner - $b.Height * $s) / 2)
    $m.Scale($s, $s)
    $m.Translate(-$b.X, -$b.Y)
    $path.Transform($m)
    $lw = $box / 48.0

    $steps = [Math]::Max(1, [int][Math]::Ceiling($depth * 2))
    for ($i = $steps; $i -ge 1; $i--) {
        $t = $i / $steps
        $c = [System.Drawing.Color]::FromArgb(255,
            [int]($edgeNear.R + ($edgeFar.R - $edgeNear.R) * $t),
            [int]($edgeNear.G + ($edgeFar.G - $edgeNear.G) * $t),
            [int]($edgeNear.B + ($edgeFar.B - $edgeNear.B) * $t))
        $p = $path.Clone(); $mm = New-Object System.Drawing.Drawing2D.Matrix
        $mm.Translate($depth * $t, $depth * $t); $p.Transform($mm)
        $g.FillPath((New-Object System.Drawing.SolidBrush($c)), $p)
        if ($i -eq $steps -and $n -ge 32) { $g.DrawPath((Pen $line $lw), $p) }
    }
    $r = New-Object System.Drawing.RectangleF([float]$x0, [float]$y0, [float]$box, [float]$box)
    $face = New-Object System.Drawing.Drawing2D.LinearGradientBrush($r, $faceTop, $faceBot, 90.0)
    $blend = New-Object System.Drawing.Drawing2D.ColorBlend(3)
    $blend.Colors = @($faceTop, $faceMid, $faceBot); $blend.Positions = @(0.0, 0.5, 1.0)
    $face.InterpolationColors = $blend
    $g.FillPath($face, $path)
    # outline from 32 px; below, a 1 px line would swallow the strokes – the brown edge separates
    if ($n -ge 32) { $g.DrawPath((Pen $line $lw), $path) }
}

function Rounded([double]$x, [double]$y, [double]$w, [double]$r) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = 2 * $r
    $p.AddArc([float]$x, [float]$y, [float]$d, [float]$d, 180, 90)
    $p.AddArc([float]($x + $w - $d), [float]$y, [float]$d, [float]$d, 270, 90)
    $p.AddArc([float]($x + $w - $d), [float]($y + $w - $d), [float]$d, [float]$d, 0, 90)
    $p.AddArc([float]$x, [float]($y + $w - $d), [float]$d, [float]$d, 90, 90)
    $p.CloseFigure()
    return $p
}

function New-Canvas([int]$n) {
    $bmp = New-Object System.Drawing.Bitmap($n, $n, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'; $g.PixelOffsetMode = 'HighQuality'; $g.Clear([System.Drawing.Color]::Transparent)
    return $bmp, $g
}

# Windows: the letter alone
function Render-Windows([int]$n) {
    $bmp, $g = New-Canvas $n
    $pad = [Math]::Max(0.5, $n * 0.02)
    Draw-Glyph $g $pad $pad ($n - 2 * $pad) $n
    $g.Dispose(); return $bmp
}

# Mac: Apple's grid – rounded square 824/1024 at 100/1024, corner radius 185/1024, shadow below;
# the letter in the middle 60 % of the square
function Render-Mac([int]$n) {
    $bmp, $g = New-Canvas $n
    $u = $n / 1024.0
    $x = 100 * $u; $w = 824 * $u; $rad = 185 * $u
    for ($k = 8; $k -ge 1; $k--) {                       # soft shadow: widening, fading layers
        $sp = Rounded ($x - $k * 1.5 * $u) ($x + (12 + $k * 1.5) * $u) ($w + $k * 3 * $u) ($rad + $k * 1.5 * $u)
        $g.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(14, 0, 0, 0))), $sp)
    }
    $sq = Rounded $x $x $w $rad
    $r = New-Object System.Drawing.RectangleF([float]$x, [float]$x, [float]$w, [float]$w)
    $bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush($r, $redTop, $redBot, 90.0)
    $blend = New-Object System.Drawing.Drawing2D.ColorBlend(3)
    $blend.Colors = @($redTop, $redMid, $redBot); $blend.Positions = @(0.0, 0.45, 1.0)
    $bg.InterpolationColors = $blend
    $g.FillPath($bg, $sq)
    $g.DrawPath((Pen $redLine ([Math]::Max(0.5, 4 * $u))), $sq)
    $box = $w * 0.62
    Draw-Glyph $g ($x + ($w - $box) / 2) ($x + ($w - $box) / 2) $box ([int]($box))
    $g.Dispose(); return $bmp
}

# PNG bytes; the leading comma keeps PowerShell from unrolling the array into single bytes
function Png($bmp) { $ms = New-Object System.IO.MemoryStream; $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); return ,$ms.ToArray() }

function Save-Preview([object[]]$bitmaps, [string]$dir) {
    $sum = 0; foreach ($b in $bitmaps) { $sum += $b.Width }
    $width = [int]($sum + 10 * ($bitmaps.Count + 1)); $height = 20 + ($bitmaps | ForEach-Object Height | Measure-Object -Maximum).Maximum
    foreach ($bgc in 'F3F3F3', '202020') {
        $pv = New-Object System.Drawing.Bitmap($width, [int]$height)
        $g = [System.Drawing.Graphics]::FromImage($pv); $g.Clear((C $bgc)); $px = 10
        foreach ($b in $bitmaps) { $g.DrawImage($b, $px, 10, $b.Width, $b.Height); $px += $b.Width + 10 }
        $g.Dispose()
        $name = if ($bgc -eq 'F3F3F3') { 'icon-preview-light.png' } else { 'icon-preview-dark.png' }
        $p = Join-Path $dir $name; $pv.Save($p); Write-Output "preview: $p"
    }
}

if ($Mac) {
    $dir = Join-Path $root 'release\macos\AppIcon.iconset'
    New-Item -ItemType Directory -Force $dir | Out-Null
    $made = @{}
    foreach ($base in 16, 32, 128, 256, 512) {
        foreach ($scale in 1, 2) {
            $n = $base * $scale
            if (-not $made.ContainsKey($n)) { $made[$n] = Render-Mac $n }
            $name = if ($scale -eq 1) { "icon_${base}x${base}.png" } else { "icon_${base}x${base}@2x.png" }
            [System.IO.File]::WriteAllBytes((Join-Path $dir $name), (Png $made[$n]))
        }
    }
    Write-Output "iconset: $dir (10 images, 16-1024 px)"
    if ($Preview) { Save-Preview @($made[16], $made[32], $made[64], $made[128], $made[256], $made[512]) (Split-Path $dir) }
    return
}

$out = Join-Path $root 'release\windows\icon.ico'
$sizes = 16, 20, 24, 32, 40, 48, 64, 128, 256
$images = foreach ($n in $sizes) {
    $bmp = Render-Windows $n
    [pscustomobject]@{ Size = $n; Png = (Png $bmp); Bitmap = $bmp }
}
# ICO: header, one 16-byte entry per image, then the PNG data (Windows Vista+)
$fs = [System.IO.File]::Create($out)
$bw = New-Object System.IO.BinaryWriter($fs)
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$images.Count)
$offset = 6 + 16 * $images.Count
foreach ($im in $images) {
    $d = if ($im.Size -ge 256) { 0 } else { $im.Size }
    $bw.Write([byte]$d); $bw.Write([byte]$d); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([uint16]1); $bw.Write([uint16]32)
    $bw.Write([uint32]$im.Png.Length); $bw.Write([uint32]$offset)
    $offset += $im.Png.Length
}
foreach ($im in $images) { $bw.Write($im.Png) }
$bw.Close()
Write-Output "icon: $out ($($images.Count) sizes, $((Get-Item $out).Length) bytes)"
if ($Preview) { Save-Preview @($images | ForEach-Object Bitmap) (Split-Path $out) }
