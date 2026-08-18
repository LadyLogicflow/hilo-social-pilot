# -*- coding: utf-8 -*-
"""M6 - Veroeffentlichung auf Meta-Plattformen (Facebook-Seiten, Instagram).

Facebook: direkter Binaer-Upload des Bildes nach POST /{page-id}/photos.
Instagram: zweistufig (Media-Container -> Publish); benoetigt eine OEFFENTLICHE Bild-URL.

Secrets (aus secrets_store):
  meta_user_token   - Nutzer-Token mit pages_manage_posts, instagram_content_publish, ...
  meta_app_id       - (optional) App-ID,  fuer Umwandlung in ein Langzeit-Token
  meta_app_secret   - (optional) App-Secret, fuer Umwandlung in ein Langzeit-Token

Tokens werden NIE geloggt oder ausgegeben.
"""
import json
import re
import time
import logging
import requests
from secrets_store import get_secret, set_secret

log = logging.getLogger("hilo.publish")

GRAPH = "https://graph.facebook.com/v26.0"


def _scrub(text):
    """Maskiert Zugangs-Tokens in beliebigen Strings (z.B. Fehlermeldungen/URLs), damit sie
    NIE im Klartext in Logs landen. Trifft ?access_token=..., fb_exchange_token=... und rohe
    EAA...-Tokens. Vgl. Doc-Zusage oben: 'Tokens werden NIE geloggt oder ausgegeben.'"""
    s = str(text)
    s = re.sub(r"((?:access_token|fb_exchange_token|client_secret)=)[^&\s\"']+", r"\1<REDACTED>", s)
    s = re.sub(r"EAA[A-Za-z0-9]{20,}", "<REDACTED>", s)
    return s


# ---------------------------------------------------------------------------
# Token-Handhabung
# ---------------------------------------------------------------------------
def _user_token():
    tok = get_secret("meta_user_token")
    if not tok:
        raise RuntimeError("Secret 'meta_user_token' fehlt. Bitte mit "
                           "'python main.py --set-secret meta_user_token' setzen.")
    return tok


def ensure_long_lived():
    """Tauscht das Kurzzeit-Token gegen ein Langzeit-Token (60 Tage), falls
    App-ID und App-Secret hinterlegt sind. Speichert das Ergebnis zurueck.
    Gibt True zurueck, wenn ein Tausch stattgefunden hat."""
    app_id = get_secret("meta_app_id")
    app_secret = get_secret("meta_app_secret")
    if not (app_id and app_secret):
        return False
    r = requests.get(GRAPH + "/oauth/access_token", timeout=30, params={
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": _user_token(),
    })
    if r.status_code != 200:
        log.warning("Langzeit-Token-Tausch fehlgeschlagen (HTTP %s).", r.status_code)
        return False
    new = r.json().get("access_token")
    if new:
        set_secret("meta_user_token", new)
        log.info("Langzeit-Token gespeichert (gueltig ca. 60 Tage).")
        return True
    return False


# ---------------------------------------------------------------------------
# Seiten / Konten ermitteln
# ---------------------------------------------------------------------------
def list_pages():
    """Liefert die Facebook-Seiten des Nutzers samt verknuepftem IG-Konto.
    Rueckgabe: Liste von Dicts {id, name, ig_id, ig_username}. OHNE Tokens.

    Wirft RuntimeError mit der ECHTEN Facebook-Fehlermeldung (nicht nur Status-Code + URL) bei
    Fehlern - r.raise_for_status() allein zeigt nur 'HTTP 400: Bad Request fuer <URL>', ohne den
    eigentlichen Grund (z.B. 'Invalid OAuth access token', 'Application does not have permission
    for this action', etc.), den Facebook im JSON-Body mitschickt (#Diagnose-Fix)."""
    r = requests.get(GRAPH + "/me/accounts", timeout=30, params={
        "fields": "id,name,instagram_business_account{id,username}",
        "limit": 100,
        "access_token": _user_token(),
    })
    if r.status_code != 200:
        raise RuntimeError(_err(r))
    out = []
    for p in r.json().get("data", []):
        ig = p.get("instagram_business_account") or {}
        out.append({
            "id": p["id"], "name": p.get("name", ""),
            "ig_id": ig.get("id"), "ig_username": ig.get("username"),
        })
    return out


