"""Comdia: a tender's documents, read under our supplier account.

Comdia carries the municipal tenders -- 9 of the 36 construction tenders of 3-14 Nov 2026 -- and
shows an anonymous reader, and a signed-in one too, "Documents 0". The files open to a supplier
that has pressed ACCESS TO TENDER on the tender's page; from then on the tender sits in the
supplier's "My Tender/offer" and its vendor page lists every file with a "Download all" button.

THE BUYER SEES IT. Access to tender registers the company on the tender, and the vendor page has a
"Not downloaded" column per file, so the buyer sees who took what. That was decided on 23 Nov 2026:
the account is SIA "Nordomatic", and the radar presses Access to tender on every Comdia tender that
reaches `dk_fetch` -- the recall gate's survivors and the cards a person is watching, nothing else.
"Show interest" and "Subscribe" are never pressed: `_postback` refuses any control outside
`PRESSED`, so no edit elsewhere in this file can press one by accident.

PREQUALIFICATION IS PRESSED FOR BUILDING WORK ONLY. A two-stage tender offers ACCESS TO
PREQUALIFICATION instead; it opens the same vendor page and files nothing -- the application and
its ESPD are separate steps this module does not know. Decided on 24 Nov 2026 for building work
(`building_work`) and for the cards a person is watching; on any other tender it stays unpressed.
The tender page keeps offering the button afterwards, so the same press opens the tender again.

WHAT NOTHING READS STAYS IN THE ARCHIVE. A renovation's archive can be mostly sewer video and its
frames (Ved Moellen: 223 .bmp, 41 .mp4 and 55 data files beside 36 documents). `MEDIA` names
them; they are not listed, not stored and not counted against the size limit, and the note says
how many there were.

EVERYTHING IS PLAIN HTTP. Every page is ASP.NET WebForms: a button is a POST of the page's hidden
fields with `__EVENTTARGET` naming the control. Proved from a runner on 23 Nov 2026: the sign-in
form on `/login.aspx` answers with `.ASPXAUTH` and the vendor start page, no captcha, no
challenge; "Download all" answers with one ZIP of the tender (Hornbaek: 119 files, 172 MB, every
member `<tender>/<group>/<file>`, names flagged UTF-8). No browser is needed.

    sign in        POST /login.aspx                     __EVENTTARGET=...cphInnerContent$lbLogin
    tender page    GET  /<buyer>/tenderinformationshow.aspx?Id=N
      no access    ...$lbRegisterTender   "Access to tender"   -> access, then as below
      access       ...$lbGoToTender       "Go to tender"       -> /Site/vendor/user/tenderentity/show.aspx?Id=M
      two stages   ...$lbRegisterPreQual  "Access to prequalification" -> the same vendor page
    vendor page    ...$lbDownloadAll<k>   "Download all"       -> application/octet-stream, a ZIP

ONE SIGN-IN PER RUN, ONE FAILED SIGN-IN PER RUN, ONE TENDER AT A TIME. A refused account is not
asked again the same night, and a pause separates the presses.

THE ARCHIVE BECOMES THE LISTING. `listing` downloads the tender's archive once and returns each
member as a file whose folder is the group the buyer filed it under; `download` hands back that
member's bytes from the archive held in memory. So `dk_fetch` asks its two questions as it asks
every host, and nothing outside this file changed when the account arrived.

THE RUN'S LOG IS PUBLIC. This module prints nothing; what went wrong is in the listing's `note`,
which lands in the tender's privately delivered `index.json`. The account is masked out of it.

    python3 tools/comdia_check.py     # sign in, say whether it worked, press nothing
"""
import html as htmlmod
import http.cookiejar
import io
import os
import re
import sys
import time
import types
import urllib.parse
import urllib.request
import zipfile

import net
from docsource import common

NAME = "comdia"
BASE = "https://www.comdia.com"
LOGIN = BASE + "/login.aspx"
VENDOR_PAGE = "/site/vendor/user/tenderentity/show.aspx"

SIGN_IN = "ctl00$cphInnerContent$lbLogin"
ACCESS = "ctl00$ctl00$cphMain$cphMain$lbRegisterTender"
GO_TO_TENDER = "ctl00$ctl00$cphMain$cphMain$lbGoToTender"
PREQUALIFICATION = "ctl00$ctl00$cphMain$cphMain$lbRegisterPreQual"
DOWNLOAD_ALL = re.compile(r"ctl00\$ctl00\$cphMain\$cphMain\$lbDownloadAll\d*")
PER_FILE = re.compile(r"\$gvDocument\$ctl\d+\$lbDownload\b")

