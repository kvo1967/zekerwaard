#!/usr/bin/env python3
"""Verification Contract gates for the static mirror (plan U5).

Usage:
  tools/verify-mirror.py            # audit files on disk, then serve locally
  tools/verify-mirror.py <base-url> # audit disk, then check a deployed site

Every markup gate matches both quote styles and covers srcset and inline
url() values. The first version matched only double-quoted src/href and
therefore reported ALL GATES PASS while four pages shipped an invalid hero
background, 25 Contact Form 7 scripts survived, and the contact page still
loaded Google Maps with the live API key.
"""
import http.server
import os
import pathlib
import re
import socketserver
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mirror_common import CANONICAL, LIVE, PAGES, Q, attr_urls, read  # noqa: E402

LIVE_HOST = 'www.zekerwaard.nl'
fails: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        fails.append(name)


def audit_disk() -> None:
    print('Disk gates')
    absent = [str(p) for p in PAGES if not p.exists()]
    check('all five pages present', not absent, ', '.join(absent))
    if absent:
        return
    pages = {p: read(p) for p in PAGES}

    check('no filename contains "?"',
          not [p for p in pathlib.Path('.').rglob('*') if '?' in p.name])

    # Only canonical and og: metadata may keep an absolute live-site URL, and
    # no script body may reference the live host at all - that is a request
    # R6 forbids. Visible text containing the company URL is page content, not
    # a reference, and is left alone.
    bad = []
    for p, s in pages.items():
        for m in re.finditer(rf'[\w:-]+={Q}[^"\']*{re.escape(LIVE_HOST)}[^"\']*{Q}', s):
            if not re.match(rf'(?:href|content)={Q}', m.group(0)):
                bad.append(f'{p}: attribute {m.group(0)[:45]}')
        for sm in re.finditer(r'<script\b[^>]*>(.*?)</script>', s, re.S | re.I):
            # JSON escapes the slashes, so match the host alone.
            if LIVE_HOST in sm.group(1):
                bad.append(f'{p}: live host inside a script body')
                break
    check('live-site URLs only in canonical/og metadata', not bad, '; '.join(bad[:3]))

    check('canonical is absolute and per-page', all(
        f'<link rel="canonical" href="{CANONICAL[p]}" />' in s
        for p, s in pages.items()))
    check('og:url is absolute and per-page', all(
        re.search(rf'og:url{Q} content={Q}{re.escape(CANONICAL[p])}{Q}', s)
        for p, s in pages.items()))

    check('no root-relative src/href', not [
        u for s in pages.values() for u in attr_urls(s)
        if u.startswith('/') and not u.startswith('//')])

    check('no extensionless page file under cms/',
          not [p for p in pathlib.Path('cms').glob('*')
               if p.is_file() and '.' not in p.name]
          if pathlib.Path('cms').exists() else True)

    # Inline style url() targets, which wget does not parse and never fetches.
    missing = []
    for p, s in pages.items():
        for u in re.findall(r'url\(\s*&quot;([^&]+)&quot;\s*\)', s):
            if not (p.parent / u).exists():
                missing.append(f'{p}: {u}')
    check('inline-style background images exist', not missing, '; '.join(missing[:3]))

    # Stylesheet url() targets. ptb_background-compressor.jpg 404s on the live
    # site too, so the mirror inherits a dead reference rather than losing one.
    missing = []
    for css in pathlib.Path('cms/wp-content/uploads/fusion-styles').glob('*'):
        if not css.is_file():
            continue
        for t in re.findall(r'url\(\s*["\']?([^)"\'\s]+)', read(css)):
            if t.startswith(('data:', '#', 'http')) or 'ptb_background-compressor' in t:
                continue
            t = urllib.parse.unquote(t.split('?')[0].split('#')[0])
            if not (css.parent / t).exists():
                missing.append(t)
    check('stylesheet url() targets resolve', not missing, '; '.join(missing[:3]))

    check('contact page has no form', '<form' not in pages[pathlib.Path('contact/index.html')])
    check('no Contact Form 7 scripts', not [
        p for p, s in pages.items()
        if re.search(r'<script[^>]*(contact-form-7|swv-js|wpcf7|recaptcha)', s, re.I)])
    check('no Google Maps loader or API key', not [
        p for p, s in pages.items() if 'maps.googleapis.com' in s or 'AIzaSy' in s])
    check('every page has a robots noindex', all(
        re.search(rf'<meta name={Q}robots{Q}[^>]*noindex', s, re.I) for s in pages.values()))
    check('.nojekyll present', pathlib.Path('.nojekyll').exists())


def audit_served(base: str) -> None:
    print(f'\nServed gates ({base})')
    for rel in ['' if p == pathlib.Path('index.html') else f'{p.parent}/' for p in PAGES]:
        url = base.rstrip('/') + '/' + rel
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                ct = r.headers.get('Content-Type', '')
                body = r.read().decode('utf8', 'replace')
            check(f'GET /{rel} is 200 text/html',
                  r.status == 200 and 'text/html' in ct, ct)
        except Exception as e:
            check(f'GET /{rel}', False, str(e))
            continue

        broken = []
        for ref in sorted(attr_urls(body)):
            if ref.startswith(('http', '//', 'mailto:', 'tel:')):
                continue
            target = urllib.parse.urljoin(url, ref)
            try:
                with urllib.request.urlopen(
                        urllib.request.Request(target, method='HEAD'), timeout=25) as rr:
                    if rr.status >= 400:
                        broken.append(f'{rr.status} {ref}')
            except Exception as e:
                broken.append(f'{getattr(e, "code", "?")} {ref}')
        check(f'/{rel} assets all resolve', not broken,
              f'{len(broken)} broken: ' + '; '.join(broken[:4]) if broken else '')


def serve_and_audit() -> None:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    with socketserver.TCPServer(('127.0.0.1', 0), Quiet) as httpd:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        audit_served(f'http://127.0.0.1:{httpd.server_address[1]}')
        httpd.shutdown()


def main() -> int:
    os.chdir(pathlib.Path(__file__).resolve().parent.parent)
    audit_disk()
    if len(sys.argv) > 1:
        audit_served(sys.argv[1])
    else:
        serve_and_audit()
    print(f"\n{'ALL GATES PASS' if not fails else f'{len(fails)} GATE(S) FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
