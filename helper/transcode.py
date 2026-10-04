"""Quality ladder + ffmpeg helpers for "auto-quality" (144p ... 4K).

Ported from the src bot's Akbots/filestore.py `generate_missing_qualities`, with these fixes:
  * the source is classified by its real picture size, so a cinema-crop 3840x1600 file counts as 4K
    (the src bot compared only the height) and a portrait 1080x1920 file counts as 1080p;
  * outputs are fitted into a 16:9 box (never upscaled, always even sizes), so wide/cropped and 4:3
    videos keep their aspect ratio;
  * 10-bit / HEVC / HDR sources are converted to 8-bit yuv420p H.264 (plays everywhere);
  * audio is re-encoded to AAC (the src bot used "-c:a copy", which fails for DTS/EAC3/Opus in MP4)
    and made smaller for the small resolutions - that is the "compress" part;
  * progress is parsed from ffmpeg so the Telegram status message can show a percentage.

The top half is pure (no I/O) and unit-tested; the bottom half runs ffmpeg / ffprobe.
"""
import asyncio
import json
import os
import re
from typing import Callable, Optional

from . import quality as q

# label -> picture height. Same labels as helper/quality.py so extract_quality() reads the new names back.
LADDER = {"144p": 144, "240p": 240, "360p": 360, "480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "4K": 2160}
ORDER = list(LADDER)                       # low -> high

CRF = {"144p": 28, "240p": 27, "360p": 26, "480p": 24, "720p": 23, "1080p": 22, "1440p": 22, "4K": 21}
AUDIO_KBPS = {"144p": 48, "240p": 64, "360p": 80, "480p": 96, "720p": 128, "1080p": 128, "1440p": 160, "4K": 160}

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".flv", ".wmv", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp"}
TELEGRAM_MAX_BYTES = 2000 * 1024 * 1024    # bots can send / download up to ~2 GB

_CODEC_WORDS = re.compile(r"(?<![0-9a-z])(?:x265|h[\s._-]?265|hevc)(?![0-9a-z])", re.IGNORECASE)


# ------------------------------------------------------------------ pure helpers

def parse_list(text: str, default=None) -> list:
    """'720p, 144p 4k' -> ['144p', '720p', '4K'] (known labels only, low -> high, no duplicates)."""
    found = set()
    for tok in re.split(r"[\s,;|]+", str(text or "")):
        tok = tok.strip()
        if not tok:
            continue
        for label in LADDER:
            if tok.lower() == label.lower() or (label == "4K" and tok.lower() == "2160p") \
                    or (label == "1440p" and tok.lower() == "2k"):
                found.add(label)
    out = [l for l in ORDER if l in found]
    return out or list(default or [])


def effective_height(width: int, height: int) -> int:
    """The "p" number a viewer would call this picture. Landscape files are rated by the larger of
    their height and width*9/16 (so a 3840x1600 film is 2160-class); portrait files by the mirror rule."""
    w, h = int(width or 0), int(height or 0)
    if w <= 0 or h <= 0:
        return h or 0
    if h > w:                                # portrait: the short side plays the role of the height
        return max(w, round(h * 9 / 16))
    return max(h, round(w * 9 / 16))


def source_label(width: int, height: int) -> Optional[str]:
    """Closest ladder label at or below the picture's real size (10 % tolerance), None if tiny."""
    eff = effective_height(width, height)
    best = None
    for label in ORDER:
        if eff >= LADDER[label] * 0.9:
            best = label
    return best


def pick_targets(width: int, height: int, wanted, have=()) -> list:
    """Labels worth encoding: wanted, not already present, and clearly smaller than the source
    (never upscale, never re-make the source's own size). Low -> high."""
    eff = effective_height(width, height)
    have = set(have or ())
    return [l for l in ORDER if l in set(wanted or ()) and l not in have and LADDER[l] <= eff * 0.9]


def pick_upscale_targets(width: int, height: int, upscale_to, have=(), max_factor: float = 4.0) -> list:
    """Labels to ENLARGE the video to: asked for, clearly bigger than the source (>10 %), not already
    present and not absurdly far away (default max 4x, so 144p never becomes 4K). Low -> high."""
    eff = effective_height(width, height)
    have = set(have or ())
    if eff <= 0:
        return []
    return [l for l in ORDER if l in set(upscale_to or ()) and l not in have
            and eff * 1.1 < LADDER[l] <= eff * max_factor]


def fit_box(label: str, portrait: bool = False) -> tuple:
    """(max_width, max_height) the output must fit in: a 16:9 box of that quality, turned for portrait."""
    h = LADDER[label]
    w = h * 16 // 9
    return (h, w) if portrait else (w, h)


def output_name(src_name: str, label: str, tag: str = "") -> str:
    """'Show.S01E01.1080p.WEB-DL.x265.mkv' -> 'Show.S01E01.480p.WEB-DL.x264.mp4'.
    The new quality replaces the old tag in place (or is appended when there was none), so
    helper.quality.extract_quality() / group_key() still group it with the original."""
    stem = os.path.splitext(os.path.basename(src_name or "video"))[0] or "video"
    old = q.extract_quality(stem)
    if old and old in q.QUALITIES:
        stem = re.sub(q.QUALITIES[old][0], label, stem, count=1, flags=re.IGNORECASE)
    else:
        sep = " " if " " in stem else "."
        stem = f"{stem}{sep}{label}"
    stem = _CODEC_WORDS.sub("x264", stem)
    stem = re.sub(r'[\\/:*?"<>|\r\n]+', " ", stem).strip(" .")
    if tag:
        stem = f"{stem}{' ' if ' ' in stem else '.'}{tag}"
    return f"{stem or 'video'}.mp4"


def build_ffmpeg_cmd(src: str, dst: str, label: str, portrait: bool = False,
                     preset: str = "veryfast", threads: int = 0, ffmpeg: str = "ffmpeg") -> list:
    mw, mh = fit_box(label, portrait)
    vf = (f"scale=w='min(iw,{mw})':h='min(ih,{mh})':force_original_aspect_ratio=decrease:force_divisible_by=2,"
          "setsar=1,format=yuv420p")
    kbps = AUDIO_KBPS[label]
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", src,
        "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-map_chapters", "-1", "-map_metadata", "-1",
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", str(CRF[label]),
        "-profile:v", "high" if LADDER[label] >= 480 else "main",
        "-c:a", "aac", "-b:a", f"{kbps}k", "-ac", "2",
        "-max_muxing_queue_size", "4096", "-movflags", "+faststart",
    ]
    if threads and int(threads) > 0:
        cmd += ["-threads", str(int(threads))]
    return cmd + ["-progress", "pipe:1", "-nostats", dst]


