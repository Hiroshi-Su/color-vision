"""matrixモードのローカルプレビュー（開発用ツール）

カメラ映像を実際の extract_matrix() で width×height に落とし、その結果を
拡大してウィンドウ表示する。ESP32/LEDパネルが無くても、
「カメラ映像 → matrix変換」の見た目（各マスの平均色・向き）を確認できる。

上段=元のカメラ映像 / 下段=matrix化した低解像度グリッド（左上原点・行優先）。

使い方:
    cd analyzer
    venv/bin/python matrix_preview.py           # .env の MATRIX_WIDTH/HEIGHT を使用
    venv/bin/python matrix_preview.py 32 18      # 横32×縦18 に上書き
    CAM_INDEX=1 venv/bin/python matrix_preview.py # 別のカメラを使う

ウィンドウ上で q キーを押すと終了。

※これは動作確認用のスタンドアロンツール。firmware の配線変換(xyToIndex)は
  含まない（それは実機側の処理で、別途 全単射を検証済み）。
"""

import os
import sys

import cv2
import numpy as np
from dotenv import load_dotenv

from analyzer import extract_matrix

load_dotenv()

W = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("MATRIX_WIDTH", "16"))
H = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.getenv("MATRIX_HEIGHT", "16"))
CELL = 28  # プレビュー上での1マスの表示ピクセル数
CAM_INDEX = int(os.getenv("CAM_INDEX", "0"))


def main() -> int:
    cap = cv2.VideoCapture(CAM_INDEX)
    if not cap.isOpened():
        print(f"カメラ(index={CAM_INDEX})を開けませんでした。")
        print("・他アプリがカメラを使用中でないか")
        print("・ターミナルにカメラ権限が付与されているか（システム設定 > プライバシー > カメラ）")
        print("・別カメラは CAM_INDEX=1 で指定")
        return 1

    print(f"matrix preview: {W}x{H} = {W * H} マス  (ウィンドウで q を押すと終了)")
    win = f"Color Vision - matrix {W}x{H} (top=camera / bottom=matrix, left-top origin)"

    while True:
        ok, frame = cap.read()
        if not ok:
            print("フレーム取得に失敗しました。")
            break

        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            continue

        # ← 実際の解析コード。センタークロップ + INTER_AREA(平均色) が効く
        m = extract_matrix(buf.tobytes(), W, H)

        # pixels は左上原点・行優先の [r,g,b]。そのまま H×W×3 に復元
        grid = np.array(m["pixels"], dtype=np.uint8).reshape(H, W, 3)

        # 表示用に拡大（INTER_NEAREST=マスの境界をくっきり）→ RGB を BGR に
        big = cv2.resize(grid, (W * CELL, H * CELL), interpolation=cv2.INTER_NEAREST)
        big = cv2.cvtColor(big, cv2.COLOR_RGB2BGR)

        # 上に元映像を同じ幅で並べる（変換前後の対応が見えるように）
        cam_w = W * CELL
        cam_h = int(cam_w * frame.shape[0] / frame.shape[1])
        cam = cv2.resize(frame, (cam_w, cam_h))
        combo = np.vstack([cam, big])

        cv2.imshow(win, combo)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
