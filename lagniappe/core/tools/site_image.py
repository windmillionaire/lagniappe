import io

from PIL import Image, ImageDraw, ImageFilter

from lagniappe import CONFIG

from .. import exceptions
from ..definitions import (
    FileConsumer,
    FileConsumerLimitError,
    enforce_file_consumer,
)
from ..tools import database


# @testable false
# @covered-by lagniappe/core/tools/site_image.py::create_site_image
# @reason background removal is part of the site image admin workflow gap
def flood_fill_background(image, tolerance=30):
    """
    Background removal using flood fill from corners.

    Args:
        image: PIL Image object
        tolerance: Tolerance for flood fill

    Returns:
        PIL Image with background removed
    """
    # Convert to RGBA if needed
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    width, height = image.size
    result = image.copy()

    # Get corner positions
    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]

    for corner_x, corner_y in corners:
        corner_color = image.getpixel((corner_x, corner_y))

        # Skip if corner is already transparent
        if len(corner_color) == 4 and corner_color[3] == 0:
            continue

        # Use ImageDraw for flood fill
        ImageDraw.floodfill(
            result, (corner_x, corner_y), (0, 0, 0, 0), thresh=tolerance
        )

    return result


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @tests tests_unit/test_018_database_assets.py::test_site_image_rejects_oversized_input_before_decode
# @features admin
# @dimensions site-image-upload generated-images metadata
def create_site_image(image, remove_bg=True, bg_tolerance=30):
    """
    Save site image with optional background removal.
    Uploads to the public bucket and stores paths in datastore.
    Static files are served from lagniappe/web/static/images/ (via nginx/app.yaml).

    Args:
        image: Uploaded image file
        remove_bg: Whether to attempt background removal
        bg_tolerance: Tolerance for background detection (0-255)

    Returns:
        Dict mapping filename to path (e.g. {"favicon.ico": "favicon.ico", ...})
    """
    try:
        enforce_file_consumer(
            image,
            FileConsumer.SITE_IMAGE,
            filename=getattr(image, "filename", None),
        )
    except FileConsumerLimitError as error:
        raise exceptions.SiteImageError(str(error)) from error

    try:
        image.stream.seek(0)
        source_image = Image.open(image.stream)
    except Exception as e:
        context = {
            "image_processing": {
                "operation": "open_image",
                "filename": getattr(image, "filename", "unknown"),
                "has_stream": hasattr(image, "stream"),
            },
        }
        exceptions.capture(e, context)
        raise exceptions.SiteImageError(f"Invalid image file: {str(e)}")

    if source_image.mode != "RGBA":
        try:
            source_image = source_image.convert("RGBA")
        except Exception as e:
            context = {
                "image_processing": {
                    "operation": "convert_to_rgba",
                    "original_mode": source_image.mode,
                    "filename": getattr(image, "filename", "unknown"),
                },
            }
            exceptions.capture(e, context)
            raise exceptions.SiteImageError(f"Failed to convert image: {str(e)}")

    pixels = list(source_image.getdata())
    transparent_count = sum(1 for p in pixels if len(p) == 4 and p[3] < 255)
    total_pixels = len(pixels)
    transparency_percent = (transparent_count / total_pixels) * 100

    if transparency_percent == 0 and remove_bg:
        try:
            source_image = flood_fill_background(source_image, bg_tolerance)
        except Exception as e:
            context = {
                "image_processing": {
                    "operation": "background_removal",
                    "bg_tolerance": bg_tolerance,
                    "filename": getattr(image, "filename", "unknown"),
                },
            }
            exceptions.capture(e, context)

    image_paths = {}
    try:
        generated_images = generate_site_images(source_image)
        for filename, image_bytes in generated_images.items():
            path = database.upload_site_image(filename, image_bytes)
            image_paths[filename] = path
        database.save_site_image(image_paths)
    except Exception as e:
        context = {
            "image_processing": {
                "operation": "generate_and_upload",
                "filename": getattr(image, "filename", "unknown"),
                "generated_count": (
                    len(generated_images) if "generated_images" in locals() else 0
                ),
            },
        }
        exceptions.capture(e, context)
        raise exceptions.SiteImageError(f"Error during image generation: {str(e)}")

    return image_paths


# @testable false
# @covered-by lagniappe/core/tools/site_image.py::generate_site_images
# @reason source image validation is part of generated site image output
def validate_source_image(image):
    """
    Validate if the source image is suitable for favicon/icon generation.

    Args:
        image: PIL Image object

    Returns:
        Tuple of (is_valid, message)
    """
    width, height = image.size

    # Check minimum size
    if width < 192 or height < 192:
        return (
            False,
            f"Image too small ({width}x{height}). Minimum size is 192x192 pixels.",
        )

    # Check if image is square or close to square
    aspect_ratio = width / height
    if not (0.8 <= aspect_ratio <= 1.25):
        return (
            False,
            f"Image aspect ratio ({aspect_ratio:.2f}) should be close to square (1:1).",
        )

    # Check image mode
    if image.mode not in ["RGB", "RGBA", "L", "P"]:
        return False, f"Unsupported image mode: {image.mode}. Use RGB, RGBA, L, or P."

    return True, "Image is suitable for favicon generation."


