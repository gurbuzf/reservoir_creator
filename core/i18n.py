# -*- coding: utf-8 -*-
"""
Interface language (English by default, Turkish available).

Every user-visible string is written in English and passed through
:func:`tr`; the Turkish text lives in :mod:`i18n_tr`, keyed by the English
source string (``str.format`` placeholders are kept, so ``tr(s).format(...)``
works in both languages).  No Qt here, so the core stays testable without
QGIS.
"""

LANGUAGES = (('en', 'English'), ('tr', 'Türkçe'))
_language = 'en'
_tables = {}


def set_language(code):
    global _language
    _language = code if code in dict(LANGUAGES) else 'en'


def language():
    return _language


def N_(text):
    """Mark a literal for translation without translating it yet."""
    return text


class Msg:
    """Text translated when it is shown, so it follows a later language switch.

    ``Msg('Level {:.1f} m', 931.1)``; arguments may themselves be :class:`Msg`.
    """

    def __init__(self, template, *args):
        self.template = template
        self.args = args

    def __str__(self):
        args = [str(a) if isinstance(a, Msg) else a for a in self.args]
        return tr(self.template).format(*args)

    def startswith(self, prefix):
        return self.template.startswith(prefix)

    def __eq__(self, other):
        return isinstance(other, Msg) and (self.template, self.args) == (other.template, other.args)

    def __hash__(self):
        return hash((self.template, self.args))


def tr(text):
    if _language == 'en':
        return text
    if _language not in _tables:
        if _language == 'tr':
            from .i18n_tr import STRINGS
            _tables['tr'] = STRINGS
        else:  # pragma: no cover
            _tables[_language] = {}
    return _tables[_language].get(text, text)
