"""What every document host shares: one transport, and the rule that a 200 proves nothing."""
import sys
import urllib.request

import net

UA = "Mozilla/5.0 (compatible; eis-tool)"
TIMEOUT = 300
HTML_HEADS = (b"<!doctype", b"<html", b"<?xml version=\"1.0\" encoding=\"utf-8\"?><!doctype")


def log(message):
    print(message, file=sys.stderr, flush=True)


def fetch(url, data=None, headers=None, opener=None, timeout=60, tries=net.TRIES):
    """Bytes of one request under the family's retry policy."""
    h = {"User-Agent": UA}
    h.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=h)
    body, _ = net.open_url(request, timeout=timeout, tries=tries, opener=opener, log=log)
    return body


def looks_like_html(data, name=""):
    """An error page served under a 200. A file the buyer named .html or .htm is allowed to be one."""
    if str(name).lower().endswith((".html", ".htm", ".xhtml")):
        return False
    head = data.lstrip()[:64].lower()
    return any(head.startswith(h) for h in HTML_HEADS)


def plain_download(entry, opener=None, headers=None):
    try:
        data = fetch(entry["download"], opener=opener, headers=headers, timeout=TIMEOUT)
    except Exception as exc:
        return None, "could not be downloaded: %s" % str(exc)[:160]
    if not data:
        return None, "the host served an empty body"
    if looks_like_html(data, entry.get("name")):
        return None, "the host served an HTML page rather than the file, under a 200 -- %d bytes" % len(data)
    return data, None