def build_upscale_cmd(src: str, dst: str, label: str, portrait: bool = False,
                      preset: str = "veryfast", threads: int = 0, ffmpeg: str = "ffmpeg") -> list:
    """Enlarge to `label`. Same filter chain as the src bot's /mastervideo (Lanczos scale -> hqdn3d denoise
    -> CAS sharpen -> unsharp), minus its colour boost and the 10-bit HEVC / slow preset (those files do not
    play inline in Telegram and take hours). Output is 8-bit H.264, aspect ratio kept (no black bars)."""
    mw, mh = fit_box(label, portrait)
    vf = (f"scale=w={mw}:h={mh}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos+accurate_rnd,"
          "hqdn3d=1.5:1.5:6:6,cas=0.6,unsharp=3:3:0.8:3:3:0,setsar=1,format=yuv420p")
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", src,
        "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-map_chapters", "-1", "-map_metadata", "-1",
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", "18", "-profile:v", "high",
        "-c:a", "aac", "-b:a", f"{AUDIO_KBPS[label]}k", "-ac", "2",
        "-max_muxing_queue_size", "4096", "-movflags", "+faststart",
    ]
    if threads and int(threads) > 0:
        cmd += ["-threads", str(int(threads))]
    return cmd + ["-progress", "pipe:1", "-nostats", dst]


def split_segment_seconds(size: int, duration: float, part_bytes: int, margin: float = 0.92) -> int:
    """Seconds per part so that parts land around `margin` * part_bytes (video bitrate is uneven, so < 1)."""
    if size <= 0 or duration <= 0 or part_bytes <= 0:
        return 0
    return max(int(duration * part_bytes * margin / size), 5)


def part_name(name: str, index: int, video: bool = True) -> str:
    """Video: 'Movie.4K.mkv' -> 'Movie.4K.part02.mkv' (playable). Other files: 'a.zip' -> 'a.zip.002' (raw bytes)."""
    if not video:
        return f"{name}.{index:03d}"
    stem, ext = os.path.splitext(name)
    return f"{stem}.part{index:02d}{ext}"


def progress_seconds(line: str) -> Optional[float]:
    """Seconds encoded so far from one `-progress` line ('out_time_us=1234567'), else None."""
    m = re.match(r"\s*out_time_(?:us|ms)=(-?\d+)", line or "")
    if not m:
        return None
    v = int(m.group(1))
    return max(v, 0) / 1_000_000


