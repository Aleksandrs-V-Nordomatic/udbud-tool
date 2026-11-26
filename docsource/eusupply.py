"""EU-Supply: names only, until there is an account.

    ctm/Supplier/PublicPurchase/{PID}/0/0          -> a page linking the documents page
    app/rfq/publicpurchase_docs.asp?PID=&LID=       -> the names, public and gated

The documents page lists the public files as `DownloadPublicDocument('{DVID}','sDoc_..','{LID}')`
and the rest under "Available after expression of interest". On 16 Nov 2026 public files existed
on 6 of 56 tenders; the other 852 files were behind the expression of interest, which the buyer
is told about.

NOTHING IS DOWNLOADED FROM HERE, NOT EVEN THE PUBLIC FILES. They are served from
`/app/docmgmt/downloadPublicDocument.asp`, and EU-Supply's robots.txt disallows `/app/docmgmt`.
Until EU-Supply says otherwise or an account brings the logged-in ZIP ("Download alle"), this
module names the files and links the page. Requests go one at a time with a cookie session: six
parallel requests drew 502 on every file.
"""
import html as htmlmod
import http.cookiejar
import re
import urllib.request

from docsource import common

NAME = "eu-supply"
ROOT = "https://eu.eu-supply.com"
PURCHASE = ROOT + "/ctm/Supplier/PublicPurchase/%s/0/0?returnUrl=&b="
WHY = "EU-Supply's robots.txt disallows /app/docmgmt, the path its public files are served from"


def clean_name(text):
    """A file name as the page shows it.

    The documents page is single-byte -- its æ, ø and å read right as latin-1 -- but every name is
    led by a UTF-8 non-breaking space, the two bytes C2 A0, which latin-1 reads as "Â" and a
    non-breaking space. 45 homes carried "Â " on every gated name until 26 Nov 2026. That pair and
    any other non-breaking space become a space; spaces are collapsed and the ends trimmed, along
    with the replacement character.
    """
    text = htmlmod.unescape(str(text or "")).replace("Â ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip(" �")


def listing(urls):
    m = re.search(r"PID=(\d+)", urls[0]) or re.search(r"PublicPurchase/(\d+)", urls[0])
    if not m:
        return {"access": "unknown", "note": "no PID in the link"}
    pid = m.group(1)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    page = common.fetch(PURCHASE % pid, opener=opener).decode("utf-8", "replace")
    docs = re.findall(r'href="(/app/rfq/publicpurchase_docs\.asp\?PID=\d+&(?:amp;)?LID=\d+[^"]*)"', page)
    if not docs:
        return {"access": "unknown", "tender_id": pid, "note": "the tender page links no documents page"}
    listing_page = common.fetch(ROOT + htmlmod.unescape(docs[0]), opener=opener).decode("latin-1", "replace")
    public = []
    for dvid, lid in re.findall(r"DownloadPublicDocument\('(\d+)','sDoc_\d+','(\d+)'\)", listing_page):
        name = re.search(r"var sDoc_%s\s*=\s*'([^']*)'" % dvid, listing_page)
        public.append(clean_name(name.group(1)) if name else "dvid%s" % dvid)
    gated = []
    at = listing_page.find("Available after expression of interest")
    if at >= 0:
        cells = re.findall(r'<td valign="top" class="tblcell" colspan="2">(.*?)</td>', listing_page[at:], re.S)
        gated = [clean_name(re.sub(r"<[^>]+>", "", c)) for c in cells]
        gated = [g for g in gated if g and g not in ("Print...", "Close window")]
    note = ("public files named, not downloaded: %s" % WHY if public
            else "" if gated else "the documents page lists no files")
    return {"access": "gated" if (public or gated) else "none", "files": [],
            "gated": public + gated, "public_names": public, "tender_id": pid, "note": note}


def download(entry):
    return None, WHY
