# -*- coding: utf-8 -*-
"""Weichen fuer den Mandanten 'BSt Next' (reine Funktionen, ohne Flask/DB, gut testbar).

BSt Next ist eine eigene Firma/Marke neben HILO (nicht eine Beratungsstelle). Ein Entwurf traegt
fields['marke'] == 'bstnext'. Diese Regeln stellen sicher:
- BSt-Next-Beitraege gehen NUR an die hinterlegte(n) BSt-Next-Facebook-Seite(n), nie an
  Beratungsstellen;
- HILO-Beitraege gehen NIE an eine BSt-Next-Seite;
- HILO-Funktionen, die das Bild/den Text per HILO-Pipeline neu erzeugen wuerden (Bild neu, Text
  ueberarbeiten, Pool, Recruiting, WhatsApp ...), sind fuer BSt-Next-Entwuerfe gesperrt."""

MARKE = "bstnext"
EINSTELLUNG_SEITEN = "bstnext_fb_seiten"      # Komma-getrennte Facebook-Page-IDs

# Flask-Endpunkte (Funktionsnamen in web.py), die einen Entwurf per HILO-Pipeline veraendern oder
# in HILO-Pools/WhatsApp geben wuerden. Fuer BSt-Next-Entwuerfe gesperrt.
GESPERRTE_ENDPOINTS = frozenset({
    "bild_neu", "umsetzung_neu", "text_neu", "anderes_bild", "bild_aktion", "bild_generieren",
    "bild_typ", "beitrag_neu", "reel_test", "vorschau",
    "pool_aufnehmen", "recruiting_freigeben", "recruiting_neu",
    "kanalwerbung_freigeben", "kanalwerbung_neu",
    "whatsapp_status_test", "whatsapp_kanal_jetzt",
})
# Aktionen von POST /aktion/<eid>, die Text/Bild per HILO-KI neu erzeugen.
GESPERRTE_AKTIONEN = frozenset({"ueberarbeiten", "caption_erstellen"})

MELDUNG_GESPERRT = ("Dieser Beitrag gehört zu BSt Next und wird unter „BSt Next“ (/bstnext) "
                    "bearbeitet. Diese Funktion ist nur für HILO-Beiträge.")


def ist_bstnext(fields):
    return isinstance(fields, dict) and fields.get("marke") == MARKE


def seiten_ids(wert):
    """Zerlegt die Einstellung 'bstnext_fb_seiten' in eine Menge von Page-IDs."""
    if not wert:
        return set()
    return {p.strip() for p in str(wert).replace(";", ",").replace("\n", ",").split(",") if p.strip()}


def ziel_erlaubt(fields, stelle, page_id, bstnext_seiten):
    """Prueft EIN Veroeffentlichungsziel. stelle = Beratungsstelle (oder None), page_id = Facebook-
    Seite (oder None), bstnext_seiten = Menge der hinterlegten BSt-Next-Seiten.
    Rueckgabe (ok, Meldung)."""
    seiten = set(bstnext_seiten or ())
    if ist_bstnext(fields):
        if stelle is not None:
            return False, "BSt-Next-Beiträge gehen nicht an Beratungsstellen."
        if not seiten:
            return False, "Die BSt-Next-Facebook-Seite ist noch nicht hinterlegt (Seite „BSt Next“)."
        if not page_id or str(page_id) not in seiten:
            return False, "BSt-Next-Beiträge gehen nur an die hinterlegte BSt-Next-Facebook-Seite."
        return True, ""
    if page_id and str(page_id) in seiten:
        return False, "HILO-Beiträge gehen nicht an die BSt-Next-Facebook-Seite."
    return True, ""


def ziele_pruefen(fields, stelle_ids, page_ids, bstnext_seiten):
    """Prueft mehrere Ziele (Formular: stelle_id[], page_id[]). Rueckgabe: Fehlermeldung oder None."""
    seiten = set(bstnext_seiten or ())
    if ist_bstnext(fields):
        for _ in stelle_ids:
            return "BSt-Next-Beiträge gehen nicht an Beratungsstellen."
        for pid in page_ids:
            ok, msg = ziel_erlaubt(fields, None, pid, seiten)
            if not ok:
                return msg
        return None
    for pid in page_ids:
        ok, msg = ziel_erlaubt(fields, None, pid, seiten)
        if not ok:
            return msg
    return None


def endpoint_gesperrt(endpoint, aktion=None):
    """True, wenn der Endpunkt (bzw. die Aktion von /aktion) fuer BSt-Next-Entwuerfe gesperrt ist."""
    if endpoint in GESPERRTE_ENDPOINTS:
        return True
    return endpoint == "aktion" and (aktion or "") in GESPERRTE_AKTIONEN
