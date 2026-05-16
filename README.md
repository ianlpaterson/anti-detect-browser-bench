# anti-detect-browser-bench

Reproducible bench harness for evaluating anti-detect browsers (vanilla Playwright, Patchright, CloakBrowser, Camoufox) against bot-detection panels, TLS fingerprint endpoints, and real-world hostile targets.

Each browser runs in its own subprocess because `sync_playwright()` is single-shot per Python process — patchright, cloakbrowser, and camoufox all ship their own Playwright forks and they fight when run in the same process.

Headed mode by default. Designed for macOS arm64 with a residential IP, but works anywhere Playwright runs.

## Quick start

```bash
git clone https://github.com/ianlpaterson/anti-detect-browser-bench
cd anti-detect-browser-bench
python3 -m venv .venv && . .venv/bin/activate
pip install playwright patchright cloakbrowser camoufox curl_cffi pyyaml
python -m playwright install chromium
python -m patchright install chromium
python -m camoufox fetch
python -c "import cloakbrowser; cloakbrowser.ensure_binary()"

# Run all four browsers against all targets in targets.yaml
python bench.py vanilla patchright cloak camofox

# One browser
python bench.py cloak

# Headless
python bench.py cloak --headless
```

Results write to `results/<target-slug>/<browser>.{png,html}` plus `results/records-<browser>.json` and a combined `results/run-<ts>.json`.

## Targets

`targets.yaml` ships with 16 targets in three groups:

- **JS-layer detection panels** — bot.sannysoft.com, abrahamjuliot.github.io/creepjs, browserleaks.com, browserscan.net/bot-detection, pixelscan.net (bot + fp checks). Standard headless / webdriver / canvas / WebGL detection.
- **TLS fingerprint endpoints** — tls.peet.ws, tls.browserleaks.com. Return the actual JA3/JA4/peetprint hash of whichever browser hits them.
- **Real-world hostile** — nowsecure.nl (Cloudflare Turnstile), crunchbase.com, canadianinsider.com, sedarplus.ca, ceo.ca, stockwatch.com, newsfilecorp.com.

Add your own target as a YAML block:

```yaml
  - name: my-target
    url: https://example.com/
    settle_s: 6
    timeout_ms: 60000
    extract:
      score: ".some-selector"
```

## Add a browser

Drop a module in `browsers/` exposing a `session(headless: bool)` context manager that yields a Playwright-compatible Browser object. See `browsers/vanilla.py` for the minimal shape.

## What we found

See the writeup: TBD (link to blog post).

Headline: of the four browsers, only Camoufox rewrites TLS, but on real-world Cloudflare-protected sites CloakBrowser actually passes more gates than Camoufox because Camoufox's Windows-UA-on-macOS spoof gets caught by consistency checks. No tool tested auto-resolves Cloudflare Turnstile. F5 BIG-IP ASM (SEDAR+) blocks everything.

## License

MIT
