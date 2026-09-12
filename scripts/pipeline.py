#!/usr/bin/env python3
"""Local, resumable video production after Codex has sourced and storyboarded a joke.

This runner never searches instead of Codex, fabricates model output, or uploads to
WeChat. It prepares a verified handoff package; the uploader is not implemented.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid
from urllib.parse import urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RATES = {("MiniMax-H3", "768P"): "0.50", ("MiniMax-H3", "2K"): "0.80",
         ("MiniMax-H3-Max", "480P"): "0.33", ("MiniMax-H3-Max", "768P"): "0.50"}
PRICE_SOURCE = "https://platform.minimax.cn/docs/guides/pricing-paygo"
PRICE_CHECKED = "2026-09-12"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    """Atomic replacement of this run's own state, not arbitrary user files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".state-", delete=False) as handle:
        temp = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def inside(run, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("运行产物必须使用运行目录内的相对路径")
    path = (run / relative).resolve()
    if not path.is_relative_to(run.resolve()) or path == run.resolve():
        raise ValueError("产物路径超出运行目录")
    return path


def preserve_unregistered(run, path):
    """Keep interrupted/unverified outputs recoverable; never adopt them as evidence."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("无法处理非普通文件的未登记产物")
    folder = inside(run, "quarantine")
    folder.mkdir(exist_ok=True)
    dest = folder / f"{uuid.uuid4().hex[:12]}-{path.name}"
    path.rename(dest)
    return str(dest.relative_to(run))


def official_base_url():
    base = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.cn").rstrip("/")
    if base != "https://api.minimax.cn":
        raise ValueError("此命令预算按国内官方人民币计价；其他区域或代理需另行核实价格后适配")
    return base


def validate_story(story):
    if story.get("version") != 1:
        raise ValueError("story.version 必须为 1")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", story.get("id", "")):
        raise ValueError("story.id 只能包含小写字母、数字、连字符和下划线")
    for name in ("title", "description", "script", "style"):
        if not isinstance(story.get(name), str) or not story[name].strip():
            raise ValueError(f"缺少 story.{name}")
    source = story.get("source", {})
    if (urlparse(source.get("url", "")).scheme not in ("https", "http")
            or not all(source.get(key) for key in ("title", "retrieved_at", "basis"))):
        raise ValueError("缺少真实读取过的网络来源、日期和改编依据")
    video = story.get("video", {})
    model, resolution = video.get("model"), video.get("resolution")
    if (model, resolution) not in RATES:
        raise ValueError("不支持的模型/分辨率；请依据官方 V2 API 更新适配器")
    shots = story.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 6:
        raise ValueError("每条视频需要 1 至 6 个镜头")
    identifiers = set()
    for shot in shots:
        sid = shot.get("id", "")
        if not re.fullmatch(r"s[1-9][0-9]?", sid) or sid in identifiers:
            raise ValueError("镜头 id 须为唯一的 s1、s2 等")
        identifiers.add(sid)
        duration = shot.get("duration")
        minimum = 4 if model == "MiniMax-H3" else 5
        if type(duration) is not int or not minimum <= duration <= 15:
            raise ValueError(f"{sid} 的时长须为 {minimum} 至 15 秒整数")
        for field in ("subtitle", "image_prompt", "motion_prompt"):
            if not isinstance(shot.get(field), str) or not shot[field].strip():
                raise ValueError(f"{sid} 缺少 {field}")
        if len(shot["motion_prompt"]) > 7000:
            raise ValueError(f"{sid} 视频提示词超过 7000 字符")
    return story


@contextmanager
def locked_run(run):
    run = Path(run).resolve()
    if not (run / "state.json").is_file():
        raise ValueError("请先 init 创建运行")
    with (run / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("这次运行已有进程在处理，请等待它结束") from exc
        try:
            state = read_json(run / "state.json")
            if digest(run / "story.json") != state["story_sha256"]:
                raise ValueError("运行中的分镜已被修改；请用新目录 init，避免与已计费任务混用")
            story = validate_story(read_json(run / "story.json"))
            yield run, story, state
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save(run, state):
    state["updated_at"] = now()
    write_json(run / "state.json", state)


def init_run(story_path, run):
    story = validate_story(read_json(story_path))
    run = Path(run).resolve()
    run.mkdir(parents=True, exist_ok=False)
    try:
        write_json(run / "story.json", story)
        state = {"version": 1, "id": story["id"], "created_at": now(),
                 "story_sha256": digest(run / "story.json"), "images": {}, "tasks": {},
                 "outputs": {}, "upload": {"status": "not_started", "adapter": "not_implemented"}}
        save(run, state)
    except Exception:
        # Keep the failed run for inspection instead of recursively deleting it.
        raise
    return {"run": str(run), "next": "Codex 逐镜生成并查看图片，再用 image 命令导入"}


def import_image(run, shot_id, source):
    from PIL import Image
    with locked_run(run) as (run, story, state):
        if shot_id not in {shot["id"] for shot in story["shots"]}:
            raise ValueError("未知镜头")
        source = Path(source).resolve()
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            width, height = image.size
            suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
        if suffix is None or not 256 <= min(width, height) or max(width, height) > 5760:
            raise ValueError("图片须为 PNG/JPEG/WEBP，宽高在 256 至 5760 像素之间")
        if abs(width / height - 9 / 16) > 0.015:
            raise ValueError("图生视频使用源图画幅，请在 Codex 生成实际 9:16 竖图")
        if source.stat().st_size > 30 * 1024 * 1024:
            raise ValueError("首帧图片超过 MiniMax 的 30 MB 限制")
        fingerprint = digest(source)
        existing = state["images"].get(shot_id)
        if existing:
            if existing["sha256"] == fingerprint and digest(inside(run, existing["path"])) == fingerprint:
                return {"image": existing, "reused": True}
            raise ValueError("该镜头已有不同图片；更换分镜请创建新运行")
        if state["tasks"]:
            raise ValueError("视频已提交，不能更换首帧")
        relative = f"images/{shot_id}{suffix}"
        dest = inside(run, relative)
        dest.parent.mkdir(exist_ok=True)
        if dest.exists():
            raise ValueError("目标图片已存在但未登记，请检查上次导入")
        shutil.copy2(source, dest)
        evidence = {"path": relative, "sha256": fingerprint, "width": width,
                    "height": height, "imported_at": now(), "visual_review": "not_machine_verified"}
        state["images"][shot_id] = evidence
        save(run, state)
        return {"image": evidence}


def quote(story):
    video = story["video"]
    rate = Decimal(RATES[video["model"], video["resolution"]])
    costs = {shot["id"]: str(rate * shot["duration"]) for shot in story["shots"]}
    return {"currency": "CNY", "estimated_total": str(sum(map(Decimal, costs.values()))),
            "per_shot": costs, "price_checked": PRICE_CHECKED, "price_source": PRICE_SOURCE,
            "scope": "国内官方按量价，每镜一张首帧；仅估算，不是实际账单"}


def verify_images(run, story, state):
    for shot in story["shots"]:
        image = state["images"].get(shot["id"])
        if not image:
            raise ValueError(f"尚未生成/导入 {shot['id']} 图片")
        if digest(inside(run, image["path"])) != image["sha256"]:
            raise ValueError(f"{shot['id']} 图片已改变，请创建新运行")


def verify_output(run, evidence):
    if not evidence:
        return False
    for item in evidence["files"].values():
        if digest(inside(run, item["path"])) != item["sha256"]:
            raise ValueError("产物已改变，不能复用旧验收")
    return True


def generate(run, env_file, budget, *, client=None):
    from minimax_video import MiniMaxClient, MiniMaxError, build_i2v_payload, load_env
    from media import probe
    if env_file:
        load_env(env_file, override=True)
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("budget-cny 必须是用户已允许的正数预算")
    with locked_run(run) as (run, story, state):
        verify_images(run, story, state)
        estimate = quote(story)
        if Decimal(estimate["estimated_total"]) > Decimal(str(budget)):
            raise ValueError(f"预计 ¥{estimate['estimated_total']}，超过本次预算 ¥{budget}")
        base = official_base_url()
        if client is None:
            client = MiniMaxClient(base_url=base, timeout=45)
        for shot in story["shots"]:
            sid = shot["id"]
            task = state["tasks"].get(sid)
            if task and task.get("base_url", base) != base:
                raise ValueError("已有任务属于不同服务域，不能混用")
            if task and task["status"] == "downloaded":
                if digest(inside(run, task["clip"])) != task["clip_sha256"]:
                    raise ValueError(f"{sid} 视频已改变；请检查本地文件")
                continue
            rejected_attempts = []
            if task and task["status"] == "submit_failed" and task.get("http_status") in {400, 401, 402, 422, 429}:
                # A new explicit generate invocation can retry a definite rejection.
                # The prior 4xx response is evidence no paid task was accepted.
                rejected_attempts = task.get("rejected_attempts", []) + [
                    {key: task[key] for key in ("submitted_at", "http_status", "error") if key in task}]
                task = None
            if task and task["status"] in {"submitting", "submit_unknown", "submit_failed", "failed", "cancelled"}:
                raise RuntimeError(f"{sid} 处于 {task['status']}；先核对平台任务，不自动重新提交收费请求")
            if task is None:
                payload = build_i2v_payload(inside(run, state["images"][sid]["path"]),
                                            shot["motion_prompt"], **story["video"], duration=shot["duration"])
                task = {"status": "submitting", "submitted_at": now(),
                        "estimated_cny": estimate["per_shot"][sid],
                        "base_url": base, "rejected_attempts": rejected_attempts,
                        "request_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}
                state["tasks"][sid] = task
                state["budget_cny"] = str(budget)
                save(run, state)  # Reserve before sending. A crash never silently repeats POST.
                try:
                    task["task_id"] = client.submit(payload)
                    task["status"] = "queued"
                except MiniMaxError as exc:
                    task["status"] = "submit_unknown" if exc.uncertain else "submit_failed"
                    task["error"] = str(exc)
                    task["http_status"] = exc.status_code
                    save(run, state)
                    raise
                save(run, state)
            response = client.query(task["task_id"])
            task["status"] = response["status"]
            task["checked_at"] = now()
            # Do not persist expiring signed download URLs in the run or public package.
            if response.get("usage"):
                task["usage"] = response["usage"]
            if response.get("error"):
                task["error"] = response["error"]
            save(run, state)
            if task["status"] in {"failed", "cancelled"}:
                raise RuntimeError(f"{sid} 平台任务 {task['status']}；任务 ID: {task['task_id']}")
            if task["status"] == "succeeded":
                relative = f"videos/{sid}.mp4"
                dest = inside(run, relative)
                dest.parent.mkdir(exist_ok=True)
                # Only the downloaded + hash-verified branch above may reuse a
                # file. A file without persisted provenance is never accepted.
                if dest.exists():
                    task.setdefault("preserved_files", []).append(preserve_unregistered(run, dest))
                    save(run, state)
                client.download(response["content"]["url"], dest)
                try:
                    checked = probe(dest)
                    duration = float(checked["duration"])
                    if abs(duration - shot["duration"]) > 0.6:
                        raise ValueError(f"{sid} 视频时长与请求不一致")
                    if abs(checked["width"] / checked["height"] - 9 / 16) > 0.03:
                        raise ValueError(f"{sid} 返回视频不是 9:16 竖幅")
                except Exception:
                    # Keep downloaded output for diagnosing real provider failures.
                    task["status"] = "download_invalid"
                    save(run, state)
                    raise
                task.update(status="downloaded", clip=relative, clip_sha256=digest(dest), media=checked)
                save(run, state)
        done = all(state["tasks"].get(shot["id"], {}).get("status") == "downloaded" for shot in story["shots"])
        return {"status": "videos_ready" if done else "pending", "tasks": state["tasks"],
                "next": "assemble" if done else "等待至少 10 秒后重跑同一 generate 命令；会查询已有 task_id"}


def reconcile_task(run, shot_id, task_id, client=None, env_file=None):
    """Recover an uncertain POST only after an operator matched the provider task."""
    from minimax_video import MiniMaxClient, load_env
    if env_file:
        load_env(env_file, override=True)
    base = official_base_url()
    if client is None:
        client = MiniMaxClient(base_url=base, timeout=45)
    with locked_run(run) as (run, story, state):
        task = state["tasks"].get(shot_id)
        if not task or task["status"] not in {"submitting", "submit_unknown"}:
            raise ValueError("仅恢复已经提交但结果不明的镜头")
        if task.get("base_url", base) != base:
            raise ValueError("已有任务属于不同服务域，不能混用")
        if any(t.get("task_id") == task_id for sid, t in state["tasks"].items() if sid != shot_id):
            raise ValueError("该平台任务已属于其他镜头")
        response = client.query(task_id)
        shot = next(s for s in story["shots"] if s["id"] == shot_id)
        expected = {**story["video"], "duration": shot["duration"]}
        if any(response.get(key) != value for key, value in expected.items()):
            raise ValueError("平台任务的模型、分辨率或时长与该镜头不符，不能绑定")
        if response.get("task_type", "generation") != "generation":
            raise ValueError("该平台任务不是视频生成任务")
        task.update(task_id=task_id, status=response["status"], reconciled_at=now())
        save(run, state)
        return {"reconciled": shot_id, "task_id": task_id, "status": task["status"]}


def assemble(run, *, preview=False, voiceover=False):
    from media import render
    with locked_run(run) as (run, story, state):
        verify_images(run, story, state)
        if voiceover and not preview:
            raise ValueError("本地 scratch 配音用于分镜预演；真实成片保留模型音频并另行验收")
        key = "preview_voiceover" if voiceover else "preview" if preview else "final"
        old = state["outputs"].get(key)
        if old and verify_output(run, old):
            return {"reused": True, **old}
        shots = []
        for shot in story["shots"]:
            prepared = {**shot, "image": state["images"][shot["id"]]["path"]}
            if voiceover:
                from narration import synthesize
                narration = synthesize(shot, run / "voiceover" / f"{shot['id']}.wav")
                prepared["voiceover"] = str(Path(narration["path"]).relative_to(run))
                state.setdefault("voiceovers", {})[shot["id"]] = narration
                save(run, state)
            if not preview:
                task = state["tasks"].get(shot["id"], {})
                if task.get("status") != "downloaded":
                    raise ValueError("真实视频尚未全部下载；preview 仅生成分镜预演，不能代替 assemble")
                if digest(inside(run, task["clip"])) != task["clip_sha256"]:
                    raise ValueError("已下载视频的指纹不符")
                prepared["clip"] = task["clip"]
            shots.append(prepared)
        folder = "preview-voiceover" if voiceover else "preview" if preview else "output"
        output = run / folder / f"{key}.mp4"
        for leftover in (output, output.with_suffix(".srt"), output.parent / "cover.jpg"):
            if leftover.exists():
                state.setdefault("preserved_files", []).append(preserve_unregistered(run, leftover))
                save(run, state)
        rendered = render(shots, run, output, preview=preview)
        files = {}
        for name in ("video_path", "srt_path", "cover_path"):
            path = Path(rendered[name]).resolve()
            relative = str(path.relative_to(run))
            files[name] = {"path": relative, "sha256": digest(path)}
        evidence = {"kind": "storyboard_preview" if preview else "ai_video", "files": files,
                    "media": rendered["probe"], "verified_at": now(),
                    "shot_media": rendered.get("shots", []),
                    "semantic_review": "requires_codex_viewing_and_listening",
                    "narration": "macos_system_voices" if voiceover else "source_audio_or_silence"}
        state["outputs"][key] = evidence
        save(run, state)
        return evidence


def record_review(run, notes):
    if not isinstance(notes, str) or len(notes.strip()) < 12:
        raise ValueError("请记录实际看图、看视频及听音后的具体结论")
    with locked_run(run) as (run, _story, state):
        final = state["outputs"].get("final")
        if not final or not verify_output(run, final):
            raise ValueError("请先完成真实视频合成")
        final["review"] = {"video_sha256": final["files"]["video_path"]["sha256"],
                           "notes": notes.strip(), "reviewed_at": now(), "basis": "operator_observation"}
        final["semantic_review"] = "operator_recorded"
        save(run, state)
        return {"review": final["review"], "note": "此记录来自操作者观察，程序只校验它绑定的文件"}


def upload_package(run):
    with locked_run(run) as (run, story, state):
        final = state["outputs"].get("final")
        if not final or final.get("kind") != "ai_video" or not verify_output(run, final):
            raise ValueError("上传包只接受已合成、已核验的真实 AI 视频；分镜预演不可冒充成片")
        if any(state["tasks"].get(s["id"], {}).get("status") != "downloaded" for s in story["shots"]):
            raise ValueError("缺少第三方生成任务的完成证据")
        if final.get("review", {}).get("video_sha256") != final["files"]["video_path"]["sha256"]:
            raise ValueError("请先实际检查成片的画面、台词和声音，再用 review 登记结果")
        dest = run / "upload-package.zip"
        if dest.exists():
            expected = state["upload"].get("package_sha256")
            if expected and digest(dest) == expected:
                return {"path": str(dest), "reused": True, **state["upload"]}
            state.setdefault("preserved_files", []).append(preserve_unregistered(run, dest))
            save(run, state)
        with zipfile.ZipFile(dest, "x", compression=zipfile.ZIP_DEFLATED) as package:
            for field, name in (("video_path", "video.mp4"), ("cover_path", "cover.jpg"), ("srt_path", "captions.srt")):
                package.write(inside(run, final["files"][field]["path"]), name)
            package.writestr("post.txt", f"{story['title']}\n\n{story['description']}\n\n来源：{story['source']['url']}\n")
            package.writestr("source.json", json.dumps(story["source"], ensure_ascii=False, indent=2))
            package.writestr("handoff.json", json.dumps({"status": "awaiting_upload", "uploader_implemented": False,
                "publication": "not_published", "video_sha256": final["files"]["video_path"]["sha256"],
                "verification_required": "目标视频号草稿可重新打开播放并显示对应文案；公开发布另需授权和状态证据"}, ensure_ascii=False, indent=2))
        state["upload"] = {"status": "awaiting_upload", "adapter": "not_implemented",
                           "package": "upload-package.zip", "package_sha256": digest(dest)}
        save(run, state)
        return {"path": str(dest), **state["upload"]}


def status(run):
    with locked_run(run) as (run, story, state):
        return {"run": str(run), "story": story["title"], "images": len(state["images"]),
                "shot_count": len(story["shots"]), "tasks": state["tasks"], "outputs": state["outputs"],
                "upload": state["upload"], "estimate": quote(story)}


def doctor():
    return {"python": sys.version.split()[0], "ffmpeg": shutil.which("ffmpeg"),
            "ffprobe": shutil.which("ffprobe"), "pillow": importlib.util.find_spec("PIL") is not None,
            "local_preview_tts": shutil.which("say"),
            "minimax_key_in_environment": bool(os.environ.get("MINIMAX_API_KEY")),
            "search": "由 Codex 联网工具执行，须当前会话检查", "image_generation": "由 Codex GPT 生图执行，须当前会话检查",
            "channels_uploader": "not_implemented", "end_to_end_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    for name in ("init", "status", "image", "estimate", "generate", "reconcile", "assemble", "preview", "review", "upload-package"):
        command = sub.add_parser(name)
        command.add_argument("--run", required=True, type=Path)
        if name == "init":
            command.add_argument("--story", required=True, type=Path)
        if name == "image":
            command.add_argument("--shot", required=True)
            command.add_argument("--file", required=True, type=Path)
        if name in {"generate", "reconcile"}:
            command.add_argument("--env-file", type=Path)
        if name == "generate":
            command.add_argument("--budget-cny", required=True, type=float)
        if name == "reconcile":
            command.add_argument("--shot", required=True)
            command.add_argument("--task-id", required=True)
        if name == "review":
            command.add_argument("--notes", required=True)
        if name == "preview":
            command.add_argument("--voiceover", action="store_true", help="使用 macOS 中文系统音色生成旁白与角色配音")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "init":
            result = init_run(args.story, args.run)
        elif args.command == "status":
            result = status(args.run)
        elif args.command == "image":
            result = import_image(args.run, args.shot, args.file)
        elif args.command == "estimate":
            with locked_run(args.run) as (_, story, _state):
                result = quote(story)
        elif args.command == "generate":
            result = generate(args.run, args.env_file, args.budget_cny)
        elif args.command == "reconcile":
            result = reconcile_task(args.run, args.shot, args.task_id, env_file=args.env_file)
        elif args.command in {"assemble", "preview"}:
            result = assemble(args.run, preview=args.command == "preview", voiceover=getattr(args, "voiceover", False))
        elif args.command == "review":
            result = record_review(args.run, args.notes)
        else:
            result = upload_package(args.run)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 75 if result.get("status") == "pending" else 0
    except Exception as exc:
        # Client exceptions are already redacted. Do not dump credentials or request bodies.
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
