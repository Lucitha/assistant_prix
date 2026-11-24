"""Application web FastAPI : un seul moteur de prix, trois canaux.

Lancer en local (depuis le dossier 01-agriculture) :
    python -m uvicorn src.app:app --reload
Puis ouvrir :
    http://127.0.0.1:8000/simulateur   téléphone USSD, avec lecture vocale
    http://127.0.0.1:8000/docs         documentation automatique de l'API
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from src import prix, ussd, whatsapp
from src.channels import handle_voice_call, handle_whatsapp_message

app = FastAPI(title="Assistant Prix - Session 01 Agriculture", version="0.2.0")

# Clé pour masquer les numéros dans le journal : à définir dans les réglages
# Render (variable CLE_SECRETE), jamais dans le code.
CLE_SECRETE = os.getenv("CLE_SECRETE", "changez-moi-en-production").encode()
JOURNAL = Path(os.getenv("JOURNAL_PATH", str(prix.DATA_DIR / "journal.csv")))


def masquer_numero(numero: str) -> str:
    """Empreinte HMAC-SHA256 du numéro : jamais de numéro en clair."""
    return hmac.new(CLE_SECRETE, numero.encode(), hashlib.sha256).hexdigest()[:16]


def journaliser(session_id: str, numero: str, text: str, reponse: str) -> None:
    """Ajoute une ligne au journal (indicateurs du DAT) ; ne bloque jamais le service."""
    try:
        nouveau = not JOURNAL.exists()
        with open(JOURNAL, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if nouveau:
                w.writerow(
                    ["horodatage", "session", "tel_hash", "saisies", "fin", "reponse"]
                )
            w.writerow(
                [
                    datetime.now().isoformat(timespec="seconds"),
                    session_id,
                    masquer_numero(numero),
                    text,
                    reponse.startswith("END"),
                    reponse.replace("\n", " | "),
                ]
            )
    except OSError:
        return


class DemandeLibre(BaseModel):
    """Demande reçue par WhatsApp ou par appel (texte transcrit ou touche)."""

    query_text: str = Field("", description="Demande en français ou en fongbé")
    quantite: float = Field(1.0, gt=0)
    offre_unitaire_fcfa: int | None = Field(None, gt=0)
    dtmf_digit: str | None = None


@app.get("/sante")
def sante() -> dict[str, bool]:
    """Supervision : le service répond."""
    return {"ok": True}


@app.get("/health")
def health() -> dict[str, str]:
    """Alias anglais de /sante."""
    return {"status": "ok", "session": "01-agriculture"}


@app.post("/ussd", response_class=PlainTextResponse)
def route_ussd(
    sessionId: str = Form(""),
    serviceCode: str = Form(""),
    phoneNumber: str = Form(""),
    text: str = Form(""),
) -> str:
    """Appelée par Africa's Talking à chaque saisie de l'utilisateur."""
    reponse = ussd.repondre(text)
    journaliser(sessionId, phoneNumber, text, reponse)
    return reponse


@app.post("/whatsapp")
async def route_whatsapp(request: Request) -> Response:
    """Bot WhatsApp réel : appelée par le sandbox Twilio à chaque message reçu."""
    formulaire = await request.form()
    champs = {cle: str(valeur) for cle, valeur in formulaire.items()}
    jeton = os.getenv("TWILIO_AUTH_TOKEN", "")
    url_publique = os.getenv("WHATSAPP_WEBHOOK_URL", "")
    if (
        jeton
        and url_publique
        and not whatsapp.signature_valide(
            jeton, url_publique, champs, request.headers.get("X-Twilio-Signature")
        )
    ):
        return Response("Signature invalide", status_code=403)
    message = champs.get("Body", "")
    texte = whatsapp.repondre_whatsapp(message)
    journaliser("whatsapp", champs.get("From", ""), message, "END " + texte)
    return Response(whatsapp.twiml(texte), media_type="application/xml")


@app.get("/whatsapp/meta", response_class=PlainTextResponse)
def verifier_webhook_meta(request: Request) -> Response:
    """Vérification de l'adresse par Meta : renvoyer hub.challenge si le jeton concorde."""
    p = request.query_params
    attendu = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    if (
        attendu
        and p.get("hub.mode") == "subscribe"
        and p.get("hub.verify_token") == attendu
    ):
        return PlainTextResponse(p.get("hub.challenge", ""))
    return PlainTextResponse("Jeton de vérification invalide", status_code=403)


@app.post("/whatsapp/meta")
async def route_whatsapp_meta(request: Request) -> dict[str, int]:
    """Bot WhatsApp réel via Meta : lit chaque message et répond par l'API de Meta."""
    corps = await request.body()
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if secret and not whatsapp.signature_meta_valide(
        secret, corps, request.headers.get("X-Hub-Signature-256")
    ):
        return {"traites": 0}
    traites = 0
    for numero, message in whatsapp.extraire_messages_meta(await request.json()):
        texte = whatsapp.repondre_whatsapp(message)
        whatsapp.envoyer_message_meta(numero, texte)
        journaliser("whatsapp-meta", numero, message, "END " + texte)
        traites += 1
    return {"traites": traites}


@app.post("/webhook/whatsapp")
def webhook_whatsapp(demande: DemandeLibre) -> dict[str, Any]:
    """Canal WhatsApp (simulation) : renvoie le message qui serait envoyé."""
    return handle_whatsapp_message(
        demande.query_text, demande.offre_unitaire_fcfa, demande.quantite
    )


@app.post("/webhook/voice")
def webhook_voice(demande: DemandeLibre) -> dict[str, Any]:
    """Canal appel (simulation) : renvoie le texte que le serveur vocal lirait."""
    return handle_voice_call(
        demande.query_text,
        demande.dtmf_digit,
        demande.offre_unitaire_fcfa,
        demande.quantite,
    )


@app.get("/prix")
def route_prix(
    produit: str,
    unite: str,
    localite: str,
    offre: int | None = None,
    quantite: float = 1,
) -> dict[str, Any]:
    """Même calcul que les canaux, en JSON.

    Exemple : /prix?produit=mais&unite=sac&localite=Savalou&offre=15000
    """
    return prix.resultat_en_json(produit, unite, localite, offre, quantite)


@app.post("/simulateur/ussd")
def simulateur_ussd(text: str = Form("")) -> dict[str, str]:
    """Pour le simulateur : l'écran USSD et le même texte accentué à lire à voix haute."""
    return {
        "ecran": ussd.repondre(text),
        "a_lire": ussd.ecran_avec_accents(text),
        "langue": ussd.langue_de(text),
    }


@app.get("/simulateur", response_class=HTMLResponse)
def simulateur() -> str:
    """Téléphone USSD dans le navigateur, avec lecture vocale des écrans."""
    return (Path(__file__).parent / "simulateur.html").read_text(encoding="utf-8")


@app.get("/")
def accueil() -> dict[str, Any]:
    """Liens utiles pour tester."""
    return {
        "service": "Assistant Prix - Session 01 Agriculture",
        "tester": [
            "/simulateur",
            "/docs",
            "/prix?produit=mais&unite=sac&localite=Savalou&offre=15000",
        ],
    }
