"""What udbud.dk says about one notice: the search row, the detail, and the facts a home is built from.

ONE SOURCE, OPEN, NO ACCOUNT. `POST /soegning/public/soegeresultat` is the portal's own search
backend, and its terms allow `udbudsformidlere` to read it round the clock. Every Danish notice
above the threshold reaches it from TED by design (`hentOgPersisterFraTed`), and the national
ones are published there directly. The official ERST API (`api.udbud.dk/udbud/ekstern-data`)
answers 401 without a registered client and is the fallback, not the route.

THE ROW IS ENOUGH TO GATE, AND THE DETAIL IS NEEDED TO KEY. The search row carries the title in
Danish and English, the buyer, the main CPV code with its name, the deadlines and the buyer's own
description -- everything the recall gate reads. It does not carry the procedure. That is BT-04,
`Identifikator for proceduren`, and it is printed only in the detail's `htmlDA`. So every row
gets its detail: about forty requests on a busy day, on an endpoint that answered 174 of 174.

THE KEY IS `procedureId`, NEVER `noticeId`. Measured over 474 competition notices in forty days,
51 procedures carried more than one notice -- an amendment, a republication, a second phase --
and every one of those notices has its own `noticeId`. Keyed on `noticeId`, one tender becomes
two homes and the board two cards.

    python3 dk_page.py 2026-09-02          # the window's rows, one line each, nothing fetched
"""
import argparse
import datetime
import html as htmlmod
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import net

BASE = "https://udbud.dk"
SEARCH = BASE + "/soegning/public/soegeresultat"
DETAIL = BASE + "/soegning/visning/%s/%s?noticePublicationNumber=%s"
# The page a person opens. It answers 200 with the same shell for a notice that exists and one
# that does not, so it is never used to check anything -- the detail call above is.
VIEW = BASE + "/detaljevisning?noticeId=%s&noticeVersion=%s&noticePublicationNumber=%s"

UA = "Mozilla/5.0 (compatible; eis-tool)"
PAGE = 100                        # the largest page the service hands out
DETAIL_PACE = 0.2                 # seconds between detail calls; ~1 500 in 90 minutes never slowed it

# `formulartypeKode` -> what the radar does with the notice. Only a competition is something a
# company can still bid on; the rest are recorded and never fetched.
KINDS = {
    "competition": "tender",
    "change": "amendment",
    "result": "award",
    "dir-awa-pre": "award",        # a direct award announced in advance: decided, not biddable
    "cont-modif": "modification",
    "planning": "plan",
    "preplanning": "plan",
    "consultation": "consultation",
}
LIVE_KINDS = ("tender", "amendment")
CLOSE_KINDS = ("award", "modification")

NOTICE_DOCUMENT = "doc/notice.md"


def log(message):
    print(message, file=sys.stderr, flush=True)


def _post(body, timeout=60):
    request = urllib.request.Request(
        SEARCH, data=json.dumps(body).encode("utf-8"),
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 "Accept": "application/json"})
    parsed, _ = net.open_url(request, timeout=timeout, log=log,
                             parse=lambda b: json.loads(b.decode("utf-8")))
    return parsed


def search(date_from=None, date_to=None, page=1, text=None, size=PAGE):
    """One page of the search. Dates are Danish publication dates, YYYY-MM-DD."""
    body = {"pagineringDto": {"aktuelSide": page, "maksElementer": size,
                              "sorteringFelt": "PUBLIKATION_DATO", "retning": "Desc"},
            "filterDto": {},
            "udbudStatusFilter": "ALLE"}
    if date_from:
        body["filterDto"] = {"publikationDatoFra": date_from, "publikationDatoTil": date_to or date_from}
    if text:
        body["fritekstQuery"] = text
    return _post(body)


def detail(notice_id, version, npn, timeout=60):
    """The notice as the portal renders it, or None when the portal says there is none.

    `noticePublicationNumber` must be exactly what the notice carries: empty for a national
    notice, the TED number for an EU one. Anything else is a 404, and a 404 here is honest.
    """
    url = DETAIL % (notice_id, version, urllib.parse.quote(npn or ""))
    try:
        parsed, _ = net.get_json(url, headers={"User-Agent": UA, "Accept": "application/json"},
                                 timeout=timeout, log=log)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    time.sleep(DETAIL_PACE)
    return parsed


