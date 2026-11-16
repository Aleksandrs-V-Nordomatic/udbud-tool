"""Byggeweb (RIB): a public document list and a two-step download.

    POST /controller  cmd=tender.public.documents&tn=<TN...>       -> an HTML list
    GET  /controller?cmd=tender.public.file&subcmd=download&tn=&fileid=&dlfid=
         -> a small page whose href='...' is the real file under /download-forced/...

The list is HTML: each file is a `<table class="filename" id="<dlfid>">` holding `fileid=` and the
name in `<td class="fname">`. Measured 16 Nov 2026: 24 of 24.
"""
import html as htmlmod
import re
import urllib.parse

from docsource import common

NAME = "byggeweb"
CONTROLLER = "https://www.byggeweb.dk/controller"
STEP = CONTROLLER + "?cmd=tender.public.file&subcmd=download&tn=%s&fileid=%s&dlfid=%s"


def listing(urls):
    m = re.search(r"tn=(\w+)", urls[0])
    if not m:
        return {"access": "unknown", "note": "no tn= in the link"}
    tn = m.group(1)
    page = common.fetch(CONTROLLER, data=urllib.parse.urlencode(
        {"cmd": "tender.public.documents", "tn": tn}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}).decode("utf-8", "replace")
    files = []
    for dlfid, block in re.findall(r'<table class="filename[^"]*" id="(\d+)">(.*?)</table>', page, re.S):
        fid = re.search(r"fileid=([0-9a-f]+)", block)
        name = re.search(r'<td class="fname[^"]*">\s*(.*?)\s*</td>', block, re.S)
        if fid and name:
            files.append({"id": dlfid, "name": htmlmod.unescape(re.sub(r"<[^>]+>", "", name.group(1))).strip(),
                          "download": STEP % (tn, fid.group(1), dlfid)})
    return {"access": "public" if files else "none", "files": files, "tender_id": tn}


def download(entry):
    try:
        shim = common.fetch(entry["download"])
    except Exception as exc:
        return None, "could not be downloaded: %s" % str(exc)[:160]
    rel = re.search(rb"href='([^']+)'", shim)
    if not rel:
        return None, "the download step did not name the file"
    target = urllib.parse.urljoin("https://www.byggeweb.dk/", rel.group(1).decode("utf-8", "replace"))
    return common.plain_download(dict(entry, download=target))
