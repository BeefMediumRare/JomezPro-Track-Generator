"""Identify the sections of a video. The track is then built from them.

This is the first of the two steps. It returns a SectionAnalysis: the sections
plus video-level metadata read while classifying them (right now, which round the
video covers). A Section is a contiguous span [start, end) with a kind (what the
region is) and a label (where it came from). Sections carry no speed: how a kind
maps to a speed, and merging neighbours that end up at the same speed, is the
track-building step's job (see track.sections_to_cues).

Right now sections come only from the YouTube chapters, classified by kind:
  - "hole"        -> a HOLE chapter (hole previews and throws will later subdivide)
  - "leaderboard" -> the closing leaderboard recap
  - "leaderboard_open" -> a LEADERBOARD right after START (front-9 recap; skipped)
  - "intro"       -> any non-hole chapter before the first hole
  - "outro"       -> any other non-hole chapter (after the holes)

If there are no HOLE chapters, the whole video is one "video" section, so a video
without chapters still produces a track instead of being classified wrongly.

The round and the nine (front or back) are read from the title and ride on the
analysis, so the track step can vary speeds by where the video sits in the
tournament. The round is bucketed into the distinctions that matter to us (first,
final, or any other round): a hole on round 1 is worth more time than the same
hole later, once you've seen it. The nine matters for the intro and outro, where
only the tournament's opener (round 1, front 9) and closer (final, back 9) are
worth playing; every other video's intro and outro are skipped.
"""

import re
from dataclasses import dataclass, field


@dataclass
class Section:
    start: float
    end: float
    kind: str
    label: str


@dataclass
class SectionAnalysis:
    sections: list = field(default_factory=list)
    round: str = "first"   # "first" | "final" | "rest"
    nine: str = None       # "front" | "back" | None


def is_hole_chapter(title):
    """A hole chapter is titled 'HOLE 1', 'HOLE 2', etc. (any case)."""
    return bool(re.match(r"\s*hole\b", title or "", re.I))


def is_leaderboard_chapter(title):
    """The closing leaderboard recap, e.g. 'PDGA LEADERBOARD CHECK-IN'."""
    return bool(re.search(r"leaderboard", title or "", re.I))


def parse_round(title):
    """Round token from a JomezPro title. The round sits inside a token like
    'R1F9' (round 1, front 9) or 'R2B9', and finals read as 'FINALB9'. Returns the
    round number as an int (R1 -> 1), the string 'FINAL', or None."""
    t = title or ""
    m = re.search(r"\bR(?:ound)?\s*(\d+)", t, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"\bFINAL", t, re.I):
        return "FINAL"
    return None


def classify_round(title):
    """Bucket the round into the distinctions we care about: 'first' (round 1),
    'final', or 'rest' (any other round). A round we can't read is treated as
    'first', the conservative choice (less speeding up)."""
    rnd = parse_round(title)
    if rnd == "FINAL":
        return "final"
    if rnd == 1 or rnd is None:
        return "first"
    return "rest"


def parse_nine(title):
    """Which nine the video covers, read from the title's 'F9' / 'B9' token (as in
    'R1F9' or 'FINALB9'). Returns 'front', 'back', or None."""
    t = title or ""
    if re.search(r"F9\b", t, re.I) or re.search(r"\bfront\s*9\b", t, re.I):
        return "front"
    if re.search(r"B9\b", t, re.I) or re.search(r"\bback\s*9\b", t, re.I):
        return "back"
    return None


def _first_preview_run(present_in_hole, cfg):
    """The first contiguous detection run within a hole (small sampling gaps
    bridged), as (run_start, run_end). None if there's nothing, or the run is too
    short to trust."""
    if not present_in_hole:
        return None
    run_start = run_end = present_in_hole[0]
    for t in present_in_hole[1:]:
        if t - run_end <= cfg.merge_gap:
            run_end = t
        else:
            break
    if run_end - run_start + 1 < cfg.debounce_frames:
        return None
    return run_start, run_end


def add_hole_previews(sections, present_seconds, cfg):
    """Split each HOLE section into a leading 'preview' sub-section and the rest of
    the 'hole', using where the hole-preview banner (the JOMEZ PRO logo) was seen.

    The preview is the drone shot at the start of a hole. It runs from the hole's
    start to where the banner disappears: the banner comes in a few seconds in and
    stays to the end of the preview, so the end of its first detection run marks
    the preview's end. The preview itself starts at the hole boundary, covering the
    few seconds of drone footage before the banner appears. A hole with no banner
    near its start is left whole.

    present_seconds: seconds (any order) where the banner was detected, across the
    whole video. Pure: takes detections, returns refined sections."""
    present = sorted({int(round(t)) for t in present_seconds})
    out = []
    for s in sections:
        if s.kind != "hole":
            out.append(s)
            continue
        inside = [t for t in present if s.start <= t < s.end]
        run = _first_preview_run(inside, cfg)
        if run is None or run[0] - s.start > cfg.preview_max_start_delay:
            out.append(s)
            continue
        preview_end = min(run[1], s.end)
        out.append(Section(s.start, preview_end, "preview", s.label))
        if preview_end < s.end:
            out.append(Section(preview_end, s.end, "hole", s.label))
    return out


