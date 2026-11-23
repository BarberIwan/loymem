"""Brand colour on the card: pick the text colour that stays readable.

Any colour a business picks gets text with at least 4.5:1 contrast (WCAG AA).
Of pure black and white one always reaches 4.58:1, so the guarantee holds for
every colour; the warm ink and ivory from DESIGN.md are preferred when they pass.
"""

from __future__ import annotations

INK = "#1B1916"
IVORY = "#FBF9F4"
BLACK = "#000000"
WHITE = "#FFFFFF"
AA = 4.5


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def card_text_colour(background: str) -> str:
    preferred = max((INK, IVORY), key=lambda c: contrast(background, c))
    if contrast(background, preferred) >= AA:
        return preferred
    return max((BLACK, WHITE), key=lambda c: contrast(background, c))


def card_palette(background: str) -> dict[str, str]:
    text = card_text_colour(background)
    return {"background": background.upper(), "text": text}
