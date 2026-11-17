"""Génère doc/logo.png (liste des apps YunoHost) : un serveur en rack et une cloche d'alerte.

Outil de développement uniquement (Pillow) : `pip install pillow && python tools/make_logo.py`.
"""

import os

from PIL import Image, ImageDraw

SIZE = 512  # taille finale
SS = 4  # sur-échantillonnage pour l'anticrénelage
RED = (213, 12, 45)  # rouge proche de celui de Hetzner, sans reprendre son logo
WHITE = (255, 255, 255)

# Géométrie dans une grille de 32, mise à l'échelle ensuite
TILE = (1, 1, 31, 31)
TILE_RADIUS = 7
RACK = [(6, 8, 20, 13), (6, 15, 20, 20), (6, 22, 20, 27)]  # trois unités de serveur
RACK_RADIUS = 1.5
LED_X = 17.5
BELL_CENTER = (24.5, 11)


def main(out):
    k = SIZE * SS / 32.0
    img = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(b):
        return [round(v * k) for v in b]

    d.rounded_rectangle(box(TILE), radius=round(TILE_RADIUS * k), fill=RED)
    for x0, y0, x1, y1 in RACK:
        d.rounded_rectangle(box((x0, y0, x1, y1)), radius=round(RACK_RADIUS * k), fill=WHITE)
        cy = (y0 + y1) / 2
        d.ellipse(box((LED_X - 1, cy - 1, LED_X + 1, cy + 1)), fill=RED)
        d.rectangle(box((x0 + 1.8, cy - 0.5, x0 + 7, cy + 0.5)), fill=RED)

    # cloche : dôme, base, battant
    cx, cy = BELL_CENTER
    d.pieslice(box((cx - 4, cy - 4.5, cx + 4, cy + 3.5)), 180, 360, fill=WHITE)
    d.rectangle(box((cx - 4, cy - 0.6, cx + 4, cy + 2.4)), fill=WHITE)
    d.rounded_rectangle(box((cx - 5.2, cy + 2.2, cx + 5.2, cy + 3.6)), radius=round(0.7 * k), fill=WHITE)
    d.ellipse(box((cx - 1.3, cy + 3.6, cx + 1.3, cy + 6.2)), fill=WHITE)
    d.ellipse(box((cx - 0.9, cy - 6, cx + 0.9, cy - 4.2)), fill=WHITE)

    img.resize((SIZE, SIZE), Image.LANCZOS).save(out, optimize=True)
    print("écrit :", out)


if __name__ == "__main__":
    main(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "doc", "logo.png"))
