"""Bot Telegram : menu à boutons (comme l'USSD) et texte libre (comme WhatsApp).

Deux façons d'utiliser le bot :
- /start : menu à boutons, langue -> produit -> unité -> zone -> offre -> résultat.
  Les écrans et les textes sont ceux de l'USSD (src/ussd.py, data/textes_ussd.csv) :
  le fongbè s'affiche dès que la colonne fon est remplie.
- texte libre : « maïs 2 sacs 15000 », réponse en français (même moteur que WhatsApp).

Le serveur (Vercel) ne garde aucune mémoire entre deux messages. Le parcours est
donc rangé dans les boutons, exactement comme le champ `text` de l'USSD : le
bouton « Sac » du parcours français/maïs porte « 1*1*1 ». Pour l'offre, tapée au
clavier, la question se termine par « (réf. 1*1*1*1) » et Telegram nous renvoie
cette question avec la réponse du producteur.

On répond DANS la réponse HTTP (sendMessage ou editMessageText) : aucun jeton
n'est nécessaire côté serveur. Si TELEGRAM_TOKEN est défini, on arrête en plus
le sablier du bouton touché (answerCallbackQuery) ; c'est facultatif.

Sécurité : au branchement du webhook, on donne à Telegram un mot de passe
(secret_token), renvoyé dans l'en-tête X-Telegram-Bot-Api-Secret-Token. Si
TELEGRAM_SECRET est défini, toute requête sans ce mot de passe est ignorée.
"""

from __future__ import annotations

import hmac
import os
import re
from datetime import date
from typing import Any

import httpx

from src import ussd
from src.whatsapp import AIDE, repondre_whatsapp

COMMANDES_AIDE = {"/aide", "/help"}
COMMANDES_MENU = {"/start", "/menu", "/langue"}
NOUVELLE_RECHERCHE = "menu"

AIDE_TELEGRAM = (
    AIDE.replace("*", "")
    + "\n\nTapez /start pour le menu à boutons (français ou fongbè)."
)

_OPTION = re.compile(r"^(\d+)\. (.+)$")
_REFERENCE = re.compile(r"\(réf\. ([0-9*]{1,40})\)\s*$")
_PARCOURS = re.compile(r"^[0-9*]{0,40}$")


def _commande(texte: str) -> str:
    """'/start@mon_bot extra' -> '/start'."""
    mots = texte.strip().split()
    return mots[0].split("@")[0].lower() if mots else ""


def texte_telegram(message: str, aujourd_hui: date | None = None) -> str:
    """Réponse à un message en texte libre, sans la mise en forme WhatsApp."""
    if _commande(message) in COMMANDES_AIDE:
        return AIDE_TELEGRAM
    reponse = repondre_whatsapp(message, aujourd_hui)
    if reponse.startswith("Bonjour !") or reponse.startswith("Je n'ai pas reconnu"):
        reponse += "\n\nTapez /start pour le menu à boutons (français ou fongbè)."
    return reponse.replace("*", "").replace("_", "")


def decouper_ecran(ecran: str) -> tuple[str, list[tuple[str, str]], bool]:
    """Écran USSD -> (texte, [(numéro, libellé)], fin ?).

    'CON Titre\\n1. Maïs\\n0. Retour' -> ('Titre', [('1','Maïs'), ('0','Retour')], False)
    """
    fin = ecran.startswith("END ")
    lignes = ecran[4:].split("\n")
    options = [m.groups() for m in map(_OPTION.match, lignes) if m]
    texte = "\n".join(ligne for ligne in lignes if not _OPTION.match(ligne))
    return texte, [(numero, libelle) for numero, libelle in options], fin


def _suivant(parcours: str, numero: str) -> str:
    return f"{parcours}*{numero}" if parcours else numero


def _clavier(parcours: str, options: list[tuple[str, str]]) -> dict[str, Any]:
    """Un bouton par ligne ; chaque bouton porte le parcours complet."""
    return {
        "inline_keyboard": [
            [
                {
                    "text": ("↩ " if numero == "0" else "") + libelle,
                    "callback_data": _suivant(parcours, numero),
                }
            ]
            for numero, libelle in options
        ]
    }


