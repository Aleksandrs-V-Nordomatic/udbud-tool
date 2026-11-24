"""A Danish notice TED holds and udbud.dk does not, in the shape the day reads.

WHY THIS EXISTS. udbud.dk pulls every Danish EU notice from TED by design, and on most days it does:
2026-09-02 40 = 40, 2026-11-13 36 = 36. On 2026-11-23 it held 28 of 30. Both missing notices were
open competitions (811676-2026, 812089-2026), and udbud.dk answered nothing for their procedure id
and nothing for their notice id the next morning. A day that only reports the gap loses the tender.

THE KEY IS THE SAME. TED's `procedure-identifier` is BT-04, which udbud.dk prints as *Identifikator
for proceduren*. So when udbud.dk catches up, its notice lands in the home this one opened.

THE FACTS COME FROM THE SEARCH API AND THE TEXT FROM TED'S OWN DANISH RENDERING. The rendering is
what `doc/notice.md` quotes; when it does not answer, the home still holds the buyer's description.
"""
import html as htmlmod
import json
import re
import urllib.parse
import urllib.request

import dk_page
import net

SEARCH = "https://api.ted.europa.eu/v3/notices/search"
VIEW = "https://ted.europa.eu/da/notice/-/detail/%s"
RENDERED = "https://ted.europa.eu/da/notice/%s/html"

FIELDS = ["publication-number", "publication-date", "notice-identifier", "notice-version",
          "procedure-identifier", "internal-identifier-proc", "form-type", "notice-type",
          "notice-subtype", "change-notice-version-identifier", "title-proc", "description-proc",
          "description-lot", "buyer-name", "buyer-identifier", "main-classification-proc",
          "classification-cpv", "deadline-receipt-tender-date-lot",
          "deadline-receipt-tender-time-lot", "deadline-receipt-request-date-lot",
          "deadline-receipt-request-time-lot", "estimated-value-proc", "estimated-value-cur-proc",
          "document-url-lot", "place-of-performance", "place-of-performance-city-lot",
          "identifier-lot"]

PROCEDURE_ID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)


def search(query, timeout=60):
    """The notices one query answers, as TED's own records. One page: a query here names a notice."""
    body = {"query": query, "fields": FIELDS, "limit": 50, "page": 1}
    request = urllib.request.Request(SEARCH, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json",
                                              "User-Agent": dk_page.UA})
    answer, _ = net.open_url(request, timeout=timeout, log=dk_page.log,
                             parse=lambda b: json.loads(b.decode("utf-8")))
    return answer.get("notices") or []


def _list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _texts(value):
    """Every language of a TED text, Danish first, as one flat list of strings."""
    if not isinstance(value, dict):
        return [str(v).strip() for v in _list(value) if v]
    languages = sorted(value, key=lambda code: (code != "dan", code != "eng", code))
    return [str(v).strip() for code in languages for v in _list(value[code]) if v]


def _first(value):
    return next(iter(_texts(value)), None)


def deadlines(dates, times):
    """`2027-01-22+01:00` with `10:00:00+01:00` -> `2027-01-22T10:00:00+01:00`, earliest first.

    A date TED gives no time for stays a date. An hour is never made up.
    """
    dates, times = _list(dates), _list(times)
    paired = len(dates) == len(times) and all(times)
    out = set()
    for n, date in enumerate(dates):
        day = str(date)[:10]
        out.add("%sT%s" % (day, times[n]) if paired else day)
    return sorted(out)


def _amount(text):
    try:
        return float(text) if text not in (None, "") else None
    except (TypeError, ValueError):
        return None


