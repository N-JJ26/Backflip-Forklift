#!/usr/bin/env python3
"""
Calibrate an ESP32-CAM (AI Thinker) to get fx, fy, cx, cy for AprilTag pose estimation.

Setup (Python 3.12):
    pip install opencv-python numpy

What you need:
    A printed checkerboard on a FLAT surface (tape it to a clipboard or board).
    Count the INNER corners (where four squares meet), not the squares.
    Example: a board with 10x7 squares has 9x6 inner corners.
    Measure one square's side length in meters.

Usage:
    python calibrate_esp_cam.py --url http://192.168.1.50:81/stream \
        --cols 9 --rows 6 --square-size 0.025

Controls (in the preview window):
    SPACE or 's'  save the current frame (only works when the board is detected)
    'c'           run calibration with the frames collected so far
    'q'           quit

Tips:
    * Calibrate at the SAME resolution you'll use for tag detection.
    * Collect 15-25 frames with the board at different angles, distances,
      and positions (including near the corners of the image).
    * Hold the board still when saving so the JPEG isn't motion-blurred.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

import cv2
import numpy as np


def open_source(url: str, snapshot: bool):
    if snapshot:
        return None
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        raise ConnectionError(f"Could not open stream: {url}")
    return cap


def read_frame(cap, url: str, snapshot: bool) -> np.ndarray | None:
    if snapshot:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = np.frombuffer(resp.read(), dtype=np.uint8)
            return cv2.imdecode(data, cv2.IMREAD_COLOR)
        except OSError:
            return None
    ok, frame = cap.read()
    return frame if ok else None


def calibrate(
    obj_points: list[np.ndarray],
    img_points: list[np.ndarray],
    image_size: tuple[int, int],
    output: str,
) -> None:
    print(f"\nCalibrating with {len(obj_points)} frames...")
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, image_size, None, None
    )

    # Mean reprojection error (more intuitive than RMS alone)
    total_err = 0.0
    for i in range(len(obj_points)):
        projected, _ = cv2.projectPoints(obj_points[i], rvecs[i], tvecs[i], K, dist)
        # OpenCV 5 can return these in different shapes/types, so normalize both to (N, 2)
        detected = np.asarray(img_points[i], dtype=np.float32).reshape(-1, 2)
        reprojected = np.asarray(projected, dtype=np.float32).reshape(-1, 2)
        # True per-frame RMS error in pixels: sqrt(sum of squared errors / N)
        total_err += cv2.norm(detected, reprojected, cv2.NORM_L2) / np.sqrt(len(reprojected))
    mean_err = total_err / len(obj_points)

    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])

    print("\n=== Calibration result ===")
    print(f"Image size:            {image_size[0]}x{image_size[1]}")
    print(f"RMS reprojection err:  {rms:.3f} px")
    print(f"Mean reprojection err: {mean_err:.3f} px  (under ~0.5 is good)")
    print(f"fx = {fx:.2f}")
    print(f"fy = {fy:.2f}")
    print(f"cx = {cx:.2f}")
    print(f"cy = {cy:.2f}")
    print(f"Distortion coeffs: {dist.ravel().round(5).tolist()}")

    result = {
        "image_width": image_size[0],
        "image_height": image_size[1],
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "camera_matrix": K.tolist(),
        "dist_coeffs": dist.ravel().tolist(),
        "rms_error": float(rms),
        "mean_reprojection_error": float(mean_err),
        "num_frames": len(obj_points),
    }
    with open(output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved to {output}")
    print("\nUse with the AprilTag script:")
    print(f"  --fx {fx:.2f} --fy {fy:.2f} --cx {cx:.2f} --cy {cy:.2f}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Camera calibration for an ESP camera")
    p.add_argument("--url", required=True, help="Stream (…:81/stream) or snapshot (…/capture) URL")
    p.add_argument("--snapshot", action="store_true", help="Poll single JPEGs instead of MJPEG stream")
    p.add_argument("--cols", type=int, required=True, help="Inner corners across (horizontal)")
    p.add_argument("--rows", type=int, required=True, help="Inner corners down (vertical)")
    p.add_argument("--square-size", type=float, required=True, help="Square side length in meters")
    p.add_argument("--min-frames", type=int, default=10, help="Minimum frames before calibrating")
    p.add_argument("--output", default="calibration.json", help="Output JSON file")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    pattern = (args.cols, args.rows)

    # 3D coordinates of the board corners in the board's own frame (z = 0 plane)
    objp = np.zeros((args.cols * args.rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0 : args.cols, 0 : args.rows].T.reshape(-1, 2)
    objp *= args.square_size

    cap = None
    while True:
        try:
            cap = open_source(args.url, args.snapshot)
            print(f"Connected to {args.url}")
            break
        except ConnectionError as e:
            print(f"{e} — retrying in 2s...")
            time.sleep(2)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    obj_points: list[np.ndarray] = []
    img_points: list[np.ndarray] = []
    image_size: tuple[int, int] | None = None

    print("SPACE/'s' = save frame, 'c' = calibrate, 'q' = quit")

    try:
        while True:
            frame = read_frame(cap, args.url, args.snapshot)
            if frame is None:
                time.sleep(0.05)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            image_size = (gray.shape[1], gray.shape[0])

            found, corners = cv2.findChessboardCorners(
                gray,
                pattern,
                cv2.CALIB_CB_ADAPTIVE_THRESH
                + cv2.CALIB_CB_NORMALIZE_IMAGE
                + cv2.CALIB_CB_FAST_CHECK,
            )

            display = frame.copy()
            if found:
                corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
                cv2.drawChessboardCorners(display, pattern, corners, found)

            status = "BOARD FOUND" if found else "no board"
            color = (0, 255, 0) if found else (0, 0, 255)
            cv2.putText(display, f"{status} | saved: {len(obj_points)}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.imshow("Calibration", display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord(" "), ord("s")):
                if found:
                    obj_points.append(objp)
                    img_points.append(corners)
                    print(f"Saved frame {len(obj_points)}")
                else:
                    print("Board not detected — frame not saved")
            elif key == ord("c"):
                if len(obj_points) < args.min_frames:
                    print(f"Need at least {args.min_frames} frames (have {len(obj_points)})")
                elif image_size is not None:
                    calibrate(obj_points, img_points, image_size, args.output)
                    break
            elif key == ord("q"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()