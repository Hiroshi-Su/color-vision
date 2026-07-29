#!/usr/bin/env python3
"""ColorHub に任意の色を送ってLEDを光らせるデバッグツール。

カメラや解析を通さず直接色を指定できるので、
「配線が悪いのか / ハブ接続が悪いのか / 解析が悪いのか」の切り分けに使う。

接続先は .env の COLORHUB_WS_URL を使う（--url で上書き可）。
Piでも動く（wscatはNode製で使えないためこちらを用意）。

使用例:
  python3 send_test_color.py red                  色名で送る
  python3 send_test_color.py "#ff00ff"            HEXで送る
  python3 send_test_color.py 255,0,255            RGBで送る
  python3 send_test_color.py red blue             複数色（帯グラフになる）
  python3 send_test_color.py red:70 blue:30       占有率を指定
  python3 send_test_color.py --off                消灯する
  python3 send_test_color.py --cycle              色を巡回させ続ける（Ctrl+Cで停止）
  python3 send_test_color.py red --source osaka   送信元タグを変える（フィルタ確認）
  python3 send_test_color.py --matrix red         matrixモードで送る（全面塗り）
  python3 send_test_color.py --local red          ローカルのanalyzerに直接送る

受信側（ESP32のLISTEN_SOURCE / Piのled_source）が拠点名でフィルタしている場合は
--source をその拠点名に合わせないと光らないので注意。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import websockets
from dotenv import load_dotenv

load_dotenv()

NAMED_COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 128, 0),
    "purple": (128, 0, 255),
    "pink": (255, 128, 192),
    "warm": (255, 180, 100),   # 電球色
    "cool": (180, 220, 255),   # 昼白色
}

# --cycle で巡回する色（配線・カラーオーダー確認に使いやすい順）
CYCLE_COLORS = ["red", "green", "blue", "white", "black"]


def parse_color(spec: str) -> tuple[tuple[int, int, int], float | None]:
    """"red" / "#ff00ff" / "255,0,255" / "red:70" を (rgb, 占有率) に変換する。"""
    pct = None
    if ":" in spec and not spec.startswith("#"):
        spec, pct_s = spec.rsplit(":", 1)
        try:
            pct = float(pct_s)
        except ValueError:
            raise SystemExit(f"占有率が数値ではありません: {pct_s!r}")

    key = spec.strip().lower()

    if key in NAMED_COLORS:
        return NAMED_COLORS[key], pct

    if key.startswith("#"):
        h = key[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            raise SystemExit(f"HEXの形式が不正です: {spec!r}（例: #ff00ff）")
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)), pct
        except ValueError:
            raise SystemExit(f"HEXの形式が不正です: {spec!r}")

    if "," in key:
        parts = [p.strip() for p in key.split(",")]
        if len(parts) != 3:
            raise SystemExit(f"RGBは3つの数値で指定してください: {spec!r}")
        try:
            rgb = tuple(int(p) for p in parts)
        except ValueError:
            raise SystemExit(f"RGBが数値ではありません: {spec!r}")
        if any(v < 0 or v > 255 for v in rgb):
            raise SystemExit(f"RGBは0〜255で指定してください: {spec!r}")
        return rgb, pct  # type: ignore[return-value]

    raise SystemExit(
        f"色を解釈できません: {spec!r}\n"
        f"  色名: {', '.join(NAMED_COLORS)}\n"
        f"  HEX : #ff00ff\n"
        f"  RGB : 255,0,255"
    )


def build_palette(specs: list[str], source: str) -> dict:
    """色指定のリストから palette ペイロードを作る。

    占有率を省略した色には、残りを均等配分する。
    """
    parsed = [parse_color(s) for s in specs]
    fixed_total = sum(p for _, p in parsed if p is not None)
    auto_count = sum(1 for _, p in parsed if p is None)
    auto_pct = max(0.0, 100.0 - fixed_total) / auto_count if auto_count else 0.0

    colors = [
        {"rgb": list(rgb), "percentage": round(pct if pct is not None else auto_pct, 2)}
        for rgb, pct in parsed
    ]
    payload = {"mode": "palette", "dominant": colors[0]["rgb"], "colors": colors}
    if source:
        payload["source"] = source
    return payload


def build_matrix(specs: list[str], source: str, width: int, height: int) -> dict:
    """matrixモード用。1色なら全面塗り、複数色なら縦帯に分割する。"""
    parsed = [parse_color(s)[0] for s in specs]
    pixels = []
    for _y in range(height):
        for x in range(width):
            pixels.append(list(parsed[x * len(parsed) // width]))
    payload = {"mode": "matrix", "width": width, "height": height, "pixels": pixels}
    if source:
        payload["source"] = source
    return payload


async def send(url: str, payloads: list[dict], repeat: float) -> int:
    try:
        async with websockets.connect(url) as ws:
            print(f"connected: {url}")
            if repeat <= 0:
                for p in payloads:
                    await ws.send(json.dumps(p))
                    print(f"sent: {describe(p)}")
                # 送信直後に切断すると届く前に閉じることがあるので少し待つ
                await asyncio.sleep(0.3)
                return 0

            print(f"cycling every {repeat}s (Ctrl+C to stop)")
            while True:
                for p in payloads:
                    await ws.send(json.dumps(p))
                    print(f"sent: {describe(p)}")
                    await asyncio.sleep(repeat)
    except asyncio.CancelledError:
        raise
    except OSError as e:
        print(f"[error] 接続できません: {e}", file=sys.stderr)
        print("        URLとネットワークを確認してください。", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def describe(payload: dict) -> str:
    src = payload.get("source", "-")
    if payload["mode"] == "matrix":
        return f"matrix {payload['width']}x{payload['height']} source={src}"
    parts = ", ".join(
        f"rgb{tuple(c['rgb'])} {c['percentage']}%" for c in payload["colors"]
    )
    return f"palette [{parts}] source={src}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ColorHubに任意の色を送ってLEDを光らせる",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="色名: " + ", ".join(NAMED_COLORS),
    )
    parser.add_argument("colors", nargs="*", help="色（色名 / #hex / r,g,b / 色:占有率）")
    parser.add_argument("--url", default=os.getenv("COLORHUB_WS_URL", ""),
                        help="接続先（既定は .env の COLORHUB_WS_URL）")
    parser.add_argument("--local", action="store_true",
                        help="ローカルのanalyzer（ws://localhost:8765）に送る")
    parser.add_argument("--source", default=os.getenv("LOCATION", "tokyo"),
                        help="送信元拠点タグ（既定は .env の LOCATION）")
    parser.add_argument("--off", action="store_true", help="消灯する")
    parser.add_argument("--cycle", action="store_true",
                        help="赤→緑→青→白→消灯を巡回し続ける")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="--cycle / 複数色巡回の間隔（秒, 既定1.0）")
    parser.add_argument("--matrix", action="store_true", help="matrixモードで送る")
    parser.add_argument("--width", type=int, default=int(os.getenv("MATRIX_WIDTH", "16")))
    parser.add_argument("--height", type=int, default=int(os.getenv("MATRIX_HEIGHT", "16")))
    args = parser.parse_args()

    url = "ws://localhost:8765" if args.local else args.url
    if not url:
        print("[error] 接続先が不明です。--url を指定するか "
              ".env に COLORHUB_WS_URL を設定してください。", file=sys.stderr)
        return 1

    def make(specs: list[str]) -> dict:
        if args.matrix:
            return build_matrix(specs, args.source, args.width, args.height)
        return build_palette(specs, args.source)

    if args.off:
        payloads = [make(["black"])]
        repeat = 0.0
    elif args.cycle:
        payloads = [make([c]) for c in CYCLE_COLORS]
        repeat = args.interval
    elif args.colors:
        # 複数色は1つのペイロード（帯グラフ）としてまとめて送る
        payloads = [make(args.colors)]
        repeat = 0.0
    else:
        parser.print_help()
        return 1

    try:
        return asyncio.run(send(url, payloads, repeat))
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
