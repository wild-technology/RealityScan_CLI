"""Image preprocessing variants for reconstruction-success testing.

Each variant is a dict of parameters; build_transform() turns it into a
callable applied to every image (BGR numpy array in, BGR out). Variants
with no parameters (baseline) return None = byte-for-byte copy.

CLAHE is applied to the L channel in LAB space so contrast is enhanced
without shifting color, which matters for feature matching on underwater
imagery. Gray-world white balance counteracts the blue/green cast.
"""

from __future__ import annotations

import cv2
import numpy as np

# First test round: baseline plus the standard underwater-imagery treatments.
ROUND1_VARIANTS = [
    {'name': 'baseline'},
    {'name': 'clahe_c2_t8', 'clahe_clip': 2.0, 'clahe_tile': 8},
    {'name': 'clahe_c4_t8', 'clahe_clip': 4.0, 'clahe_tile': 8},
    {'name': 'wb_clahe_c2_t8', 'white_balance': True, 'clahe_clip': 2.0, 'clahe_tile': 8},
]


def gray_world_white_balance(img: np.ndarray) -> np.ndarray:
    result = img.astype(np.float32)
    means = result.reshape(-1, 3).mean(axis=0)
    overall = means.mean()
    for c in range(3):
        if means[c] > 1e-6:
            result[:, :, c] *= overall / means[c]
    return np.clip(result, 0, 255).astype(np.uint8)


def clahe_lab(img: np.ndarray, clip: float, tile: int) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile))
    l_channel = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)


def build_transform(params: dict):
    """Returns a BGR->BGR callable for this variant, or None for a plain copy."""
    steps = []
    if params.get('white_balance'):
        steps.append(gray_world_white_balance)
    if params.get('clahe_clip'):
        clip = float(params['clahe_clip'])
        tile = int(params.get('clahe_tile', 8))
        steps.append(lambda img, c=clip, t=tile: clahe_lab(img, c, t))

    if not steps:
        return None

    def transform(img):
        for step in steps:
            img = step(img)
        return img

    return transform


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
