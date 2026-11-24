"""One Danish window, delivered: `day.json`, `changes.json`, and a home per tender.

WHAT A DAY IS. The two files every country tool in this family writes: `changes.json` says what
moved, `day.json` says what the window holds and is written LAST. Both point at
`tenders/<procedureId>/`, which is permanent and shared across days.

A WINDOW, NOT A DATE. A missed night is caught up by widening the window, not by running twice.
The day folder is named for the window's last day.

THE DATES ARE DANISH. udbud.dk filters by `publiceringsdato`, a calendar date in Copenhagen.

WHAT THE GATE MAY AND MAY NOT DECIDE. The gate decides what is DOWNLOADED, never what is KNOWN.
Every row in the window gets its detail -- about forty requests on a busy day -- because the
detail is the only place the procedure is printed, and the procedure is the key: without it an
award cannot close the card it answers, and an amendment cannot find the home it belongs in.

ONLY A COMPETITION IS FETCHED. `competition` (and its amendments) is something a company can bid
on. Awards and contract modifications are recorded as closes, keyed on the same procedure; plans
and market consultations are recorded and counted; nothing else costs a document request.

    python3 dk_day.py 2026-09-02 --out work/DK --limit 5
"""
import argparse
import datetime
import json
import os
import sys
import time

import dk_fetch
import dk_page
import dk_recon
import dk_targets
import dk_ted

try:
    import changes as changes_mod
except Exception:
    changes_mod = None

try:
    import policy as policy_mod
except Exception:
    policy_mod = None


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _future(when):
    if not when:
        return None
    try:
        moment = datetime.datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment > datetime.datetime.now(datetime.timezone.utc)


def _summary(target):
    return {k: target.get(k) for k in ("pid", "ref", "kind", "title", "buyer", "published", "link",
                                       "notice_id", "npn", "form_code")}


def _watched_on_ted(reference):
    """A watched tender udbud.dk knows nothing about, as TED holds it.

    Only when the portal has no notice of the procedure at all. One it knows and no longer lists as
    live was awarded or withdrawn, and TED's old competition notice must not bring it back.
    """
    if dk_targets.procedure(reference):
        return None, None
    return dk_ted.procedure(reference)


