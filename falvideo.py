# -*- coding: utf-8 -*-
"""Reels-MVP (Spur A): animiert ein FERTIGES Motiv (mit eingebrannter Ueberschrift + Logo) zu einem
kurzen Hochkant-Clip via fal.ai (Image-to-Video). Bewusst minimal: EIN Motiv rein -> EIN Clip raus,
kein Multi-Shot (kein "Morphen"), kein separater Schnitt noetig, weil Branding schon im Bild steckt.

Voraussetzungen auf dem Pi:
  - pip install fal-client
  - Secret 'fal_api_key' gesetzt (main.py --set-secret fal_api_key)
Das fal-Modell ist ueber die Einstellung 'fal_video_model' austauschbar (Default: MiniMax Hailuo-02
Standard, guenstig + solide). Der API-Key wird NIE geloggt/ausgegeben.
"""
import os
import logging
import requests

log = logging.getLogger("hilo.falvideo")

# Austauschbarer Default; ueber Einstellung 'fal_video_model' ueberschreibbar.
DEFAULT_MODEL = "fal-ai/minimax/hailuo-02/standard/image-to-video"

# Sanfte, markensichere Bewegung; das Bild (inkl. Text/Logo) soll erhalten bleiben, nur leicht "leben".
DEFAULT_MOTION_PROMPT = (
    "Sanfte, langsame Kamerabewegung mit dezentem Zoom und leichtem Parallax-Effekt. "
    "Natuerliche, ruhige Bewegung in der Szene (z.B. Licht, Blaetter, feine Details). "
    "Bildkomposition, Text und Logo bleiben stabil und unveraendert - keine harten Schnitte, "
    "keine neuen Objekte, keine Verzerrung von Schrift oder Gesichtern."
)


def selftest():
    """Schneller Verbindungs-/Key-Test OHNE Video-Erzeugung: laedt ein winziges Testbild in den
    fal-Speicher hoch (das prueft Key + Erreichbarkeit). Rueckgabe: (ok, meldung)."""
    try:
        from secrets_store import get_secret
    except Exception as ex:
        return False, "secrets_store nicht verfuegbar: %s" % ex
    key = get_secret("fal_api_key", required=False)
    if not key:
        return False, "Kein fal-API-Key hinterlegt. Setzen: python3 main.py --set-secret fal_api_key"
    os.environ["FAL_KEY"] = key
    try:
        import fal_client
    except Exception:
        return False, "Python-Paket 'fal-client' fehlt (pip install fal-client)."
    import tempfile
    try:
        from PIL import Image
        p = os.path.join(tempfile.gettempdir(), "fal_selftest.png")
        Image.new("RGB", (16, 16), (11, 37, 69)).save(p)
    except Exception as ex:
        return False, "Testbild konnte nicht erstellt werden: %s" % ex
    try:
        url = fal_client.upload_file(p)
        return True, "fal-Verbindung + Key OK (Test-Upload erfolgreich)."
    except Exception as ex:
        return False, "fal-Verbindung/Key FEHLGESCHLAGEN: %s" % ex
    finally:
        try:
            os.remove(p)
        except Exception:
            pass


def _model(get_einstellung=None):
    if get_einstellung:
        try:
            m = (get_einstellung("fal_video_model") or "").strip()
            if m:
                return m
        except Exception:
            pass
    return DEFAULT_MODEL


