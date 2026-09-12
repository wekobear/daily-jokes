"""Real FFmpeg integration tests; run with python -m unittest discover -s tests."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.media import MediaError, probe, render


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="笑话 media test '")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "videos").mkdir()
        (self.root / "images").mkdir()

    def clip(self, name, *, audio=False, duration=0.6):
        path = self.root / "videos" / name
        args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
                "-f", "lavfi", "-i", f"color=c=blue:s=180x320:r=30:d={duration}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if audio:
            args += ["-c:a", "aac", "-shortest"]
        subprocess.run(args + [str(path)], check=True, capture_output=True)
        return path

    def test_real_assembly_audio_subtitles_cover_and_non_ascii_path(self):
        first = self.clip("有声.mp4", audio=True)
        second = self.clip("无声.mp4")
        self.assertTrue(probe(first)["audio"])
        self.assertFalse(probe(second)["audio"])
        original_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, second)]
        shots = [
            {"id": "s1", "duration": 0.6, "subtitle": "老板问：你怎么迟到了？", "clip": "videos/有声.mp4"},
            {"id": "s2", "duration": 0.6, "subtitle": "我说：路上没人叫我起床。", "clip": "videos/无声.mp4"},
        ]
        result = render(shots, self.root, Path("成品/final.mp4"))
        actual = result["probe"]
        self.assertEqual(result["mode"], "generated_video_assembly")
        self.assertEqual((actual["width"], actual["height"]), (720, 1280))
        self.assertEqual((actual["video_codec"], actual["audio_codec"]), ("h264", "aac"))
        self.assertEqual(actual["pixel_format"], "yuv420p")
        self.assertAlmostEqual(actual["fps"], 30)
        self.assertAlmostEqual(actual["duration"], 1.2, delta=0.05)
        self.assertEqual([s["source_audio"] for s in result["shots"]], [True, False])
        self.assertEqual([s["audio_action"] for s in result["shots"]], ["preserved", "silence_added"])
        self.assertTrue(Path(result["cover_path"]).is_file())
        srt = Path(result["srt_path"]).read_text(encoding="utf-8")
        self.assertIn("00:00:00,600 --> 00:00:01,200", srt)
        self.assertIn("老板问", srt)
        self.assertEqual(original_hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, second)])
        # The first clip's sine wave survives; the silent second clip stays silent.
        import array
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", result["video_path"],
                              "-f", "s16le", "-ac", "1", "-ar", "8000", "-"],
                             capture_output=True, check=True).stdout
        samples = array.array("h", pcm)
        self.assertGreater(max(abs(v) for v in samples[800:3200]), 500)
        self.assertLess(max(abs(v) for v in samples[6400:8800]), 100)
        with self.assertRaises(FileExistsError):
            render(shots, self.root, Path("成品/final.mp4"))

    def test_preview_is_labelled_and_keeps_source_image(self):
        from PIL import Image
        image = self.root / "images" / "s1.png"
        Image.new("RGB", (180, 320), "salmon").save(image)
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        shots = [{"id": "s1", "duration": 0.5, "subtitle": "这是分镜预演。", "image": "images/s1.png"}]
        with self.assertRaisesRegex(MediaError, "filename"):
            render(shots, self.root, Path("not-a-video.mp4"), preview=True)
        result = render(shots, self.root, Path("预演/storyboard-preview.mp4"), preview=True)
        self.assertTrue(result["preview"])
        self.assertEqual(result["mode"], "storyboard_preview")
        self.assertEqual(result["shots"][0]["audio_action"], "silence_added")
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), digest)
        raw = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json",
                              result["video_path"]], check=True, capture_output=True, text=True)
        self.assertIn("storyboard_preview", json.loads(raw.stdout)["format"]["tags"]["comment"])
        # A dark label at top-left and subtitle box appear in the encoded frame.
        with Image.open(result["cover_path"]) as cover:
            self.assertLess(sum(cover.getpixel((30, 55))), 250)
            self.assertLess(sum(cover.getpixel((40, 1050))), 250)

    def test_invalid_video_missing_clip_short_clip_and_path_escape(self):
        broken = self.root / "videos" / "broken.mp4"
        broken.write_text("not a movie", encoding="utf-8")
        with self.assertRaises(MediaError):
            probe(broken)
        shot = {"id": "s1", "duration": 1, "subtitle": "你好", "clip": "videos/missing.mp4"}
        with self.assertRaisesRegex(MediaError, "Missing clip"):
            render([shot], self.root, Path("final.mp4"))
        shot["clip"] = "../outside.mp4"
        with self.assertRaisesRegex(MediaError, "inside run_dir"):
            render([shot], self.root, Path("final.mp4"))
        shot["clip"] = "videos/short.mp4"
        self.clip("short.mp4", duration=0.3)
        with self.assertRaisesRegex(MediaError, "shorter"):
            render([shot], self.root, Path("final.mp4"))
        with self.assertRaisesRegex(MediaError, "inside run_dir"):
            render([shot], self.root, self.root.parent / "outside.mp4")
        self.assertFalse((self.root / "final.mp4").exists())


if __name__ == "__main__":
    unittest.main()
