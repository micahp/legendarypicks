# NCAAF audio streams

**Updated:** 2026-10-13

**Scope:** Varsity Network direct audio feeds found for the 2026 FBS season

## Coverage

The initial October 10 live query returned 20 Varsity audio records, including eight football feeds across seven games. That was a live snapshot, not the full Varsity event catalog. Searching the published season and future event records found feeds for schools beyond the AP Top 25.

The official NCAA standings roster contained 138 FBS schools when checked. Of these, 77 had a qualifying Varsity game-audio event record in the catalog search: 72 direct streams passed playback checks and are listed below, while five discovered direct URLs failed. For the other 61 schools, no qualifying Varsity event record was found in the records searched. This does not establish that those schools lack radio coverage through another provider or an unindexed Varsity page.

Discovery included published audio records with a football/game association and game-like records without `gameUid` when the title and date matched the FBS schedule. Unlinked records included Iowa, Arkansas, Missouri, Purdue, South Carolina, and Vanderbilt. A Stanford event titled “Stanford @ Clemson” was excluded because it did not match an FBS football game on that date.

The streams were checked on 2026-10-13. `ffprobe` identified each format and an `ffmpeg` decode of three seconds succeeded. The configured inventory contains 51 MP3 and 21 AAC feeds. These are event-linked publisher URLs: the event pages and direct URLs can rotate between games, so the inventory should be refreshed against the next published schedule.

