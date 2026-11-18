# Typeface of the English text

Nunito Sans (The Nunito Sans Project Authors, SIL Open Font License 1.1, `OFL.txt`; the licence
declares no reserved font name). `tools/hd/typeface.py` draws the text of the translated ROM and
of the HD pack from these files, so the glyphs are part of what a release ships.

Both files are fixed cuts of the variable font `NunitoSans[YTLC,opsz,wdth,wght].ttf` from
github.com/google/fonts (`ofl/nunitosans`), made with fontTools:

    fonttools varLib.instancer NunitoSans-VF.ttf wght=500 wdth=94 opsz=12 YTLC=500 -o NunitoSans-Medium-w94.ttf
    fonttools varLib.instancer NunitoSans-VF.ttf wght=500 wdth=75 opsz=12 YTLC=500 -o NunitoSansCondensed-Medium.ttf

Width 94 instead of 100 for the big size: at 100 "Weather" (66 px in a 64 px box) and "Weather
rule" no longer fit, and ten menu strings fall back to the small size; at 94 the split between
big and small strings is the same as it was with Avenir Next (78 big, 257 small).
