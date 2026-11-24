#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One Danish tender, end to end: find it, download what can be downloaded, read it, say what
could not be read.

    python3 eis_tool.py day 2026-09-02 --country DK --out work    # the published window
    python3 eis_tool.py probe --country DK                        # does this address get Denmark whole
    python3 eis_tool.py discover --date 2026-09-02 --country DK   # the window, fetching nothing
    python3 eis_tool.py fetch <procedureId> --country DK          # one tender into a home
    python3 eis_tool.py reconcile --date 2026-09-02 --country DK  # the coverage controls alone
    python3 eis_tool.py scans --date 2026-09-02 --country DK      # read what no decoder could
    python3 eis_tool.py extract --pack out                        # deterministic text

WHY IT IS CALLED `eis_tool.py` IN A DANISH REPOSITORY. The name is the family's, not the
portal's: Latvia's, Lithuania's, Estonia's and Finland's tools all carry it, and a person who has
driven one has driven this. `udbud_tool.py` would have been the fifth spelling of one command.

ONE COUNTRY, AND IT STILL HAS TO BE NAMED. `--country DK` has no default: the destination folder
is derived from it. See country.py.
"""

import argparse
import json
import os
import re
import sys

import country
from console import utf8_streams


def extract(pack, with_images=False, keep_unpacked=False):
    """Deterministic text. Imported rather than shelled out, so a failure is a traceback."""
    import normalize
    argv = ["--in", pack, "--out", os.path.join(pack, "normalized")]
    if with_images:
        argv.append("--with-images")
    if keep_unpacked:
        argv.append("--keep-unpacked")
    return normalize.main(argv)


def read_scans(pack, model=None, limit=None, provider=None):
    """The fallback lane over files no decoder could read. Never fails the run."""
    import assist as assist_mod
    provider = provider or os.environ.get("ASSIST_PROVIDER", assist_mod.DEFAULT_PROVIDER)
    _, needs_key, _, _ = assist_mod.PROVIDERS.get(
        provider, assist_mod.PROVIDERS[assist_mod.DEFAULT_PROVIDER])
    api_key = (os.environ.get("%s_API_KEY" % provider.upper())
               or os.environ.get("ASSIST_API_KEY"))
    if needs_key and not api_key:
        print("scan lane skipped -- %s_API_KEY not set (the pack is complete without it)"
              % provider.upper())
        return 0
    try:
        doc = assist_mod.run(pack, model=model, api_key=api_key, provider=provider, limit=limit)
    except Exception as exc:
        print("scan lane skipped -- %s" % str(exc)[:200])
        return 0
    print("%s lane - %d read - %d deferred - %d skipped"
          % (doc["provider"], doc["read"], doc["deferred"], doc["skipped"]))
    return 0


def read_targets(source):
    """Watched references from a file or from the argument itself, deduplicated, in order.

    A Danish card is held by its procedure id (`DK:<uuid>` or the bare uuid); a notice id works
    too, and is followed to its procedure's newest live notice.
    """
    if not source:
        return []
    raw = source
    if os.path.exists(source):
        with open(source, encoding="utf-8") as fh:
            raw = fh.read()
    out, seen = [], set()
    for token in re.split(r"[\s,]+", raw.strip()):
        token = token.split(":")[-1].strip().lower()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def probe():
    """Does this address get the Denmark a workstation gets? The egress draw, run here."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    import dk_egress
    return dk_egress.main()


