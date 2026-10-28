import re
from html import unescape
from typing import List, Tuple

from .normalization import normalize_text

WORD_RE = re.compile(r"[\w\u0600-\u06FF]+(?:[-/][\w\u0600-\u06FF]+)*", re.UNICODE)
MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
HTML_LINK_RE = re.compile(r"<a\s+[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", re.I | re.S)
HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_markdown(md: str) -> str:
    text = re.sub(r"```.*?```", " ", md, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = MD_IMAGE_RE.sub(lambda m: f" {m.group(1)} ", text)
    text = MD_LINK_RE.sub(lambda m: f" {m.group(1)} ", text)
    text = HTML_LINK_RE.sub(lambda m: f" {HTML_TAG_RE.sub(' ', m.group(2))} ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", " ", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
    text = text.replace("|", " ")
    return normalize_text(unescape(text))


def words(text: str) -> List[str]:
    return WORD_RE.findall(strip_markdown(text))


def headings(md: str) -> List[Tuple[int, str]]:
    out = []
    for line in md.splitlines():
        m = re.match(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m:
            out.append((len(m.group(1)), normalize_text(m.group(2))))
    return out


def paragraphs(md: str) -> List[str]:
    blocks = re.split(r"\n\s*\n", md)
    out = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(re.match(r"^#{1,6}\s+", ln) for ln in lines):
            continue
        if all(ln.startswith("|") and ln.endswith("|") for ln in lines):
            continue
        if all(re.match(r"^[-*_]{3,}$", ln) for ln in lines):
            continue
        cleaned = strip_markdown(block)
        if cleaned:
            out.append(cleaned)
    return out


def markdown_links(md: str):
    links = []
    for m in MD_LINK_RE.finditer(md):
        links.append({"text": normalize_text(m.group(1)), "url": m.group(2), "nofollow": False})
    for m in HTML_LINK_RE.finditer(md):
        tag = m.group(0)
        links.append({
            "text": normalize_text(HTML_TAG_RE.sub(" ", m.group(2))),
            "url": m.group(1),
            "nofollow": bool(re.search(r"rel=['\"][^'\"]*nofollow", tag, re.I)),
        })
    return links


def markdown_images(md: str):
    return [{"alt": normalize_text(m.group(1)), "url": m.group(2)} for m in MD_IMAGE_RE.finditer(md)]