# The only controls this module may press. Show interest and Subscribe are not among them, and
# Access to prequalification is let through one call at a time (`prequalify`).
PRESSED = frozenset({SIGN_IN, ACCESS, GO_TO_TENDER})

# Building work by its CPV codes, as prefixes: construction in general, buildings, installation and
# completion, repair of building installations, and their design and supervision. Roads, pipelines
# and water works (4523-4525), surveys (7135) and environmental consultancy (71313) are not.
BUILDING_CPV = ("45000000", "451", "45200000", "4521", "4526", "453", "454", "507",
                "71000000", "712", "71300000", "71310000", "71314", "71315",
                "7132", "7133", "715")

# What an archive holds that nothing downstream reads.
MEDIA = frozenset({"mp4", "avi", "mov", "wmv", "mkv", "mpg", "mpeg", "m4v", "bmp",
                   "dat", "evtdat"})

# Between two presses on Comdia: one supplier reading one tender at a time.
PAUSE = 2.0

# The Hornbaek archive is 172 MB and came down in seconds; ten minutes covers a slow night.
ARCHIVE_TIMEOUT = 600

# What one tender may unpack to; a claim beyond it is a mistake or a bomb.
MAX_UNPACKED = 1024 * 1024 * 1024

CHALLENGE = re.compile(r"captcha|turnstile|cf-chl|challenge-platform", re.I)


class SignInFailed(Exception):
    """The account did not get us in. The message names the step and never the account."""


_SESSION = {"opener": None, "failed": None}
_ARCHIVE = {"key": None, "zip": None}


def _account():
    user = (os.environ.get("COMDIA_USER") or "").strip()
    password = os.environ.get("COMDIA_PASSWORD") or ""
    return (user, password) if user and password else None


def _mask(text):
    account = _account()
    text = str(text)
    if account:
        for secret in (account[1], account[0], urllib.parse.quote(account[0]),
                       urllib.parse.quote_plus(account[0])):
            if secret:
                text = text.replace(secret, "<account>")
    return text[:200]


def hidden_fields(page):
    """Every hidden input of an ASP.NET page -- the state a postback has to carry back."""
    fields = {}
    for tag in re.findall(r"<input[^>]+>", page):
        if not re.search(r'type="hidden"', tag, re.I):
            continue
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            fields[htmlmod.unescape(name.group(1))] = htmlmod.unescape(value.group(1)) if value else ""
    return fields


def controls(page):
    """The control names the page's links post back to, unescaped."""
    return [htmlmod.unescape(t) for t in
            re.findall(r"__doPostBack\((?:&#39;|')(.*?)(?:&#39;|')", page)]


def signed_in(page):
    return "logout.ashx" in page and "txtPassword" not in page


def _send(opener, url, data=None, timeout=60, tries=3):
    """`(body, final_url, content_type)` for one request through the run's cookie jar, under the
    family's retry policy."""
    headers = {"User-Agent": common.UA}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers)
    seen = {}

    def open_and_note(req, timeout=60):        # net.open_url reads the body; keep url and type
        resp = opener.open(req, timeout=timeout)
        seen.update(url=resp.geturl(), type=resp.headers.get("Content-Type", ""))
        return resp

    body, _ = net.open_url(request, timeout=timeout, tries=tries,
                           opener=types.SimpleNamespace(open=open_and_note), log=common.log)
    return body, seen.get("url", url), seen.get("type", "")


def _page(opener, url, data=None):
    body, final, _ = _send(opener, url, data)
    return body.decode("utf-8", "replace"), final


def _postback(opener, url, page, target, timeout=60, tries=3, prequalify=False):
    """Press one control. Refuses every control but the sign-in, Access and Go to tender, the
    Download all button and, only when the caller says so, Access to prequalification."""
    allowed = (target in PRESSED or DOWNLOAD_ALL.fullmatch(target)
               or (prequalify and target == PREQUALIFICATION))
    if not allowed:
        raise PermissionError("Comdia control %r is not one this module presses" % target)
    form = hidden_fields(page)
    form.update({"__EVENTTARGET": target, "__EVENTARGUMENT": ""})
    time.sleep(PAUSE)
    return _send(opener, url, form, timeout=timeout, tries=tries)


