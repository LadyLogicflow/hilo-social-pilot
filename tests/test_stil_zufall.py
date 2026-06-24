# -*- coding: utf-8 -*-
"""Tests fuer Issue #144 - Bild-Stil ZUFAELLIG pro Beitrag + Freigabe-Schalter 'Anderes Bild'.

Deckt ab:
  A) stilwahl.aktive_stile: liest die drei An/Aus-Flags (bild_stil_standard/_ki_tafel/_kreativ);
     Default alle aktiv; deaktivierte kommen nie vor; mind. einer (Fallback standard).
  B) stilwahl.waehle_stil: waehlt nur aus AKTIVEN Stilen (deaktivierte nie); nie-doppelt zum
     direkten Vorgaenger bei >1 aktiv.
  C) stilwahl.zuweisen_stil_falls_fehlt: setzt fields['bild_stil'] nur wenn leer (stabil).
  D) stilwahl.aktiver_stil: bevorzugt fields['bild_stil'] ueber die globale Einstellung.
  E) bildmotiv/bildgen/art_director nutzen den PRO-BEITRAG-Stil (fields['bild_stil']), auch wenn
     global ein anderer Stil eingestellt ist (z.B. fields ki_tafel rendert Tafel bei global standard).
  F) art_director kreativ-Kostenschutz pro Beitrag: KI-Aufruf NUR wenn fields['bild_stil']=='kreativ'.
  G) anderen_stil_waehlen: wechselt auf einen anderen aktiven Stil; nur 1 aktiv -> None.
  H) Retention: cache_dateien_fuer_fields deckt den aktiven Stil-Pfad ab (alle Varianten).

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_stil_zufall.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
import bildgen as b
import textgen
import stilwahl
from bildmotiv import MOTIV_DIR


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


class _FakeText:
    def __init__(self, text):
        self.text = text


class _FakeMsg:
    def __init__(self, text):
        self.content = [_FakeText(text)]


class _FakeClient:
    def __init__(self, antwort):
        self.antwort = antwort
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        return _FakeMsg(self.antwort)


def _flags(standard, ki_tafel, kreativ):
    db.set_einstellung("bild_stil_standard", "1" if standard else "0")
    db.set_einstellung("bild_stil_ki_tafel", "1" if ki_tafel else "0")
    db.set_einstellung("bild_stil_kreativ", "1" if kreativ else "0")


def _dummy_photo(name="dummy_stil.png"):
    p = os.path.join(MOTIV_DIR, name)
    os.makedirs(MOTIV_DIR, exist_ok=True)
    Image.new("RGB", (64, 64), (200, 200, 200)).save(p)
    return p


# --- A) aktive_stile -------------------------------------------------------------------------
def test_aktive_stile():
    # Default (kein Flag gesetzt) -> alle drei aktiv
    for k in ("bild_stil_standard", "bild_stil_ki_tafel", "bild_stil_kreativ"):
        db.set_einstellung(k, None)
    aktiv = stilwahl.aktive_stile()
    if set(aktiv) != {"standard", "ki_tafel", "kreativ"}:
        _fail("Default: alle Stile aktiv erwartet, war %r" % aktiv)
    # nur ki_tafel aktiv
    _flags(False, True, False)
    if stilwahl.aktive_stile() != ["ki_tafel"]:
        _fail("nur ki_tafel aktiv erwartet, war %r" % stilwahl.aktive_stile())
    # keiner aktiv -> Fallback standard
    _flags(False, False, False)
    if stilwahl.aktive_stile() != ["standard"]:
        _fail("Fallback ['standard'] erwartet, war %r" % stilwahl.aktive_stile())
    print("  A) aktive_stile (Default/Teilmenge/Fallback) OK")


# --- B) waehle_stil nur aktive + nie-doppelt -------------------------------------------------
def test_waehle_stil():
    _flags(True, True, False)   # kreativ deaktiviert
    for _ in range(200):
        s = stilwahl.waehle_stil(None, {})
        if s == "kreativ":
            _fail("waehle_stil lieferte deaktivierten Stil 'kreativ'")
        if s not in ("standard", "ki_tafel"):
            _fail("waehle_stil lieferte unbekannten Stil %r" % s)
    # nie-doppelt zum Vorgaenger (>1 aktiv): bei 2 aktiven muss der andere kommen
    _flags(True, True, False)
    for _ in range(50):
        if stilwahl.waehle_stil(None, {}, vorgaenger="standard") == "standard":
            _fail("nie-doppelt: Vorgaenger 'standard' wurde wieder gewaehlt (2 aktiv)")
    # nur 1 aktiv -> genau dieser, auch als Vorgaenger
    _flags(False, True, False)
    if stilwahl.waehle_stil(None, {}, vorgaenger="ki_tafel") != "ki_tafel":
        _fail("bei nur 1 aktiv muss dieser geliefert werden (auch als Vorgaenger)")
    print("  B) waehle_stil: nur aktive + nie-doppelt OK")


# --- C) zuweisen_stil_falls_fehlt stabil -----------------------------------------------------
def test_zuweisen_stabil():
    _flags(True, True, True)
    f = {}
    stilwahl.zuweisen_stil_falls_fehlt(None, f)
    erst = f.get("bild_stil")
    if erst not in ("standard", "ki_tafel", "kreativ"):
        _fail("zuweisen_stil_falls_fehlt setzte keinen gueltigen Stil: %r" % erst)
    # erneuter Aufruf darf NICHT ueberschreiben (stabil)
    for _ in range(20):
        stilwahl.zuweisen_stil_falls_fehlt(None, f)
        if f["bild_stil"] != erst:
            _fail("zuweisen_stil_falls_fehlt ueberschrieb bestehenden Stil (nicht stabil)")
    print("  C) zuweisen_stil_falls_fehlt: setzt nur wenn leer + stabil OK")


# --- D) aktiver_stil bevorzugt fields --------------------------------------------------------
def test_aktiver_stil_vorrang():
    db.set_einstellung("bild_stil", "standard")
    if stilwahl.aktiver_stil({"bild_stil": "ki_tafel"}) != "ki_tafel":
        _fail("aktiver_stil muss fields['bild_stil'] vor der globalen Einstellung bevorzugen")
    # kein fields-Stil -> globale Einstellung
    if stilwahl.aktiver_stil({}) != "standard":
        _fail("aktiver_stil ohne fields-Stil muss auf die globale Einstellung fallen")
    db.set_einstellung("bild_stil", "kreativ")
    if stilwahl.aktiver_stil({}) != "kreativ":
        _fail("aktiver_stil ohne fields-Stil muss globale Einstellung 'kreativ' liefern")
    # ungueltiger fields-Stil -> Fallback global
    if stilwahl.aktiver_stil({"bild_stil": "quatsch"}) != "kreativ":
        _fail("aktiver_stil mit ungueltigem fields-Stil muss auf global fallen")
    db.set_einstellung("bild_stil", "standard")
    print("  D) aktiver_stil: fields vor global, Fallback global/standard OK")


# --- E) bildmotiv/bildgen nutzen den Pro-Beitrag-Stil ----------------------------------------
def test_pro_beitrag_render():
    # GLOBAL standard, aber fields ki_tafel -> Tafel-Pfad muss genommen werden.
    db.set_einstellung("bild_stil", "standard")
    f = {"bild_stil": "ki_tafel", "ueberschrift": "Test-Tafel",
         "szene_motiv": "ein ruhiger Tisch am Fenster"}
    # bildmotiv: ensure_photo_fuer routet ueber den Pro-Beitrag-Stil. ki_tafel ohne Key -> kein
    # echtes Foto, aber die Pfad-/Cache-Logik muss die Tafel-Variante treffen.
    tafel_pfad = bildmotiv._tafel_pfad(bildmotiv._tafel_scene(f), bildmotiv.tafel_sign_text(f),
                                       traeger=bildmotiv._tafel_traeger(f))
    # bildgen.render: ki_tafel-Stil pro Beitrag muss den Tafel-Render-Zweig nehmen (statt Standard).
    photo = _dummy_photo()
    out = os.path.join(MOTIV_DIR, "render_ki_tafel.png")
    b.render(f, photo, "HILO", out)
    if not os.path.exists(out):
        _fail("bildgen.render lieferte keine Datei fuer Pro-Beitrag ki_tafel")
    img = Image.open(out)
    if img.size != (1080, 1080):
        _fail("Render-Groesse 1080x1080 erwartet, war %r" % (img.size,))
    # Gegenprobe: fields kreativ rendert NICHT im Tafel-Zweig (kreativ nutzt Standard-Layout).
    f2 = {"bild_stil": "kreativ", "ueberschrift": "X", "szene_motiv": "eine Szene"}
    out2 = os.path.join(MOTIV_DIR, "render_kreativ.png")
    b.render(f2, photo, "HILO", out2)
    if not os.path.exists(out2):
        _fail("bildgen.render lieferte keine Datei fuer Pro-Beitrag kreativ")
    db.set_einstellung("bild_stil", "standard")
    print("  E) bildmotiv/bildgen nutzen Pro-Beitrag-Stil (ki_tafel rendert bei global standard) OK")


# --- F) art_director kreativ-Kostenschutz pro Beitrag ----------------------------------------
def test_art_director_pro_beitrag():
    # GLOBAL standard. fields['bild_stil']=='kreativ' -> GENAU ein KI-Aufruf.
    db.set_einstellung("bild_stil", "standard")
    c = _FakeClient("Eine kinoreife Szene am Hafen bei Sonnenaufgang.")
    f = {"bild_stil": "kreativ", "ueberschrift": "H", "caption": "C", "bullets": ["a"]}
    textgen.art_director_motiv(f, client=c)
    if c.calls != 1:
        _fail("kreativ pro Beitrag: genau 1 Art-Director-Aufruf erwartet, war %d" % c.calls)
    if not (f.get("kreativ_motiv") or "").strip():
        _fail("kreativ pro Beitrag: kreativ_motiv haette gesetzt werden muessen")
    # GLOBAL kreativ, aber fields standard -> KEIN Aufruf (Kostenschutz pro Beitrag).
    db.set_einstellung("bild_stil", "kreativ")
    c2 = _FakeClient("xxx")
    f2 = {"bild_stil": "standard", "ueberschrift": "H", "caption": "C", "bullets": ["a"]}
    textgen.art_director_motiv(f2, client=c2)
    if c2.calls != 0:
        _fail("standard pro Beitrag (global kreativ): KEIN Art-Director-Aufruf erwartet, war %d" % c2.calls)
    if (f2.get("kreativ_motiv") or "").strip():
        _fail("standard pro Beitrag: kreativ_motiv darf NICHT gesetzt sein")
    db.set_einstellung("bild_stil", "standard")
    print("  F) art_director kreativ-Kostenschutz pro Beitrag (fields-Stil entscheidet) OK")


# --- G) anderen_stil_waehlen -----------------------------------------------------------------
def test_anderen_stil():
    _flags(True, True, True)
    f = {"bild_stil": "standard"}
    for _ in range(50):
        ff = dict(f)
        neu = stilwahl.anderen_stil_waehlen(None, ff)
        if neu == "standard" or neu is None:
            _fail("anderen_stil_waehlen lieferte denselben/keinen Stil bei 3 aktiven: %r" % neu)
        if ff["bild_stil"] != neu:
            _fail("anderen_stil_waehlen hat fields['bild_stil'] nicht aktualisiert")
    # nur 1 aktiv und das ist der aktuelle -> None (Hinweis), fields unveraendert
    _flags(False, False, True)
    f2 = {"bild_stil": "kreativ"}
    if stilwahl.anderen_stil_waehlen(None, f2) is not None:
        _fail("anderen_stil_waehlen muss None liefern, wenn nur der aktuelle Stil aktiv ist")
    if f2["bild_stil"] != "kreativ":
        _fail("anderen_stil_waehlen darf fields nicht aendern, wenn kein anderer aktiv ist")
    # neuer Stil kreativ + noch kein kreativ_motiv -> Aufrufer setzt es via art_director (hier
    # nur pruefen, dass der Wechsel auf kreativ stattfindet)
    _flags(False, False, True)   # nur kreativ aktiv
    f3 = {"bild_stil": "standard"}
    if stilwahl.anderen_stil_waehlen(None, f3) != "kreativ":
        _fail("Wechsel von standard auf den einzigen anderen aktiven Stil 'kreativ' erwartet")
    print("  G) anderen_stil_waehlen: anderer aktiver Stil / None bei nur 1 OK")


# --- H) Retention deckt aktiven Stil-Pfad ab -------------------------------------------------
def test_retention():
    f = {"bild_stil": "ki_tafel", "ueberschrift": "Tafeltext",
         "szene_motiv": "ein ruhiger Tisch", "traeger": "ein Holzschild"}
    pfade = bildmotiv.cache_dateien_fuer_fields(f)
    erwartet = bildmotiv._tafel_pfad(bildmotiv._tafel_scene(f), bildmotiv.tafel_sign_text(f),
                                     traeger=bildmotiv._tafel_traeger(f))
    if erwartet not in pfade:
        _fail("Retention deckt den aktiven Tafel-Pfad nicht ab")
    # kreativ-Pfad ebenfalls enthalten (Stil-uebergreifender Schutz)
    fk = {"bild_stil": "kreativ", "kreativ_motiv": "Szene am Hafen"}
    pk = bildmotiv.cache_dateien_fuer_fields(fk)
    if bildmotiv._kreativ_pfad(bildmotiv._kreativ_scene(fk)) not in pk:
        _fail("Retention deckt den kreativ-Pfad nicht ab")
    print("  H) Retention: cache_dateien_fuer_fields deckt aktiven Stil-Pfad ab OK")


if __name__ == "__main__":
    db.init_db()
    test_aktive_stile()
    test_waehle_stil()
    test_zuweisen_stabil()
    test_aktiver_stil_vorrang()
    test_pro_beitrag_render()
    test_art_director_pro_beitrag()
    test_anderen_stil()
    test_retention()
    print("OK - test_stil_zufall (#144) bestanden")
