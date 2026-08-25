"""Shared language choices for keyword research and rank tracking.

Keeping this list in one module prevents the Research and Project Settings
screens from accepting different language codes for the same provider calls.
"""

KEYWORD_LANGUAGES = {
    "en": "English",
    "vi": "Vietnamese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ja": "Japanese",
    "ko": "Korean",
}


def keyword_language_options():
    return tuple(
        {"code": code, "name": name}
        for code, name in KEYWORD_LANGUAGES.items()
    )


def normalize_keyword_language(raw_language):
    language = (raw_language or "en").strip().lower()
    if language not in KEYWORD_LANGUAGES:
        raise ValueError("Choose a supported keyword language.")
    return language
