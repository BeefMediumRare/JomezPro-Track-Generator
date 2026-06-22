"""Build the track document, name its file, and validate it.

The format and the filename rules are the extension's, so the helpers here mirror
`formatTimestamp` and `slugifyTitle` from its `parser.js`, and validation is done
by calling that same `parser.js` through node rather than re-checking the rules
here. The extension stays the single source of truth.
"""

import json
import os
import re
import subprocess

SCHEMA_VERSION = 1

# Title and description shown in the extension. Every generated track does the same
# thing, so these describe the behaviour, not the video (the video is identified by
# youtubeVideoId). Time saved isn't mentioned — it depends on the viewer's own speed
# settings, so that's the extension's to show.
TRACK_TITLE = "Focus on Throws"
TRACK_DESCRIPTION = (
    "Throws play at normal speed. Holes and drone previews are sped up; "
    "intros, sponsors and outros are skipped."
)


def format_timestamp(seconds):
    """Whole-second m:ss (or h:mm:ss past an hour). Mirrors parser.js."""
    total = max(0, round(seconds))
    s = total % 60
    m = (total // 60) % 60
    h = total // 3600
    head = f"{h}:{m:02d}" if h > 0 else f"{m}"
    return f"{head}:{s:02d}"


def slugify_title(title):
    """Lowercase, non-alphanumerics to '-', trimmed. Mirrors parser.js."""
    s = (title or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


def speed_for_kind(kind, round_bucket, nine, cfg):
    """Map a section kind to a speed code. This is where speed enters the pipeline;
    sections themselves don't carry one.

    Only the opener's intro (round 1, front 9) is worth a fast watch — the course
    flyover and player intros — so every other intro is skipped (later videos just
    repeat it). The outro (the trailing founders/sponsor chapter) is always
    skipped: the win and the trophy aren't here, they're inside the last hole's
    chapter, which already plays. Unknown kinds play at the default speed."""
    if kind == "intro":
        return cfg.speed_default if (round_bucket == "first" and nine == "front") else cfg.speed_skip
    if kind == "outro":
        return cfg.speed_skip
    if kind == "preview":
        # Round 1 you haven't seen the hole, so the preview plays fast. Later rounds
        # repeat it, so it plays faster still.
        return cfg.preview_speed_round1 if round_bucket == "first" else cfg.preview_speed_other
    return {
        "hole": cfg.speed_default,
        "throw": cfg.speed_throw,
        "leaderboard": cfg.speed_leaderboard,
        "sponsor": cfg.speed_skip,
    }.get(kind, cfg.speed_default)


def sections_to_cues(sections, round_bucket, nine, cfg):
    """Turn sections into cues [{t, code}]. Each section's kind (with the round and
    nine) picks a speed, and neighbours that land on the same speed merge into one
    cue (a cue is emitted only where the speed changes). The first cue is forced to
    0:00."""
    cues = []
    prev = None
    for s in sorted(sections, key=lambda x: x.start):
        code = speed_for_kind(s.kind, round_bucket, nine, cfg)
        if code != prev:
            cues.append({"t": int(round(s.start)), "code": code})
            prev = code
    if cues:
        cues[0]["t"] = 0
    return cues


def build_track(video_id, title, cues, description=""):
    """Assemble the track dict from cues [{t, code}]."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "youtubeVideoId": video_id,
        "title": title,
        "description": description,
        "cues": [
            {"timestamp": format_timestamp(c["t"]), "speed": str(c["code"])}
            for c in cues
        ],
    }


def track_filename(video_id, title):
    return f"{video_id}_{slugify_title(title)}.json"


def write_track(track, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, track_filename(track["youtubeVideoId"], track["title"]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(track, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


# Tiny node program: load the extension's parser, validate the file, report errors.
_VALIDATE_JS = (
    "const p=require(process.argv[1]);"
    "const fs=require('fs');"
    "const t=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
    "const r=p.validateTrack(t);"
    "if(r.errors&&r.errors.length){console.error(r.errors.map(e=>e.message).join('\\n'));process.exit(1);}"
    "console.log('ok');"
)


def validate_with_extension(track_path, parser_path):
    """Run the extension's validateTrack on the file. Returns (ok, message).

    If node or parser.js isn't reachable, returns (None, reason) so the caller can
    warn without treating it as a failure of the track itself.
    """
    if not parser_path or not os.path.exists(parser_path):
        return None, f"parser not found at {parser_path!r}; skipped validation"
    try:
        proc = subprocess.run(
            ["node", "-e", _VALIDATE_JS, os.path.abspath(parser_path), os.path.abspath(track_path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None, "node not available; skipped validation"
    if proc.returncode == 0:
        return True, "valid"
    return False, (proc.stderr or proc.stdout).strip()
