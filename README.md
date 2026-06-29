# Image EXIF Border

Add a white bottom border to a photo and render key EXIF information such as
camera model, lens, aperture, focal length, shutter speed, ISO, and capture time.
If a camera brand icon exists in `icon/`, the brand is rendered on the left side
of the caption bar. If no matching icon is found, the brand is rendered as text.
The right side uses two same-sized text lines: camera/lens on the first line,
and exposure settings/capture time on the second line.

## Setup

### Install Miniconda

For Windows:

```
https://anaconda.com/api/installers/Miniconda3-latest-Windows-x86_64.exe
```

### Install Python Environment

```bash
conda create -n image python=3.12 -y
conda activate image
pip install -r requirements.txt
```

## Usage

```bash
python exif_border.py test.jpg
```

The default output is written next to the source image as `test_exif.jpg`.

Useful options:

```bash
python exif_border.py test.jpg -o output.jpg
python exif_border.py test.jpg --bar-ratio 0.16 --quality 92
python exif_border.py test.jpg --font /path/to/font.ttf
python exif_border.py test.jpg --icon-dir ./icon
```

Icon files are matched by file name after normalizing the EXIF `Make` value. For
example, `NIKON CORPORATION` matches `icon/nikon.jpg`. The camera model is
rendered from the EXIF `Model` value as-is.
