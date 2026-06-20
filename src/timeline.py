"""Helpers for turning frame detections into sections.

NOT WIRED IN YET. These support the next steps (hole previews, then throws): the
build pipeline currently makes sections from chapters only (see sections.py). When
preview and throw detection are added back, they will group detected frames into
windows with detections_to_windows and choose the preview speed by round.
"""


def preview_speed_for_round(round_bucket, cfg):
    """Round 1 keeps previews watchable (you haven't seen the hole yet). Later
    rounds and finals speed them up, since the holes have already been shown.
    round_bucket is the value from sections.classify_round."""
    return cfg.preview_speed_round1 if round_bucket == "first" else cfg.preview_speed_other


def detections_to_windows(present_seconds, cfg):
    """Group detected seconds into padded, merged [start, end] windows.

    present_seconds: iterable of seconds (any order) where a graphic was seen.
    """
    present = sorted({int(round(t)) for t in present_seconds})
    if not present:
        return []

    # Group seconds into runs of (near-)consecutive detections.
    runs = []
    for t in present:
        if runs and t - runs[-1][1] <= 1:
            runs[-1][1] = t
        else:
            runs.append([t, t])

    # Debounce: a single stray frame isn't a real graphic.
    runs = [r for r in runs if (r[1] - r[0] + 1) >= cfg.debounce_frames]

    # Pad each side so the run-up and landing aren't clipped.
    padded = [[max(0, r[0] - cfg.pad_before), r[1] + cfg.pad_after] for r in runs]

    # Merge windows that are close enough to be one block.
    merged = []
    for r in padded:
        if merged and r[0] - merged[-1][1] <= cfg.merge_gap:
            merged[-1][1] = max(merged[-1][1], r[1])
        else:
            merged.append(r)
    return merged
