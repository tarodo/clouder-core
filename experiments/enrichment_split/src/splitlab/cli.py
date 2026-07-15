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

    p_run = sub.add_parser("run", help="run the two-pass pipeline over the sample")
    p_run.add_argument("--cap", type=int, default=2)
    p_run.add_argument("--kind", choices=["label", "artist"], default=None)
    p_run.add_argument("--limit", type=int, default=None)

    p_rep = sub.add_parser("report", help="summarize a run and render the gate report")
    p_rep.add_argument("run_id")

    args = parser.parse_args()
    settings = load_settings()

    if args.cmd == "pull-sample":
        from .pull_sample import pull

        data = pull(settings, labels=args.labels, artists=args.artists)
        out = ROOT / "sample" / "sample.yaml"
        save_sample(out, data)
        print(f"labels={len(data['labels'])} artists={len(data['artists'])} -> {out}")

    elif args.cmd == "run":
        import json as _json

        from .runner import run_experiment
        from .sample import load_sample

        sample = load_sample(ROOT / "sample" / "sample.yaml")
        kinds = [args.kind] if args.kind else ["label", "artist"]
        run_id = run_experiment(sample, settings, cap=args.cap, kinds=kinds,
                                limit=args.limit, outputs_root=ROOT / "outputs")
        print(f"run_id={run_id}")

    elif args.cmd == "report":
        import json as _json

        from .metrics import summarize
        from .report import render

        run_dir = ROOT / "outputs" / args.run_id
        summary = summarize(run_dir)
        manifest = _json.loads((run_dir / "manifest.json").read_text())
        md = render(summary, manifest)
        ig_lines = []
        for path in sorted(run_dir.glob("*__*.json")):
            cell = _json.loads(path.read_text())
            url = cell["merged"].get("instagram_url")
            if url:
                tier = cell["provenance"].get("instagram_url", "?")
                ig_lines.append(f"- {cell['kind']} **{cell['entity']['name']}** -> {url} ({tier})")
        md += "\n" + "\n".join(ig_lines) + "\n"
        out = ROOT / "outputs" / f"{args.run_id}-report.md"
        out.write_text(md)
        print(md[:2000])
        print(f"\nfull report -> {out}")


if __name__ == "__main__":
    main()
