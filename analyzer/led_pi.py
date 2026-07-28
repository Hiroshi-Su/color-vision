"""Raspberry Pi の GPIO から WS2812B を直接駆動するLEDレンダラー。

ESP32ファーム（firmware/colorvision_led/colorvision_led.ino）と
同じ描画ロジックをPython側に移植したもの。Arduino/ESP32は不要。

- palette: 占有率に比例した帯グラフ
- matrix : 低解像度グリッド（蛇行配線・スタート角に対応）
- 毎フレーム現在色→目標色へブレンドして滑らかに遷移
- 輝度上限＋消費電流のソフトキャップ（USB給電時の安全装置）

描画ロジック（LedRenderer）はハードウェアに依存しないので、
rpi_ws281x が無い環境（Mac等）でもテスト・シミュレーションできる。
実際のLED出力は PiLedStrip が担当する。

配線（rpi_ws281x の既定チャンネル）:
  Pi GPIO18 (物理12番) → LED Data In（緑線）
  Pi GND              → LED GND（黒線）
  5V電源              → LED 5V（赤線）※Piの5Vピンは1A程度まで。多数なら外部電源
  ※ 電源を外部にする場合も GND は Pi と共通にすること
"""

from __future__ import annotations

import os

# WS2812B 1個あたりの最大電流（mA）。R/G/Bそれぞれ約20mA
_MA_PER_CHANNEL_FULL = 20.0


def xy_to_index(
    x: int,
    y: int,
    width: int,
    height: int,
    serpentine: bool = True,
    vertical: bool = False,
    start_corner: int = 2,
) -> int:
    """論理座標(x=左から, y=上から)を物理LEDインデックスに変換する。

    ESP32ファームの xyToIndex() と同一ロジック。
    start_corner: 0=左上 1=右上 2=左下 3=右下（DIをつなぐ物理的な角）
    """
    start_left = start_corner in (0, 2)
    start_top = start_corner in (0, 1)

    if not vertical:
        ry = y if start_top else (height - 1 - y)
        ltr = start_left
        if serpentine and (ry & 1):
            ltr = not ltr
        col = x if ltr else (width - 1 - x)
        return ry * width + col

    cx = x if start_left else (width - 1 - x)
    ttb = start_top
    if serpentine and (cx & 1):
        ttb = not ttb
    row = y if ttb else (height - 1 - y)
    return cx * height + row


