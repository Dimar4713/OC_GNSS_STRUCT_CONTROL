from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def fingerprint(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"Orekit data root is not a directory: {root}")
    files = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(root).parts
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not files:
        raise ValueError(f"Orekit data root contains no physical files: {root}")

    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                digest.update(chunk)
        digest.update(b"\xff")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(fingerprint(args.root))


if __name__ == "__main__":
    main()
