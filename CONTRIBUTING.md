# Contributing to CrawlForge

Thanks for checking out CrawlForge! The project is still growing, so bug reports, thoughtful suggestions, and small focused pull requests are all useful. You don't need to build a huge feature to help.

## Before you start

- Check existing issues and pull requests to avoid duplicating work.
- For a big change, open an issue first so we can talk through the idea.
- Keep each pull request focused where possible.
- Never commit credentials, cookies, tokens, private crawl results, or other sensitive data.
- Test crawling behavior only with local fixtures or systems you're authorized to assess.

## Set up a development environment

Use Python 3.10 or newer.

### Windows (Command Prompt)

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

### Linux or macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Chromium is needed for the browser-dashboard test. If you're not working on that part, you may not need to install it.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

If you change behavior, add or update tests when you can. If something fails, mention the command and the relevant error output in your pull request.

## Opening a pull request

1. Create a branch for your change.
2. Make your change and add tests where appropriate.
3. Run the relevant tests.
4. Review your diff and remove debug output, secrets, and unrelated edits.
5. Open a pull request explaining what changed, why it helps, and how you tested it.

Mention any limitations or parts you couldn't test.

## A few project preferences

- Prefer readable Python over clever tricks.
- Keep runtime dependencies low unless a new one clearly helps.
- Be careful with crawl scope and request rates.
- Don't call something a confirmed vulnerability unless it has actually been verified.

Thanks for helping make CrawlForge better!