Sources: [NCAA FBS standings](https://www.ncaa.com/standings/football/fbs) and [The Varsity Network](https://thevarsitynetwork.com/audioapplink).

## Verified feeds

The table is keyed by the ESPN scoreboard team code used by `data/radio-listen.json`. “Event” identifies the Varsity record used for discovery; the timestamp is its published start time in UTC. “Direct stream” is what the browser audio player loads, and “Event page” is the publisher page retained in the entry.

| ESPN code | School | Verified event · publish time (UTC) | Codec | Direct stream | Event page |
|---|---|---|---|---|---|
| `AFA` | Air Force | Air Force vs. UNLV · 2026-10-17 17:30Z | MP3 | <https://img.leanstream.co/IM2601-MP3> | <https://goairforcefalcons.com/watch/?Live=1020> |
| `ALA` | Alabama | Alabama @ Tennessee · 2026-10-17 16:30Z | MP3 | <https://img.leanstream.co/IM7001-MP3> | <https://rolltide.com/watch/?Live=10228> |
| `ARK` | Arkansas | Arkansas vs LSU · 2026-11-28 09:00Z | MP3 | <https://img.leanstream.co/IM1201-MP3> | <https://uark.sidearmstreaming.com/watch/?Live=894> |
| `ARMY` | Army | Army vs. Florida Atlantic · 2026-10-17 15:30Z | AAC | <https://img.leanstream.co/IM8601-MP3> | <https://goarmywestpoint.com/watch/?Live=3427> |
| `BGSU` | Bowling Green | Bowling Green vs. Ball State · 2026-10-17 15:00Z | AAC | <https://img.leanstream.co/LF0601-MP3> | <https://bgsufalcons.com/watch/?Live=417> |
| `BOIS` | Boise State | Boise State @ Washington State · 2026-10-24 21:00Z | AAC | <https://img.leanstream.co/LF0401-MP3> | <https://broncosports.com/watch/?Live=849> |
| `BUFF` | Buffalo | Buffalo vs. Massachusetts · 2026-10-17 16:00Z | AAC | <https://img.leanstream.co/LF0801-MP3> | <https://ubbulls.com/watch/?Live=414> |
| `CAL` | California | Cal vs. Wake Forest · 2026-10-18 01:30Z | AAC | <https://img.leanstream.co/LF1001-MP3> | <https://calbears.com/watch/?Live=516> |
| `COLO` | Colorado | Colorado vs. Utah · 2026-10-18 00:00Z | MP3 | <https://img.leanstream.co/IM7101-MP3> | <https://cubuffs.com/watch/?Live=3185> |
| `CONN` | UConn | UCONN vs. Massachusetts · 2026-10-23 21:30Z | MP3 | <https://img.leanstream.co/IM3401-MP3> | <https://uconnhuskies.com/watch/?Live=7363> |
| `CSU` | Colorado State | Colorado State @ Texas State · 2026-10-15 22:00Z | AAC | <https://img.leanstream.co/LF1701-MP3> | <https://csurams.com/watch/?Live=6954> |
| `DUKE` | Duke | Duke vs. North Carolina · 2026-10-17 18:00Z | MP3 | <https://img.leanstream.co/IM3501-MP3> | <https://goduke.com/watch/?Live=1525> |
| `EMU` | Eastern Michigan | Eastern Michigan vs Toledo · 2026-10-17 19:15Z | MP3 | <https://img.leanstream.co/IM6001-MP3> | <https://emueagles.com/watch/?Live=1395> |
| `FLA` | Florida | Florida @ Texas · 2026-10-17 13:00Z | MP3 | <https://img.leanstream.co/IM3601-MP3> | <https://floridagators.com/watch/?Live=6037> |
| `GASO` | Georgia Southern | Georgia Southern @ Old Dominion · 2026-10-15 21:30Z | MP3 | <https://img.leanstream.co/LF2401-MP3> | <https://gseagles.com/watch/?Live=2926> |
| `HOU` | Houston | Houston vs. Oklahoma State · 2026-10-17 22:30Z | MP3 | <https://img.leanstream.co/IM1501-MP3> | <https://uhcougars.com/watch/?Live=1385> |
| `ILL` | Illinois | Illinois vs. Oregon · 2026-10-24 08:00Z | MP3 | <https://img.leanstream.co/IM7401-MP3> | <https://fightingillini.com/watch/?Live=7065> |
| `IOWA` | Iowa | Iowa @ Washington · 2026-10-09 23:00Z | MP3 | <https://img.leanstream.co/IM7601-MP3> | <https://uiowa.sidearmstreaming.com/watch/?Live=1013> |
| `ISU` | Iowa State | Iowa State @ BYU · 2026-10-10 00:00Z | MP3 | <https://img.leanstream.co/IM7901-MP3> | <https://cyclones.com/watch/?Live=5977> |
| `IU` | Indiana | Indiana vs. Ohio State · 2026-10-17 15:00Z | MP3 | <https://img.leanstream.co/IM7301-MP3> | <https://iuhoosiers.com/watch/?Live=5109> |
| `JMU` | James Madison | JMU Football hosts Georgia State · 2026-10-17 15:00Z | MP3 | <https://img.leanstream.co/LF7101-MP3> | <https://jmusports.com/watch/?Live=627> |
| `KSU` | Kansas State | K State vs. Kansas · 2026-10-17 14:00Z | MP3 | <https://img.leanstream.co/IM8001-MP3> | <https://kstatesports.com/watch/?Live=6233> |
| `KU` | Kansas | Kansas @ Kansas State · 2026-10-17 15:30Z | MP3 | <https://img.leanstream.co/IM0101-MP3> | <https://kuathletics.com/watch/?Live=468> |
| `LOU` | Louisville | Louisville @ Syracuse · 2026-10-17 22:00Z | MP3 | <https://img.leanstream.co/IM7501-MP3> | <https://gocards.com/watch/?Live=12178> |
| `LT` | Louisiana Tech | Louisiana Tech @ ULM · 2026-10-17 22:30Z | AAC | <https://img.leanstream.co/LF2701-MP3> | <https://latechsports.com/watch/?Live=11287> |
| `MASS` | UMass | UMass @ Buffalo · 2026-10-17 16:30Z | AAC | <https://img.leanstream.co/LF6101-MP3> | <https://umassathletics.com/watch/?Live=5229> |
| `MEM` | Memphis | Memphis @ Tulane · 2026-10-16 21:30Z | AAC | <https://img.leanstream.co/LF3101-MP3> | <https://gotigersgo.com/watch/?Live=8876> |
| `MICH` | Michigan | Michigan vs. Penn State · 2026-10-17 16:30Z | MP3 | <https://img.leanstream.co/IM4001-MP3> | <https://mgoblue.com/watch/?Live=2828> |
| `MINN` | Minnesota | Minnesota vs. Iowa · 2026-10-24 08:00Z | MP3 | <https://img.leanstream.co/IM8401-MP3> | <https://gophersports.com/watch/?Live=5867> |
| `MISS` | Ole Miss | Ole Miss vs. Missouri · 2026-10-17 17:30Z | MP3 | <https://img.leanstream.co/IM4101-MP3> | <https://olemisssports.com/watch/?Live=1366> |
| `MIZ` | Missouri | Mizzou vs. Oklahoma · 2026-11-28 09:00Z | MP3 | <https://img.leanstream.co/IM8801-MP3> | <https://mizzou.sidearmstreaming.com/watch/?Live=4980> |
| `MOST` | Missouri State | Missouri State vs. Kennesaw State · 2026-10-14 23:00Z | AAC | <https://img.leanstream.co/LF3601-MP3> | <https://missouristatebears.com/watch/?Live=950> |
| `MRSH` | Marshall | Marshall vs. South Alabama · 2026-10-20 21:30Z | MP3 | <https://img.leanstream.co/IM1601-MP3> | <https://herdzone.com/watch/?Live=561> |
| `MSST` | Mississippi State | Mississippi State @ LSU · 2026-10-17 14:00Z | MP3 | <https://img.leanstream.co/IM8301-MP3> | <https://hailstate.com/watch/?Live=7980> |
| `NCSU` | NC State | NC State @ Stanford · 2026-10-24 00:30Z | MP3 | <https://img.leanstream.co/IM9301-MP3> | <https://gopack.com/watch/?Live=11275> |
| `NDSU` | North Dakota State | North Dakota State vs Nevada · 2026-10-17 22:00Z | AAC | <https://img.leanstream.co/LF7501-MP3> | <https://gobison.com/watch/?Live=4831> |
| `NEV` | Nevada | Nevada @ NDSU · 2026-10-17 22:00Z | AAC | <https://img.leanstream.co/LF4001-MP3> | <https://nevadawolfpack.com/watch/?Live=4858> |
| `OHIO` | Ohio | Ohio @ Sacramento State · 2026-10-18 01:00Z | MP3 | <https://img.leanstream.co/IM4301-MP3> | <https://ohiobobcats.com/watch/?Live=457> |
| `OKST` | Oklahoma State | Oklahoma State @ Houston · 2026-10-17 21:30Z | MP3 | <https://img.leanstream.co/IM9101-MP3> | <https://okstate.com/watch/?Live=6855> |
| `ORE` | Oregon | Oregon vs. Nebraska · 2026-10-18 01:00Z | MP3 | <https://img.leanstream.co/IM0801-MP3> | <https://goducks.com/watch/?Live=18925> |
| `ORST` | Oregon State | Oregon State vs. Washington State · 2026-10-17 20:00Z | MP3 | <https://img.leanstream.co/IM7201-MP3> | <https://osubeavers.com/watch/?Live=11610> |
| `OSU` | Ohio State | Ohio State @ Indiana · 2026-10-17 14:30Z | MP3 | <https://img.leanstream.co/IM5801-MP3> | <https://ohiostatebuckeyes.com/watch/?Live=931> |
| `OU` | Oklahoma | Oklahoma vs. Kentucky · 2026-10-17 20:30Z | MP3 | <https://img.leanstream.co/IM9001-MP3> | <https://soonersports.com/watch/?Live=2497> |
| `PUR` | Purdue | Purdue @ Indiana · 2026-11-28 08:00Z | MP3 | <https://img.leanstream.co/IM8901-MP3> | <https://purduestream.sidearmsports.com/watch/?Live=188> |
| `RICE` | Rice | Rice vs. Tulsa · 2026-10-17 20:00Z | MP3 | <https://img.leanstream.co/IM4501-MP3> | <https://riceowls.com/watch/?Live=6782> |
| `RUTG` | Rutgers | Rutgers @ Maryland · 2026-10-17 15:30Z | MP3 | <https://img.leanstream.co/IM4601-MP3> | <https://scarletknights.com/watch/?Live=1857> |
| `SC` | South Carolina | South Carolina at Clemson · 2026-11-28 09:00Z | MP3 | <https://img.leanstream.co/IM1701-MP3> | <https://unisouthcarolinastream.sidearmstreaming.com/watch/?Live=744> |
| `SMU` | SMU | SMU vs. Virginia · 2026-10-17 15:30Z | AAC | <https://img.leanstream.co/LF5401-MP3> | <https://smumustangs.com/watch/?Live=5380> |
| `SYR` | Syracuse | Syracuse vs. Louisville · 2026-10-17 21:30Z | MP3 | <https://img.leanstream.co/IM4801-MP3> | <https://cuse.com/watch/?Live=8507> |
| `TCU` | TCU | TCU @ Baylor · 2026-10-17 22:00Z | MP3 | <https://img.leanstream.co/IM4901-MP3> | <https://gofrogs.com/watch/?Live=1240> |
| `TENN` | Tennessee | Tennessee vs Alabama · 2026-10-17 17:00Z | MP3 | <https://img.leanstream.co/IM1901-MP3> | <https://utsports.com/watch/?Live=5632> |
| `TEX` | Texas | Texas vs. Florida · 2026-10-17 15:00Z | MP3 | <https://img.leanstream.co/IM0201-MP3> | <https://texaslonghorns.com/watch/?Live=921> |
| `TLSA` | Tulsa | Tulsa @ Rice · 2026-10-17 19:30Z | AAC | <https://img.leanstream.co/LF6001-MP3> | <https://tulsahurricane.com/watch/?Live=6371> |
| `TOL` | Toledo | Toledo @ Eastern Michigan · 2026-10-17 18:30Z | AAC | <https://img.leanstream.co/LF5901-MP3> | <https://utrockets.com/watch/?Live=1198> |
| `TROY` | Troy | vs. Louisiana · 2026-10-17 20:50Z | AAC | <https://ice6.securenetsystems.net/WTXK> | <https://troytrojans.com/watch/?Live=5803> |
| `TTU` | Texas Tech | Texas Tech vs. Arizona State · 2026-10-17 18:30Z | MP3 | <https://img.leanstream.co/IM8101-MP3> | <https://texastech.com/watch/?Live=8143> |
| `TULN` | Tulane | Tulane vs. Memphis · 2026-10-16 22:30Z | MP3 | <https://img.leanstream.co/IM5701-MP3> | <https://tulanegreenwave.com/watch/?Live=10477> |
| `UAB` | UAB | UAB vs. East Carolina · 2026-10-15 22:30Z | AAC | <https://img.leanstream.co/IM2001-MP3> | <https://uabsports.com/watch/?Live=4794> |
| `UGA` | Georgia | Football Game Audio vs. Auburn · 2026-10-17 15:30Z | MP3 | <https://img.leanstream.co/IM5001-MP3> | <https://georgiadogs.com/watch/?Live=5093> |
| `UL` | Louisiana | Louisiana vs. Troy · 2026-10-17 20:00Z | AAC | <https://img.leanstream.co/LF2801-MP3> | <https://ragincajuns.com/watch/?Live=2778> |
| `UNC` | North Carolina | North Carolina @ Duke · 2026-10-17 18:30Z | MP3 | <https://img.leanstream.co/IM9201-MP3> | <https://goheels.com/watch/?Live=5680> |
| `UNLV` | UNLV | UNLV @ Air Force · 2026-10-17 18:30Z | AAC | <https://img.leanstream.co/IM2101-MP3> | <https://unlvrebels.com/watch/?Live=390> |
| `USC` | USC | USC Football at Wisconsin (Radio) · 2026-10-24 05:00Z | AAC | <https://live.amperwave.net/manifest/goodkarma-kspnuscaac-hlsc.m3u8> | <https://usctrojans.com/watch/?Live=1466> |
| `USM` | Southern Miss | Southern Miss vs. Arkansas State · 2026-10-17 21:30Z | MP3 | <https://img.leanstream.co/IM1801-MP3> | <https://southernmiss.com/watch/?Live=7438> |
| `USU` | Utah State | Utah State vs. Washington State · 2026-10-10 00:00Z | AAC | <https://img.leanstream.co/LF6301-MP3> | <https://utahstateaggies.com/watch/?Live=497> |
| `VAN` | Vanderbilt | Vanderbilt vs Tennessee · 2026-11-28 09:00Z | MP3 | <https://img.leanstream.co/IM2301-MP3> | <https://vandy.sidearmstreaming.com/watch/?Live=934> |
| `WAKE` | Wake Forest | Wake Forest @ Cal · 2026-10-18 01:30Z | MP3 | <https://img.leanstream.co/IM2401-MP3> | <https://godeacs.com/watch/?Live=1527> |
| `WASH` | Washington | Washington @ Purdue · 2026-10-16 20:00Z | MP3 | <https://img.leanstream.co/IM1001-MP3> | <https://gohuskies.com/watch/?Live=1597> |
| `WIS` | Wisconsin | Wisconsin @ UCLA · 2026-10-17 21:30Z | MP3 | <https://img.leanstream.co/IM8501-MP3> | <https://uwbadgers.com/watch/?Live=802> |
| `WKU` | Western Kentucky | Western Kentucky @ Sam Houston · 2026-10-14 23:00Z | MP3 | <https://img.leanstream.co/IM2501-MP3> | <https://wkusports.com/watch/?Live=3737> |
| `WVU` | West Virginia | West Virginia vs. Cincinnati · 2026-10-17 13:00Z | MP3 | <https://img.leanstream.co/IM0301-MP3> | <https://wvusports.com/watch/?Live=5950> |
| `WYO` | Wyoming | Wyoming vs. Northern Illinois University · 2026-10-17 18:00Z | MP3 | <https://img.leanstream.co/IM8201-MP3> | <https://gowyo.com/watch/?Live=2961> |

## Discovered URLs that failed

These five FBS event records were not added to the player because their direct URLs failed the October 13 playback check.

| School | Varsity event | Direct URL | Result | Event page |
|---|---|---|---|---|
| Charlotte | FB Audio at Temple | <https://cdn.jwplayer.com/live/broadcast/ihmxwrwa.m3u8> | 404 | <https://charlotte49ers.com/watch/?Live=1792> |
| Texas State | Texas State vs. Colorado State | <https://img.leanstream.co/LF5801-MP3> | 5xx | <https://txst.com/watch/?Live=2328> |
| South Alabama | FB at Marshall | <https://cdn.jwplayer.com/live/broadcast/VKIx0yVR.m3u8> | 404 | <https://usajaguars.com/watch/?Live=1529> |
| Liberty | vs. Kennesaw State | <https://cdn.jwplayer.com/live/broadcast/VPFxwoGV.m3u8> | 404 | <https://libertyflames.com/watch/?Live=675> |
| North Texas | North Texas @ Navy | <https://img.leanstream.co/LF4302-MP3> | 5xx | <https://meangreensports.com/watch/?Live=550> |

The older Purdue event URL `https://img.leanstream.co/IM8904-MP3` also returned HTTP 502. Purdue’s later `https://img.leanstream.co/IM8901-MP3` stream passed and is configured above.

## FBS schools with no qualifying record found

These 61 schools were on the NCAA roster but had no qualifying Varsity football event record in the catalog search. Charlotte, North Texas, Texas State, South Alabama, and Liberty are listed in the failed-URL table above instead.

| School | School | School |
|---|---|---|
| Miami (FL) | Pittsburgh | Virginia |
| Clemson | Georgia Tech | Virginia Tech |
| Florida St. | Stanford | Boston College |
| UTSA | Fla. Atlantic | East Carolina |
| Temple | South Fla. | Navy |
| Utah | BYU | Baylor |
| Arizona | Cincinnati | Arizona St. |
| UCF | UCLA | Nebraska |
| Northwestern | Penn St. | Maryland |
| Michigan St. | Jacksonville St. | FIU |
| New Mexico St. | Delaware | Middle Tenn. |
| Sam Houston | Kennesaw St. | Notre Dame |
| Western Mich. | Miami (OH) | Central Mich. |
| Kent St. | Akron | Ball St. |
| Sacramento St. | New Mexico | San Jose St. |
| Hawaii | UTEP | NIU |
| Fresno St. | San Diego St. | Washington St. |
| Kentucky | LSU | Auburn |
| Texas A&M | Georgia St. | Coastal Carolina |
| Old Dominion | App State | Arkansas St. |
| ULM |  |  |

## Scoreboard playback

`lib/gameAudio.ts` looks up each game’s teams by ESPN code. `GameCard` selects the home team’s feed first and falls back to the away team’s feed; it renders one station per game. The existing audio control plays the configured direct URL in the browser. A team without a verified entry has no feed to select.
