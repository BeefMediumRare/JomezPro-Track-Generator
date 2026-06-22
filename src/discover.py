"""Find which JomezPro videos still need a track.

The server scans the channel's newest uploads, keeps the per-hole tournament
coverage (a title regex), drops anything already turned into a track, and bounds
the rest by upload age. What's left is the work for this round.

The order is deliberate: the channel listing is one cheap flat call, the regex
and the already-tracked check are local, and only the few survivors get a
metadata fetch for their upload time — so the back catalogue is never downloaded.
"""

import glob
import os
import re
import time

import yt_dlp


def coverage_re(cfg):
    return re.compile(cfg.coverage_regex, re.I)


def is_coverage(title, cfg):
    return bool(coverage_re(cfg).match(title or ""))


def list_channel_videos(cfg):
    """The newest uploads as [{id, title}], newest first. Flat extraction: one
    request, no per-video calls, no downloads."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": cfg.max_scan_entries,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(cfg.channel_url, download=False)
    out = []
    for e in info.get("entries") or []:
        vid = e.get("id")
        if vid:
            out.append({"id": vid, "title": (e.get("title") or "").strip()})
    return out


def has_track(output_dir, video_id):
    """True if a track for this video already exists. The filename is
    "<id>_<slug>.json" and the id itself can contain "_" (e.g. "BVZ7_oWHDNM"),
    so this matches on the id prefix rather than splitting the name on "_".

    Matching on "<id>_" is unambiguous because YouTube ids are a fixed 11 chars:
    one real id can never be a prefix of another at an underscore boundary."""
    pattern = os.path.join(output_dir, f"{glob.escape(video_id)}_*.json")
    return bool(glob.glob(pattern))


def upload_timestamp(video_id, cfg):
    """Unix upload/release time for a video, or None if it can't be read. A
    metadata-only fetch — no video bytes."""
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_id, download=False)
    except yt_dlp.utils.DownloadError:
        return None
    ts = info.get("timestamp") or info.get("release_timestamp")
    if ts:
        return float(ts)
    # Fall back to the date-only field (YYYYMMDD) if the epoch one is missing.
    date = info.get("upload_date") or info.get("release_date")
    if date and len(date) == 8:
        try:
            return time.mktime(time.strptime(date, "%Y%m%d"))
        except ValueError:
            return None
    return None


def find_new(cfg, now=None, log=print):
    """The videos to process this round: coverage, not already tracked, fresh
    enough. Returns [{id, title}]. Logs each step so a dry run is legible."""
    now = time.time() if now is None else now
    cutoff = now - cfg.max_age_days * 86400

    videos = list_channel_videos(cfg)
    log(f"  scanned {len(videos)} newest uploads")

    coverage = [v for v in videos if is_coverage(v["title"], cfg)]
    log(f"  {len(coverage)} match the coverage pattern")

    untracked = [v for v in coverage if not has_track(cfg.output_dir, v["id"])]
    log(f"  {len(untracked)} not yet turned into a track")

    fresh = []
    for v in untracked:
        ts = upload_timestamp(v["id"], cfg)
        if ts is None:
            log(f"  skip {v['id']}: couldn't read an upload time")
            continue
        if ts < cutoff:
            log(f"  skip {v['id']}: older than {cfg.max_age_days} day(s)")
            continue
        fresh.append(v)
    log(f"  {len(fresh)} new and within {cfg.max_age_days} day(s)")
    return fresh
