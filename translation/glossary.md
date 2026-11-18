# Glossary (binding)

| Japanese | Reading | English | Context / note |
|---|---|---|---|
| 独 | doku | Germany | short form in captions, e.g. 独、ラインラント進駐 |
| ヒトラー | Hitorā | Hitler | |
| 全自動 | zenjidō | Automation | menu (lit. "fully automatic"); 全自動 開始 → "Start automation"; was "Full auto" |
| 全補給 / 全占領 / 全工事 / 全移動 ＯＮ/ＯＦＦ | zen-hokyū … | Auto supply / Auto occupy / Auto works / Auto move ON/OFF | Automation submenu; was "All …" |
| 累積度 | ruisekido | Soil | turn screen, ground condition from accumulated weather: 通常 Normal / 雨 Wet / 雪 Snw; lit. "accumulation level"; "Total" made no sense; "Soil" (not "Terrain") so it fits the big font |
| 大勝利 | daishōri | Great victory | campaign outcome (win before the map's great-victory date; `docs/notes/campaign.md`); turn screen label "GREAT" (added line, no JP original) |
| テイチ ショコク (低地諸国) | teichi shokoku | Benelux | scenario name (8 chars); lit. "Low Countries" – Netherlands, Belgium, Luxembourg; "Low Ctry" was unclear |
| ヒトラー内閣成立 | Hitorā naikaku seiritsu | Hitler becomes Chancellor | lit. "Hitler cabinet formed" |
| 総統 | sōtō | Führer | |
| ヒンデンブルグ | Hindenburugu | Hindenburg | |
| ベルサイユ条約 | Berusaiyu jōyaku | Treaty of Versailles | |
| ミュンヘン一揆 | Myunhen ikki | Munich Putsch | not "Beer Hall Putsch" (keep the place name, as in JP) |
| ミュンヘン会談 | Myunhen kaidan | Munich Conference | |
| ラインラント | Rainranto | Rhineland | |
| 進駐 | shinchū | occupy (troops move in) | |
| 日独防共協定 | Nichi-Doku bōkyō kyōtei | Anti-Comintern Pact | |
| オーストリア | Ōsutoria | Austria | |
| 併合 | heigō | annex | |
| ズデーテン | Zudēten | Sudetenland | |
| 割譲 | katsujō | cede | |
| チェコ | Cheko | Czechoslovakia | the state of 1939, not the Czech Republic |
| 解体 | kaitai | break up | |
| 独ソ不可侵条約 | Doku-So fukashin jōyaku | German-Soviet Pact | full: German-Soviet Non-Aggression Pact; short form for space |
| 調印 / 締結 | chōin / teiketsu | signed | |
| ホヘイ / ヘイ | hohei / hei | Infantry / Inf | 8-char names; ホヘイ ３９ → `Inf   39` |
| ジュウホヘイ | jū-hohei | Hvy Inf | |
| キヘイ | kihei | Cavalry | |
| ホウ | hō | Gun | weapons/units, e.g. ７５㎜ホウＬ２４ → `75㎜ L24` (gun implied when L is given) |
| ヤホウ | yahō | How (howitzer) | lit. field gun; ７．２ｉｎヤホウ → `7.2inHow` |
| カノン | kanon | Gun | long-barrel gun, `150㎜ Gun` |
| キカンホウ | kikanhō | AC (autocannon) | `20㎜ AC` |
| ＡＡホウ | AA-hō | AA | `88㎜ AA` |
| バクダン | bakudan | Bomb | `250㎏Bomb` |
| ロケット | roketto | Rkt / Rocket | |
| トラック | torakku | Trck / Trk | |
| ホキュウ | hokyū | Sup (supply) | ホキュウトラック → `SupTruck` |
| トシ | toshi | City | terrain |
| クウコウ | kūkō | Airfield / Airfd | terrain; with owner tag `Airfd B1` |
| シュト | shuto | Capital / Cap. | terrain |
| ミナト | minato | Port | terrain |
| トウケツ | tōketsu | Fr. (frozen) | terrain |
| ホウカイ / コワレ | hōkai / koware | Dmg (damaged) | terrain |
| テツドウ / テッキョウ | tetsudō / tekkyō | Rail / RlBr | terrain; ユーロ (European standard gauge) → Ger, ロシア (Russian broad gauge) → RU: `Rail Ger`, `RlBr Ger` ("EU" sounds wrong for 1941) |
| 索敵レベル | sakuteki reberu | Fog for | system menu; the level says who plays under fog of war |
| 初級 / 中級 / 上級 | shokyū / chūkyū / jōkyū | None / All / You | fog levels, lit. basic / intermediate / advanced: no fog / fog for everyone / fog for the player only; 2 cells (32 px) |
| Ｆｔ | – | Ft (Front) | Soviet fronts in army names, kept |
| ドイツ　テイコク | Doitsu teikoku | Dt.Reich | the player's faction (armies table); lit. "German Reich", the historical term – not "Germany" as in the EN patch. "Germany" stays for 独 and the country in story texts |
| 決定 | kettei | Defend | unit command: end the unit's move and hold (clearer than "OK", as in the EN patch) |
| 武装 | busō | Rearm | unit command: change weapons/loadout; error 13 "Cannot rearm here" |
| 中止 | chūshi | Quit | Record menu, fourth entry (`$0EF253`): asks Cancel / Exec. and then leaves the game for the title menu (`$0118E8`). Was "Cancel" until 15.11.2026, which read like closing the menu; 取消 stays "Cancel" |

## Campaign briefings and results (`translation/script/brief-*.toml`)

| Japanese | Reading | English | Context / note |
|---|---|---|---|
| 総統訓令第Ｎ号 | sōtō kunrei dai N gō | Führer Directive No. N | title row |
| ―ファル・ＸＸ― | faru | – Case White – etc. | ヴァイス White, ゲルプ Yellow, ロート Red; Weserübung keeps the German name |
| ―ＸＸ作戦― | sakusen | – Operation Sea Lion – | operation names in their usual English form: Sea Lion, Marita, Barbarossa, Typhoon, Blue (ブラウ), Winter Storm (ヴィンターシュツルム), Uranus, Saturn, Citadel, Crusader, Torch, Husky, Shingle, Overlord, Lüttich, Market Garden, Watch on the Rhine (ラインの守り), Supercharge |
| 同盟 | dōmei | Allies: | heading of the ally list; entries `R1 - Leeb` (colour + slot as in the JP, full names) |
| わが部隊 / わが軍 | waga butai / waga gun | our units / our forces | first person plural, the player's side |
| 軍集団 | gun shūdan | Army Group | 北方/中央/南方 → North/Centre/South |
| 装甲部隊 / 装甲軍 | sōkō butai / sōkō gun | panzer units / Panzer Army | |
| 第Ｎ軍 | dai N gun | Nth Army | 英第８軍 → British Eighth Army |
| 空挺 | kūtei | airborne | |
| 制空権 / 制海権 | seikūken / seikaiken | air superiority / command of the sea | |
| 死守命令 | shishu meirei | stand-fast order | |
| 渡河点 | tokaten | river crossing | |
| ビシー | Bishī | Vichy | |
| ヴィルテンブルフ | Virutenburufu | Wildenbruch | Pfeffer-Wildenbruch, Budapest; misspelt in the JP briefing |

## Intro graphics (`translation/script/graphics.toml`)

| Japanese | Reading | English | Context / note |
|---|---|---|---|
| 資料提供 | shiryō teikyō | Courtesy of | credits screen; lit. "material provided by"; the magazine logos 戦車マガジン (Sensha Magazine) and 航空情報 (Kōkū Jōhō) stay as logos |
| ドイツ電撃作戦 | Doitsu dengeki sakusen | German Blitzkrieg | game subtitle; on the title screen only "Blitzkrieg" (120 px between the dashes) |
| – | – | Language: English / Deutsch / Français / Español / Japanese | row the port adds to the System settings screen (no JP original); each language named in its own language, except "Japanese" not 日本語 |
| – | – | Fast enemy turn: ON / OFF; Enemy battles: 1x / 2x / 4x / MAX | System settings rows the port adds (no JP original): automatic fast-forward of the computer's turn, and the speed of the battles in it; values the same in every language |
| – | – | Restart | Record menu row the port puts in place of "Give up" in the campaign (no JP original), also the title of its Cancel / Exec. dialog: begins the map in play again |
| – | – | CAMPAIGN START 1939 | title menu row the port adds (start year of the campaign, no JP original); was "START 1939", unclear without knowing the function |