def generate_clip(image_path, out_path, prompt=None, duration=6, get_einstellung=None):
    """Animiert das Bild unter image_path zu einem Clip und speichert ihn als MP4 unter out_path.

    Rueckgabe: (ok: bool, info: str) - info ist out_path bei Erfolg, sonst eine Fehlermeldung.
    Laeuft synchron (das Warten auf fal kann 1-3 Min dauern) - Aufrufer sollte das im Hintergrund tun.
    """
    if not image_path or not os.path.exists(image_path):
        return False, "Eingabebild nicht gefunden: %s" % image_path

    try:
        from secrets_store import get_secret
    except Exception as ex:
        return False, "secrets_store nicht verfuegbar: %s" % ex
    key = get_secret("fal_api_key", required=False) if hasattr(get_secret, "__call__") else None
    if not key:
        return False, ("Kein fal-API-Key hinterlegt. Auf dem Pi setzen: "
                       "python3 main.py --set-secret fal_api_key")

    # fal-Client erwartet den Key in der Umgebung (FAL_KEY). NIE loggen.
    os.environ["FAL_KEY"] = key
    try:
        import fal_client
    except Exception:
        return False, "Python-Paket 'fal-client' fehlt. Auf dem Pi: pip install fal-client"

    model = _model(get_einstellung)
    prompt = prompt or DEFAULT_MOTION_PROMPT
    headers = {"Authorization": "Key %s" % key, "Content-Type": "application/json"}
    import time

    # 1) Bild in den fal-Speicher laden -> oeffentliche URL (fal braucht eine URL, keine lokale Datei).
    try:
        log.warning("fal-Reel: lade Bild hoch ... (%s)", os.path.basename(image_path))
        image_url = fal_client.upload_file(image_path)
    except Exception as ex:
        return False, "fal-Upload fehlgeschlagen: %s" % ex

    # 2) Job ueber die REST-Queue einreichen (volle Kontrolle ueber Timeout/Logging statt blockierendem get()).
    submit_url = "https://queue.fal.run/%s" % model
    args = {"prompt": prompt, "image_url": image_url, "duration": str(duration)}
    try:
        log.warning("fal-Reel: submit an %s", model)
        sr = requests.post(submit_url, headers=headers, json=args, timeout=60)
        if sr.status_code not in (200, 201):
            return False, "fal-Submit fehlgeschlagen (HTTP %s): %s" % (sr.status_code, sr.text[:300])
        sj = sr.json()
        status_url = sj.get("status_url")
        response_url = sj.get("response_url")
        req_id = sj.get("request_id")
        if not status_url or not response_url:
            return False, "fal-Submit ohne status_url/response_url: %s" % str(sj)[:300]
        log.warning("fal-Reel: request_id=%s, warte auf Fertigstellung ...", req_id)
    except Exception as ex:
        return False, "fal-Submit-Fehler (%s): %s" % (model, ex)

    # 3) Pollen mit HARTEM Timeout (max ~5 Min) - kein ewiges Haengen mehr.
    deadline = time.time() + 300
    last = None
    try:
        while time.time() < deadline:
            st = requests.get(status_url, headers=headers, timeout=30)
            if st.status_code != 200:
                return False, "fal-Status-Abfrage HTTP %s: %s" % (st.status_code, st.text[:200])
            stj = st.json()
            last = stj.get("status")
            if last == "COMPLETED":
                break
            if last in ("FAILED", "ERROR", "CANCELLED"):
                return False, "fal-Job %s: %s" % (last, str(stj)[:300])
            time.sleep(5)
        else:
            return False, ("fal-Timeout nach 5 Min (Status zuletzt: %s, Modell %s). Evtl. Modell-ID/"
                           "Parameter pruefen." % (last, model))
    except Exception as ex:
        return False, "fal-Poll-Fehler: %s" % ex

    # 4) Ergebnis holen -> Video-URL.
    try:
        rr = requests.get(response_url, headers=headers, timeout=60)
        if rr.status_code != 200:
            return False, "fal-Ergebnis HTTP %s: %s" % (rr.status_code, rr.text[:200])
        result = rr.json()
    except Exception as ex:
        return False, "fal-Ergebnis-Fehler: %s" % ex
    video_url = None
    v = result.get("video") if isinstance(result, dict) else None
    if isinstance(v, dict):
        video_url = v.get("url")
    elif isinstance(v, str):
        video_url = v
    if not video_url and isinstance(result, dict):
        vids = result.get("videos")
        if isinstance(vids, list) and vids:
            first = vids[0]
            video_url = first.get("url") if isinstance(first, dict) else first
    if not video_url:
        return False, "fal-Antwort ohne Video-URL (Modell %s): %s" % (model, str(result)[:300])
    log.warning("fal-Reel: Video fertig, lade herunter ...")

    # 4) MP4 herunterladen.
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        r = requests.get(video_url, timeout=180)
        if r.status_code != 200:
            return False, "Download des Clips fehlgeschlagen (HTTP %s)." % r.status_code
        with open(out_path, "wb") as fh:
            fh.write(r.content)
    except Exception as ex:
        return False, "Clip-Download fehlgeschlagen: %s" % ex

    log.info("fal-Reel erzeugt: %s (Modell %s)", out_path, model)
    return True, out_path
