"""gfonts: warn when a brand font is not on Google Fonts (the piece would fall back to a generic font)."""

import os
import urllib.error
import urllib.parse
import urllib.request

WARN = ('"{n}" is not on Google Fonts: the piece falls back to a generic font; put the font files next to the piece '
        "or pick a Google font")


def check(names) -> list:
    """One warning per font Google answers 400 for. Offline or unreachable: silent, we cannot know."""
    if os.environ.get("STUDIO_OFFLINE") == "1":
        return []
    out = []
    for n in filter(None, (x.strip() for x in names if x)):
        url = "https://fonts.googleapis.com/css2?family=" + urllib.parse.quote_plus(n)
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=5).close()
        except urllib.error.HTTPError as err:
            if err.code == 400:
                out.append(WARN.format(n=n))
        except Exception:
            pass
    return out
