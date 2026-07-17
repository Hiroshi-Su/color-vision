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
