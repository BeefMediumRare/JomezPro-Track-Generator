# JomezPro Track Generator

> **Note:** This whole project is vibe-coded. Every line was produced by prompting
> an AI assistant in conversation, not written by hand. Keep that in mind before
> relying on it.

This tool builds **tracks** for the Firefox extension
[Ain't Nobody Got Time for That](../Ain-t-Nobody-Got-Time-for-That). A track is a
list of timestamps with a speed at each one. The extension follows it to play
filler fast and the parts worth watching at normal speed. Normally you record a
track by hand while you watch. This tool makes one for you instead, for
**JomezPro disc golf videos** on YouTube.

It works one video at a time: give it a YouTube link, get one track file.

## How it decides what to speed up

The track is built in two steps: first the video is split into **sections**, then
the track is built from those. A section is just a span of the video with a kind
(what the region is) and a label. The speed comes in the second step, where each
kind is given a speed and neighbours that end up at the same speed are merged.

The sections come from the video's **YouTube chapters**, plus the drone preview at
the start of each hole, which is found by detecting an on-screen graphic:

- **HOLE** chapters play at the default fast speed (speed 2).
- Each hole's opening **drone preview** is sped up: speed 2 on round 1 (you
  haven't seen the hole yet), faster (speed 3) on later rounds.
- The closing **leaderboard** chapter plays at normal speed (speed 1).
- The **intro** and **outro** depend on where the video sits in the tournament
  (see below).

A tournament is several videos (round 1 front 9, round 1 back 9, and so on, up to
the final). The round and the nine (front or back) are read from the title's
token, like `R1F9` or `FINALB9`. The intro and outro are worth playing only once
across the whole tournament:

- The **intro** plays fast only on the opener (round 1, front 9): the course
  flyover and player intros. Every other video's intro is skipped.
- The **outro** plays fast only on the closer (final, back 9): the win and the
  trophy. Every other video's outro is skipped.

When it runs, it prints the detected round and nine, the sections it found, and
the track cues it produced, so you can see both steps. If the video has no HOLE
chapters, the whole thing plays at the default speed and nothing is skipped.

### Planned next

**Throw detection**: slowing each throw to normal speed while a player is
throwing, found by detecting the player card. The repository already ships the
reference image and the `calibrate` command for it (see below); it isn't wired
into the track yet.

## What you need

[Docker](https://www.docker.com/). Nothing else is installed on your machine;
yt-dlp, ffmpeg, and the rest live inside the container.

The output is checked against the extension's own validator. For that step the
tool reads the extension's `parser.js`. The `docker-compose.yml` expects the
extension repo to sit next to this one
(`../Ain-t-Nobody-Got-Time-for-That`). If yours is elsewhere, change that path in
`docker-compose.yml`. The check is optional: without it, the file is still
written, just not validated.

## Use it

### 1. Build the image

    docker compose build

### 2. Generate the track

    docker compose run --rm trackgen "https://www.youtube.com/watch?v=VIDEO_ID"

It prints the sections and writes the track to `tracks/JomezPro/` as
`<videoId>_<title>.json`. Point the extension at that folder (or commit it to a
public GitHub repo and add that repo in the extension's settings).

By default the run deletes the downloaded video and its frames afterwards, so it
leaves nothing behind. While iterating locally, keep them (so a re-run skips the
download and re-extraction):

    docker compose run --rm trackgen --keep-cache "https://www.youtube.com/watch?v=VIDEO_ID"

You can also set `KEEP_CACHE=1` in the environment instead of passing the flag.

## Settings

The settings are in `src/config.py`. The ones you are most likely to change are
the speeds (`speed_default` for the holes, `speed_skip`, `speed_leaderboard`, and
`preview_speed_round1` / `preview_speed_other` for the drone previews) and
`hole_preview_threshold`, which controls how closely a frame must match the banner
template to count as a preview.

## Calibration (remaking the preview template)

Preview detection matches a reference image of the hole-preview banner, and the
repository ships a working one (`assets/hole-preview.png`). JomezPro has changed
the graphics over the years, so if previews stop being detected, remake it from a
video in the style you want:

    docker compose run --rm trackgen calibrate "https://www.youtube.com/watch?v=VIDEO_ID"

This writes frames to `calibration/VIDEO_ID/`, already cropped to the lower part
of the screen. Crop the part of the banner that looks the same every time (the
JOMEZ PRO logo box, not the player name, score, or distance) into
`assets/hole-preview.png`. The repository also ships `assets/player-card.png` for
the planned throw step.

## Output format

A track is a JSON file the extension reads:

    {
      "schemaVersion": 1,
      "youtubeVideoId": "dQw4w9WgXcQ",
      "title": "Front 9",
      "description": "",
      "cues": [
        { "timestamp": "0:00", "speed": "4" },
        { "timestamp": "2:14", "speed": "2" },
        { "timestamp": "38:53", "speed": "1" },
        { "timestamp": "39:38", "speed": "4" }
      ]
    }

Each cue sets the speed from its timestamp until the next one. Speed is a code,
not a rate: `1` normal, `2` fast, `3` faster, `4` skip. The extension maps those
codes to actual speeds in its own settings.

## Licensing

This project is MIT. The Python dependencies are permissive (yt-dlp is
public-domain, OpenCV is Apache-2.0, NumPy is BSD). ffmpeg is used as an external
tool inside the container, not bundled into or linked with this code.
