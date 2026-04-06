#!/usr/bin/env python3

import argparse
import importlib.util
import io
import os
import sys
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


TEST_PATTERN_PALETTES = (
    ((255, 0, 0), (0, 255, 0), (0, 0, 255)),
    ((255, 255, 255), (0, 0, 0), (255, 255, 0)),
    ((0, 255, 255), (255, 0, 255), (255, 128, 0)),
    ((32, 32, 32), (255, 255, 255), (32, 32, 32)),
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


def list_jpeg_devices():
    return sorted(Path("/dev").glob("trigger6-*-out1-jpeg"))


def require_portal_capture(mod):
    if getattr(mod, "_HAS_PORTAL_CAPTURE", False):
        return

    raise SystemExit(
        "Portal capture support is unavailable. Install PyGObject plus the required GStreamer/PipeWire portal packages, or use --test-pattern."
    )


def build_test_frame(width, height, label, palette=None, footer=None):
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72
        )
    except Exception:
        font = ImageFont.load_default()

    image = Image.new("RGB", (width, height), (18, 18, 22))
    draw = ImageDraw.Draw(image)
    if palette is None:
        palette = TEST_PATTERN_PALETTES[0]

    third = width // 3
    draw.rectangle((0, 0, third, height), fill=palette[0])
    draw.rectangle((third, 0, third * 2, height), fill=palette[1])
    draw.rectangle((third * 2, 0, width, height), fill=palette[2])
    draw.rectangle((0, 0, width, 90), fill=(255, 255, 255))
    draw.rectangle((0, height - 200, width, height), fill=(24, 24, 24))
    draw.text((40, 12), "TRIGGER6 OUTPUT 1 TEST", fill=(0, 0, 0), font=font)
    draw.text((40, height - 150), label, fill=(255, 255, 255), font=font)
    if footer:
        draw.text((40, height - 80), footer, fill=(200, 200, 200), font=font)
    return image.tobytes()


def build_animated_test_frame(width, height, device_name, frame_index, hold_index=1, hold_total=1):
    palette = TEST_PATTERN_PALETTES[frame_index % len(TEST_PATTERN_PALETTES)]
    label = f"FRAME {frame_index:03d}"
    footer = (
        f"{device_name} palette={frame_index % len(TEST_PATTERN_PALETTES)} "
        f"hold={hold_index}/{hold_total}"
    )
    return build_test_frame(width, height, label, palette=palette, footer=footer)


def encode_jpeg(rgb_frame, width, height, quality, subsampling):
    image = Image.frombytes("RGB", (width, height), rgb_frame)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, subsampling=subsampling)
    return buffer.getvalue()


