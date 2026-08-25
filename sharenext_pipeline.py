#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ShareNext Pipeline - End-to-End Premium Mode Bildgenerierung.

Komplette Pipeline von Message Brief bis fertiges Bild:
1. Message Brief Generator
2. Creative Director (4 Routen)
3. Concept Jury (Gewinner wählen)
4. Art Director Board
5. Image Producer (gpt-image-2)
6. Visual QA (Gate A)

Teil von Issue #7: ShareNext MVP - Integration
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from message_brief import MessageBrief, generate_message_brief, generate_headline
from creative_director import CreativeTerritories, generate_creative_routes
from concept_jury import ConceptJuryVerdict, evaluate_routes
from art_director import ArtDirectionBoard, create_art_direction_board
from creative_memory import load_recent_heroes, remember_hero
from image_producer import ImageProductionBrief, produce_image
from visual_qa import VisualQAVerdict, check_raw_image

log = logging.getLogger("hilo.sharenext")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PIPELINE RESULT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ShareNextResult:
    """Result der ShareNext Premium Pipeline."""

    def __init__(
        self,
        # Input
        stream: str,
        thema: str,
        text: str,
        kanal: str,
        # Pipeline Artifacts
        message_brief: MessageBrief,
        creative_territories: CreativeTerritories,
        concept_verdict: ConceptJuryVerdict,
        art_board: ArtDirectionBoard,
        production_brief: ImageProductionBrief,
        qa_verdict: VisualQAVerdict,
        # Output
        image: Image.Image,
        approved: bool
    ):
        self.stream = stream
        self.thema = thema
        self.text = text
        self.kanal = kanal

        self.message_brief = message_brief
        self.creative_territories = creative_territories
        self.concept_verdict = concept_verdict
        self.art_board = art_board
        self.production_brief = production_brief
        self.qa_verdict = qa_verdict

        self.image = image
        self.approved = approved

    @property
    def winning_route(self):
        """Gewinnende kreative Route."""
        route_map = {
            1: self.creative_territories.route_1_emotionale_szene,
            2: self.creative_territories.route_2_metapher,
            3: self.creative_territories.route_3_objekt,
            4: self.creative_territories.route_4_kontrast,
            5: self.creative_territories.route_5_unkonventionell,
        }
        return route_map[self.concept_verdict.winning_route]

    def __repr__(self):
        status = "✓ APPROVED" if self.approved else "⚠ NEEDS REVIEW"
        return (
            f"ShareNextResult(\n"
            f"  Thema: {self.thema}\n"
            f"  Route: {self.concept_verdict.winning_titel}\n"
            f"  QA Score: {self.qa_verdict.gesamtscore:.1f}/10\n"
            f"  Status: {status}\n"
            f")"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN PIPELINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run_sharenext_pipeline(
    stream: str,
    thema: str,
    text: str,
    kanal: str,
    headline: str = "",
    size: str = "1024x1024",
    quality: str = "medium",
    output_path: Optional[Path] = None
) -> ShareNextResult:
    """ShareNext Premium Pipeline - End-to-End Bildgenerierung.

    Führt die komplette 6-Stufen-Pipeline aus:
    1. Message Brief Generator (KI)
    2. Creative Director - 4 Routen (KI)
    3. Concept Jury - Gewinner wählen (KI)
    4. Art Director Board (KI)
    5. Image Producer - OpenAI Image Model (KI) - MIT freigegebener headline!
    6. Visual QA - Gate A Check (KI)

    Args:
        stream: Content-Stream ('radar', 'fristen', 'anlass', 'wissen')
        thema: Thema/Überschrift des Posts
        text: Post-Text
        kanal: Social-Media-Kanal ('Facebook', 'Instagram', 'LinkedIn', 'Google Business')
        headline: Freigegebene Überschrift vom Copywriter (Campaign Plan) - wird INS Bild geschrieben!
        size: Bildgröße (default: 1024x1024)
        quality: Qualität ('low', 'medium', 'high', 'auto') - default: 'medium'
        output_path: Optional Speicherpfad für Bild

    Returns:
        ShareNextResult: Komplett Result mit allen Artifacts + Bild

    Raises:
        Exception: Bei Fehler in irgendeiner Pipeline-Stufe

    Example:
        >>> result = run_sharenext_pipeline(
        ...     stream="fristen",
        ...     thema="Steuerfrist 31.12.",
        ...     text="Jetzt Termin sichern!",
        ...     kanal="Facebook"
        ... )
        >>> print(result)
        >>> result.image.show()
    """
    log.info(f"🚀 ShareNext Pipeline START: {thema}")

    # ─────────────────────────────────────────────────────────────────────────
    # STUFE 1: Message Brief
    # ─────────────────────────────────────────────────────────────────────────
    log.info("📋 Stufe 1/6: Message Brief Generator")
    message_brief = generate_message_brief(stream, thema, text, kanal)
    log.info(f"   ✓ Zielgruppe: {message_brief.zielgruppe}")

    # Headline-Fallback: Ohne Überschrift liefe der Image Producer im Modus 'no_text' und
    # erzeugte ein Bild ganz ohne Text. Eine freigegebene Überschrift hat immer Vorrang.
    if not headline or not headline.strip():
        headline = generate_headline(message_brief, text=text)
        log.info(f"   ℹ Überschrift selbst generiert (keine freigegebene übergeben)")
    else:
        headline = headline.strip()

    # ─────────────────────────────────────────────────────────────────────────
    # STUFE 2: Creative Director - 4 Routen
    # ─────────────────────────────────────────────────────────────────────────
    log.info("🎨 Stufe 2/6: Creative Director (4 Routen)")
    creative_territories = generate_creative_routes(message_brief)
    log.info("   ✓ 4 kreative Routen generiert")

    # ─────────────────────────────────────────────────────────────────────────
    # STUFE 3: Concept Jury - Gewinner wählen
    # ─────────────────────────────────────────────────────────────────────────
    log.info("🏆 Stufe 3/6: Concept Jury")
    # Serien-Vielfalt: zuletzt genutzte Hero-Kategorien laden und der Jury (NICHT dem Creative
    # Director) fuer die Novelty-Abwertung mitgeben.
    recent_heroes = load_recent_heroes()
    if recent_heroes:
        log.info(f"   ℹ Creative Memory (zuletzt): {', '.join(recent_heroes)}")
    concept_verdict = evaluate_routes(message_brief, creative_territories, recent_heroes=recent_heroes)
    log.info(f"   ✓ Gewinner: Route {concept_verdict.winning_route} - {concept_verdict.winning_titel}")
    log.info(f"   Score: {concept_verdict.winning_score:.1f}/10")

    # Gewinnende Route extrahieren
    route_map = {
        1: creative_territories.route_1_emotionale_szene,
        2: creative_territories.route_2_metapher,
        3: creative_territories.route_3_objekt,
        4: creative_territories.route_4_kontrast,
        5: creative_territories.route_5_unkonventionell,
    }
    winning_route = route_map[concept_verdict.winning_route]

    # Gewinner-Hero-Kategorie in die Creative Memory schreiben (steuert die naechste Novelty-Pruefung).
    try:
        remember_hero(getattr(winning_route, "hero_kurz", ""))
        log.info(f"   ✓ Creative Memory aktualisiert: {getattr(winning_route, 'hero_kurz', '')}")
    except Exception as e:
        log.warning(f"   Creative Memory-Update uebersprungen: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # STUFE 4: Art Director Board
    # ─────────────────────────────────────────────────────────────────────────
    log.info("🎬 Stufe 4/6: Art Director Board")
    art_board = create_art_direction_board(message_brief, winning_route)
    log.info(f"   ✓ Focal Point: {art_board.focal_point}")
    log.info(f"   ✓ Farben: {', '.join(art_board.dominante_farben[:3])}")

    # ─────────────────────────────────────────────────────────────────────────
    # STUFE 5: Image Producer - gpt-image-2
    # ─────────────────────────────────────────────────────────────────────────
    log.info(f"🖼️  Stufe 5/6: Image Producer (gpt-image-2 {size})")
    log.info(f"   Headline: '{headline}'" if headline else "   (Kein Text im Bild)")
    image, production_brief = produce_image(
        message_brief,
        winning_route,
        art_board,
        headline=headline,
        size=size,
        quality=quality,
        output_path=output_path
    )
    log.info(f"   ✓ Bild generiert: {image.size[0]}x{image.size[1]} px")
    log.info(f"   ✓ Alt-Text: {production_brief.alt_text or '(nicht generiert)'}")

    # ─────────────────────────────────────────────────────────────────────────
    # STUFE 6: Visual QA - Gate A
    # ─────────────────────────────────────────────────────────────────────────
    log.info("✅ Stufe 6/6: Visual QA (Gate A)")
    qa_verdict = check_raw_image(image, message_brief, winning_route, art_board, headline=headline)
    log.info(f"   ✓ QA Score: {qa_verdict.gesamtscore:.1f}/10")
    log.info(f"   {'✓ FREIGEGEBEN' if qa_verdict.freigegeben else '⚠ ABGELEHNT'}")

    # ─────────────────────────────────────────────────────────────────────────
    # RESULT
    # ─────────────────────────────────────────────────────────────────────────
    result = ShareNextResult(
        stream=stream,
        thema=thema,
        text=text,
        kanal=kanal,
        message_brief=message_brief,
        creative_territories=creative_territories,
        concept_verdict=concept_verdict,
        art_board=art_board,
        production_brief=production_brief,
        qa_verdict=qa_verdict,
        image=image,
        approved=qa_verdict.freigegeben
    )

    log.info(f"🎉 ShareNext Pipeline COMPLETE!")
    log.info(f"   Approved: {'Ja' if result.approved else 'Nein (Review empfohlen)'}")

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s"
    )

    print("="*80)
    print("SHARENEXT PIPELINE - END-TO-END TEST")
    print("="*80)

    # Test Input
    stream = "fristen"
    thema = "Wichtige Steuerfrist endet am 31. Dezember"
    text = "Jetzt Termin sichern und Verspätungszuschlag vermeiden!"
    kanal = "Facebook"

    print(f"\nInput:")
    print(f"  Stream: {stream}")
    print(f"  Thema: {thema}")
    print(f"  Kanal: {kanal}\n")

    try:
        # Run Pipeline
        result = run_sharenext_pipeline(
            stream=stream,
            thema=thema,
            text=text,
            kanal=kanal,
            output_path=Path("/tmp/sharenext-result.png")
        )

        # Show Result
        print("\n" + "="*80)
        print("RESULT")
        print("="*80)
        print(result)
        print("\n" + "="*80)
        print("DETAILS")
        print("="*80)
        print(f"\nMessage Brief:")
        print(f"  Kernaussage: {result.message_brief.kernaussage}")
        print(f"  Zielgruppe: {result.message_brief.zielgruppe}")
        print(f"\nGewinnende Route:")
        print(f"  {result.winning_route.typ}: {result.winning_route.titel}")
        print(f"\nArt Direction:")
        print(f"  Focal Point: {result.art_board.focal_point}")
        print(f"  Licht: {result.art_board.licht_stimmung}")
        print(f"  Farben: {', '.join(result.art_board.dominante_farben)}")
        print(f"\nVisual QA:")
        print(f"  Score: {result.qa_verdict.gesamtscore:.1f}/10")
        print(f"  Freigegeben: {'Ja' if result.qa_verdict.freigegeben else 'Nein'}")
        print(f"  Stärken: {result.qa_verdict.staerken}")
        print(f"  Schwächen: {result.qa_verdict.schwaechen}")
        print(f"\nBild gespeichert: /tmp/sharenext-result.png")
        print(f"\nAlt-Text: {result.production_brief.alt_text or '(nicht generiert)'}")
        print("="*80)

    except Exception as e:
        print(f"\n❌ Fehler: {e}")
        import traceback
        traceback.print_exc()
