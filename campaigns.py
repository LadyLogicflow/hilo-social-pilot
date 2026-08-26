# -*- coding: utf-8 -*-
"""Registry der Sonder-Kampagnen fuer die kampagne-Parametrisierung der ShareNext-Pipeline.
'steuer' (Default) = kein Sonder-Prompt (bestehendes Verhalten). Andere Kampagnen liefern ein
Prompt-Modul mit einheitlichem Interface (SYSTEM, build_prompt, MESSAGE_BRIEF_SYSTEM, message_brief_user,
BILD_DIREKTIVE, BEGRIFFE_TABU, NORMALISIERUNG, optional CREATIVE_DIREKTIVE).
"""


def get(kampagne):
    """Liefert das Prompt-Modul der Kampagne oder None (fuer 'steuer'/unbekannt = Standard-Pipeline)."""
    if kampagne == "recruiting":
        import recruiting_prompts
        return recruiting_prompts
    if kampagne == "kanalwerbung":
        import kanalwerbung_prompts
        return kanalwerbung_prompts
    return None
