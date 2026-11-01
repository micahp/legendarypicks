# Pixel Red Zone visual evidence

The screenshots were captured from the feature branch preview at desktop 1280×900 and mobile 390×844. The mobile overlay fills the viewport without scrolling or overlapping the page UI. The browser reported no JavaScript errors.

`channel-desktop.png` and `channel-mobile.png` show the room TV's scoreboard view. At capture time, no NFL game was live; the panel showed the next scheduled game and its scoreboard snapshot age. The archive was offered as a separate, explicit choice.

`redzone-desktop.png` and `redzone-mobile.png` show play 15 of 180 from the archived Cincinnati Bengals at Cleveland Browns game on September 7, 2025: ESPN sequence 38400, Q1 7:32, touchdown, and the publisher's attached extra point. The on-screen score is the score at that play, not the game's final score. The source record is `backend/fixtures/pixel_red_zone/401772829.json`, whose raw ESPN fixture SHA-256 is `349693297cd6f8abdabe0f4e35bc3917d20bc542f2f10ca50a5066d417390161`.

`field-before-desktop.png` / `field-after-desktop.png` and `field-before-mobile.png` / `field-after-mobile.png` are field crops from that same verified touchdown, captured before and after the SVG field fix at 1280×900 and 390×844. The SVG draws clear 5-yard and 10-yard markings, hashes, line of scrimmage, first-down line, and a transparent football with laces. End-zone labels rotate and use the source-matched team names. When a play has no verified spot, the ball stays visible at midfield with a `?` and an explicit illustrative-placeholder label; it is never presented as ESPN's location.

The old football was a tiny CSS oval with a thick cream box shadow, which read as a white square at mobile scale. It was also omitted entirely whenever the event's field confidence was unavailable. The old field used low-contrast dashed stripes without a line of scrimmage, and displayed generic horizontal end-zone labels. The new SVG removes the CSS matte, always renders a bounded marker, and exposes missing position data in text.

`interaction.webm` shows the room, opening the TV scoreboard, choosing the archived replay, stepping to that source play, and returning to the room. Replay mode and source captions remain visible throughout.

The replay archive now contains eight compact, frozen ESPN game summaries generated from the checked-in source audit; every final score reconciles to the independent scoreboard snapshot, and all 1,464 play IDs are present and unique. Replay assets load lazily in the frontend, so playback does not depend on the replay API route being present in the separate running backend. The scoreboard view uses the existing NFL scoreboard endpoint. There were no live games during these captures, so they do not claim to verify live channel freshness or the live multi-game director. No app server or tunnel was started or restarted.
