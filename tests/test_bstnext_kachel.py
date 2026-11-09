# -*- coding: utf-8 -*-
"""Tests Kachel-Generator BSt Next: Format, Markenfarben, Fehlerfaelle, Determinismus."""
import hashlib

import pytest
from PIL import Image

from bstnext import brand, kachel

HEAD = ["Wir fangen nicht", "mit Software an.", "Wir fangen mit"]


def test_quadrat_hat_format_und_navy_hintergrund(tmp_path):
    p = kachel.render(HEAD, ["Ihren", "Terminen an."], str(tmp_path / "k.png"))
    im = Image.open(p).convert("RGB")
    assert im.size == (1080, 1080)
    assert im.getpixel((5, 5)) == brand.NAVY == (0, 25, 66)


def test_enthaelt_weiss_und_lime_aber_keine_hilo_farben(tmp_path):
    p = kachel.render(HEAD, ["Ihren", "Belegen an."], str(tmp_path / "k.png"))
    farben = {c for _, c in Image.open(p).convert("RGB").getcolors(maxcolors=1 << 20)}
    assert brand.WHITE in farben and brand.LIME in farben
    for hilo in [(30, 58, 95), (143, 188, 63), (74, 123, 167)]:   # #1e3a5f #8fbc3f #4a7ba7
        assert hilo not in farben


def test_logo_ist_weiss_nicht_dunkel(tmp_path):
    p = kachel.render(HEAD, ["Ihrer", "Sichtbarkeit an."], str(tmp_path / "k.png"))
    im = Image.open(p).convert("RGB")
    logo_zone = im.crop((90, 860, 540, 990))
    weiss = sum(1 for px in logo_zone.getdata() if px == brand.WHITE)
    assert weiss > 500          # 'BSt' ist weiss, nicht dunkelblau auf Navy


def test_deterministisch(tmp_path):
    a = kachel.render(HEAD, ["Ihren", "Telefonaten an."], str(tmp_path / "a.png"))
    b = kachel.render(HEAD, ["Ihren", "Telefonaten an."], str(tmp_path / "b.png"))
    h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert h(a) == h(b)


def test_hochformat_und_story(tmp_path):
    assert Image.open(kachel.render(HEAD, ["Ihren", "Terminen an."], str(tmp_path / "h.png"), "hochformat")).size == (1080, 1350)
    assert Image.open(kachel.render(HEAD, ["Ihren", "Terminen an."], str(tmp_path / "s.png"), "story")).size == (1080, 1920)


def test_zu_breite_zeile_wird_abgelehnt(tmp_path):
    with pytest.raises(kachel.KachelFehler):
        kachel.render(["Das ist eine viel zu lange Headline Zeile"], [], str(tmp_path / "x.png"))


def test_ohne_headline_wird_abgelehnt(tmp_path):
    with pytest.raises(kachel.KachelFehler):
        kachel.render([], ["Ihren Terminen an."], str(tmp_path / "x.png"))


def test_unbekanntes_format(tmp_path):
    with pytest.raises(kachel.KachelFehler):
        kachel.render(HEAD, [], str(tmp_path / "x.png"), "kino")


def test_zu_viele_zeilen_im_quadrat(tmp_path):
    with pytest.raises(kachel.KachelFehler):
        kachel.render(["Eins", "Zwei", "Drei", "Vier", "Fuenf", "Sechs"], ["Sieben"], str(tmp_path / "x.png"))
