# -*- coding: utf-8 -*-
"""Sichere Secret-Beschaffung: zuerst Umgebungsvariable, sonst geschuetzte secrets.json.
Robust gegen fehlerhafte secrets.json (crasht nicht). KEINE Klartext-Secrets im Code/Repo."""
import json, logging, os
from config import SECRETS_FILE

log = logging.getLogger("hilo.secrets")

_ENV_MAP = {
    "anthropic_api_key":     "HILO_ANTHROPIC_API_KEY",
    "openai_api_key":        "HILO_OPENAI_API_KEY",
    "ideogram_api_key":      "HILO_IDEOGRAM_API_KEY",
    "linkedin_access_token": "HILO_LINKEDIN_ACCESS_TOKEN",
    "linkedin_org_id":       "HILO_LINKEDIN_ORG_ID",
}
_cache = None

def _read():
    if not os.path.exists(SECRETS_FILE):
        return {}
    try:
        with open(SECRETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as ex:
        log.warning("secrets.json ist fehlerhaft (%s) - wird ignoriert. "
                    "Neu setzen mit: python main.py --set-secret NAME", ex)
        return {}

def _load_file():
    global _cache
    if _cache is None:
        _cache = _read()
    return _cache

def get_secret(name, required=False):
    env = _ENV_MAP.get(name)
    val = (os.environ.get(env) if env else None) or _load_file().get(name)
    if required and not val:
        raise RuntimeError("Secret '%s' fehlt (Umgebungsvariable %s oder %s)." % (name, env, SECRETS_FILE))
    return val

def set_secret(name, value):
    """Schreibt ein Geheimnis valide nach secrets.json (Datei wird ggf. neu angelegt)."""
    global _cache
    data = _read()
    data[name] = value
    with open(SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(SECRETS_FILE, 0o600)
    except Exception:
        pass
    _cache = None