def _present_runs(present_seconds, cfg):
    """Card-present runs as (start, end) in seconds (end = last present second).
    A run bridges gaps up to throw_max_absent (the score flashes when a putt
    drops). These runs are the segments where throws happen."""
    present = sorted({int(round(t)) for t in present_seconds})
    if not present:
        return []
    runs = [[present[0], present[0]]]
    for t in present[1:]:
        if t - runs[-1][1] - 1 <= cfg.throw_max_absent:
            runs[-1][1] = t
        else:
            runs.append([t, t])
    return [(a, b) for a, b in runs if b - a + 1 >= cfg.debounce_frames]


def throw_ends(present_seconds, signals, cfg):
    """Seconds where a throw ends. Sources: any diff signal spiking above its
    threshold (the whole-card diff catches player transitions; the counter diff
    catches a same-player next throw), gated to where the card is present on both
    sides so camera motion can't fake one; plus the card disappearing (the end of a
    present run, the last player's throw). signals is a list of (diffs, threshold),
    each diffs being [(second, value)]. The transition animation straddles two
    samples, so consecutive spikes collapse to the first."""
    present = {int(round(s)) for s in present_seconds}
    spikes = set()
    for diffs, threshold in signals:
        for s, d in diffs:
            if d >= threshold and s in present and (s - 1) in present:
                spikes.add(s)
    ends = []
    prev_spike = None
    for s in sorted(spikes):
        if prev_spike is None or s - prev_spike > 1:   # start of a new spike run
            ends.append(s)
        prev_spike = s
    for (a, b) in _present_runs(present_seconds, cfg):
        ends.append(b)
    return sorted(set(ends))


def made_putt_events(putt_seconds, cfg):
    """Seconds where a putt was made. The reveal-colour detection (detect.made_putts)
    flickers a little, so seconds within 2s are bridged into a run and a run must last
    debounce_frames to count; the run's start is the putt moment. A real putt comes
    clustered with the rest of the group putting out on the same hole, so an event
    counts only if another event falls within putt_neighbor_sec — a lone reveal (an ace
    or a throw-in) is dropped. Pure."""
    present = sorted({int(round(t)) for t in putt_seconds})
    if not present:
        return []
    runs = [[present[0], present[0]]]
    for t in present[1:]:
        if t - runs[-1][1] <= 2:   # bridge a dropped frame inside one reveal
            runs[-1][1] = t
        else:
            runs.append([t, t])
    events = [a for a, b in runs if b - a + 1 >= cfg.debounce_frames]
    return [e for e in events
            if any(o != e and abs(o - e) <= cfg.putt_neighbor_sec for o in events)]


def _throw_windows(ends, cfg):
    """Normal-speed [start, end] window for each throw, from the sorted throw-end
    seconds (transitions, and the card vanishing). The transition lands just after the
    disc has come to rest, so the window ends throw_end_pad seconds before it; the
    throw plays for up to throw_lead seconds before that, but never starts until
    throw_min_gap seconds after the previous throw end (the next player needs a beat to
    set up). So a closely-spaced pair of ends yields a window shorter than throw_lead,
    and one closer than throw_end_pad + throw_min_gap yields none."""
    ends = sorted(ends)
    windows = []
    for i, e in enumerate(ends):
        end = e - cfg.throw_end_pad
        start = end - cfg.throw_lead
        if i > 0:
            start = max(start, ends[i - 1] + cfg.throw_min_gap)
        if end > start:
            windows.append((start, end))
    return windows


