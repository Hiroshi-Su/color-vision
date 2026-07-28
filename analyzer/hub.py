"""ColorHub (Cloudflare Durable Object) への色データ転送クライアント。

環境変数 COLORHUB_WS_URL が設定されている場合のみ有効。
例: COLORHUB_WS_URL=wss://color-vision-worker.color-vision.workers.dev/ws
"""

import asyncio
import json
import time

import websockets


def build_palette_payload(result: dict, source: str = "") -> dict:
    """extract_colors() の結果を LED 向けの palette モード JSON に変換する。

    フォーマットは docs/LED_RD.md セクション7準拠:
    {"mode": "palette", "source": "tokyo", "dominant": [r, g, b],
     "colors": [{"rgb": [...], "percentage": ...}]}

    source は送信元拠点タグ（環境変数 LOCATION）。受信側（ESP32等）が
    「どの拠点の色を表示するか」を選別するために使う。空なら付けない。
    """
    colors = result.get("colors", [])
    payload = {
        "mode": "palette",
        "dominant": colors[0]["rgb"] if colors else [0, 0, 0],
        "colors": [
            {"rgb": c["rgb"], "percentage": c["percentage"]} for c in colors
        ],
    }
    if source:
        payload["source"] = source
    return payload


def build_matrix_payload(matrix_result: dict, source: str = "") -> dict:
    """extract_matrix() の結果を LED 向けの matrix モード JSON に変換する。

    フォーマットは docs/LED_RD.md セクション7準拠:
    {"mode": "matrix", "width": W, "height": H, "pixels": [[r,g,b], ...]}

    pixels は左上原点・行優先(row-major)。ESP32側が配線に合わせて
    (x, y) → LEDインデックスの座標変換を行う。
    """
    payload = {
        "mode": "matrix",
        "width": matrix_result.get("width", 0),
        "height": matrix_result.get("height", 0),
        "pixels": matrix_result.get("pixels", []),
    }
    if source:
        payload["source"] = source
    return payload


class ForwardGate:
    """LED向け配信の「間引き」と「時間帯制御」を判定するゲート。

    - forward_fps: 配信レート上限。0以下なら間引きなし（毎フレーム配信）。
      DO無料枠（10万リクエスト/日、WS受信20通=1リクエスト換算）対策として
      10fps程度を推奨。LED側にはフェード処理があるため体感は変わらない。
    - active_hours: "10-21" のような時間帯指定（ローカル時刻、10:00〜20:59に配信）。
      "22-6" のような日またぎも可。空文字なら常時配信（時間制限なし）。
    """

    def __init__(self, forward_fps: float = 0.0, active_hours: str = ""):
        self._min_interval = 1.0 / forward_fps if forward_fps > 0 else 0.0
        self._hours = self._parse_hours(active_hours)
        self._last_sent = 0.0

    @staticmethod
    def _parse_hours(spec: str) -> tuple[int, int] | None:
        spec = spec.strip()
        if not spec:
            return None  # 未設定 = 常時配信
        try:
            start_s, end_s = spec.split("-")
            start, end = int(start_s), int(end_s)
            if not (0 <= start <= 23 and 0 <= end <= 24):
                raise ValueError
            return (start, end)
        except ValueError:
            print(f"[gate] Invalid HUB_ACTIVE_HOURS: {spec!r} (expected e.g. '10-21'). Ignoring.")
            return None

    def in_active_hours(self) -> bool:
        if self._hours is None:
            return True
        start, end = self._hours
        h = time.localtime().tm_hour
        if start <= end:
            return start <= h < end
        return h >= start or h < end  # 日またぎ（例 "22-6"）

    def allow(self) -> bool:
        """今このフレームを配信してよいか。呼ぶと内部タイマーが進む。"""
        if not self.in_active_hours():
            return False
        if self._min_interval <= 0:
            return True
        now = time.monotonic()
        if now - self._last_sent < self._min_interval:
            return False
        self._last_sent = now
        return True


class ColorHubForwarder:
    """ColorHub への常時接続を維持し、色データを転送する。

    - 接続断は自動リトライ（reconnect_interval 秒間隔）
    - 未接続時の send() は黙って捨てる（解析処理をブロックしない）
    - forward_fps / active_hours により配信を間引く（DO無料枠対策）
    """

    def __init__(
        self,
        url: str,
        reconnect_interval: float = 3.0,
        forward_fps: float = 0.0,
        active_hours: str = "",
        on_message=None,
    ):
        self.url = url
        self.reconnect_interval = reconnect_interval
        # 他拠点から届いた色データを受け取るコールバック（Piでは LED 描画に使う）。
        # None なら受信データは読み捨てる（従来の送信専用動作）。
        self.on_message = on_message
        self._gate = ForwardGate(forward_fps, active_hours)
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
                    # 受信ループ。切断されるとループを抜けて再接続に回る
                    async for message in ws:
                        if self.on_message is None:
                            continue  # 送信専用モード: 受信データは読み捨てる
                        try:
                            payload = json.loads(message)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if isinstance(payload, dict):
                            self.on_message(payload)
            except Exception as e:
                print(f"[hub] Connection failed: {e}")
            finally:
                self._ws = None
            print(f"[hub] Reconnecting in {self.reconnect_interval}s...")
            await asyncio.sleep(self.reconnect_interval)

    async def send(self, payload: dict) -> None:
        if self._ws is None:
            return
        if not self._gate.allow():
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            print(f"[hub] Send failed: {e}")