class LedRenderer:
    """LEDバッファの計算だけを行う（ハードウェア非依存）。

    current[i] / target[i] は (r, g, b) のタプル。
    """

    def __init__(
        self,
        num_leds: int,
        brightness: int = 20,
        max_milliamps: int = 400,
        fade_amount: int = 40,
        matrix_width: int = 0,
        matrix_height: int = 1,
        matrix_serpentine: bool = True,
        matrix_vertical: bool = False,
        matrix_start_corner: int = 2,
        panel_bases: dict[str, int] | None = None,
    ):
        self.num_leds = num_leds
        self.brightness = max(0, min(255, brightness))
        self.max_milliamps = max_milliamps
        self.fade_amount = max(1, min(255, fade_amount))
        self.matrix_width = matrix_width or num_leds
        self.matrix_height = matrix_height
        self.matrix_serpentine = matrix_serpentine
        self.matrix_vertical = matrix_vertical
        self.matrix_start_corner = matrix_start_corner
        # 拠点名 → パネル先頭インデックス（複数マトリクスを直列にした場合）
        self.panel_bases = panel_bases or {}

        self.current = [(0, 0, 0)] * num_leds
        self.target = [(0, 0, 0)] * num_leds

    # ---------------- 目標色の設定 ----------------

    def set_palette(self, colors: list[dict], base: int = 0, span: int | None = None) -> None:
        """占有率に比例した帯グラフを target に書き込む。

        base/span を指定するとテープの一部区間だけに描ける
        （複数拠点をゾーン分割して表示する場合に使う）。
        """
        if not colors:
            return
        span = self.num_leds - base if span is None else span
        if span <= 0:
            return

        start = 0
        cum = 0.0
        last = (0, 0, 0)
        for c in colors:
            rgb = c.get("rgb") or []
            if len(rgb) < 3:
                continue
            col = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            last = col
            cum += float(c.get("percentage", 0.0))
            end = int(cum / 100.0 * span + 0.5)
            end = min(end, span)
            for i in range(start, end):
                self.target[base + i] = col
            start = end

        # 占有率の合計が100に満たない分は最後の色で埋める
        for i in range(start, span):
            self.target[base + i] = last

    def set_matrix(self, pixels: list, width: int, height: int, base: int = 0) -> None:
        """低解像度グリッドを配線に合わせて target に書き込む。"""
        if not pixels:
            return
        w = width or self.matrix_width
        h = height or self.matrix_height
        for i, rgb in enumerate(pixels):
            if not rgb or len(rgb) < 3:
                continue
            x = i % w
            y = i // w
            if y >= h:
                break
            idx = base + xy_to_index(
                x, y, w, h,
                self.matrix_serpentine, self.matrix_vertical, self.matrix_start_corner,
            )
            if 0 <= idx < self.num_leds:
                self.target[idx] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))

    def apply_payload(self, payload: dict) -> bool:
        """palette/matrix のJSONペイロードを target に反映する。

        payload["source"] が panel_bases に登録されていれば、
        その拠点専用のパネル区画に描画する（複数マトリクス構成）。
        戻り値: 描画対象として受け付けたか
        """
        mode = payload.get("mode", "palette")
        source = payload.get("source", "")
        base = self.panel_bases.get(source, 0)

        if mode == "palette":
            span = None
            if self.panel_bases:
                # ゾーン分割時は自分の区画の幅だけに描く
                span = self._panel_span(base)
            self.set_palette(payload.get("colors", []), base, span)
            return True
        if mode == "matrix":
            self.set_matrix(
                payload.get("pixels", []),
                payload.get("width", 0),
                payload.get("height", 0),
                base,
            )
            return True
        return False

    def _panel_span(self, base: int) -> int:
        """base の次に始まる区画までの長さ（ゾーン分割時の1区画の幅）。"""
        nexts = [b for b in self.panel_bases.values() if b > base]
        return (min(nexts) if nexts else self.num_leds) - base

    def set_all(self, rgb: tuple[int, int, int]) -> None:
        self.target = [rgb] * self.num_leds

    def clear(self) -> None:
        """即座に全消灯（フェードを待たない）。"""
        self.target = [(0, 0, 0)] * self.num_leds
        self.current = [(0, 0, 0)] * self.num_leds

    # ---------------- フレーム計算 ----------------

    @staticmethod
    def _blend(a: int, b: int, amount: int) -> int:
        """a から b へ amount/255 の割合で近づける（FastLEDのblend相当）。

        差が小さいと整数除算で移動量が0になり目標色に届かないまま
        停滞するため、差がある限り最低1は動かして必ず収束させる。
        """
        diff = b - a
        if diff == 0:
            return a
        step = diff * amount // 255
        if step == 0:
            step = 1 if diff > 0 else -1
        return a + step

    def step(self) -> list[tuple[int, int, int]]:
        """1フレーム分フェードを進め、実際に出力する色列を返す。

        戻り値には輝度・電流キャップを適用済み。
        """
        amount = self.fade_amount
        self.current = [
            (
                self._blend(c[0], t[0], amount),
                self._blend(c[1], t[1], amount),
                self._blend(c[2], t[2], amount),
            )
            for c, t in zip(self.current, self.target)
        ]
        return self._apply_limits(self.current)

    def _apply_limits(self, pixels: list) -> list:
        """輝度スケール＋消費電流のソフトキャップを適用する。

        rpi_ws281x には FastLED の setMaxPowerInVoltsAndMilliamps に
        相当する機能がないため、ここで同等の保護を行う。
        """
        scale = self.brightness / 255.0

        if self.max_milliamps > 0:
            # 全チャンネルの合計から概算電流を求める
            total = sum(p[0] + p[1] + p[2] for p in pixels)
            est_ma = total / 255.0 * _MA_PER_CHANNEL_FULL * scale
            if est_ma > self.max_milliamps:
                scale *= self.max_milliamps / est_ma

        return [
            (int(p[0] * scale), int(p[1] * scale), int(p[2] * scale))
            for p in pixels
        ]

    def estimate_milliamps(self, pixels: list | None = None) -> float:
        """出力色列の概算消費電流（mA）。配線・電源設計の目安に使う。"""
        px = pixels if pixels is not None else self._apply_limits(self.current)
        total = sum(p[0] + p[1] + p[2] for p in px)
        return total / 255.0 * _MA_PER_CHANNEL_FULL


