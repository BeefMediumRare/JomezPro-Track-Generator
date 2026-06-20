"""Fetch what we need from YouTube with yt-dlp: the metadata (id, title,
duration, chapters) and a low-resolution copy of the video.

Low resolution is deliberate. Overlay matching doesn't need a sharp picture, and a
360p file downloads in a fraction of the time. The file is cached by video id so a
re-run skips the download.
"""

import os

import yt_dlp


def fetch(url_or_id, cfg):
    """Download (if needed) and return metadata plus the local video path.

    Returns a dict: {video_id, title, duration, chapters, video_path}.
    """
    os.makedirs(cfg.cache_dir, exist_ok=True)
    outtmpl = os.path.join(cfg.cache_dir, "%(id)s.%(ext)s")

    ydl_opts = {
        "format": cfg.download_format,
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # Keep the muxed file as-is; we only read frames from it.
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url_or_id, download=True)
        video_path = ydl.prepare_filename(info)

    # yt-dlp may have remuxed to a different extension; find the real file.
    if not os.path.exists(video_path):
        base = os.path.join(cfg.cache_dir, info["id"])
        for ext in ("mp4", "mkv", "webm"):
            cand = f"{base}.{ext}"
            if os.path.exists(cand):
                video_path = cand
                break

    chapters = info.get("chapters") or []
    return {
        "video_id": info["id"],
        "title": (info.get("title") or "").strip() or info["id"],
        "duration": float(info.get("duration") or 0),
        "chapters": chapters,
        "video_path": video_path,
    }
