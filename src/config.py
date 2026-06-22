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


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name, default):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class Config:
    # --- Where things live (host paths are bind-mounted in Docker) ---
    cache_dir: str = field(default_factory=lambda: _env("CACHE_DIR", ".cache"))
    # Off by default: download, process, then delete the video and frames, so a
    # server/cron run leaves nothing behind. Turn on locally (env KEEP_CACHE=1 or
    # --keep-cache) to reuse downloads and frames while iterating.
    keep_cache: bool = field(default_factory=lambda: _env_bool("KEEP_CACHE", False))
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
    # Top-left corner of the full frame, where the tournament logo sits. Cropped
    # generously; the logo's exact box is then derived from it per video.
    top_left_box: tuple = (0.0, 0.0, 0.34, 0.30)
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

    # --- Sponsor blocks (baked-in ads): the tournament logo vanishes during them ---
    # The logo is derived per video, then its presence is tracked as the fraction of
    # logo-coloured pixels in its box. Smoothed over a window; below the threshold
    # for long enough, inside a hole, is an ad.
    sponsor_window: int = 5            # rolling-average window (seconds) for the signal
    sponsor_min_absent: int = 10       # logo gone at least this long to count as an ad
    # A logo pixel barely moves across play frames; below this temporal std (on the
    # fixed-height grayscale) a pixel counts as stable. Set above the overlay's own
    # flicker (semi-transparent logos let some background through) but well below how
    # much real footage moves, so the logo separates from the background.
    logo_std_max: float = 30.0
    logo_min_blob: int = 5             # drop stable specks smaller than this (px) when finding the logo
    logo_present_threshold: float = 0.3  # smoothed logo-pixel fraction below this = absent
    logo_hue_tolerance: int = 12       # hue band (+/-) around the sampled logo hue
    logo_sat_min: int = 50
    logo_val_min: int = 60
    logo_sample_count: int = 200       # play frames (spread across the video) to derive the logo from

    # --- Speed codes (strings, matching the track format) ---
    # 1 normal, 2 fast, 3 faster, 4 skip.
    speed_throw: str = "1"            # the parts worth watching, at normal speed
    speed_leaderboard: str = "1"      # the closing leaderboard recap, at normal speed
    speed_default: str = "2"          # walking / setup / banter
    speed_skip: str = "4"             # intro, sponsor lists, and other non-play chapters
    # Hole previews: slower on round 1 (you haven't seen the hole), faster after.
    preview_speed_round1: str = "2"
    preview_speed_other: str = "3"

    # --- Server / cron mode (serve.py) ---
    # The channel to scan, and the rule for "this is per-hole tournament coverage".
    # The regex is matched (case-insensitive) against the video title; it picks the
    # MPO per-hole videos (e.g. "... | MPO R1F9 | ...", "... | MPO FINALB9 | ...")
    # and leaves replays, interviews and FPO coverage out.
    channel_url: str = field(default_factory=lambda: _env("CHANNEL_URL", "https://www.youtube.com/@JomezPro/videos"))
    coverage_regex: str = field(default_factory=lambda: _env("COVERAGE_REGEX", r".*MPO.*(R[1-4]|FINAL)[FB]9.*"))
    # How often the server wakes up to scan, and how far back it looks. The age
    # bound also stops the very first scan (empty tracks dir) from pulling the whole
    # back catalogue — only videos this fresh are ever downloaded.
    scan_interval_sec: int = field(default_factory=lambda: _env_int("SCAN_INTERVAL_SEC", 3600))
    max_age_days: float = field(default_factory=lambda: _env_float("MAX_AGE_DAYS", 1.0))
    # How many of the newest uploads to look at per scan. The channel lists newest
    # first, so a handful covers a tournament day with room to spare.
    max_scan_entries: int = field(default_factory=lambda: _env_int("MAX_SCAN_ENTRIES", 50))
    # The repo checkout the server commits tracks into (cloned on first run). Its
    # tracks/JomezPro is where generated tracks land — see OUTPUT_DIR wiring in serve.py.
    repo_dir: str = field(default_factory=lambda: _env("REPO_DIR", ".repo"))
    repo_url: str = field(default_factory=lambda: _env("REPO_URL", "https://github.com/BeefMediumRare/JomezPro-Track-Generator.git"))
    repo_branch: str = field(default_factory=lambda: _env("REPO_BRANCH", "main"))
    # The bot identity for the unsigned commits the server pushes. The push token is
    # read from the GITHUB_TOKEN env var only — never stored here or in .git/config.
    git_user_name: str = field(default_factory=lambda: _env("GIT_USER_NAME", "jomez-track-bot"))
    git_user_email: str = field(default_factory=lambda: _env("GIT_USER_EMAIL", "jomez-track-bot@users.noreply.github.com"))

    # --- Download target: 720p video, for crisp graphics to match against ---
    # Prefer a video-only stream (no audio: we never use it, and it avoids a merge).
    download_format: str = (
        "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/"
        "best[height<=720][ext=mp4]/best[height<=720]/best"
    )


CONFIG = Config()
