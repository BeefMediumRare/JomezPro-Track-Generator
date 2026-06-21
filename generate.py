#!/usr/bin/env python3
"""Generate a speed track for one JomezPro video.

Two commands:

    python generate.py <url|id>             build a track file
    python generate.py calibrate <url|id>   dump frames to crop templates from

The track is built in two steps: identify the sections of the video, then turn
those into a track. Sections come from the YouTube chapters (skip the intro and
sponsor lists, normal speed for the closing leaderboard, default speed for the
holes), and each hole's opening drone preview is found by detecting the JOMEZ PRO
banner. Throw detection is planned next.

The track file lands in tracks/JomezPro/ and is validated against the extension's
own parser. See README.md for the Docker usage.
"""

import os
import sys

from src.config import CONFIG
from src import download, frames, detect, track
from src.sections import (build_sections, add_hole_previews, add_throws, add_sponsors,
                          throw_ends, is_hole_chapter)
from src.track import format_timestamp


def _frames_dir(cfg, video_id):
    return os.path.join(cfg.cache_dir, "frames", video_id)


def _tl_dir(cfg, video_id):
    return os.path.join(cfg.cache_dir, "frames_tl", video_id)


def cmd_generate(url_or_id):
    cfg = CONFIG

    print(f"Fetching {url_or_id} ...")
    meta = download.fetch(url_or_id, cfg)
    print(f"  {meta['video_id']} — {meta['title']}")
    print(f"  duration {meta['duration']:.0f}s, {len(meta['chapters'])} chapters")
    if not any(is_hole_chapter(c.get("title")) for c in meta["chapters"]):
        print(
            "  WARNING: no HOLE chapters found. The whole video will play at the "
            "default speed (nothing skipped).",
            file=sys.stderr,
        )

    analysis = build_sections(meta["duration"], meta["chapters"], meta["title"])
    print(f"  detected round: {analysis.round}, nine: {analysis.nine}")

    # Detect the two graphics: the hole-preview banner (drone shots) and the
    # player card (throws). Each is matched only inside its own search box.
    specs = {}
    try:
        specs["preview"] = (detect.load_template(cfg.hole_preview_template, "hole preview"),
                            cfg.preview_search_box, cfg.hole_preview_threshold)
    except detect.TemplateError as e:
        print(f"  WARNING: {e} Skipping hole previews.", file=sys.stderr)
    try:
        specs["throw"] = (detect.load_template(cfg.throw_label_template, "throw label"),
                          cfg.throw_search_box, cfg.throw_threshold)
    except detect.TemplateError as e:
        print(f"  WARNING: {e} Skipping throws.", file=sys.stderr)

    if specs:
        print("Extracting frames ...")
        fr = frames.extract_band(meta["video_path"], _frames_dir(cfg, meta["video_id"]), cfg)
        present = detect.detect(fr, specs)
        if "preview" in present:
            print(f"  hole-preview banner seen in {len(present['preview'])} of {len(fr)} frames")
            analysis.sections = add_hole_previews(analysis.sections, present["preview"], cfg)
        if "throw" in present:
            diffs = detect.card_diffs(fr, {"card": cfg.diff_box, "counter": cfg.counter_box})
            signals = [(diffs["card"], cfg.transition_threshold),
                       (diffs["counter"], cfg.counter_threshold)]
            ends = throw_ends(present["throw"], signals, cfg)
            print(f"  player card seen in {len(present['throw'])} of {len(fr)} frames, "
                  f"{len(ends)} throws (look-ahead)")
            analysis.sections = add_throws(analysis.sections, present["throw"], signals, cfg)

            # Sponsor blocks: the tournament logo (top-left) vanishes during baked-in
            # ads. Derive the logo from play frames spread across the whole video
            # (different holes = different backgrounds, so only the logo is constant),
            # then scan.
            present_secs = sorted(present["throw"])
            if present_secs:
                tl = frames.extract_top_left(meta["video_path"], _tl_dir(cfg, meta["video_id"]), cfg)
                tl_map = dict(tl)
                step = max(1, len(present_secs) // cfg.logo_sample_count)
                sample = [(s, tl_map[s]) for s in present_secs[::step] if s in tl_map]
                logo = detect.derive_logo(sample, cfg)
                if logo:
                    presence = detect.logo_presence(tl, logo, cfg)
                    analysis.sections = add_sponsors(analysis.sections, presence, cfg)
                    n = sum(1 for s in analysis.sections if s.kind == "sponsor")
                    print(f"  tournament logo derived (hue {logo['hue']}); {n} sponsor block(s)")
                else:
                    print("  WARNING: couldn't derive the tournament logo (static first "
                          "block?); skipping sponsor detection.", file=sys.stderr)

    print("Sections:")
    for s in analysis.sections:
        print(f"  {format_timestamp(s.start):>7} - {format_timestamp(s.end):<7} {s.kind:<11} {s.label}")

    cues = track.sections_to_cues(analysis.sections, analysis.round, analysis.nine, cfg)
    print("Track cues:")
    for c in cues:
        print(f"  {format_timestamp(c['t']):>7}  speed {c['code']}")

    doc = track.build_track(meta["video_id"], meta["title"], cues)
    path = track.write_track(doc, cfg.output_dir)
    print(f"Wrote {path} ({len(cues)} cues)")

    ok, msg = track.validate_with_extension(path, cfg.ext_parser_path)
    if ok is True:
        print("Validation: passed (extension validateTrack)")
    elif ok is False:
        print(f"Validation: FAILED — {msg}", file=sys.stderr)
        return 1
    else:
        print(f"Validation: {msg}", file=sys.stderr)
    return 0


def cmd_calibrate(url_or_id):
    cfg = CONFIG
    print(f"Fetching {url_or_id} ...")
    meta = download.fetch(url_or_id, cfg)
    out_dir = os.path.join(cfg.calibration_dir, meta["video_id"])
    print(f"Dumping calibration frames every {cfg.calibrate_every_sec:.0f}s ...")
    fr = frames.extract_for_calibration(meta["video_path"], out_dir, cfg)
    print(f"Wrote {len(fr)} frames to {out_dir}")
    print("Open them and crop reference images for detection:")
    print(f"  - the hole preview banner (JOMEZ PRO logo)  -> {cfg.hole_preview_template}")
    print(f"  - the THROW label on the player card        -> {cfg.throw_label_template}")
    return 0


def main(argv):
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "calibrate":
        if len(args) < 2:
            print("usage: generate.py calibrate <url|id>", file=sys.stderr)
            return 2
        return cmd_calibrate(args[1])
    return cmd_generate(args[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