def _page_token(page_id):
    """Holt das Seiten-Token fuer eine bestimmte Seite (intern, nie ausgeben).
    Fallback: Wenn /me/accounts fehlschlaegt (z.B. fehlende Permissions), wird
    der User-Token als Fallback verwendet (funktioniert fuer Basic-Posts)."""
    user_tok = _user_token()
    try:
        r = requests.get(GRAPH + "/me/accounts", timeout=30, params={
            "fields": "id,access_token", "limit": 100, "access_token": user_tok,
        })
        if r.status_code != 200:
            raise RuntimeError(_err(r))   # _err liefert nur die Facebook-Meldung, NICHT die Token-URL
        for p in r.json().get("data", []):
            if p["id"] == str(page_id):
                return p.get("access_token")
    except Exception as ex:
        log.warning("Page-Token konnte nicht geholt werden (%s), verwende User-Token als Fallback.", _scrub(ex))
        return user_tok
    raise RuntimeError("Keine Berechtigung fuer Seite %s (nicht in /me/accounts)." % page_id)


def page_token_map():
    """Holt ALLE Seiten-Tokens in EINEM /me/accounts-Aufruf und liefert {seiten_id: token}.
    Fuer Massen-Operationen (z.B. Insights ueber viele Beitraege), damit NICHT pro Beitrag
    einzeln /me/accounts aufgerufen wird (das treibt sonst das Facebook-Anfrage-Limit hoch, #4).
    Bei Fehler: leeres Dict (die Aufrufer fallen dann auf _page_token/User-Token zurueck)."""
    try:
        r = requests.get(GRAPH + "/me/accounts", timeout=30, params={
            "fields": "id,access_token", "limit": 100, "access_token": _user_token(),
        })
        if r.status_code != 200:
            log.warning("page_token_map: /me/accounts fehlgeschlagen (%s).", _scrub(_err(r)))
            return {}
        return {str(p["id"]): p.get("access_token") for p in r.json().get("data", []) if p.get("access_token")}
    except Exception as ex:
        log.warning("page_token_map fehlgeschlagen (%s).", _scrub(ex))
        return {}


# ---------------------------------------------------------------------------
# Facebook: Foto-Beitrag
# ---------------------------------------------------------------------------
def publish_facebook(page_id, image_path, caption, place=None, alt_text=None):
    """Veroeffentlicht ein Foto mit Begleittext auf einer Facebook-Seite.
    place = optionale Facebook-Orts-ID fuer die Standort-Markierung. Schlaegt der Post MIT Ort fehl
    (z.B. ungueltige Orts-ID), wird OHNE Ort erneut versucht, damit der Beitrag trotzdem erscheint.
    alt_text = optionaler Alt-Text fuer Barrierefreiheit (Feld 'alt_text_custom' - das schreibbare
    Feld der Graph API; 'alt_text' selbst ist schreibgeschuetzt/automatisch generiert).
    Rueckgabe: (ok, info) - info ist die Post-/Foto-ID oder die Fehlermeldung."""
    token = _page_token(page_id)
    def _post(with_place):
        data = {"message": caption or "", "access_token": token}
        if with_place and place:
            data["place"] = place
        if alt_text:
            data["alt_text_custom"] = alt_text
        with open(image_path, "rb") as fh:
            return requests.post(GRAPH + "/%s/photos" % page_id, timeout=120, data=data, files={"source": fh})
    r = _post(True)
    if r.status_code != 200 and place:
        log.warning("Facebook-Foto-Post mit Ort fehlgeschlagen, erneut ohne Ort: %s", _err(r))
        r = _post(False)
    if r.status_code == 200:
        j = r.json()
        return True, (j.get("post_id") or j.get("id") or "")
    return False, _err(r)


# ---------------------------------------------------------------------------
# Facebook: Karussell-Beitrag (mehrere Fotos in einem Post)
# ---------------------------------------------------------------------------
def _delete_fb_photos(media_ids, token):
    """Raeumt teilweise hochgeladene, unveroeffentlichte Fotos nach einem Abbruch auf
    (best effort - Fehler werden geschluckt, damit der eigentliche Fehler sichtbar bleibt)."""
    for mid in media_ids:
        try:
            requests.post(GRAPH + "/%s" % mid, timeout=30,
                          data={"method": "delete", "access_token": token})
        except Exception:
            pass


