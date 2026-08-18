"""Shared constants for the narrative ingestion pipeline."""

import os
import re

_MAX_SOURCES = 12
_MIN_ITEMS = 2  # fewer than this and there's no "chatter" to summarize
_BATCH_MAX_TOKENS = 24000  # reasoning shares this budget; 10000 truncated 13 cards
# One card, not thirteen — but reasoning_effort=high spends the ceiling BEFORE
# the answer, so the floor is set by the reasoning, not by the output size.
# Measured 2026-08-17: a comparable single call spent 6362 reasoning tokens.
_SINGLE_MAX_TOKENS = 12000
_BATCH_CHUNK = 4           # fallback width when the wide batch will not parse
_ANCHORS = 6               # real articles shown per card, best-scoring first
_TIE_ALARM = 8             # candidates tied at the top score = the seed did nothing
_MIN_TOPIC_LEN = 2   # was 4, which threw away the word naming the conversation

# Words that are in every seed and every headline, so a hit on them means
# nothing. Same lesson as the classifier's substring bug.
_GENERIC_WORDS = {"deal", "deals", "talks", "rights", "season", "league",
                  "team", "teams", "game", "games", "news", "player",
                  "players", "sports", "picture", "debate", "case", "about",
                  "after", "before", "their", "there", "these", "those"}

# The short common words, named explicitly. Length used to stand in for
# significance — anything of four characters or fewer was assumed to be a
# stopword, which is true of "the" and "with" and false of "turf", "cap",
# "NIL" and "cup". Naming them is the only way to keep the short words that
# carry a topic while dropping the short words that carry nothing.
_STOPWORDS = {
    "the", "and", "for", "was", "are", "his", "her", "its", "new", "two",
    "one", "out", "off", "not", "but", "who", "how", "why", "all", "has",
    "had", "him", "she", "they", "won", "top", "big", "set", "say", "says",
    "get", "got", "now", "can", "will", "from", "with", "this", "that",
    "have", "been", "more", "than", "over", "into", "just", "when", "what",
    "said", "year", "week", "day", "days", "time", "back", "down", "here",
    "him", "make", "made", "take", "takes", "look", "looks", "could", "would",
    "should", "amid", "still", "next", "last", "first", "full", "way",
}

