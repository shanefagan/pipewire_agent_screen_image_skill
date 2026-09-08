#!/usr/bin/env python3
"""
PipeWire Agent Screen Capture Engine
Captures screen or application window frames on Linux (KDE, GNOME, Wayland/X11)
via XDG Desktop Portal (ScreenCast) and PipeWire.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import dbus
from dbus.mainloop.glib import DBusGMainLoop
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import GLib, Gst, GstApp  # noqa: E402
from PIL import Image  # noqa: E402


def send_notification(reason: str) -> None:
    """Send a desktop notification to inform the user about the screen capture request."""
    title = "📸 Agent Screen Capture Request"
    body = f"The agent is requesting a screen capture:\n\"{reason}\"\n\nPlease select a screen or window in the system dialog."
    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name=Antigravity Agent",
                "--icon=camera-photo",
                "--urgency=normal",
                "--expire-time=15000",
                title,
                body,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        # If notify-send fails or is unavailable, fallback silently
        pass


class ScreenCastPortalCapture:
    def __init__(
        self,
        reason: str,
        output_path: str,
        source_type: str = "all",
        cursor: bool = True,
        timeout: int = 60,
        delay: float = 0.0,
        show_notification: bool = True,
        debug: bool = False,
    ):
        self.reason = reason
        self.output_path = Path(output_path).expanduser().resolve()
        self.source_type = source_type
        self.cursor = cursor
        self.timeout = timeout
        self.delay = delay
        self.show_notification = show_notification
        self.debug = debug

        self.loop = GLib.MainLoop()
        self.bus = dbus.SessionBus()
        self.portal = self.bus.get_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        self.portal_iface = dbus.Interface(
            self.portal,
            "org.freedesktop.portal.ScreenCast",
        )

        # Sender token format required by Desktop Portal
        raw_sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.sender = raw_sender
        self.session_token = f"screencast_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self.session_handle = None
        self.node_id = None
        self.pw_fd = None
        self.error_message = None
        self.cancelled = False
        self.timed_out = False
        self.timeout_source_id = None

    def _log(self, msg: str):
        if self.debug:
            print(f"[DEBUG] {msg}", file=sys.stderr)

    def _on_timeout(self):
        self.timed_out = True
        self.error_message = f"Screen capture request timed out after {self.timeout} seconds waiting for user response."
        self.loop.quit()
        return False

    def capture(self) -> dict:
        start_time = time.time()

        # Step 1: Notify user
        if self.show_notification:
            send_notification(self.reason)

        # Set overall timeout for user confirmation
        if self.timeout > 0:
            self.timeout_source_id = GLib.timeout_add_seconds(
                self.timeout, self._on_timeout
            )

        try:
            # Step 2: Create ScreenCast Session
            self._log("Creating ScreenCast portal session...")
            self._create_session()
            if self.cancelled or self.timed_out or self.error_message:
                self._raise_or_exit()

            # Step 3: Select Sources
            self._log(f"Selecting sources (type={self.source_type}, cursor={self.cursor})...")
            self._select_sources()
            if self.cancelled or self.timed_out or self.error_message:
                self._raise_or_exit()

            # Step 4: Start Session (Pops up KDE/GNOME dialog)
            self._log("Starting portal session (system dialog prompting user)...")
            self._start_session()
            if self.cancelled or self.timed_out or self.error_message:
                self._raise_or_exit()

            # Step 5: Open PipeWire Remote FD
            self._log(f"Opening PipeWire remote for node_id={self.node_id}...")
            self._open_pipewire_remote()
            if not self.pw_fd or not self.node_id:
                raise RuntimeError("Failed to obtain PipeWire file descriptor or node ID.")

            # Optional delay requested by caller (e.g. to let window focus settle)
            if self.delay > 0:
                self._log(f"Waiting {self.delay}s delay before capturing frame...")
                time.sleep(self.delay)

            # Step 6: Grab frame via GStreamer
            self._log("Capturing video frame from PipeWire stream...")
            width, height, file_size = self._capture_frame_gstreamer()

            elapsed = round(time.time() - start_time, 2)
            return {
                "status": "success",
                "image_path": str(self.output_path),
                "width": width,
                "height": height,
                "size_bytes": file_size,
                "reason": self.reason,
                "elapsed_seconds": elapsed,
            }

        finally:
            # Cancel timer if still active
            if self.timeout_source_id:
                GLib.source_remove(self.timeout_source_id)
                self.timeout_source_id = None

            # Clean up PipeWire FD and Portal Session
            self._cleanup()

    def _raise_or_exit(self):
        if self.timed_out:
            raise TimeoutError(self.error_message)
        if self.cancelled:
            raise PermissionError("Screen capture request was cancelled or declined by user.")
        if self.error_message:
            raise RuntimeError(self.error_message)

    def _create_session(self):
        create_token = f"create_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        request_path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{create_token}"

        def on_response(response, results):
            if response == 0:
                self.session_handle = results.get("session_handle")
                self._log(f"Session created: {self.session_handle}")
            else:
                self.error_message = f"Failed to create portal session (code {response})."
            self.loop.quit()

        signal_match = self.bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=request_path,
        )

        try:
            self.portal_iface.CreateSession(
                {
                    "session_handle_token": self.session_token,
                    "handle_token": create_token,
                }
            )
            self.loop.run()
        finally:
            signal_match.remove()

    def _select_sources(self):
        # Determine source type bitmask: 1=Monitor, 2=Window, 3=Both
        if self.source_type == "monitor":
            types_mask = 1
        elif self.source_type == "window":
            types_mask = 2
        else:
            types_mask = 3  # All: allows user to choose monitor or window

        # Cursor mode: 1=Hidden, 2=Embedded
        cursor_mode = 2 if self.cursor else 1

        select_token = f"select_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        request_path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{select_token}"

        def on_response(response, results):
            if response != 0:
                self.error_message = f"SelectSources failed with code {response}."
            else:
                self._log("SelectSources acknowledged.")
            self.loop.quit()

        signal_match = self.bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=request_path,
        )

        try:
            self.portal_iface.SelectSources(
                self.session_handle,
                {
                    "types": dbus.UInt32(types_mask),
                    "multiple": dbus.Boolean(False),
                    "cursor_mode": dbus.UInt32(cursor_mode),
                    "handle_token": select_token,
                },
            )
            self.loop.run()
        finally:
            signal_match.remove()

    def _start_session(self):
        start_token = f"start_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        request_path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{start_token}"

        def on_response(response, results):
            if response == 0:
                streams = results.get("streams", [])
                self._log(f"Streams returned by portal: {streams}")
                if streams and len(streams) > 0:
                    self.node_id = int(streams[0][0])
                    self._log(f"Selected PipeWire node ID: {self.node_id}")
                else:
                    self.error_message = "No streams returned by Desktop Portal."
            elif response == 1:
                self.cancelled = True
                self.error_message = "User cancelled or denied the screen share request."
            else:
                self.error_message = f"ScreenCast Start failed with code {response}."
            self.loop.quit()

        signal_match = self.bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=request_path,
        )

        try:
            # Empty parent_window string indicates no specific parent window
            self.portal_iface.Start(
                self.session_handle,
                "",
                {"handle_token": start_token},
            )
            self.loop.run()
        finally:
            signal_match.remove()

    def _open_pipewire_remote(self):
        fd_obj = self.portal_iface.OpenPipeWireRemote(
            self.session_handle,
            {},
        )
        self.pw_fd = fd_obj.take()
        self._log(f"Obtained PipeWire remote file descriptor: {self.pw_fd}")

    def _capture_frame_gstreamer(self) -> tuple:
        Gst.init(None)

        pipeline = Gst.Pipeline.new("pipewire-screen-grabber")

        src = Gst.ElementFactory.make("pipewiresrc", "pw_src")
        # Duplicate fd so both GStreamer and our cleanup handle cleanly
        dup_fd = os.dup(self.pw_fd)
        src.set_property("fd", dup_fd)

        # Set path to the PipeWire node ID.
        # PipeWire's pipewiresrc parses path with atoi() to connect to the node.
        src.set_property("path", str(self.node_id))

        # always-copy ensures memory is copied into system memory buffers
        if src.find_property("always-copy"):
            src.set_property("always-copy", True)

        # Keepalive ensures that buffers are pushed even if the screen is idle/static
        if src.find_property("keepalive-time"):
            src.set_property("keepalive-time", 100)

        conv = Gst.ElementFactory.make("videoconvert", "pw_conv")
        capsfilter = Gst.ElementFactory.make("capsfilter", "pw_caps")
        caps = Gst.Caps.from_string("video/x-raw,format=RGBA")
        capsfilter.set_property("caps", caps)

        sink = Gst.ElementFactory.make("appsink", "pw_sink")
        sink.set_property("drop", True)
        sink.set_property("max-buffers", 1)

        pipeline.add(src)
        pipeline.add(conv)
        pipeline.add(capsfilter)
        pipeline.add(sink)

        if not src.link(conv):
            raise RuntimeError("Failed to link pipewiresrc to videoconvert.")
        if not conv.link(capsfilter):
            raise RuntimeError("Failed to link videoconvert to capsfilter.")
        if not capsfilter.link(sink):
            raise RuntimeError("Failed to link capsfilter to appsink.")

        bus = pipeline.get_bus()

        ret = pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            msg = bus.pop_filtered(Gst.MessageType.ERROR)
            if msg:
                err, dbg = msg.parse_error()
                raise RuntimeError(f"GStreamer failed to start pipeline: {err.message} ({dbg})")
            raise RuntimeError("GStreamer failed to set pipeline state to PLAYING.")

        sample = None
        deadline = time.time() + 15.0  # Allow up to 15 seconds to receive the frame

        try:
            while time.time() < deadline:
                # Check for bus errors immediately
                msg = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.WARNING)
                if msg:
                    if msg.type == Gst.MessageType.ERROR:
                        err, dbg = msg.parse_error()
                        raise RuntimeError(f"GStreamer pipeline error: {err.message} (debug: {dbg})")
                    elif msg.type == Gst.MessageType.WARNING and self.debug:
                        warn, dbg = msg.parse_warning()
                        self._log(f"GStreamer warning: {warn.message} ({dbg})")

                # Poll appsink with 250ms timeout
                sample = sink.try_pull_sample(250 * Gst.MSECOND)
                if sample:
                    buf = sample.get_buffer()
                    if buf and buf.get_size() > 0:
                        break
                    # Empty buffer, continue polling
                    sample = None

            if not sample:
                raise TimeoutError("Timed out waiting for video frame from PipeWire stream.")

            caps = sample.get_caps()
            struct = caps.get_structure(0)
            width = struct.get_value("width")
            height = struct.get_value("height")
            self._log(f"Frame received: {width}x{height}, format=RGBA")

            buffer = sample.get_buffer()
            success, map_info = buffer.map(Gst.MapFlags.READ)
            if not success:
                raise RuntimeError("Failed to map GStreamer buffer memory.")

            try:
                img = Image.frombytes("RGBA", (width, height), map_info.data)

                # Ensure target directory exists
                self.output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(self.output_path)
                file_size = self.output_path.stat().st_size
                self._log(f"Saved screenshot ({file_size} bytes) to {self.output_path}")
                return width, height, file_size
            finally:
                buffer.unmap(map_info)

        finally:
            pipeline.set_state(Gst.State.NULL)

    def _cleanup(self):
        if self.pw_fd is not None:
            try:
                os.close(self.pw_fd)
            except OSError:
                pass
            self.pw_fd = None

        if self.session_handle:
            try:
                session_obj = self.bus.get_object(
                    "org.freedesktop.portal.Desktop",
                    self.session_handle,
                )
                session_iface = dbus.Interface(
                    session_obj,
                    "org.freedesktop.portal.Session",
                )
                session_iface.Close()
                self._log(f"Closed portal session {self.session_handle}")
            except Exception:
                pass
            self.session_handle = None


def main():
    DBusGMainLoop(set_as_default=True)

    parser = argparse.ArgumentParser(
        description="Request and capture a screenshot from the user via PipeWire and XDG Desktop Portal."
    )
    parser.add_argument(
        "--reason",
        "-r",
        required=True,
        help="Reason for screen capture (e.g. 'Inspecting GUI application error dialog'). Displayed in notification and logs.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="",
        help="Path where screenshot should be saved (default: ./screenshots/capture_<timestamp>.png).",
    )
    parser.add_argument(
        "--source-type",
        "-s",
        choices=["all", "monitor", "window"],
        default="all",
        help="Type of sources allowed for selection in the system dialog (default: all).",
    )
    parser.add_argument(
        "--no-cursor",
        action="store_true",
        help="Hide mouse cursor in captured image.",
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=60,
        help="Timeout in seconds waiting for user confirmation (default: 60s).",
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=0.0,
        help="Delay in seconds before capturing frame after user approves share (default: 0).",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Do not trigger a desktop notification.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to stderr.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON.",
    )

    args = parser.parse_args()

    # Generate default output path if not specified
    if not args.output:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        args.output = f"./screenshots/capture_{timestamp}.png"

    # Print user-visible announcement to terminal
    print("=" * 60, file=sys.stderr)
    print("📸 SCREEN CAPTURE REQUEST", file=sys.stderr)
    print(f"Reason: {args.reason}", file=sys.stderr)
    print("Action: A system dialog has appeared requesting screen/window access.", file=sys.stderr)
    print("        Please select the window or screen and click Share.", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    capturer = ScreenCastPortalCapture(
        reason=args.reason,
        output_path=args.output,
        source_type=args.source_type,
        cursor=not args.no_cursor,
        timeout=args.timeout,
        delay=args.delay,
        show_notification=not args.no_notify,
        debug=args.debug,
    )

    try:
        result = capturer.capture()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("\n✅ Screen capture saved successfully!")
            print(f"Image Path:  {result['image_path']}")
            print(f"Resolution:  {result['width']}x{result['height']}")
            print(f"Size:        {result['size_bytes'] / 1024:.1f} KB")
            print(f"Time Taken:  {result['elapsed_seconds']}s")
            print(f"Reason:      {result['reason']}\n")
        sys.exit(0)

    except PermissionError as e:
        if args.json:
            print(json.dumps({"status": "cancelled", "error": str(e)}))
        else:
            print(f"\n⚠️  Screen capture cancelled: {e}", file=sys.stderr)
        sys.exit(1)

    except TimeoutError as e:
        if args.json:
            print(json.dumps({"status": "timeout", "error": str(e)}))
        else:
            print(f"\n⏱️  Screen capture timed out: {e}", file=sys.stderr)
        sys.exit(2)

    except Exception as e:
        if args.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"\n❌ Error capturing screen: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
