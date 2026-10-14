"""
Cuts focused figures for the Jury 2 slides out of the full screenshots.

Run after docs/capture_screenshots_jury2.py:

    .venv\\Scripts\\python.exe presentation\\crop_figures.py

Coordinates are in pixels of the 2880 x 1720 screenshots.
"""

import os

from PIL import Image

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "assets", "jury2")

# name of new figure: (source screenshot, (left, top, right, bottom))
CROPS = {
    # Cards from the right-hand panel, cut from the sharp 2x screenshots.
    # The chat figures (chat_*.png) need no cutting: the capture script
    # already saves them at the right size.
    "fig_emotion_disagree.png": ("01_full_interface.png", (2120, 265, 2840, 752)),
    "fig_tone_concern.png":     ("02_concern.png",        (2120, 770, 2840, 1315)),
    "fig_crisis_panel.png":     ("04_crisis.png",         (2120, 265, 2840, 1152)),
    "fig_timeline.png":         ("04_crisis.png",         (2115, 1370, 2845, 1480)),
}


def main():
    for name, (source, box) in CROPS.items():
        image = Image.open(os.path.join(FOLDER, source))
        image.crop(box).save(os.path.join(FOLDER, name))
        print("saved", name, image.crop(box).size)


if __name__ == "__main__":
    main()
