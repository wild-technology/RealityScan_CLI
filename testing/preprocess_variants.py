"""Image preprocessing variants for reconstruction-success testing.

Each variant is a dict of parameters; build_transform() turns it into a
callable applied to every image (BGR numpy array in, BGR out). Variants
with no parameters (baseline) return None = byte-for-byte copy.

The transforms themselves live in the pipeline module
(modules/preprocess_images) - this file only defines the variant grid and
refinement logic used by run_zone9_tests.py.
"""

from __future__ import annotations

from modules.preprocess_images.preprocess_images import (  # noqa: F401
    build_transform, clahe_lab, gray_world_white_balance)

# First test round: baseline plus the standard underwater-imagery treatments.
ROUND1_VARIANTS = [
    {'name': 'baseline'},
    {'name': 'clahe_c2_t8', 'clahe_clip': 2.0, 'clahe_tile': 8},
    {'name': 'clahe_c4_t8', 'clahe_clip': 4.0, 'clahe_tile': 8},
    {'name': 'wb_clahe_c2_t8', 'white_balance': True, 'clahe_clip': 2.0, 'clahe_tile': 8},
]


def refine_variants(best: dict, already_tested: set[str]) -> list[dict]:
    """Neighbors of the best round-1 variant for the refinement round.

    Only CLAHE-based winners are refined (clip halved/raised, tile 4/16,
    white balance toggled). A baseline win means preprocessing is not
    helping and there is nothing to refine.
    """
    if not best.get('clahe_clip'):
        return []

    clip = float(best['clahe_clip'])
    tile = int(best.get('clahe_tile', 8))
    wb = bool(best.get('white_balance'))
    wb_prefix = 'wb_' if wb else ''

    candidates = [
        {'name': f'{wb_prefix}clahe_c{clip / 2:g}_t{tile}', 'clahe_clip': clip / 2, 'clahe_tile': tile, 'white_balance': wb},
        {'name': f'{wb_prefix}clahe_c{clip * 1.5:g}_t{tile}', 'clahe_clip': clip * 1.5, 'clahe_tile': tile, 'white_balance': wb},
        {'name': f'{wb_prefix}clahe_c{clip:g}_t4', 'clahe_clip': clip, 'clahe_tile': 4, 'white_balance': wb},
        {'name': f'{wb_prefix}clahe_c{clip:g}_t16', 'clahe_clip': clip, 'clahe_tile': 16, 'white_balance': wb},
        {'name': f'{"" if wb else "wb_"}clahe_c{clip:g}_t{tile}_wbflip', 'clahe_clip': clip, 'clahe_tile': tile, 'white_balance': not wb},
    ]
    return [c for c in candidates if c['name'] not in already_tested]