def human_size(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def looks_like_video(name: str = "", mime: str = "") -> bool:
    return (os.path.splitext(name or "")[1].lower() in VIDEO_EXTS) or str(mime or "").lower().startswith("video/")


# ------------------------------------------------------------------ ffmpeg / ffprobe

async def probe(path: str, ffprobe: str = "ffprobe") -> dict:
    """{'duration': float, 'width': int, 'height': int} as the picture is *displayed* (rotation applied)."""
    proc = await asyncio.create_subprocess_exec(
        ffprobe, "-v", "error", "-select_streams", "v:0", "-print_format", "json",
        "-show_entries", "stream=width,height:stream_tags=rotate:stream_side_data=rotation:format=duration",
        path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    try:
        data = json.loads(out.decode() or "{}")
        st = (data.get("streams") or [{}])[0]
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
        rot = st.get("tags", {}).get("rotate")
        for sd in st.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = sd["rotation"]
        if rot is not None and int(float(rot)) % 180 != 0:
            w, h = h, w
        return {"duration": float((data.get("format") or {}).get("duration") or 0), "width": w, "height": h}
    except Exception:
        return {"duration": 0.0, "width": 0, "height": 0}


async def run_ffmpeg(cmd: list, duration: float = 0.0, on_progress: Optional[Callable] = None) -> tuple:
    """Run ffmpeg. -> (returncode, last stderr lines). `on_progress(fraction 0..1)` is awaited as it runs."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    tail = []

    async def _drain_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            tail.append(line.decode(errors="replace").rstrip())
            del tail[:-12]

    err_task = asyncio.create_task(_drain_stderr())
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            sec = progress_seconds(line.decode(errors="replace"))
            if sec is not None and duration > 0 and on_progress:
                await on_progress(min(sec / duration, 1.0))
        await proc.wait()
        await err_task
    except BaseException:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        err_task.cancel()
        raise
    return proc.returncode, "\n".join(tail[-6:])


async def make_thumbnail(src: str, dst: str, at: float = 1.0, ffmpeg: str = "ffmpeg") -> bool:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{max(at, 0):.2f}", "-i", src,
        "-frames:v", "1", "-vf", "scale='min(320,iw)':-2", dst,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.wait()
    return proc.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0


# ------------------------------------------------------------------ splitting

_MP4_LIKE = {".mp4", ".m4v", ".mov", ".3gp"}


async def split_video(src: str, out_dir: str, duration: float, part_bytes: int,
                      hard_limit: int = TELEGRAM_MAX_BYTES, ffmpeg: str = "ffmpeg") -> list:
    """Cut `src` into playable parts with stream copy (fast, lossless). Parts end on keyframes so sizes
    vary: every part is checked against `hard_limit` and the cut is redone with shorter parts if one is
    too big. -> sorted part paths. Raises RuntimeError if it cannot be done."""
    size = os.path.getsize(src)
    ext = os.path.splitext(src)[1].lower() or ".mkv"
    if duration <= 0:
        raise RuntimeError("unknown duration")
    os.makedirs(out_dir, exist_ok=True)
    maps = ["-map", "0:v", "-map", "0:a?"] if ext in _MP4_LIKE else ["-map", "0"]
    for margin in (0.92, 0.8, 0.65, 0.5):
        for f in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, f))
        seg = split_segment_seconds(size, duration, part_bytes, margin)
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", src, *maps,
            "-c", "copy", "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1",
            os.path.join(out_dir, f"part%03d{ext}"),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        parts = sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir))
        if proc.returncode != 0 or not parts:
            raise RuntimeError("ffmpeg split failed: " + (err or b"").decode(errors="replace")[-200:])
        if all(0 < os.path.getsize(p) <= hard_limit for p in parts):
            return parts
    raise RuntimeError("could not make parts small enough (very long keyframe gaps)")


def split_raw(src: str, out_dir: str, part_bytes: int, name: str) -> list:
    """Byte-split any file into name.001, name.002 ... (blocking, run it with asyncio.to_thread)."""
    os.makedirs(out_dir, exist_ok=True)
    parts, index, block = [], 0, 8 * 1024 * 1024
    with open(src, "rb") as f:
        while True:
            chunk = f.read(min(block, part_bytes))
            if not chunk:
                break
            index += 1
            path = os.path.join(out_dir, part_name(name, index, video=False))
            written = 0
            with open(path, "wb") as out:
                while chunk:
                    out.write(chunk)
                    written += len(chunk)
                    if written >= part_bytes:
                        break
                    chunk = f.read(min(block, part_bytes - written))
            parts.append(path)
    return parts