def danish_date(text):
    """`02-09-2026` -> `2026-09-02`. None when it is not that shape."""
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", str(text or "").strip())
    return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else None


def kind_of(row):
    data = row.get("dataDa") or {}
    kind = KINDS.get(data.get("formulartypeKode"), "other")
    if kind == "tender" and data.get("erAendring"):
        return "amendment"
    return kind


def is_live(target):
    return target.get("kind") in LIVE_KINDS


def _value(text):
    try:
        return float(text) if text not in (None, "") else None
    except (TypeError, ValueError):
        return None


def notice(row):
    """A search row in the family's shape. `pid` stays None until the detail has been read."""
    da = row.get("dataDa") or {}
    en = row.get("dataEn") or {}
    npn = row.get("noticePublicationNumber") or ""
    deadlines = sorted(d for d in (da.get("tidsfrister") or []) if d)
    value = _value(da.get("anslaaetVaerdi"))
    return {
        "pid": None,
        "notice_id": row.get("noticeId"),
        "notice_version": row.get("noticeVersion"),
        "npn": npn,
        # What a person quotes: the TED number on an EU notice. A national notice has none, and
        # its `noticeId` is the only handle there is.
        "ref": npn or row.get("noticeId"),
        "kind": kind_of(row),
        "form_code": da.get("formulartypeKode"),
        "form": da.get("formulartype"),
        "subtype": da.get("bkSubType"),
        "subtype_code": da.get("bkSubTypeKode"),
        "eu": bool(npn),
        "title": da.get("titel") or en.get("titel"),
        # Both languages added together, never chosen between: a buyer writes different words in
        # each, and the gate reads them all.
        "titles": " ".join(dict.fromkeys(t for t in (da.get("titel"), en.get("titel")) if t)),
        "description": da.get("beskrivelse") or en.get("beskrivelse"),
        "buyer": da.get("ordregiver"),
        "buyers": da.get("alleOrdregivere") or [],
        "buyer_id": (da.get("ordregiverIdDatavasket") or da.get("ordregiverId") or "").strip() or None,
        "published": danish_date(da.get("publiceringsdato")),
        "deadline": deadlines[0] if deadlines else None,
        "deadlines": deadlines,
        "value": value,
        # `anslaaetVaerdi` absent is not zero, and a value with no currency is not a value.
        "currency": da.get("anslaaetVaerdiValuta") if value is not None else None,
        "cpv_main": da.get("cpvKode"),
        "cpv": [da["cpvKode"]] if da.get("cpvKode") else [],
        "cpv_name": da.get("cpvTitel"),
        "expected_start": da.get("forventetOpstart"),
        "link": VIEW % (row.get("noticeId"), row.get("noticeVersion"), urllib.parse.quote(npn)),
        "record": row,
    }


# The detail's notice is eForms rendered to HTML: nested <section>s, each a label and a value.
_LABELLED = r'<span class="label">%s</span>\s*<span class="text">[^<]*</span>\s*<span class="value">([^<]+)</span>'


def labelled(html, label):
    m = re.search(_LABELLED % re.escape(label), html or "")
    return htmlmod.unescape(m.group(1)).strip() if m else None


