"""Assemble generated clips, or create an explicitly labelled storyboard preview.

Requires ffmpeg/ffprobe on PATH and Pillow (``python -m pip install Pillow``).
The input images are read only. Caption overlays are generated independently.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from fractions import Fraction
from typing import Any


WIDTH, HEIGHT, FPS = 720, 1280, 30


class MediaError(RuntimeError):
    """Invalid media, missing dependency, or unsuccessful encoding."""


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise MediaError(f"Missing {args[0]}; install ffmpeg including ffprobe.") from exc
    if result.returncode:
        raise MediaError(f"{Path(args[0]).name} failed: {result.stderr.strip()[-3000:]}")
    return result.stdout


def _positive_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise MediaError(f"{label} must be a positive finite number.") from exc
    if isinstance(value, bool) or not math.isfinite(number) or number <= 0:
        raise MediaError(f"{label} must be a positive finite number.")
    return number


def probe(path: str | Path) -> dict:
    """Inspect a playable video; raise MediaError for absent/invalid video media.

    ``audio`` is whether this file has an audio stream, not a claim that the
    original AI clip supplied speech. Render evidence records that separately.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise MediaError(f"Video does not exist: {source}")
    try:
        data = json.loads(_run([
            "ffprobe", "-v", "error", "-show_format", "-show_streams",
            "-of", "json", str(source),
        ]))
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe returned invalid JSON for {source}") from exc
    video = next((stream for stream in data.get("streams", [])
                  if stream.get("codec_type") == "video"
                  and not stream.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise MediaError(f"No video stream: {source}")
    audio = next((stream for stream in data.get("streams", [])
                  if stream.get("codec_type") == "audio"), None)
    duration = _positive_number(
        video.get("duration") or data.get("format", {}).get("duration"),
        f"Video duration ({source.name})",
    )
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if width <= 0 or height <= 0:
        raise MediaError(f"Invalid video dimensions: {source}")
    try:
        fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "path": str(source), "duration": duration, "width": width,
        "height": height, "fps": fps, "codec": video.get("codec_name"),
        "video_codec": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"), "audio": audio is not None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "audio_channels": int(audio.get("channels", 0)) if audio else 0,
        "audio_sample_rate": int(audio.get("sample_rate", 0)) if audio else 0,
        "size_bytes": source.stat().st_size,
        "container": data.get("format", {}).get("format_name"),
    }


def _within(root: Path, value: str | Path, label: str) -> Path:
    candidate = Path(value)
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not target.is_relative_to(root) or target == root:
        raise MediaError(f"{label} must stay inside run_dir: {value}")
    return target


def _font_path() -> str:
    custom = os.environ.get("DAILY_JOKES_FONT")
    if custom:
        if not Path(custom).is_file():
            raise MediaError("DAILY_JOKES_FONT does not point to a font file.")
        return custom
    for candidate in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ):
        if Path(candidate).is_file():
            return candidate
    raise MediaError("No Chinese font found. Set DAILY_JOKES_FONT to a CJK .ttf/.ttc file.")


def _caption(text: str, path: Path, preview: bool) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise MediaError("Pillow is required; run: python -m pip install Pillow") from exc
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font_file = _font_path()
    lines: list[str] = []
    # Wrap by rendered glyph width, including Chinese without whitespace.
    for size in range(44, 31, -2):
        font = ImageFont.truetype(font_file, size)
        lines = []
        for paragraph in text.split("\n"):
            line = ""
            for character in paragraph:
                if line and draw.textlength(line + character, font=font) > WIDTH - 104:
                    lines.append(line)
                    line = character
                else:
                    line += character
            lines.append(line)
        if len(lines) <= 4:
            break
    if len(lines) > 4:
        raise MediaError("Subtitle is too long for one shot; split it into shorter shots.")
    line_height = size + 18
    box_height = line_height * len(lines) + 30
    top = HEIGHT - 170 - box_height
    draw.rounded_rectangle((32, top, WIDTH - 32, top + box_height),
                           radius=20, fill=(0, 0, 0, 190))
    for index, line in enumerate(lines):
        draw.text((WIDTH / 2, top + 15 + index * line_height), line, font=font,
                  anchor="mt", fill="white", stroke_width=1, stroke_fill="black")
    if preview:
        label_font = ImageFont.truetype(font_file, 27)
        draw.rounded_rectangle((24, 35, 425, 88), radius=12, fill=(0, 0, 0, 185))
        draw.text((42, 45), "分镜预演 · 非 AI 生成视频", font=label_font, fill="white")
    layer.save(path)


