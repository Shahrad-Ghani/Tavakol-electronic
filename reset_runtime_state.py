"""Reset generated runtime state for a genuinely fresh pipeline test.

By default this removes generated metadata/images/datasheets/logs but preserves
input photos and assets. Use --include-input only when you also want to empty input/.
Secrets (.env, proxies.txt) and assets/store_logo.png are never touched.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parent
RUNTIME_DIRS = ["metadata", "output", "Final", "datasheets", "debug_html", "logs", "seo"]


def clear_dir(path: Path):
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    removed = 0
    for item in list(path.iterdir()):
        if item.name == ".gitkeep":
            continue
        if item.is_dir():
            import shutil
            shutil.rmtree(item)
        else:
            item.unlink()
        removed += 1
    return removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-input", action="store_true", help="Also remove input images.")
    args = parser.parse_args()

    total = 0
    for name in RUNTIME_DIRS:
        n = clear_dir(ROOT / name)
        total += n
        print(f"[RESET] {name}/ removed={n}")
    if args.include_input:
        n = clear_dir(ROOT / "input")
        total += n
        print(f"[RESET] input/ removed={n}")
    print(f"[DONE] runtime reset removed={total}; secrets/assets preserved")


if __name__ == "__main__":
    main()
