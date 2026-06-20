"""Pull frames out of the video with ffmpeg.

Frames are scaled to a fixed height (so the graphics, and the templates we match
against them, stay a stable size whatever the source resolution) and cropped to
the bottom band, where both the hole-preview banner and the player card live. Each
graphic is then matched only inside its own search box (see detect.py), so the
band just needs to contain both. Frames are written as zero-padded PNGs; with
fps=1 the Nth frame (0-indexed) is second N of the video.
"""

import glob
import os
import subprocess


def _band_filter(cfg, fps_expr):
    # Scale to a fixed height, then keep the bottom `analyze_bottom_frac`.
    frac = cfg.analyze_bottom_frac
    return (f"{fps_expr},scale=-2:{cfg.scale_height},"
            f"crop=iw:ih*{frac}:0:ih*(1-{frac})")


def _extract(video_path, out_dir, vf):
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.png")):
        os.remove(old)
    pattern = os.path.join(out_dir, "%06d.png")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vf", vf,
        pattern,
    ]
    subprocess.run(cmd, check=True)
    return sorted(glob.glob(os.path.join(out_dir, "*.png")))


def extract_band(video_path, out_dir, cfg):
    """One bottom-band frame per second. Returns [(second, path), ...]."""
    files = _extract(video_path, out_dir, _band_filter(cfg, f"fps={cfg.sample_fps}"))
    return [(i, p) for i, p in enumerate(files)]


def extract_for_calibration(video_path, out_dir, cfg):
    """Sparser bottom-band frames for cropping templates. Returns [(second, path)]."""
    every = max(0.01, cfg.calibrate_every_sec)
    files = _extract(video_path, out_dir, _band_filter(cfg, f"fps=1/{every}"))
    return [(round(i * every), p) for i, p in enumerate(files)]