CLAVIER_NOUVELLE_RECHERCHE = {
    "inline_keyboard": [
        [{"text": "🔁 Nouvelle recherche", "callback_data": NOUVELLE_RECHERCHE}]
    ]
}


def ecran_menu(
    chat_id: str,
    parcours: str,
    message_id: int | None = None,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Réponse Telegram pour l'écran du menu correspondant au parcours."""
    texte, options, fin = decouper_ecran(ussd.ecran_avec_accents(parcours, aujourd_hui))
    if not fin and not options:
        # Étape de l'offre : on demande une réponse tapée au clavier.
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": f"{texte}\n(réf. {parcours})",
            "reply_markup": {"force_reply": True, "input_field_placeholder": "15000"},
        }
    clavier = CLAVIER_NOUVELLE_RECHERCHE if fin else _clavier(parcours, options)
    reponse: dict[str, Any] = {
        "method": "editMessageText" if message_id else "sendMessage",
        "chat_id": chat_id,
        "text": texte,
        "reply_markup": clavier,
    }
    if message_id:
        reponse["message_id"] = message_id
    return reponse


def _bouton(
    rappel: dict[str, Any], aujourd_hui: date | None
) -> tuple[str, dict[str, Any]]:
    """Bouton touché : on remplace l'écran par le suivant."""
    message = rappel.get("message") or {}
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return "", {}
    arreter_sablier(str(rappel.get("id", "")))
    donnees = str(rappel.get("data", ""))
    if donnees == NOUVELLE_RECHERCHE:
        return chat_id, ecran_menu(chat_id, "", None, aujourd_hui)
    if not _PARCOURS.match(donnees):
        return chat_id, {}
    return chat_id, ecran_menu(chat_id, donnees, message.get("message_id"), aujourd_hui)


def _message(
    message: dict[str, Any], aujourd_hui: date | None
) -> tuple[str, dict[str, Any]]:
    """Message tapé : commande, réponse à la question de l'offre, ou texte libre."""
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return "", {}
    texte = message.get("text")
    if not texte:  # photo, vocal, autocollant…
        return chat_id, {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": AIDE_TELEGRAM,
        }
    if _commande(texte) in COMMANDES_MENU:
        return chat_id, ecran_menu(chat_id, "", None, aujourd_hui)
    question = (message.get("reply_to_message") or {}).get("text", "")
    reference = _REFERENCE.search(question)
    if reference:
        offre = texte.strip().replace(" ", "")
        texte_resultat, _, _ = decouper_ecran(
            ussd.ecran_avec_accents(f"{reference.group(1)}*{offre}", aujourd_hui)
        )
        return chat_id, {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": texte_resultat,
            "reply_markup": CLAVIER_NOUVELLE_RECHERCHE,
        }
    return chat_id, {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": texte_telegram(texte, aujourd_hui),
    }


def reponse_telegram(
    mise_a_jour: dict[str, Any], aujourd_hui: date | None = None
) -> tuple[str, dict[str, Any]]:
    """(identifiant de la discussion, réponse à renvoyer à Telegram)."""
    if mise_a_jour.get("callback_query"):
        return _bouton(mise_a_jour["callback_query"], aujourd_hui)
    if mise_a_jour.get("message"):
        return _message(mise_a_jour["message"], aujourd_hui)
    return "", {}


def texte_recu(mise_a_jour: dict[str, Any]) -> str:
    """Ce que l'utilisateur a tapé ou touché (pour le journal)."""
    rappel = mise_a_jour.get("callback_query") or {}
    if rappel:
        return "bouton:" + str(rappel.get("data", ""))
    return str((mise_a_jour.get("message") or {}).get("text") or "")


def arreter_sablier(identifiant: str) -> None:
    """Facultatif : arrête le sablier du bouton touché (si TELEGRAM_TOKEN est défini)."""
    jeton = os.getenv("TELEGRAM_TOKEN", "")
    if not jeton or not identifiant:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{jeton}/answerCallbackQuery",
            json={"callback_query_id": identifiant},
            timeout=3,
        )
    except httpx.HTTPError:
        return


def secret_valide(attendu: str, recu: str | None) -> bool:
    """Compare le mot de passe reçu à celui attendu, en temps constant."""
    return bool(recu) and hmac.compare_digest(attendu, recu or "")
