"""Pick a font that has every Japanese glyph, and prove it after drawing.

Order: a font the user configured, then a Japanese system font with real
bold weights, then IPAexGothic (shipped inside the matplotlib-fontja wheel,
so a bare Linux server still renders Japanese). Matplotlib falls back per
glyph through the family list, and any glyph still missing is reported as an
error rather than drawn as a box.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import warnings
from contextlib import contextmanager
from typing import Iterator, List, Optional

from matplotlib import font_manager

# Proportional families with a usable bold weight first; a UD (universal design) face leads.
SYSTEM_FAMILIES = (
    "BIZ UDPGothic", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP",
    "Noto Sans JP", "Source Han Sans JP", "Yu Gothic", "YuGothic", "Meiryo",
    # Fixed-width Latin digits ("1, 405") read worse in labels: last resorts only.
    "BIZ UDGothic", "IPAexGothic", "IPAGothic", "TakaoPGothic", "VL PGothic",
)
FALLBACK_FAMILY = "IPAexGothic"
LATIN_FALLBACK = "DejaVu Sans"

_registered_bundle = False


def bundled_font_path() -> Optional[str]:
    """Path of ipaexg.ttf inside matplotlib-fontja, found without importing it.

    Importing matplotlib_fontja would set matplotlib's global default font for
    every other tool in the process, so only the file is used.
    """
    spec = importlib.util.find_spec("matplotlib_fontja")
    for base in (spec.submodule_search_locations or []) if spec else []:
        path = os.path.join(base, "fonts", "ipaexg.ttf")
        if os.path.isfile(path):
            return path
    return None


def _register_bundled_font() -> bool:
    """Add IPAexGothic to matplotlib's font list (no global rc change)."""
    global _registered_bundle
    if _registered_bundle:
        return True
    path = bundled_font_path()
    if not path:
        return False
    if FALLBACK_FAMILY not in {f.name for f in font_manager.fontManager.ttflist}:
        font_manager.fontManager.addfont(path)
    _registered_bundle = True
    return True


def family_list(preferred: Optional[str] = None) -> List[str]:
    """Font families to hand matplotlib, best first."""
    _register_bundled_font()
    installed = {f.name for f in font_manager.fontManager.ttflist}
    out: List[str] = []
    if preferred:
        if os.path.isfile(preferred):
            font_manager.fontManager.addfont(preferred)
            preferred = font_manager.FontProperties(fname=preferred).get_name()
        if preferred in {f.name for f in font_manager.fontManager.ttflist}:
            out.append(preferred)
    for fam in SYSTEM_FAMILIES:
        if fam in installed and fam not in out:
            out.append(fam)
            break  # one Japanese system family keeps weights consistent
    if FALLBACK_FAMILY not in out and FALLBACK_FAMILY in {f.name for f in font_manager.fontManager.ttflist}:
        out.append(FALLBACK_FAMILY)
    out.append(LATIN_FALLBACK)
    return out


def bundled_only() -> List[str]:
    _register_bundled_font()
    return [FALLBACK_FAMILY, LATIN_FALLBACK]


_MISSING_RE = re.compile(r"Glyph (\d+) .*missing from (?:current )?font", re.IGNORECASE)


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def missing_glyphs() -> Iterator[List[str]]:
    """Collect characters matplotlib could not find in any font while drawing."""
    found: List[str] = []
    handler = _Collector()
    loggers = [logging.getLogger(n) for n in ("matplotlib", "matplotlib.font_manager",
                                             "matplotlib.backends.backend_agg", "matplotlib.text",
                                             "matplotlib._text_helpers")]
    for lg in loggers:
        lg.addHandler(handler)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield found
        finally:
            for lg in loggers:
                lg.removeHandler(handler)
            texts = [str(w.message) for w in caught] + handler.messages
            for text in texts:
                m = _MISSING_RE.search(text)
                if m:
                    ch = chr(int(m.group(1)))
                    if ch not in found:
                        found.append(ch)
