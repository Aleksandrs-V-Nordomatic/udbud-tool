"""Does a GitHub runner address get the same Denmark this laptop gets?

One draw: the udbud.dk count for two known days, one detail, TED's count for a known day, and the
first bytes of one public file on every anonymous document host the radar will read. Each check
compares against a number measured from the laptop, because every host here can answer 200 with
the wrong thing. Only read calls: Dalux gets IsTenderPublic and nothing else, EU-Supply only its
public documents page (never /app/docmgmt, which its robots.txt disallows).

    python3 tools/dk_egress.py      -> one line per check, exit 1 if any check differs

The hosts' answers can change as tenders close -- a list grows by a corrigendum, a file is
withdrawn -- so a red draw is a reason to look, and the numbers are re-measured when one is.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docsource import dalux  # noqa: E402

UA = "Mozilla/5.0 (compatible; eis-tool)"
# Measured from the laptop on 2026-11-16. A runner that gets anything else has found a difference.
MEASURED = {"udbud_2026-09-02": 42, "udbud_2026-11-13": 39, "detail_has_procedure": True,
            "ted_2026-11-13": 36, "ethics_list": 39, "ethics_file": "25504446",
            "dalux_public": True, "dalux_file": "25504446", "udbud_file": "504b0304",
            "byggeweb_list": 24, "eusupply_page": True, "mercell_names": 10}


def req(url, body=None, headers=None, first=None, timeout=40):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if isinstance(body, (dict, list)):
        h["Content-Type"] = "application/json"
        body = json.dumps(body).encode()
    h.update(headers or {})
    r = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, x.read(first) if first else x.read()
    except urllib.error.HTTPError as ex:
        return ex.code, b""
    except Exception as ex:
        return "ERR " + type(ex).__name__, b""


def udbud_total(day):
    st, b = req("https://udbud.dk/soegning/public/soegeresultat", {
        "pagineringDto": {"aktuelSide": 1, "maksElementer": 100,
                          "sorteringFelt": "PUBLIKATION_DATO", "retning": "Desc"},
        "filterDto": {"publikationDatoFra": day, "publikationDatoTil": day},
        "udbudStatusFilter": "ALLE"})
    if st != 200:
        return st, None
    j = json.loads(b)
    return st, j.get("totaltAntalResultater"), j.get("resultatElementDtoList") or []


def ted_total(day):
    st, b = req("https://api.ted.europa.eu/v3/notices/search", {
        "query": "buyer-country=DNK AND publication-date=%s" % day.replace("-", ""),
        "fields": ["publication-number"], "limit": 1, "page": 1})
    return st, (json.loads(b).get("totalNoticeCount") if st == 200 else None)


def dalux_public(tid):
    # The reader's own call, so the probe cannot pass with a client the reader does not send.
    try:
        answer = dalux._call("IsTenderPublic", {"tenderLinkIdentifier": tid}, tid)
        return 200, answer.get("value")
    except Exception as exc:
        return "ERR " + type(exc).__name__, None


def magic(url):
    st, b = req(url, first=4)
    return st, b.hex()


def main(expect=None):
    # The expected numbers are an argument, not sys.argv read at import: `eis_tool.py probe` imports
    # this module, and its argv[1] is the word "probe".
    expect = MEASURED if expect is None else expect
    got = {}
    for day in ("2026-09-02", "2026-11-13"):
        st, total, rows = (udbud_total(day) + ([],))[:3]
        got["udbud_" + day] = total
        if day == "2026-09-02" and rows:
            r = next((x for x in rows if x.get("noticePublicationNumber")), rows[0])
            st, b = req("https://udbud.dk/soegning/visning/%s/%s?noticePublicationNumber=%s"
                        % (r["noticeId"], r["noticeVersion"], r.get("noticePublicationNumber") or ""))
            got["detail_has_procedure"] = st == 200 and b"Identifikator for proceduren" in b
    got["ted_2026-11-13"] = ted_total("2026-11-13")[1]

    st, b = req("https://www.ethics.dk/ethics/publicTenderDocs/43f506cc-638d-447a-9ee7-0edbc8a5c229")
    got["ethics_list"] = len(json.loads(b).get("tenderDocs", [])) if st == 200 else st
    got["ethics_file"] = magic("https://www.ethics.dk/ethics/publicTenderDoc/43f506cc-638d-447a-9ee7-"
                               "0edbc8a5c229/2b540118-33c3-4028-b5d5-4d615847a9be/download")[1]
    got["dalux_public"] = dalux_public("TID-505330742574720785")[1]
    got["dalux_file"] = magic("https://node1.field.dalux.com/service/web/downloadfile/"
                              "TID-505330742574720785/areafilerevision-511089161642442757/")[1]
    got["udbud_file"] = magic("https://api.udbud.dk/udbud/vedhaeftning/0750b704-c585-4a1c-85b5-"
                              "de15df4d38e4/01/fil/553db89c-6a4f-44a4-a4d8-50519bfe6237/"
                              "Requirement_specification_for__Riding_Breeches.DOCX")[1]
    st, b = req("https://www.byggeweb.dk/controller",
                b"cmd=tender.public.documents&tn=TN816672A",
                {"Content-Type": "application/x-www-form-urlencoded"})
    got["byggeweb_list"] = b.count(b'<table class="filename') if st == 200 else st
    st, b = req("https://eu.eu-supply.com/ctm/Supplier/PublicPurchase/462343/0/0?returnUrl=&b=")
    got["eusupply_page"] = st == 200 and b"publicpurchase_docs.asp" in b
    st, b = req("https://permalink.mercell.com/292116047.aspx")
    got["mercell_names"] = b.count(b"_tdDownload") if st == 200 else st

    ip = req("https://api.ipify.org")[1].decode() or "?"
    bad = [k for k, v in expect.items() if got.get(k) != v]
    print("ip %-16s %s" % (ip, json.dumps(got, sort_keys=True)))
    for k in bad:
        print("::error::%s is %r, expected %r" % (k, got.get(k), expect[k]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(json.loads(sys.argv[1]) if len(sys.argv) > 1 else None))