# @testable false
# @covered-by lagniappe/core/tools/site_image.py::generate_site_images
# @reason maskable icon shaping is part of generated site image output
def create_maskable_icon(image, size, padding_percent=20):
    """
    Create a maskable icon by adding padding and ensuring the icon fits within the safe area.
    Preserves transparency from the source image.

    Args:
        image: Source image
        size: Target size
        padding_percent: Percentage of padding to add around the image

    Returns:
        Maskable icon as PIL Image with transparency preserved
    """
    # Calculate the safe area (icon should fit within 80% of the total area for maskable icons)
    safe_size = int(size * (100 - padding_percent) / 100)

    # Create new image with transparent background
    maskable = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Ensure source image has transparency support
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    # Resize the source image to fit in the safe area
    resized = image.copy()
    resized.thumbnail((safe_size, safe_size), Image.Resampling.LANCZOS)

    # Center the image
    x_offset = (size - resized.width) // 2
    y_offset = (size - resized.height) // 2

    # Paste with transparency preserved
    maskable.paste(resized, (x_offset, y_offset), resized)

    return maskable


# @testable false
# @covered-by lagniappe/core/tools/site_image.py::generate_site_images
# @reason image resizing is part of generated site image output
def resize_image_smooth(image, size):
    """
    Resize image with high quality resampling and sharpening while preserving transparency.

    Args:
        image: Source image
        size: Target size as (width, height)

    Returns:
        Resized image with transparency preserved
    """
    # Ensure we have RGBA for transparency support
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    # Use high-quality resampling
    resized = image.resize(size, Image.Resampling.LANCZOS)

    # Apply slight sharpening for small sizes (but preserve transparency)
    if size[0] <= 64:
        # Only sharpen the RGB channels, preserve alpha
        rgb_data = resized.convert("RGB")
        alpha_data = resized.split()[-1]  # Extract alpha channel

        sharpened_rgb = rgb_data.filter(
            ImageFilter.UnsharpMask(radius=0.5, percent=150, threshold=2)
        )

        # Recombine with original alpha
        resized = Image.merge("RGBA", (*sharpened_rgb.split(), alpha_data))

    return resized


# @testable false
# @covered-by lagniappe/core/tools/site_image.py::generate_site_images
# @reason ICO assembly is part of generated site image output
def create_ico_file(image):
    """
    Create a multi-size ICO file containing 16x16, 32x32, and 48x48 versions.
    Preserves transparency from the source image.

    Args:
        image: Source image

    Returns:
        ICO file data as bytes
    """
    sizes = [16, 32, 48]
    ico_images = []

    for size in sizes:
        resized = resize_image_smooth(image, (size, size))
        # Keep RGBA format to preserve transparency in ICO
        ico_images.append(resized)

    # Save to bytes buffer
    ico_buffer = io.BytesIO()
    ico_images[0].save(
        ico_buffer, format="ICO", sizes=[(img.width, img.height) for img in ico_images]
    )
    return ico_buffer.getvalue()


