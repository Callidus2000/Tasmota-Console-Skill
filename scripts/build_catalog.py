#!/usr/bin/env python3
"""Assemble the OpenCode HTTP catalog in a new directory."""
import argparse
import json
import re
import shutil
from pathlib import Path, PurePosixPath


def build(output):
    root = Path(__file__).resolve().parent.parent
    index = json.loads((root / "catalog" / "index.json").read_text(encoding="utf-8"))
    entries = index["skills"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Catalog must have at least one entry")
    copies = []
    for entry in entries:
        name = entry["name"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("Unsafe skill name")
        if not isinstance(entry["version"], str) or not entry["version"]:
            raise ValueError("A catalog version is required")
        if "SKILL.md" not in entry["files"]:
            raise ValueError("Missing SKILL.md")
        for item in entry["files"]:
            path = PurePosixPath(item)
            if (not item or path.is_absolute() or ".." in path.parts or "\\" in item
                    or any(part.startswith(".") for part in path.parts)):
                raise ValueError("Unsafe catalog path")
            source = (root / Path(*path.parts)).resolve()
            if not source.is_relative_to(root) or not source.is_file():
                raise ValueError("Catalog source missing or outside repository")
            copies.append((source, Path(name, *path.parts)))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    for source, relative in copies:
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new catalog directory")
    build(parser.parse_args().output)
