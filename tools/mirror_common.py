"""Shared constants and helpers for the static-mirror tooling."""
import pathlib
import re

LIVE = 'https://www.zekerwaard.nl'
HOST = r'https?://www\.zekerwaard\.nl'
SLUGS = ('verzekeringen', 'hypotheken', 'over', 'contact')

# page path -> prefix that reaches the repo root from that page
PAGES: dict[pathlib.Path, str] = {
    pathlib.Path('index.html'): '',
    **{pathlib.Path(f'{s}/index.html'): '../' for s in SLUGS},
}

# Canonical URL each page must declare. wget --convert-links rewrites these to
# a relative path (and to the wrong page), so they are restored from here.
CANONICAL: dict[pathlib.Path, str] = {
    pathlib.Path('index.html'): f'{LIVE}/',
    **{pathlib.Path(f'{s}/index.html'): f'{LIVE}/{s}/' for s in SLUGS},
}

# WordPress emits head tags with either quote style, so every pattern that
# matches markup must accept both. Missing this made the first round of gates
# blind to single-quoted attributes.
Q = r'["\']'


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding='utf8', errors='replace')


def attr_urls(html: str, attrs: str = 'src|href') -> set[str]:
    """Every URL in the named attributes, in either quote style, plus srcset
    candidates and inline style url() values."""
    found: set[str] = set()
    for q in ('"', "'"):
        found |= set(re.findall(rf'(?:{attrs})={q}([^{q}]+){q}', html))
    for q in ('"', "'"):
        for ss in re.findall(rf'srcset={q}([^{q}]+){q}', html):
            found |= {c.strip().split()[0] for c in ss.split(',') if c.strip()}
    for raw in re.findall(r'url\(\s*(?:&quot;|["\'])?([^)\s]+?)(?:&quot;|["\'])?\s*\)', html):
        found.add(raw)
    cleaned = set()
    for u in found:
        u = u.strip().removesuffix('&quot;').removeprefix('&quot;').strip('"\'')
        if '${' in u or '{{' in u:      # JS template literal, not an asset
            continue
        if u and not u.startswith(('#', 'data:', 'javascript:', 'mailto:', 'tel:')):
            cleaned.add(u)
    return cleaned
