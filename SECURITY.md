# Security Policy

Thanks for helping keep CrawlForge and its users safer.

CrawlForge is a website discovery and crawling tool. Use it only on systems you own or have clear permission to test.

## Reporting a security issue

Please **don't post exploit details, credentials, access tokens, private URLs, or sensitive target data in a public GitHub issue**.

If GitHub's **Private vulnerability reporting** option is enabled for this repository, use it to send a report privately. If you can't see that option, contact the maintainer through a private channel listed on their GitHub profile. A normal public issue is not private.

When possible, include:
- A short description and the possible impact
- The affected version or commit
- Steps to reproduce the issue, preferably using a local test case
- Relevant logs with secrets and personal information removed

Please include enough detail to understand what happened without exposing someone else's private data.

## Handling crawl results

Crawl results may include internal paths, query parameters, form metadata, or strings that resemble secrets. Store them carefully and review them before sharing. Never commit real credentials, cookies, tokens, or private scan results.

## Responsible use

Reports about vulnerabilities in CrawlForge itself are welcome. If you find an issue on a third-party site while using CrawlForge, follow that site's security reporting process and stay within its authorized scope.