def notice(record):
    """A TED record in the shape `dk_page.notice` plus `dk_page.enrich` give a udbud.dk row."""
    number = str(record.get("publication-number") or "").strip()
    head, _, year = number.partition("-")
    npn = "%s-%s" % (head.zfill(8), year) if year else number
    form = record.get("form-type")
    kind = dk_page.KINDS.get(form, "other")
    if kind == "tender" and record.get("change-notice-version-identifier"):
        kind = "amendment"
    tender = deadlines(record.get("deadline-receipt-tender-date-lot"),
                       record.get("deadline-receipt-tender-time-lot"))
    request = deadlines(record.get("deadline-receipt-request-date-lot"),
                        record.get("deadline-receipt-request-time-lot"))
    every = sorted(set(tender + request))
    titles = list(dict.fromkeys(_texts(record.get("title-proc"))))
    described = list(dict.fromkeys(_texts(record.get("description-proc"))
                                   + _texts(record.get("description-lot"))))
    codes = list(dict.fromkeys(str(c) for c in _list(record.get("main-classification-proc"))
                               + _list(record.get("classification-cpv")) if c))
    value = _amount(_first(record.get("estimated-value-proc")))
    links = list(dict.fromkeys(u for u in _list(record.get("document-url-lot")) if u))
    procedure_id = (_first(record.get("procedure-identifier")) or "").lower() or None
    version = record.get("notice-version")
    notice_id = record.get("notice-identifier") or "ted-%s" % number
    buyer_id = _first(record.get("buyer-identifier"))
    intern = _first(record.get("internal-identifier-proc"))
    # The same three steps as `dk_page.enrich`, so both sources open one home.
    if procedure_id:
        pid = procedure_id
    elif buyer_id and intern:
        pid = "int-%s-%s" % (buyer_id, re.sub(r"[^\w.-]+", "_", intern))
    else:
        pid = "notice-%s" % notice_id
    return {
        "pid": pid,
        "procedure_id": procedure_id,
        "intern_id": intern,
        "notice_id": notice_id,
        "notice_version": "%02d" % version if isinstance(version, int) else version,
        "npn": npn, "ref": npn, "kind": kind,
        "form_code": form, "form": record.get("notice-type"),
        "subtype": record.get("notice-type"), "subtype_code": record.get("notice-subtype"),
        "eu": True,
        "title": titles[0] if titles else None, "titles": " ".join(titles),
        "description": "\n\n".join(described) or None,
        "buyer": _first(record.get("buyer-name")),
        "buyers": list(dict.fromkeys(_texts(record.get("buyer-name")))),
        "buyer_id": buyer_id,
        "published": str(record.get("publication-date") or "")[:10] or None,
        "deadline": every[0] if every else None, "deadlines": every,
        "deadline_tender": tender[0] if tender else None,
        "deadline_request": request[0] if request else None,
        "value": value,
        "currency": _first(record.get("estimated-value-cur-proc")) if value is not None else None,
        "cpv_main": codes[0] if codes else None, "cpv": codes, "cpv_name": None,
        "expected_start": None,
        "link": VIEW % number, "link_verified": True,
        "documents_urls": links, "documents_url": links[0] if links else None,
        "documents_host": urllib.parse.urlparse(links[0]).netloc.lower() if links else None,
        "lots": len(_list(record.get("identifier-lot"))) or None,
        "nuts": list(dict.fromkeys(str(p) for p in _list(record.get("place-of-performance"))
                                   if re.match(r"^DK\d", str(p)))),
        "place": list(dict.fromkeys(_texts(record.get("place-of-performance-city-lot")))),
        "source": "ted.europa.eu", "source_kind": "TED",
        "record": record,
    }


_BLOCK = re.compile(r"</(?:div|p|li|tr|h\d|section)>|<br\s*/?>", re.I)


def plain(html):
    """TED's rendering as lines of text: no styles, no tags, one line per block."""
    html = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", html or "")
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", _BLOCK.sub("\n", html)))
    lines = (re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def document(target):
    """The stand-in for udbud.dk's detail: the record TED gave and its Danish text, if it answers."""
    number = str((target.get("record") or {}).get("publication-number") or "")
    try:
        text = plain(net.get_text(RENDERED % number, headers={"User-Agent": dk_page.UA},
                                  log=dk_page.log))
    except Exception as exc:
        dk_page.log("  TED's rendering of %s did not answer: %s" % (number, str(exc)[:120]))
        text = ""
    return {"source": "ted.europa.eu", "record": target.get("record"), "text": text}


def one(number):
    """`(target, document)` of one publication number, or `(None, None)` when TED has none."""
    for record in search("publication-number=%s" % number):
        target = notice(record)
        return target, document(target)
    return None, None


def procedure(reference):
    """`(target, document)` of a procedure's newest notice when it is live, else `(None, None)`."""
    reference = str(reference or "").strip()
    if reference.upper().startswith("DK:"):
        reference = reference[3:]
    if not PROCEDURE_ID.match(reference):
        return None, None
    found = [notice(r) for r in search("procedure-identifier=%s" % reference)]
    found.sort(key=lambda t: (t.get("published") or "", t.get("npn") or ""), reverse=True)
    if not found or not dk_page.is_live(found[0]):
        return None, None
    return found[0], document(found[0])
