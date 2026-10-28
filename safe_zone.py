from pathlib import Path
from PIL import Image


def safe_zone_ok(path: Path, width=330, height=330, max_occupancy=0.012):
    """
    Detect whether the upper-left reserved logo zone contains meaningful
    non-white pixels. Runs before the logo is added.

    V1.2 intentionally uses Pillow only; NumPy is not required.
    """
    img = Image.open(path).convert("RGB")
    width = max(1, min(int(width), img.width))
    height = max(1, min(int(height), img.height))
    zone = img.crop((0, 0, width, height))

    occupied = 0
    total = width * height
    for r, g, b in zone.getdata():
        if r < 245 or g < 245 or b < 245:
            occupied += 1

    occupancy = occupied / total
    return occupancy <= float(max_occupancy), occupancy
