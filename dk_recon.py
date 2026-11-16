"""The coverage controls: did the window arrive whole, and does it hold every Danish EU notice?

Two controls, both hard.

1 · ROWS HELD == THE PORTAL'S OWN COUNT. `totaltAntalResultater` is asserted by `dk_targets.rows`
    on every window; this report carries the two numbers so `day.json` shows them.

2 · THE EU NOTICES MATCH TED BOTH WAYS. Every Danish notice above the threshold is published on
    TED first and pulled into udbud.dk by design, and its `noticePublicationNumber` IS the TED
    publication number. So for each day the set of TED numbers whose buyer is Danish must equal
    the set of numbers udbud.dk holds. Measured: 2026-09-02 40 = 40, 2026-11-13 36 = 36, and three
    September days exact. A difference either way means a notice one side has and the other does
    not -- a crawl that lost a row, or a notice udbud.dk never pulled.

    A national notice has no TED number and is outside this control by construction: the count
    control is what holds it.

    python3 dk_recon.py 2026-09-02
"""
import argparse
import json
import sys
import urllib.request

import dk_page
import dk_targets
import net

TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"
TED_PAGE = 100


def _norm(number):
    return str(number or "").strip().lstrip("0")


def ted_numbers(day, timeout=60):
    """Every TED publication number with a Danish buyer published on `day`."""
    numbers, page = set(), 1
    while True:
        body = {"query": "buyer-country=DNK AND publication-date=%s" % day.replace("-", ""),
                "fields": ["publication-number"], "limit": TED_PAGE, "page": page}
        request = urllib.request.Request(TED_SEARCH, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "Accept": "application/json",
                                                  "User-Agent": dk_page.UA})
        answer, _ = net.open_url(request, timeout=timeout, log=dk_page.log,
                                 parse=lambda b: json.loads(b.decode("utf-8")))
        got = answer.get("notices") or []
        numbers |= {_norm(n.get("publication-number")) for n in got}
        total = answer.get("totalNoticeCount") or 0
        if not got or len(numbers) >= total:
            return numbers
        page += 1


def run(date_from, date_to=None, rows=None, count=None, ted=True):
    """The report. `rows` and `count` are the window already held, so nothing is asked twice."""
    date_to = date_to or date_from
    problems = []
    if rows is None:
        try:
            count, rows = dk_targets.rows(date_from, date_to)
        except (dk_targets.Truncated, dk_targets.OutsideWindow) as exc:
            return {"ok": False, "window": {"from": date_from, "to": date_to},
                    "index_count": None, "rows_held": None, "ted": None, "problems": [str(exc)]}
    held = len(rows)
    if count is None or held != count:
        problems.append("rows held %d, the portal counts %s" % (held, count))

    per_day = []
    if ted:
        for day in dk_targets.days(date_from, date_to):
            ours = {_norm(r.get("noticePublicationNumber")) for r in rows
                    if r.get("noticePublicationNumber")
                    and dk_page.danish_date((r.get("dataDa") or {}).get("publiceringsdato")) == day}
            try:
                theirs = ted_numbers(day)
            except Exception as exc:
                per_day.append({"day": day, "error": "%s: %s" % (type(exc).__name__, str(exc)[:160])})
                problems.append("TED did not answer for %s" % day)
                continue
            only_ours, only_ted = sorted(ours - theirs), sorted(theirs - ours)
            per_day.append({"day": day, "udbud": len(ours), "ted": len(theirs),
                            "only_udbud": only_ours, "only_ted": only_ted})
            if only_ours or only_ted:
                problems.append("%s: %d only on udbud.dk, %d only on TED"
                                % (day, len(only_ours), len(only_ted)))
    national = sum(1 for r in rows if not r.get("noticePublicationNumber"))
    return {"ok": not problems, "window": {"from": date_from, "to": date_to},
            "index_count": count, "rows_held": held, "national": national,
            "ted": per_day if ted else None, "problems": problems}


def line(report):
    if report.get("index_count") is None and report.get("problems"):
        return "coverage: %s" % "; ".join(report["problems"])
    ted = report.get("ted") or []
    eu = sum(d.get("udbud", 0) for d in ted)
    tedn = sum(d.get("ted", 0) for d in ted)
    return ("coverage %s: rows %s of %s, national %s, EU %d vs TED %d%s"
            % ("OK" if report["ok"] else "SHORT", report["rows_held"], report["index_count"],
               report.get("national"), eu, tedn,
               "" if report["ok"] else " -- " + "; ".join(report["problems"])))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("date")
    ap.add_argument("--to", default=None)
    args = ap.parse_args(argv)
    report = run(args.date, args.to)
    print(line(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
