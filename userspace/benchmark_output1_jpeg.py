#!/usr/bin/env python3

import argparse
import importlib.util
import io
import statistics
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_CASES = (
    ("stable", 95, 2),
    ("speed", 85, 2),
    ("hq420", 97, 2),
    ("422-experimental", 95, 1),
    ("444-experimental", 97, 0),
)


def load_driver_module():
    try:
        import mct_t6_display as module

        return module
    except ImportError:
        module_path = Path(__file__).with_name("mct_t6_display.py")
        spec = importlib.util.spec_from_file_location("mct_t6_display", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def build_synthetic_frame(width, height):
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64
        )
    except Exception:
        font = ImageFont.load_default()

    image = Image.new("RGB", (width, height), (12, 12, 16))
    draw = ImageDraw.Draw(image)

    stripe_h = height // 6
    colors = [
        (255, 255, 255),
        (255, 255, 0),
        (0, 255, 255),
        (0, 255, 0),
        (255, 0, 255),
        (255, 0, 0),
    ]
    for idx, color in enumerate(colors):
        top = idx * stripe_h
        draw.rectangle((0, top, width, top + stripe_h), fill=color)

    box_y = height - 280
    for idx in range(16):
        shade = int(idx * 255 / 15)
        left = idx * width // 16
        right = (idx + 1) * width // 16
        draw.rectangle((left, box_y, right, height - 180), fill=(shade, shade, shade))

    draw.rectangle((0, height - 180, width, height), fill=(18, 18, 18))
    draw.text((40, height - 130), "OUTPUT 1 JPEG BENCH", fill=(255, 255, 255), font=font)
    draw.text((40, height - 70), "Color bars, grayscale ramp, text", fill=(200, 200, 200), font=font)
    return image.tobytes()


def encode_jpeg(rgb_frame, width, height, quality, subsampling):
    image = Image.frombytes("RGB", (width, height), rgb_frame)
    buffer = io.BytesIO()
    started = time.perf_counter()
    image.save(buffer, format="JPEG", quality=quality, subsampling=subsampling)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return elapsed_ms, buffer.getvalue()


def benchmark_case(rgb_frame, width, height, quality, subsampling, repeats):
    timings = []
    sizes = []
    for _ in range(repeats):
        elapsed_ms, payload = encode_jpeg(rgb_frame, width, height, quality, subsampling)
        timings.append(elapsed_ms)
        sizes.append(len(payload))
    return {
        "avg_ms": statistics.mean(timings),
        "min_ms": min(timings),
        "max_ms": max(timings),
        "avg_size": statistics.mean(sizes),
        "min_size": min(sizes),
        "max_size": max(sizes),
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark output-1 JPEG settings without touching the device")
    parser.add_argument(
        "--source",
        choices=("synthetic", "desktop"),
        default="synthetic",
        help="Frame source for the JPEG benchmark (default: synthetic)",
    )
    parser.add_argument("--width", type=int, default=1920, help="Frame width for synthetic source")
    parser.add_argument("--height", type=int, default=1080, help="Frame height for synthetic source")
    parser.add_argument("--repeats", type=int, default=3, help="Encodes per test case (default: 3)")
    parser.add_argument(
        "--save-dir",
        help="Optional directory to save one JPEG per test case for manual inspection",
    )
    args = parser.parse_args()

    mod = load_driver_module()
    if args.source == "desktop":
        desktop = mod.capture_desktop()
        if not desktop:
            raise SystemExit("Desktop capture failed; try --source synthetic or ensure the portal session is available")
        width, height, rgb_frame = desktop
        if width != 1920 or height != 1080:
            rgb_frame = mod.extract_screen_region(rgb_frame, width, height, None, 1920, 1080)
            width, height = 1920, 1080
    else:
        width, height = args.width, args.height
        rgb_frame = build_synthetic_frame(width, height)

    save_dir = Path(args.save_dir) if args.save_dir else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    print(f"source={args.source} width={width} height={height} repeats={args.repeats}")
    print("case quality subs avg_ms avg_kib note")
    for name, quality, subsampling in DEFAULT_CASES:
        result = benchmark_case(rgb_frame, width, height, quality, subsampling, args.repeats)
        note = "safe" if (quality <= mod.SECONDARY_SAFE_JPEG_QUALITY and subsampling == mod.SECONDARY_SAFE_JPEG_SUBSAMPLING) else "experimental"
        print(
            f"{name:16s} {quality:7d} {subsampling:4d} {result['avg_ms']:6.2f} {result['avg_size'] / 1024:7.1f} {note}"
        )
        if save_dir:
            _, payload = encode_jpeg(rgb_frame, width, height, quality, subsampling)
            (save_dir / f"{name}.jpg").write_bytes(payload)


if __name__ == "__main__":
    main()