# CrawlForge

CrawlForge is a Python web crawler I built for exploring a website's structure and collecting useful links and endpoint information. You can run it in a terminal, use the interactive menu, or open the local browser dashboard.

The idea is to keep it straightforward: choose a target you're allowed to test, set crawl limits, run it, and review the results.

> **Use it responsibly.** Only crawl websites you own or have clear permission to test. CrawlForge is a discovery tool, not a magic vulnerability scanner, and its results should be checked rather than blindly trusted.

## Features

- Depth-first and breadth-first crawling
- Scope rules, depth and time limits, and per-domain limits
- URL, status-code, and extension filters
- HTML link and form discovery
- Optional static extraction of endpoint-like strings from JavaScript
- Optional `robots.txt` and sitemap discovery
- Request pacing, retries, custom headers, and proxy support
- JSON Lines, CSV, TXT, and standalone HTML report exports
- Saved crawl state and endpoint comparison
- Interactive terminal menu and local browser dashboard

CrawlForge does not submit POST forms. Its secret-pattern checks only flag strings that might be sensitive; they do not verify whether a token or credential is real.

## Requirements

- Python 3.10 or newer
- A terminal
- A modern browser for the optional dashboard

The crawler uses Python's standard library at runtime, so you don't need a long list of packages just to run it.

## Install

```bash
git clone https://github.com/NEKOX-skid/CRAWLFORGE.git
cd CRAWLFORGE
python -m pip install -e .
```

On Windows, use `py` instead of `python` if that's how Python is configured on your PC.

## Quick start

Open the interactive menu:

```bash
python -m crawlforge
```

Crawl a site you're authorized to test:

```bash
python -m crawlforge -u https://example.com -preset standard -j -o results.jsonl
```

Replace `https://example.com` with a site you own or have permission to test. Keep the depth and request rate reasonable.

Start the local browser dashboard:

```bash
python -m crawlforge -web
```

By default, the dashboard binds to `127.0.0.1` on port `8787` and prints a URL containing a token. Open that exact URL in your browser and keep the terminal window open while using the dashboard.

**Keep the dashboard local.** Don't expose it to the public internet or an untrusted network, and don't share its tokenized URL.

Show command-line options:

```bash
python -m crawlforge -h
```

## Presets

| Preset | Purpose |
| --- | --- |
| `quick` | A shallow first look |
| `standard` | Balanced discovery with optional extra checks |
| `deep` | Broader discovery with more extraction and deduplication |
| `api-hunt` | Emphasizes API-like and JavaScript endpoints |
| `stealth` | Uses lower concurrency and slower pacing; it does **not** make you anonymous |

Presets don't override a site's rules or give you permission to scan it.

## Tests

Run the standard test suite:

```bash
python -m unittest discover -s tests -v
```

For the browser dashboard test, install the optional development requirements and Chromium:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

## Results and privacy

Crawl results can contain URLs, query parameters, form details, technology fingerprints, and strings that look like secrets. Treat reports as potentially sensitive. Review them before sharing, and never commit real credentials, cookies, tokens, or private scan results to Git.

## Known limitations

- Pages aren't rendered in a headless browser; JavaScript discovery uses static extraction.
- POST forms are found but not submitted.
- Possible secret matches aren't verified with external services.
- Results depend on the site's structure, responses, and your configured limits, so some endpoints may be missed.
- CrawlForge isn't a replacement for a proper security assessment.

## Contributing and security

Suggestions, bug reports, and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) before contributing. For security issues, read [SECURITY.md](SECURITY.md) and avoid posting sensitive details publicly.

## License

CrawlForge is released under the MIT License. See [LICENSE](LICENSE).

