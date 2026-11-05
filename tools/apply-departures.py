#!/usr/bin/env python3
"""Apply the mirror's deliberate departures from the live site (plan U4).

Run from the repo root after tools/normalize-mirror.py. Idempotent.

Permanent (survives cut-over):
  R7 - remove the Contact Form 7 block and every script it loads. The form
       needs PHP; the contact page already shows full contact details. One of
       those scripts also bakes a live wp-json endpoint into the page.

Preview-only (reversed at cut-over by plan U6, R12):
  R10 - add a robots noindex directive so the preview cannot be indexed and
        compete with the live site.
  R11 - replace the Google Maps embed, its loader and its initializer with a
        static image. Removing the loader is the point: it carries the live
        API key, which is referrer-restricted to zekerwaard.nl and would throw
        on the preview origin.

R8 is deliberately a no-op: the six placeholder menu items stay as they are.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mirror_common import PAGES, Q, read  # noqa: E402

# Scripts Contact Form 7 and its reCAPTCHA pull in, by element id.
CF7_SCRIPT_IDS = (
    'avada-contact-form-7-js', 'contact-form-7-js', 'contact-form-7-js-before',
    'contact-form-7-js-translations', 'google-recaptcha-js', 'swv-js',
    'wpcf7-recaptcha-js', 'wpcf7-recaptcha-js-before',
)
# Google Maps loader and the Fusion initializer it feeds.
MAP_SCRIPT_IDS = (
    'google-maps-api-js', 'jquery-fusion-maps-js', 'jquery-fusion-maps-js-extra',
)
MAP_IMG = ('<img src="{prefix}assets/map-preview.png" '
           'alt="Kaart: Zekerwaard, Middenweg 287, 1701 GD Heerhugowaard" '
           'style="height:440px;width:100%;object-fit:cover;display:block;" '
           'loading="lazy" decoding="async" />')

problems: list[str] = []


def drop_scripts_by_id(text: str, ids: tuple[str, ...]) -> tuple[str, int]:
    n = 0
    for sid in ids:
        text, k = re.subn(
            rf'<script[^>]*id={Q}{re.escape(sid)}{Q}[^>]*>.*?</script>\s*',
            '', text, flags=re.S | re.I)
        n += k
        text, k = re.subn(
            rf'<script[^>]*id={Q}{re.escape(sid)}{Q}[^>]*/?>\s*', '', text,
            flags=re.I)
        n += k
    return text, n


def cut_balanced_div(text: str, start_pat: str) -> tuple[str, int]:
    """Remove each <div> matching start_pat with its matching close tag.

    Depth counting ignores comments and script bodies, where literal <div>
    text would otherwise skew the count.
    """
    removed = 0
    while True:
        m = re.search(start_pat, text)
        if not m:
            return text, removed
        masked = re.sub(r'<!--.*?-->|<script\b.*?</script>',
                        lambda x: ' ' * len(x.group(0)), text, flags=re.S | re.I)
        depth = 0
        for t in re.finditer(r'<div\b|</div>', masked[m.start():]):
            depth += 1 if t.group(0).startswith('<div') else -1
            if depth == 0:
                text = text[:m.start()] + text[m.start() + t.end():]
                removed += 1
                break
        else:
            problems.append('unbalanced div; block left in place')
            return text, removed


def apply(path: pathlib.Path, prefix: str) -> dict:
    text = original = read(path)
    c: dict[str, int] = {}

    # R7 - the form block, its scripts and its stylesheet.
    text, c['cf7_block'] = cut_balanced_div(text, rf'<div class={Q}wpcf7[ "\']')
    text, c['cf7_script'] = drop_scripts_by_id(text, CF7_SCRIPT_IDS)
    text, c['cf7_css'] = re.subn(
        rf'<link[^>]*(?:contact-form-7|wpcf7)[^>]*>\s*', '', text, flags=re.I)

    # R11 - static map, and the loader/initializer that would still call Google.
    text, c['map_div'] = re.subn(
        rf'<div class={Q}shortcode-map[^"\']*{Q}[^>]*></div>',
        MAP_IMG.format(prefix=prefix), text)
    text, c['map_script'] = drop_scripts_by_id(text, MAP_SCRIPT_IDS)
    text, k = re.subn(r'<script[^>]*>(?:(?!</script>).)*?fusion_run_map'
                      r'(?:(?!</script>).)*?</script>\s*', '', text, flags=re.S | re.I)
    c['map_script'] += k

    # R10 - noindex. Assert on the robots meta itself, not a bare substring:
    # the word "noindex" can appear anywhere in a page.
    robots = re.search(rf'<meta name={Q}robots{Q}[^>]*>', text, re.I)
    if robots and 'noindex' not in robots.group(0):
        text, c['noindex'] = re.subn(
            rf'(<meta name={Q}robots{Q} content={Q})', r'\1noindex, nofollow, ',
            text, count=1)
    elif robots:
        c['noindex'] = 0          # already carries noindex
    else:
        c['noindex'] = 0
        problems.append(f'{path}: no robots meta to extend')

    if not re.search(rf'<meta name={Q}robots{Q}[^>]*noindex', text, re.I):
        problems.append(f'{path}: page has no noindex directive')

    if text != original:
        path.write_text(text, encoding='utf8')
    return c


def main() -> int:
    for path, prefix in PAGES.items():
        if not path.exists():
            print(f'missing page: {path}', file=sys.stderr)
            return 1
        c = apply(path, prefix)
        print(f'{str(path):28} ' + ' '.join(f'{k}={v}' for k, v in c.items()))
    for p in problems:
        print(f'PROBLEM: {p}', file=sys.stderr)
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
