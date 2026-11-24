"""Canaux WhatsApp et appel vocal, en SIMULATION pour la démo.

État réel (novembre 2026) :
- USSD : branché sur Africa's Talking (voir src/ussd.py et la route /ussd).
- Appel : le sandbox Africa's Talking ne gère pas la voix ; il faut un numéro
  de production. Ici, la route renvoie le texte que le serveur vocal lirait.
- WhatsApp : via Africa's Talking c'est payant (mise en place + abonnement) ;
  l'API Cloud de Meta est la piste gratuite pour le pilote. Ici, la route
  renvoie le message qui serait envoyé.

Les deux canaux utilisent le même moteur que l'USSD (src/prix.py) : les
mêmes données donnent les mêmes chiffres, quel que soit le canal.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src import prix
from src.fon_assistant import (
    build_confirmation_prompt,
    build_dtmf_fallback_prompt,
    parse_farmer_request,
)

MOIS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def date_parlee(iso: str) -> str:
    """'2026-11-21' -> '21 novembre' (pour la lecture à voix haute)."""
    jour = date.fromisoformat(iso)
    return f"{jour.day} {MOIS[jour.month - 1]}"


def fcfa(montant: float) -> str:
    """25000 -> '25 000 FCFA'."""
    return f"{round(montant):,}".replace(",", " ") + " FCFA"


def _evaluer(
    texte: str,
    dtmf_digit: str | None,
    offre_unitaire: int | None,
    quantite: float,
    aujourd_hui: date | None,
) -> tuple[Any, dict[str, Any] | None]:
    """Comprend la demande puis calcule ; résultat None si le produit est inconnu."""
    demande = parse_farmer_request(texte, dtmf_digit, prix.localites())
    if demande.product is None:
        return demande, None
    resultat = prix.resultat_en_json(
        demande.product,
        demande.unit,
        demande.localite,
        offre_unitaire,
        quantite,
        aujourd_hui,
    )
    return demande, resultat


def _phrase_offre(resultat: dict[str, Any]) -> str:
    """Comparaison entre le meilleur net et l'offre de l'acheteur."""
    meilleur = resultat["resultats"][0]
    ecart = meilleur.get("ecart_avec_offre_total")
    if ecart is None:
        return ""
    if ecart > 0:
        texte = (
            f"L'offre est inférieure de {fcfa(ecart)} au net à {meilleur['marche']}."
        )
    else:
        texte = "L'offre est égale ou supérieure aux nets des marchés."
    if resultat["offre_sous_cout_revient"]:
        texte += " Attention : l'offre est sous votre coût de revient."
    return texte


def handle_whatsapp_message(
    message_text: str,
    offre_unitaire: int | None = None,
    quantite: float = 1,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Message WhatsApp entrant (texte libre) -> réponse à renvoyer."""
    demande, resultat = _evaluer(
        message_text, None, offre_unitaire, quantite, aujourd_hui
    )
    if resultat is None:
        return {"channel": "whatsapp", "reply": build_dtmf_fallback_prompt()}
    nom = prix.nom_produit(demande.product)
    if not resultat["resultats"]:
        return {
            "channel": "whatsapp",
            "reply": f"Aucun prix récent pour {nom} près de {demande.localite}. "
            "Aucun prix n'est deviné.",
            "evaluation": resultat,
        }
    unite = demande.unit + ("s" if quantite > 1 and demande.unit != "kg" else "")
    lignes = [f"*{nom}, {quantite:g} {unite}, net après frais :*"]
    for m in resultat["resultats"]:
        lignes.append(
            f"- {m['marche']} : {fcfa(m['net_total'])} "
            f"(relevé du {m['date_releve']}, {m['source']})"
        )
    phrase = _phrase_offre(resultat)
    if phrase:
        lignes.append(phrase)
    lignes.append(f"_{resultat['note']}_")
    return {"channel": "whatsapp", "reply": "\n".join(lignes), "evaluation": resultat}


def handle_voice_call(
    spoken_or_text_input: str,
    dtmf_digit: str | None = None,
    offre_unitaire: int | None = None,
    quantite: float = 1,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Appel : transcription (ou touche) -> texte que le serveur vocal lirait."""
    demande, resultat = _evaluer(
        spoken_or_text_input, dtmf_digit, offre_unitaire, quantite, aujourd_hui
    )
    if resultat is None:
        return {
            "channel": "appel",
            "mode": "menu_touches",
            "texte_a_lire": build_dtmf_fallback_prompt(),
        }
    nom = prix.nom_produit(demande.product)
    confirmation = build_confirmation_prompt(nom, demande.unit, demande.localite)
    if not resultat["resultats"]:
        texte = f"Aucun prix récent pour {nom}. Je ne donne jamais un prix deviné."
    else:
        meilleur = resultat["resultats"][0]
        texte = (
            f"À {meilleur['marche']}, relevé du {date_parlee(meilleur['date_releve'])}, "
            f"il vous reste {fcfa(meilleur['net_total'])} après les frais. "
            f"{_phrase_offre(resultat)} C'est vous qui décidez."
        )
    return {
        "channel": "appel",
        "mode": "reponse",
        "confirmation": confirmation,
        "texte_a_lire": " ".join(texte.split()),
        "evaluation": resultat,
    }
