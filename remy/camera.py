import logging

from remy import config

logger = logging.getLogger(__name__)


class CameraUnavailableError(RuntimeError):
    pass


def capture() -> bytes:
    """Return JPEG-encoded bytes from the attached camera.

    Requires OpenCV and a reachable camera device (Jetson / physical hardware).
    Raises CameraUnavailableError if the camera cannot be opened or a frame
    cannot be read — the orchestrator catches this and returns a safe fallback.
    """
    try:
        import cv2  # noqa: PLC0415
    except ImportError as exc:
        raise CameraUnavailableError("opencv-python not installed") from exc

    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    if not cap.isOpened():
        raise CameraUnavailableError(f"Cannot open camera index={config.CAMERA_INDEX!r}")

    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            raise CameraUnavailableError("Camera opened but frame read failed")
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise CameraUnavailableError("JPEG encoding failed")
        return buf.tobytes()
    finally:
        cap.release()
