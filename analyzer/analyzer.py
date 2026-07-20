import cv2
import numpy as np
from sklearn.cluster import KMeans
from utils import rgb_to_hsl, rgb_to_hex


def extract_colors(frame_bytes: bytes, n_colors: int = 5) -> dict:
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image")

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pixels = img_rgb.reshape(-1, 3).astype(np.float32)

    # サンプリングして速度を上げる
    if len(pixels) > 10000:
        idx = np.random.choice(len(pixels), 10000, replace=False)
        pixels = pixels[idx]

    kmeans = KMeans(n_clusters=n_colors, n_init=3, max_iter=100, random_state=42)
    kmeans.fit(pixels)

    centers = kmeans.cluster_centers_.astype(int)
    labels = kmeans.labels_
    counts = np.bincount(labels, minlength=n_colors)
    total = counts.sum()

    colors = []
    for i in np.argsort(counts)[::-1]:
        r, g, b = int(centers[i][0]), int(centers[i][1]), int(centers[i][2])
        pct = round(float(counts[i]) / total * 100, 2)
        colors.append({
            "hex": rgb_to_hex(r, g, b),
            "rgb": [r, g, b],
            "hsl": rgb_to_hsl(r, g, b),
            "percentage": pct,
        })

    return {
        "colors": colors,
        "dominant": colors[0]["hex"] if colors else "#000000",
    }


def _center_crop_to_aspect(img_rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """グリッドの縦横比(width:height)に合わせて中央をクロップする。

    映像とLEDグリッドの比率が違うと resize が像を引き伸ばして歪むため、
    先に中央を切り出して比率を揃える（端は少し切れるが形は保たれる）。
    """
    h, w = img_rgb.shape[:2]
    target = width / height
    current = w / h
    if abs(current - target) < 1e-6:
        return img_rgb
    if current > target:
        # 横に広すぎる → 左右を削る
        new_w = int(round(h * target))
        x0 = (w - new_w) // 2
        return img_rgb[:, x0:x0 + new_w]
    # 縦に高すぎる → 上下を削る
    new_h = int(round(w / target))
    y0 = (h - new_h) // 2
    return img_rgb[y0:y0 + new_h, :]


def extract_matrix(
    frame_bytes: bytes,
    width: int = 16,
    height: int = 16,
    crop: bool = True,
) -> dict:
    """映像を width×height の低解像度グリッドに落とし、各マスの平均色を返す。

    出力は「画面そのままの向き」= 左上原点・行優先(row-major)。
    行0 = 画面最上段、各行は左→右。物理的な配線（蛇行・スタート角など）の
    変換は firmware 側に任せ、ここではハードウェア非依存の論理グリッドだけを返す。

    pixels[i] は (row, col) = (i // width, i % width) のマスの [r, g, b]。
    """
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image")

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if crop:
        img_rgb = _center_crop_to_aspect(img_rgb, width, height)

    # INTER_AREA = 縮小時にブロック内の平均色を取る補間方式
    small = cv2.resize(img_rgb, (width, height), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(int).tolist()

    return {
        "width": width,
        "height": height,
        "pixels": pixels,
    }