# @testable false
# @covered-by lagniappe/core/tools/site_image.py::generate_site_images
# @reason splash image composition is part of generated site image output
def create_splash_screen(
    source_image, app_name, size=(1242, 2688), theme_color="#4f46e5"
):
    """
    Create a splash screen with the app logo and name.

    Args:
        source_image: PIL Image object (logo)
        app_name: App name to display
        size: Target size (width, height)
        theme_color: Background color

    Returns:
        PIL Image object
    """
    from PIL import ImageFont
    import textwrap

    width, height = size

    # Create canvas with theme color
    splash = Image.new("RGB", (width, height), color=theme_color)
    draw = ImageDraw.Draw(splash)

    # Prepare logo
    if source_image.mode != "RGBA":
        source_image = source_image.convert("RGBA")

    # Logo sizing - roughly 1/6 of screen width
    logo_size = width // 6
    logo_resized = source_image.copy()
    logo_resized.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)

    # Position logo in upper center
    logo_x = (width - logo_resized.width) // 2
    logo_y = (height - logo_resized.height) // 2 - height // 8

    # Create a white background circle for logo if it has transparency
    circle_radius = logo_size // 2 + 20
    circle_x = logo_x + logo_resized.width // 2
    circle_y = logo_y + logo_resized.height // 2

    draw.ellipse(
        [
            circle_x - circle_radius,
            circle_y - circle_radius,
            circle_x + circle_radius,
            circle_y + circle_radius,
        ],
        fill="white",
    )

    # Paste logo (with transparency if available)
    if source_image.mode == "RGBA":
        splash.paste(logo_resized, (logo_x, logo_y), logo_resized)
    else:
        splash.paste(logo_resized, (logo_x, logo_y))

    # Add app name below logo
    try:
        # Try to use a nice font, fall back to default
        font_size = width // 20  # Responsive font size
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except OSError:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
            )
        except OSError:
            font = ImageFont.load_default()

    # Wrap text if needed
    wrapped_lines = textwrap.wrap(app_name, width=20)

    line_height = font_size + 10

    # Position text below logo
    text_y = logo_y + logo_resized.height + 50

    for i, line in enumerate(wrapped_lines):
        # Get text dimensions
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]

        # Center horizontally
        text_x = (width - text_width) // 2
        line_y = text_y + (i * line_height)

        # Draw text with slight shadow for better readability
        draw.text((text_x + 2, line_y + 2), line, fill=(0, 0, 0), font=font)
        draw.text((text_x, line_y), line, fill="white", font=font)

    return splash


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @features admin
# @dimensions generated-images
def generate_site_images(source_image):
    """
    Generate all necessary favicon, icon, and splash screen files from a source image.
    Preserves transparency in all formats except ICO (which doesn't support it well).

    Args:
        source_image: PIL Image object (should be at least 192x192)

    Returns:
        Dictionary mapping filename to image data (bytes)

    Raises:
        ValueError: If the source image is not suitable
    """
    # Validate the source image
    is_valid, message = validate_source_image(source_image)
    if not is_valid:
        raise ValueError(f"Invalid source image: {message}")

    generated_images = {}

    # Ensure we're working with RGBA to preserve any transparency
    if source_image.mode != "RGBA":
        source_image = source_image.convert("RGBA")

    # Standard favicon sizes (PNG format preserves transparency)
    favicon_sizes = {
        "favicon-16x16.png": (16, 16),
        "favicon-32x32.png": (32, 32),
    }

    # Generate standard favicons with transparency preserved
    for filename, size in favicon_sizes.items():
        resized = resize_image_smooth(source_image, size)
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG", optimize=True)
        generated_images[filename] = buffer.getvalue()

    # Generate ICO file (multi-size) - preserves transparency
    generated_images["favicon.ico"] = create_ico_file(source_image)

    # Apple Touch Icon (180x180) - preserves transparency
    apple_icon = resize_image_smooth(source_image, (180, 180))
    buffer = io.BytesIO()
    apple_icon.save(buffer, format="PNG", optimize=True)
    generated_images["apple-touch-icon.png"] = buffer.getvalue()

    # PWA manifest icons (all preserve transparency)
    # 192x192 - standard icon
    icon_192 = resize_image_smooth(source_image, (192, 192))
    buffer = io.BytesIO()
    icon_192.save(buffer, format="PNG", optimize=True)
    generated_images["logo-192x192.png"] = buffer.getvalue()

    # 512x512 - maskable icon for PWA
    maskable_512 = create_maskable_icon(source_image, 512)
    buffer = io.BytesIO()
    maskable_512.save(buffer, format="PNG", optimize=True)
    generated_images["logo-512x512.png"] = buffer.getvalue()

    # Additional useful sizes (all preserve transparency)
    # 144x144 - Windows tile
    icon_144 = resize_image_smooth(source_image, (144, 144))
    buffer = io.BytesIO()
    icon_144.save(buffer, format="PNG", optimize=True)
    generated_images["logo-144x144.png"] = buffer.getvalue()

    # 72x72 - older Android devices
    icon_72 = resize_image_smooth(source_image, (72, 72))
    buffer = io.BytesIO()
    icon_72.save(buffer, format="PNG", optimize=True)
    generated_images["logo-72x72.png"] = buffer.getvalue()

    # 96x96 - Android home screen
    icon_96 = resize_image_smooth(source_image, (96, 96))
    buffer = io.BytesIO()
    icon_96.save(buffer, format="PNG", optimize=True)
    generated_images["logo-96x96.png"] = buffer.getvalue()

    # Generate splash screens for different iOS devices
    app_name = getattr(CONFIG, "APP_NAME", None) or "Lagniappe"
    theme_color = getattr(CONFIG, "THEME_COLOR", None) or "#4f46e5"

    splash_sizes = {
        # iPhone 12 Pro Max
        "splash-1242x2688.png": (1242, 2688),
        # iPhone 12 Pro
        "splash-1170x2532.png": (1170, 2532),
        # iPhone 11 Pro Max
        "splash-1242x2208.png": (1242, 2208),
        # iPhone 11 Pro
        "splash-1125x2436.png": (1125, 2436),
        # iPhone XR / 11
        "splash-828x1792.png": (828, 1792),
        # iPad Pro 12.9"
        "splash-2048x2732.png": (2048, 2732),
        # iPad Pro 11"
        "splash-1668x2388.png": (1668, 2388),
        # Standard iPad
        "splash-1536x2048.png": (1536, 2048),
    }

    for filename, size in splash_sizes.items():
        splash = create_splash_screen(source_image, app_name, size, theme_color)
        buffer = io.BytesIO()
        splash.save(buffer, format="PNG", optimize=True)
        generated_images[filename] = buffer.getvalue()

    return generated_images