def _srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_int, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds_int:02},{millis:03}"


def render(shots: list[dict], run_dir: Path, output: Path, *, preview: bool = False) -> dict:
    """Render H.264/AAC 720x1280 video with burned-in Chinese subtitles.

    Each shot has ``id``, positive ``duration``, ``subtitle`` and a run-relative
    ``clip`` (real assembly) or ``image`` (preview). Real clips shorter than the
    requested duration by more than 0.12 seconds are rejected. Source audio is
    kept when present; silence is added only for missing audio or a short tail.
    Inputs and outputs must stay within run_dir; existing outputs are not replaced.
    A preview output filename must contain ``preview``. Returns paths and measured
    media evidence. This function never calls an AI video-generation service.
    """
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise MediaError(f"run_dir does not exist: {root}")
    target = _within(root, output, "output")
    if target.suffix.lower() != ".mp4":
        raise MediaError("output must be an .mp4 file.")
    if preview and "preview" not in target.stem.lower():
        raise MediaError("Storyboard preview output filename must contain 'preview'.")
    if not isinstance(shots, list) or not shots:
        raise MediaError("shots must be a nonempty list.")
    srt_path = target.with_suffix(".srt")
    cover_path = target.parent / "cover.jpg"
    for path in (target, srt_path, cover_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Will not replace an existing artifact: {path}")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise MediaError("ffmpeg and ffprobe must be installed and available on PATH.")

    normalized = []
    seen = set()
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise MediaError(f"Shot {index + 1} must be an object.")
        identifier = shot.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise MediaError("Every shot must have a nonempty, unique string id.")
        seen.add(identifier)
        duration = _positive_number(shot.get("duration"), f"{identifier}.duration")
        # Frame-accurate boundaries keep subtitles and each normalized clip aligned.
        frame_count = round(duration * FPS)
        if frame_count < 1:
            raise MediaError(f"{identifier}.duration must be at least one frame.")
        duration = frame_count / FPS
        subtitle = shot.get("subtitle")
        if not isinstance(subtitle, str) or not subtitle.strip():
            raise MediaError(f"{identifier}.subtitle must be a nonempty string.")
        key = "image" if preview else "clip"
        if not isinstance(shot.get(key), (str, Path)) or not str(shot[key]).strip():
            raise MediaError(f"{identifier}.{key} is required for this render mode.")
        source = _within(root, shot[key], f"{identifier}.{key}")
        if not source.is_file():
            raise MediaError(f"Missing {key} for {identifier}: {source}")
        evidence = None if preview else probe(source)
        if evidence and evidence["duration"] + 0.12 < duration:
            raise MediaError(f"{identifier} clip is shorter than its requested duration "
                             f"({evidence['duration']:.3f}s < {duration:.3f}s).")
        voiceover = None
        if shot.get("voiceover"):
            voiceover = _within(root, shot["voiceover"], f"{identifier}.voiceover")
            try:
                from .narration import inspect_audio
            except ImportError:
                from narration import inspect_audio
            voice_evidence = inspect_audio(voiceover)
            if (voice_evidence["duration"] > duration + 0.02
                    or voice_evidence["peak"] < 0.005 or voice_evidence["rms"] < 0.0001):
                raise MediaError("Voiceover must be audible and fit the shot without truncation.")
        normalized.append({"id": identifier, "duration": duration,
                           "subtitle": subtitle.strip(), "source": source,
                           "probe": evidence, "voiceover": voiceover})

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".daily-jokes-media-", dir=target.parent) as temp:
        scratch = Path(temp)
        segments = []
        subtitles = []
        elapsed = 0.0
        for index, shot in enumerate(normalized):
            caption = scratch / f"caption-{index:04}.png"
            _caption(shot["subtitle"], caption, preview)
            segment = scratch / f"segment-{index:04}.mp4"
            duration_text = f"{shot['duration']:.9f}"
            native_audio = bool(shot["probe"] and shot["probe"]["audio"])
            args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n"]
            if preview:
                args += ["-loop", "1", "-framerate", str(FPS)]
            args += ["-i", str(shot["source"]), "-loop", "1", "-framerate", str(FPS),
                     "-i", str(caption)]
            if shot["voiceover"]:
                args += ["-i", str(shot["voiceover"])]
            elif not native_audio:
                args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            audio_input = "0:a:0" if native_audio and not shot["voiceover"] else "2:a:0"
            video_filter = (
                f"[0:v:0]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"setsar=1,fps={FPS},tpad=stop_mode=clone:stop_duration=0.12,"
                f"trim=duration={duration_text},setpts=PTS-STARTPTS[base];"
                "[base][1:v:0]overlay=0:0:format=auto,format=yuv420p[v];"
                f"[{audio_input}]aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,apad,"
                f"atrim=duration={duration_text},asetpts=PTS-STARTPTS[a]"
            )
            args += ["-filter_complex", video_filter, "-map", "[v]", "-map", "[a]",
                     "-t", duration_text, "-r", str(FPS), "-c:v", "libx264", "-preset", "fast",
                     "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                     "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(segment)]
            _run(args)
            segments.append(segment)
            end = elapsed + shot["duration"]
            subtitles.append(f"{index + 1}\n{_srt_time(elapsed)} --> {_srt_time(end)}\n"
                             f"{shot['subtitle']}\n")
            elapsed = end
        # Only controlled ASCII basenames occur in the concat list; run paths can
        # contain spaces, Chinese characters, quotes, or shell metacharacters.
        concat = scratch / "segments.txt"
        concat.write_text("".join(f"file '{p.name}'\n" for p in segments), encoding="utf-8")
        movie = scratch / "render.mp4"
        mode = "storyboard_preview" if preview else "generated_video_assembly"
        _run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
              "-f", "concat", "-safe", "1", "-i", str(concat), "-map", "0:v:0",
              "-map", "0:a:0", "-c", "copy", "-movflags", "+faststart",
              "-metadata", f"comment=daily-jokes mode={mode}", str(movie)])
        measured = probe(movie)
        if (measured["width"], measured["height"]) != (WIDTH, HEIGHT):
            raise MediaError("Rendered video dimensions did not pass verification.")
        if (measured["video_codec"] != "h264" or measured["pixel_format"] != "yuv420p"
                or not measured["audio"] or measured["audio_codec"] != "aac"
                or abs(measured["fps"] - FPS) > 0.01):
            raise MediaError("Rendered video codec, pixel format, frame rate, or audio is invalid.")
        if abs(measured["duration"] - elapsed) > max(0.12, len(shots) / FPS):
            raise MediaError(f"Rendered duration mismatch: {measured['duration']:.3f}s vs {elapsed:.3f}s")
        # Decode the finished result so a metadata-only success cannot certify it.
        _run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror",
              "-i", str(movie), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
        cover = scratch / "cover.jpg"
        _run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
              "-i", str(movie), "-frames:v", "1", "-q:v", "2", str(cover)])
        srt = scratch / "subtitles.srt"
        srt.write_text("\n".join(subtitles), encoding="utf-8")
        # Hard-link promotion is atomic and refuses to overwrite a newly created
        # destination; scratch lives on the same filesystem as the outputs.
        promoted: list[Path] = []
        try:
            for source, destination in ((movie, target), (srt, srt_path), (cover, cover_path)):
                os.link(source, destination)
                promoted.append(destination)
        except OSError:
            for path in promoted:
                path.unlink()
            raise
        measured["path"] = str(target)
    return {
        "mode": mode, "preview": preview, "video_path": str(target),
        "srt_path": str(srt_path), "cover_path": str(cover_path),
        "expected_duration": round(elapsed, 6), "probe": measured,
        "shots": [{"id": shot["id"], "duration": shot["duration"],
                   "source_path": str(shot["source"]),
                   "voiceover_path": str(shot["voiceover"]) if shot["voiceover"] else None,
                   "source_audio": bool(shot["probe"] and shot["probe"]["audio"]),
                   "audio_action": "voiceover" if shot["voiceover"] else "preserved" if shot["probe"] and shot["probe"]["audio"]
                   else "silence_added"} for shot in normalized],
    }
