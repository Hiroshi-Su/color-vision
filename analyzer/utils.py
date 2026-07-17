import colorsys


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_hsl(r: int, g: int, b: int) -> dict:
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {
        "h": round(h * 360),
        "s": round(s * 100),
        "l": round(l * 100),
    }