def run(date, out_root, limit=None, run_id=None, policy=None, watch=None, date_to=None,
        reconcile=True, with_text=True):
    run_id = run_id or time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    date_from, date_to = date, date_to or date
    folder = date_to

    discovery_error = None
    try:
        index_count, raw = dk_targets.rows(date_from, date_to)
    except (dk_targets.Truncated, dk_targets.OutsideWindow) as exc:
        index_count, raw, discovery_error = None, [], str(exc)
    targets = [dk_page.notice(r) for r in raw]
    # AN EMPTY WINDOW OVER A WEEKDAY IS A BROKEN CRAWL until shown otherwise. Every way the
    # search can break returns an empty list, and left unsaid that is a green, empty morning.
    discovery_failed = bool(discovery_error) or (
        bool(dk_targets.publishing_days(date_from, date_to)) and not targets)

    failed = []
    documents = {}

    # WHAT TED HOLDS AND udbud.dk DOES NOT IS READ FROM TED, so a notice the portal never pulled is
    # a tender in the day and not a line in a report.
    proof = None
    if reconcile and not discovery_error:
        proof = dk_recon.run(date_from, date_to, rows=raw, count=index_count)
    from_ted = []
    for number in dk_recon.only_ted(proof):
        try:
            target, document = dk_ted.one(number)
        except Exception as exc:
            dk_page.log("  TED did not hand over %s: %s" % (number, str(exc)[:120]))
            continue
        if target is not None:
            documents[target["notice_id"]] = document
            from_ted.append(target)
    if from_ted:
        dk_recon.taken(proof, [t["record"]["publication-number"] for t in from_ted])

    for target in targets:
        try:
            document = dk_page.detail(target["notice_id"], target["notice_version"], target["npn"])
        except Exception as exc:
            document = None
            target["detail_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:150])
        dk_page.enrich(target, document)
        documents[target["notice_id"]] = document
        if document is None and dk_page.is_live(target):
            failed.append({"pid": target["pid"], "ref": target["ref"], "kind": target["kind"],
                           "watched": False,
                           "reason": target.get("detail_error") or "the detail answered 404"})

    targets = targets + from_ted
    live_all = [t for t in targets if dk_page.is_live(t) and documents.get(t["notice_id"]) is not None]
    closed = [_summary(t) for t in targets if t["kind"] in dk_page.CLOSE_KINDS]
    plans = [_summary(t) for t in targets if t["kind"] in ("plan", "consultation")]
    other = [_summary(t) for t in targets if t["kind"] == "other"]

    # ONE HOME PER PROCEDURE, EVEN WITHIN ONE WINDOW. A procedure republished or amended the same
    # day carries two notices; the newest is fetched and the other is named as superseded.
    newest, superseded = {}, []
    for t in sorted(live_all, key=lambda t: (t.get("published") or "", t.get("notice_version") or "")):
        if t["pid"] in newest:
            superseded.append(_summary(newest[t["pid"]]))
        newest[t["pid"]] = t
    live = list(newest.values())
    if limit:
        live = live[:limit]
    known = {t["pid"] for t in live}

    # THE WATCH LIST RIDES IN THE SAME PASS, past the gate. A watched tender is held by its
    # procedure id; the newest live notice of that procedure is the one read.
    for reference in (watch or []):
        reference = str(reference).strip()
        if not reference:
            continue
        try:
            row = dk_targets.one(reference)
        except Exception as exc:
            failed.append({"ref": reference, "pid": None, "kind": None, "watched": True,
                           "reason": "the portal did not answer: %s" % str(exc)[:150]})
            continue
        document = None
        if row is None:
            try:
                row, document = _watched_on_ted(reference)
            except Exception as exc:
                failed.append({"ref": reference, "pid": None, "kind": None, "watched": True,
                               "reason": "udbud.dk holds no live notice and TED did not answer: %s"
                                         % str(exc)[:150]})
                continue
        if row is None:
            failed.append({"ref": reference, "pid": None, "kind": None, "watched": True,
                           "reason": "no live notice for this procedure -- awarded, cancelled "
                                     "or withdrawn; look at the closes"})
            continue
        if row["pid"] in known:
            for t in live:
                if t["pid"] == row["pid"]:
                    t["watched"] = True
            continue
        row["watched"] = True
        if document is None:
            document = dk_page.detail(row["notice_id"], row["notice_version"], row["npn"])
        documents[row["notice_id"]] = document
        live.append(row)
        known.add(row["pid"])

    rules = policy_mod.load_policy(policy) if policy_mod is not None else None
    moves, delivered, gated, host_failures = [], [], [], []
    for target in live:
        pid = target["pid"]
        if rules is not None and not target.get("watched") and policy_mod.outside_scope(target, rules):
            # Named, never merely dropped: the whole row, so a person can overrule the gate the
            # next morning without the day being fetched again.
            gated.append({k: v for k, v in target.items() if k != "record"})
            continue
        home = os.path.join(out_root, "tenders", pid)
        previous_state = _read(os.path.join(home, "state.json"))
        try:
            done = dk_fetch.fetch(target, out_root, documents.get(target["notice_id"]),
                                  with_text=with_text,
                                  previous=_read(os.path.join(home, "procurement.json")))
        except Exception as exc:                       # one tender must not lose the day
            failed.append({"pid": pid, "ref": target["ref"], "kind": target["kind"],
                           "watched": bool(target.get("watched")),
                           "reason": "%s: %s" % (type(exc).__name__, str(exc)[:200])})
            continue
        if done.get("host_failed"):
            host_failures.append({"ref": target["ref"], "pid": pid, "host": done["documents_host"],
                                  "note": done["host_failed"]})
        record = None
        if changes_mod is not None and done.get("state") is not None:
            record = changes_mod.diff(previous_state, done["state"], date=folder, run_id=run_id)
        status = (record or {}).get("status") or ("new" if previous_state is None else "changed")
        moves.append({
            "pid": pid, "ref": target["ref"], "kind": target["kind"], "status": status,
            "watched": bool(target.get("watched")),
            "title": target["title"], "buyer": target["buyer"],
            "published": target["published"], "deadline": target.get("deadline"),
            "deadline_future": _future(target.get("deadline")),
            "value": target.get("value"), "currency": target.get("currency"),
            "cpv_main": target.get("cpv_main"),
            "documents_available": done["documents_available"],
            "documents_host": done["documents_host"],
            "link_verified": done["link_verified"],
            "documents": done["documents"], "withheld": done["withheld"],
            "uncatalogued": done["uncatalogued"],
            "moved": (record or {}).get("moves") or [],
        })
        delivered.append({
            "pid": pid, "ref": target["ref"], "kind": target["kind"], "status": status,
            "watched": bool(target.get("watched")), "home": "tenders/%s" % pid,
            "documents": done["documents"], "bytes": done["bytes"],
            "documents_available": done["documents_available"],
            "documents_host": done["documents_host"],
            "link_verified": done["link_verified"], "title": target["title"],
        })

    by_status = {}
    for row in moves:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    watched_count = sum(1 for row in moves if row["watched"])
    lost_window = [f for f in failed if not f.get("watched")]
    lost_watch = [f for f in failed if f.get("watched")]

    no_deadline = [m["ref"] for m in moves if m["kind"] == "tender" and not m["deadline"]]
    by_access = {}
    for row in delivered:
        by_access[row["documents_available"]] = by_access.get(row["documents_available"], 0) + 1

    complete = not lost_window and not discovery_failed and (proof is None or proof["ok"])
    common = {"date": folder, "window": {"from": date_from, "to": date_to}, "country": "DK",
              "run_id": run_id, "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "complete": complete, "discovery_failed": discovery_failed,
              "discovery_error": discovery_error}

    changes = dict(common, **{
        "schema": "day-changes/1",
        "counts": dict(by_status, tenders=len(moves), gated=len(gated), watched=watched_count,
                       closed=len(closed), plans=len(plans)),
        "gated": gated, "closed": closed, "plans": plans, "other": other,
        "superseded": superseded, "tenders": moves,
    })
    _write(os.path.join(out_root, folder, "changes.json"), changes)

    kinds = {}
    for t in targets:
        kinds[t["form_code"] or "?"] = kinds.get(t["form_code"] or "?", 0) + 1
    day = dict(common, **{
        "schema": "day/1", "source": "udbud.dk",
        "changes_path": "%s/changes.json" % folder, "tenders_path": "tenders",
        "coverage": {"index_count": index_count, "rows_held": len(raw),
                     "from_ted": len(from_ted), "by_form": kinds,
                     "live": len(live), "targets": len(live), "delivered": len(delivered),
                     "gated": len(gated), "failed": len(lost_window),
                     "watch_holes": len(lost_watch), "closed": len(closed), "plans": len(plans)},
        "counts": dict(by_status, tenders=len(delivered), gated=len(gated), watched=watched_count,
                       closed=len(closed), plans=len(plans),
                       documents=sum(t["documents"] for t in delivered),
                       bytes=sum(t["bytes"] for t in delivered)),
        "documents_available": by_access,
        "reconciliation": proof,
        "host_failures": host_failures,
        "unverified_links": [],
        "tenders_without_deadline": no_deadline,
        "lost": failed,
        "tenders": delivered,
        "shards": ["udbud-day-shard-1"],
    })
    _write(os.path.join(out_root, folder, "day.json"), day)   # last, as the contract says
    return day, changes


def one_tender(target, done, out_root, run_id=None):
    """A day file for one hand-fetched tender, in its own folder so it never overwrites a window's."""
    run_id = run_id or time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    folder = "%s-fetch-%s" % (time.strftime("%Y-%m-%d", time.gmtime()), str(done["pid"])[:8])
    row = {"pid": done["pid"], "ref": done["ref"], "kind": done["kind"], "status": "fetched",
           "watched": True, "home": "tenders/%s" % done["pid"], "documents": done["documents"],
           "bytes": done["bytes"], "documents_available": done["documents_available"],
           "documents_host": done["documents_host"], "link_verified": done["link_verified"],
           "title": done["title"]}
    common = {"date": folder, "window": None, "country": "DK", "run_id": run_id,
              "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "complete": True, "discovery_failed": False}
    _write(os.path.join(out_root, folder, "changes.json"),
           dict(common, schema="day-changes/1", counts={"tenders": 1}, gated=[], closed=[],
                tenders=[row]))
    _write(os.path.join(out_root, folder, "day.json"),
           dict(common, schema="day/1", source="udbud.dk", changes_path="%s/changes.json" % folder,
                tenders_path="tenders", coverage={"targets": 1, "delivered": 1},
                counts={"tenders": 1, "documents": done["documents"], "bytes": done["bytes"]},
                lost=[], tenders=[row], shards=["udbud-fetch"]))
    return row, folder


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("date")
    ap.add_argument("--to", default=None)
    ap.add_argument("--out", default="work/DK")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--policy", default=None)
    args = ap.parse_args(argv)
    day, _ = run(args.date, args.out, args.limit, policy=args.policy, date_to=args.to)
    print(json.dumps(day["coverage"], ensure_ascii=False))
    return 0 if day["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
