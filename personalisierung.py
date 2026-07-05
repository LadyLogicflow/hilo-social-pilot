# -*- coding: utf-8 -*-
"""Personalisierung eines Beitrags je Beratungsstelle: gleiches Bild, aber der CTA-Text
im Bild nennt die Stelle, und der Begleittext bekommt einen lokalen Bezug + Buchungslink.
Deterministisch (kein KI-Token)."""
import os
import re


def buchungslink(stelle):
    """Buchungs-URL der Beratungsstelle (oder '')."""
    return (stelle["buchungs_url"] or "").strip() if _has(stelle, "buchungs_url") else ""


def _local_satz(stelle):
    """Persoenlicher, lokaler Satz (Leitung/Ort) fuer den Begleittext (oder '' ohne Ort) - OHNE Link.
    Den Link bzw. den kanalabhaengigen Termin-Hinweis ergaenzt personalisiere_caption."""
    ort = (stelle["ort"] or "").strip() if _has(stelle, "ort") else ""
    if not ort:
        return ""
    leitung = (stelle["leitung"] or "").strip() if _has(stelle, "leitung") else ""
    if leitung:
        return ("%s von Ihrer HILO-Beratungsstelle in %s bespricht Ihre steuerliche "
                "Situation gerne persönlich mit Ihnen." % (leitung, ort))
    return "Ihre HILO-Beratungsstelle in %s berät Sie gerne persönlich." % ort


def _split_hashtags(text):
    """Trennt einen abschliessenden Hashtag-Block (#... am Ende) vom Haupttext ab.
    Nur wenn der Block klar abgesetzt ist: durch einen Zeilenumbruch ODER mit mindestens zwei
    Hashtags. So wird ein einzelnes Hashtag mitten im Satz (z.B. '... unter dem Tag #steuern')
    NICHT zerrissen. Rueckgabe: (haupttext, hashtag_block) - hashtag_block '' wenn keiner."""
    text = (text or "").strip()
    m = re.search(r"(\s*)((?:#\S+\s*)+)$", text)
    if not m or m.start(2) == 0:
        return text, ""
    block = m.group(2).strip()
    abgesetzt = "\n" in m.group(1) or len(re.findall(r"#\S+", block)) >= 2
    if not abgesetzt:
        return text, ""
    return text[:m.start()].rstrip(), block


def personalisiere_caption(base, stelle, kanal=None):
    """Haengt den lokalen Satz (+ kanalabhaengigen Termin-Hinweis) an den Begleittext an - aber VOR
    einen evtl. vorhandenen Hashtag-Block. Der Termin-Hinweis wird NUR ergaenzt, wenn ein Buchungslink
    hinterlegt ist - so passt er immer zum tatsaechlich geposteten ersten Kommentar:
    Facebook -> 'Link im ersten Kommentar', Instagram -> 'in unserer Bio', sonst (WhatsApp/Default)
    der Buchungslink direkt im Text."""
    satz = _local_satz(stelle)
    if not satz:
        return (base or "").strip()
    link = buchungslink(stelle)
    if link:
        if kanal == "facebook":
            satz += " Den Link zum Termin finden Sie im ersten Kommentar."
        elif kanal == "instagram":
            satz += " Den Termin-Link finden Sie in unserer Bio."
        else:
            satz += " Termin vereinbaren: %s" % link
    haupt, tags = _split_hashtags(base)
    kombi = (haupt + " " + satz).strip() if haupt else satz
    return (kombi + "\n\n" + tags).strip() if tags else kombi