def sign_in(user, password):
    """A cookie jar signed in to Comdia. Raises `SignInFailed` naming the step."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        page, _ = _page(opener, LOGIN)
    except Exception as exc:
        raise SignInFailed("the sign-in page did not load (%s)" % type(exc).__name__)
    if CHALLENGE.search(page):
        raise SignInFailed("a captcha or a challenge stood in front of the sign-in page")
    form = hidden_fields(page)
    form.update({"__EVENTTARGET": SIGN_IN, "__EVENTARGUMENT": "",
                 "ctl00$cphInnerContent$txtEmail": user,
                 "ctl00$cphInnerContent$txtPassword": password,
                 "ctl00$cphInnerContent$txtBrowserWidth": "1600",
                 "ctl00$cphInnerContent$txtBrowserHeight": "900"})
    try:
        page, _ = _page(opener, LOGIN, form)
    except Exception as exc:
        raise SignInFailed("the sign-in form was not answered (%s)" % type(exc).__name__)
    if CHALLENGE.search(page):
        raise SignInFailed("a captcha or a challenge stood in the way after the password")
    if not signed_in(page):
        raise SignInFailed("Comdia refused the account")
    return opener


def session(fresh=False):
    """The run's signed-in cookie jar, signing in on first use; at most one failure per run."""
    if _SESSION["failed"]:
        raise SignInFailed(_SESSION["failed"])
    if _SESSION["opener"] is not None and not fresh:
        return _SESSION["opener"]
    account = _account()
    if account is None:
        raise SignInFailed("no Comdia account is configured for this run")
    try:
        _SESSION["opener"] = sign_in(*account)
    except SignInFailed as exc:
        _SESSION["failed"] = str(exc)
        raise
    return _SESSION["opener"]


def tender_id(url):
    """The `Id=` of a Comdia tender page, or None."""
    query = urllib.parse.urlparse(url or "").query
    for key, values in urllib.parse.parse_qs(query).items():
        if key.casefold() == "id" and values[0].strip().isdigit():
            return values[0].strip()
    return None


def building_work(codes):
    """Whether any of a tender's CPV codes is building work."""
    return any(str(code).startswith(BUILDING_CPV) for code in codes or [] if code)


def open_tender(opener, url, prequalify=False):
    """The tender's vendor page `(page, url)`, pressing Access to tender if it is not open yet,
    or Access to prequalification when `prequalify` allows it.

    Returns `(None, None, reason)` when the tender offers no way in we are allowed to take.
    """
    page, final = _page(opener, url)
    if not signed_in(page):
        raise SignInFailed("the session ended")
    found = controls(page)
    pressed = False
    if GO_TO_TENDER not in found and ACCESS in found:
        body, final, _ = _postback(opener, final, page, ACCESS)
        pressed = True
        page = body.decode("utf-8", "replace")
        if VENDOR_PAGE in final.lower():
            return page, final, None
        found = controls(page)
    if GO_TO_TENDER in found:
        body, final, _ = _postback(opener, final, page, GO_TO_TENDER)
        page = body.decode("utf-8", "replace")
        if VENDOR_PAGE in final.lower():
            return page, final, None
        return None, None, "Go to tender did not lead to the tender's vendor page"
    if pressed:
        return None, None, "Access to tender was pressed and the tender did not open"
    if PREQUALIFICATION in found:
        if not prequalify:
            return None, None, "the tender has prequalification and is not building work; not pressed"
        body, final, _ = _postback(opener, final, page, PREQUALIFICATION, prequalify=True)
        if VENDOR_PAGE in final.lower():
            return body.decode("utf-8", "replace"), final, None
        return None, None, "Access to prequalification was pressed and the tender did not open"
    offered = sorted({c.rsplit("$", 1)[-1] for c in found if "cphMain$cphMain$lb" in c})
    return None, None, "the tender page offers no Access to tender (it offers: %s)" % (
        ", ".join(offered) or "nothing")


def _member_name(info):
    """The member's real name; one without the UTF-8 flag is read as cp437 by Python."""
    name = info.filename
    if not info.flag_bits & 0x800:
        for codec in ("utf-8", "cp1252"):
            try:
                name = name.encode("cp437").decode(codec)
                break
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    return name.replace("\\", "/")


def _extension(name):
    base = name.rpartition("/")[2]
    return base.rpartition(".")[2].lower() if "." in base else ""


def left_out(archive):
    """The members nothing downstream reads, counted by extension."""
    counts = {}
    for info in archive.infolist():
        extension = _extension(_member_name(info))
        if not info.is_dir() and extension in MEDIA:
            counts[extension] = counts.get(extension, 0) + 1
    return counts


def archive_files(archive, source):
    """The listing's files, one per member that something reads. The archive's own top folder --
    the tender, the same for every member -- is dropped; the groups under it are kept as the
    folder."""
    members = [(i, _member_name(i)) for i in archive.infolist() if not i.is_dir()]
    tops = {name.split("/", 1)[0] for _, name in members if "/" in name}
    strip_top = len(tops) == 1 and all("/" in name for _, name in members)
    files = []
    for info, name in sorted(members, key=lambda m: m[1]):
        if _extension(name) in MEDIA:
            continue
        path = name.split("/", 1)[1] if strip_top else name
        folder, _, base = path.rpartition("/")
        files.append({"id": "zip:%s" % name, "name": base or path, "folder": folder,
                      "member": info.filename, "bytes": info.file_size, "download": source})
    return files


