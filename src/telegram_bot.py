"""Bot Telegram : même moteur et mêmes réponses que le bot WhatsApp.

Fonctionnement :
1. le producteur écrit au bot, par exemple « maïs 2 sacs 15000 » ;
2. Telegram envoie un POST /telegram avec le message en JSON ;
3. on répond DANS la réponse HTTP (méthode sendMessage) : le serveur n'a
   besoin d'aucun jeton pour répondre.

Sécurité : au branchement du webhook, on donne à Telegram un mot de passe
(secret_token). Telegram le renvoie dans l'en-tête
X-Telegram-Bot-Api-Secret-Token ; si TELEGRAM_SECRET est défini, toute
requête sans ce mot de passe est ignorée.
"""

from __future__ import annotations

import hmac
from datetime import date
from typing import Any

from src.whatsapp import AIDE, repondre_whatsapp

COMMANDES_AIDE = {"/start", "/aide", "/help"}


def texte_telegram(message: str, aujourd_hui: date | None = None) -> str:
    """Réponse au message, sans la mise en forme WhatsApp (* et _)."""
    commande = message.strip().split("@")[0].lower()
    if commande in COMMANDES_AIDE:
        reponse = AIDE
    else:
        reponse = repondre_whatsapp(message, aujourd_hui)
    return reponse.replace("*", "").replace("_", "")


def reponse_telegram(
    mise_a_jour: dict[str, Any], aujourd_hui: date | None = None
) -> tuple[str, dict[str, Any]]:
    """(identifiant de la discussion, réponse à renvoyer à Telegram).

    Une mise à jour sans message texte (photo, vocal, modification…) reçoit l'aide.
    """
    message = mise_a_jour.get("message") or {}
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return "", {}
    texte = message.get("text")
    contenu = texte_telegram(texte, aujourd_hui) if texte else AIDE.replace("*", "")
    return chat_id, {"method": "sendMessage", "chat_id": chat_id, "text": contenu}


def secret_valide(attendu: str, recu: str | None) -> bool:
    """Compare le mot de passe reçu à celui attendu, en temps constant."""
    return bool(recu) and hmac.compare_digest(attendu, recu or "")