def _merge_intervals(intervals):
    """Join overlapping [start, end] windows into the minimal set of disjoint ones.
    Sorted by start so a putt's short window and a throw's long one merge correctly."""
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def add_throws(sections, present_seconds, signals, putt_seconds, cfg):
    """Split each HOLE section into 'hole' and 'throw' segments. The card-present
    detection marks where throws happen; individual throws are the look-ahead windows
    ending a little before each detected throw end (see _throw_windows) or at each made
    putt (the tighter putt_lead). A putt overwrites the throw it ends: any throw end
    within putt_suppress_sec after a putt is the putt being scored, not a separate
    throw, so it's dropped and the putt's short window stands in its place. Pure: takes
    detections, returns refined sections."""
    putts = made_putt_events(putt_seconds, cfg)
    ends = [e for e in throw_ends(present_seconds, signals, cfg)
            if not any(0 <= e - p <= cfg.putt_suppress_sec for p in putts)]
    windows = _merge_intervals(_throw_windows(ends, cfg) +
                               [(p - cfg.putt_lead, p) for p in putts])
    out = []
    for s in sections:
        if s.kind != "hole":
            out.append(s)
            continue
        local = [(max(a, s.start), min(b, s.end)) for (a, b) in windows
                 if min(b, s.end) > max(a, s.start)]
        if not local:
            out.append(s)
            continue
        cur = s.start
        for (a, b) in local:
            if a > cur:
                out.append(Section(cur, a, "hole", s.label))
            out.append(Section(max(a, cur), b, "throw", s.label))
            cur = b
        if cur < s.end:
            out.append(Section(cur, s.end, "hole", s.label))
    return out


def _smooth(presence, window):
    """Rolling mean of a [(second, value)] signal over `window` seconds."""
    vals = {s: v for s, v in presence}
    out = []
    for s, v in presence:
        win = [vals[t] for t in range(s - window + 1, s + 1) if t in vals]
        out.append((s, sum(win) / len(win) if win else v))
    return out


def logo_absence_runs(presence, cfg):
    """Contiguous spans where the smoothed logo presence stays below the threshold.
    The minimum-length check is NOT applied here — it's applied per sponsor segment
    in add_sponsors, after a run has been clipped to a hole and split by previews,
    so a short leftover beside a preview doesn't pass on the strength of the long
    run it came from."""
    smoothed = _smooth(presence, cfg.sponsor_window)
    absent = sorted(s for s, v in smoothed if v < cfg.logo_present_threshold)
    runs = []
    for s in absent:
        if runs and s - runs[-1][1] <= 1:
            runs[-1][1] = s
        else:
            runs.append([s, s])
    return [(a, b) for a, b in runs]


def add_sponsors(sections, presence, cfg):
    """Split HOLE sections where the tournament logo is absent (a baked-in ad) into
    'sponsor' segments. Only 'hole' sections are touched, so this never fires inside
    a preview (the logo is gone there too, but it's already its own kind) or outside
    the holes — and clipping to the section's end naturally ends a sponsor at the
    next hole's chapter start. A segment counts as a sponsor only if it lasts at
    least sponsor_min_absent (ads are long; a brief ambience shot between the
    preview and the throws is not). Pure: takes the presence signal."""
    runs = logo_absence_runs(presence, cfg)
    out = []
    for s in sections:
        if s.kind != "hole":
            out.append(s)
            continue
        local = [(max(a, s.start), min(b, s.end)) for (a, b) in runs
                 if min(b, s.end) - max(a, s.start) >= cfg.sponsor_min_absent]
        if not local:
            out.append(s)
            continue
        cur = s.start
        for (a, b) in local:
            if a > cur:
                out.append(Section(cur, a, "hole", s.label))
            out.append(Section(max(a, cur), b, "sponsor", s.label))
            cur = b
        if cur < s.end:
            out.append(Section(cur, s.end, "hole", s.label))
    return out


def build_sections(duration, chapters, title=""):
    """Classify a video into a SectionAnalysis (sections + detected round + nine)."""
    rnd = classify_round(title)
    nine = parse_nine(title)
    chapters = chapters or []
    hole_idxs = [i for i, c in enumerate(chapters) if is_hole_chapter(c.get("title"))]
    if not hole_idxs:
        whole = Section(0.0, float(duration), "video", "whole video (no HOLE chapters)")
        return SectionAnalysis(sections=[whole], round=rnd, nine=nine)

    first_hole = hole_idxs[0]
    sections = []
    for i, c in enumerate(chapters):
        ctitle = (c.get("title") or "").strip()
        start = float(c.get("start_time", 0) or 0)
        end = float(c.get("end_time", duration) or duration)
        if is_hole_chapter(ctitle):
            kind = "hole"
        elif is_leaderboard_chapter(ctitle):
            # A leaderboard before the first hole is the opening recap (right after
            # START) — you've already watched the earlier nine, so it's skipped. The
            # leaderboard after the holes is the closing recap and keeps its kind.
            kind = "leaderboard_open" if i < first_hole else "leaderboard"
        elif i < first_hole:
            kind = "intro"
        else:
            kind = "outro"
        sections.append(Section(start, end, kind, ctitle))
    return SectionAnalysis(sections=sections, round=rnd, nine=nine)
