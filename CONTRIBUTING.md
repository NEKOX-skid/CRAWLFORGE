# Contributing

Thanks for considering a contribution to CrawlForge.

## Before opening a change

1. Keep changes focused and explain the problem they solve.
2. Add or update tests for behavior changes.
3. Avoid adding runtime dependencies unless there is a clear need.
4. Never include credentials, cookies, private crawl results, or other sensitive data in commits.
5. Only test against local fixtures or systems you are authorized to assess.

## Local checks

```bash
python -m unittest discover -s tests -v
```

For the browser-based dashboard test, install the optional development dependencies and Chromium:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Please describe what you changed, how you tested it, and any known limitations in your pull request.
