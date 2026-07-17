import asyncio
import json
import os

import websockets

from analyzer import extract_colors
from hub import ColorHubForwarder, build_palette_payload

HOST = os.getenv("WS_HOST", "0.0.0.0")
PORT = int(os.getenv("WS_PORT", "8765"))
# 設定するとColorHub（Cloudflare）にも色データを転送する
# 例: wss://color-vision-worker.color-vision.workers.dev/ws
COLORHUB_WS_URL = os.getenv("COLORHUB_WS_URL", "")

hub = ColorHubForwarder(COLORHUB_WS_URL) if COLORHUB_WS_URL else None


async def handler(websocket):
    print(f"Client connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                result = extract_colors(message)
                # 既存: ブラウザに解析結果を返す
                await websocket.send(json.dumps(result))
                # 追加: ColorHub経由でLED（ESP32）等にも配信
                if hub:
                    await hub.send(build_palette_payload(result))
    except websockets.exceptions.ConnectionClosedOK:
        pass
    finally:
        print(f"Client disconnected: {websocket.remote_address}")


async def main():
    if hub:
        hub.start()
        print(f"ColorHub forwarding enabled: {COLORHUB_WS_URL}")
    else:
        print("ColorHub forwarding disabled (set COLORHUB_WS_URL to enable)")

    print(f"Starting analyzer WebSocket server on ws://{HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
