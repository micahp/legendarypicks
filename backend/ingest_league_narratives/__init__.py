"""ingest_league_narratives — AI-generated league conversations (package).

Split from the former single-file ingest_league_narratives.py (2026-08-18)
into modules by concern: topic_words, anchor_routing, parsing, roles,
content, timeline, quality, editor, generate, prompt, cli.

The package exposes the same external surface the module did. Callers that
did `from ingest_league_narratives import X` keep working unchanged.
"""
from .topic_words import (  # noqa: F401
    _norm_url, _norm_words, _significant, _topic_words, _topic_hits,
    weak_seed, _squash_title, _MIN_TOPIC_LEN, _GENERIC_WORDS,
    _STOPWORDS, _TIE_ALARM,
)
from .anchor_routing import _better_home, _MAX_SOURCES, _MIN_ITEMS  # noqa: F401
from .parsing import (  # noqa: F401
    _parse_response, _load_chatter, _ANCHORS,
)
from .roles import (  # noqa: F401
    is_social, social_leaks, post_text, post_handle, is_promo, is_relay,
    post_role, _SOCIAL_HOSTS, _LINK_RE, _HANDLE_RE, _PROMO_MARKERS,
    _FIRSTHAND_MARKERS,
)
from .content import (  # noqa: F401
    _content_words, corroboration, _prompt_items, _CORROB_STOP,
    _PROMPT_ITEMS,
)
from .timeline import (  # noqa: F401
    _age_days, is_background, split_by_age, stale_anchor, pool_key,
    newest_item, _numbered, _FRESH_DAYS,
)
from .quality import (  # noqa: F401
    had_publisher_material, unsupported_allegation, _squash, _outlet_vocab,
    _domain_of, speakers_shown, voice_without_speakers, credited_outlets,
    uncited_outlets, _attributed_names, _drafts, _cited_sources,
    _ALLEGATION_WORDS, _NOT_OUTLETS, _INLINE_DOMAIN, _REPORTING_VERBS,
    _SELF_REPORTING_VERBS, _OBSERVER_VERBS, _VOICE_SUBJECTS,
)
from .editor import (  # noqa: F401
    _log_deletion, _editor_marks, _DELETIONS_LOG, _BODY_CHARS,
    _SHOW_ANCHORS,
)
from .generate import (  # noqa: F401
    _generate, _generate_batch, _generate_batch_chunked,
    _BATCH_MAX_TOKENS, _SINGLE_MAX_TOKENS, _BATCH_CHUNK,
)
from .prompt import _SYSTEM  # noqa: F401
from .cli import main  # noqa: F401
