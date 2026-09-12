"""Local narration checks with real decoded audio; no paid or network providers."""

import array
import copy
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import narration


def pcm_samples(path):
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le",
         "-ac", "1", "-ar", "8000", "-"],
        check=True, capture_output=True,
    )
    return array.array("h", result.stdout)


class SpeechTextTests(unittest.TestCase):
    def test_explicit_speech_takes_precedence_over_display_subtitle(self):
        shot = {"id": "s1", "duration": 4, "subtitle": "画面字幕，不应作为配音。",
                "speech": [{"speaker": "narrator", "text": "旁白在这里。"},
                           {"speaker": "woman", "text": "我来回答。"}]}
        self.assertEqual(narration.speech_for_shot(shot), shot["speech"])

    def test_dialogue_labels_are_not_spoken_and_narration_lines_merge(self):
        shot = {"id": "s1", "duration": 8,
                "subtitle": "有位女士走进店里。\n她打算借一把伞。\n女士：外面下雨了吗？\n她看看窗外。\n她：那我再等等。"}
        speech = narration.speech_for_shot(shot)
        self.assertEqual(len(speech), 4)
        self.assertIn("有位女士走进店里。", speech[0]["text"])
        self.assertIn("她打算借一把伞。", speech[0]["text"])
        self.assertEqual([speech[index]["text"] for index in (1, 3)],
                         ["外面下雨了吗？", "那我再等等。"])
        self.assertEqual(speech[1]["speaker"], speech[3]["speaker"])
        self.assertNotEqual(speech[0]["speaker"], speech[1]["speaker"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "ffmpeg and ffprobe required")
class NarrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="笑话 narration test '")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "配音.wav"
        self.calls = []
        self.shot = {
            "id": "s1", "duration": 2.0, "subtitle": "旁白说完，再由女士回答。",
            "speech": [{"speaker": "narrator", "text": "早上好。"},
                       {"speaker": "woman", "text": "你好呀。"}],
        }
        self.voices = {"narrator": "Fixture narrator", "woman": "Fixture woman"}

    def tones(self, text, voice, rate, path):
        """Deterministic audible stand-in for an offline TTS adapter."""
        self.calls.append((text, voice, rate, Path(path)))
        frequency = 440 if voice == self.voices["narrator"] else 660
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
             "-f", "lavfi", "-i",
             f"sine=frequency={frequency}:sample_rate=48000:duration=0.65",
             str(path)], check=True, capture_output=True,
        )

    def generate(self, **kwargs):
        return narration.synthesize(self.shot, self.output, voices=self.voices,
                                    synthesizer=self.tones, **kwargs)

    def test_complete_audible_lines_fit_and_cues_match_the_decoded_audio(self):
        result = self.generate()
        self.assertFalse(result["cached"])
        self.assertEqual(Path(result["path"]), self.output.resolve())
        self.assertEqual(result["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual([call[0] for call in self.calls], ["早上好。", "你好呀。"])
        self.assertEqual([call[1] for call in self.calls], list(self.voices.values()))
        audio = narration.inspect_audio(self.output)
        samples = pcm_samples(self.output)
        self.assertGreater(audio["peak"], 0)
        self.assertGreater(audio["rms"], 0)
        self.assertGreater(max(abs(sample) for sample in samples), 500)
        self.assertAlmostEqual(audio["duration"], len(samples) / 8000, delta=0.03)
        self.assertAlmostEqual(result["duration"], audio["duration"], delta=0.03)
        self.assertLessEqual(audio["duration"], self.shot["duration"] + 0.04)
        self.assertGreaterEqual(audio["duration"], 1.3 / 1.18 - 0.04)
        self.assertGreaterEqual(result["speed"], 1)
        self.assertLessEqual(result["speed"], 1.18)
        self.assertEqual([cue["text"] for cue in result["cues"]],
                         [cue["text"] for cue in self.shot["speech"]])
        previous_end = 0
        for cue in result["cues"]:
            self.assertGreaterEqual(cue["start"], previous_end - 0.01)
            self.assertAlmostEqual(cue["source_duration"], 0.65, delta=0.03)
            self.assertGreaterEqual(cue["end"] - cue["start"], 0.65 / 1.18 - 0.03)
            self.assertLessEqual(cue["end"], audio["duration"] + 0.03)
            # The end of each utterance remains audible, including the last one.
            end_window = samples[max(0, int((cue["end"] - 0.12) * 8000)):
                                 int((cue["end"] - 0.04) * 8000)]
            self.assertTrue(end_window)
            self.assertGreater(max(abs(sample) for sample in end_window), 500)
            previous_end = cue["end"]

    def test_all_text_is_validated_before_any_synthesis(self):
        self.shot["speech"][-1]["text"] = "  "
        with self.assertRaises((ValueError, RuntimeError)):
            self.generate()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_modest_speed_increase_keeps_the_end_of_every_line_audible(self):
        self.shot["duration"] = 1.8
        result = self.generate()
        self.assertGreater(result["speed"], 1)
        self.assertLessEqual(result["speed"], 1.18)
        samples = pcm_samples(self.output)
        self.assertAlmostEqual(len(samples) / 8000, 1.8, delta=0.03)
        for cue in result["cues"]:
            self.assertAlmostEqual(cue["source_duration"], 0.65, delta=0.03)
            self.assertGreaterEqual(cue["end"] - cue["start"], 0.65 / 1.18 - 0.03)
            end_window = samples[int((cue["end"] - 0.12) * 8000):
                                 int((cue["end"] - 0.04) * 8000)]
            self.assertTrue(end_window)
            self.assertGreater(max(abs(sample) for sample in end_window), 500)

    def test_oversized_speech_fails_instead_of_cutting_a_line(self):
        self.shot["duration"] = 0.4
        with self.assertRaises((ValueError, RuntimeError)):
            self.generate()
        self.assertFalse(self.output.exists())

    def test_identical_input_reuses_audio_without_synthesizing_again(self):
        first = self.generate()
        original = self.output.read_bytes()
        call_count = len(self.calls)
        second = self.generate()
        self.assertTrue(second["cached"])
        self.assertEqual(len(self.calls), call_count)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(self.output.read_bytes(), original)

    def test_changed_parameters_and_text_cannot_overwrite_existing_audio(self):
        self.generate()
        original = self.output.read_bytes()
        call_count = len(self.calls)
        with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
            self.generate(rate=210)
        self.shot = copy.deepcopy(self.shot)
        self.shot["speech"][0]["text"] = "改过的台词。"
        with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
            self.generate()
        self.assertEqual(len(self.calls), call_count)
        self.assertEqual(self.output.read_bytes(), original)

    def test_modified_audio_is_not_adopted_as_a_valid_cache(self):
        self.generate()
        call_count = len(self.calls)
        self.output.write_bytes(b"changed user audio")
        with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
            self.generate()
        self.assertEqual(len(self.calls), call_count)
        self.assertEqual(self.output.read_bytes(), b"changed user audio")

    def test_unregistered_output_is_not_overwritten(self):
        self.output.write_bytes(b"pre-existing user file")
        with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
            self.generate()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.output.read_bytes(), b"pre-existing user file")

    def test_silent_synthesis_and_invalid_media_are_rejected(self):
        silent = self.root / "silent.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.3",
             str(silent)], check=True, capture_output=True,
        )
        inspected = narration.inspect_audio(silent)
        self.assertEqual(inspected["peak"], 0)
        self.assertEqual(inspected["rms"], 0)

        def silent_synth(text, voice, rate, path):
            shutil.copyfile(silent, path)

        with self.assertRaises((ValueError, RuntimeError)):
            narration.synthesize(self.shot, self.output, voices=self.voices,
                                  synthesizer=silent_synth)
        self.assertFalse(self.output.exists())
        self.output.write_bytes(b"this is not audio")
        with self.assertRaises((ValueError, RuntimeError)):
            narration.inspect_audio(self.output)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("say"),
                         "macOS local say required")
    def test_local_chinese_speech_decodes_to_real_non_silent_audio(self):
        available = subprocess.run(["say", "-v", "?"], check=True,
                                   capture_output=True, text=True).stdout
        if "Tingting" not in available:
            self.skipTest("Tingting Chinese voice is not installed")
        shot = {"id": "s1", "duration": 4.0, "subtitle": "你好。",
                "speech": [{"speaker": "narrator", "text": "你好。"}]}
        result = narration.synthesize(shot, self.output,
                                      voices={"narrator": "Tingting"})
        samples = pcm_samples(self.output)
        self.assertGreater(max(abs(sample) for sample in samples), 200)
        self.assertGreater(sum(abs(sample) > 100 for sample in samples), 500)
        self.assertEqual(result["cues"][0]["text"], "你好。")
        self.assertLessEqual(result["duration"], 4.04)


if __name__ == "__main__":
    unittest.main()
