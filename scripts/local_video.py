#!/usr/bin/env python3
"""Make a local illustrated video: system speech, timed captions and FFmpeg motion.

This command never imports a provider client or submits a video generation task.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import media
import narration
import pipeline


def _run(args):
    result = subprocess.run(args, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-2000:])


def render_local(run):
    with pipeline.locked_run(run) as (root, story, state):
        pipeline.verify_images(root, story, state)
        old = state["outputs"].get("local_video")
        if old and pipeline.verify_output(root, old):
            return {"reused": True, **old}
        # Validate all local options and speech before generating any audio.
        for shot in story["shots"]:
            narration.speech_for_shot(shot)
            for field in ("local_voices", "speaker_labels"):
                value = shot.get(field, {})
                if (not isinstance(value, dict)
                        or any(key not in narration.VOICES or not isinstance(text, str)
                               for key, text in value.items())):
                    raise ValueError(f"{shot['id']}.{field} must map narrator/woman/man to text")
        folder = root / "local-video"
        folder.mkdir(exist_ok=True)
        names = {"video_path": "local_video.mp4", "srt_path": "local_video.srt", "cover_path": "cover.jpg"}
        for name in (*names.values(), "verification.json"):
            path = folder / name
            if path.exists():
                pipeline.preserve_unregistered(root, path)
        voices = {}
        for shot in story["shots"]:
            result = narration.synthesize(shot, root / "local-voiceover" / f"{shot['id']}.wav",
                                          voices=shot.get("local_voices"))
            voices[shot["id"]] = result
            state.setdefault("local_voiceovers", {})[shot["id"]] = result
            pipeline.save(root, state)
        with tempfile.TemporaryDirectory(prefix=".local-video-", dir=root) as temporary:
            scratch = Path(temporary)
            parts, subtitles, elapsed = [], [], 0.0
            for shot in story["shots"]:
                sid, duration = shot["id"], shot["duration"]
                audio = voices[sid]
                args = ["ffmpeg", "-nostdin", "-v", "error", "-n", "-loop", "1", "-framerate", "30",
                        "-i", str(pipeline.inside(root, state["images"][sid]["path"]))]
                caption_info = []
                for index, cue in enumerate(audio["cues"]):
                    label = shot.get("speaker_labels", {}).get(cue["speaker"], "")
                    text = (label + "：" if label else "") + cue["text"]
                    caption = scratch / f"{sid}-caption-{index}.png"
                    media._caption(text, caption, False)
                    args += ["-loop", "1", "-framerate", "30", "-i", str(caption)]
                    begin = 0 if index == 0 else cue["start"]
                    end = audio["cues"][index + 1]["start"] if index + 1 < len(audio["cues"]) else duration
                    caption_info.append((index + 1, begin, end))
                    subtitles.append(f"{len(subtitles) + 1}\n{media._srt_time(elapsed + begin)} --> "
                                     f"{media._srt_time(elapsed + end)}\n{text}\n")
                args += ["-i", audio["path"]]
                # Push in 4.5% over this shot; captions remain stationary.
                frames = duration * media.FPS - 1
                filters = ["[0:v]scale=1440:2560,"
                           f"zoompan=z='1+0.045*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
                           "d=1:s=720x1280:fps=30,setsar=1[base]"]
                previous = "base"
                for index, begin, end in caption_info:
                    current = f"layer{index}"
                    filters.append(f"[{previous}][{index}:v]overlay=0:0:enable='gte(t,{begin})*lt(t,{end})'[{current}]")
                    previous = current
                filters.append(f"[{previous}]format=yuv420p[v]")
                segment = scratch / f"{sid}.mp4"
                args += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", f"{len(caption_info) + 1}:a:0",
                         "-t", str(duration), "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "19",
                         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(segment)]
                _run(args)
                parts.append(segment)
                elapsed += duration
            listing = scratch / "segments.txt"
            listing.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
            movie = scratch / names["video_path"]
            _run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "concat", "-safe", "1", "-i", str(listing),
                  "-map", "0:v", "-map", "0:a", "-c", "copy", "-movflags", "+faststart", "-metadata",
                  "comment=daily-jokes local_illustrated_video; system speech; FFmpeg camera motion; no video API", str(movie)])
            (scratch / names["srt_path"]).write_text("\n".join(subtitles), encoding="utf-8")
            _run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(movie), "-frames:v", "1", "-q:v", "2",
                  str(scratch / names["cover_path"])])
            _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(movie), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
            measured, sound = media.probe(movie), narration.inspect_audio(movie)
            if ((measured["width"], measured["height"]) != (720, 1280)
                    or abs(measured["duration"] - elapsed) >= 0.12
                    or sound["peak"] <= 0.005 or sound["rms"] <= 0.0001):
                raise RuntimeError("Local video failed duration, dimensions or audible-audio validation")
            files = {}
            for key, name in names.items():
                target = folder / name
                # This run is locked; promotion never overwrites an existing file.
                import os
                os.link(scratch / name, target)
                files[key] = {"path": str(target.relative_to(root)), "sha256": pipeline.digest(target)}
            measured["path"] = str(folder / names["video_path"])
        evidence = {"kind": "local_illustrated_video", "files": files, "media": measured, "audio": sound,
                    "video_api_submissions": 0, "speech_engine": "macos_say", "verified_at": pipeline.now(),
                    "motion": "gentle_camera_push_in_not_character_animation",
                    "semantic_review": "requires_actual_viewing_and_listening"}
        pipeline.write_json(folder / "verification.json", evidence)
        state["outputs"]["local_video"] = evidence
        pipeline.save(root, state)
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(render_local(args.run), ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"Local video: {exc}\n")


if __name__ == "__main__":
    main()
