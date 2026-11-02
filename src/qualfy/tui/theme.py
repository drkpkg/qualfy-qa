from __future__ import annotations

from textual.theme import Theme

# Colors from the qualfy icon: plum quail, orange crest, cream tile.
QUALFY_DARK = Theme(
    name="qualfy",
    primary="#9B6BB5",
    secondary="#5B2C6F",
    accent="#F7A043",
    warning="#F7A043",
    error="#E5534B",
    success="#57AB5A",
    foreground="#F3E9F7",
    background="#1C1424",
    surface="#251B2F",
    panel="#33253F",
    dark=True,
)

QUALFY_LIGHT = Theme(
    name="qualfy-light",
    primary="#5B2C6F",
    secondary="#9B6BB5",
    accent="#E0812A",
    warning="#E0812A",
    error="#C93C37",
    success="#2E7D32",
    foreground="#2B1736",
    background="#FBF5F1",
    surface="#FFFFFF",
    panel="#F3E3D3",
    dark=False,
)


def install(app) -> None:
    for theme in (QUALFY_DARK, QUALFY_LIGHT):
        app.register_theme(theme)
    app.theme = "qualfy"
