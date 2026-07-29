"""Wild Technology brand tokens for WildScan.

One place for every colour, glyph and the wordmark, so the app reads as one
system. Palette: abyssal navy field, bioluminescent teal primary, coral
accent, sand for warm highlights - the expedition look, readable on any
terminal that supports truecolor and degrading sanely on 256-colour.
"""
from __future__ import annotations

# ----------------------------------------------------------------- palette
ABYSS = "#0B1B26"          # app background - deep water
ABYSS_PANEL = "#102634"    # panel surfaces
ABYSS_EDGE = "#1B3A4D"     # borders / rules
TEAL = "#19D3B5"           # primary - bioluminescence
TEAL_DIM = "#0F8B7A"
CORAL = "#FF6B5E"          # accent / warnings with warmth
SAND = "#E8D5A3"           # highlights, selected text
FOAM = "#C7E8E3"           # body text
MIST = "#6E8B99"           # secondary text
OK = "#3DDC84"
WARN = "#FFC857"
ERR = "#FF5D5D"

# ------------------------------------------------------------------ glyphs
GLYPH_DONE = "●"      # filled circle
GLYPH_PARTIAL = "◑"   # half circle
GLYPH_PENDING = "○"   # open circle
GLYPH_BLOCKED = "■"   # square
GLYPH_ARROW = "→"
GLYPH_WAVE = "≈"

STATUS_GLYPH = {
    "done": GLYPH_DONE,
    "partial": GLYPH_PARTIAL,
    "pending": GLYPH_PENDING,
    "blocked": GLYPH_BLOCKED,
}
STATUS_COLOR = {
    "done": OK,
    "partial": WARN,
    "pending": MIST,
    "blocked": ERR,
}

WORDMARK = r"""
 __        __  ___   _      ____    ____    ____      _      _   _
 \ \      / / |_ _| | |    |  _ \  / ___|  / ___|    / \    | \ | |
  \ \ /\ / /   | |  | |    | | | | \___ \ | |       / _ \   |  \| |
   \ V  V /    | |  | |___ | |_| |  ___) | | |___  / ___ \  | |\  |
    \_/\_/    |___| |_____||____/  |____/   \____|/_/   \_\ |_| \_|
""".strip("\n")

FOOTER_NOTE = "Wild Technology ≈ ocean exploration, open by default"

# ------------------------------------------------------------- Textual CSS
CSS = f"""
Screen {{
    background: {ABYSS};
    color: {FOAM};
}}
#wordmark {{
    color: {TEAL};
    text-style: bold;
    padding: 1 2 0 2;
}}
#tagline {{
    color: {MIST};
    padding: 0 2 1 2;
}}
.panel {{
    background: {ABYSS_PANEL};
    border: round {ABYSS_EDGE};
    padding: 1 2;
    margin: 0 1 1 1;
}}
.panel-title {{
    color: {SAND};
    text-style: bold;
}}
DataTable {{
    background: {ABYSS_PANEL};
    color: {FOAM};
}}
DataTable > .datatable--header {{
    background: {ABYSS_EDGE};
    color: {SAND};
    text-style: bold;
}}
DataTable > .datatable--cursor {{
    background: {TEAL_DIM};
    color: {ABYSS};
}}
Button {{
    background: {TEAL_DIM};
    color: {FOAM};
    border: none;
}}
Button.-primary {{
    background: {TEAL};
    color: {ABYSS};
    text-style: bold;
}}
Button.-warning {{
    background: {CORAL};
    color: {ABYSS};
}}
Input {{
    background: {ABYSS_PANEL};
    border: round {ABYSS_EDGE};
    color: {FOAM};
}}
ProgressBar > .bar--bar {{
    color: {TEAL};
}}
ProgressBar > .bar--complete {{
    color: {OK};
}}
RichLog {{
    background: {ABYSS_PANEL};
    border: round {ABYSS_EDGE};
    color: {FOAM};
}}
Footer {{
    background: {ABYSS_EDGE};
    color: {MIST};
}}
Header {{
    background: {ABYSS_EDGE};
    color: {SAND};
}}
"""
