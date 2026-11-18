Advanced Daisenryaku for Windows
================================

A native port of "Advanced Daisenryaku - Deutsch Dengeki Sakusen" (Sega Mega Drive, 1991) with an
English translation. Version @VERSION@ (build @BUILD@), Windows 10 (1903) or 11, 64-bit.

You need your own ROM
---------------------
The game contains no game data. On the first start it asks for your own dump of the Japanese
cartridge (Japan, Rev A; 1,048,576 bytes, CRC32 E0D5E18A; a plain .md/.bin file, not zipped).
The English translation is applied to a copy; your file is not changed.

Start
-----
Unpack the folder anywhere and start "Advanced Daisenryaku.exe". The program is not signed:
Windows SmartScreen may warn the first time - "More info", then "Run anyway".

Language
--------
English, Deutsch, Français, Español or the original Japanese. The game starts in your Windows
display language when it is one of these, otherwise in English. To change it: System menu →
System → "Language"; that choice is kept.

Keys
----
F9   zoomed-out map          F10  HD text and tiles on/off
Quit: title menu "QUIT GAME", or close the window.
Controller and keyboard layout: settings.ini in the data folder.

Your files
----------
%APPDATA%\Advanced Daisenryaku   (paste this into the Explorer address bar)
    ad-tr.srm       save games (the cartridge's battery memory) - back this up
    settings.ini    controls and display
    run.log         messages of the last start (please attach to bug reports)

Licences
--------
See the files next to this one: LICENSE (PolyForm Noncommercial 1.0.0) with PERMISSIONS.txt,
THIRD-PARTY-LICENSES.md, SDL-LICENSE.txt, FONT-LICENSE.txt (Nunito Sans, SIL OFL 1.1).
Free, noncommercial use only.
"Advanced Daisenryaku" is a trademark of its owners; this is an unofficial fan project.