class PortalMultiScreenCapture:
    def __init__(self, mod):
        self.mod = mod
        self.bus = mod.Gio.bus_get_sync(mod.Gio.BusType.SESSION, None)
        self.session_handle = None
        self.pipelines = []
        self.appsinks = []
        self.node_ids = []
        self.latest_frames = []

    def _sender_path(self):
        return self.bus.get_unique_name().lstrip(":").replace(".", "_")

    def _request_path(self, token):
        return f"/org/freedesktop/portal/desktop/request/{self._sender_path()}/{token}"

    def _session_path(self, token):
        return f"/org/freedesktop/portal/desktop/session/{self._sender_path()}/{token}"

    def _call_portal_request(self, method, params, timeout_ms=120000):
        request_token = f"mct{uuid.uuid4().hex}"
        request_path = self._request_path(request_token)
        response = {}
        loop = self.mod.GLib.MainLoop()

        def on_response(_conn, _sender, _path, _interface, _signal, parameters, _data):
            response["payload"] = self.mod._variant_to_python(parameters)
            loop.quit()

        sub_id = self.bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request",
            "Response",
            request_path,
            None,
            self.mod.Gio.DBusSignalFlags.NONE,
            on_response,
            None,
        )

        def on_timeout():
            response["timed_out"] = True
            loop.quit()
            return False

        timeout_source = self.mod.GLib.timeout_add(timeout_ms, on_timeout)
        try:
            self.bus.call_sync(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.ScreenCast",
                method,
                params(request_token),
                self.mod.GLib.VariantType("(o)"),
                self.mod.Gio.DBusCallFlags.NONE,
                timeout_ms,
                None,
            )
            loop.run()
        finally:
            self.mod.GLib.source_remove(timeout_source)
            self.bus.signal_unsubscribe(sub_id)

        if response.get("timed_out"):
            raise RuntimeError(f"Portal screencast request {method} timed out")

        code, results = response.get("payload", (2, {}))
        if code != 0:
            raise RuntimeError(f"Portal screencast request {method} failed with response={code}")
        return self.mod._variant_to_python(results)

    def start(self):
        session_token = f"mct{uuid.uuid4().hex}"
        create_results = self._call_portal_request(
            "CreateSession",
            lambda request_token: self.mod.GLib.Variant(
                "(a{sv})",
                (
                    {
                        "handle_token": self.mod.GLib.Variant("s", request_token),
                        "session_handle_token": self.mod.GLib.Variant("s", session_token),
                    },
                ),
            ),
        )
        self.session_handle = create_results.get("session_handle") or self._session_path(session_token)

        self._call_portal_request(
            "SelectSources",
            lambda request_token: self.mod.GLib.Variant(
                "(oa{sv})",
                (
                    self.session_handle,
                    {
                        "handle_token": self.mod.GLib.Variant("s", request_token),
                        "types": self.mod.GLib.Variant("u", 1),
                        "multiple": self.mod.GLib.Variant("b", True),
                        "cursor_mode": self.mod.GLib.Variant("u", 2),
                        "persist_mode": self.mod.GLib.Variant("u", 1),
                    },
                ),
            ),
        )

        start_results = self._call_portal_request(
            "Start",
            lambda request_token: self.mod.GLib.Variant(
                "(osa{sv})",
                (
                    self.session_handle,
                    "",
                    {"handle_token": self.mod.GLib.Variant("s", request_token)},
                ),
            ),
        )
        streams = start_results.get("streams") or []
        self.node_ids = [stream[0] for stream in streams]
        if not self.node_ids:
            raise RuntimeError("Portal screencast started without returning any streams")

    def _ensure_pipelines(self):
        if self.pipelines:
            return
        if not self.node_ids:
            self.start()

        for node_id in self.node_ids:
            pipeline = self.mod.Gst.parse_launch(
                "pipewiresrc path={path} do-timestamp=true keepalive-time=1000 "
                "on-disconnect=error ! videoconvert ! video/x-raw,format=RGB ! "
                "appsink name=sink emit-signals=false max-buffers=1 drop=true sync=false".format(
                    path=node_id
                )
            )
            sink = pipeline.get_by_name("sink")
            if not sink:
                raise RuntimeError("Failed to create GStreamer appsink for portal stream")

            pipeline.set_state(self.mod.Gst.State.PLAYING)
            state_change, _state, _pending = pipeline.get_state(5 * self.mod.Gst.SECOND)
            if state_change == self.mod.Gst.StateChangeReturn.FAILURE:
                raise RuntimeError(f"PipeWire capture pipeline failed to start for path={node_id}")

            self.pipelines.append(pipeline)
            self.appsinks.append(sink)
            self.latest_frames.append(None)

    def get_frames(self):
        self._ensure_pipelines()

        for index, (pipeline, sink) in enumerate(zip(self.pipelines, self.appsinks)):
            msg = pipeline.get_bus().timed_pop_filtered(
                0,
                self.mod.Gst.MessageType.ERROR | self.mod.Gst.MessageType.EOS,
            )
            if msg:
                if msg.type == self.mod.Gst.MessageType.ERROR:
                    err, debug = msg.parse_error()
                    raise RuntimeError(f"PipeWire capture error on stream {index}: {err}; {debug}")
                raise RuntimeError(f"PipeWire capture stream {index} ended")

            sample = sink.emit("try-pull-sample", 500 * self.mod.Gst.MSECOND)
            if sample is None:
                continue

            caps = sample.get_caps()
            structure = caps.get_structure(0)
            width = structure.get_value("width")
            height = structure.get_value("height")
            if not width or not height:
                raise RuntimeError(f"Failed to parse caps for portal stream {index}")

            buffer = sample.get_buffer()
            ok, map_info = buffer.map(self.mod.Gst.MapFlags.READ)
            if not ok:
                raise RuntimeError(f"Failed to map buffer for portal stream {index}")

            try:
                row_len = width * 3
                row_stride = len(map_info.data) // height
                raw = memoryview(map_info.data)
                if row_stride == row_len:
                    rgb = bytes(raw[: row_stride * height])
                else:
                    out = bytearray(row_len * height)
                    for row in range(height):
                        src = row * row_stride
                        dst = row * row_len
                        out[dst : dst + row_len] = raw[src : src + row_len]
                    rgb = bytes(out)
            finally:
                buffer.unmap(map_info)

            self.latest_frames[index] = (width, height, rgb)

        return self.latest_frames

    def close(self):
        for pipeline in self.pipelines:
            pipeline.set_state(self.mod.Gst.State.NULL)
        self.pipelines = []
        self.appsinks = []
        self.latest_frames = []
        if self.session_handle:
            try:
                self.bus.call_sync(
                    "org.freedesktop.portal.Desktop",
                    self.session_handle,
                    "org.freedesktop.portal.Session",
                    "Close",
                    None,
                    None,
                    self.mod.Gio.DBusCallFlags.NONE,
                    5000,
                    None,
                )
            except Exception:
                pass
        self.session_handle = None


