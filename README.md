# CrawlForge

CrawlForge is a small, scope-aware web crawler written in Python. It can be used from the command line, an interactive terminal menu, or a local browser-based dashboard.

The project uses Python's standard library for its runtime; no third-party package is needed to run the crawler.

> **Use responsibly:** crawl only websites you own or have explicit permission to test. Respect the target's policies, rate limits, and availability. CrawlForge is a discovery tool, not a vulnerability scanner or a substitute for a security review.

## Features

- Depth-first and breadth-first crawling with depth, duration, and per-domain limits
- Scope controls and URL/status/extension filters
- HTML link and form discovery, with optional JavaScript endpoint extraction
- Optional robots.txt and sitemap discovery
- Request pacing, retries, custom headers, and proxy support
- JSON Lines output, CSV/TXT exports, and standalone HTML reports
- Resume state and endpoint-diff support
- Interactive terminal menu and localhost-only web dashboard

CrawlForge does not submit POST forms. Its optional secret-pattern detection only flags possible matches; it does not validate credentials or tokens.

## Requirements

- Python 3.10 or newer
- A terminal for command-line and menu use
- A modern browser for the optional local dashboard

## Install from a checkout

```bash
git clone https://github.com/OWNER/CrawlForge.git
cd CrawlForge
python -m pip install -e .
```

Replace `OWNER` with the GitHub account or organization that hosts the repository.

On Windows, use `py` instead of `python` if that is how your Python installation is configured.

## Quick start

Open the interactive menu:

```bash
python -m crawlforge
```

Crawl a site you are authorized to test:

```bash
python -m crawlforge -u https://example.com -preset standard -j -o results.jsonl
```

Start the local dashboard:

```bash
python -m crawlforge -web
```

The dashboard binds to `127.0.0.1` by default and prints a tokenized local URL. Keep it local; do not expose it to a network or the public internet.

Show command-line options:

```bash
python -m crawlforge -h
```

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

The browser-based UI test additionally needs Playwright and its Chromium browser. Install the optional test dependency and browser with:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

## Presets

| Preset | Purpose |
| --- | --- |
| `quick` | A shallow first look at a site |
| `standard` | Balanced discovery with optional JavaScript and known-file checks |
| `deep` | Broader discovery with additional extraction and deduplication |
| `api-hunt` | Emphasizes API-like and JavaScript endpoints |
| `stealth` | Uses lower request concurrency and pacing; not an anonymity feature |

Presets are starting points, not permission to ignore the target's rules. Tune depth and request rates for the environment you are testing.

## Output and privacy

Crawl results can contain URLs, query parameters, form fields, technology fingerprints, and strings that resemble secrets. Treat output files and reports as potentially sensitive. Review them before sharing or committing them, and never commit real tokens, cookies, credentials, or private scan results.

The dashboard is designed for local use. Its token and host checks are additional safeguards, not a guarantee that exposing it remotely is safe.

## Known limitations

- No headless-browser rendering; JavaScript discovery is based on static extraction.
- POST forms are identified but not submitted.
- Secret-pattern matches are not checked against providers.
- Crawl results depend on site structure, responses, and configured limits; missing endpoints are possible.
- Only use the tool against systems you are authorized to test.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for local checks and contribution notes. Please report security issues privately as described in [SECURITY.md](SECURITY.md).

## License

CrawlForge is distributed under the MIT License. See [LICENSE](LICENSE).
