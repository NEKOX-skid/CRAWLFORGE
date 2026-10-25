"""Scan presets: name -> (description, Options overrides)."""

PRESETS = {
    "quick":    ("Fast shallow map of the site", dict(depth=2, concurrency=10, rate_limit=150)),
    "standard": ("Balanced default: JS + robots/sitemap + tech", dict(depth=3, js_crawl=True, known_files=True, tech_detect=True)),
    "deep":     ("Thorough: depth 5, JS, robots/sitemap, path-climb, forms, secrets, near-dup filter",
                 dict(depth=5, js_crawl=True, known_files=True, path_climb=True, form_extraction=True,
                      tech_detect=True, secrets=True, content_similar=True, filter_similar=True)),
    "api-hunt": ("Find API/JS endpoints: JS parsing, strategy BFS, keep only json/js/php/asp(x)/jsp",
                 dict(depth=4, js_crawl=True, known_files=True, strategy="breadth-first",
                      ext_match=["json", "js", "php", "asp", "aspx", "jsp", "none"])),
    "stealth":  ("Low and slow: 2 workers, 2 req/s, 1s delay, retries off",
                 dict(depth=3, concurrency=2, rate_limit=2, host_rate_limit=2, delay=1.0, retries=0)),
}


def apply(opts, name: str):
    desc, over = PRESETS[name]
    for k, v in over.items():
        setattr(opts, k, list(v) if isinstance(v, list) else v)
    return desc
