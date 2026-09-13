#!/usr/bin/env python3
"""Fetch a bounded, reproducible A-Joke candidate batch, without API keys."""
import argparse
from datetime import date, datetime, timezone
import hashlib
from html import unescape
import json
from pathlib import Path
import random
import re
from urllib.request import Request, urlopen

REPO = "Licoy/A-Joke"
SKILL_VERSION = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
REVISION = "9d87e1c8f3fe9123c54fcc818e7fbd0255fd14a4"
ISSUE_PATH = re.compile(r"joke/\d{4}/\d{2}/\d{2}\.md")
HEADING = re.compile(r"^###\s+.*?\{\s*第(\d+)档\s*\}\s*(.*?)\s*$", re.M)


def fetch(url):
    request = Request(url, headers={"User-Agent": f"jokes-skill/{SKILL_VERSION}"})
    with urlopen(request, timeout=20) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError("Source exceeds 4 MB limit")
    return raw.decode("utf-8-sig")


def parse_issue(content, path):
    if not ISSUE_PATH.fullmatch(path):
        raise ValueError("Unexpected issue path")
    headings = list(HEADING.finditer(content))
    records = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        body = content[match.end():end]
        body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
        body = unescape(re.sub(r"<[^>]*>", "", body))
        body = "\n".join(line.strip() for line in body.splitlines() if line.strip())
        normalized = "".join(c for c in body.casefold() if c.isalnum())
        if not normalized:
            continue
        line = content[:match.start()].count("\n") + 1
        records.append({
            "id": f"a-joke/{path}/{match.group(1)}", "title": match.group(2),
            "text": body, "fingerprint": hashlib.sha256(normalized.encode()).hexdigest(),
            "source": {"kind": "web_adaptation", "repository": REPO,
                       "revision": REVISION, "path": path,
                       "entry": int(match.group(1)),
                       "url": f"https://github.com/{REPO}/blob/{REVISION}/{path}#L{line}",
                       "issue_date": path[5:-3].replace("/", "-")},
            "review_status": "unreviewed", "circles": [],
        })
    return records


def collect(day, count=30, issues=4, fetcher=fetch):
    date.fromisoformat(day)
    if not 1 <= count <= 100 or not 1 <= issues <= 10:
        raise ValueError("count must be 1..100; issues must be 1..10")
    tree = json.loads(fetcher(f"https://api.github.com/repos/{REPO}/git/trees/{REVISION}?recursive=1"))
    if tree.get("truncated"):
        raise ValueError("Incomplete upstream tree")
    paths = sorted({item["path"] for item in tree["tree"]
                    if item.get("type") == "blob" and ISSUE_PATH.fullmatch(item.get("path", ""))})
    if not paths:
        raise ValueError("No matching issue files")
    rng = random.Random(day + REVISION)
    rng.shuffle(paths)
    records, seen, failures, loaded = [], set(), [], []
    for path in paths[:issues]:
        try:
            parsed = parse_issue(fetcher(f"https://raw.githubusercontent.com/{REPO}/{REVISION}/{path}"), path)
        except (OSError, UnicodeError, ValueError):
            failures.append(path)
            continue
        loaded.append(path)
        for record in parsed:
            if record["fingerprint"] not in seen:
                seen.add(record["fingerprint"])
                records.append(record)
    rng.shuffle(records)
    selected = records[:count]
    retrieved_at = datetime.now(timezone.utc).isoformat()
    for record in selected:
        record["source"]["retrieved_at"] = retrieved_at
    return {"schema_version": 1, "date": day, "repository": REPO, "revision": REVISION,
            "retrieved_at": retrieved_at, "available_issue_files": len(paths),
            "loaded_issues": loaded, "failed_issues": failures,
            "requested_candidates": count, "candidate_count": len(selected),
            "shortfall": max(0, count - len(selected)),
            "notice": "Historical web compilation; candidates are not publication-approved. Agent must review rights, content, circles and semantic duplicates.",
            "candidates": selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--issues", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output already exists; choose a new batch path")
    result = collect(args.date, args.count, args.issues)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({key: result[key] for key in
                      ("available_issue_files", "candidate_count", "shortfall", "failed_issues")}, ensure_ascii=False))
    return 2 if result["shortfall"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
