"""
Internationalization engine for the web panel.
Loads JSON locale files and provides a `_()` translation function.
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional

LOCALE_DIR = Path(__file__).parent / "locales"

SUPPORTED_LANGS = {
    "zh_CN": "中文",
    "en_US": "English",
}

_cache: Dict[str, Dict[str, str]] = {}


def load_locale(lang: str) -> Dict[str, str]:
    if lang in _cache:
        return _cache[lang]
    file_path = LOCALE_DIR / f"{lang}.json"
    if not file_path.exists():
        lang = "en_US"
        file_path = LOCALE_DIR / f"{lang}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _cache[lang] = data
    return data


def detect_lang(accept_language: str, cookie_lang: Optional[str], query_lang: Optional[str]) -> str:
    if query_lang and query_lang in SUPPORTED_LANGS:
        return query_lang
    if cookie_lang and cookie_lang in SUPPORTED_LANGS:
        return cookie_lang
    if accept_language:
        for part in accept_language.split(","):
            code = part.strip().split(";")[0].replace("-", "_")
            if code.startswith("zh"):
                return "zh_CN"
            if code.startswith("en"):
                return "en_US"
    return "en_US"


def make_translator(lang: str):
    locale = load_locale(lang)

    def _(key: str, **kwargs) -> str:
        val = locale.get(key, key)
        if kwargs:
            val = re.sub(r"\{(\w+)\}", lambda m: str(kwargs.get(m.group(1), m.group(0))), val)
        return val

    return _
