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
import time
import logging
import requests
from secrets_store import get_secret, set_secret

log = logging.getLogger("hilo.publish")

GRAPH = "https://graph.facebook.com/v21.0"


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
    Rueckgabe: Liste von Dicts {id, name, ig_id, ig_username}. OHNE Tokens."""
    r = requests.get(GRAPH + "/me/accounts", timeout=30, params={
        "fields": "id,name,instagram_business_account{id,username}",
        "limit": 100,
        "access_token": _user_token(),
    })
    r.raise_for_status()
    out = []
    for p in r.json().get("data", []):
        ig = p.get("instagram_business_account") or {}
        out.append({
            "id": p["id"], "name": p.get("name", ""),
            "ig_id": ig.get("id"), "ig_username": ig.get("username"),
        })
    return out


def _page_token(page_id):
    """Holt das Seiten-Token fuer eine bestimmte Seite (intern, nie ausgeben)."""
    r = requests.get(GRAPH + "/me/accounts", timeout=30, params={
        "fields": "id,access_token", "limit": 100, "access_token": _user_token(),
    })
    r.raise_for_status()
    for p in r.json().get("data", []):
        if p["id"] == str(page_id):
            return p.get("access_token")
    raise RuntimeError("Keine Berechtigung fuer Seite %s (nicht in /me/accounts)." % page_id)


# ---------------------------------------------------------------------------
# Facebook: Foto-Beitrag
# ---------------------------------------------------------------------------
def publish_facebook(page_id, image_path, caption):
    """Veroeffentlicht ein Foto mit Begleittext auf einer Facebook-Seite.
    Rueckgabe: (ok, info) - info ist die Post-/Foto-ID oder die Fehlermeldung."""
    token = _page_token(page_id)
    with open(image_path, "rb") as fh:
        r = requests.post(GRAPH + "/%s/photos" % page_id, timeout=120,
                          data={"message": caption or "", "access_token": token},
                          files={"source": fh})
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


def publish_facebook_carousel(page_id, image_paths, caption):
    """Veroeffentlicht mehrere Bilder als Karussell-Beitrag auf einer Facebook-Seite.
    Jedes Foto wird zunaechst unveroeffentlicht (published=false) hochgeladen, danach
    werden alle Foto-IDs in einem Feed-Beitrag zusammengefuehrt (attached_media).
    Scheitert ein Schritt, werden bereits hochgeladene Fotos wieder geloescht."""
    if not image_paths:
        return False, "Keine Bilder fuer Karussell uebergeben."
    token = _page_token(page_id)
    media_ids = []
    for path in image_paths:
        with open(path, "rb") as fh:
            r = requests.post(GRAPH + "/%s/photos" % page_id, timeout=120,
                              data={"published": "false", "access_token": token},
                              files={"source": fh})
        if r.status_code != 200:
            _delete_fb_photos(media_ids, token)
            return False, _err(r)
        mid = r.json().get("id")
        if not mid:
            _delete_fb_photos(media_ids, token)
            return False, "Foto-Upload ohne ID-Rueckgabe."
        media_ids.append(mid)
    data = {"message": caption or "", "access_token": token}
    for i, mid in enumerate(media_ids):
        data["attached_media[%d]" % i] = json.dumps({"media_fbid": mid})
    r = requests.post(GRAPH + "/%s/feed" % page_id, timeout=120, data=data)
    if r.status_code == 200:
        return True, (r.json().get("id") or "")
    _delete_fb_photos(media_ids, token)   # Feed-Beitrag fehlgeschlagen -> Fotos nicht verwaisen lassen
    return False, _err(r)


# ---------------------------------------------------------------------------
# Instagram: zweistufige Veroeffentlichung (benoetigt oeffentliche Bild-URL)
# ---------------------------------------------------------------------------
def publish_instagram(ig_user_id, image_url, caption):
    """Veroeffentlicht ein Bild auf einem Instagram-Business-Konto.
    image_url MUSS oeffentlich erreichbar sein (kein Pi-localhost!)."""
    token = _user_token()
    c = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=60,
                      data={"image_url": image_url, "caption": caption or "", "access_token": token})
    if c.status_code != 200:
        return False, _err(c)
    creation_id = c.json().get("id")
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


def publish_instagram_carousel(ig_user_id, image_urls, caption):
    """Veroeffentlicht mehrere Bilder als Karussell auf einem Instagram-Business-Konto.
    Jede image_url MUSS oeffentlich erreichbar sein (kein Pi-localhost!). Ablauf:
    je Bild einen Kind-Container (is_carousel_item=true) -> auf FINISHED warten,
    dann einen CAROUSEL-Container mit allen Kindern -> auf FINISHED warten -> Publish.
    Hinweis: wie publish_instagram noch nicht in der Web-Oberflaeche verdrahtet -
    wird scharfgeschaltet, sobald die Bilder oeffentlich erreichbar sind (IG-Anbindung)."""
    if not image_urls:
        return False, "Keine Bild-URLs fuer Karussell uebergeben."
    token = _user_token()
    child_ids = []
    for url in image_urls:
        c = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=120,
                          data={"image_url": url, "is_carousel_item": "true", "access_token": token})
        if c.status_code != 200:
            return False, _err(c)
        cid = c.json().get("id")
        if not cid:
            return False, "Kind-Container ohne ID-Rueckgabe."
        ok, err = _wait_ig_container(cid, token)
        if not ok:
            return False, err
        child_ids.append(cid)
    cont = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=120,
                         data={"media_type": "CAROUSEL", "children": ",".join(child_ids),
                               "caption": caption or "", "access_token": token})
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


def post_insights(kanal, plattform_post_id, page_id):
    """Ruft Reichweite + Interaktionen eines veroeffentlichten Beitrags ab.
    Reichweite ist die Zahl der erreichten Personen (eindeutig). Rueckgabe: (reichweite, interaktionen).
    Wirft bei fehlender ID oder API-Fehler eine RuntimeError-Ausnahme."""
    if not plattform_post_id:
        raise RuntimeError("Keine Plattform-Post-ID hinterlegt.")
    token = _page_token(page_id) if page_id else _user_token()
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
    # Facebook-Seitenbeitrag: eindeutige Reichweite (Insight) + Reaktionen/Kommentare/Teilen
    r = requests.get(GRAPH + "/%s" % plattform_post_id, timeout=30, params={
        "fields": "insights.metric(post_impressions_unique),reactions.summary(true),"
                  "comments.summary(true),shares",
        "access_token": token})
    if r.status_code != 200:
        raise RuntimeError(_err(r))
    j = r.json()
    reichweite = _insight_value(j, "post_impressions_unique")
    reaktionen = ((j.get("reactions") or {}).get("summary") or {}).get("total_count") or 0
    kommentare = ((j.get("comments") or {}).get("summary") or {}).get("total_count") or 0
    teilen = (j.get("shares") or {}).get("count") or 0
    return reichweite, int(reaktionen) + int(kommentare) + int(teilen)
