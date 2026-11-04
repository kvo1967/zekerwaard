#!/usr/bin/env python3
"""Verification Contract gates for the static mirror (plan U5).

Usage:
  tools/verify-mirror.py            # audit the files on disk, then serve
                                    # locally and check every page and asset
  tools/verify-mirror.py <base-url> # audit disk, then check a deployed site

Implements the gate table in the plan's Verification Contract.
"""
import http.server, os, pathlib, re, socketserver, sys, threading
import urllib.parse, urllib.request

PAGES = ['', 'verzekeringen/', 'hypotheken/', 'over/', 'contact/']
LIVE = 'www.zekerwaard.nl'
fails: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        fails.append(name)


def page_files() -> list[pathlib.Path]:
    return [pathlib.Path((p or '.') + '/index.html') for p in PAGES]


def audit_disk() -> None:
    print('Disk gates')
    check('no filename contains "?"',
          not list(pathlib.Path('.').rglob('*?*')) or
          not [p for p in pathlib.Path('.').rglob('*') if '?' in p.name])

    # same-host absolutes: only canonical and og: metadata may remain
    bad = []
    for f in page_files():
        s = f.read_text(encoding='utf8', errors='replace')
        for m in re.finditer(rf'[\w:-]+="[^"]*{re.escape(LIVE)}[^"]*"', s):
            tag = m.group(0)
            if not re.match(r'(href="https://www\.zekerwaard\.nl/[a-z]*/?"|content=)', tag):
                bad.append(f'{f}: {tag[:60]}')
    check('only metadata URLs stay absolute', not bad, '; '.join(bad[:3]))

    check('no root-relative src/href', not [
        m for f in page_files()
        for m in re.findall(r'(?:src|href)="(/[^/"][^"]*)"',
                            f.read_text(encoding='utf8', errors='replace'))])

    check('no extensionless page file under cms/', not [
        p for p in pathlib.Path('cms').glob('*') if p.is_file() and '.' not in p.name]
        if pathlib.Path('cms').exists() else True)

    # every stylesheet url() target that exists upstream resolves locally
    missing = []
    for css in pathlib.Path('cms/wp-content/uploads/fusion-styles').glob('*'):
        if not css.is_file():
            continue
        base = css.parent
        for t in re.findall(r'url\(\s*["\']?([^)"\']+)["\']?\s*\)',
                            css.read_text(encoding='utf8', errors='replace')):
            if t.startswith(('data:', '#', 'http')):
                continue
            t = urllib.parse.unquote(t.split('?')[0].split('#')[0])
            if not (base / t).resolve().exists():
                missing.append(t)
    # ptb_background-compressor.jpg 404s on the live site too; it is a dead
    # reference the mirror inherits rather than an asset the capture lost.
    missing = [m for m in missing if 'ptb_background-compressor' not in m]
    check('stylesheet url() targets resolve', not missing, '; '.join(missing[:3]))

    check('contact page has no form', '<form' not in
          pathlib.Path('contact/index.html').read_text(encoding='utf8', errors='replace'))
    check('all pages carry noindex',
          all('noindex' in f.read_text(encoding='utf8', errors='replace')
              for f in page_files()))
    check('.nojekyll present', pathlib.Path('.nojekyll').exists())


def audit_served(base: str) -> None:
    print(f'\nServed gates ({base})')
    for p in PAGES:
        url = base.rstrip('/') + '/' + p
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                ct = r.headers.get('Content-Type', '')
                body = r.read().decode('utf8', 'replace')
            check(f'GET /{p or ""} is 200 text/html',
                  r.status == 200 and 'text/html' in ct, ct)
        except Exception as e:
            check(f'GET /{p or ""}', False, str(e))
            continue

        refs = set(re.findall(r'(?:src|href)="([^"#?][^"]*)"', body))
        broken = []
        for ref in refs:
            if ref.startswith(('http', '//', 'mailto:', 'tel:', 'data:')):
                continue
            target = urllib.parse.urljoin(url, ref)
            try:
                rq = urllib.request.Request(target, method='HEAD')
                with urllib.request.urlopen(rq, timeout=20) as rr:
                    if rr.status >= 400:
                        broken.append(f'{rr.status} {ref}')
            except Exception as e:
                code = getattr(e, 'code', '?')
                broken.append(f'{code} {ref}')
        check(f'/{p or ""} assets all resolve', not broken,
              f'{len(broken)} broken: ' + '; '.join(broken[:4]) if broken else '')


def serve_and_audit() -> None:
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    with socketserver.TCPServer(('127.0.0.1', 0), Q) as httpd:
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        audit_served(f'http://127.0.0.1:{port}')
        httpd.shutdown()


def main() -> int:
    os.chdir(pathlib.Path(__file__).resolve().parent.parent)
    audit_disk()
    if len(sys.argv) > 1:
        audit_served(sys.argv[1])
    else:
        serve_and_audit()
    print(f"\n{'ALL GATES PASS' if not fails else str(len(fails)) + ' GATE(S) FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
