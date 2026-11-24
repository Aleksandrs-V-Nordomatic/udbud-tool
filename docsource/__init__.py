"""Where a Danish tender's documents live, and what of them can be read without an account.

udbud.dk carries no documents. Each notice names a link -- `udbudsDokumenter` -- on the platform
the buyer runs the tender on, and Denmark has a dozen of them. Measured over the 174 competition
notices of 3-14 Nov 2026:

    host            share   without an account
    eu-supply       32.2%   names of the files; the files themselves after "expression of interest"
    ethics.dk       19.5%   every public file  (481 of 481 downloaded)
    comdia          16.1%   every file, under our supplier account (Access to tender)
    mercell          8.0%   names and sizes
    amgros           8.0%   pharmaceuticals, out of scope
    dalux            6.9%   every file of a public tender (1 622 of 1 622)
    api.udbud.dk     2.3%   every file (18 of 18)
    byggeweb, ajour, others  ~5%
    ibinder          1%     what its public view shows (4 tenders, 344 of 349 files, 24 Nov 2026)

ONE MODULE PER HOST, EACH ANSWERING THE SAME TWO QUESTIONS: `listing(url)` -- what the host says
the tender holds and which of it is public -- and `download(entry)` -- the bytes of one public
file. A host that needs an account answers `listing` with the names it shows anonymously and
`access: gated`, and never downloads. When an account arrives for one of them, its module is the
only file that changes: `dk_fetch` asks the same two questions of whatever module the host maps to.

`access` on a listing:
    public    every listed file can be downloaded
    partial   some can, some are behind the account
    gated     the host lists names (or nothing) and serves no file without an account
    none      the host answered and the tender has no documents
    unknown   no module for this host; a person opens the link
"""
import urllib.parse

from docsource import byggeweb, comdia, dalux, ethics, eusupply, ibinder, mercell, udbuddk

MODULES = (
    ("ethics.dk", ethics),
    ("dalux.com", dalux),
    ("api.udbud.dk", udbuddk),
    ("byggeweb.dk", byggeweb),
    ("eu-supply.com", eusupply),
    ("mercell.com", mercell),
    ("comdia.com", comdia),
    ("ibinder.com", ibinder),
)


def host_of(url):
    return urllib.parse.urlparse(url or "").netloc.lower()


def module_for(url):
    host = host_of(url)
    for suffix, module in MODULES:
        if host == suffix or host.endswith("." + suffix):
            return module
    return None


def listing(urls, facts=None):
    """What the tender's documents link leads to. `urls` is `udbudsDokumenter`, in order.

    `facts` is the notice's own record. Only Comdia asks for it, to decide whether it may open a
    two-stage tender.
    """
    urls = [u for u in (urls or []) if u]
    if not urls:
        return {"host": None, "platform": None, "access": "none", "files": [], "gated": [],
                "note": "the notice names no documents link"}
    module = module_for(urls[0])
    if module is None:
        return {"host": host_of(urls[0]), "platform": None, "access": "unknown", "files": [],
                "gated": [], "note": "no reader for this host; the link is on the card"}
    try:
        found = module.listing(urls, facts) if module is comdia else module.listing(urls)
    except Exception as exc:                  # one host's outage must not lose the tender
        found = {"access": "unknown", "files": [], "gated": [], "failed": True,
                 "note": "the listing failed: %s: %s" % (type(exc).__name__, str(exc)[:160])}
    found.setdefault("files", [])
    found.setdefault("gated", [])
    found.setdefault("note", "")
    found["host"] = host_of(urls[0])
    found["platform"] = module.NAME
    return found


def download(platform, entry):
    """`(bytes, reason)` for one public file; exactly one of them is set."""
    for _, module in MODULES:
        if module.NAME == platform:
            return module.download(entry)
    return None, "no reader for %s" % platform
