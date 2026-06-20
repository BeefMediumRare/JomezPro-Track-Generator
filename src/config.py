"""Tunable settings for the generator, in one place.

Paths can be overridden by environment variables so the Docker setup can point at
mounted folders without changing code. Detection numbers are the knobs you turn
when throw windows clip a throw or trigger on walking footage.

Two graphics are matched, each with its own template and threshold:
  - the hole preview (JOMEZ PRO logo + distance), shown at the start of a hole
  - the player card (name + THROW counter), shown when a player throws
"""

import os
from dataclasses import dataclass, field


def _env(name, default):
    value = os.environ.get(name)
    return value if value else default


@dataclass
class Config:
    # --- Where things live (host paths are bind-mounted in Docker) ---
    cache_dir: str = field(default_factory=lambda: _env("CACHE_DIR", ".cache"))
    output_dir: str = field(default_factory=lambda: _env("OUTPUT_DIR", "tracks/JomezPro"))
    calibration_dir: str = field(default_factory=lambda: _env("CALIBRATION_DIR", "calibration"))
    hole_preview_template: str = field(default_factory=lambda: _env("HOLE_PREVIEW_TEMPLATE", "assets/hole-preview.png"))
    throw_label_template: str = field(default_factory=lambda: _env("THROW_LABEL_TEMPLATE", "assets/throw-label.png"))
    # Path to the extension's parser.js, used as the validation gate. Empty or
    # missing => validation is skipped with a warning (still writes the file).
    ext_parser_path: str = field(default_factory=lambda: _env("EXT_PARSER_PATH", "../Ain-t-Nobody-Got-Time-for-That/src/parser.js"))

    # --- Frame sampling / cropping ---
    sample_fps: float = 1.0           # frames per second analysed
    calibrate_every_sec: float = 5.0  # how often to dump a frame in calibrate mode
    # Frames are scaled to a fixed height (no-op for a 720p source, normalises
    # anything else) so the templates stay a stable size, then cropped to the
    # bottom band that holds both graphics.
    scale_height: int = 720
    analyze_bottom_frac: float = 0.34

    # The graphics sit in fixed spots, so each is matched only inside its own
    # search box — fractions (x0, y0, x1, y1) of the analysed bottom band. Boxes
    # are roughly 3x the asset, giving it room to shift without false matches
    # elsewhere on screen.
    preview_search_box: tuple = (0.596, 0.155, 0.765, 1.0)   # JOMEZ PRO logo (centre-right)
    throw_search_box: tuple = (0.147, 0.616, 0.367, 0.800)   # THROW label (bottom-left card)
    # The whole player card, diffed frame-to-frame to spot player transitions: when
    # the card rotates to the next player, everything inside changes at once.
    diff_box: tuple = (0.042, 0.563, 0.288, 0.767)
    # Just the THROW counter (the digits, wide enough for a par-5's 1 2 3 4 5). A
    # same-player next throw only ticks the counter — too small for the whole-card
    # diff, but obvious here.
    counter_box: tuple = (0.221, 0.735, 0.286, 0.796)

    # --- Graphic detection (matchTemplate score that counts as "present") ---
    hole_preview_threshold: float = 0.70
    throw_threshold: float = 0.70
    debounce_frames: int = 2          # a graphic needs at least this many present frames
    # A player transition (throw end) is a frame-to-frame change in the card region
    # above this. Real transitions run from ~12 up to 130; the floor is set low on
    # purpose — extra detections are harmless, since the look-ahead windows merge.
    transition_threshold: float = 12.0
    # The counter ticking (or resetting) spikes its small box to 40+, baseline ~0.3.
    counter_threshold: float = 15.0

    # --- Turning detections into windows (seconds) ---
    pad_before: int = 2               # extend each window earlier so the run-up isn't clipped
    pad_after: int = 2                # ...and later so the landing isn't clipped
    merge_gap: int = 3                # join two windows closer than this
    # The hole-preview banner appears a few seconds into a hole. If its detection
    # run starts later than this into the hole, it isn't the opening preview.
    preview_max_start_delay: int = 60

    # The THROW label marks a segment where throws happen; it stays "present"
    # through a short gap (the score flashes up when a putt drops). The segment
    # ends once the label has been gone for more than this many seconds.
    throw_max_absent: int = 2
    # Individual throws are found by the look-ahead: each throw end (a transition,
    # or the card disappearing) plays normal speed for this many seconds before it.
    throw_lead: int = 18

    # --- Speed codes (strings, matching the track format) ---
    # 1 normal, 2 fast, 3 faster, 4 skip.
    speed_throw: str = "1"            # the parts worth watching, at normal speed
    speed_leaderboard: str = "1"      # the closing leaderboard recap, at normal speed
    speed_default: str = "2"          # walking / setup / banter
    speed_skip: str = "4"             # intro, sponsor lists, and other non-play chapters
    # Hole previews: slower on round 1 (you haven't seen the hole), faster after.
    preview_speed_round1: str = "2"
    preview_speed_other: str = "3"

    # --- Download target: 720p video, for crisp graphics to match against ---
    # Prefer a video-only stream (no audio: we never use it, and it avoids a merge).
    download_format: str = (
        "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/"
        "best[height<=720][ext=mp4]/best[height<=720]/best"
    )


CONFIG = Config()
