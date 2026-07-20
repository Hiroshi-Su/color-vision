import asyncio
import json
import os

import websockets
from dotenv import load_dotenv

from analyzer import extract_colors, extract_matrix
from hub import ColorHubForwarder, build_palette_payload, build_matrix_payload

# 同ディレクトリの .env を読み込む（既存の環境変数は上書きしない）。
# .env が無くてもエラーにはならないので、環境変数を直接渡す運用とも共存できる。
load_dotenv()

HOST = os.getenv("WS_HOST", "0.0.0.0")
PORT = int(os.getenv("WS_PORT", "8765"))
# 設定するとColorHub（Cloudflare）にも色データを転送する
# 例: wss://color-vision-worker.color-vision.workers.dev/ws
COLORHUB_WS_URL = os.getenv("COLORHUB_WS_URL", "")

# LEDへ配信するモード: "palette"（5色帯・横一列） or "matrix"（低解像度映像）
LED_MODE = os.getenv("LED_MODE", "palette").lower()
# matrixモード時のグリッド解像度（= 設置するLEDの 横個数 × 縦個数）
MATRIX_WIDTH = int(os.getenv("MATRIX_WIDTH", "16"))
MATRIX_HEIGHT = int(os.getenv("MATRIX_HEIGHT", "16"))

hub = ColorHubForwarder(COLORHUB_WS_URL) if COLORHUB_WS_URL else None


async def handler(websocket):
    print(f"Client connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # paletteは常に解析（ブラウザのビジュアライザが常時使うため）
                result = extract_colors(message)

                # matrixモード時はグリッドも解析（hubの有無と独立）。
                # これによりColorHub未接続でもブラウザ側でmatrixプレビューできる。
                matrix_payload = None
                if LED_MODE == "matrix":
                    matrix = extract_matrix(message, MATRIX_WIDTH, MATRIX_HEIGHT)
                    matrix_payload = build_matrix_payload(matrix)

                # ブラウザへ返信。matrixモード時はプレビュー用に matrix も同梱する
                # （既存フロントは未知フィールドを無視するので後方互換）
                response = dict(result)
                if matrix_payload is not None:
                    response["matrix"] = matrix_payload
                await websocket.send(json.dumps(response))

                # LED（ESP32）へは LED_MODE に応じたペイロードを配信
                if hub:
                    if matrix_payload is not None:
                        await hub.send(matrix_payload)
                    else:
                        await hub.send(build_palette_payload(result))
    except websockets.exceptions.ConnectionClosedOK:
        pass
    finally:
        print(f"Client disconnected: {websocket.remote_address}")


async def main():
    if hub:
        hub.start()
        print(f"ColorHub forwarding enabled: {COLORHUB_WS_URL}")
        if LED_MODE == "matrix":
            print(f"LED mode: matrix ({MATRIX_WIDTH}x{MATRIX_HEIGHT})")
        else:
            print("LED mode: palette")
    else:
        print("ColorHub forwarding disabled (set COLORHUB_WS_URL to enable)")

    print(f"Starting analyzer WebSocket server on ws://{HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
