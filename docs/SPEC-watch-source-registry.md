# Watch source registry

## Purpose

The Watch page is source-first: it can surface any official free broadcast,
regardless of sport. A source row is **not** a promise that every video on a
channel is a game, free, live, or embeddable.

`backend/routers/watch_registry.py` is the single source of truth for audited
publishers. `GET /api/watch/sources` exposes that read-only contract without
performing upstream network work.

## Publication contract

A future scheduled collector may publish a concrete Watch card only when all
of these are true:

1. The registry names the official publisher and evidence for that source.
2. The exact video/event is live or upcoming, rather than a VOD, draw, press
   conference, reaction show, or generic channel page.
3. The event is free in the applicable territory. `event_specific` does not
   mean free by default.
4. For `youtube_embed`, the concrete video passes the existing YouTube
   ownership/live/oEmbed checks. For `external_free`, LP links out unless that
   provider's iframe policy has been independently verified.

Failure of any check means no card is published. The collector should retain
its last successful snapshot separately and report the failed source/check;
it must not substitute a random or stale channel video.

## Registry states

| Field | Meaning |
| --- | --- |
| `youtube_embed` | Eligible only for a resolved, official, embeddable YouTube video. |
| `external_free` | Free official destination; outbound only until iframe behavior is verified. |
| `always_free` | The publisher currently represents its covered events as free, subject to stated territory notes. |
| `event_specific` | A per-event official availability check is mandatory. |

## First sources

- PWHL YouTube is eligible for title-filtered discovery, with the explicit
  country exceptions stored in the registry.
- FIBA YouTube is discovery metadata only until a particular competition's
  official watch notice verifies free availability; memberships and blackouts
  vary.
- FIFA+ is a free-link research source, not an iframe source.

The next implementation slice is a bounded scheduled collector that reads this
registry, writes an atomic published snapshot, and exposes only validated
concrete events to `/api/watch`.
