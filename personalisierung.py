# -*- coding: utf-8 -*-
"""Personalisierung eines Beitrags je Beratungsstelle: gleiches Bild, aber der CTA-Text
im Bild nennt die Stelle, und der Begleittext bekommt einen lokalen Bezug + Buchungslink.
Deterministisch (kein KI-Token)."""
import os
import re


def buchungslink(stelle):
    """Buchungs-URL der Beratungsstelle (oder '')."""
    return (stelle["buchungs_url"] or "").strip() if _has(stelle, "buchungs_url") else ""


def homepage(stelle):
    """HILO-Homepage-URL der Beratungsstelle (oder '')."""
    return (stelle["homepage_url"] or "").strip() if (stelle and _has(stelle, "homepage_url")) else ""


def kanal_invite(stelle):
    """Einladungslink des WhatsApp-Kanals der Beratungsstelle (oder '')."""
    return (stelle["wa_kanal_invite"] or "").strip() if (stelle and _has(stelle, "wa_kanal_invite")) else ""


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


# Fester Karriere-Link fuer Recruiting-Beitraege (deutschlandweit, keine Stellen-Regionalisierung).
KARRIERE_LINK = "https://www.hilo.de/karriere/"


def _mit_karriere_link(base):
    """Haengt den Karriere-Link an den Begleittext an - aber VOR einen evtl. Hashtag-Block."""
    haupt, tags = _split_hashtags(base)
    kern = ((haupt + "\n\n" if haupt else "") + "Mehr erfahren: %s" % KARRIERE_LINK).strip()
    return (kern + "\n\n" + tags).strip() if tags else kern


def caption_fuer_stelle(fields, stelle, kanal):
    """Kanalspezifischer, fuer die Beratungsstelle personalisierter Begleittext."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    base = caps.get(kanal) or fields.get("caption") or ""
    # Recruiting: KEINE steuerliche Stellen-Personalisierung und KEIN Terminlink - stattdessen der feste
    # Karriere-Link (der Beitrag wirbt deutschlandweit Beratungsstellenleiter an, nicht Steuer-Mandanten).
    if fields.get("kampagne") == "recruiting":
        return _mit_karriere_link(base)
    return personalisiere_caption(base, stelle, kanal)


def whatsapp_texte(fields, stelle=None, quelle_url=""):
    """Liefert (kanal_text, story_text) fuer WhatsApp - Buchungs- und Info-Link werden hier direkt
    eingebettet (WhatsApp erlaubt Links). Der "Mehr Infos"-Link zeigt auf die HILO-Homepage der
    Beratungsstelle (homepage_url); der Parameter quelle_url wird nicht mehr verwendet (Kompatibilitaet).
    stelle=None -> ohne Stellen-Personalisierung, dann auch ohne Homepage-Link."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    # Recruiting-Status/-Kanal: kein Terminlink, keine Kanal-Einladung (das ist der Steuer-Funnel) -
    # nur der feste Karriere-Link.
    if fields.get("kampagne") == "recruiting":
        kanal_text = ((caps.get("whatsapp_kanal") or fields.get("caption") or "").strip()
                      + "\n\nMehr erfahren: %s" % KARRIERE_LINK).strip()
        story = ((caps.get("whatsapp_story") or "").strip()
                 + "\nMehr erfahren: %s" % KARRIERE_LINK).strip()
        return kanal_text, story
    link = buchungslink(stelle) if stelle else ""
    ort = (stelle["ort"] or "").strip() if (stelle and _has(stelle, "ort")) else ""
    hp = homepage(stelle)

    kanal = (caps.get("whatsapp_kanal") or fields.get("caption") or "").strip()
    zeilen = []
    if ort:
        zeilen.append("Ihre HILO-Beratungsstelle in %s berät Sie gerne." % ort)
    if hp:
        zeilen.append("Mehr Infos: %s" % hp)
    if link:
        zeilen.append("Termin vereinbaren: %s" % link)
    kanal_text = (kanal + ("\n\n" + "\n".join(zeilen) if zeilen else "")).strip()

    story = (caps.get("whatsapp_story") or "").strip()
    if link:
        story = (story + "\nTermin: %s" % link).strip()
    # Funnel: der Status (nur Kontakte) lädt zum öffentlichen WhatsApp-Kanal ein - aber nur, wenn
    # die Stelle überhaupt einen Kanal hinterlegt hat (sonst keine Einladung).
    invite = kanal_invite(stelle)
    if invite:
        story = (story + "\n➡️ Für mehr Informationen folge unserem WhatsApp-Kanal: %s" % invite).strip()
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




def render_fuer_stelle(fields, stelle, out_path):
    """Rendert das ShareNext-Bild mit personalisierten Logo-Kreisen für die Beratungsstelle.

    ShareNext-Bilder haben Text bereits integriert - keine Text-Personalisierung nötig!
    Nur Logo-Kreise werden angepasst (Portrait der Beratungsstelle).

    NUR ShareNext-Bilder (entwurf_*.png) werden unterstützt - Legacy-Systeme
    wurden entfernt."""
    import bildgen
    f = fuer_stelle(fields, stelle)

    bild_pfad = f.get("bild_pfad")

    # ShareNext-Bild muss existieren
    if not bild_pfad or not os.path.exists(bild_pfad):
        raise ValueError(f"Kein Bild gefunden für Entwurf: {bild_pfad}")

    # Nur ShareNext-Bilder (entwurf_*.png) werden unterstützt
    basename = os.path.basename(bild_pfad)
    if not (basename.startswith("entwurf_") and "_premium" not in basename):
        raise ValueError(f"Nur ShareNext-Bilder werden unterstützt: {basename}")

    # ShareNext-Bild kopieren + Logo-Kreise hinzufügen
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    slogan = bildgen.pick_slogan(f.get("slogan"))
    bildgen.add_logo_circles(bild_pfad, slogan, out_path, portrait=_portrait(stelle), pos="unten")

    return f, out_path


def render_slides_fuer_stelle(fields, stelle, out_dir, prefix):
    """Rendert ShareNext-Bilder mit personalisierten Logo-Kreisen für die Beratungsstelle.

    ShareNext-Bilder haben Text bereits integriert - keine Text-Personalisierung nötig!
    Nur Logo-Kreise werden angepasst (Portrait der Beratungsstelle).

    NUR ShareNext-Bilder werden unterstützt - alle Stil-Logik wurde entfernt.
    Liefert (felder, [pfade]) - Liste mit einem Bild."""
    import bildgen
    f = fuer_stelle(fields, stelle)

    bild_pfad = f.get("bild_pfad")

    # ShareNext-Bild muss existieren
    if not bild_pfad or not os.path.exists(bild_pfad):
        raise ValueError(f"Kein Bild gefunden für Entwurf: {bild_pfad}")

    # Nur ShareNext-Bilder (entwurf_*.png) werden unterstützt
    basename = os.path.basename(bild_pfad)
    if not (basename.startswith("entwurf_") and "_premium" not in basename):
        raise ValueError(f"Nur ShareNext-Bilder werden unterstützt: {basename}")

    # ShareNext-Bild kopieren + Logo-Kreise hinzufügen
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{prefix}_0.png")
    slogan = bildgen.pick_slogan(f.get("slogan"))
    bildgen.add_logo_circles(bild_pfad, slogan, out_path, portrait=_portrait(stelle), pos="unten")

    return f, [out_path]


def _has(row, key):
    try:
        return key in row.keys()
    except Exception:
        return key in row
