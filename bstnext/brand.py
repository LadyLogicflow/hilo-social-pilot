# -*- coding: utf-8 -*-
"""Markenprofil BSt Next (catrin 09.11.2026: Navy #001942, Lime #A3E635 nur als Akzent).

Eigenstaendig, kein Bezug zur HILO-Marke (hilo_brand_identity.json). Aenderungen an Farben nur
nach Entscheidung von catrin."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NAME = "BSt Next"
NAVY = (0, 25, 66)        # #001942
LIME = (163, 230, 53)     # #A3E635, nur Akzent
WHITE = (255, 255, 255)

FONT_HEADLINE = os.path.join(BASE_DIR, "fonts", "ArchivoBlack-Regular.ttf")
LOGO_MIT_CLAIM = os.path.join(BASE_DIR, "assets", "bstnext", "logo_transparent_mit_claim.png")
CLAIM = "digital. effizient. besser."

# Formate: (Breite, Hoehe)
FORMATE = {
    "quadrat": (1080, 1080),
    "hochformat": (1080, 1350),
    "story": (1080, 1920),
}

# Hashtags der Marke (Casty, 09.11.2026)
HASHTAGS = "#BStNext #Beratungsstelle #Digitalisierung #Lohnsteuerhilfe"
