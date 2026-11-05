"""Starter claims in stored NFL news, each attributed to the player it is about.

Extractor version claims-v1. It reads the headline, notes and analysis of one stored update version and returns claims.
Every claim names a subject player, which may differ from the update's own player:

- own: the update's player is the only roster player the sentence mentions, or the headline mentions no roster player.
- named_in_other_update: the sentence's only roster mention is a teammate, so the claim belongs to that teammate and the
  update stays linked to its original player.

A roster mention is a full name, or a surname that is unique on the team. A shared surname that no full name explains
makes the sentence ambiguous, and it is not attributed. A sentence with two or more roster mentions is not attributed to
anyone. Both cases are counted, and their text stays in the stored update. Negated sentences make no claim.

The starter lexicon is the one in scripts/nfl_sequence/news_evidence.py (lp-slc-v2). Its gaps are known: wording such as
"will serve as the starter" and "favorite to start" is not matched. Any change belongs in a new extractor version.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

EXTRACTOR = 'claims-v1'

SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
NAMED = re.compile(r'\bnamed\b[^.!?]{0,40}?\bstart(?:er|ing)?\b', re.IGNORECASE)
EXPECTED = re.compile(r'\b(?:expected|projected|likely|set|slated|should|favored|in line)\b[^.!?]{0,40}?'
                      r'\bstart(?:er|ing)?\b', re.IGNORECASE)
COACH = re.compile(r'\b(?:coach|head coach|team|staff|organization)\b', re.IGNORECASE)
CONFIRM = re.compile(r'\bconfirm(?:s|ed|ing)?\b', re.IGNORECASE)
START = re.compile(r'\bstart(?:s|ed|ing|er|ers)?\b', re.IGNORECASE)
NEGATION = re.compile(r"\b(?:not|no longer|won't|will not|isn't|doesn't|unlikely)\b|n't\b", re.IGNORECASE)
SUFFIXES = frozenset({'jr', 'sr', 'ii', 'iii', 'iv'})
FIELDS = ('headline', 'notes', 'analysis')


def normalize(text):
    folded = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode('ascii').lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', folded).split())


def roster_entry(player_id, name):
    tokens = [token for token in normalize(name).split() if token not in SUFFIXES]
    return {'player_id': int(player_id), 'full': ' '.join(tokens), 'last': tokens[-1] if tokens else ''}


def _mentions(sentence_tokens, sentence_text, roster, surname_counts):
    """(player ids mentioned, ambiguous). A full name is a mention. A surname is a mention only when it is unique on the
    roster. A surname that is shared and is not already explained by a full name makes the sentence ambiguous."""
    found = set()
    full_lasts = set()
    for entry in roster:
        if entry['full'] and f' {entry["full"]} ' in sentence_text:
            found.add(entry['player_id'])
            full_lasts.add(entry['last'])
    ambiguous = False
    for entry in roster:
        if entry['player_id'] in found or entry['last'] in full_lasts or entry['last'] not in sentence_tokens:
            continue
        if surname_counts.get(entry['last']) == 1:
            found.add(entry['player_id'])
        else:
            ambiguous = True
    return sorted(found), ambiguous


def _starter_classes(sentence):
    checks = (
        ('starter_named', NAMED.search(sentence)),
        ('starter_expected', EXPECTED.search(sentence)),
        ('coach_confirmation_reported', COACH.search(sentence) and CONFIRM.search(sentence) and START.search(sentence)),
    )
    return [name for name, hit in checks if hit]


def extract(update, own_player_id, roster, own_name=None):
    """Claims for one stored update version.

    update: dict with headline, notes, analysis. own_player_id: the player the update is about, or None. roster: list of
    roster_entry dicts for the update's team. own_name: the own player's name, used when the roster does not list him,
    so that a sentence naming him and a teammate is seen as a two-player sentence. Returns (claims, counts).
    """
    counts = Counter()
    if own_player_id is not None and own_name and not any(e['player_id'] == own_player_id for e in roster):
        roster = list(roster) + [roster_entry(own_player_id, own_name)]
    surname_counts = Counter(entry['last'] for entry in roster)
    claims = []
    seen = set()
    for field in FIELDS:
        for sentence in SENTENCE_SPLIT.split(update.get(field) or ''):
            sentence = sentence.strip()
            if not sentence:
                continue
            classes = _starter_classes(sentence)
            if not classes:
                continue
            if NEGATION.search(sentence):
                counts['negated'] += 1
                continue
            text = normalize(sentence)
            mentions, ambiguous = _mentions(set(text.split()), f' {text} ', roster, surname_counts)
            if ambiguous:
                counts['ambiguous_mention'] += 1
                continue
            if len(mentions) > 1:
                counts['multi_player_sentence'] += 1
                continue
            if mentions:
                subject = mentions[0]
            elif field == 'headline' and own_player_id is not None:
                subject = own_player_id
            else:
                counts['no_subject'] += 1
                continue
            attribution = 'own' if subject == own_player_id else 'named_in_other_update'
            for claim_class in classes:
                key = (subject, claim_class, field)
                if key in seen:
                    continue
                seen.add(key)
                claims.append({'subject_player_id': subject, 'attribution': attribution, 'claim_class': claim_class,
                               'field': field, 'span': sentence[:300]})
                counts[attribution] += 1
    return claims, counts
