#!/usr/bin/env python3

import argparse
import importlib.util
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_CASES = {
    "stable": ("balanced", 95, 2),
    "speed": ("speed", 85, 2),
    "hq420": ("balanced", 97, 2),
    "422-experimental": ("balanced", 95, 1),
    "444-experimental": ("text", 97, 0),
}


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


def build_test_frame(width, height, label="OUTPUT 1 TEST"):
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96
        )
    except Exception:
        font = ImageFont.load_default()

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    third = width // 3
    draw.rectangle((0, 0, third, height), fill=(255, 0, 0))
    draw.rectangle((third, 0, third * 2, height), fill=(0, 255, 0))
    draw.rectangle((third * 2, 0, width, height), fill=(0, 0, 255))
    draw.rectangle((0, height - 180, width, height), fill=(20, 20, 20))
    draw.text((50, height - 130), label, fill=(255, 255, 255), font=font)
    return image.tobytes()


def resolve_case_specs(args):
    if args.case:
        return [(case_name, *DEFAULT_CASES[case_name]) for case_name in args.case]

    return [
        (
            "custom",
            args.quality_profile,
            args.jpeg_quality,
            args.jpeg_subsampling,
        )
    ]


def apply_case_settings(mod, profile, quality, subsampling, allow_unsafe):
    profile, quality, subsampling = mod.resolve_jpeg_settings(
        profile,
        fps=1,
        quality=quality,
        subsampling=subsampling,
    )
    profile, quality, subsampling, clamped = mod.stabilize_secondary_jpeg_settings(
        profile,
        quality,
        subsampling,
        allow_unsafe=allow_unsafe,
    )
    mod.JPEG_QUALITY = quality
    mod.JPEG_SUBSAMPLING = subsampling
    mod.log_jpeg_settings(profile, quality, subsampling, clamped=clamped)
    return profile, quality, subsampling, clamped


def send_case_frames(mod, targets, case_name, frames, delay, allow_unsafe):
    out1 = next((out for out in targets if out.out == 1), None)
    if out1 is None:
        raise RuntimeError(
            f"No logical output 1 found for bus={targets[0].dev.bus} address={targets[0].dev.address}"
        )

    profile, quality, subsampling = DEFAULT_CASES.get(case_name, (None, None, None))
    if profile is None:
        raise RuntimeError(f"Unknown output-1 case: {case_name}")

    profile, quality, subsampling, _ = apply_case_settings(
        mod,
        profile,
        quality,
        subsampling,
        allow_unsafe=allow_unsafe,
    )
    mod.init_outputs(targets)
    label = f"{case_name} q={quality} s={subsampling}"
    frame = build_test_frame(out1.width, out1.height, label=label)
    for _ in range(frames):
        out1.send_frame(frame)
        time.sleep(delay)
    return profile, quality, subsampling


def send_custom_frames(mod, targets, profile, quality, subsampling, frames, delay, allow_unsafe):
    out1 = next((out for out in targets if out.out == 1), None)
    if out1 is None:
        raise RuntimeError(
            f"No logical output 1 found for bus={targets[0].dev.bus} address={targets[0].dev.address}"
        )

    profile, quality, subsampling, _ = apply_case_settings(
        mod,
        profile,
        quality,
        subsampling,
        allow_unsafe=allow_unsafe,
    )
    mod.init_outputs(targets)
    label = f"OUT1 q={quality} s={subsampling}"
    frame = build_test_frame(out1.width, out1.height, label=label)
    for _ in range(frames):
        out1.send_frame(frame)
        time.sleep(delay)
    return profile, quality, subsampling


def restore_safe_output(mod, targets, frames, delay):
    safe_profile = "balanced"
    profile, quality, subsampling, _ = apply_case_settings(
        mod,
        safe_profile,
        mod.SECONDARY_SAFE_JPEG_QUALITY,
        mod.SECONDARY_SAFE_JPEG_SUBSAMPLING,
        allow_unsafe=False,
    )
    mod.init_outputs(targets)
    out1 = next((out for out in targets if out.out == 1), None)
    if out1 is None:
        return profile, quality, subsampling

    frame = build_test_frame(out1.width, out1.height, label="RESTORED SAFE 95/2")
    for _ in range(frames):
        out1.send_frame(frame)
        time.sleep(delay)
    return profile, quality, subsampling


def main():
    parser = argparse.ArgumentParser(description="Reinitialize a T6 chip and push a test pattern to logical output 1")
    parser.add_argument("--bus", type=int, required=True, help="USB bus number of the target T6 chip")
    parser.add_argument("--address", type=int, required=True, help="USB device address of the target T6 chip")
    parser.add_argument("--frames", type=int, default=12, help="Number of test frames to send (default: 12)")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between frames in seconds (default: 0.15)")
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(DEFAULT_CASES),
        help="Named output-1 experiment case to run; can be provided multiple times",
    )
    parser.add_argument(
        "--pause-between-cases",
        type=float,
        default=1.0,
        help="Pause in seconds between experiment cases (default: 1.0)",
    )
    parser.add_argument(
        "--restore-safe-frames",
        type=int,
        default=8,
        help="Known-good frames to send after experiments when rollback is enabled (default: 8)",
    )
    parser.add_argument(
        "--no-restore-safe",
        action="store_true",
        help="Do not restore output 1 to the known-good 95/2 state before exit",
    )
    parser.add_argument(
        "--quality-profile",
        default="balanced",
        choices=("auto", "speed", "balanced", "text"),
        help="JPEG quality profile for logical output 1 (default: balanced)",
    )
    parser.add_argument("--jpeg-quality", type=int, help="Override JPEG quality for logical output 1")
    parser.add_argument(
        "--jpeg-subsampling",
        type=int,
        choices=(0, 1, 2),
        help="Override JPEG subsampling for logical output 1",
    )
    parser.add_argument(
        "--allow-unsafe-secondary-jpeg",
        action="store_true",
        help="Allow settings outside the known-good output-1 envelope",
    )
    args = parser.parse_args()

    mod = load_driver_module()
    outputs = mod.find_outputs()
    targets = [
        out for out in outputs if out.dev.bus == args.bus and out.dev.address == args.address
    ]
    if not targets:
        raise SystemExit(f"No T6 outputs found for bus={args.bus} address={args.address}")

    if not any(out.out == 1 for out in targets):
        raise SystemExit(f"No logical output 1 found for bus={args.bus} address={args.address}")

    try:
        if args.case:
            for index, (case_name, _profile, _quality, _subsampling) in enumerate(resolve_case_specs(args), start=1):
                log_msg = f"Running output-1 experiment case {index}/{len(args.case)}: {case_name}"
                print(log_msg)
                send_case_frames(
                    mod,
                    targets,
                    case_name,
                    frames=args.frames,
                    delay=args.delay,
                    allow_unsafe=args.allow_unsafe_secondary_jpeg,
                )
                if index < len(args.case):
                    time.sleep(args.pause_between_cases)
        else:
            send_custom_frames(
                mod,
                targets,
                args.quality_profile,
                args.jpeg_quality,
                args.jpeg_subsampling,
                frames=args.frames,
                delay=args.delay,
                allow_unsafe=args.allow_unsafe_secondary_jpeg,
            )
    finally:
        try:
            if not args.no_restore_safe:
                print("Restoring output 1 to known-good balanced/95/2")
                restore_safe_output(
                    mod,
                    targets,
                    frames=args.restore_safe_frames,
                    delay=args.delay,
                )
        finally:
            mod.close_outputs(targets)


if __name__ == "__main__":
    main()