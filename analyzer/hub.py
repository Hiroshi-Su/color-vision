"""ColorHub (Cloudflare Durable Object) への色データ転送クライアント。

環境変数 COLORHUB_WS_URL が設定されている場合のみ有効。
例: COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws
"""

import asyncio
import json

import websockets


def build_palette_payload(result: dict) -> dict:
    """extract_colors() の結果を LED 向けの palette モード JSON に変換する。

    フォーマットは docs/LED_RD.md セクション7準拠:
    {"mode": "palette", "dominant": [r, g, b], "colors": [{"rgb": [...], "percentage": ...}]}
    """
    colors = result.get("colors", [])
    return {
        "mode": "palette",
        "dominant": colors[0]["rgb"] if colors else [0, 0, 0],
        "colors": [
            {"rgb": c["rgb"], "percentage": c["percentage"]} for c in colors
        ],
    }


def build_matrix_payload(matrix_result: dict) -> dict:
    """extract_matrix() の結果を LED 向けの matrix モード JSON に変換する。

    フォーマットは docs/LED_RD.md セクション7準拠:
    {"mode": "matrix", "width": W, "height": H, "pixels": [[r,g,b], ...]}

    pixels は左上原点・行優先(row-major)。ESP32側が配線に合わせて
    (x, y) → LEDインデックスの座標変換を行う。
    """
    return {
        "mode": "matrix",
        "width": matrix_result.get("width", 0),
        "height": matrix_result.get("height", 0),
        "pixels": matrix_result.get("pixels", []),
    }


class ColorHubForwarder:
    """ColorHub への常時接続を維持し、色データを転送する。

    - 接続断は自動リトライ（reconnect_interval 秒間隔）
    - 未接続時の send() は黙って捨てる（解析処理をブロックしない）
    """

    def __init__(self, url: str, reconnect_interval: float = 3.0):
        self.url = url
        self.reconnect_interval = reconnect_interval
        self._ws = None
        self._task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def start(self) -> None:
        """バックグラウンドで接続維持ループを開始する（イベントループ内で呼ぶこと）"""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    self._ws = ws
                    print(f"[hub] Connected to ColorHub: {self.url}")
                    await ws.wait_closed()
            except Exception as e:
                print(f"[hub] Connection failed: {e}")
            finally:
                self._ws = None
            print(f"[hub] Reconnecting in {self.reconnect_interval}s...")
            await asyncio.sleep(self.reconnect_interval)

    async def send(self, payload: dict) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            print(f"[hub] Send failed: {e}")
