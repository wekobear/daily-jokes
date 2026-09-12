"""Local Mandarin scratch voiceovers for storyboard previews (macOS say)."""
from __future__ import annotations

import array
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


VOICES = {"narrator": "Tingting", "woman": "Flo (中文（中国大陆）)",
          "man": "Eddy (中文（中国大陆）)"}


class NarrationError(RuntimeError):
    pass


def _run(args):
    try:
        result = subprocess.run(args, capture_output=True, check=False, timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise NarrationError(f"{args[0]} 超过处理时限，未保存成功产物") from exc
    except FileNotFoundError as exc:
        raise NarrationError(f"缺少 {args[0]}，本地预演配音需要 macOS say 和 FFmpeg") from exc
    if result.returncode:
        raise NarrationError(f"{args[0]} 执行失败：{result.stderr.decode(errors='replace')[-1000:]}")
    return result.stdout


def inspect_audio(path):
    data = json.loads(_run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                           "-of", "json", str(path)]))
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not stream:
        raise NarrationError("配音文件缺少音轨")
    duration = float(stream.get("duration") or data.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise NarrationError("配音时长无效")
    raw = _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"])
    samples = array.array("h", raw)
    if not samples:
        raise NarrationError("配音无法解码")
    peak = max(abs(s) for s in samples) / 32768
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768
    return {"duration": duration, "peak": peak, "rms": rms,
            "sample_rate": int(stream.get("sample_rate", 0))}


def speech_for_shot(shot):
    explicit = shot.get("speech")
    if explicit is not None:
        if not isinstance(explicit, list) or not explicit:
            raise NarrationError("speech 必须是非空的说话片段列表")
        speech = []
        for cue in explicit:
            if (not isinstance(cue, dict) or cue.get("speaker") not in VOICES
                    or not isinstance(cue.get("text"), str) or not cue["text"].strip()):
                raise NarrationError("每段配音需要 narrator/woman/man 和非空 text")
            speech.append({"speaker": cue["speaker"], "text": cue["text"].strip()})
        return speech
    subtitle = shot.get("subtitle")
    if not isinstance(subtitle, str) or not subtitle.strip():
        raise NarrationError("缺少配音文案或字幕")
    speech = []
    labels = {"女士": "woman", "她": "woman", "女声": "woman", "女人": "woman",
              "男士": "man", "他": "man", "男声": "man", "男人": "man", "旁白": "narrator"}
    for line in subtitle.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(女士|她|女声|女人|男士|他|男声|男人|旁白)[:：]\s*(.*)$", line)
        speaker, text = (labels[match[1]], match[2]) if match else ("narrator", line)
        if not text.strip():
            raise NarrationError("角色标签后缺少台词")
        if speech and speech[-1]["speaker"] == speaker:
            speech[-1]["text"] += text
        else:
            speech.append({"speaker": speaker, "text": text})
    return speech


def _say(text, voice, rate, path):
    _run(["say", "-v", voice, "-r", str(rate), "-o", str(path), text])


def synthesize(shot, output: Path, *, voices=None, rate=205, synthesizer=None):
    """Synthesize all lines, fit them without truncation, pad to the shot duration.

    Repeated calls reuse verified artifacts only when text, voice and timing match.
    The stock system voices are draft narration, not a claim of acting-quality audio.
    """
    speech = speech_for_shot(shot)  # Validate every cue before starting any synthesis.
    duration = shot.get("duration")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration <= 0):
        raise NarrationError("镜头时长须为正数")
    if type(rate) is not int or not 100 <= rate <= 300:
        raise NarrationError("语速须在 100 至 300 之间")
    selected = {**VOICES, **(voices or {})}
    if any(not isinstance(selected[cue["speaker"]], str) or not selected[cue["speaker"]].strip() for cue in speech):
        raise NarrationError("音色不能为空")
    output = Path(output).resolve()
    if output.suffix.lower() != ".wav":
        raise NarrationError("配音输出必须使用 .wav")
    engine = "macos_say" if synthesizer is None else "injected_synthesizer"
    spec = {"version": 1, "duration": duration, "speech": speech,
            "voices": selected, "rate": rate, "engine": engine}
    spec_hash = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    metadata = output.with_suffix(".json")
    if output.exists() or metadata.exists():
        if output.is_file() and metadata.is_file():
            old = json.loads(metadata.read_text(encoding="utf-8"))
            if (old.get("spec_sha256") == spec_hash
                    and hashlib.sha256(output.read_bytes()).hexdigest() == old.get("sha256")):
                return {**old, "cached": True}
        raise NarrationError("已有不同或未核验的配音文件；请使用新的输出目录，保留原版本")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise NarrationError("本地配音需要 FFmpeg 和 ffprobe")
    if synthesizer is None and not shutil.which("say"):
        raise NarrationError("本地配音使用 macOS say；其他宿主可传入已生成的 WAV 配音")
    synth = synthesizer or _say
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".voiceover-", dir=output.parent) as temp:
        scratch = Path(temp)
        chunks = []
        for index, cue in enumerate(speech):
            path = scratch / f"line-{index}.aiff"
            voice = selected[cue["speaker"]]
            synth(cue["text"], voice, rate, path)
            inspected = inspect_audio(path)
            if inspected["peak"] < 0.005 or inspected["rms"] < 0.0001:
                raise NarrationError("语音合成返回静音，不能当作已有配音")
            chunks.append({**cue, "voice": voice, "path": path, "source_duration": inspected["duration"]})
        lead, tail, gap = 0.18, 0.25, 0.16
        available = duration - lead - tail - gap * (len(chunks) - 1)
        if available <= 0:
            raise NarrationError("镜头太短，无法容纳配音及停顿")
        speed = max(1.0, sum(c["source_duration"] for c in chunks) / available)
        if speed > 1.18:
            raise NarrationError("完整台词超出镜头时长；请缩短文案或延长镜头，不截断配音")
        args = ["ffmpeg", "-nostdin", "-v", "error", "-n"]
        filters, cues = [], []
        position = lead
        for index, chunk in enumerate(chunks):
            args += ["-i", str(chunk["path"])]
            tempo = f"atempo={speed:.9f}," if speed > 1.00001 else ""
            filters.append(f"[{index}:a:0]{tempo}aresample=48000,"
                           f"adelay={round(position * 1000)}:all=1[a{index}]")
            end = position + chunk["source_duration"] / speed
            cues.append({key: chunk[key] for key in ("speaker", "text", "voice", "source_duration")}
                        | {"start": round(position, 4), "end": round(end, 4)})
            position = end + gap
        mix = "".join(f"[a{i}]" for i in range(len(chunks)))
        # A finite silent base fixes the timeline independently of speech EOF.
        # Padding after amix can end early with short AIFF inputs in FFmpeg 8.
        filters.append(f"anullsrc=r=48000:cl=stereo:d={duration}[bed]")
        filters.append(f"[bed]{mix}amix=inputs={len(chunks) + 1}:duration=first:normalize=0,"
                       "alimiter=limit=0.95:level=0[out]")
        mixed = scratch / "voiceover.wav"
        args += ["-filter_complex", ";".join(filters), "-map", "[out]", "-t", str(duration), "-ar", "48000", "-ac", "2",
                 "-c:a", "pcm_s16le", str(mixed)]
        _run(args)
        inspected = inspect_audio(mixed)
        if abs(inspected["duration"] - duration) > 0.02 or inspected["rms"] < 0.0001:
            raise NarrationError("配音的时长或实际音量未通过检查")
        result = {"path": str(output), "sha256": hashlib.sha256(mixed.read_bytes()).hexdigest(),
                  "spec_sha256": spec_hash, "duration": duration, "cues": cues,
                  "speed": round(speed, 6), "engine": engine, "cached": False, "audio": inspected}
        staged_metadata = scratch / "voiceover.json"
        staged_metadata.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Atomic no-clobber promotion on the same filesystem.
        import os
        os.link(mixed, output)
        try:
            os.link(staged_metadata, metadata)
        except Exception:
            output.unlink()
            raise
    return result
