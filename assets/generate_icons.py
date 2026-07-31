"""Generate app icons for macOS (.icns) and Windows (.ico) from a PNG."""

from PIL import Image, ImageDraw


def create_base_icon(size: int = 512) -> Image.Image:
    """Create the base icon as a PNG."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle — dark slate
    margin = size // 16
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(45, 55, 72, 255),
        outline=(100, 116, 139, 255),
        width=size // 32,
    )

    # Microphone shape — white
    cx, cy = size // 2, size // 2
    mic_w = size // 6
    mic_h = size // 4
    # Mic body (rounded rect approximation)
    draw.ellipse(
        [cx - mic_w, cy - mic_h, cx + mic_w, cy + mic_w // 2],
        fill=(255, 255, 255, 255),
    )
    # Mic stand
    stand_w = size // 16
    draw.rectangle(
        [cx - stand_w, cy + mic_w // 2, cx + stand_w, cy + mic_h + size // 8],
        fill=(255, 255, 255, 255),
    )
    # Mic base
    base_w = size // 6
    base_h = size // 20
    draw.rounded_rectangle(
        [cx - base_w, cy + mic_h + size // 8, cx + base_w, cy + mic_h + size // 8 + base_h],
        radius=base_h // 2,
        fill=(255, 255, 255, 255),
    )

    return img


def save_icons():
    """Save icons in all needed formats."""
    icon = create_base_icon(512)

    # Save PNG
    icon.save("icon.png")
    print("saved icon.png")

    # Save ICO (Windows) — needs multiple sizes
    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_images = [icon.resize((s, s), Image.Resampling.LANCZOS) for s in ico_sizes]
    ico_images[0].save("icon.ico", format="ICO", sizes=[(s, s) for s in ico_sizes], append_images=ico_images[1:])
    print("saved icon.ico")

    # For macOS .icns — save a 512x512 PNG; use iconutil on macOS to convert
    icon.save("icon_512x512.png")
    print("saved icon_512x512.png (use iconutil to create .icns on macOS)")


if __name__ == "__main__":
    save_icons()
