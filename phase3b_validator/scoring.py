import math


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def density_score(density: float, cfg: dict) -> int:
    t = cfg["thresholds"]["keyword_density"]
    if density < t["fail_below"] or density > t["fail_above"]:
        return 0
    if t["fair_min"] <= density <= t["fair_max"]:
        return int(t["fair_score"])
    if t["good_min"] <= density <= t["good_max"]:
        return int(t["good_score"])
    return int(t["best_score"])


def media_score(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count == 2:
        return 2
    if count == 3:
        return 4
    return 6


def content_length_score(word_count: int, cfg: dict) -> int:
    """Rank Math public analyzer graduated content-length scoring.

    Public boundaries:
      >=2500 -> 8
      >=2000 -> 5
      >=1500 -> 4
      >=1000 -> 3
      >=600  -> 2
      <600   -> 0
    """
    b = cfg["thresholds"]["content_length_boundaries"]
    ordered = sorted(
        ((int(v["boundary"]), int(v["score"])) for v in b.values()),
        reverse=True,
    )
    for boundary, score in ordered:
        if word_count >= boundary:
            return score
    return 0


def score_metrics(m: dict, cfg: dict) -> dict:
    w = cfg["weights"]
    t = cfg["thresholds"]

    title_half = m["title_chars"] / 2 if m["title_chars"] else 0
    title_start = m["title_keyword_position"] >= 0 and m["title_keyword_position"] < title_half

    earned = {
        "keyword_in_title": w["keyword_in_title"] if m["keyword_in_title"] else 0,
        "keyword_in_meta_description": w["keyword_in_meta_description"] if m["keyword_in_meta"] else 0,
        "keyword_in_permalink": w["keyword_in_permalink"] if m["keyword_in_permalink"] else 0,
        "keyword_in_first_10_percent": w["keyword_in_first_10_percent"] if m["keyword_in_first_10_percent"] else 0,
        "keyword_in_content": w["keyword_in_content"] if m["keyword_in_content"] else 0,
        "keyword_in_subheadings": w["keyword_in_subheadings"] if m["keyword_in_subheadings"] else 0,
        "keyword_density": density_score(m["keyword_density"], cfg),
        "keyword_in_image_alt": w["keyword_in_image_alt"] if m["keyword_in_image_alt"] else 0,
        "permalink_length": w["permalink_length"] if m["permalink_chars"] <= t["permalink_max_chars"] else 0,
        "internal_link": w["internal_link"] if m["internal_links"] > 0 else 0,
        "external_link": w["external_link"] if m["external_links"] > 0 else 0,
        "external_dofollow": w["external_dofollow"] if m["external_dofollow_links"] > 0 else 0,
        "short_paragraphs": w["short_paragraphs"] if m["max_paragraph_words"] <= t["paragraph_max_words"] else 0,
        "media_assets": min(w["media_assets"], media_score(m["media_count"])),
        "title_start_with_keyword": w["title_start_with_keyword"] if title_start else 0,
        "content_length": content_length_score(m["word_count"], cfg),
    }

    max_scores = dict(w)
    max_total = sum(max_scores.values())
    earned_total = sum(earned.values())
    score = _round_half_up((earned_total / max_total) * 100) if max_total else 0

    return {
        "score": score,
        "earned_total": earned_total,
        "max_total": max_total,
        "earned": earned,
        "max_scores": max_scores,
    }