def choose_device(args):
    if args.device:
        return Path(args.device)

    devices = list_jpeg_devices()
    if len(devices) != 1:
        raise SystemExit(
            "Specify --device explicitly; available JPEG devices: " + ", ".join(str(path) for path in devices)
        )
    return devices[0]


def list_streams(mod):
    require_portal_capture(mod)
    capture = PortalMultiScreenCapture(mod)
    try:
        frames = capture.get_frames()
        for index, frame in enumerate(frames):
            if frame is None:
                print(f"stream {index}: no frame yet")
            else:
                width, height, _rgb = frame
                print(f"stream {index}: {width}x{height}")
    finally:
        capture.close()


def write_jpeg(device_path, jpg_bytes):
    with open(device_path, "wb", buffering=0) as f:
        f.write(jpg_bytes)


def main():
    parser = argparse.ArgumentParser(description="Feed pre-encoded JPEG frames into the trigger6 kernel output-1 transport")
    parser.add_argument("--device", help="Path to /dev/trigger6-*-out1-jpeg")
    parser.add_argument("--list-devices", action="store_true", help="List available kernel output-1 JPEG devices")
    parser.add_argument("--list-streams", action="store_true", help="List portal stream indexes and dimensions")
    parser.add_argument("--stream-index", type=int, help="Portal stream index to relay into the chosen JPEG device")
    parser.add_argument("--test-pattern", action="store_true", help="Send a generated test pattern instead of relaying a portal stream")
    parser.add_argument(
        "--relay-framebuffer",
        action="store_true",
        help="Read compositor framebuffer from the kernel device, JPEG-encode, and write back (hybrid DRM path)",
    )
    parser.add_argument(
        "--animate-test-pattern",
        action="store_true",
        help="Change the test pattern every frame so panel updates are easier to notice",
    )
    parser.add_argument("--width", type=int, default=1920, help="Width for the generated test pattern (default: 1920)")
    parser.add_argument("--height", type=int, default=1080, help="Height for the generated test pattern (default: 1080)")
    parser.add_argument("--fps", type=float, default=2.0, help="Relay rate in frames per second (default: 2.0)")
    parser.add_argument("--frames", type=int, default=0, help="Frames to send; 0 means run until interrupted")
    parser.add_argument(
        "--repeat-each-frame",
        type=int,
        default=1,
        help="Repeat each animated frame this many times before advancing (default: 1)",
    )
    parser.add_argument("--jpeg-quality", type=int, default=95, help="JPEG quality to encode (default: 95)")
    parser.add_argument("--jpeg-subsampling", type=int, default=2, choices=(0, 1, 2), help="JPEG subsampling to encode (default: 2)")
    args = parser.parse_args()

    if args.repeat_each_frame < 1:
        raise SystemExit("--repeat-each-frame must be >= 1")

    if args.list_devices:
        for path in list_jpeg_devices():
            print(path)
        return

    mod = load_driver_module()
    if args.list_streams:
        list_streams(mod)
        if not args.test_pattern and args.stream_index is None:
            return

    device_path = choose_device(args)
    if not device_path.exists():
        raise SystemExit(f"JPEG injection device not found: {device_path}")

    delay = 1.0 / args.fps if args.fps > 0 else 0.0
    sent = 0

    if args.test_pattern:
        total_sends = 0
        while args.frames == 0 or sent < args.frames:
            if args.animate_test_pattern:
                logical_frame = total_sends // args.repeat_each_frame
                hold_index = (total_sends % args.repeat_each_frame) + 1
                frame = build_animated_test_frame(
                    args.width,
                    args.height,
                    device_path.name,
                    logical_frame,
                    hold_index=hold_index,
                    hold_total=args.repeat_each_frame,
                )
            else:
                frame = build_test_frame(
                    args.width,
                    args.height,
                    f"DRM OUT1 {device_path.name}",
                )
            jpg = encode_jpeg(frame, args.width, args.height, args.jpeg_quality, args.jpeg_subsampling)
            write_jpeg(device_path, jpg)
            total_sends += 1
            if not args.animate_test_pattern or total_sends % args.repeat_each_frame == 0:
                sent += 1
            if delay > 0:
                time.sleep(delay)
        return

    if args.relay_framebuffer:
        frame_size = args.width * args.height * 4  # XRGB8888
        fd = os.open(str(device_path), os.O_RDWR)
        try:
            print(f"Relay-framebuffer mode: reading {args.width}x{args.height} XRGB8888 "
                  f"({frame_size} bytes) from {device_path}, JPEG q={args.jpeg_quality}")
            while args.frames == 0 or sent < args.frames:
                try:
                    data = os.pread(fd, frame_size, 0)
                except OSError as e:
                    print(f"Read error (device gone?): {e}")
                    break
                if len(data) != frame_size:
                    print(f"Short read: {len(data)}/{frame_size} bytes")
                    break

                img = Image.frombytes("RGB", (args.width, args.height), data, "raw", "BGRX")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=args.jpeg_quality, subsampling=args.jpeg_subsampling)
                jpg = buf.getvalue()

                try:
                    os.pwrite(fd, jpg, 0)
                except OSError as e:
                    print(f"Write error: {e}")
                    break

                sent += 1
                if sent % 100 == 1:
                    print(f"Frame {sent}: {len(jpg)} bytes JPEG")
        finally:
            os.close(fd)
        return

    if args.stream_index is None:
        raise SystemExit("Provide --stream-index for portal relay mode or use --test-pattern")

    require_portal_capture(mod)
    capture = PortalMultiScreenCapture(mod)
    try:
        while args.frames == 0 or sent < args.frames:
            frames = capture.get_frames()
            if args.stream_index >= len(frames):
                raise SystemExit(f"Portal stream index {args.stream_index} is out of range (have {len(frames)} streams)")

            frame = frames[args.stream_index]
            if frame is None:
                if delay > 0:
                    time.sleep(delay)
                continue

            width, height, rgb = frame
            jpg = encode_jpeg(rgb, width, height, args.jpeg_quality, args.jpeg_subsampling)
            write_jpeg(device_path, jpg)
            sent += 1
            if delay > 0:
                time.sleep(delay)
    finally:
        capture.close()


if __name__ == "__main__":
    sys.exit(main())