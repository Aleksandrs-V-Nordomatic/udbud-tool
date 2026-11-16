"""api.udbud.dk: a national notice's attachments, published on the portal itself.

Each `udbudsDokumenter` entry IS a file:
    https://api.udbud.dk/udbud/vedhaeftning/{id}/01/fil/{id}/{name}

The name is part of the path and carries Danish letters, so the path is quoted before the
request -- an unquoted `ø` failed one of eighteen on 16 Nov 2026; quoted, 18 of 18.
"""
import urllib.parse

from docsource import common

NAME = "api.udbud.dk"


def _quoted(url):
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def listing(urls):
    files = []
    for n, url in enumerate(u for u in urls if "/vedhaeftning/" in u):
        files.append({"id": "%d" % n,
                      "name": urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]),
                      "download": _quoted(url)})
    return {"access": "public" if files else "none", "files": files}


def download(entry):
    return common.plain_download(entry)
