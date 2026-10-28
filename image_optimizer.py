from pathlib import Path
import os
from PIL import Image


CANVAS = (1254, 1254)


def _subject_bbox(img: Image.Image, white_threshold=245):
    rgb = img.convert("RGB")
    xs = []
    ys = []
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = rgb.getpixel((x, y))
            if r < white_threshold or g < white_threshold or b < white_threshold:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return (0, 0, img.width, img.height)
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _fit_size(src_w, src_h, box_w, box_h, max_upscale=1.15):
    scale = min(box_w / src_w, box_h / src_h, max_upscale)
    scale = max(scale, 0.01)
    return max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale))), scale


def _centered_safe_fit(subject_w: int, subject_h: int, margin: int, reserved_w: int, reserved_h: int, max_upscale: float):
    full_box_w = max(1, CANVAS[0] - 2 * margin)
    full_box_h = max(1, CANVAS[1] - 2 * margin)

    # Start from the largest visually centered fit on the full canvas.
    centered_w, centered_h, centered_scale = _fit_size(subject_w, subject_h, full_box_w, full_box_h, max_upscale=max_upscale)

    centered_left = (CANVAS[0] - centered_w) / 2.0
    centered_top = (CANVAS[1] - centered_h) / 2.0
    overlaps_logo_zone = centered_left < reserved_w and centered_top < reserved_h
    if not overlaps_logo_zone:
        return centered_w, centered_h, centered_scale

    # Keep the object centered, but if the centered fit intrudes into the top-left logo zone,
    # scale it down only as much as needed so the centered subject clears the zone.
    clear_w = max(1, CANVAS[0] - 2 * reserved_w)
    clear_h = max(1, CANVAS[1] - 2 * reserved_h)

    candidates = []
    for box_w, box_h in ((clear_w, full_box_h), (full_box_w, clear_h)):
        out_w, out_h, scale = _fit_size(subject_w, subject_h, box_w, box_h, max_upscale=max_upscale)
        left = (CANVAS[0] - out_w) / 2.0
        top = (CANVAS[1] - out_h) / 2.0
        if left >= reserved_w or top >= reserved_h:
            candidates.append((out_w * out_h, out_w, out_h, scale))

    if not candidates:
        return centered_w, centered_h, centered_scale

    _, out_w, out_h, scale = max(candidates, key=lambda item: item[0])
    return out_w, out_h, scale


def fit_to_canvas(src: Path, dst: Path):
    """
    Deterministic layout for V1.5.

    The software keeps the product visually centered on the final 1254x1254 canvas
    while preserving a fixed top-left logo region. If a centered placement would
    intrude into the logo zone, the subject is scaled down just enough to clear that
    zone, instead of being shifted off-center.
    """
    img = Image.open(src).convert("RGBA")
    bbox = _subject_bbox(img)
    subject = img.crop(bbox)

    margin = int(os.getenv("PRODUCT_CANVAS_MARGIN", "48"))
    max_upscale = float(os.getenv("CANVAS_MAX_UPSCALE", "1.15"))
    reserved_w = int(os.getenv("SAFE_ZONE_WIDTH", "330"))
    reserved_h = int(os.getenv("SAFE_ZONE_HEIGHT", "330"))

    out_w, out_h, _ = _centered_safe_fit(
        subject.width,
        subject.height,
        margin=margin,
        reserved_w=reserved_w,
        reserved_h=reserved_h,
        max_upscale=max_upscale,
    )
    resized = subject.resize((out_w, out_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", CANVAS, (255, 255, 255, 255))
    x = (CANVAS[0] - out_w) // 2
    y = (CANVAS[1] - out_h) // 2
    canvas.alpha_composite(resized, (x, y))

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dst, "PNG", optimize=True)


def optimize_final(src: Path, dst: Path, min_kb=50, max_kb=100):
    img = Image.open(src).convert("RGB")
    if img.size != CANVAS:
        raise ValueError(f"Optimizer received {img.size}; expected {CANVAS}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp.webp")
    chosen = None

    try:
        for quality in range(95, 29, -2):
            img.save(tmp, "WEBP", quality=quality, method=6)
            size = tmp.stat().st_size
            if size <= int(max_kb) * 1024:
                chosen = (quality, size, tmp.read_bytes())
                break

        if chosen is None:
            quality = 30
            img.save(tmp, "WEBP", quality=quality, method=6)
            chosen = (quality, tmp.stat().st_size, tmp.read_bytes())

        dst.write_bytes(chosen[2])
        return chosen[0], chosen[1] / 1024
    finally:
        tmp.unlink(missing_ok=True)
