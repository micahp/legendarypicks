# Pixel Red Zone visual evidence

The screenshots were captured from the feature branch preview at desktop 1280×900 and mobile 390×844. The mobile overlay fills the viewport without scrolling or overlapping the page UI. The browser reported no JavaScript errors.

`channel-desktop.png` and `channel-mobile.png` show the room TV's scoreboard view. At capture time, no NFL game was live; the panel showed the next scheduled game and its scoreboard snapshot age. The archive was offered as a separate, explicit choice.

`redzone-desktop.png` and `redzone-mobile.png` show play 15 of 180 from the archived Cincinnati Bengals at Cleveland Browns game on September 7, 2025: ESPN sequence 38400, Q1 7:32, touchdown, and the publisher's attached extra point. The on-screen score is the score at that play, not the game's final score. The source record is `backend/fixtures/pixel_red_zone/401772829.json`, whose raw ESPN fixture SHA-256 is `349693297cd6f8abdabe0f4e35bc3917d20bc542f2f10ca50a5066d417390161`.

`interaction.webm` shows the room, opening the TV scoreboard, choosing the archived replay, stepping to that source play, and returning to the room. Replay mode and source captions remain visible throughout.

The archive loads as a lazy frontend asset from the checked-in fixture, so it does not depend on the replay API route being present in the separate running backend. The scoreboard view uses the existing NFL scoreboard endpoint. There were no live games during this capture, so the selected-game live play-by-play request was not exercised; these screenshots do not claim to verify live channel freshness or the live multi-game director. No app server or tunnel was started or restarted.
