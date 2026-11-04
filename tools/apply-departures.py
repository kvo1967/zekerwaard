#!/usr/bin/env python3
"""Apply the mirror's deliberate departures from the live site (plan U4).

Run from the repo root after tools/normalize-mirror.py. Idempotent.

Permanent (survives cut-over):
  R7 - remove the Contact Form 7 block, its reCAPTCHA and its scripts. The
       form needs PHP; the contact page already shows full contact details.
  R9 - handled in normalize-mirror.py (search form).

Preview-only (reversed at cut-over by plan U6, R12):
  R10 - add a robots noindex directive so the preview cannot be indexed
        and compete with the live site.
  R11 - swap the Google Maps embed for a static image, because the live
        API key is referrer-restricted to zekerwaard.nl.

R8 is deliberately a no-op: the six placeholder menu items stay exactly as
the live site has them.
"""
import re, pathlib, sys

PAGES = [pathlib.Path(p) for p in (
    'index.html', 'verzekeringen/index.html', 'hypotheken/index.html',
    'over/index.html', 'contact/index.html')]

MAP_IMG = ('<img src="{prefix}assets/map-preview.png" '
           'alt="Kaart: Zekerwaard, Middenweg 287, 1701 GD Heerhugowaard" '
           'style="height:440px;width:100%;object-fit:cover;display:block;" '
           'loading="lazy" decoding="async" />')


def cut_balanced_div(text: str, start_pat: str) -> tuple[str, int]:
    """Remove each <div> matching start_pat together with its matching close."""
    removed = 0
    while True:
        m = re.search(start_pat, text)
        if not m:
            return text, removed
        depth = 0
        for t in re.finditer(r'<div\b|</div>', text[m.start():]):
            depth += 1 if t.group(0).startswith('<div') else -1
            if depth == 0:
                text = text[:m.start()] + text[m.start() + t.end():]
                removed += 1
                break
        else:
            print('   unbalanced div, left in place', file=sys.stderr)
            return text, removed


def apply(path: pathlib.Path, prefix: str) -> dict:
    text = original = path.read_text(encoding='utf8', errors='replace')
    c = {}

    # R7 - Contact Form 7 block and its scripts.
    text, c['cf7_block'] = cut_balanced_div(text, r'<div class="wpcf7[ "]')
    text, c['cf7_script'] = re.subn(
        r'<script[^>]*(?:recaptcha|wpcf7)[^>]*>.*?</script>\s*', '',
        text, flags=re.S | re.I)
    text, k = re.subn(
        r'<script[^>]*(?:recaptcha|wpcf7)[^>]*/?>\s*', '', text, flags=re.I)
    c['cf7_script'] += k
    text, c['cf7_css'] = re.subn(
        r'<link[^>]*(?:contact-form-7|wpcf7)[^>]*>\s*', '', text, flags=re.I)

    # R11 - static map in place of the live embed (preview only).
    text, c['map'] = re.subn(
        r'<div class="shortcode-map[^"]*"[^>]*></div>',
        MAP_IMG.format(prefix=prefix), text)

    # R10 - noindex (preview only). Extend the existing robots meta.
    if 'noindex' not in text:
        text, c['noindex'] = re.subn(
            r"(<meta name=['\"]robots['\"] content=['\"])",
            r"\1noindex, nofollow, ", text, count=1)
    else:
        c['noindex'] = 0

    if text != original:
        path.write_text(text, encoding='utf8')
    return c


def main() -> int:
    for p in PAGES:
        if not p.exists():
            print(f'missing page: {p}', file=sys.stderr)
            return 1
        prefix = '' if p.parent == pathlib.Path('.') else '../'
        c = apply(p, prefix)
        print(f'{str(p):28} cf7_block={c["cf7_block"]} '
              f'cf7_script={c["cf7_script"]} cf7_css={c["cf7_css"]} '
              f'map={c["map"]} noindex={c["noindex"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