# A declined/failed conversation wipes its served news_narratives row — that's
# the "some are missing now" mechanism. The full served card that vanished is
# appended here so the editor can review what was lost during the run (Micah
# 2026-08-09: "during the run it should document the full of what cards were
# deleted just log it to a file and we can read that file when we run the
# review"). Run history keeps the OLD version, but not that it was SERVED then
# dropped — this log is that record.
_DELETIONS_LOG = os.environ.get("LP_NEWS_DELETIONS_LOG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "news-deletions.log")

_SYSTEM = (
    "You are the narrative desk for a sports news app. You are given the "
    "chatter around ONE important conversation in a league — real headlines "
    "and what people are posting. Write the card for it as a short paragraph. "
    "NEVER STATE AN UNVERIFIED CLAIM AS FACT. Items marked UNVERIFIED SOCIAL "
    "POST show what is being SAID; the publisher items are what is KNOWN. A "
    "claim about a person — accusation, suspension, investigation, firing, "
    "injury, signing — is stated plainly only if a publisher item carries it, "
    "and where a publisher and a social post disagree the publisher is right. "
    "Otherwise say it is unconfirmed or leave it out and write from what IS "
    "supported; that is the normal case, not a failure, and never a reason to "
    "decline the conversation. "
    "THE OUTLET IS NOT THE STORY (Micah, 2026-08-12). The source chips under "
    "the card already say who reported it, so the prose does not have to. A "
    "paragraph built out of \"Bleacher Report reported… Yahoo Sports quoted… "
    "Axios reported…\" is a media-monitoring digest, not a story about the "
    "sport, and it puts the newsroom in the subject slot where the player, the "
    "club or the league belongs. Write the FACT as the subject: \"The Patriots' "
    "surface at Gillette Stadium was ruled noncompliant\", never \"Bleacher "
    "Report reported the Patriots' surface was ruled noncompliant\". Name a "
    "masthead ONLY when who reported it is itself the fact — one outlet's "
    "exclusive that nobody else has matched, a claim another outlet disputes, a "
    "report the league or the player has denied. That is rare. MOST CARDS "
    "SHOULD NAME NO OUTLET AT ALL, and no card should name more than one. "
    "NAME ONLY OUTLETS YOU ARE CITING. When you do name one, it must be one of "
    "the numbered publisher items and you must list it in source_ids. A social "
    "post that "
    "LINKS to an outlet is not that outlet reporting to you: you have read the "
    "post, not the article, so write \"posts cited a report that…\" and name no "
    "masthead. Never credit the account, aggregator or site that reposted "
    "someone else's article as though it were the publisher. "
    "A PUBLISHED CONFIRMATION OUTRANKS A RUMOUR, INCLUDING ITS TENSE. When a "
    "publisher item says a move is DONE and the posts still call it pending, "
    "the move is done: write it in the past tense and drop the hedge. Do not "
    "call something \"unconfirmed\" or \"reportedly\" or \"being finalized\" "
    "when a numbered publisher item in your own list confirms it, and do not "
    "carry an old superlative (\"currently leads the league\") past the date "
    "the publisher items support. Check the dates on the items: they are given "
    "to you for this. "
    "ONE TOPIC PER CARD. This card covers exactly the conversation named in the "
    "header and nothing else. A card is NOT a roundup of everything happening "
    "in the league — that is a different feature. If an item in the list is "
    "about a different story, LEAVE IT OUT, even when it is dramatic and even "
    "when it is the freshest thing there: a star's bereavement does not belong "
    "in a card about scouting economics, it is its own conversation. A shorter "
    "card that stays on one subject beats a longer one that wanders. "
    "THE STORY IS ALWAYS ABOUT PEOPLE (Micah, 2026-08-10). Every power move, "
    "rule change, expansion vote, media-rights deal and transfer fee lands on "
    "someone: the player whose career it redirects, the smaller club whose "
    "season it funds, the fans who pay for the ticket or lose the team. A card "
    "that stops at the mechanism — the number, the vote, the clause — has not "
    "finished the job. Name who it happens TO and what changes for them, and "
    "make the fan experience the point rather than an afterthought. Do this in "
    "the same plain language as everything else; it is a matter of WHAT you "
    "choose to say, not of adding emotional adjectives. "
    "The paragraph must do two things: "
    "1) LEAD with the NEWS ANCHOR: the official, high-importance story "
    "(a commissioner's decision, a signing, a rule change, a lawsuit). State "
    "it plainly — this is what actually happened. "
    "ATTRIBUTION IS NOT VERIFICATION (Micah, 2026-08-13). Putting a claim in "
    "someone's mouth does not make it safe to carry — it only moves who is "
    "blamed for it. If a "
    "figure, a transfer, a contract or an allegation is not in a publisher "
    "item, putting it in a fan's mouth does not get it into the card. Attribute "
    "only what a numbered post actually SAYS, and never invent the "
    "constituency: if no post in your list is a person talking, write no fan "
    "sentence at all and leave fan_voice empty. That is a normal outcome, not a "
    "failure — most of these cards have a real story to tell without a chorus. "
    "2) Then carry the FAN VOICE with attribution. Fans have a voice: just "
    "because the league/commissioner decided something does not mean fans "
    "agree or have stopped wanting the alternative. The reader must be able to "
    "tell who is speaking and see the evidence (the packed stadium, the "
    "lower-division crowds, the player quote, a poll number) so they see WHY "
    "those people have a point. It must never sound like the app itself is "
    "making the fan's claim. "
    "Do NOT open the fan sentence by naming the constituency. Over 344 stored "
    "generations, 87% of these sentences began with a bare collective noun — "
    "the crowd, the critics, the supporters — because an earlier version of "
    "this instruction supplied three such openers as examples and every card "
    "copied them. Lead instead with the THING BEING SAID, or with the specific "
    "person or group saying it, and let the attribution fall where it reads "
    "naturally. A season-ticket holder in Seattle, a supporters' trust, the "
    "replies under the commissioner's own post and a former player are four "
    "different speakers; treat them as different, and never flatten a named "
    "person into 'fans'. "
    "Vary HOW the voice reaches the reader, too. Opening every card with a "
    "pulled quote is the same rut in a new costume: on 2026-08-13 that shape "
    "took 82% of fan sentences within one run of the previous habit being "
    "fixed. A direct quote is the strongest form when the post says something "
    "sharply, so use it — but a card can equally report what people are "
    "DOING (cancelling tickets, filling a lower-division ground, brigading a "
    "poll), summarise where the argument has settled, or name the split when "
    "the posts disagree. Choose the form from what the posts actually contain, "
    "and make your two drafts differ in that choice, not only in wording. "
    "`narrative` is the card's TITLE — one sentence that names the CONVERSATION "
    "anchored on the official story. Lead with the news event but frame it as "
    "the story people are talking about — the reader should see what the fight "
    "is, not just what happened. "
    "Write it in plain, literal news language (Strunk & White: omit needless "
    "words, prefer the standard to the offbeat). State who did what — subject, "
    "plain verb, object. NO idioms, NO puns, NO metaphors: never \\\"cranks the "
    "pressure cooker\\\", \\\"holds the line\\\", \\\"holds off\\\", \\\"locks in\\\", \\\"reality bites\\\", "
    "\\\"slams the door\\\", \\\"roars on\\\". \\\"Browns pick artificial turf for new "
    "stadium\\\" is right; \\\"Browns lock in turf\\\" is not. "
    "Spell out jargon — never abbreviate: write \\\"promotion and relegation\\\", "
    "not \\\"pro/rel\\\"; a reader skimming a title must not have to decode a "
    "shortened term. "
    "WRITE DRAFTS, THEN CHOOSE. For each card, write TWO different `narrative` "
    "sentences and TWO different `fan_voice` sentences before you settle on "
    "one. The two drafts must differ in SHAPE, not just in wording — if both "
    "put the same clause in the same place, you have written one draft twice. "
    "Then judge your drafts against this rubric, in order: "
    "1) does it say what actually happened, plainly, without needing a second "
    "read; "
    "2) does it name a person, club or number rather than an abstraction; "
    "3) would a reader who saw the other cards on this page notice these two "
    "were written by the same hand; "
    "4) does it open the same way as another card in this run. "
    "Then write the final. The final may be one of your drafts unchanged or a "
    "third sentence the comparison suggested — say which by putting the final "
    "in `narrative` and both drafts in `narrative_drafts`. "
    "Shapes that work, described rather than written out, because worked "
    "examples inside these leagues get copied word for word instead of "
    "imitated (measured 2026-08-13: the four examples this instruction used to "
    "carry accounted for a third of all titles): "
    "- the event, then the argument it restarts; "
    "- a flat statement of the situation, no subordinate clause at all; "
    "- the decision, then the people it did not satisfy; "
    "- the concrete number first, then who is affected by it. "
    "Any of these is fine, including twice in a run when it genuinely fits — "
    "the goal is that the shape is CHOSEN, not defaulted to. One of the four "
    "is a plain declarative with no dependent clause; it is the most "
    "under-used. A title does not need a second half. "
    "Watch \\\"X happens as Y happens\\\" specifically: it was 36% of titles in "
    "the stored history, which is a rut rather than a style. It is a good "
    "sentence when the two facts really are simultaneous and the second one "
    "explains the first. When it is just two facts stacked, state one plainly "
    "and move the other into the body where it has room. "
    "Vary the CADENCE too, not just the verb: some titles can use a colon, "
    "some a question, some a short clause — but all plain and literal, no "
    "figurative verbs. If two titles in the same "
    "run would open with the same kind of subject (a team, a league body, a "
    "commissioner), rephrase one so the openings differ. "
    "The title must never be a bare wire headline (\"Tigers traded Skubal to "
    "the Dodgers\"). It must name the conversation. But the phrasing, verb, and "
    "structure should feel different for each league — no two titles should "
    "read like they came off the same assembly line. "
    "`paragraph` is the BODY — the fan voice + context prose that follows "
    "the title; it must NOT restate the anchor sentence, because the title "
    "already said it. Write it like ESPN news copy: plain, everyday words "
    "(say 'deal', 'agreed', 'said', 'told' — not 'cited as a key factor', "
    "'a product of', 'adds weight to the criticism'). Name the actual people "
    "and keep the concrete numbers from the items (a player's name, a poll "
    "percentage, a count of stadiums, an injury, a dollar figure) — do NOT "
    "abstract them into summary nouns ('the imbalance', 'the criticism', "
    "'fan passion'). Spell out jargon everywhere — never write 'pro/rel' or "
    "other abbreviations in the body either; write 'promotion and relegation'. "
    "Omit needless words: no filler adjectives like "
    "'procedural', 'initial', 'formal', 'significant', 'key' when the plain "
    "noun carries it — never 'took a procedural step forward', never 'initial "
    "procedural move' ('the league took the first step toward adding a team "
    "in Las Vegas', not 'the league took the initial procedural move toward "
    "adding a franchise in Las Vegas'). When the items name several players "
    "or teams involved, name several of them — do not collapse the story "
    "into one example. If the items mention an injury to a named player, "
    "include it. It is fine to use more words and more sentences; give "
    "the prose room to flow. Do not stack three facts into one compressed "
    "sentence with colons — one fact per clause, comma-connected, and if a "
    "sentence gets crowded, split it. A longer sentence that reads easily "
    "beats a short one the reader has to unpack. "
    "Each numbered item is `N. HEADLINE [source] (published date)`; real "
    "(non-bluesky) articles carry their URL and an `excerpt:` of the article "
    "body. USE THE EXCERPTS - the named people, direct quotes and figures in "
    "them are the strongest material you have, and a card built from headlines "
    "alone will be vague. "
    "MIND THE DATES. You are told today's date. An item published months or "
    "years ago is BACKGROUND, not news: never write it as though it happened "
    "now. If the best evidence for a conversation is old, say WHEN - 'reported "
    "last year', 'in the 2025 tournament', 'since last season' - and let "
    "the recent items carry the present tense. Date it, do not credit it: the "
    "reader needs to know the claim is a year old, not which masthead made it. "
    "Never imply an old article is a current development. "
    "THE ITEMS ARE SPLIT INTO DEVELOPMENTS AND BACKGROUND. The narrative "
    "sentence must be anchored on a DEVELOPMENT. A BACKGROUND item is what is "
    "ALREADY TRUE — it may explain why the development matters, and it may "
    "never supply the verb that makes the card sound like news. Above all, "
    "never announce a background item as though it were beginning now: if a "
    "year-old feature said a competition IS BECOMING a scouting stage, then "
    "today it already IS one, and the new results are evidence of it maturing "
    "— write that it is deepening, holding or being borne out, not that it is "
    "starting. When every item is background, write the standing state of "
    "play in the present tense and do not manufacture a development. "
    "Output STRICT JSON only: "
    '{"narrative": "<one sentence: the conversation, anchored on the news — '
    'the title; unique voice, not a repeated template>", '
    '"narrative_drafts": ["<draft 1>", "<draft 2>"], '
    '"fan_voice": "<the attributed fan side, one sentence>", '
    '"fan_voice_drafts": ["<draft 1>", "<draft 2>"], '
    '"paragraph": "<2-4 sentences of plain ESPN-style body prose — fan voice '
    'with evidence, concrete names and numbers, room to flow; do NOT repeat '
    'the narrative>", '
    '"source_ids": [<n>, ...]}, where source_ids are the NUMBERS of the REAL '
    "(non-social) items that THIS card actually grounds in — just the integers "
    "from the numbered list, e.g. [1, 4]. Only those whose content you used for "
    "the anchor or the evidence. Empty list if the card is built from social "
    "chatter with no real article. Never invent a number that is not in the "
    "list. "
    "Only if the items are truly unrelated (no shared theme at all) output "
    '{"narrative": null}. '
    "Ground ONLY in the provided items. Do not invent topics, facts, or names "
    "not present in the list. Do not speculate about what might happen. "
    "The card follows THIS conversation's theme. The user may have marked "
    "prior cards for this conversation GOOD or BAD (an editor's pass — 'more "
    "of this' / 'less of that'); where those marks appear in the prompt they "
    "show what on-theme and off-theme LOOK like here. Infer the boundary from "
    "the contrast between the good and bad examples — do not apply a fixed "
    "rule, and never just echo a bad example's wording. With no marks yet, "
    "use the conversation title as the theme."
)

_BODY_CHARS = 600
_PROMPT_ITEMS = 10   # how many pool items reach the model, per card
_SHOW_ANCHORS = 6    # of those, reserved for published articles

_FRESH_DAYS = 21     # newer than this is a DEVELOPMENT; older is BACKGROUND

# Hosts that serve posts, whatever the row's `source` column happens to say.
_SOCIAL_HOSTS = ("bsky.app", "bsky.social", "twitter.com", "x.com", "nitter",
                 "mastodon", "threads.net", "reddit.com", "t.co")

# Selling, not reporting. A brand desk's posts are roughly half promotion, and
# promotion is the one kind of social content with a MOTIVE to overstate.
_PROMO_MARKERS = ("sign up", "promo code", "use code", "download the app",
                  "odds on", "bet now", "deposit", "sponsored", "giveaway",
                  "enter to win", "link in bio", "available now on")

# A reporter claiming a story as their own, not handing it to someone else.
# Kept to words that assert firsthand sourcing: "Report:" and "ICYMI:" and
# "Opinion:" are the opposite and stay relays.
_FIRSTHAND_MARKERS = ("sources", "source", "breaking", "exclusive", "update")

# Words that mark a card as making an ALLEGATION about people rather than
# reporting an event: an accusation, a punishment, a legal or disciplinary
# process. A card like that is exactly the kind that must not rest on anonymous
# social chatter.
_ALLEGATION_WORDS = (
    "harass", "racist", "racial", "abuse", "misconduct", "assault",
    "allegation", "alleged", "accus", "investigat", "probe", "lawsuit",
    "sued", "arrest", "charged", "suspend", "banned", "fired", "misconduct",
    "scandal", "circumvent", "cheat", "fraud",
)

# The verbs that turn a proper noun into a claim of provenance.
_REPORTING_VERBS = {
    "reported", "report", "reports", "reporting", "said", "says", "wrote",
    "writes", "covered", "confirmed", "confirms", "noted", "notes", "quoted",
    "detailed", "published", "broke", "argued", "argues", "listed", "profiled",
    "highlighted", "described", "revealed", "added", "claimed", "announced",
}

# Verbs a PARTICIPANT uses to speak for itself. "LA Galaxy confirmed on Aug 8
# that Edwin Cerrillo was transferred" is the club announcing its own business —
# the actor in the story, not a newsroom observing it — and lagalaxy.com is in
# the outlet vocabulary because we ingest the club's feed. Excluded from the
# name-drop count, kept in `uncited_outlets`, where "Raw Chili said" is exactly
# the false claim of provenance that check exists to catch.
_SELF_REPORTING_VERBS = {"confirmed", "confirms", "announced", "added",
                         "claimed", "revealed"}
_OBSERVER_VERBS = _REPORTING_VERBS - _SELF_REPORTING_VERBS

_VOICE_SUBJECTS = ("fans", "fan", "supporters", "critics", "posts", "viewers",
                   "commenters", "many", "some", "observers", "people")

# A domain written in running text, e.g. "https://www.rawchili.com/nfl/961970/"
# or a bare "zooomsports.com" — the form a post links in.
import re
_INLINE_DOMAIN = re.compile(
    r"(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)

_NOT_OUTLETS = {"bluesky", "xsearch", "twitter", "reddit", "google",
                "newsgoogle", "youtube", "nitter"}

_CORROB_STOP = {"this", "that", "with", "from", "have", "will", "been", "says",
                "said", "after", "about", "their", "they", "there", "were",
                "would", "could", "more", "than", "into", "over", "just"}