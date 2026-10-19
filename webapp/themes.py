"""Colour themes: every channel has one of the approved palettes; the whole app wears the
active channel's palette. New channels, and channels never given one, use Ember."""

from collections import OrderedDict
from typing import Optional

from webapp.queue import ActionError

DEFAULT = "ember"
# name -> (label, swatch colour 1, swatch colour 2), in the approved preview's order.
PALETTES = OrderedDict([
    ("sunset", ("Sunset", "#ff7a85", "#ff9a6b")),
    ("aurora", ("Aurora", "#2563eb", "#22d3a6")),
    ("blossom", ("Blossom", "#ff5fa2", "#8b46e0")),
    ("forest", ("Forest", "#34a853", "#f5c451")),
    ("midnight", ("Midnight", "#5b4be8", "#00c2ff")),
    ("ember", ("Ember", "#ff5a36", "#ffb020")),
    ("graphite", ("Graphite", "#2dd4bf", "#f5b942")),
])


def palette(theme: Optional[str]) -> str:
    """The palette to show for a stored value: unknown or unset means Ember."""
    return theme if theme in PALETTES else DEFAULT


def avatar_colour(theme: Optional[str]) -> str:
    return PALETTES[palette(theme)][1]


def set_theme(conn, channel_id: int, theme: str) -> str:
    if theme not in PALETTES:
        raise ActionError("Pick one of the palettes.")
    if not conn.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone():
        raise ActionError("Channel not found.")
    conn.execute("UPDATE channels SET theme = ? WHERE id = ?", (theme, channel_id))
    return theme
