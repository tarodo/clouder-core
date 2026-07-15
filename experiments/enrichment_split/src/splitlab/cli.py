"""splitlab CLI: pull-sample | run | report."""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_settings
from .sample import save_sample

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(prog="splitlab")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull-sample", help="pull stratified 50+50 sample from prod")
    p_pull.add_argument("--labels", type=int, default=50)
    p_pull.add_argument("--artists", type=int, default=50)

    args = parser.parse_args()
    if args.cmd == "pull-sample":
        from .pull_sample import pull

        settings = load_settings()
        data = pull(settings, labels=args.labels, artists=args.artists)
        out = ROOT / "sample" / "sample.yaml"
        save_sample(out, data)
        print(f"labels={len(data['labels'])} artists={len(data['artists'])} -> {out}")


if __name__ == "__main__":
    main()
