"""Local rendered media and state checks; uses a deterministic local audio fixture."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_video
import narration
import pipeline


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class LocalVideoTests(unittest.TestCase):
    def test_local_render_captions_audio_reuse_and_mode(self):
        with tempfile.TemporaryDirectory(prefix="local video 中文 '") as temporary:
            root = Path(temporary)
            story = pipeline.read_json(ROOT / "examples/afanti/story.json")
            story["shots"] = story["shots"][:1]
            pipeline.write_json(root / "input.json", story)
            run = root / "run"
            pipeline.init_run(root / "input.json", run)
            pipeline.import_image(run, "s1", ROOT / "examples/afanti/images/s1.png")
            original = narration.synthesize

            def tone(text, voice, rate, path):
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                                "sine=frequency=440:duration=0.65", str(path)], check=True, capture_output=True)

            def synthesize(shot, output, **kwargs):
                return original(shot, output, synthesizer=tone, **kwargs)

            with patch.object(narration, "synthesize", side_effect=synthesize):
                result = local_video.render_local(run)
            self.assertEqual(result["kind"], "local_illustrated_video")
            self.assertEqual(result["video_api_submissions"], 0)
            self.assertGreater(result["audio"]["rms"], 0.0001)
            self.assertAlmostEqual(result["media"]["duration"], 5, delta=0.12)
            captions = (run / result["files"]["srt_path"]["path"]).read_text()
            self.assertIn("路人：掉这儿了？", captions)
            self.assertEqual(captions.count(" --> "), 2)
            movie = run / result["files"]["video_path"]["path"]
            metadata = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(movie)],
                                                 check=True, capture_output=True).stdout)
            self.assertIn("local_illustrated_video", metadata["format"]["tags"]["comment"])
            with patch.object(narration, "synthesize", side_effect=AssertionError("cached run must not synthesize")):
                reused = local_video.render_local(run)
            self.assertTrue(reused["reused"])
            self.assertEqual(reused["files"], result["files"])
            self.assertEqual(pipeline.read_json(run / "state.json")["tasks"], {})


if __name__ == "__main__":
    unittest.main()