class PiLedStrip:
    """rpi_ws281x を使った実際のLED出力。

    rpi_ws281x はDMAを使うため root 権限が必要（sudo で実行）。
    またオンボードオーディオと競合するので無効化しておくこと。
    詳細は docs/LED_PI_SETUP.md 参照。
    """

    def __init__(
        self,
        num_leds: int,
        pin: int = 18,
        color_order: str = "GRB",
        dma: int = 10,
        channel: int = 0,
        freq_hz: int = 800_000,
    ):
        try:
            from rpi_ws281x import PixelStrip, Color, ws
        except ImportError as e:
            raise RuntimeError(
                "rpi_ws281x not installed. Run: sudo pip3 install rpi_ws281x "
                "--break-system-packages"
            ) from e

        self._Color = Color
        strip_types = {
            "GRB": ws.WS2811_STRIP_GRB,   # WS2812B の標準
            "RGB": ws.WS2811_STRIP_RGB,
            "BRG": ws.WS2811_STRIP_BRG,
            "GRBW": ws.SK6812_STRIP_GRBW,  # SK6812（RGBW）用
        }
        strip_type = strip_types.get(color_order.upper())
        if strip_type is None:
            raise ValueError(f"Unknown LED_COLOR_ORDER: {color_order!r}")

        # 輝度スケールはレンダラー側で行うのでライブラリ側は255（素通し）
        self._strip = PixelStrip(
            num_leds, pin, freq_hz, dma, False, 255, channel, strip_type
        )
        self._strip.begin()
        self.num_leds = num_leds

    def show(self, pixels: list) -> None:
        for i, (r, g, b) in enumerate(pixels):
            self._strip.setPixelColor(i, self._Color(r, g, b))
        self._strip.show()

    def off(self) -> None:
        self.show([(0, 0, 0)] * self.num_leds)


def renderer_from_env() -> LedRenderer:
    """環境変数から LedRenderer を組み立てる。"""
    panel_bases: dict[str, int] = {}
    # 例: LED_PANELS=kanazawa:0,osaka:256
    spec = os.getenv("LED_PANELS", "").strip()
    if spec:
        for part in spec.split(","):
            if ":" not in part:
                continue
            name, base = part.split(":", 1)
            try:
                panel_bases[name.strip()] = int(base)
            except ValueError:
                print(f"[led] Invalid LED_PANELS entry: {part!r}")

    return LedRenderer(
        num_leds=int(os.getenv("LED_COUNT", "144")),
        brightness=int(os.getenv("LED_BRIGHTNESS", "20")),
        max_milliamps=int(os.getenv("LED_MAX_MILLIAMPS", "400")),
        fade_amount=int(os.getenv("LED_FADE_AMOUNT", "40")),
        matrix_width=int(os.getenv("MATRIX_WIDTH", "0")),
        matrix_height=int(os.getenv("MATRIX_HEIGHT", "1")),
        matrix_serpentine=os.getenv("MATRIX_SERPENTINE", "true").lower() == "true",
        matrix_vertical=os.getenv("MATRIX_VERTICAL", "false").lower() == "true",
        matrix_start_corner=int(os.getenv("MATRIX_START_CORNER", "2")),
        panel_bases=panel_bases,
    )


def strip_from_env(num_leds: int) -> PiLedStrip:
    """環境変数から PiLedStrip を組み立てる。"""
    return PiLedStrip(
        num_leds=num_leds,
        pin=int(os.getenv("LED_GPIO_PIN", "18")),
        color_order=os.getenv("LED_COLOR_ORDER", "GRB"),
    )
