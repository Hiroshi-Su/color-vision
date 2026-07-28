"""Raspberry Pi のカメラ抽象レイヤー。

USBウェブカメラ（OpenCV）と Piカメラ / CSI接続（picamera2）の
どちらでも同じインターフェースで使えるようにする。

環境変数 CAMERA_BACKEND:
  auto (既定) — usb を試し、開けなければ csi にフォールバック
  usb         — cv2.VideoCapture を使う
  csi         — picamera2 を使う（libcamera系。cv2では開けない）

いずれの実装も read() で BGR の numpy 配列を返すので、
呼び出し側（capture_pi.py）はカメラの種類を気にしなくてよい。
"""

from __future__ import annotations


class CameraError(RuntimeError):
    pass


class UsbCamera:
    """USBウェブカメラ（OpenCVのVideoCapture経由）。"""

    name = "usb"

    def __init__(self, width: int, height: int, device: int = 0):
        import cv2

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            raise CameraError(f"USB camera not found (device={device})")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # 内部バッファを最小にして「古いフレーム」が出てくる遅延を抑える
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def read(self):
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        self._cap.release()


class CsiCamera:
    """Piカメラ / CSI接続（picamera2経由）。

    現在のRaspberry Pi OSはlibcameraスタックなので、
    CSIカメラは cv2.VideoCapture では開けず picamera2 が必要。
    """

    name = "csi"

    def __init__(self, width: int, height: int):
        try:
            from picamera2 import Picamera2
        except ImportError as e:
            raise CameraError(
                "picamera2 not installed. Run: sudo apt install -y python3-picamera2"
            ) from e

        self._cam = Picamera2()
        # BGR888 を指定するとOpenCVと同じチャンネル順で受け取れる
        config = self._cam.create_preview_configuration(
            main={"size": (width, height), "format": "BGR888"}
        )
        self._cam.configure(config)
        self._cam.start()

    def read(self):
        return self._cam.capture_array()

    def close(self) -> None:
        self._cam.stop()
        self._cam.close()


def open_camera(backend: str, width: int, height: int, device: int = 0):
    """backend に応じてカメラを開く。auto なら usb → csi の順に試す。"""
    backend = (backend or "auto").lower()

    if backend == "usb":
        return UsbCamera(width, height, device)
    if backend == "csi":
        return CsiCamera(width, height)
    if backend != "auto":
        raise CameraError(f"Unknown CAMERA_BACKEND: {backend!r} (use auto/usb/csi)")

    errors = []
    for factory in (lambda: UsbCamera(width, height, device), lambda: CsiCamera(width, height)):
        try:
            cam = factory()
            print(f"[camera] backend={cam.name} ({width}x{height})")
            return cam
        except Exception as e:  # CameraError / picamera2内部エラー等
            errors.append(str(e))
    raise CameraError("No camera available. Tried usb and csi:\n  " + "\n  ".join(errors))
