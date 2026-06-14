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
def publish_facebook_carousel(page_id, image_paths, caption):
    """Veroeffentlicht mehrere Bilder als Karussell-Beitrag auf einer Facebook-Seite.
    Jedes Foto wird zunaechst unveroeffentlicht (published=false) hochgeladen, danach
    werden alle Foto-IDs in einem Feed-Beitrag zusammengefuehrt (attached_media)."""
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
            return False, _err(r)
        mid = r.json().get("id")
        if not mid:
            return False, "Foto-Upload ohne ID-Rueckgabe."
        media_ids.append(mid)
    data = {"message": caption or "", "access_token": token}
    for i, mid in enumerate(media_ids):
        data["attached_media[%d]" % i] = '{"media_fbid":"%s"}' % mid
    r = requests.post(GRAPH + "/%s/feed" % page_id, timeout=120, data=data)
    if r.status_code == 200:
        return True, (r.json().get("id") or "")
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


def publish_instagram_carousel(ig_user_id, image_urls, caption):
    """Veroeffentlicht mehrere Bilder als Karussell auf einem Instagram-Business-Konto.
    Jede image_url MUSS oeffentlich erreichbar sein (kein Pi-localhost!). Ablauf:
    je Bild einen Kind-Container (is_carousel_item=true), dann einen CAROUSEL-Container
    mit allen Kindern, danach Publish."""
    if not image_urls:
        return False, "Keine Bild-URLs fuer Karussell uebergeben."
    token = _user_token()
    child_ids = []
    for url in image_urls:
        c = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=60,
                          data={"image_url": url, "is_carousel_item": "true", "access_token": token})
        if c.status_code != 200:
            return False, _err(c)
        cid = c.json().get("id")
        if not cid:
            return False, "Kind-Container ohne ID-Rueckgabe."
        child_ids.append(cid)
    cont = requests.post(GRAPH + "/%s/media" % ig_user_id, timeout=60,
                         data={"media_type": "CAROUSEL", "children": ",".join(child_ids),
                               "caption": caption or "", "access_token": token})
    if cont.status_code != 200:
        return False, _err(cont)
    creation_id = cont.json().get("id")
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