def publish_facebook_carousel(page_id, image_paths, caption, place=None, alt_texts=None):
    """Veroeffentlicht mehrere Bilder als Karussell-Beitrag auf einer Facebook-Seite.
    Jedes Foto wird zunaechst unveroeffentlicht (published=false) hochgeladen, danach
    werden alle Foto-IDs in einem Feed-Beitrag zusammengefuehrt (attached_media).
    Scheitert ein Schritt, werden bereits hochgeladene Fotos wieder geloescht.
    alt_texts = optionale Liste mit einem Alt-Text je Bild (gleiche Reihenfolge/Laenge wie
    image_paths, einzelne Eintraege duerfen None sein). Feld 'alt_text_custom' (schreibbar)."""
    if not image_paths:
        return False, "Keine Bilder fuer Karussell uebergeben."
    if alt_texts is not None and len(alt_texts) != len(image_paths):
        return False, "alt_texts muss dieselbe Laenge wie image_paths haben."
    token = _page_token(page_id)
    media_ids = []
    for i, path in enumerate(image_paths):
        data = {"published": "false", "access_token": token}
        alt = alt_texts[i] if alt_texts else None
        if alt:
            data["alt_text_custom"] = alt
        with open(path, "rb") as fh:
            r = requests.post(GRAPH + "/%s/photos" % page_id, timeout=120,
                              data=data, files={"source": fh})
        if r.status_code != 200:
            _delete_fb_photos(media_ids, token)
            return False, _err(r)
        mid = r.json().get("id")
        if not mid:
            _delete_fb_photos(media_ids, token)
            return False, "Foto-Upload ohne ID-Rueckgabe."
        media_ids.append(mid)
    base = {"message": caption or "", "access_token": token}
    for i, mid in enumerate(media_ids):
        base["attached_media[%d]" % i] = json.dumps({"media_fbid": mid})
    def _feed(with_place):
        data = dict(base)
        if with_place and place:
            data["place"] = place
        return requests.post(GRAPH + "/%s/feed" % page_id, timeout=120, data=data)
    r = _feed(True)
    if r.status_code != 200 and place:
        log.warning("Facebook-Karussell mit Ort fehlgeschlagen, erneut ohne Ort: %s", _err(r))
        r = _feed(False)
    if r.status_code == 200:
        return True, (r.json().get("id") or "")
    _delete_fb_photos(media_ids, token)   # Feed-Beitrag fehlgeschlagen -> Fotos nicht verwaisen lassen
    return False, _err(r)


# ---------------------------------------------------------------------------
# Facebook: Story (Foto, verschwindet nach 24 Stunden) - offizielle Page-Stories-API
# ---------------------------------------------------------------------------
def publish_facebook_story(page_id, image_path, alt_text=None):
    """Veroeffentlicht ein Bild als Facebook-Seiten-Story (verschwindet nach 24 Stunden).
    Zweistufig: Foto unveroeffentlicht hochladen (POST /{page_id}/photos?published=false),
    dann die Foto-ID an POST /{page_id}/photo_stories uebergeben. Anders als bei Instagram
    ist KEINE oeffentliche Bild-URL noetig (direkter Binaer-Upload). Ideal im Hochformat 9:16.
    alt_text = optionaler Alt-Text fuer Barrierefreiheit (Feld 'alt_text_custom').
    Rueckgabe: (ok, info) - info ist die Story-/Post-ID oder die Fehlermeldung."""
    token = _page_token(page_id)
    data = {"published": "false", "access_token": token}
    if alt_text:
        data["alt_text_custom"] = alt_text
    with open(image_path, "rb") as fh:
        up = requests.post(GRAPH + "/%s/photos" % page_id, timeout=120,
                           data=data, files={"source": fh})
    if up.status_code != 200:
        return False, _err(up)
    photo_id = up.json().get("id")
    if not photo_id:
        return False, "Foto-Upload ohne ID-Rueckgabe."
    r = requests.post(GRAPH + "/%s/photo_stories" % page_id, timeout=60,
                      data={"photo_id": photo_id, "access_token": token})
    if r.status_code == 200:
        j = r.json()
        return True, (j.get("post_id") or j.get("id") or "")
    _delete_fb_photos([photo_id], token)   # Story-Publish fehlgeschlagen -> Foto nicht verwaisen lassen
    return False, _err(r)


