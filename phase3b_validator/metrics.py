import re
from urllib.parse import urlparse

from .markdown_tools import headings, markdown_images, markdown_links, paragraphs, strip_markdown, words
from .normalization import lower, normalize_slug, normalize_text


def count_exact(text: str, keyword: str) -> int:
    hay = lower(text)
    needle = lower(keyword)
    if not needle:
        return 0
    return len(re.findall(re.escape(needle), hay, flags=re.I))


def contains(text: str, keyword: str) -> bool:
    return count_exact(text, keyword) > 0


def classify_url(url: str, site_domain: str) -> str:
    url = (url or "").strip()
    if not url:
        return "unknown"
    if url.startswith(("/", "./", "../", "#")):
        return "internal"
    p = urlparse(url if "://" in url else "https://" + url)
    host = (p.hostname or "").casefold()
    site = site_domain.casefold().lstrip("www.")
    host2 = host.lstrip("www.")
    return "internal" if host2 == site or host2.endswith("." + site) else "external"


def build_metrics(bundle: dict, md: str, site_domain: str) -> dict:
    keyword = bundle["seo"]["focus_keyword"]
    seo_title = bundle["snippet"].get("seo_title", "")
    meta = bundle["snippet"].get("meta_description", "")
    slug = bundle["page"].get("slug", "")

    plain = strip_markdown(md)
    word_list = words(md)
    word_count = len(word_list)
    keyword_count = count_exact(plain, keyword)
    density = round((keyword_count / word_count * 100), 2) if word_count else 0.0

    first_n = max(1, int((word_count * 0.10) + 0.999999)) if word_count else 0
    first_10_text = " ".join(word_list[:first_n])

    hs = headings(md)
    subheads = [text for level, text in hs if 2 <= level <= 6]
    ps = paragraphs(md)
    paragraph_counts = [len(words(p)) for p in ps]

    collected_links = []
    for item in bundle.get("links", {}).get("internal", []):
        collected_links.append({**item, "declared": "internal"})
    for item in bundle.get("links", {}).get("external", []):
        collected_links.append({**item, "declared": "external"})
    collected_links.extend(markdown_links(md))

    # Deduplicate the same logical link when it is both declared in the bundle
    # and physically present in Markdown. This changes only audit counts; the
    # frozen binary scoring rule remains "at least one internal/external link".
    internal = []
    external = []
    seen = set()
    for link in collected_links:
        kind = classify_url(link.get("url", ""), site_domain)
        if kind not in {"internal", "external"}:
            continue
        key = (kind, (link.get("url") or "").strip(), bool(link.get("nofollow", False)))
        if key in seen:
            continue
        seen.add(key)
        (internal if kind == "internal" else external).append(link)

    declared_images = bundle.get("images", [])
    md_images = markdown_images(md)
    image_count = max(len(declared_images), len(md_images))
    image_alts = [i.get("alt", "") for i in declared_images] + [i.get("alt", "") for i in md_images]

    title_pos = lower(seo_title).find(lower(keyword)) if keyword else -1

    return {
        "word_count": word_count,
        "keyword_count": keyword_count,
        "keyword_density": density,
        "keyword_in_title": contains(seo_title, keyword),
        "keyword_in_meta": contains(meta, keyword),
        "keyword_in_permalink": normalize_slug(keyword) in normalize_slug(slug),
        "keyword_in_first_10_percent": contains(first_10_text, keyword),
        "keyword_in_content": contains(plain, keyword),
        "keyword_in_subheadings": any(contains(h, keyword) for h in subheads),
        "keyword_in_image_alt": any(contains(a, keyword) for a in image_alts),
        "permalink_chars": len(normalize_text(slug)),
        "internal_links": len(internal),
        "external_links": len(external),
        "external_dofollow_links": sum(1 for x in external if not x.get("nofollow", False)),
        "max_paragraph_words": max(paragraph_counts) if paragraph_counts else 0,
        "media_count": image_count,
        "title_keyword_position": title_pos,
        "title_chars": len(normalize_text(seo_title)),
        "subheadings": subheads,
    }
