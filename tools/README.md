# Mirror tooling

The site in this repo is a static mirror of the rendered zekerwaard.nl. The live
site is the reference for correctness, except for the deliberate departures
recorded in `docs/plans/2026-11-04-1652-feat-wordpress-static-mirror-plan.md`.

There is no test runner. Proof is `tools/verify-mirror.py` plus, for the
homepage slider, one comparison against the live page in a browser.

## Refreshing one page after the live site changes

The capture is a point-in-time freeze, so any edit in WordPress makes the mirror
stale until it is refreshed. Refreshing the homepage is the worked example; the
other pages differ only in the URL and the file copied.

1. **Check what actually drifted.** Fetch the live page and diff its visible text
   against the committed copy. A refresh is for drift you have looked at — if
   anything beyond the expected change shows up, stop and review it rather than
   installing a page nobody has read.

2. **Capture into a throwaway directory**, never over the repo. Capturing in
   place re-downloads the version-suffixed asset files alongside the terminal
   copies an earlier run renamed, and every one of them then reports a rename
   collision.

   ```bash
   mkdir /tmp/zw-capture && cd /tmp/zw-capture
   wget --page-requisites --convert-links --no-host-directories \
        --restrict-file-names=windows https://www.zekerwaard.nl/
   ```

   Exit status 8 is expected: a handful of requisites 404 on the live site too.
   Every flag matters. `--page-requisites` without `--recursive` avoids the
   `/cms/<slug>` menu links, which 301-redirect and would otherwise be stored as
   extensionless files that GitHub Pages serves as `application/octet-stream`.
   `--no-host-directories` puts the page at the root instead of under a hostname
   directory. `--restrict-file-names=windows` remaps the `?ver=` query strings
   into legal static filenames.

3. **Capture the assets Slider Revolution builds in JavaScript.** `wget` cannot
   find these: the runtime concatenates them from `SR7.E.plugin_url` at load
   time, so they appear nowhere in the HTML. The page declares the list itself —
   read `SR7.E.css` out of the captured page and map each entry with
   `name.replace("css", "sr7.") + ".css"`:

   ```bash
   B=https://www.zekerwaard.nl/cms/wp-content/plugins/revslider/public/css
   for f in sr7.lp.css sr7.btns.css sr7.filters.css sr7.nav.css sr7.media.css; do
     curl -fsS -o "<repo>/cms/wp-content/plugins/revslider/public/css/$f" "$B/$f"
   done
   curl -fsS -o "<repo>/cms/wp-content/plugins/revslider/public/css/preloaders/t4.css" \
        "$B/preloaders/t4.css"      # t<N> matches the slider's configured plType
   ```

   Re-read `SR7.E.css` each refresh rather than trusting this list — a plugin
   update can add an entry. `SR7.E.modules` and `SR7.E.libs` are declared the
   same way but are bundled into `sr7.js`; only `page.js`, `defaults.js`,
   `migration.js` and `libs/webgl.js` exist separately on the live host, and
   nothing requested them at the last refresh. Leave them out unless step 6
   shows a 404 for one — `webgl.js` alone is 645KB.

   Missing these is invisible to every gate and produces a hero that shows a
   preloader forever: the stylesheets load in a chain, so each one you add
   unblocks the request for the next.

4. **Copy only the page** into the repo and leave `cms/` alone:

   ```bash
   cp /tmp/zw-capture/index.html <repo>/index.html
   ```

   The asset tree is not re-captured. Re-check that assumption when the live
   plugins change: at the last refresh the slider runtime was byte-identical to
   the mirrored copy and the homepage's generated Avada stylesheet hash was
   unchanged, so only the page's markup had moved.

5. **Replay the pipeline**, from the repo root, in this order:

   ```bash
   python3 tools/normalize-mirror.py    # document-relative refs, dead WP plumbing, search form
   python3 tools/apply-departures.py    # contact form, static map, noindex
   python3 tools/verify-mirror.py       # disk gates, then gates against a served copy
   ```

   Both passes are idempotent and both run over all five pages; the four you did
   not re-capture come out byte-identical.

6. **Compare the homepage hero against live in a browser, with the server's
   request log in view.** The gates cannot see a slider that renders but
   animates wrongly, and they cannot see a runtime-constructed URL at all.
   Serve the repo (`python3 -m http.server 8787 > access.log 2>&1`), load the
   page, then check the log for any non-200 — that is the only thing that
   catches a missing lazily-loaded asset. Put the page beside
   `https://www.zekerwaard.nl/`
   at a desktop and a phone width. Watch the layer entry order and timing, the
   autoplay cycle, the navigation controls, and whether the cycle passes through
   an empty frame.

   On a mismatch, restore the committed page rather than shipping it. The
   pre-deletion database dump — kept outside this repo, because it carries
   credentials and user records — holds the original slider record and is the
   reference for deciding whether the live site itself regressed.
