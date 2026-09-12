#!/usr/bin/env python3
"""Build the installable jokes/ bundle from an explicit source allowlist."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["SKILL.md", "requirements.txt", ".env.example", "examples/umbrella/story.json",
            "scripts/pipeline.py", "scripts/minimax_video.py", "scripts/media.py", "scripts/narration.py", "scripts/package_skill.py",
            "references/humor-rules.md", "references/onboarding-and-state.md", "references/comic-production.md",
            "references/video-workflow.md", "references/minimax-api.md", "tests/acceptance.md"]


def build(output):
    output = Path(output)
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(f"Required skill resource missing: {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as package:
        for name in REQUIRED:
            package.write(ROOT / name, "jokes/" + name)
    with zipfile.ZipFile(output) as package:
        if package.testzip() is not None or len(package.namelist()) != len(REQUIRED):
            raise RuntimeError("Skill archive verification failed")
    return output.resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/jokes.zip")
    print(build(parser.parse_args().output))
