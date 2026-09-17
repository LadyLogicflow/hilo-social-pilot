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
    try:
        # 1) Bild in den fal-Speicher laden -> oeffentliche URL (fal braucht eine URL, keine lokale Datei).
        image_url = fal_client.upload_file(image_path)
        # 2) Job einreichen (Image-to-Video). duration als String - so erwarten es die gaengigen Modelle.
        args = {"prompt": prompt, "image_url": image_url, "duration": str(duration)}
        handler = fal_client.submit(model, arguments=args)
        result = handler.get()   # blockiert bis fertig (fal-Queue mit Auto-Retry)
    except Exception as ex:
        return False, "fal-Video fehlgeschlagen (%s): %s" % (model, ex)

    # 3) Video-URL aus dem Ergebnis holen (fal liefert i.d.R. {"video": {"url": ...}}).
    video_url = None
    try:
        v = result.get("video") if isinstance(result, dict) else None
        if isinstance(v, dict):
            video_url = v.get("url")
        elif isinstance(v, str):
            video_url = v
        if not video_url and isinstance(result, dict):
            # Fallback: manche Modelle liefern eine Liste unter 'videos'
            vids = result.get("videos")
            if isinstance(vids, list) and vids:
                first = vids[0]
                video_url = first.get("url") if isinstance(first, dict) else first
    except Exception as ex:
        return False, "fal-Antwort ohne Video-URL: %s" % ex
    if not video_url:
        return False, "fal-Antwort ohne Video-URL (Modell %s)." % model

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
