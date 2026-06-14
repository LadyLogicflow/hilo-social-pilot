# -*- coding: utf-8 -*-
"""Laedt ein Bild per SFTP auf den Webspace und liefert die OEFFENTLICHE URL zurueck.
Wird fuer die Instagram-Veroeffentlichung gebraucht: Instagram holt das Bild ueber eine
oeffentlich erreichbare URL (der Pi selbst ist privat). Zugangsdaten kommen ausschliesslich
aus dem Secret-Store (secrets.json/ENV), NIE aus dem Code/Repo.

Benoetigte Secrets:
  ionos_sftp_host          - SFTP-Server (z.B. ...1and1-data.host)
  ionos_sftp_user          - SFTP-Benutzer
  ionos_sftp_password      - SFTP-Passwort
  ionos_public_base_url    - oeffentliche Basis-URL des Zielordners (z.B. https://.../bilder)
  ionos_sftp_dir           - (optional) Zielordner auf dem Server, Default = Stammverzeichnis
  ionos_sftp_port          - (optional) Port, Default 22
"""
import os, logging, posixpath
from secrets_store import get_secret

log = logging.getLogger("hilo.uploader")


def _cfg():
    host = get_secret("ionos_sftp_host")
    user = get_secret("ionos_sftp_user")
    pw = get_secret("ionos_sftp_password")
    base = (get_secret("ionos_public_base_url") or "").rstrip("/")
    remote_dir = (get_secret("ionos_sftp_dir") or "").strip().strip("/")
    try:
        port = int(get_secret("ionos_sftp_port") or 22)
    except (TypeError, ValueError):
        port = 22
    return host, user, pw, base, remote_dir, port


def configured():
    """True, wenn die Pflicht-Secrets fuer den Upload gesetzt sind."""
    host, user, pw, base, _, _ = _cfg()
    return bool(host and user and pw and base)


def _ensure_dirs(sftp, remote_dir):
    """Legt den Zielordner (ggf. verschachtelt) an, falls er fehlt (best effort)."""
    cur = ""
    for part in [p for p in remote_dir.split("/") if p]:
        cur = cur + "/" + part if cur else part
        try:
            sftp.stat(cur)
        except IOError:
            try:
                sftp.mkdir(cur)
            except Exception:
                pass


def upload(local_path, remote_name=None):
    """Laedt local_path per SFTP hoch und gibt die oeffentliche URL zurueck.
    remote_name = Zieldateiname (Default: Basisname der lokalen Datei)."""
    import paramiko  # lazy import (nur noetig, wenn IG-Upload genutzt wird)
    host, user, pw, base, remote_dir, port = _cfg()
    if not (host and user and pw and base):
        raise RuntimeError("Upload nicht konfiguriert: ionos_sftp_host/user/password und "
                           "ionos_public_base_url muessen gesetzt sein.")
    if not os.path.exists(local_path):
        raise FileNotFoundError(local_path)
    remote_name = remote_name or os.path.basename(local_path)
    remote_name = posixpath.basename(remote_name)   # Pfad-Anteile entfernen (kein '../', kein Unterordner)
    remote_path = posixpath.join(remote_dir, remote_name) if remote_dir else remote_name

    transport = paramiko.Transport((host, port))
    try:
        transport.connect(username=user, password=pw)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            if remote_dir:
                _ensure_dirs(sftp, remote_dir)
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()
    finally:
        transport.close()

    url = base + "/" + remote_name
    log.info("Bild hochgeladen -> %s", url)
    return url