def listing(urls, facts=None):
    """The tender as `_read` found it; `files` is always there, empty when nothing was read."""
    return dict({"files": []}, **_read(urls, facts))


def _read(urls, facts=None):
    """Sign in, open the tender, download its archive, and list its members.

    `facts` is what the notice says of the tender: its CPV codes, and whether a card watches it,
    decide whether Access to prequalification may be pressed. Without them it may not.
    """
    facts = facts or {}
    prequalify = bool(facts.get("watched")) or building_work(
        [facts.get("cpv_main")] + list(facts.get("cpv") or []))
    _ARCHIVE.update(key=None, zip=None)
    url = urls[0]
    if tender_id(url) is None:
        return {"access": "unknown", "note": "the Comdia link names no tender (no Id=)"}
    if _account() is None:
        return {"access": "gated", "note": "no Comdia account is configured for this run"}
    try:
        opener = session()
        try:
            page, vendor_url, reason = open_tender(opener, url, prequalify)
        except SignInFailed:                   # the session ended mid-run: one fresh sign-in
            opener = session(fresh=True)
            page, vendor_url, reason = open_tender(opener, url, prequalify)
        if reason:
            return {"access": "gated", "note": reason}
        buttons = [c for c in controls(page) if DOWNLOAD_ALL.fullmatch(c)]
        on_page = len({c for c in controls(page) if PER_FILE.search(c)})
        if not buttons:
            if on_page:
                return {"access": "gated", "note": "the vendor page lists %d file(s) and no Download all" % on_page}
            return {"access": "none", "note": "the tender's vendor page lists no documents"}
        data, final, kind = _postback(opener, vendor_url, page, buttons[0],
                                      timeout=ARCHIVE_TIMEOUT, tries=2)
        if not data.startswith(b"PK\x03\x04"):
            if data.startswith(b"PK\x05\x06"):
                return {"access": "none", "note": "Comdia's archive holds no files"}
            return {"access": "gated", "note": "Download all answered %s, %d bytes, not an archive"
                    % (kind or "no type", len(data))}
        archive = zipfile.ZipFile(io.BytesIO(data))
        claimed = sum(i.file_size for i in archive.infolist()
                      if _extension(_member_name(i)) not in MEDIA)
        if claimed > MAX_UNPACKED:
            return {"access": "gated", "note": "the archive claims %.0f MB unpacked, over the %d MB a tender may take"
                    % (claimed / 1048576.0, MAX_UNPACKED // 1048576)}
        files = archive_files(archive, vendor_url)
        skipped = left_out(archive)
        held = len(files) + sum(skipped.values())
        _ARCHIVE.update(key=vendor_url, zip=archive)
        notes = []
        if on_page > held:
            notes.append("the vendor page lists %d; the archive holds %d" % (on_page, held))
        if skipped:
            notes.append("left out, nothing reads them: %s"
                         % ", ".join("%d .%s" % (n, e) for e, n in sorted(skipped.items())))
        note = "; ".join(notes)
        return {"access": "public" if files else "none", "files": files, "tender_id": tender_id(url),
                "note": note}
    except SignInFailed as exc:
        return {"access": "gated", "note": "Comdia sign-in failed: %s" % _mask(exc)}
    except Exception as exc:                   # one tender must not lose the night
        return {"access": "gated", "note": "the Comdia step failed: %s: %s" % (type(exc).__name__, _mask(exc))}


def download(entry):
    """One member's bytes from the archive `listing` just downloaded."""
    if _ARCHIVE["zip"] is None or entry.get("download") != _ARCHIVE["key"]:
        return None, "the Comdia archive is no longer held; the tender has to be listed again"
    try:
        data = _ARCHIVE["zip"].read(entry["member"])
    except Exception as exc:
        return None, "the archive member could not be read: %s" % type(exc).__name__
    if not data:
        return None, "the archive member is empty"
    return data, None


def main(argv=None):
    if list(argv if argv is not None else sys.argv[1:]) != ["--check"]:
        print("usage: python3 tools/comdia_check.py")
        return 2
    try:
        session()
    except SignInFailed as exc:
        print("comdia: sign-in failed: %s" % _mask(exc))
        return 1
    print("comdia: signed in")
    return 0


if __name__ == "__main__":
    sys.exit(main())