def main(argv=None):
    utf8_streams()

    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="turn a downloaded pack into text")
    p.add_argument("--pack", required=True)
    p.add_argument("--with-images", action="store_true")

    p = sub.add_parser("day", help="fetch one country's published window into the delivery shape")
    p.add_argument("date", help="YYYY-MM-DD, a Danish publication date, the first day of the window")
    p.add_argument("--to", default=None, help="the last day; absent means a single day")
    p.add_argument("--out", default="work")
    p.add_argument("--limit", type=int, default=None, help="stop after this many, for a trial")
    p.add_argument("--policy", default=None,
                   help="recall policy: JSON, a path to one, or DK_POLICY from the environment. "
                        "Absent means fetch everything.")
    p.add_argument("--targets", default=None,
                   help="procedure ids to re-read whatever the gate would say -- a file of them, "
                        "one per line, or the ids separated by commas")
    p.add_argument("--no-reconcile", action="store_true",
                   help="skip the coverage controls. For a trial run, never for a night")
    country.add_argument(p)

    p = sub.add_parser("probe", help="does this address get the same Denmark a workstation gets")
    country.add_argument(p)

    p = sub.add_parser("discover", help="one window's notices, without fetching any of them")
    p.add_argument("--date", required=True, help="YYYY-MM-DD, Danish")
    p.add_argument("--to", default=None)
    p.add_argument("--json", action="store_true")
    country.add_argument(p)

    p = sub.add_parser("fetch", help="one tender into a home, by procedure id or notice id")
    p.add_argument("reference")
    p.add_argument("--out", default="work")
    country.add_argument(p)

    p = sub.add_parser("reconcile", help="the coverage controls alone, without a delivery")
    p.add_argument("--date", required=True, help="YYYY-MM-DD, Danish")
    p.add_argument("--to", default=None)
    p.add_argument("--no-ted", action="store_true")
    p.add_argument("--json", action="store_true")
    country.add_argument(p)

    p = sub.add_parser("scans", help="read the files no decoder could, over one day's homes")
    p.add_argument("--out", default="work")
    p.add_argument("--date", required=True, help="the day whose homes to walk")
    p.add_argument("--model", default=None)
    p.add_argument("--provider", default=None)
    p.add_argument("--limit", type=int, default=None)
    country.add_argument(p)

    args = ap.parse_args(argv)

    try:
        code = country.resolve(args.country, os.environ) if args.command != "extract" else None
    except country.Mismatch as exc:
        print("%s: %s" % (args.command, exc), file=sys.stderr)
        return 2

    if args.command == "extract":
        return extract(os.path.abspath(args.pack), args.with_images)

    if args.command == "probe":
        return probe()

    if args.command == "discover":
        import dk_targets
        found = dk_targets.window(args.date, args.to or args.date)
        if args.json:
            json.dump([{k: v for k, v in r.items() if k != "record"} for r in found],
                      sys.stdout, ensure_ascii=False, indent=2)
            print()
            return 0
        kinds = {}
        for row in found:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        print("%s..%s: %d notices  %s" % (args.date, args.to or args.date, len(found), kinds))
        return 0

    if args.command == "reconcile":
        import dk_recon
        report = dk_recon.run(args.date, args.to, ted=not args.no_ted)
        if args.json:
            json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
            print()
        else:
            print(dk_recon.line(report))
        return 0 if report["ok"] else 1

    if args.command == "fetch":
        import dk_day
        import dk_fetch
        target, document = dk_day.live_notice(args.reference)
        if target is None:
            print("fetch: no live notice for %s -- awarded, cancelled or withdrawn" % args.reference,
                  file=sys.stderr)
            return 1
        out = os.path.join(args.out, code)
        done = dk_fetch.fetch(target, out, document)
        _, folder = dk_day.one_tender(target, done, out)
        print("%s (%s): %d of %d document(s), %.1f MB, documents %s on %s -> %s"
              % (done["ref"], done["pid"], done["documents"], done["catalogued"],
                 done["bytes"] / 1048576.0, done["documents_available"],
                 done["documents_host"], done["home"]))
        if done["index"].get("documents_note"):
            print("  the host said: %s" % done["index"]["documents_note"])
        print("  deliver it with: python3 deliver_dk.py --out %s --date %s" % (args.out, folder))
        return 0

    if args.command == "scans":
        root = os.path.join(args.out, code)
        day_file = os.path.join(root, args.date, "day.json")
        if not os.path.exists(day_file):
            print("scans: no day at %s -- nothing to walk" % args.date, file=sys.stderr)
            return 0
        with open(day_file, encoding="utf-8") as fh:
            day = json.load(fh)
        for row in day.get("tenders", []):
            home = os.path.join(root, "tenders", str(row["pid"]))
            # A tender with no readable documents has no queue, and that is not a failure.
            if not os.path.exists(os.path.join(home, "normalized", "manifest_normalized.json")):
                continue
            read_scans(home, model=args.model, limit=args.limit, provider=args.provider)
        return 0

    if args.command == "day":
        import dk_day
        import dk_recon
        out = os.path.join(args.out, code)
        day, _ = dk_day.run(args.date, out, args.limit, policy=args.policy,
                            watch=read_targets(args.targets), date_to=args.to,
                            reconcile=not args.no_reconcile)
        print("%s %s..%s: %d/%d delivered, %d gated, %d closed, %d document(s) %s -> %s"
              % (code, day["window"]["from"], day["window"]["to"],
                 day["coverage"]["delivered"], day["coverage"]["targets"],
                 day["coverage"]["gated"], day["coverage"]["closed"],
                 day["counts"]["documents"], day["documents_available"], out))
        if day.get("reconciliation"):
            print("  %s" % dk_recon.line(day["reconciliation"]))
        if day.get("discovery_error"):
            print("  discovery: %s" % day["discovery_error"], file=sys.stderr)
        for row in day.get("lost", []):
            print("  lost %s (%s): %s" % (row.get("ref") or row.get("pid"),
                                          row.get("kind") or "?", row.get("reason")),
                  file=sys.stderr)
        return 0 if day["complete"] else 1

    raise AssertionError("unreachable: argparse rejects any other command")


if __name__ == "__main__":
    sys.exit(main())