def caption_fuer_stelle(fields, stelle, kanal):
    """Kanalspezifischer, fuer die Beratungsstelle personalisierter Begleittext."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    base = caps.get(kanal) or fields.get("caption") or ""
    return personalisiere_caption(base, stelle, kanal)


def whatsapp_texte(fields, stelle=None, quelle_url=""):
    """Liefert (kanal_text, story_text) fuer WhatsApp - Buchungs- und Quelllink werden hier direkt
    eingebettet (WhatsApp erlaubt Links). stelle=None -> ohne Stellen-Personalisierung."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    link = buchungslink(stelle) if stelle else ""
    ort = (stelle["ort"] or "").strip() if (stelle and _has(stelle, "ort")) else ""
    quelle_url = (quelle_url or "").strip()

    kanal = (caps.get("whatsapp_kanal") or fields.get("caption") or "").strip()
    zeilen = []
    if ort:
        zeilen.append("Ihre HILO-Beratungsstelle in %s berät Sie gerne." % ort)
    if quelle_url:
        zeilen.append("Mehr dazu: %s" % quelle_url)
    if link:
        zeilen.append("Termin vereinbaren: %s" % link)
    kanal_text = (kanal + ("\n\n" + "\n".join(zeilen) if zeilen else "")).strip()

    story = (caps.get("whatsapp_story") or "").strip()
    if link:
        story = (story + "\nTermin: %s" % link).strip()
    return kanal_text, story


def fuer_stelle(fields, stelle, kanal=None):
    """Gibt eine personalisierte Kopie der Beitrags-Felder fuer eine Beratungsstelle zurueck.
    Deterministisch: nutzt ausschliesslich echte Stammdaten (Ort, Leitung, Buchungslink) und
    erfindet nichts. Der CTA im Bild nennt den Ort; der Begleittext bekommt einen lokalen Bezug.
    Mit 'kanal' wird der passende kanalspezifische Begleittext gewaehlt (sonst der Default)."""
    f = dict(fields)
    ort = (stelle["ort"] or "").strip() if _has(stelle, "ort") else ""
    base = caption_fuer(fields, kanal)
    if ort:
        f["cta"] = "Jetzt Termin bei Ihrer HILO-Beratungsstelle %s vereinbaren" % ort
        f["ort"] = ort   # fuer den sichtbaren Ortsbezug im Bild
    f["caption"] = personalisiere_caption(base, stelle)
    return f


