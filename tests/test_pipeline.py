"""Runner tests: external provider is simulated; FFmpeg rendering is real."""
from contextlib import contextmanager
import copy
import fcntl
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline
from minimax_video import MiniMaxError


class FakeProvider:
    """No HTTP and no billing. Only state transitions are simulated here."""
    def __init__(self, clip=None, fail_submit=False, fail_query=False):
        self.clip = clip
        self.fail_submit = fail_submit
        self.fail_query = fail_query
        self.submissions = 0
        self.queries = {}
        self.downloads = 0

    def submit(self, payload):
        self.submissions += 1
        if self.fail_submit:
            raise MiniMaxError("simulated lost response", uncertain=True)
        return f"task-{self.submissions}"

    def query(self, task_id):
        if self.fail_query:
            self.fail_query = False
            raise MiniMaxError("simulated read timeout")
        self.queries[task_id] = self.queries.get(task_id, 0) + 1
        status = "running" if self.queries[task_id] == 1 else "succeeded"
        return {"id": task_id, "status": status, "model": "MiniMax-H3", "resolution": "768P",
                "duration": 4, "content": {"url": "https://fixture.invalid/generated.mp4"}}

    def download(self, url, destination):
        self.downloads += 1
        shutil.copyfile(self.clip, destination)
        return destination


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow required")
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jokes-runner-")
        self.base = Path(self.temp.name)
        self.run = self.base / "运行 空格"
        self.story = copy.deepcopy(pipeline.read_json(ROOT / "examples/umbrella/story.json"))
        self.story["shots"] = self.story["shots"][:1]
        self.story["shots"][0]["duration"] = 4
        self.story_file = self.base / "story.json"
        pipeline.write_json(self.story_file, self.story)
        pipeline.init_run(self.story_file, self.run)
        from PIL import Image
        self.image = self.base / "fixture.png"
        Image.new("RGB", (288, 512), "teal").save(self.image)
        pipeline.import_image(self.run, "s1", self.image)

    def tearDown(self):
        self.temp.cleanup()

    def test_budget_missing_image_and_modified_image_do_not_submit(self):
        provider = FakeProvider()
        with self.assertRaisesRegex(ValueError, "超过"):
            pipeline.generate(self.run, None, 1, client=provider)
        with self.assertRaises(ValueError):
            pipeline.generate(self.run, None, float("nan"), client=provider)
        image = self.run / "images/s1.png"
        image.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "改变"):
            pipeline.generate(self.run, None, 2, client=provider)
        self.assertEqual(provider.submissions, 0)

    def test_submission_unknown_never_reposts(self):
        provider = FakeProvider(fail_submit=True)
        with self.assertRaises(MiniMaxError):
            pipeline.generate(self.run, None, 2, client=provider)
        self.assertEqual(pipeline.status(self.run)["tasks"]["s1"]["status"], "submit_unknown")
        with self.assertRaisesRegex(RuntimeError, "submit_unknown"):
            pipeline.generate(self.run, None, 2, client=provider)
        self.assertEqual(provider.submissions, 1)
        provider.fail_submit = False
        pipeline.reconcile_task(self.run, "s1", "verified-existing-task", client=provider)
        self.assertEqual(provider.submissions, 1)
        self.assertEqual(pipeline.status(self.run)["tasks"]["s1"]["task_id"], "verified-existing-task")

    def test_get_timeout_resumes_same_task(self):
        provider = FakeProvider(fail_query=True)
        with self.assertRaises(MiniMaxError):
            pipeline.generate(self.run, None, 2, client=provider)
        result = pipeline.generate(self.run, None, 2, client=provider)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(provider.submissions, 1)
        self.assertEqual(provider.queries, {"task-1": 1})

    def test_definite_rejection_can_resume_without_repeating_unknown_post(self):
        provider = FakeProvider()
        with patch.object(provider, "submit", side_effect=MiniMaxError("balance", status_code=402)):
            with self.assertRaises(MiniMaxError):
                pipeline.generate(self.run, None, 2, client=provider)
        result = pipeline.generate(self.run, None, 2, client=provider)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(provider.submissions, 1)
        self.assertEqual(result["tasks"]["s1"]["rejected_attempts"][0]["http_status"], 402)

    def test_reconcile_rejects_different_service_or_task_specification(self):
        provider = FakeProvider(fail_submit=True)
        with self.assertRaises(MiniMaxError):
            pipeline.generate(self.run, None, 2, client=provider)
        with patch.dict("os.environ", {"MINIMAX_BASE_URL": "https://another.example"}):
            with self.assertRaisesRegex(ValueError, "国内官方"):
                pipeline.reconcile_task(self.run, "s1", "task-id", client=provider)
        with patch.object(provider, "query", return_value={"status": "running", "model": "MiniMax-H3", "resolution": "2K", "duration": 4}):
            with self.assertRaisesRegex(ValueError, "不能绑定"):
                pipeline.reconcile_task(self.run, "s1", "task-id", client=provider)

    def test_changed_story_and_concurrent_run_are_rejected(self):
        with (self.run / ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "已有进程"):
                pipeline.status(self.run)
        data = pipeline.read_json(self.run / "story.json")
        data["shots"][0]["motion_prompt"] = "new prompt"
        pipeline.write_json(self.run / "story.json", data)
        with self.assertRaisesRegex(ValueError, "分镜已被修改"):
            pipeline.status(self.run)

    def test_invalid_story_and_path_escape(self):
        invalid = copy.deepcopy(self.story)
        invalid["source"]["url"] = "file:///private/data"
        with self.assertRaises(ValueError):
            pipeline.validate_story(invalid)
        invalid = copy.deepcopy(self.story)
        invalid["shots"][0]["id"] = "../../evil"
        with self.assertRaises(ValueError):
            pipeline.validate_story(invalid)
        with self.assertRaises(ValueError):
            pipeline.inside(self.run, "../outside")
        (self.run / "escape").symlink_to(self.base)
        with self.assertRaises(ValueError):
            pipeline.inside(self.run, "escape/story.json")

    def test_image_import_is_idempotent_without_overwrite(self):
        self.assertTrue(pipeline.import_image(self.run, "s1", self.image)["reused"])
        from PIL import Image
        second = self.base / "second.png"
        Image.new("RGB", (288, 512), "red").save(second)
        with self.assertRaisesRegex(ValueError, "不同图片"):
            pipeline.import_image(self.run, "s1", second)
        self.assertEqual(pipeline.digest(self.image), pipeline.digest(self.run / "images/s1.png"))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_preview_cannot_be_assembled_or_uploaded_as_ai_video(self):
        preview = pipeline.assemble(self.run, preview=True)
        self.assertEqual(preview["kind"], "storyboard_preview")
        self.assertAlmostEqual(preview["media"]["duration"], 4, places=1)
        self.assertTrue(pipeline.assemble(self.run, preview=True)["reused"])
        with self.assertRaisesRegex(ValueError, "真实视频"):
            pipeline.assemble(self.run)
        with self.assertRaisesRegex(ValueError, "真实 AI 视频"):
            pipeline.upload_package(self.run)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_provider_resume_through_real_media_and_handoff_package(self):
        fixture = self.base / "fixture.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-f", "lavfi",
                        "-i", "testsrc2=size=288x512:rate=30", "-f", "lavfi", "-i", "sine=frequency=500",
                        "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(fixture)], check=True)
        provider = FakeProvider(fixture)
        self.assertEqual(pipeline.generate(self.run, None, 2, client=provider)["status"], "pending")
        self.assertEqual(pipeline.generate(self.run, None, 2, client=provider)["status"], "videos_ready")
        self.assertEqual(pipeline.generate(self.run, None, 2, client=provider)["status"], "videos_ready")
        self.assertEqual((provider.submissions, provider.downloads), (1, 1))
        # An interrupted render may leave unregistered output; preserve it and rerender.
        (self.run / "output").mkdir()
        (self.run / "output/final.mp4").write_bytes(b"interrupted output")
        final = pipeline.assemble(self.run)
        self.assertEqual(len(list((self.run / "quarantine").glob("*-final.mp4"))), 1)
        self.assertEqual(final["kind"], "ai_video")
        self.assertEqual(final["media"]["codec"], "h264")
        self.assertTrue(pipeline.assemble(self.run)["reused"])
        with self.assertRaisesRegex(ValueError, "review"):
            pipeline.upload_package(self.run)
        pipeline.record_review(self.run, "测试专用模拟审看记录：此文件为合成测试图案和测试音，不是真实AI效果验收。")
        package = pipeline.upload_package(self.run)
        self.assertEqual(package["status"], "awaiting_upload")
        self.assertEqual(package["adapter"], "not_implemented")
        with zipfile.ZipFile(package["path"]) as archive:
            self.assertEqual(set(archive.namelist()), {"video.mp4", "cover.jpg", "captions.srt", "post.txt", "source.json", "handoff.json"})
            self.assertFalse(json.loads(archive.read("handoff.json"))["uploader_implemented"])
            self.assertNotIn("task-1", archive.read("handoff.json").decode())
        self.assertTrue(pipeline.upload_package(self.run)["reused"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_unregistered_and_invalid_downloads_are_not_adopted(self):
        fixture = self.base / "fixture.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-f", "lavfi",
                        "-i", "testsrc2=size=288x512:rate=30", "-t", "4", "-c:v", "libx264", str(fixture)], check=True)
        provider = FakeProvider(fixture)
        pipeline.generate(self.run, None, 2, client=provider)
        videos = self.run / "videos"
        videos.mkdir()
        (videos / "s1.mp4").write_bytes(b"unregistered file")
        with patch.object(provider, "download", side_effect=lambda url, target: target.write_bytes(b"invalid download")):
            with self.assertRaises(RuntimeError):
                pipeline.generate(self.run, None, 2, client=provider)
        result = pipeline.generate(self.run, None, 2, client=provider)
        self.assertEqual(result["status"], "videos_ready")
        self.assertEqual(provider.submissions, 1)
        self.assertEqual(provider.downloads, 1)
        self.assertEqual(len(list((self.run / "quarantine").glob("*-s1.mp4"))), 2)


if __name__ == "__main__":
    unittest.main()
