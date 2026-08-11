# -*- coding: utf-8 -*-
"""Tests fuer #159 (Referenz-Anker) UND #160 (Comic-Strip Szenen-Vielfalt).

Beide gehoeren zusammen: der Referenz-Anker (REF_ANCHOR) haelt die FIGUR konstant, die Szenen-
Variation macht jedes Beitrags-Bild ANDERS. Alles gemockt - KEINE echten Bild-/KI-APIs.

#159 - Referenz-Anker (REF_ANCHOR steht im Prompt, WENN eine Referenz genutzt wird; NICHT sonst):
  A1) comic_strip: Panel MIT Referenz (Feld 2 = Finanzamt) -> Anker; Panel OHNE Referenz
      (Feld 1/3 ohne Berater-Ref -> generations-Weg) -> KEIN Anker.
  A2) comic (normal): _comic_prompt MIT aktiver Referenz + vorhandenem stil_ref -> Anker;
      mit HILO_COMIC_REFERENCE=0 (kein Referenz-Call) -> KEIN Anker.
  A3) comic_beratung: _comic_beratung_prompt MIT existierender Berater-Referenz -> Anker;
      ohne (None) -> KEIN Anker.

#160 - Szenen-Vielfalt pro Beitrag (nur comic_strip):
  B1) zwei Beitraege mit unterschiedlicher Ueberschrift -> unterschiedliche Szenen-Variation im
      Feld-2-Prompt (und Feld 1/3) -> unterschiedliche _comic_strip_pfad.
  B2) gleicher Beitrag -> stabile Variation -> gleicher _comic_strip_pfad.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/cav-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/manual_comic_ref_anchor_variety.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    print("  OK:", msg)


def _dummy_png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (32, 32), (180, 200, 160)).save(path)
    return path


# ============================ #159 - Referenz-Anker ============================================

def test_A1_comic_strip_anker():
    """comic_strip: Panel mit Referenz -> REF_ANCHOR; Panel ohne Referenz -> kein REF_ANCHOR.
    Trick: berater='' -> Feld 1/3 haben KEINE Referenz (generations-Weg, kein Anker), Feld 2 hat
    die Finanzamt-Referenz (Referenz-Call, MIT Anker). So sind beide Faelle in EINEM Lauf pruefbar."""
    db.set_einstellung("finanzamt_bibel_bild", None)   # -> _finanzamt_ref_pfad = FINANZAMT_REF_PATH
    ref_prompts = []      # Panels MIT Referenz (Feld 2)
    gen_prompts = []      # Panels OHNE Referenz (Feld 1/3)

    def _fake_ref(prompt, refs):
        ref_prompts.append(prompt)
        return b"PANELPNG"

    def _fake_gen(prompt, tool=None):
        gen_prompts.append(prompt)
        return b"GENPNG"

    orig_ref, orig_gen = bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_comic_bild_ref = _fake_ref
    bildmotiv.erzeuge_bild = _fake_gen
    try:
        fields = {"bild_stil": "comic_strip", "ueberschrift": "ANKER-STRIP-159-A"}
        panels = bildmotiv.ensure_comic_strip_bilder(fields, "")
    finally:
        bildmotiv.erzeuge_comic_bild_ref, bildmotiv.erzeuge_bild = orig_ref, orig_gen

    if len(panels) != 3:
        _fail("comic_strip lieferte nicht 3 Panels: %r" % panels)
    if len(ref_prompts) != 1:
        _fail("erwartete genau 1 Referenz-Panel (Feld 2/Finanzamt), war %d" % len(ref_prompts))
    if len(gen_prompts) != 2:
        _fail("erwartete genau 2 referenzlose Panels (Feld 1/3), war %d" % len(gen_prompts))
    # Panel MIT Referenz -> Anker vorhanden
    if bildmotiv.REF_ANCHOR not in ref_prompts[0]:
        _fail("REF_ANCHOR fehlt im Referenz-Panel-Prompt (Feld 2)")
    # Panels OHNE Referenz -> KEIN Anker
    for p in gen_prompts:
        if bildmotiv.REF_ANCHOR in p:
            _fail("REF_ANCHOR steht faelschlich in einem referenzlosen Panel-Prompt (Feld 1/3)")
    _ok("#159 comic_strip: Anker im Referenz-Panel (Feld 2), NICHT in referenzlosen Panels (Feld 1/3)")


def test_A2_comic_normal_anker():
    """comic (normal): _comic_prompt mit aktiver Referenz + stil_ref -> Anker; mit
    HILO_COMIC_REFERENCE=0 (kein Referenz-Call) -> kein Anker."""
    if not os.path.exists(bildmotiv.STIL_REF_PATH):
        _fail("stil_ref-Asset fehlt: %r" % bildmotiv.STIL_REF_PATH)
    fields = {"comic_brief": {"szene": "eine ruhige Szene am Kuechentisch", "finanzamt_figur": False}}

    prev = os.environ.get("HILO_COMIC_REFERENCE")
    try:
        # Referenz aktiv (Default) -> stil_ref liegt vor -> Anker
        os.environ.pop("HILO_COMIC_REFERENCE", None)
        p_mit = bildmotiv._comic_prompt(fields)
        if bildmotiv.REF_ANCHOR not in p_mit:
            _fail("REF_ANCHOR fehlt im comic-Prompt trotz aktiver Referenz + stil_ref")
        # Referenz deaktiviert -> kein Referenz-Call -> kein Anker
        os.environ["HILO_COMIC_REFERENCE"] = "0"
        p_ohne = bildmotiv._comic_prompt(fields)
        if bildmotiv.REF_ANCHOR in p_ohne:
            _fail("REF_ANCHOR steht faelschlich im comic-Prompt bei deaktivierter Referenz")
    finally:
        if prev is None:
            os.environ.pop("HILO_COMIC_REFERENCE", None)
        else:
            os.environ["HILO_COMIC_REFERENCE"] = prev
    _ok("#159 comic (normal): Anker nur bei aktiver Referenz (stil_ref), NICHT bei HILO_COMIC_REFERENCE=0")


def test_A3_comic_beratung_anker():
    """comic_beratung: _comic_beratung_prompt mit existierender Berater-Referenz -> Anker;
    ohne (None/leerer Pfad) -> kein Anker."""
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_159.png"))
    fields = {"bibel_text": ""}

    p_mit = bildmotiv._comic_beratung_prompt(fields, berater)
    if bildmotiv.REF_ANCHOR not in p_mit:
        _fail("REF_ANCHOR fehlt im comic_beratung-Prompt trotz vorhandener Berater-Referenz")
    p_ohne = bildmotiv._comic_beratung_prompt(fields, None)
    if bildmotiv.REF_ANCHOR in p_ohne:
        _fail("REF_ANCHOR steht faelschlich im comic_beratung-Prompt ohne Berater-Referenz")
    p_ohne2 = bildmotiv._comic_beratung_prompt(fields)   # Default-Argument
    if bildmotiv.REF_ANCHOR in p_ohne2:
        _fail("REF_ANCHOR steht faelschlich im comic_beratung-Prompt (Default ohne Referenz)")
    _ok("#159 comic_beratung: Anker nur mit vorhandener Berater-Referenz, NICHT ohne")


# ============================ #160 - Szenen-Vielfalt ==========================================

def test_B1_verschiedene_beitraege_verschiedene_szene():
    """Zwei Beitraege mit unterschiedlicher Ueberschrift -> unterschiedliche Szenen-Variation in
    Feld 2 (und Feld 1/3) -> unterschiedliche _comic_strip_pfad."""
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_160.png"))
    f1 = {"bild_stil": "comic_strip", "ueberschrift": "Kinderbetreuungskosten absetzen"}
    f2 = {"bild_stil": "comic_strip", "ueberschrift": "Homeoffice-Pauschale 2026"}

    # Feld 2 (jammer) Szenen-Variation muss sich unterscheiden
    s1 = bildmotiv._comic_strip_szene(f1, "jammer", "vorteil")
    s2 = bildmotiv._comic_strip_szene(f2, "jammer", "vorteil")
    if not s1 or not s2:
        _fail("Feld-2-Szenen-Variation leer: %r / %r" % (s1, s2))
    if s1 == s2:
        _fail("Feld-2-Szenen-Variation identisch fuer verschiedene Beitraege: %r" % s1)

    # -> unterschiedliche Panel-Prompts -> unterschiedliche Pfade (je Feld)
    for idx, quelle in ((0, "ueberschrift"), (1, "jammer"), (2, "pointe")):
        z1 = bildmotiv._comic_strip_zeile(f1, quelle, "vorteil")
        z2 = bildmotiv._comic_strip_zeile(f2, quelle, "vorteil")
        delta, _q = bildmotiv._comic_strip_panels("vorteil")[idx]
        refs1 = bildmotiv._comic_strip_refs(idx, berater)
        pr1 = bildmotiv._comic_strip_prompt(f1, delta, z1, hat_ref=bool(refs1),
                                            szene=bildmotiv._comic_strip_szene(f1, quelle, "vorteil"))
        pr2 = bildmotiv._comic_strip_prompt(f2, delta, z2, hat_ref=bool(refs1),
                                            szene=bildmotiv._comic_strip_szene(f2, quelle, "vorteil"))
        path1 = bildmotiv._comic_strip_pfad(idx, pr1, berater)
        path2 = bildmotiv._comic_strip_pfad(idx, pr2, berater)
        if idx == 1 and path1 == path2:
            _fail("Feld 2: gleicher Pfad trotz verschiedener Beitraege: %r" % path1)
    # Feld 2 Prompts muessen die (verschiedene) Szenen-Variation woertlich enthalten
    d2, _ = bildmotiv._comic_strip_panels("vorteil")[1]
    p1 = bildmotiv._comic_strip_prompt(f1, d2, "x", szene=s1)
    p2 = bildmotiv._comic_strip_prompt(f2, d2, "x", szene=s2)
    if s1 not in p1 or s2 not in p2:
        _fail("Szenen-Variation steht nicht im Feld-2-Prompt")
    _ok("#160 verschiedene Beitraege: unterschiedliche Feld-2-Szene -> unterschiedliche Panel-Pfade")


def test_B2_gleicher_beitrag_stabil():
    """Gleicher Beitrag -> stabile Szenen-Variation -> gleicher _comic_strip_pfad (reproduzierbar)."""
    berater = _dummy_png(os.path.join(bildmotiv.DATA_DIR, "berater", "comic_160b.png"))
    f = {"bild_stil": "comic_strip", "ueberschrift": "Handwerkerleistungen von der Steuer"}
    for idx, quelle in ((0, "ueberschrift"), (1, "jammer"), (2, "pointe")):
        s_a = bildmotiv._comic_strip_szene(f, quelle, "vorteil")
        s_b = bildmotiv._comic_strip_szene(f, quelle, "vorteil")
        if s_a != s_b:
            _fail("Szenen-Variation nicht stabil fuer denselben Beitrag: %r != %r" % (s_a, s_b))
        z = bildmotiv._comic_strip_zeile(f, quelle, "vorteil")
        delta, _q = bildmotiv._comic_strip_panels("vorteil")[idx]
        refs = bildmotiv._comic_strip_refs(idx, berater)
        pr_a = bildmotiv._comic_strip_prompt(f, delta, z, hat_ref=bool(refs), szene=s_a)
        pr_b = bildmotiv._comic_strip_prompt(f, delta, z, hat_ref=bool(refs), szene=s_b)
        if bildmotiv._comic_strip_pfad(idx, pr_a, berater) != bildmotiv._comic_strip_pfad(idx, pr_b, berater):
            _fail("Panel-Pfad nicht stabil fuer denselben Beitrag (Feld %d)" % (idx + 1))
    _ok("#160 gleicher Beitrag: stabile Szenen-Variation -> gleicher Panel-Pfad")


def test_B3_kennung_id_vorrang():
    """Beitrags-Kennung nutzt eine vorhandene ID mit Vorrang vor der Ueberschrift (stabil je Beitrag)."""
    f_id = {"id": 4711, "ueberschrift": "egal"}
    if bildmotiv._comic_strip_beitrag_kennung(f_id) != "4711":
        _fail("Beitrags-Kennung nutzt die ID nicht mit Vorrang: %r"
              % bildmotiv._comic_strip_beitrag_kennung(f_id))
    f_txt = {"ueberschrift": "Nur Ueberschrift"}
    if bildmotiv._comic_strip_beitrag_kennung(f_txt) != "Nur Ueberschrift":
        _fail("Beitrags-Kennung fiel nicht auf die Ueberschrift zurueck")
    _ok("#160 Beitrags-Kennung: ID hat Vorrang, sonst Ueberschrift")


if __name__ == "__main__":
    db.init_db()
    test_A1_comic_strip_anker()
    test_A2_comic_normal_anker()
    test_A3_comic_beratung_anker()
    test_B1_verschiedene_beitraege_verschiedene_szene()
    test_B2_gleicher_beitrag_stabil()
    test_B3_kennung_id_vorrang()
    print("\nALLE TESTS BESTANDEN (#159 Referenz-Anker + #160 Szenen-Vielfalt).")
