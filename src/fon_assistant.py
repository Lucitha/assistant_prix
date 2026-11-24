"""Compréhension d'une demande libre en français ou en fongbé (WhatsApp, appel).

Repérage par mots-clés, sans IA. Les mots fongbé (gbadé, takin…) viennent
d'une première liste de l'équipe et doivent être validés par un locuteur fon
avant le pilote : voir la piste J'aime Ma Langue (jaimemalangue.bj).

Aucune phrase n'est générée en fon ici : une réponse en fon ne sera ajoutée
qu'une fois les phrases enregistrées ou validées par un locuteur.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# mot repéré -> code produit de data/produits.csv
PRODUCT_ALIASES: dict[str, str] = {
    "mais": "mais",
    "gbade": "mais",  # fongbé, à valider
    "piment": "piment",
    "takin": "piment",  # fongbé, à valider
}

# mot repéré -> unité de prix.UNITES
UNIT_ALIASES: dict[str, str] = {
    "sac": "sac",
    "sacs": "sac",
    "bassine": "bassine",
    "bassines": "bassine",
    "bol": "bol",
    "bols": "bol",
    "kilo": "kg",
    "kilos": "kg",
    "kg": "kg",
}

# Menu à touches de repli (appel)
DTMF_MENU: dict[str, str] = {"1": "mais", "2": "piment"}


@dataclass(frozen=True)
class ParsedQuery:
    """Demande structurée : produit (ou None), unité et localité."""

    product: str | None
    unit: str
    localite: str
    needs_dtmf_fallback: bool


def normalize_text(text: str) -> str:
    """Minuscules, sans accents ni espaces superflus : 'Gbadé  SAC' -> 'gbade sac'."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return " ".join(sans_accents.lower().split())


def _premier_alias(mots: list[str], aliases: dict[str, str]) -> str | None:
    """Premier mot de la demande présent dans le dictionnaire d'alias."""
    for mot in mots:
        if mot in aliases:
            return aliases[mot]
    return None


def parse_farmer_request(
    raw_text: str,
    dtmf_digit: str | None = None,
    localites: list[str] | None = None,
) -> ParsedQuery:
    """Extrait produit, unité et localité d'une demande, ou d'une touche du clavier."""
    localites = localites or ["Savalou"]
    if dtmf_digit and dtmf_digit.strip() in DTMF_MENU:
        return ParsedQuery(DTMF_MENU[dtmf_digit.strip()], "sac", localites[0], False)

    mots = normalize_text(raw_text).replace(",", " ").replace(".", " ").split()
    produit = _premier_alias(mots, PRODUCT_ALIASES)
    unite = _premier_alias(mots, UNIT_ALIASES) or "sac"
    localite = next(
        (loc for loc in localites if normalize_text(loc) in mots), localites[0]
    )
    return ParsedQuery(produit, unite, localite, produit is None)


def build_dtmf_fallback_prompt() -> str:
    """Menu à touches proposé quand la demande n'est pas comprise."""
    return "Je n'ai pas compris le produit. " "Tapez 1 pour le maïs, 2 pour le piment."


def build_confirmation_prompt(product_name: str, unit: str, localite: str) -> str:
    """Reformulation avant l'annonce des prix (règle du cadrage)."""
    return f"{product_name}, au {unit}, autour de {localite} : c'est bien cela ?"
