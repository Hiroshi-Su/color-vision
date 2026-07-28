"""Raspberry Pi 単体で動くColor Visionパイプライン。

  カメラ撮影 → K-means色抽出 → LED描画（GPIO直結）
                            └→ ColorHubへ送信（他拠点のLEDを光らせる）
  ColorHubから受信 ────────→ LED描画（他拠点の色を自分のLEDに映す）

ブラウザもESP32もArduinoも不要。1台で「撮る」と「光る」が完結する。

使い方:
  sudo -E python3 capture_pi.py          # DMAアクセスのためroot必須
  sudo -E python3 capture_pi.py --test   # LEDの配線確認（赤→緑→青）

LED_SOURCE で「どの拠点の色を自分のLEDに映すか」を決める:
  self      — 自分のカメラの色をそのまま自分のLEDへ（1台での動作確認用）
  <拠点名>   — その拠点の色だけを映す（例: kanazawa。クロス表示用）
  any       — 他拠点から届いたものは全部映す（自分の色は映さない）

CAPTURE_ENABLED=false にするとカメラを使わず「表示専用機」になる:
  他拠点の色を受け取ってLEDに映すだけ。カメラが繋がっていなくても動く。
  （撮影しないサテライト拠点をPiで組む場合に使う）
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from analyzer import extract_colors_bgr, extract_matrix_bgr  # noqa: E402
from camera_pi import CameraError, open_camera  # noqa: E402
from hub import ColorHubForwarder, build_matrix_payload, build_palette_payload  # noqa: E402
from led_pi import renderer_from_env, strip_from_env  # noqa: E402

# --- カメラ ---
# false にするとカメラを使わない「表示専用機」になる
CAPTURE_ENABLED = os.getenv("CAPTURE_ENABLED", "true").lower() not in ("false", "0", "no")
CAMERA_BACKEND = os.getenv("CAMERA_BACKEND", "auto")
CAPTURE_WIDTH = int(os.getenv("CAPTURE_WIDTH", "320"))
CAPTURE_HEIGHT = int(os.getenv("CAPTURE_HEIGHT", "240"))
CAPTURE_FPS = float(os.getenv("CAPTURE_FPS", "10"))

# --- 拠点・配信 ---
LOCATION = os.getenv("LOCATION", "")
COLORHUB_WS_URL = os.getenv("COLORHUB_WS_URL", "")
HUB_FORWARD_FPS = float(os.getenv("HUB_FORWARD_FPS", "10"))
HUB_ACTIVE_HOURS = os.getenv("HUB_ACTIVE_HOURS", "")

# --- 表示 ---
LED_MODE = os.getenv("LED_MODE", "palette").lower()
LED_SOURCE = os.getenv("LED_SOURCE", "self")
MATRIX_WIDTH = int(os.getenv("MATRIX_WIDTH", "16"))
MATRIX_HEIGHT = int(os.getenv("MATRIX_HEIGHT", "16"))
FRAME_INTERVAL_MS = int(os.getenv("LED_FRAME_INTERVAL_MS", "20"))

renderer = renderer_from_env()
running = True


def build_payload(frame) -> dict:
    """1フレームからLED向けペイロードを作る。"""
    if LED_MODE == "matrix":
        matrix = extract_matrix_bgr(frame, MATRIX_WIDTH, MATRIX_HEIGHT)
        return build_matrix_payload(matrix, LOCATION)
    result = extract_colors_bgr(frame)
    return build_palette_payload(result, LOCATION)


def should_render(payload: dict) -> bool:
    """このペイロードを自分のLEDに映すか判定する。"""
    source = payload.get("source", "")
    if LED_SOURCE == "self":
        return source == LOCATION or not source
    if LED_SOURCE == "any":
        return source != LOCATION
    return source == LED_SOURCE


def on_hub_message(payload: dict) -> None:
    """ColorHubから他拠点の色が届いたときのコールバック。"""
    if should_render(payload):
        renderer.apply_payload(payload)


async def led_loop(strip) -> None:
    """一定間隔でフェードを進めてLEDへ出力する（50fps程度）。"""
    interval = FRAME_INTERVAL_MS / 1000.0
    while running:
        strip.show(renderer.step())
        await asyncio.sleep(interval)


async def capture_loop(camera, hub) -> None:
    """カメラから撮影 → 解析 → LED/ハブへ流す。"""
    interval = 1.0 / CAPTURE_FPS if CAPTURE_FPS > 0 else 0.0
    fail_count = 0

    while running:
        started = time.monotonic()
        frame = camera.read()

        if frame is None:
            fail_count += 1
            if fail_count % 30 == 1:
                print("[camera] read failed (retrying)")
            await asyncio.sleep(0.5)
            continue
        fail_count = 0

        # 解析はCPUを使うので別スレッドに逃がし、LEDループを止めない
        payload = await asyncio.to_thread(build_payload, frame)

        if should_render(payload):
            renderer.apply_payload(payload)
        if hub:
            await hub.send(payload)

        elapsed = time.monotonic() - started
        await asyncio.sleep(max(0.0, interval - elapsed))


def self_test(strip) -> None:
    """配線とカラーオーダーの確認。赤→緑→青の順に全点灯する。

    「赤」と表示されるべき瞬間に別の色が出たら LED_COLOR_ORDER を見直す。
    """
    for name, rgb in (("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)), ("BLUE", (0, 0, 255))):
        print(f"[test] {name}")
        renderer.set_all(rgb)
        # フェードを飛ばして即座に目標色へ
        renderer.current = list(renderer.target)
        pixels = renderer.step()
        strip.show(pixels)
        print(f"       estimated current: {renderer.estimate_milliamps(pixels):.0f} mA")
        time.sleep(1.0)
    strip.off()
    print("[test] done")


async def main() -> int:
    global running

    strip = strip_from_env(renderer.num_leds)

    if "--test" in sys.argv:
        self_test(strip)
        return 0

    camera = None
    if CAPTURE_ENABLED:
        try:
            camera = open_camera(CAMERA_BACKEND, CAPTURE_WIDTH, CAPTURE_HEIGHT)
        except CameraError as e:
            strip.off()
            print(f"[error] {e}")
            print("       カメラを使わない表示専用機にする場合は "
                  "CAPTURE_ENABLED=false を設定してください")
            return 1
    else:
        # 表示専用機はハブから色を受け取るしか光る手段がない
        if not COLORHUB_WS_URL:
            strip.off()
            print("[error] CAPTURE_ENABLED=false のときは COLORHUB_WS_URL が必須です"
                  "（受け取る色がありません）")
            return 1
        if LED_SOURCE == "self":
            print("[warn] 表示専用機で LED_SOURCE=self は光りません。"
                  "相手の拠点名か any を指定してください")

    hub = None
    if COLORHUB_WS_URL:
        hub = ColorHubForwarder(
            COLORHUB_WS_URL,
            forward_fps=HUB_FORWARD_FPS,
            active_hours=HUB_ACTIVE_HOURS,
            on_message=on_hub_message,
        )
        hub.start()
        print(f"Hub: {COLORHUB_WS_URL}")
    else:
        print("Hub: disabled (set COLORHUB_WS_URL to enable)")

    print(f"Role        : {'capture + display' if camera else 'display only'}")
    print(f"Location    : {LOCATION or '(none)'}")
    print(f"LED source  : {LED_SOURCE}")
    print(f"LED mode    : {LED_MODE}"
          + (f" ({MATRIX_WIDTH}x{MATRIX_HEIGHT})" if LED_MODE == "matrix" else ""))
    print(f"LED count   : {renderer.num_leds} (brightness {renderer.brightness}, "
          f"cap {renderer.max_milliamps}mA)")
    if camera:
        print(f"Capture     : {CAPTURE_WIDTH}x{CAPTURE_HEIGHT} @ {CAPTURE_FPS}fps")
        print(f"Forward     : {HUB_FORWARD_FPS or 'unlimited'} fps, "
              f"hours {HUB_ACTIVE_HOURS or 'always'}")

    loop = asyncio.get_running_loop()

    def stop() -> None:
        global running
        running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)

    tasks = [led_loop(strip)]
    if camera:
        tasks.append(capture_loop(camera, hub))

    try:
        await asyncio.gather(*tasks)
    finally:
        if camera:
            camera.close()
        strip.off()
        print("Stopped. LEDs off.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