# ---------------------------------------------------------------------------
# Instagram: zweistufige Veroeffentlichung (benoetigt oeffentliche Bild-URL)
# ---------------------------------------------------------------------------
def publish_instagram(ig_user_id, image_url, caption, location_id=None, alt_text=None):
    """Veroeffentlicht ein Bild auf einem Instagram-Business-Konto.
    image_url MUSS oeffentlich erreichbar sein (kein Pi-localhost!).
    location_id = optionale Facebook-Orts-ID fuer den Geotag (Standort-Markierung).
    alt_text = optionaler Alt-Text fuer Barrierefreiheit (Feld 'alt_text', seit 24.03.2025
    Teil der Instagram Graph API fuer Bild-Posts auf /media - NICHT unterstuetzt bei
    Reels/Stories).

    #Bugfix 'Media ID is not available': Instagram laedt das Bild von image_url ASYNCHRON
    herunter, nachdem der Container erstellt wurde - media_publish schlug bisher fehl, wenn der
    Container noch nicht fertig verarbeitet war (kein Warten vor dem Publish-Aufruf, anders als
    bei publish_instagram_story/publish_instagram_carousel, die _wait_ig_container schon immer
    genutzt haben). Jetzt wird wie dort auf status_code=FINISHED gewartet."""
    token = _user_token()
    data = {"image_url": image_url, "caption": caption or "", "access_token": token}
    if location_id:
        data["location_id"] = location_id
    if alt_text:
        data["alt_text"] = alt_text
    c = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=60, data=data)
    if c.status_code != 200:
        return False, _err(c)
    creation_id = c.json().get("id")
    if not creation_id:
        return False, "Instagram lieferte keine Container-ID."
    ok, err = _wait_ig_container(creation_id, token)
    if not ok:
        return False, err
    pub = requests.post(GRAPH + "/%s/media_publish" % ig_user_id, timeout=60,
                        data={"creation_id": creation_id, "access_token": token})
    if pub.status_code == 200:
        return True, pub.json().get("id", "")
    return False, _err(pub)


def comment_facebook(post_id, page_id, message):
    """Postet einen ersten Kommentar unter einen Facebook-Seitenbeitrag (z.B. mit dem Termin-Link).
    Rueckgabe: (ok, info) - info ist die Kommentar-ID oder die Fehlermeldung."""
    token = _page_token(page_id)
    r = requests.post(GRAPH + "/%s/comments" % post_id, timeout=30,
                      data={"message": message or "", "access_token": token})
    if r.status_code == 200:
        return True, r.json().get("id", "")
    return False, _err(r)


def publish_instagram_story(ig_user_id, image_url):
    """Veroeffentlicht ein Bild als Instagram-Story (verschwindet nach 24 Stunden).
    image_url MUSS oeffentlich erreichbar sein (kein Pi-localhost!). Ideal im Hochformat 9:16.
    KEIN alt_text-Parameter: Meta unterstuetzt das alt_text-Feld laut Doku nur fuer Bild-Posts
    auf /media, ausdruecklich NICHT fuer Stories/Reels (Stand 2026).
    Rueckgabe: (ok, info)."""
    token = _user_token()
    c = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=60,
                      data={"image_url": image_url, "media_type": "STORIES", "access_token": token})
    if c.status_code != 200:
        return False, _err(c)
    creation_id = c.json().get("id")
    if not creation_id:
        return False, "Instagram lieferte keine Story-Container-ID."
    ok, err = _wait_ig_container(creation_id, token)
    if not ok:
        return False, err
    pub = requests.post(GRAPH + "/%s/media_publish" % ig_user_id, timeout=60,
                        data={"creation_id": creation_id, "access_token": token})
    if pub.status_code == 200:
        return True, pub.json().get("id", "")
    return False, _err(pub)


def _wait_ig_container(container_id, token, attempts=12, delay=2):
    """Pollt einen Instagram-Container, bis er fertig verarbeitet ist (status_code=FINISHED).
    Meta laedt das Bild von der image_url asynchron herunter - vor dem Publish muss der
    Container bereit sein, sonst schlaegt media_publish fehl. Liefert (ok, fehler)."""
    for _ in range(attempts):
        r = requests.get(GRAPH + "/%s" % container_id, timeout=30,
                         params={"fields": "status_code", "access_token": token})
        if r.status_code == 200:
            sc = r.json().get("status_code")
            if sc == "FINISHED":
                return True, ""
            if sc == "ERROR":
                return False, "Instagram-Container-Verarbeitung fehlgeschlagen (status ERROR)."
        time.sleep(delay)
    return False, "Instagram-Container nicht rechtzeitig bereit (Timeout)."


