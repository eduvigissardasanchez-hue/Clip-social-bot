from .models import PLATFORMS


def available_capacity(counts, limit=10):
    if set(counts) != set(PLATFORMS) or any(type(n) is not int or n < 0 for n in counts.values()):
        raise ValueError("Se requieren conteos válidos de las tres colas")
    return max(0, min(limit - counts[p] for p in PLATFORMS))


def missing_platforms(posts):
    by_platform = {p["platform"]: dict(p) for p in posts}
    return [p for p in PLATFORMS if not by_platform.get(p, {}).get("post_id")]


def can_cleanup(posts):
    posts = list(posts)
    return (len(posts) == 3 and {p["platform"] for p in posts} == set(PLATFORMS)
            and all(p["post_id"] and p["state"] == "sent" for p in posts))
