#!/usr/bin/env python3
"""Normalize a freshly captured wget mirror of zekerwaard.nl for static hosting.

Run from the repo root after the capture step. Idempotent.

Implements plan U3 (KTD7, KTD8):
  - rewrites /cms/<slug> navigation to depth-correct relative paths (R5)
  - rewrites same-host absolute asset references to document-relative (R4)
  - leaves canonical and Open Graph URLs absolute, since relative canonicals
    break search and social sharing (plan KTD1 note on metadata)
  - strips link elements for feeds, comment feeds, wp-json and oembed, which
    cannot resolve without WordPress (R6)
  - removes the WordPress search form, which has no static equivalent (R9)
  - drops the robots.txt Sitemap line, since no sitemap is published
"""
import re, pathlib, sys

HOST = r'https?://www\.zekerwaard\.nl'
PAGES = {
    pathlib.Path('index.html'): '',
    pathlib.Path('verzekeringen/index.html'): '../',
    pathlib.Path('hypotheken/index.html'): '../',
    pathlib.Path('over/index.html'): '../',
    pathlib.Path('contact/index.html'): '../',
}
SLUGS = ('verzekeringen', 'hypotheken', 'over', 'contact')
LIVE = 'https://www.zekerwaard.nl'
# wget --convert-links rewrites rel=canonical to a relative path (and to the
# wrong page: every one becomes index.html). Canonicals must be absolute and
# per-page, so they are restored from this map rather than from the capture.
CANONICAL = {
    pathlib.Path('index.html'): f'{LIVE}/',
    pathlib.Path('verzekeringen/index.html'): f'{LIVE}/verzekeringen/',
    pathlib.Path('hypotheken/index.html'): f'{LIVE}/hypotheken/',
    pathlib.Path('over/index.html'): f'{LIVE}/over/',
    pathlib.Path('contact/index.html'): f'{LIVE}/contact/',
}
# Lines matching these are dead without WordPress and are removed wholesale.
DEAD_LINK = re.compile(
    r"<link[^>]*(?:wp-json|oembed|/feed/|comments/feed)[^>]*>\s*", re.I)
# Metadata URLs that must stay absolute.
KEEP_ABSOLUTE = re.compile(
    r'(<link[^>]+rel=["\']canonical["\'][^>]*>|'
    r'<meta[^>]+property=["\']og:[^"\']*["\'][^>]*>)', re.I)


def normalize_page(path: pathlib.Path, prefix: str) -> dict:
    text = original = path.read_text(encoding='utf8', errors='replace')
    counts = {}

    # 0a. Repair wget's doubled-URL mangling of &quot;-escaped urls inside
    # inline style attributes: it prepends the host to the escaped quote.
    text, counts['unmangle'] = re.subn(
        rf'{HOST}/&quot;{HOST}/', f'&quot;{LIVE}/', text)

    # 0b. Restore the canonical wget relativized (see CANONICAL above).
    text, counts['canonical'] = re.subn(
        r'<link rel="canonical"[^>]*>',
        f'<link rel="canonical" href="{CANONICAL[path]}" />', text)

    # 0c. Neutralize the author-archive link; that page is not mirrored, so the
    # link would 404. The byline text is kept.
    text, counts['author'] = re.subn(
        rf'<a[^>]+href="{HOST}/author/[^"]*"[^>]*>(.*?)</a>', r'\1',
        text, flags=re.S)

    # Protect metadata URLs from the asset rewrite below.
    vault = []

    def stash(m):
        vault.append(m.group(0))
        return f'\x00KEEP{len(vault) - 1}\x00'

    text = KEEP_ABSOLUTE.sub(stash, text)

    # 1. Navigation: /cms/<slug> -> <prefix><slug>/  (R5)
    n = 0
    for slug in SLUGS:
        text, k = re.subn(rf'{HOST}/cms/{slug}/?', f'{prefix}{slug}/', text)
        n += k
    counts['nav_cms'] = n

    # 2. Already-pretty absolute navigation: /<slug>/ -> <prefix><slug>/
    n = 0
    for slug in SLUGS:
        text, k = re.subn(rf'{HOST}/{slug}/', f'{prefix}{slug}/', text)
        n += k
    counts['nav_pretty'] = n

    # 3. Asset references under /cms/ -> document-relative (R4)
    text, counts['assets'] = re.subn(rf'{HOST}/cms/', f'{prefix}cms/', text)

    # 4. Home link: host root, with or without a trailing slash, and the
    # bare-anchor form used by dropdown parents.
    n = 0
    text, k = re.subn(rf'(href=["\']){HOST}/?#', r'\1#', text); n += k
    text, k = re.subn(rf'(href=["\']){HOST}/?(["\'])',
                      rf'\1{prefix or "./"}\2', text); n += k
    counts['home'] = n

    # 5. Dead WordPress link elements (R6)
    text, counts['dead_links'] = DEAD_LINK.subn('', text)

    # 6. WordPress search form (R9)
    text, counts['search'] = re.subn(
        r'<form[^>]*class="[^"]*searchform[^"]*"[^>]*>.*?</form>\s*',
        '', text, flags=re.S | re.I)

    # Restore metadata URLs.
    for i, original_tag in enumerate(vault):
        text = text.replace(f'\x00KEEP{i}\x00', original_tag)

    if text != original:
        path.write_text(text, encoding='utf8')
    counts['changed'] = text != original
    return counts


def normalize_css() -> int:
    """Rewrite absolute asset urls inside the generated stylesheets."""
    total = 0
    for css in pathlib.Path('cms/wp-content/uploads/fusion-styles').glob('*'):
        if not css.is_file():
            continue
        text = original = css.read_text(encoding='utf8', errors='replace')
        # fusion-styles sits 3 levels below cms/, so ../../.. reaches the root.
        text, k = re.subn(rf'{HOST}/cms/', '../../../', text)
        if text != original:
            css.write_text(text, encoding='utf8')
        total += k
    return total


def normalize_robots() -> bool:
    p = pathlib.Path('robots.txt')
    if not p.exists():
        return False
    text = original = p.read_text(encoding='utf8')
    text = re.sub(r'(?m)^Sitemap:.*\n?', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text).rstrip() + '\n'
    if text != original:
        p.write_text(text, encoding='utf8')
    return text != original


def main() -> int:
    missing = [str(p) for p in PAGES if not p.exists()]
    if missing:
        print(f'missing captured pages: {missing}', file=sys.stderr)
        return 1
    for path, prefix in PAGES.items():
        c = normalize_page(path, prefix)
        print(f'{str(path):28} nav={c["nav_cms"]+c["nav_pretty"]:3} '
              f'assets={c["assets"]:3} home={c["home"]:2} '
              f'dead_links={c["dead_links"]:2} search={c["search"]}')
    print(f'stylesheet absolute urls rewritten: {normalize_css()}')
    print(f'robots.txt sitemap line removed: {normalize_robots()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
