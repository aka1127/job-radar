"""The one HTTP identity of the engine. An honest crawler user agent by default (robots.txt is checked before any
page is opened, see careers.allowed); `crawl.user_agent` in config.yaml replaces it when a source needs another."""
DEFAULT_UA = "Mozilla/5.0 (compatible; JobRadar/1.0; +https://github.com/aka1127/job-radar)"
UA = {"User-Agent": DEFAULT_UA}  # shared dict, read at request time: configure() changes it for every module


def configure(cfg: dict | None):
    """Apply the engine config (called when a candidate is loaded)."""
    crawl = (cfg or {}).get("crawl") or {}
    UA["User-Agent"] = str(crawl.get("user_agent") or DEFAULT_UA)
