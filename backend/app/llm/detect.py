"""The language the user actually wrote in.

The UI has a language toggle, and until now that toggle alone decided the reply
language — so a Vietnamese question typed while the UI sat on English came back
in English. The message itself is the better signal: this module reads it, and
the toggle stays as the fallback for anything too short or too ambiguous to
call (a bare "CRD-0173", a number, an emoji).

Detection is deterministic and offline on purpose. It runs before the model is
prompted, so it cannot depend on the model being up, and a wrong guess must be
reproducible from the text alone.
"""

from __future__ import annotations

import re
import unicodedata

from ..engine.render import DEFAULT_LANG, normalise_lang

# Combining marks that only Vietnamese uses among the two languages we support:
# dot below, hook above, breve, horn. Grave, acute and tilde are deliberately
# absent — "café" is English text, and a word carrying only those falls through
# to the word check below, where "chào" still lands on Vietnamese via "chao".
VI_ONLY_MARKS = frozenset((
    "\u0323",   # dot below   - ạ ẹ ị
    "\u0309",   # hook above  - ả ẻ ỉ
    "\u0306",   # breve       - ă
    "\u031b",   # horn        - ơ ư
))
VI_ONLY_LETTERS = frozenset("đ")

TOKEN = re.compile(r"[a-z]+")

# Diacritic-free Vietnamese words, so an unaccented "toi muon xem giao dich"
# still reads as Vietnamese. Anything that collides with an English word is
# left out: "the" (thế), "on" (ơn) and "do" (đó) would score every English
# sentence as Vietnamese.
VI_WORDS = frozenset("""
chao xin ban minh toi tao tui chung nhe nha khong co gi sao nao bao nhieu
tien giao dich thang tuan ngay nay kia cho xem giup cam la ai duoc hay cua
nhung kiem tra phi tai khoan dang ky huy bi tru hoa don gui thu email tong
quan can xac nhan trung lap thue lai vay tieu mua tra ve voi den tu boi
muon biet hieu ro them nua roi chua dau nhi vai may cai khi neu thi ma
""".split())

EN_WORDS = frozenset("""
the is are was were am be been what which how much many why when where who
whom whose my me i you your yours we our us they them their it its this that
these those show list tell explain give check please thanks thank hello hi
hey can could would should do does did will about of for from with without
and or but not any all some more transaction transactions charge charges
spending subscription subscriptions statement account card fee fees refund
month week day today yesterday total need want know see
""".split())


def _has_vietnamese_letters(text: str) -> bool:
    """True when a character can only have been typed for Vietnamese."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return any(ch in VI_ONLY_MARKS or ch in VI_ONLY_LETTERS
               for ch in decomposed)


def _strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    without_marks = "".join(ch for ch in decomposed
                            if not unicodedata.combining(ch))
    return without_marks.replace("đ", "d").replace("Đ", "d")


def _word_scores(text: str) -> tuple[int, int]:
    """How many distinct Vietnamese and English words the message contains."""
    words = set(TOKEN.findall(_strip_diacritics(text)))
    return len(words & VI_WORDS), len(words & EN_WORDS)


def detect_lang(question: str, fallback: str = DEFAULT_LANG) -> str:
    """The language to answer in: the question's, or the UI's when unclear."""
    fallback = normalise_lang(fallback)
    text = (question or "").strip()
    if not text:
        return fallback
    if _has_vietnamese_letters(text):
        return "vi"
    vi_hits, en_hits = _word_scores(text)
    if vi_hits > en_hits:
        return "vi"
    if en_hits > vi_hits:
        return "en"
    return fallback


# -- an explicit request ---------------------------------------------------
#
# "trả lời bằng tiếng Anh" is a Vietnamese sentence asking for English, so the
# language the message is *written* in is the wrong answer to it. A request
# beats detection, and it is read from the wording rather than from the model,
# for the same reason as above: it must hold when the model is down.

_VERB = (r"(tr[ảa] l[ờo]i|n[óo]i|d[ùu]ng|s[ửu] d[ụu]ng|vi[ếe]t|chuy[ểe]n|"
         r"đ[ổo]i|doi|answer|repl(?:y|ies)|respond|speak|write|switch|use|"
         r"talk|continue|go on)")
_TARGET = {
    "en": r"(ti[ếe]ng anh|english)",
    "vi": r"(ti[ếe]ng vi[ệe]t|vietnamese)",
}
# Particles that turn a bare language name into an instruction: "English
# please", "tiếng Anh đi", "tiếng Việt nhé".
_PLEASE = r"(please|đi|di|nh[éeá]|nha|th[ôo]i|only|lu[ôo]n)"

LANG_REQUEST: dict[str, list[re.Pattern[str]]] = {
    lang: [
        re.compile(rf"{_VERB}[^.?!\n]{{0,40}}\b{target}", re.I),
        re.compile(rf"\b{target}\b[^.?!\n]{{0,12}}\b{_PLEASE}\b", re.I),
        re.compile(rf"^\s*(in|b[ằa]ng|sang|to)?\s*{target}\s*[?.!]*\s*$", re.I),
    ]
    for lang, target in _TARGET.items()
}


def _first_request_at(text: str, lang: str) -> int | None:
    """Where in the message this language is first asked for, if it is."""
    found = [match.start() for pattern in LANG_REQUEST[lang]
             if (match := pattern.search(text))]
    return min(found) if found else None


def requested_lang(question: str) -> str | None:
    """The language the user asked to be answered in, or None if they did not.

    When a message names both — "answer in English, not Vietnamese" — the one
    asked for first wins, which is where the instruction sits in both
    languages.
    """
    text = (question or "").strip()
    if not text:
        return None
    positions = {lang: at for lang in _TARGET
                 if (at := _first_request_at(text, lang)) is not None}
    if not positions:
        return None
    return min(positions, key=lambda lang: positions[lang])