def publish_instagram_carousel(ig_user_id, image_urls, caption, location_id=None, alt_texts=None):
    """Veroeffentlicht mehrere Bilder als Karussell auf einem Instagram-Business-Konto.
    Jede image_url MUSS oeffentlich erreichbar sein (kein Pi-localhost!). Ablauf:
    je Bild einen Kind-Container (is_carousel_item=true) -> auf FINISHED warten,
    dann einen CAROUSEL-Container mit allen Kindern -> auf FINISHED warten -> Publish.
    alt_texts = optionale Liste mit einem Alt-Text je Bild (gleiche Reihenfolge/Laenge wie
    image_urls, einzelne Eintraege duerfen None sein). Feld 'alt_text' je Kind-Container.
    Hinweis: wie publish_instagram noch nicht in der Web-Oberflaeche verdrahtet -
    wird scharfgeschaltet, sobald die Bilder oeffentlich erreichbar sind (IG-Anbindung)."""
    if not image_urls:
        return False, "Keine Bild-URLs fuer Karussell uebergeben."
    if alt_texts is not None and len(alt_texts) != len(image_urls):
        return False, "alt_texts muss dieselbe Laenge wie image_urls haben."
    token = _user_token()
    child_ids = []
    for i, url in enumerate(image_urls):
        data = {"image_url": url, "is_carousel_item": "true", "access_token": token}
        alt = alt_texts[i] if alt_texts else None
        if alt:
            data["alt_text"] = alt
        c = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=120, data=data)
        if c.status_code != 200:
            return False, _err(c)
        cid = c.json().get("id")
        if not cid:
            return False, "Kind-Container ohne ID-Rueckgabe."
        ok, err = _wait_ig_container(cid, token)
        if not ok:
            return False, err
        child_ids.append(cid)
    cont_data = {"media_type": "CAROUSEL", "children": ",".join(child_ids),
                 "caption": caption or "", "access_token": token}
    if location_id:
        cont_data["location_id"] = location_id   # Geotag am Eltern-Container des Karussells
    cont = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=120, data=cont_data)
    if cont.status_code != 200:
        return False, _err(cont)
    creation_id = cont.json().get("id")
    ok, err = _wait_ig_container(creation_id, token)
    if not ok:
        return False, err
    pub = requests.post(GRAPH + "/%s/media_publish" % ig_user_id, timeout=60,
                        data={"creation_id": creation_id, "access_token": token})
    if pub.status_code == 200:
        return True, pub.json().get("id", "")
    return False, _err(pub)


def _err(resp):
    try:
        e = resp.json().get("error", {})
        return "HTTP %s: %s" % (resp.status_code, e.get("message") or resp.text[:200])
    except Exception:
        return "HTTP %s: %s" % (resp.status_code, resp.text[:200])


# ---------------------------------------------------------------------------
# Insights / Auswertung - Reichweite und Interaktionen je veroeffentlichtem Beitrag
# ---------------------------------------------------------------------------
def _insight_value(node, metric):
    """Liest einen Insights-Wert aus einem Graph-Node (insights.data[i].values[0].value)."""
    for d in (((node.get("insights") or {}).get("data")) or []):
        if d.get("name") == metric:
            vals = d.get("values") or []
            if vals:
                try:
                    return int(vals[0].get("value") or 0)
                except (TypeError, ValueError):
                    return 0
    return 0


# Facebook-Reichweiten-Metrik: Meta hat 'post_impressions_unique' zum 15.11.2025 deprecatet -> die
# Abfrage wirft seither (#100) 'The value must be a valid insights metric'. Meta ersetzt Reach durch
# das "Media Views/Viewers"-Framework (z.B. post_media_view). Weil Meta die Namen laufend aendert,
# probieren wir die Kandidaten durch und merken uns den ersten gueltigen (Cache je Prozess) - so
# ueberlebt der Abruf kuenftige Umbenennungen ohne Code-Aenderung.
_FB_REACH_CANDIDATES = ["post_impressions_unique", "post_media_view_unique", "post_media_view",
                        "post_views", "post_impressions"]