def caption_fuer(fields, kanal):
    """Liefert den kanalspezifischen Begleittext (Fallback: gemeinsame 'caption')."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    return (caps.get(kanal) or fields.get("caption") or "").strip()


def _portrait(stelle):
    """Pfad zum Kreisportraet der Stelle, falls hinterlegt und vorhanden - sonst None
    (dann zeigt das Bild den blauen Slogan-Punkt)."""
    p = (stelle["portrait_pfad"] or "").strip() if _has(stelle, "portrait_pfad") else ""
    return p if (p and os.path.exists(p)) else None


def _berater_comic(stelle):
    """Pfad zum Comic-Portrait der Leitung DIESER Stelle (Feld berater_comic, Stil 'Comic Beratung'),
    falls hinterlegt und vorhanden - sonst None."""
    p = (stelle["berater_comic"] or "").strip() if _has(stelle, "berater_comic") else ""
    return p if (p and os.path.exists(p)) else None


def _bibel_bild(stelle):
    """Pfad zur Character-Bible / Comic-Vorlage DIESER Stelle (Feld bibel_bild, #151), falls
    hinterlegt und vorhanden - sonst None. Hat Vorrang vor dem aus dem Foto abgeleiteten
    berater_comic (Stil 'Comic Beratung')."""
    p = (stelle["bibel_bild"] or "").strip() if _has(stelle, "bibel_bild") else ""
    return p if (p and os.path.exists(p)) else None


def _bibel_text(stelle):
    """Charakter-Beschreibung DIESER Stelle (Feld bibel_text, #151) oder '' - wird an den
    comic_beratung-Prompt angehaengt."""
    return (stelle["bibel_text"] or "").strip() if _has(stelle, "bibel_text") else ""


def _setze_berater_comic(f, stelle):
    """Legt fuer den Stil 'comic_beratung' die Berater-Referenz DIESER Stelle in f['berater_comic'] ab,
    damit bildmotiv.ensure_photo_fuer das personalisierte Comic-Beratung-Bild mit dem eigenen
    Berater-Gesicht der Stelle erzeugt (jede Stelle ihr eigenes Bild). Andere Stile bleiben unberuehrt.

    NEU (#151, Character-Bible): Vorrang bibel_bild > berater_comic > (nichts). Ist fuer die Stelle
    eine Character-Bible (bibel_bild) hinterlegt, wird sie STATT des aus dem Foto abgeleiteten
    berater_comic als erste Referenz genutzt. Zusaetzlich wird die optionale Charakter-Beschreibung
    (bibel_text) in f['bibel_text'] durchgereicht, damit sie in den Prompt einfliesst. Hat die Stelle
    weder Bible noch Berater-Comic, wird nichts gesetzt (bildmotiv faellt dann auf den normalen Comic
    zurueck). Liefert f zurueck."""
    import stilwahl
    if stilwahl.aktiver_stil(f) == "comic_beratung":
        bild = _bibel_bild(stelle) or _berater_comic(stelle)
        if bild:
            f["berater_comic"] = bild
        text = _bibel_text(stelle)
        if text:
            f["bibel_text"] = text
    return f


def render_fuer_stelle(fields, stelle, out_path):
    """Rendert das Bild mit personalisiertem CTA (gleiches Foto/Design). Liefert (felder, pfad).
    Hat die Stelle ein Kreisportraet hinterlegt, ersetzt es den blauen Slogan-Punkt."""
    import bildgen, bildmotiv
    f = fuer_stelle(fields, stelle)
    _setze_berater_comic(f, stelle)   # Stil 'comic_beratung': Berater-Comic DIESER Stelle einsetzen
    photo = bildmotiv.ensure_photo_fuer(f)
    slogan = bildgen.pick_slogan(f.get("slogan"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bildgen.render(f, photo, slogan, out_path, portrait=_portrait(stelle))
    return f, out_path


def _berater_ref(stelle):
    """Liefert die Berater-Referenz DIESER Stelle fuer die Comic-Familie: bibel_bild (Character-Bible,
    #151) hat Vorrang vor dem aus dem Foto abgeleiteten berater_comic; sonst None. Gleiche
    Aufloesung wie _setze_berater_comic (dort fuer comic_beratung)."""
    return _bibel_bild(stelle) or _berater_comic(stelle)


def render_slides_fuer_stelle(fields, stelle, out_dir, prefix):
    """Rendert ein Karussell mit personalisiertem CTA (gleiches Foto/Design je Stelle).
    Liefert (felder, [pfade]). Kreisportraet der Stelle ersetzt ggf. den blauen Slogan-Punkt.

    Stil 'comic_strip' (#154): ein 3-Felder-Comic-Karussell mit Sprechblasen, personalisiert je
    Stelle. Statt der normalen Slide-Pipeline werden die 3 ROHEN KI-Panels (kein Text-Karten-Overlay,
    keine CI-Kreise) ueber bildmotiv.ensure_comic_strip_bilder erzeugt und deren Pfade geliefert. Die
    Berater-Referenz der Stelle (bibel_bild > berater_comic) fuellt Feld 1+3; hat die Stelle keine,
    degradieren die Panels sinnvoll (ohne Berater-Gesicht) statt zu crashen.

    v2 (#155): der Archetyp (vorteil/warnung) + die Bild-2-Variante reisen als fields['strip_archetyp']
    /['strip_zeile2'] mit (fuer_stelle kopiert sie unveraendert). ensure_comic_strip_bilder loest sie
    auf; fehlen sie (Alt-Entwurf), greift dort die KI-Vorauswahl bzw. der Default 'vorteil'."""
    import bildgen, bildmotiv
    import stilwahl
    f = fuer_stelle(fields, stelle)
    if stilwahl.aktiver_stil(f) == "comic_strip":
        os.makedirs(out_dir, exist_ok=True)
        paths = bildmotiv.ensure_comic_strip_bilder(f, _berater_ref(stelle))
        return f, paths
    _setze_berater_comic(f, stelle)   # Stil 'comic_beratung': Berater-Comic DIESER Stelle einsetzen
    photo = bildmotiv.ensure_photo_fuer(f)
    slogan = bildgen.pick_slogan(f.get("slogan"))
    paths = bildgen.render_slides(f, photo, slogan, out_dir, prefix, portrait=_portrait(stelle))
    return f, paths


def _has(row, key):
    try:
        return key in row.keys()
    except Exception:
        return key in row
