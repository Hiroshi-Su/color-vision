import asyncio
import json
import os

import websockets
from dotenv import load_dotenv

from analyzer import extract_colors, extract_matrix
from hub import (
    ColorHubForwarder,
    ForwardGate,
    build_palette_payload,
    build_matrix_payload,
)

# 同ディレクトリの .env を読み込む（既存の環境変数は上書きしない）。
# .env が無くてもエラーにはならないので、環境変数を直接渡す運用とも共存できる。
load_dotenv()

HOST = os.getenv("WS_HOST", "0.0.0.0")
PORT = int(os.getenv("WS_PORT", "8765"))

# --- ハブ転送設定（DOモード / Tunnelモードの切り替えはURLだけで決まる）---
# DOモード:     COLORHUB_WS_URL=wss://color-vision-worker...workers.dev/ws
# Tunnelモード: COLORHUB_WS_URL=wss://<相手拠点のTunnel URL>
#               （相手のmain.pyに直接送り、相手側がローカル配信する）
# 未設定なら外部転送なし（ローカル配信のみ）
COLORHUB_WS_URL = os.getenv("COLORHUB_WS_URL", "")

# 送信元拠点タグ（例: tokyo / kanazawa）。受信側がどの拠点の色を
# 表示するか選別するために使う。空なら付けない。
LOCATION = os.getenv("LOCATION", "")

# LED向け配信のレート上限（fps）。0で間引きなし。
# DO無料枠（10万リクエスト/日）対策として10fps推奨。
HUB_FORWARD_FPS = float(os.getenv("HUB_FORWARD_FPS", "10"))

# LED向け配信の時間帯（例 "10-21" = 10:00〜20:59のみ配信）。
# 未設定（空）なら時間制限なしで常時配信。
HUB_ACTIVE_HOURS = os.getenv("HUB_ACTIVE_HOURS", "")

# LEDへ配信するモード: "palette"（5色帯・横一列） or "matrix"（低解像度映像）
LED_MODE = os.getenv("LED_MODE", "palette").lower()
# matrixモード時のグリッド解像度（= 設置するLEDの 横個数 × 縦個数）
MATRIX_WIDTH = int(os.getenv("MATRIX_WIDTH", "16"))
MATRIX_HEIGHT = int(os.getenv("MATRIX_HEIGHT", "16"))

hub = (
    ColorHubForwarder(
        COLORHUB_WS_URL,
        forward_fps=HUB_FORWARD_FPS,
        active_hours=HUB_ACTIVE_HOURS,
    )
    if COLORHUB_WS_URL
    else None
)

# ローカル配信（このサーバーに直接繋いだESP32等への配信）用ゲート。
# ハブ転送と同じ設定にすることで、Tunnel/DOどちらのモードでも
# LEDの更新頻度が同じになり、A/B検証の条件が揃う。
local_gate = ForwardGate(HUB_FORWARD_FPS, HUB_ACTIVE_HOURS)

# 接続中の全クライアント（ブラウザ / ESP32 / 相手拠点のforwarder）
clients: set = set()


async def broadcast(payload: dict, exclude=None) -> None:
    """接続中の全クライアント（exclude以外）にJSONを配信する。"""
    if not clients:
        return
    message = json.dumps(payload)
    for client in list(clients):
        if client is exclude:
            continue
        try:
            await client.send(message)
        except Exception:
            pass  # 切断途中のクライアントは無視（finallyで除去される）


async def handler(websocket):
    print(f"Client connected: {websocket.remote_address}")
    clients.add(websocket)
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # === バイナリ = カメラフレーム（ブラウザ / ESP32-CAM）===
                # paletteは常に解析（ブラウザのビジュアライザが常時使うため）
                result = extract_colors(message)

                # matrixモード時はグリッドも解析（hubの有無と独立）。
                # これによりColorHub未接続でもブラウザ側でmatrixプレビューできる。
                matrix_payload = None
                if LED_MODE == "matrix":
                    matrix = extract_matrix(message, MATRIX_WIDTH, MATRIX_HEIGHT)
                    matrix_payload = build_matrix_payload(matrix, LOCATION)

                # ブラウザへ返信。matrixモード時はプレビュー用に matrix も同梱する
                # （既存フロントは未知フィールドを無視するので後方互換）
                response = dict(result)
                if matrix_payload is not None:
                    response["matrix"] = matrix_payload
                await websocket.send(json.dumps(response))

                # LED向けペイロードを配信（間引き・時間帯はゲートが判定）
                led_payload = (
                    matrix_payload
                    if matrix_payload is not None
                    else build_palette_payload(result, LOCATION)
                )
                # ① 外部ハブへ（DOモード: ColorHub / Tunnelモード: 相手拠点）
                if hub:
                    await hub.send(led_payload)
                # ② ローカル接続クライアントへ（Tunnelモードで自拠点のESP32が
                #    このサーバーに直接繋いでいる場合の配信路）
                if local_gate.allow():
                    await broadcast(led_payload, exclude=websocket)
            else:
                # === テキスト = 相手拠点からの色データ（Tunnelモード）===
                # 相手のColorHubForwarderがこのサーバーに直接送ってくる。
                # ローカル接続クライアント（ESP32等）へそのまま中継する。
                # 送信元で間引き済みなのでゲートは通さない。
                try:
                    payload = json.loads(message)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(payload, dict) and "mode" in payload:
                    await broadcast(payload, exclude=websocket)
    except websockets.exceptions.ConnectionClosedOK:
        pass
    finally:
        clients.discard(websocket)
        print(f"Client disconnected: {websocket.remote_address}")


async def main():
    if hub:
        hub.start()
        print(f"Hub forwarding enabled: {COLORHUB_WS_URL}")
    else:
        print("Hub forwarding disabled (set COLORHUB_WS_URL to enable)")

    print(f"Location tag: {LOCATION or '(none)'}")
    print(f"Forward rate: {HUB_FORWARD_FPS or 'unlimited'} fps")
    print(f"Active hours: {HUB_ACTIVE_HOURS or 'always'}")
    if LED_MODE == "matrix":
        print(f"LED mode: matrix ({MATRIX_WIDTH}x{MATRIX_HEIGHT})")
    else:
        print("LED mode: palette")

    print(f"Starting analyzer WebSocket server on ws://{HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
