# Sean Payton (Broncos): play-calling tendencies from the RedZone broadcast, 2026-11-22

Source: a live transcript of the NFL RedZone broadcast on Sunday 2026-11-22. The Broncos were playing the Raiders on CBS, and Denver led 3-0 at 15:57.
- The audio was recorded from 15:34:51 CST and transcribed with faster-whisper `small.en`.
- Times are clock times in CST, about 3-6 s behind the TV.
- There is no audio from 16:02:34 to 16:12:13.
- The raw transcript is kept outside the repo at `C:\Users\micah\Documents\redzone_transcripts\2026-11-22\transcript.txt`.

These quotes are what the announcers said, not measured stats. They are leads to test against play-by-play data, not facts.

## What the broadcast said

| Time (CST) | Tendency | Quote (Whisper text, lightly trimmed) |
|---|---|---|
| 18:01:11 | **Play action in run situations, more than the rest of the league** | "Sean Payton is known to play action more than other offenses when you think it's going to be a run" |
| 16:14:59 | **Low red zone: play action, boots and screens** | "...master at the play action in the low red zone and the boots and the screens." Whisper garbled the start of this line ("he campaigns at"); from the context it is about Payton. |
| 16:36:34 | **Rub routes to get receivers open** | "Sean Payton is great at picking rub routes to get receivers open." |
| 16:13:51 | **Trick plays: the flea flicker** | "Sean Payton dials up the flea flicker and the Broncos go up 16-nothing" (Nix to Marvin Mims for a TD) |
| 16:14:05 | Aggressive play calling in this game | "Sean Payton is in his bag right now" |
| 16:14:32 | Hurried to the line rather than challenge a play at the goal line | "...they wanted to go fast ... Sean Payton didn't want to look didn't want to review it" |
| 17:42:16 | Schemed touches for Marvin Mims (a returner) | "Sean Payton talked about getting Marvin Mims the ball." The 11-yard run came right before this line. |
| 17:46:52 | Run/pass balance on scoring drives | "Ten play drive, five runs, five passes. Great balance by Sean Payton" |

The same broadcast also gave context on the run game:
- Jonah Coleman scored a rushing TD for the third game in a row (16:15:12).
- Coleman set a career high, 74+ rushing yards, by 18:01.
- That run threat is what makes the play-action tendency above work.

## Hypotheses to test with play-by-play

1. **Play-action rate on early downs in run situations.** Example: 1st and 10, or 2nd and short, with RB personnel. Expect Denver to rank near the top of the league, and higher than its overall play-action rate.
2. **Play action and bootlegs inside the opponent's 10-yard line** ("low red zone"). Compare Denver's red-zone play-action and rollout share with the league.
3. **Screen rate in the red zone.**
4. **Rub, pick and stack releases on 3rd down and in the red zone.** This needs charting or tracking data. Play-by-play alone won't show route concepts.
5. **Trick-play frequency** (flea flickers, reverses, gadget passes) per game.
6. **Touches for Marvin Mims on offense** (rushes plus targets) per game, trending up.
7. **Tempo after big plays near the goal line**: hurry up rather than wait for a review.

## Betting angles (unvalidated)

- If (1) holds, a Denver run threat inflates the QB's yards per attempt on early downs. That would make Bo Nix passing-yards and longest-completion props worth a look when Coleman is running well.
- If (2) and (3) hold, Denver red-zone TDs go more often to TEs and RBs on boots and screens than a plain run/pass split would suggest. That's relevant to anytime-TD props.
- If (6) holds, Mims rushing and receiving lines may lag his real usage.

## Next steps

- Join transcript lines to play-by-play by game clock, and tag each claim with the play it describes.
- Run the same extraction on the other RedZone transcripts (on the other machine) to build tendency claims for every coach. Then score each claim against the data.
