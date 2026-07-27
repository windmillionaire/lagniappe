# Test Files

`editor_test_image.jpeg` is a 96×64 JPEG made specifically for this repository
from simple geometric shapes. It contains no third-party artwork or embedded
metadata and is covered by the repository license.

`site_image_test_image.jpeg` uses the same repository-owned design at 192×192,
the minimum dimensions accepted by the site-image generator.

The fixtures can be regenerated with:

```bash
magick -size 96x64 xc:'#f4efe6' -fill '#476b8a' \
  -draw 'rectangle 0,0 47,63' -fill '#d8a24a' \
  -draw 'circle 71,32 71,12' -strip -quality 82 \
  testing/files/editor_test_image.jpeg

magick -size 192x192 xc:'#f4efe6' -fill '#476b8a' \
  -draw 'rectangle 0,0 95,191' -fill '#d8a24a' \
  -draw 'circle 143,96 143,36' -strip -quality 82 \
  testing/files/site_image_test_image.jpeg
```
