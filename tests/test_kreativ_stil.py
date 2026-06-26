# -*- coding: utf-8 -*-
"""Tests fuer Issue #143 - dritter, umschaltbarer Bild-Stil 'kreativ': ein kinoreifes,
fotorealistisches Foto OHNE Text; Botschaft + HILO-CI kommen wie im Standard-Look per Code-Overlay.

Deckt ab:
  A) db.get/set_einstellung: 'kreativ' waehlbar/persistierbar; standard/ki_tafel unveraendert.
  B) textgen.art_director_motiv: erzeugt fields['kreativ_motiv'] NUR im kreativ-Modus
     (mockbarer Client, KEIN echter KI-Aufruf); stabil (nur-wenn-leer); robust (Fehler -> kein
     kreativ_motiv). Der Art-Director-Prompt enthaelt den exakten deutschen Wortlaut.
  C) bildmotiv: kreativ-Prompt enthaelt 'fotorealistisch/kinoreif' + Klischee-Verneinung
     (Taschenrechner/Ordner/Haendedruecke) + 'ABSOLUT KEIN Text' + die Szene; Payload
     background='opaque'/size '1024x1024'; eigener Cache-Praefix 'kreativ_'; verschiedene
     kreativ_motiv -> verschiedene Pfade; getrennt von szene/tafel. ensure_photo_fuer routet
     kreativ + None ohne Key. Retention: cache_dateien_fuer_fields enthaelt den kreativ-Pfad.
  D) bildgen: Modus kreativ rendert mit Standard-Layout (Text-Karte + CI-Kreise vorhanden,
     KEIN Tafel-Device) ueber Dummy-Foto, 1080x1080.
  E) E2E-Retention: aktiver Entwurf im kreativ-Modus, altes kreativ-Foto -> bleibt erhalten.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_kreativ_stil.py
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import db
import bildmotiv
import bildgen as b
import textgen
import wartung
from bildmotiv import MOTIV_DIR


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


# --- Mock-Anthropic-Client (KEIN echter KI-Aufruf) -------------------------------------------
class _FakeText:
    def __init__(self, text):
        self.text = text


class _FakeMsg:
    def __init__(self, text):
        self.content = [_FakeText(text)]


class _FakeClient:
    """Minimaler Stub mit messages.create(...) - liefert eine feste Bildszene zurueck und zaehlt
    die Aufrufe, damit Tests beweisen koennen, dass im kreativ-Modus GENAU ein Aufruf erfolgt und
    in anderen Stilen KEINER."""
    def __init__(self, antwort):
        self.antwort = antwort
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return _FakeMsg(self.antwort)


FIELDS = {
    "ueberschrift": "Abschiedsfeier steuerfrei - so geht's!",
    "subline": "Was Arbeitnehmer beachten muessen",
    "bullets": ["Bis 110 Euro je Person steuerfrei", "Betrieblicher Anlass noetig", "Belege aufbewahren"],
    "cta": "Jetzt Beratungsstelle in Ihrer Naehe finden",
    "caption": "Viele verschenken bares Geld - nur weil sie eine Frist verpassen.",
    "hero": "110 EUR",
    "szene_motiv": "Ein warmer Herbstmoment am Kuechentisch",
}
KREATIV_SZENE = ("Ein leerer Stuhl an einem festlich gedeckten Tisch, das Licht faellt warm "
                 "durchs Fenster, im Hintergrund unscharf eine froehliche Feier.")


# ---------------------------------------------------------------------------
# A) Einstellung get/set
# ---------------------------------------------------------------------------
def test_einstellung():
    db.init_db()
    if db.get_einstellung("bild_stil", "standard") != "standard":
        _fail("Default-Fallback fuer fehlenden Schluessel falsch")
    db.set_einstellung("bild_stil", "kreativ")
    if db.get_einstellung("bild_stil", "standard") != "kreativ":
        _fail("set/get_einstellung persistiert 'kreativ' nicht")
    # standard/ki_tafel weiter waehlbar (Rueckwaertskompatibilitaet)
    for s in ("standard", "ki_tafel"):
        db.set_einstellung("bild_stil", s)
        if db.get_einstellung("bild_stil") != s:
            _fail("Bild-Stil %r nicht persistiert" % s)
    db.set_einstellung("bild_stil", "standard")
    print("  A) get/set_einstellung: 'kreativ' waehlbar + standard/ki_tafel unveraendert OK")


# ---------------------------------------------------------------------------
# B) textgen Art-Director-Schritt
# ---------------------------------------------------------------------------
def test_art_director_prompt_wortlaut():
    p = textgen._art_director_prompt(FIELDS)
    for stueck in ("preisgekrönter Art Director", "überraschendste",
                   "fotorealistische", "kinoreif", "KEINE Stockfoto-Ästhetik",
                   "keine Taschenrechner", "keine Ordner", "keine Händedrücke",
                   "KEIN Text im Bild", "Gib NUR die konkrete Bildszene"):
        if stueck not in p:
            _fail("Art-Director-Prompt fehlt der Wortlaut %r" % stueck)
    # Beitragstext (Ueberschrift/Caption) fliesst ein, damit die KI die Erkenntnis findet
    if FIELDS["caption"] not in p or FIELDS["ueberschrift"] not in p:
        _fail("Art-Director-Prompt enthaelt den Beitragstext nicht")
    # echte deutsche Umlaute
    for ch in ("ä", "ö", "ü"):
        if ch not in p:
            _fail("Echter Umlaut %r fehlt im Art-Director-Prompt" % ch)
    print("  B1) Art-Director-Prompt: exakter deutscher Wortlaut + Beitragstext + Umlaute OK")


def test_art_director_nur_kreativ():
    db.set_einstellung("bild_stil", "standard")
    f = dict(FIELDS)
    client = _FakeClient(KREATIV_SZENE)
    textgen.art_director_motiv(f, client=client)
    if client.calls != 0:
        _fail("Art-Director-Schritt hat im STANDARD-Modus einen KI-Aufruf gemacht (%d)" % client.calls)
    if "kreativ_motiv" in f:
        _fail("Art-Director-Schritt hat im STANDARD-Modus ein kreativ_motiv gesetzt")
    db.set_einstellung("bild_stil", "ki_tafel")
    client2 = _FakeClient(KREATIV_SZENE)
    textgen.art_director_motiv(f, client=client2)
    if client2.calls != 0 or "kreativ_motiv" in f:
        _fail("Art-Director-Schritt darf im ki_tafel-Modus NICHT laufen")
    print("  B2) Art-Director-Schritt: KEIN KI-Aufruf in standard/ki_tafel OK")


def test_art_director_kreativ_setzt_motiv():
    db.set_einstellung("bild_stil", "kreativ")
    f = dict(FIELDS)
    f.pop("kreativ_motiv", None)
    client = _FakeClient(KREATIV_SZENE)
    textgen.art_director_motiv(f, client=client)
    if client.calls != 1:
        _fail("Kreativ-Modus haette GENAU 1 KI-Aufruf machen muessen, war %d" % client.calls)
    if (f.get("kreativ_motiv") or "").strip() != KREATIV_SZENE:
        _fail("kreativ_motiv wurde nicht aus der KI-Antwort gesetzt: %r" % f.get("kreativ_motiv"))
    # System/Prompt korrekt uebergeben (mockbar, ohne Netz geprueft)
    if "Art Director" not in client.last_kwargs.get("system", ""):
        _fail("Art-Director-System wurde nicht uebergeben")
    print("  B3) Art-Director-Schritt: kreativ-Modus erzeugt kreativ_motiv (1 KI-Aufruf) OK")


def test_art_director_stabil_nur_wenn_leer():
    db.set_einstellung("bild_stil", "kreativ")
    f = dict(FIELDS)
    f["kreativ_motiv"] = "BESTEHENDE SZENE die erhalten bleiben muss"
    client = _FakeClient(KREATIV_SZENE)
    textgen.art_director_motiv(f, client=client)
    if client.calls != 0:
        _fail("Bei bereits gesetztem kreativ_motiv darf KEIN neuer KI-Aufruf erfolgen (%d)" % client.calls)
    if f["kreativ_motiv"] != "BESTEHENDE SZENE die erhalten bleiben muss":
        _fail("Bestehendes kreativ_motiv wurde ueberschrieben (nicht stabil)")
    print("  B4) Art-Director-Schritt: stabil (nur-wenn-leer, kein Re-Render-Overwrite) OK")


def test_art_director_robust():
    db.set_einstellung("bild_stil", "kreativ")
    f = dict(FIELDS)
    f.pop("kreativ_motiv", None)

    class _BoomClient:
        def __init__(self):
            self.messages = self
        def create(self, **kwargs):
            raise RuntimeError("KI nicht erreichbar")

    # Fehler im KI-Aufruf -> kein Crash, kein kreativ_motiv (Fallback greift spaeter via _kreativ_scene)
    textgen.art_director_motiv(f, client=_BoomClient())
    if "kreativ_motiv" in f:
        _fail("Bei KI-Fehler darf kein kreativ_motiv gesetzt werden")
    # nicht-dict robust
    if textgen.art_director_motiv(None) is not None:
        _fail("art_director_motiv(None) sollte None liefern, nicht crashen")
    db.set_einstellung("bild_stil", "standard")
    print("  B5) Art-Director-Schritt: robust (Fehler -> kein kreativ_motiv, kein Crash) OK")


# ---------------------------------------------------------------------------
# C) bildmotiv kreativ-Prompt / Payload / Cache
# ---------------------------------------------------------------------------
def test_kreativ_prompt():
    p = bildmotiv._kreativ_prompt(KREATIV_SZENE)
    for stueck in ("Fotorealistisches", "KINOREIF", "keine Taschenrechner", "keine Ordner",
                   "keine Haendedruecke", "ABSOLUT KEIN Text"):
        if stueck not in p:
            _fail("Kreativ-Prompt fehlt %r" % stueck)
    if KREATIV_SZENE not in p:
        _fail("Kreativ-Prompt enthaelt die Szene nicht")
    print("  C1) Kreativ-Prompt: fotorealistisch/kinoreif + Klischee-Verneinung + 'KEIN Text' + Szene OK")


def test_kreativ_payload():
    pl = bildmotiv.kreativ_payload(KREATIV_SZENE)
    if pl.get("background") != "opaque":
        _fail("Kreativ-Payload background != 'opaque'")
    if pl.get("size") != "1024x1024":
        _fail("Kreativ-Payload size != '1024x1024'")
    if KREATIV_SZENE not in pl.get("prompt", ""):
        _fail("Kreativ-Payload-Prompt enthaelt die Szene nicht")
    print("  C2) Kreativ-Payload: background='opaque', size='1024x1024', Szene im Prompt OK")


def test_kreativ_cache_praefix():
    db.set_einstellung("bild_tool", "openai")
    p1 = bildmotiv._kreativ_pfad(KREATIV_SZENE)
    if "kreativ_" not in os.path.basename(p1):
        _fail("Kreativ-Cache-Pfad traegt nicht den Praefix 'kreativ_': %s" % p1)
    # verschiedene Szenen -> verschiedene Pfade
    p2 = bildmotiv._kreativ_pfad("eine voellig andere Szene mit anderem Inhalt")
    if p1 == p2:
        _fail("Verschiedene kreativ_motiv ergeben denselben Cache-Pfad")
    # getrennt von szene/tafel (eigener Praefix, kein Hash-Clash)
    sz = bildmotiv._szene_pfad(KREATIV_SZENE)
    tf = bildmotiv._tafel_pfad(KREATIV_SZENE, "X")
    if p1 == sz or p1 == tf:
        _fail("Kreativ-Pfad kollidiert mit szene/tafel-Pfad")
    # erwarteter Hash (Praefix 'kreativ:' im Schluessel)
    h = hashlib.sha256(("kreativ:" + KREATIV_SZENE).lower().encode("utf-8")).hexdigest()[:16]
    if p1 != os.path.join(MOTIV_DIR, "kreativ_" + h + ".png"):
        _fail("Kreativ-Hash-Formel weicht ab: %s" % p1)
    print("  C3) Kreativ-Cache: Praefix 'kreativ_', motiv-spezifisch, getrennt von szene/tafel OK")


def test_kreativ_scene_helper():
    # kreativ_motiv hat Vorrang; Fallback auf szene_motiv/bild_motiv
    if bildmotiv._kreativ_scene({"kreativ_motiv": "A", "szene_motiv": "B"}) != "A":
        _fail("_kreativ_scene bevorzugt kreativ_motiv nicht")
    if bildmotiv._kreativ_scene({"szene_motiv": "B"}) != "B":
        _fail("_kreativ_scene faellt nicht auf szene_motiv zurueck")
    if not bildmotiv._kreativ_scene({}):
        _fail("_kreativ_scene liefert keinen Default")
    print("  C4) _kreativ_scene: kreativ_motiv-Vorrang + Fallback-Kette OK")


def test_ensure_photo_fuer_routing():
    db.set_einstellung("bild_stil", "kreativ")
    res = bildmotiv.ensure_photo_fuer({"ueberschrift": "X", "kreativ_motiv": KREATIV_SZENE})
    if res is not None:
        _fail("Ohne API-Key sollte ensure_photo_fuer (kreativ) None liefern, war: %r" % res)
    # 'icon:'-Motive bleiben gezeichnet (kein kreativ-Foto)
    icon_res = bildmotiv.ensure_photo_fuer({"szene_motiv": "icon:kalender"})
    if icon_res is None or "icon_kalender" not in os.path.basename(icon_res):
        _fail("'icon:'-Motiv sollte auch im kreativ-Modus gezeichnet werden: %r" % icon_res)
    db.set_einstellung("bild_stil", "standard")
    print("  C5) ensure_photo_fuer routet kreativ + None ohne Key; icon: bleibt gezeichnet OK")


def test_retention_kreativ_in_cache_dateien():
    fields = {"kreativ_motiv": KREATIV_SZENE, "ueberschrift": "X", "szene_motiv": "Y"}
    pfade = bildmotiv.cache_dateien_fuer_fields(fields)
    # Producer-Pfad (openai) muss enthalten sein -> Retention-Schutz
    kp = bildmotiv._kreativ_pfad(KREATIV_SZENE, tool="openai")
    if kp not in pfade:
        _fail("cache_dateien_fuer_fields enthaelt den kreativ-Pfad NICHT (Retention-Luecke): %r" % kp)
    # ideogram-Variante ebenfalls (beide Tools geschuetzt)
    kpi = bildmotiv._kreativ_pfad(KREATIV_SZENE, tool="ideogram")
    if kpi not in pfade:
        _fail("cache_dateien_fuer_fields enthaelt die ideogram-kreativ-Variante NICHT")
    print("  C6) Retention: cache_dateien_fuer_fields enthaelt kreativ-Pfad (openai+ideogram) OK")


# ---------------------------------------------------------------------------
# D) bildgen kreativ -> Standard-Layout
# ---------------------------------------------------------------------------
def _dummy_photo(path):
    Image.new("RGB", (1024, 1024), (180, 140, 90)).save(path)
    return path


def _card_pixels(img):
    cnt = 0
    px = img.convert("RGB").load()
    for x in range(380, 700, 8):
        for y in range(380, 700, 8):
            r, g, bl = px[x, y]
            if r > 235 and g > 235 and bl > 235:
                cnt += 1
    return cnt


def test_render_kreativ_reines_foto():
    # #145: kreativ = reines Foto + NUR CI-Kreise -> KEINE weisse Text-Karte in der Mitte.
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    photo = _dummy_photo(os.path.join(data, "dummy_kreativ.png"))
    db.set_einstellung("bild_stil", "kreativ")
    out = os.path.join(data, "kreativ.png")
    p = b.render(FIELDS, photo, "Wir sind HILO", out, portrait=None)
    if not (p and os.path.exists(p)):
        _fail("render() (kreativ) hat kein Bild erzeugt")
    img = Image.open(p)
    if img.size != (1080, 1080):
        _fail("kreativ-Bild hat falsche Groesse: %r" % (img.size,))
    card = _card_pixels(img)
    # Kreativ: KEINE weisse Text-Karte in der Mitte (reines Foto). Toleranz fuer Streupixel.
    if card > 60:
        _fail("kreativ zeigt eine Text-Karte (weisse Mitte %d Pixel) - soll reines Foto sein" % card)
    # Standard zum Vergleich: Karte vorhanden (Regression - Standard-Layout unveraendert).
    db.set_einstellung("bild_stil", "standard")
    out_s = os.path.join(data, "kreativ_std.png")
    p_s = b.render(FIELDS, photo, "Wir sind HILO", out_s, portrait=None)
    card_s = _card_pixels(Image.open(p_s))
    if card_s < 200:
        _fail("standard-Render hat keine Text-Karte mehr (weisse Mitte nur %d Pixel) - Regression" % card_s)
    db.set_einstellung("bild_stil", "standard")
    print("  D) bildgen kreativ: reines Foto ohne Karte (%d), standard behaelt Karte (%d) OK" % (card, card_s))


# ---------------------------------------------------------------------------
# E) E2E-Retention: aktiver kreativ-Entwurf, altes Foto -> bleibt
# ---------------------------------------------------------------------------
def _touch(pfad, alter_tage=0.0):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    if alter_tage:
        t = time.time() - alter_tage * 86400
        os.utime(pfad, (t, t))
    return pfad


def test_e2e_retention_kreativ():
    db.init_db()
    os.makedirs(MOTIV_DIR, exist_ok=True)
    f_aktiv = {"kreativ_motiv": "E2E aktive kreativ-Szene, leerer Stuhl bei Feier",
               "ueberschrift": "Bleibt", "szene_motiv": "Kuechentisch"}
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES (?,?,?)",
                     ("facebook", json.dumps(f_aktiv, ensure_ascii=False), "entwurf"))
        conn.commit()
    # altes kreativ-Foto (40 Tage) genau am Producer-Pfad anlegen
    scene = bildmotiv._kreativ_scene(f_aktiv)
    p_kreativ = _touch(bildmotiv._kreativ_pfad(scene, tool="openai"), alter_tage=40)
    with db.get_conn() as conn:
        wartung.aufraeumen_motive(conn, schonfrist_tage=14)
    if not os.path.exists(p_kreativ):
        _fail("Aktiver kreativ-Entwurf: altes kreativ-Foto wurde faelschlich geloescht: %s" % p_kreativ)
    print("  E) E2E-Retention: aktiver kreativ-Entwurf -> altes kreativ-Foto bleibt OK")


if __name__ == "__main__":
    print("== A) Einstellung get/set ==")
    test_einstellung()
    print("== B) textgen Art-Director-Schritt (NUR kreativ) ==")
    test_art_director_prompt_wortlaut()
    test_art_director_nur_kreativ()
    test_art_director_kreativ_setzt_motiv()
    test_art_director_stabil_nur_wenn_leer()
    test_art_director_robust()
    print("== C) bildmotiv kreativ-Prompt / Payload / Cache / Retention ==")
    test_kreativ_prompt()
    test_kreativ_payload()
    test_kreativ_cache_praefix()
    test_kreativ_scene_helper()
    test_ensure_photo_fuer_routing()
    test_retention_kreativ_in_cache_dateien()
    print("== D) bildgen kreativ -> reines Foto (kein Textfeld) ==")
    test_render_kreativ_reines_foto()
    print("== E) E2E-Retention kreativ ==")
    test_e2e_retention_kreativ()
    print("BESTANDEN: Bild-Stil 'kreativ' (#143) - alle Pruefungen gruen.")
