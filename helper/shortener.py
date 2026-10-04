"""AdLinkFly-compatible URL shortener helper.

Ported from Multi-FileStoreBot utils/shortener.py.
Used by worker bots when shortener gate is enabled.
"""
import logging

import aiohttp

log = logging.getLogger(__name__)


async def shorten_url(url: str, api_key: str, domain: str) -> str:
    """Shorten a URL using an AdLinkFly-compatible shortener API.

    Args:
        url:     The URL to shorten.
        api_key: The user's shortener API key.
        domain:  The shortener domain (e.g. 'example.com').

    Returns:
        The shortened URL, or the original URL on any failure.
    """
    if not api_key or not domain:
        return url

    if not domain.startswith("http"):
        domain = f"https://{domain}"
    domain = domain.rstrip("/")

    api_url = f"{domain}/api"
    params = {"api": api_key, "url": url}

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                api_url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    try:
                        data = await r.json(content_type=None)
                        if data.get("status") == "success":
                            short = data.get("shortenedUrl", "")
                            if short:
                                log.info(f"Shortened: {url[:50]}…")
                                return short
                    except Exception:
                        pass
                    text = await r.text()
                    if text.strip().startswith("http"):
                        return text.strip()
                log.warning(f"Shortener returned HTTP {r.status}")
    except aiohttp.ClientError as e:
        log.error(f"Shortener network error: {e}")
    except Exception as e:
        log.error(f"Shortener error: {e}")
    return url


# Alias used by multi/engine.py
get_short_link = shorten_url
