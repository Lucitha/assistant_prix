"""Bot WhatsApp réel : API WhatsApp Cloud de Meta (gratuite) ou sandbox Twilio.

Au Bénin, Twilio refuse les comptes d'essai : on utilise Meta (voir plus bas).
La partie Twilio reste pour un éventuel compte payant.

Fonctionnement (comme l'USSD avec Africa's Talking) :
1. le producteur écrit au numéro du sandbox, par exemple « maïs 2 sacs 15000 » ;
2. Twilio envoie un POST /whatsapp avec les champs de formulaire Body et From ;
3. on répond directement avec un petit XML (TwiML) contenant le message.

Le message est en texte libre : produit (« maïs », « gbadé »…), unité
(« sac », « bassine »…), quantité (nombre de moins de 100) et offre de
l'acheteur par unité (nombre de 100 ou plus, « 15000 » ou « 15 000 »).

Sécurité : si TWILIO_AUTH_TOKEN et WHATSAPP_WEBHOOK_URL sont définis dans les
réglages, chaque requête doit porter une signature Twilio valide.
"""

from __future__ import annotations

import base64
import hmac
import html
import os
import re
from datetime import date
from typing import Any

import httpx

from src.channels import handle_whatsapp_message
from src.fon_assistant import normalize_text

AIDE = (
    "Bonjour ! Je donne le prix récent sur les marchés proches, net de frais.\n"
    "Écrivez par exemple :\n"
    "*maïs sac 15000*  (15000 = prix proposé par l'acheteur pour 1 sac)\n"
    "*piment 3 kg 600*\n"
    "*gbadé bassine*\n"
    "Produits : maïs, piment. Unités : sac, bassine, bol, kg."
)

MOTS_AIDE = {"", "aide", "help", "bonjour", "bonsoir", "salut", "menu", "start"}

# « 15 000 », « 15.000 » ou « 15000 »
_NOMBRE = re.compile(r"\d{1,3}(?:[ .]\d{3})+|\d+")


def lire_quantite_et_offre(texte: str) -> tuple[float, int | None]:
    """Repère la quantité (nombre < 100) et l'offre par unité (nombre >= 100).

    'maïs 2 sacs 15 000' -> (2, 15000) ; 'maïs sac' -> (1, None).
    """
    quantite: float = 1
    offre: int | None = None
    quantite_vue = False
    for brut in _NOMBRE.findall(normalize_text(texte)):
        valeur = int(brut.replace(" ", "").replace(".", ""))
        if valeur >= 100:
            offre = valeur
        elif valeur > 0 and not quantite_vue:
            quantite, quantite_vue = valeur, True
    return quantite, offre


def repondre_whatsapp(message: str, aujourd_hui: date | None = None) -> str:
    """Texte de la réponse au message reçu."""
    if normalize_text(message) in MOTS_AIDE:
        return AIDE
    quantite, offre = lire_quantite_et_offre(message)
    reponse = handle_whatsapp_message(message, offre, quantite, aujourd_hui)
    if "evaluation" not in reponse:  # produit non reconnu
        return "Je n'ai pas reconnu le produit.\n\n" + AIDE
    return str(reponse["reply"])


def twiml(texte: str) -> str:
    """Réponse au format attendu par Twilio."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{html.escape(texte)}</Message></Response>"
    )


def signature_twilio(token: str, url: str, champs: dict[str, str]) -> str:
    """Signature attendue : HMAC-SHA1 de l'URL suivie des champs triés, en base64."""
    donnees = url + "".join(cle + champs[cle] for cle in sorted(champs))
    empreinte = hmac.new(token.encode(), donnees.encode(), "sha1").digest()
    return base64.b64encode(empreinte).decode()


def signature_valide(
    token: str, url: str, champs: dict[str, str], recue: str | None
) -> bool:
    """Compare la signature reçue à celle attendue, en temps constant."""
    if not recue:
        return False
    return hmac.compare_digest(signature_twilio(token, url, champs), recue)


# ---------- API WhatsApp Cloud de Meta (gratuite, numéro de test) ----------
#
# Différences avec Twilio :
# - Meta vérifie d'abord l'adresse par un GET (hub.challenge à renvoyer) ;
# - les messages arrivent en JSON ;
# - la réponse ne se fait PAS dans la réponse HTTP : on appelle l'API de Meta
#   avec un jeton d'accès (WHATSAPP_TOKEN).


def extraire_messages_meta(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Liste des (numéro de l'expéditeur, texte) contenus dans une notification Meta.

    Les notifications de statut (envoyé, lu…) ne contiennent pas de message : liste vide.
    """
    messages: list[tuple[str, str]] = []
    for entree in payload.get("entry", []):
        for changement in entree.get("changes", []):
            for msg in changement.get("value", {}).get("messages", []):
                if msg.get("type") == "text":
                    messages.append((msg.get("from", ""), msg["text"].get("body", "")))
                else:
                    messages.append((msg.get("from", ""), ""))  # vocal, image… -> aide
    return messages


def signature_meta_valide(secret: str, corps: bytes, recue: str | None) -> bool:
    """Vérifie l'en-tête X-Hub-Signature-256 ('sha256=' + HMAC-SHA256 du corps)."""
    if not recue:
        return False
    attendue = "sha256=" + hmac.new(secret.encode(), corps, "sha256").hexdigest()
    return hmac.compare_digest(attendue, recue)


def envoyer_message_meta(destinataire: str, texte: str) -> int:
    """Envoie un message texte par l'API de Meta ; renvoie le code HTTP obtenu."""
    version = os.getenv("GRAPH_API_VERSION", "v23.0")
    numero_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    url = f"https://graph.facebook.com/{version}/{numero_id}/messages"
    reponse = httpx.post(
        url,
        headers={"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN', '')}"},
        json={
            "messaging_product": "whatsapp",
            "to": destinataire,
            "type": "text",
            "text": {"body": texte},
        },
        timeout=10,
    )
    return reponse.status_code
