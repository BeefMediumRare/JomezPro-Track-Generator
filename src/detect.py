"""Decide, frame by frame, which JomezPro graphic is on screen.

Each graphic sits in a fixed spot, so we match its reference template only inside
its own search box (a fraction of the analysed band) rather than across the whole
frame. That kills false matches on grass and shadows elsewhere, and lets the
threshold be strict. Within the box we use OpenCV's normalized cross-correlation
and take the best score; a frame whose best score clears the template's threshold
counts as a hit. Each frame is read once and matched against every graphic.

Two graphics matter here:
  - the hole preview (the JOMEZ PRO logo) at the start of a hole
  - the player card (the THROW label) shown while a player throws
"""

import os

import cv2
import numpy as np


class TemplateError(Exception):
    pass


def load_template(path, label):
    if not path or not os.path.exists(path):
        raise TemplateError(
            f"No {label} template at {path!r}. Run the 'calibrate' command first "
            f"and crop the graphic into that file."
        )
    tmpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if tmpl is None:
        raise TemplateError(f"Could not read {label} template at {path!r}.")
    return tmpl


def _box_px(box_frac, h, w):
    x0, y0, x1, y1 = box_frac
    return (max(0, int(x0 * w)), max(0, int(y0 * h)),
            min(w, int(x1 * w)), min(h, int(y1 * h)))


def _score_in_box(frame_gray, template, box_frac):
    h, w = frame_gray.shape
    x0, y0, x1, y1 = _box_px(box_frac, h, w)
    region = frame_gray[y0:y1, x0:x1]
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return 0.0
    res = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


def detect(frames, specs):
    """Match every graphic against every frame, each inside its own search box.

    frames: [(second, path)].
    specs: {name: (gray_template, box_frac, threshold)}.
    Returns {name: [seconds where present]}.
    """
    present = {name: [] for name in specs}
    for second, path in frames:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        for name, (tmpl, box, threshold) in specs.items():
            if _score_in_box(img, tmpl, box) >= threshold:
                present[name].append(second)
    return present


def derive_logo(frames_subset, cfg):
    """Find the tournament logo in the top-left corner from a set of play frames.
    The logo sits at a fixed spot while the background moves, so across frames its
    pixels have low variance and the background's is high. We threshold the variance
    map (Otsu) to a logo mask, take its bounding box, and sample the logo's hue from
    the masked pixels (so it adapts to whatever colour the logo is this season).

    frames_subset: [(second, path)], best sampled across the whole video so the
    backgrounds differ (one static stretch would leave its background looking as
    constant as the logo). Returns {mask, bbox, hue} or None if the logo can't be
    told apart — too little background movement leaves the mask bloated."""
    grays, bgrs = [], []
    for second, path in frames_subset:
        bgr = cv2.imread(path)
        if bgr is None:
            continue
        bgrs.append(bgr)
        grays.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32))
    if len(grays) < 5:
        return None

    std = np.stack(grays).std(0)
    sn = (std / (std.max() + 1e-6) * 255).astype(np.uint8)
    _, m = cv2.threshold(sn, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = m > 0
    # Sanity: the logo is a small, stable patch against a moving background. A real
    # logo is a few percent of the corner; if the mask is much bigger, or the
    # "background" isn't much more variable than the "logo", the camera didn't move
    # enough to separate them and the mask is contaminated — bail.
    if mask.sum() < 30 or mask.mean() > 0.25:
        return None
    if std[~mask].mean() < 1.5 * std[mask].mean():
        return None

    ys, xs = np.where(mask)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    hues = [cv2.cvtColor(b, cv2.COLOR_BGR2HSV)[:, :, 0][mask] for b in bgrs[::max(1, len(bgrs) // 5)]]
    hue = int(np.median(np.concatenate(hues)))
    return {"mask": mask, "bbox": bbox, "hue": hue}


def logo_presence(frames, logo, cfg):
    """Per second, the fraction of the logo's pixels that show the logo's colour.
    High when the logo is on screen, ~0 when it's gone (an ad, a preview, a recap).
    Returns [(second, fraction), ...]."""
    mask = logo["mask"]
    lo = (logo["hue"] - cfg.logo_hue_tolerance) % 180
    hi = (logo["hue"] + cfg.logo_hue_tolerance) % 180
    out = []
    for second, path in frames:
        bgr = cv2.imread(path)
        if bgr is None:
            continue
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:, :, 0][mask], hsv[:, :, 1][mask], hsv[:, :, 2][mask]
        hue_ok = (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)
        present = hue_ok & (s >= cfg.logo_sat_min) & (v >= cfg.logo_val_min)
        out.append((second, float(present.mean())))
    return out


def card_diffs(frames, boxes):
    """Mean absolute frame-to-frame difference inside each box, per second. A big
    value means that region changed. boxes: {name: box_frac}. Returns
    {name: [(second, diff), ...]}; the first frame has no prior, so it's skipped.
    All boxes are measured in one pass over the frames."""
    out = {name: [] for name in boxes}
    prev = {name: None for name in boxes}
    for second, path in frames:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            prev = {name: None for name in boxes}
            continue
        h, w = img.shape
        for name, box in boxes.items():
            x0, y0, x1, y1 = _box_px(box, h, w)
            roi = img[y0:y1, x0:x1].astype(np.float32)
            p = prev[name]
            if p is not None and p.shape == roi.shape:
                out[name].append((second, float(np.abs(roi - p).mean())))
            prev[name] = roi
    return out