_fb_reach_metric_cache = None   # None = noch nicht ermittelt, "" = probiert/keiner gueltig


def _fb_reach_metric(post_id, token):
    """Liefert den aktuell gueltigen Facebook-Reichweiten-Metriknamen (einmal ermittelt, dann gecacht).
    Probiert die Kandidaten am gegebenen Post; nutzt den ersten, der KEIN (#100) 'invalid metric' wirft.
    Bei anderem Fehler (z.B. Rate-Limit) wird NICHT gecacht (spaeter erneut versuchen). Rueckgabe:
    Metrikname oder None (dann wird nur die Interaktion, keine Reichweite ermittelt)."""
    global _fb_reach_metric_cache
    if _fb_reach_metric_cache is not None:
        return _fb_reach_metric_cache or None
    for metric in _FB_REACH_CANDIDATES:
        try:
            r = requests.get(GRAPH + "/%s/insights" % post_id, timeout=30,
                             params={"metric": metric, "access_token": token})
        except Exception:
            continue
        if r.status_code == 200:
            _fb_reach_metric_cache = metric
            return metric
        code = None
        try:
            code = (r.json().get("error") or {}).get("code")
        except Exception:
            pass
        if code != 100:
            # kein "Metrik ungueltig" (z.B. (#4) Rate-Limit / Rechteproblem) -> nicht cachen, spaeter erneut
            return None
    _fb_reach_metric_cache = ""   # alle Kandidaten (#100) -> nicht bei jedem Post neu probieren
    return None


def post_insights(kanal, plattform_post_id, page_id, page_token=None):
    """Ruft Reichweite + Interaktionen eines veroeffentlichten Beitrags ab.
    Reichweite ist die Zahl der erreichten Personen (eindeutig). Rueckgabe: (reichweite, interaktionen).
    page_token: optional bereits ermitteltes Seiten-Token (z.B. aus page_token_map()) - dann wird
    KEIN eigener /me/accounts-Aufruf gemacht (spart Anfragen bei Massen-Abrufen). Wirft bei fehlender
    ID oder API-Fehler eine RuntimeError-Ausnahme."""
    if not plattform_post_id:
        raise RuntimeError("Keine Plattform-Post-ID hinterlegt.")
    token = page_token or (_page_token(page_id) if page_id else _user_token())
    if kanal == "instagram":
        # Instagram-Media: Reichweite + Speichern (Insights) sowie Likes/Kommentare (Felder)
        r = requests.get(GRAPH + "/%s" % plattform_post_id, timeout=30, params={
            "fields": "like_count,comments_count,insights.metric(reach,saved)",
            "access_token": token})
        if r.status_code != 200:
            raise RuntimeError(_err(r))
        j = r.json()
        reichweite = _insight_value(j, "reach")
        interaktionen = (int(j.get("like_count") or 0) + int(j.get("comments_count") or 0)
                         + _insight_value(j, "saved"))
        return reichweite, interaktionen
    # Facebook-Seitenbeitrag: Reichweite (aktuell gueltige Metrik) + Reaktionen/Kommentare/Teilen.
    # Reaktionen/Kommentare/Teilen sind KEINE Insights-Metriken und bleiben immer gueltig; die
    # Reichweiten-Metrik wird dynamisch ermittelt (Meta-Deprecation, siehe _fb_reach_metric).
    metric = _fb_reach_metric(plattform_post_id, token)
    fields = "reactions.summary(true),comments.summary(true),shares"
    if metric:
        fields = "insights.metric(%s)," % metric + fields
    r = requests.get(GRAPH + "/%s" % plattform_post_id, timeout=30, params={
        "fields": fields, "access_token": token})
    if r.status_code != 200:
        raise RuntimeError(_err(r))
    j = r.json()
    reichweite = _insight_value(j, metric) if metric else 0
    reaktionen = ((j.get("reactions") or {}).get("summary") or {}).get("total_count") or 0
    kommentare = ((j.get("comments") or {}).get("summary") or {}).get("total_count") or 0
    teilen = (j.get("shares") or {}).get("count") or 0
    return reichweite, int(reaktionen) + int(kommentare) + int(teilen)
