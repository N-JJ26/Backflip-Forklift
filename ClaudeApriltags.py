from __future__ import annotations

import argparse
import time
import urllib.request
from dataclasses import dataclass

import cv2
import numpy as np
from pupil_apriltags import Detector


@dataclass
class Camera:
    """Wraps either an MJPEG stream or a polled snapshot endpoint."""

    url: str
    snapshot: bool = False
    _cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        if not self.snapshot:
            self._cap = cv2.VideoCapture(self.url)
            if not self._cap.isOpened():
                raise ConnectionError(f"Could not open stream: {self.url}")

    def read(self) -> np.ndarray | None:
        if self.snapshot:
            try:
                with urllib.request.urlopen(self.url, timeout=5) as resp:
                    data = np.frombuffer(resp.read(), dtype=np.uint8)
                return cv2.imdecode(data, cv2.IMREAD_COLOR)
            except OSError:
                return None
        assert self._cap is not None
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def draw_detection(frame: np.ndarray, det) -> None:
    """Draw tag outline, center, and ID on the frame."""
    corners = det.corners.astype(int)
    for i in range(4):
        cv2.line(frame, tuple(corners[i]), tuple(corners[(i + 1) % 4]), (0, 255, 0), 2)

    cx, cy = map(int, det.center)
    cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
    cv2.putText(
        frame,
        f"ID {det.tag_id}",
        (corners[0][0], corners[0][1] - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 0),
        2,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AprilTag detection from an ESP camera")
    p.add_argument("--url", required=True, help="Stream (…:81/stream) or snapshot (…/capture) URL")
    p.add_argument("--snapshot", action="store_true", help="Poll single JPEGs instead of using MJPEG stream")
    p.add_argument("--family", default="tag36h11", help="AprilTag family (default: tag36h11)")
    p.add_argument("--decimate", type=float, default=1.0, help="Downsample factor for speed (default: 1.0)")
    p.add_argument("--threads", type=int, default=2, help="Detector threads")
    p.add_argument("--no-gui", action="store_true", help="Don't show a preview window")
    # Optional pose estimation
    p.add_argument("--tag-size", type=float, help="Tag side length in meters (enables pose)")
    p.add_argument("--fx", type=float, help="Camera focal length x (pixels)")
    p.add_argument("--fy", type=float, help="Camera focal length y (pixels)")
    p.add_argument("--cx", type=float, help="Camera principal point x (pixels)")
    p.add_argument("--cy", type=float, help="Camera principal point y (pixels)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    detector = Detector(
        families=args.family,
        nthreads=args.threads,
        quad_decimate=args.decimate,
        quad_sigma=0.0,
        refine_edges=True,
        decode_sharpening=0.25,
    )

    camera_params = None
    if args.tag_size and None not in (args.fx, args.fy, args.cx, args.cy):
        camera_params = (args.fx, args.fy, args.cx, args.cy)
    elif args.tag_size:
        print("Warning: --tag-size given without --fx/--fy/--cx/--cy; pose disabled.")

    cam = Camera(args.url, snapshot=args.snapshot)

    while True:
        try:
            cam.open()
            print(f"Connected to {args.url}")
            break
        except ConnectionError as e:
            print(f"{e} — retrying in 2s...")
            time.sleep(2)

    fps_t, frames, fps = time.time(), 0, 0.0
    failures = 0

    try:
        while True:
            frame = cam.read()
            if frame is None:
                failures += 1
                if failures > 10:
                    print("Lost connection, reconnecting...")
                    cam.close()
                    time.sleep(1)
                    try:
                        cam.open()
                        failures = 0
                    except ConnectionError:
                        pass
                continue
            failures = 0

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            detections = detector.detect(
                gray,
                estimate_tag_pose=camera_params is not None,
                camera_params=camera_params,
                tag_size=args.tag_size,
            )

            for det in detections:
                distance = np.sqrt((det.corners[0][0] - det.center[0])**2 + (det.corners[0][1] - det.center[1])**2)
                msg = f"Tag {det.tag_id}: center=({det.center[0]:.1f}, {det.center[1]:.1f}) left corner=({det.corners[0][0]}, {det.corners[0][1]})"
                if det.pose_t is not None:
                    x, y, z = det.pose_t.flatten()
                    msg += f" pos(m)=({x:.3f}, {y:.3f}, {z:.3f})"
                print(msg)
                draw_detection(frame, det)

            frames += 1
            now = time.time()
            if now - fps_t >= 1.0:
                fps, frames, fps_t = frames / (now - fps_t), 0, now

            if not args.no_gui:
                cv2.putText(frame, f"{fps:.1f} FPS", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                cv2.imshow("ESP Cam - AprilTags", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()