def enrich(target, document):
    """Add what only the detail knows, and choose the home's key.

    The key is the procedure. Where the notice prints none -- never seen in 174 of 174, but the
    portal publishes old forms too -- it falls back to the buyer and its internal id, and then to
    the notice itself, so a home is never `None` and never shared by two procedures.
    """
    html = (document or {}).get("htmlDA") or ""
    summary = (document or {}).get("opsummeringDA") or {}
    procedure = labelled(html, "Identifikator for proceduren")
    intern = labelled(html, "Intern ID")
    target["procedure_id"] = procedure
    target["intern_id"] = intern
    if procedure:
        target["pid"] = procedure.lower()
    elif target.get("buyer_id") and intern:
        target["pid"] = "int-%s-%s" % (target["buyer_id"], re.sub(r"[^\w.-]+", "_", intern))
    else:
        target["pid"] = "notice-%s" % target["notice_id"]
    target["link_verified"] = document is not None
    documents = [u for u in (summary.get("udbudsDokumenter") or []) if u]
    target["documents_urls"] = documents
    target["documents_url"] = documents[0] if documents else None
    target["documents_host"] = (urllib.parse.urlparse(documents[0]).netloc.lower()
                                if documents else None)
    target["lots"] = summary.get("antalLots")
    target["nuts"] = summary.get("udforelsesstedNutsCode") or []
    target["place"] = summary.get("udforelsesstedBy") or []
    target["deadline_tender"] = (summary.get("tilbudsfrister") or [None])[0]
    target["deadline_request"] = (summary.get("deltagelsefrister") or [None])[0]
    target["source_kind"] = summary.get("indholdsType")
    return target


class _Text(HTMLParser):
    """The rendered notice as Markdown: a numbered section is a heading, a leaf is `label: value`."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.buf, self.lines = 0, [], []

    def _flush(self):
        text = "".join(self.buf)
        text = "\n".join(re.sub(r"[ \t\r\f\v\n \xa0]+", " ", part).strip()
                         for part in text.split("\x00"))
        text = text.strip()
        self.buf = []
        if not text:
            return
        if re.match(r"^\d+(\.\d+)*\s", text):
            self.lines.append("")
            self.lines.append("%s %s" % ("#" * min(self.depth + 1, 6), text))
            self.lines.append("")
        else:
            self.lines.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "section":
            self._flush()
            self.depth += 1
        elif tag == "br":
            self.buf.append("\x00")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.buf.append("\x00")

    def handle_endtag(self, tag):
        if tag == "section":
            self._flush()
            self.depth -= 1

    def handle_data(self, data):
        self.buf.append(data)


def html_markdown(html):
    parser = _Text()
    parser.feed(html or "")
    parser._flush()
    out = "\n".join(parser.lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


def notice_markdown(target, document):
    """`doc/notice.md`: the facts as labelled lines, the description exactly as the index holds it,
    then the whole notice as the portal renders it in Danish.

    For most Danish tenders this file IS the readable artefact -- the documents sit behind a
    supplier login on two in three of them -- so a quote a card makes from the notice has to be
    findable here byte for byte.
    """
    lines = ["# %s" % (target.get("title") or ""), ""]
    for label, value in (
            ("Ordregiver", target.get("buyer")),
            ("Offentliggjort", target.get("published")),
            ("Frist", target.get("deadline")),
            ("Bekendtgørelse", target.get("form")),
            ("Type", target.get("subtype")),
            ("CPV", " ".join(filter(None, [target.get("cpv_main"), target.get("cpv_name")]))),
            ("Anslået værdi", ("%s %s" % (target["value"], target.get("currency") or ""))
             if target.get("value") is not None else None),
            ("Procedure", target.get("procedure_id")),
            ("Udbudsdokumenter", target.get("documents_url")),
            ("Link", target.get("link"))):
        if value:
            lines.append("- %s: %s" % (label, value))
    lines += ["", "## Beskrivelse", "", target.get("description") or "", ""]
    html = (document or {}).get("htmlDA")
    if html:
        lines += ["## Bekendtgørelsen", "", html_markdown(html)]
    text = (document or {}).get("text")
    if text and not html:                      # TED's rendering, for a notice udbud.dk lacks
        lines += ["## Bekendtgørelsen", "", text]
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("date")
    args = ap.parse_args(argv)
    page = search(args.date, args.date)
    for row in page.get("resultatElementDtoList") or []:
        t = notice(row)
        print("%-12s %-14s %s | %s" % (t["kind"], t["ref"][:14], (t["title"] or "")[:70], t["buyer"]))
    print("total %s" % page.get("totaltAntalResultater"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
