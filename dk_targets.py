"""Which notices a window holds, proved against the portal's own count.

THE COUNT IS THE CONTROL. Every page carries `totaltAntalResultater`, and a window is whole only
when the rows held equal it. Measured on 2026-09-02: 42 = 42, one page. A short window here is
not a quiet day; it is a crawl that broke, and it must say so.

EVERY ROW MUST FALL INSIDE THE WINDOW IT WAS ASKED FOR. The filter is a pair of Danish dates and
the row carries its own `publiceringsdato`; a row outside the window means the filter was not
applied, which is the shape a dropped filter takes on every portal in this family.

THE DATES ARE DANISH CALENDAR DATES, NOT UTC. udbud.dk filters and prints `publiceringsdato` as
a date in Copenhagen. A night that asks for "yesterday" asks for yesterday in Denmark.

WEEKENDS ARE EMPTY. Three weekend days of three measured in November carried 0 notices, and so
did the Sunday 2026-08-30 in September. So an empty window that covers only Saturday and Sunday
is a normal empty day, and an empty window over a weekday is a broken crawl until shown
otherwise. Public holidays look like weekdays here and will read as a failed discovery once a
year each -- the honest direction to be wrong in.

    python3 dk_targets.py 2026-09-02
"""
import argparse
import datetime
import sys

import dk_page


class Truncated(RuntimeError):
    """The portal said the window holds more rows than it handed out."""


class OutsideWindow(RuntimeError):
    """A row came back from outside the window it was asked for: the filter was not applied."""


def days(date_from, date_to):
    a = datetime.date.fromisoformat(date_from)
    b = datetime.date.fromisoformat(date_to or date_from)
    if b < a:
        raise ValueError("the window ends (%s) before it starts (%s)" % (b, a))
    return [(a + datetime.timedelta(n)).isoformat() for n in range((b - a).days + 1)]


def publishing_days(date_from, date_to):
    """The days in the window Denmark publishes on: Monday to Friday."""
    return [d for d in days(date_from, date_to)
            if datetime.date.fromisoformat(d).weekday() < 5]


def rows(date_from, date_to=None):
    """`(count, rows)` for the window: the portal's own total and every row it holds."""
    date_to = date_to or date_from
    inside = set(days(date_from, date_to))
    held, page, total = [], 1, None
    while True:
        answer = dk_page.search(date_from, date_to, page=page)
        total = answer.get("totaltAntalResultater")
        got = answer.get("resultatElementDtoList") or []
        for row in got:
            published = dk_page.danish_date((row.get("dataDa") or {}).get("publiceringsdato"))
            if published not in inside:
                raise OutsideWindow("asked for %s..%s and got a row published %s -- the date "
                                    "filter was not applied" % (date_from, date_to, published))
        held += got
        if not got or total is None or len(held) >= total:
            break
        page += 1
    if total is None or len(held) != total:
        raise Truncated("the portal counts %s rows in %s..%s and handed out %d"
                        % (total, date_from, date_to, len(held)))
    return total, held


def window(date_from, date_to=None):
    return [dk_page.notice(r) for r in rows(date_from, date_to)[1]]


def procedure(reference):
    """Every notice the portal holds for a procedure, newest first.

    The free-text search matches a `procedureId` and a `noticeId` exactly -- measured: a
    procedure id returned its two notices, a notice id its one -- and does NOT match a TED number,
    which it splits into words. So a watched tender is held by its procedure id.
    """
    reference = str(reference or "").strip()
    if reference.upper().startswith("DK:"):
        reference = reference[3:]
    if not reference:
        return []
    answer = dk_page.search(text=reference, size=dk_page.PAGE)
    found = [dk_page.notice(r) for r in answer.get("resultatElementDtoList") or []]
    found.sort(key=lambda t: (t.get("published") or "", t.get("notice_version") or ""),
               reverse=True)
    return found


def one(reference):
    """The newest live notice of a procedure, enriched from its detail, or None.

    A notice id finds one notice; its procedure is then asked for again, so an amendment
    published since is the one returned.
    """
    candidates = procedure(reference)
    for target in candidates:
        document = dk_page.detail(target["notice_id"], target["notice_version"], target["npn"])
        dk_page.enrich(target, document)
        if target.get("procedure_id") and target["procedure_id"].lower() != str(reference).lower():
            newer = [t for t in procedure(target["procedure_id"]) if dk_page.is_live(t)]
            if newer and newer[0]["notice_id"] != target["notice_id"]:
                target = newer[0]
                dk_page.enrich(target, dk_page.detail(target["notice_id"],
                                                      target["notice_version"], target["npn"]))
        if dk_page.is_live(target):
            return target
    return None


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("date")
    ap.add_argument("--to", default=None)
    args = ap.parse_args(argv)
    total, held = rows(args.date, args.to)
    kinds = {}
    for r in held:
        k = dk_page.kind_of(r)
        kinds[k] = kinds.get(k, 0) + 1
    print("%s..%s: %d of %d rows held  %s" % (args.date, args.to or args.date, len(held), total, kinds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
