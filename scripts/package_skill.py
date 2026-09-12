#!/usr/bin/env python3
"""Build the installable jokes/ bundle from an explicit source allowlist."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["SKILL.md", "README.md", "requirements.txt", ".env.example", ".gitignore", "examples/umbrella/story.json",
            "VERSION", "docs/getting-started.md", "docs/releases-v1.3.0.md", "references/video-provider-contract.md",
            "examples/README.md", "examples/afanti/README.md", "examples/umbrella/README.md",
            "examples/umbrella/images/s1.png", "examples/umbrella/images/s2.png", "examples/umbrella/images/s3.png",
            "examples/umbrella/cover.jpg", "examples/umbrella/preview-silent.mp4", "examples/umbrella/preview-voiceover.mp4",
            "examples/h3-trial/README.md", "examples/h3-trial/story.json", "examples/h3-trial/images/s3.png", "examples/h3-trial/demo.mp4",
            "THIRD_PARTY_NOTICES.md", "references/daily-production.md", "assets/selection-template.md",
            "docs/workflow.json", "docs/workflow.html", "docs/workflow.png", "docs/workflow-verification.md",
            "scripts/pipeline.py", "scripts/minimax_video.py", "scripts/media.py", "scripts/narration.py", "scripts/local_video.py", "scripts/package_skill.py",
            "examples/afanti/story.json", "examples/afanti/images/s1.png", "examples/afanti/images/s2.png", "examples/afanti/images/s3.png",
            "examples/afanti/demo.mp4", "examples/afanti/cover.jpg",
            "references/humor-rules.md", "references/onboarding-and-state.md", "references/comic-production.md",
            "references/video-workflow.md", "references/minimax-api.md", "tests/acceptance.md", "tests/verification.md",
            "tests/test_media.py", "tests/test_minimax_video.py", "tests/test_pipeline.py", "tests/test_narration.py", "tests/test_local_video.py"]


def build(output):
    output = Path(output)
    for name in REQUIRED:
        source = ROOT / name
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"Skill resource must be a local regular file: {name}")
        if not source.is_file():
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
