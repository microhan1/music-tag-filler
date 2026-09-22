"""settings.json values with type checking.

The file sits next to the exe where anyone can edit it, so nothing in it is
trusted: a wrong type or an unknown value falls back to the default.
"""
from __future__ import annotations

import dataclasses

import i18n
from search_itunes import COUNTRIES, COUNTRY_FOR_LANG


@dataclasses.dataclass
class Prefs:
    country: str = ""  # "" = follow the UI language
    acoustid_key: str = ""
    fpcalc_path: str = ""
    rename: bool = False
    cover_max_px: int = 1000

    def effective_country(self) -> str:
        if self.country in COUNTRIES:
            return self.country
        return COUNTRY_FOR_LANG.get(i18n.current_lang(), "US")


def load() -> Prefs:
    raw = i18n.load_settings()
    default = Prefs()

    def typed(key: str, kind: type):
        value = raw.get(key)
        ok = isinstance(value, kind) and (kind is bool or not isinstance(value, bool))
        return value if ok else getattr(default, key)

    p = Prefs(
        country=typed("country", str).upper(),
        acoustid_key=typed("acoustid_key", str).strip(),
        fpcalc_path=typed("fpcalc_path", str),
        rename=typed("rename", bool),
        cover_max_px=typed("cover_max_px", int),
    )
    if p.country not in COUNTRIES:
        p.country = ""
    if not 200 <= p.cover_max_px <= 4000:
        p.cover_max_px = default.cover_max_px
    return p


def save(p: Prefs) -> None:
    settings = i18n.load_settings()
    settings.update(dataclasses.asdict(p))
    i18n.save_settings(settings)
