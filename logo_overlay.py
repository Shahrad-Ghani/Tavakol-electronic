from pathlib import Path
from PIL import Image

def overlay_logo(image_path: Path, logo_path: Path, out_path: Path,
                  max_width=260, max_height=260, margin=40):
    base=Image.open(image_path).convert("RGBA")
    logo=Image.open(logo_path).convert("RGBA")

    # Preserve aspect ratio. Never force width and height independently.
    logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

    # Optional cleanup for a logo PNG with an opaque white background:
    # keep it opaque; it is intentionally placed on the white canvas.
    base.alpha_composite(logo, (margin, margin))
    base.convert("RGB").save(out_path, "PNG", optimize=True)
