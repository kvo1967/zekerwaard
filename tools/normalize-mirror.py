#!/usr/bin/env python3
"""Normalize a freshly captured wget mirror of zekerwaard.nl for static hosting.

Run from the repo root after the capture step. Idempotent.

Implements plan U3 (KTD7, KTD8):
  - repairs two wget --convert-links defects: a doubled host on &quot;-escaped
    url() values inside inline styles, and rel=canonical rewritten to a
    relative path pointing at the wrong page
  - rewrites /cms/<slug> navigation to depth-correct relative paths (R5)
  - rewrites same-host absolute asset references to document-relative (R4)
  - leaves canonical and Open Graph URLs absolute; relative canonicals break
    search and social sharing
  - strips link elements that cannot resolve without WordPress (R6)
  - removes the WordPress search form (R9)
  - drops the robots.txt Sitemap line, since no sitemap is published

Every repair asserts its expected substitution count. A silent zero-match is
how the first version of this script shipped broken pages.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mirror_common import CANONICAL, HOST, LIVE, PAGES, Q, SLUGS, read  # noqa: E402

# Link elements that are dead without WordPress. Both quote styles: WordPress
# emits shortlink and RSD single-quoted and the rest double-quoted.
DEAD_LINK = re.compile(
    rf'<link[^>]*(?:wp-json|oembed|/feed/|comments/feed|xmlrpc\.php|'
    rf'rel={Q}(?:EditURI|shortlink|alternate|wlwmanifest){Q})[^>]*>\s*', re.I)

problems: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        problems.append(msg)


def normalize_page(path: pathlib.Path, prefix: str) -> dict:
    text = original = read(path)
    c: dict[str, int] = {}

    # 0a. Repair wget's doubled host on &quot;-escaped url() values. The lazy
    # quantifier matters: the sub-page form carries the slug between the host
    # and the escaped quote, and a greedy match swallows the real URL.
    text, c['unmangle'] = re.subn(
        rf'{HOST}/[^()\s]*?&quot;{HOST}/', f'&quot;{LIVE}/', text)

    # 0c. Neutralize the author-archive link; that page is not mirrored.
    text, c['author'] = re.subn(
        rf'<a[^>]+href={Q}{HOST}/author/[^>]*>(.*?)</a>', r'\1', text,
        flags=re.S | re.I)

    # 1-2. Navigation to the four sub-pages, in both /cms/<slug> and pretty form.
    n = 0
    for slug in SLUGS:
        text, k = re.subn(rf'{HOST}/cms/{slug}/?', f'{prefix}{slug}/', text)
        n += k
        text, k = re.subn(rf'{HOST}/{slug}/', f'{prefix}{slug}/', text)
        n += k
    c['nav'] = n

    # 3. Asset references under /cms/ become document-relative (R4).
    text, c['assets'] = re.subn(rf'{HOST}/cms/', f'{prefix}cms/', text)

    # 4. Home link, with or without a trailing slash, and the bare-anchor form.
    n = 0
    text, k = re.subn(rf'(href={Q}){HOST}/?#', r'\1#', text)
    n += k
    text, k = re.subn(rf'(href={Q}){HOST}/?({Q})', rf'\1{prefix or "./"}\2', text)
    c['home'] = n + k

    # 4b. Live-host URLs left inside inline script bodies (R6). Attribute
    # metadata is untouched: this only rewrites inside <script>...</script>,
    # so canonical and og: URLs keep their absolute form.
    def _script_body(m):
        body = re.sub(rf'{HOST}/', prefix or './', m.group(0))
        # Slider Revolution embeds JSON with escaped slashes, so the plain
        # pattern above misses it; one such entry loads a webfont from the
        # live host.
        esc = (prefix or './').replace('/', r'\\/')
        body = re.sub(r'(?:https?:)?\\/\\/www\.zekerwaard\.nl\\/', esc, body)
        return body

    before = text
    text = re.sub(r'<script\b[^>]*>.*?</script>', _script_body, text,
                  flags=re.S | re.I)
    c['script_urls'] = 0 if text == before else 1

    # 5-6. Dead WordPress link elements (R6) and the search form (R9).
    text, c['dead_links'] = DEAD_LINK.subn('', text)
    text, c['search'] = re.subn(
        rf'<form[^>]*class={Q}[^"\']*searchform[^"\']*{Q}[^>]*>.*?</form>\s*',
        '', text, flags=re.S | re.I)

    # LAST. Restore metadata URLs to absolute form. This runs after every
    # rewrite on purpose: the navigation and home rules above would otherwise
    # relativize them, which breaks search and social sharing. An earlier
    # version of this script restored the canonical first and shipped it
    # relative because a later rule clobbered it.
    text, c['canonical'] = re.subn(
        rf'<link rel={Q}canonical{Q}[^>]*>',
        f'<link rel="canonical" href="{CANONICAL[path]}" />', text)
    expect(c['canonical'] == 1,
           f'{path}: expected exactly 1 canonical, found {c["canonical"]}')

    text, c['og_url'] = re.subn(
        rf'(<meta property={Q}og:url{Q} content={Q})[^"\']*',
        rf'\g<1>{CANONICAL[path]}', text)
    expect(c['og_url'] == 1,
           f'{path}: expected exactly 1 og:url, found {c["og_url"]}')

    def _abs_og_image(m):
        url = m.group(2)
        if url.startswith('http'):
            return m.group(0)
        resolved = (path.parent / url).resolve().relative_to(
            pathlib.Path.cwd().resolve())
        return f'{m.group(1)}{LIVE}/{resolved.as_posix()}'

    text, c['og_image'] = re.subn(
        rf'(<meta property={Q}og:image{Q} content={Q})([^"\']*)',
        _abs_og_image, text)

    if text != original:
        path.write_text(text, encoding='utf8')
    return c


def strip_version_suffixes() -> int:
    """Rename *.css@ver=N / *.js@ver=N so the extension is terminal.

    wget's --restrict-file-names=windows turns the query into part of the
    filename, which fixes the 404 but leaves the extension non-terminal.
    GitHub Pages then serves them as application/octet-stream, and a browser
    in standards mode refuses to apply a stylesheet without a CSS MIME type,
    so the site renders unstyled. Font files are left alone: their MIME does
    not gate rendering and several would collide on rename.
    """
    renames: dict[str, str] = {}
    for path in sorted(pathlib.Path('cms').rglob('*')):
        if not path.is_file() or '@' not in path.name:
            continue
        stem, _, _ = path.name.partition('@')
        if not stem.endswith(('.css', '.js')):
            continue
        target = path.with_name(stem)
        if target.exists():
            problems.append(f'rename collision: {path} -> {target}')
            continue
        path.rename(target)
        renames[path.name] = stem

    if not renames:
        return 0
    for f in list(PAGES) + [c for c in pathlib.Path('cms').rglob('*')
                            if c.is_file() and c.suffix in ('.css', '.js')]:
        if not f.exists():
            continue
        try:
            text = original = read(f)
        except (OSError, UnicodeError):
            continue
        text = re.sub(r'(\.(?:css|js))@[^"\'\s)>]*', r'\1', text)
        if text != original:
            f.write_text(text, encoding='utf8')
    return len(renames)


def normalize_css() -> int:
    total = 0
    for css in sorted(pathlib.Path('cms/wp-content/uploads/fusion-styles').glob('*')):
        if not css.is_file():
            continue
        text = original = read(css)
        # fusion-styles sits three levels below cms/.
        text, k = re.subn(rf'{HOST}/cms/', '../../../', text)
        if text != original:
            css.write_text(text, encoding='utf8')
        total += k
    return total


def normalize_robots() -> bool:
    p = pathlib.Path('robots.txt')
    if not p.exists():
        return False
    text = original = read(p)
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
        print(f'{str(path):28} ' + ' '.join(f'{k}={v}' for k, v in c.items()))
    print(f'version-suffixed css/js renamed: {strip_version_suffixes()}')
    print(f'stylesheet absolute urls rewritten: {normalize_css()}')
    print(f'robots.txt sitemap line removed: {normalize_robots()}')
    for p in problems:
        print(f'PROBLEM: {p}', file=sys.stderr)
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
