"""Tests automatiques de l'Assistant Prix. Lancer : pytest -x"""

import csv
from datetime import date

import pytest
from fastapi.testclient import TestClient

import src.app as appli
from src import prix, ussd, verifier
from src.channels import handle_voice_call, handle_whatsapp_message
from src.fon_assistant import parse_farmer_request

JOUR = date(2026, 11, 24)  # date fixe : les tests ne dépendent pas du jour réel
APRES = date(2027, 3, 1)  # date où tous les relevés de démo sont trop vieux


# ---------- Moteur de calcul ----------


def test_net_apres_frais_glazoue() -> None:
    """Sac de maïs à Glazoué : 25 000 - 1 000 transport - 200 manutention - 100 taxe."""
    glazoue = prix.chercher_prix("mais", "sac", "Savalou", JOUR)["resultats"][0]
    assert glazoue.marche == "Glazoué"
    assert (glazoue.prix, glazoue.transport, glazoue.manutention, glazoue.taxe) == (
        25000,
        1000,
        200,
        100,
    )
    assert glazoue.frais == 1300
    assert glazoue.net == 23700


def test_conversion_sac_vers_bassine() -> None:
    """25 000 F le sac de 100 kg -> 6 250 F la bassine de 25 kg."""
    res = prix.chercher_prix("mais", "bassine", "Savalou", JOUR)["resultats"]
    assert [p for p in res if p.marche == "Glazoué"][0].prix == 6250


def test_prix_trop_vieux_jamais_annonce() -> None:
    """Le piment à Bantè date du 05/11 : plus de 7 jours, il ne sort pas."""
    res = prix.chercher_prix("piment", "kg", "Savalou", JOUR)
    assert "Bantè" not in [p.marche for p in res["resultats"]]
    assert "Bantè" in res["sans_prix_recent"]


def test_ne_devine_jamais_un_prix() -> None:
    """Sans relevé récent, aucun résultat."""
    assert prix.chercher_prix("mais", "sac", "Savalou", APRES)["resultats"] == []


def test_quantite_offre_et_cout_de_revient() -> None:
    """2 sacs, offre de 10 000 F par sac : écart et alerte sur le coût de revient."""
    res = prix.resultat_en_json("mais", "sac", "Savalou", 10000, 2, JOUR)
    glazoue = res["resultats"][0]
    assert glazoue["net_total"] == 47400
    assert glazoue["ecart_avec_offre_total"] == 27400
    assert res["cout_revient_unitaire"] == 12000
    assert res["offre_sous_cout_revient"] is True


def test_quantite_invalide() -> None:
    with pytest.raises(ValueError):
        prix.resultat_en_json("mais", "sac", "Savalou", quantite=0)


def test_valeurs_par_defaut_inconnues() -> None:
    assert prix.frais_par_kg("Inconnu") == (0.0, 0.0)
    assert prix.cout_revient("mais", "inconnue") is None
    assert prix.nom_produit("inconnu") == "inconnu"
    assert prix.nom_marche("Inconnu") == "Inconnu"


# ---------- Menu USSD ----------
# Saisies : langue * produit * unité * zone * offre (1 = français, 2 = fongbè)


def test_premier_ecran_choix_de_langue() -> None:
    r = ussd.repondre("", JOUR)
    assert r.startswith("CON Prix du marche")
    assert "1. Francais" in r and "2. Fongbe" in r


def test_parcours_complet() -> None:
    r = ussd.repondre("1*1*1*1*15000", JOUR)
    assert r.startswith("END")
    assert "Glazoue 23 700F" in r
    assert "8 700F sous Glazoue" in r
    assert len(r) <= ussd.LIMITE_CARACTERES


def test_alerte_cout_de_revient() -> None:
    r = ussd.repondre("1*1*1*1*10000", JOUR)
    assert "Attention: sous votre cout (12 000F)" in r
    assert len(r) <= ussd.LIMITE_CARACTERES


def test_offre_au_dessus_et_sans_offre() -> None:
    assert "egale ou au-dessus" in ussd.repondre("1*1*1*1*30000", JOUR)
    assert "A vous de decider" in ussd.repondre("1*2*4*1*0", JOUR)


@pytest.mark.parametrize(
    "saisies, attendu",
    [
        ("1", "CON Choisissez le produit"),
        ("1*1", "CON Mais: quelle unite"),
        ("1*1*1", "CON Vous etes pres de"),
        ("1*1*1*1", "CON Prix propose"),
        ("1*1*0*2", "CON Piment"),
        ("1*0", "CON Prix du marche"),
        ("9", "END Choix invalide"),
        ("1*9", "END Choix invalide"),
        ("1*1*9", "END Choix invalide"),
        ("1*1*1*9", "END Choix invalide"),
        ("1*1*1*1*abc", "END Montant invalide"),
    ],
)
def test_navigation(saisies: str, attendu: str) -> None:
    assert ussd.repondre(saisies, JOUR).startswith(attendu)


def test_aucun_prix_recent_ussd() -> None:
    assert "Aucun prix recent" in ussd.repondre("1*1*1*1*15000", APRES)


def test_ecran_avec_accents_pour_la_voix() -> None:
    assert "Maïs" in ussd.ecran_avec_accents("1", JOUR)


def copier_donnees_avec_fon(tmp_path, monkeypatch, fon: dict[str, str]) -> None:  # type: ignore[no-untyped-def]
    """Copie data/ dans tmp_path en imposant le texte fon de certaines clés.

    Les tests ne dépendent ainsi pas des traductions en cours dans le vrai fichier.
    """
    for f in prix.DATA_DIR.glob("*.csv"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(prix, "DATA_DIR", tmp_path)
    lignes = prix.lire_csv("textes_ussd.csv")
    for ligne in lignes:
        if ligne["cle"] in fon:
            ligne["fon"] = fon[ligne["cle"]]
    with open(tmp_path / "textes_ussd.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cle", "fr", "fon", "valide"])
        w.writeheader()
        w.writerows(lignes)


def test_fongbe_noms_fon_et_repli_en_francais(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """En fongbè : noms de produits en fon ; textes sans traduction en français."""
    copier_donnees_avec_fon(tmp_path, monkeypatch, {"titre_produit": ""})
    r = ussd.repondre("2", JOUR)
    assert "1. Gbade" in r and "2. Takin" in r
    assert "Choisissez le produit" in r  # pas traduit : repli en français
    assert ussd.langue_de("2*1") == "fon"
    assert ussd.langue_de("") == "fr"
    assert "23 700F" in ussd.repondre("2*1*1*1*15000", JOUR)


def test_fongbe_traduction_et_lettres_fon(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Une case fon remplie est affichée ; ɔ, ɛ, ɖ deviennent o, e, d pour l'USSD."""
    copier_donnees_avec_fon(
        tmp_path,
        monkeypatch,
        {"titre_produit": "Nǔ ɖé ɔ:", "pied_decider": "{inconnue}"},
    )
    assert ussd.repondre("2", JOUR).startswith("CON Nu de o:")
    # Variable inconnue dans le texte fon : repli en français, et le vérificateur le signale
    assert "A vous de decider" in ussd.repondre("2*2*4*1*0", JOUR)
    assert any("pied_decider" in e for e in verifier.verifier_textes())


def test_virgule_en_trop_ne_plante_pas(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Une ligne de textes_ussd.csv avec une colonne de trop : le service répond
    quand même, et le vérificateur signale la ligne."""
    copier_donnees_avec_fon(tmp_path, monkeypatch, {})
    with open(tmp_path / "textes_ussd.csv", "a", encoding="utf-8") as f:
        f.write("cle_test,Texte,Tɛ́xti,a_valider,\n")
    assert ussd.repondre("", JOUR).startswith("CON ")
    assert any("colonnes" in e for e in verifier.verifier_textes())


def test_texte_absent() -> None:
    assert ussd.t("cle_inconnue", "fon") == "cle_inconnue"


# ---------- Compréhension et canaux simulés ----------


def test_comprehension_fongbe_et_touches() -> None:
    d = parse_farmer_request("Gbadé bassine Savalou")
    assert (d.product, d.unit, d.localite) == ("mais", "bassine", "Savalou")
    assert parse_farmer_request("", dtmf_digit="2").product == "piment"
    assert parse_farmer_request("bonjour").needs_dtmf_fallback is True


def test_canal_whatsapp() -> None:
    r = handle_whatsapp_message("maïs sac", 15000, 1, JOUR)
    assert r["channel"] == "whatsapp"
    assert "Glazoué : 23 700 FCFA" in r["reply"]
    assert "8 700 FCFA" in r["reply"]


def test_canal_whatsapp_cas_limites() -> None:
    assert "Tapez 1" in handle_whatsapp_message("bonjour", aujourd_hui=JOUR)["reply"]
    assert "Aucun prix" in handle_whatsapp_message("maïs", aujourd_hui=APRES)["reply"]


def test_canal_appel() -> None:
    r = handle_voice_call("takin kg", offre_unitaire=400, aujourd_hui=JOUR)
    assert r["mode"] == "reponse"
    assert "Piment, au kg" in r["confirmation"]
    assert "Attention" in r["texte_a_lire"]
    assert "relevé du 21 novembre" in r["texte_a_lire"]


def test_canal_appel_cas_limites() -> None:
    assert handle_voice_call("rien")["mode"] == "menu_touches"
    r = handle_voice_call("", dtmf_digit="1", aujourd_hui=APRES)
    assert "jamais un prix deviné" in r["texte_a_lire"]
    sans_offre = handle_voice_call("maïs", aujourd_hui=JOUR)["texte_a_lire"]
    assert "Attention" not in sans_offre
    egale = handle_voice_call("maïs", offre_unitaire=30000, aujourd_hui=JOUR)
    assert "égale ou supérieure" in egale["texte_a_lire"]


# ---------- Données ----------


def test_donnees_de_demo_valides() -> None:
    assert verifier.verifier() == []
    assert verifier.resume_fraicheur()


def test_csv_excel_point_virgule(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Un CSV enregistré par Excel en français (BOM + « ; ») est lu pareil."""
    for f in prix.DATA_DIR.glob("*.csv"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    contenu = (prix.DATA_DIR / "prix.csv").read_text(encoding="utf-8")
    (tmp_path / "prix.csv").write_text(
        "﻿" + contenu.replace(",", ";"), encoding="utf-8"
    )
    monkeypatch.setattr(prix, "DATA_DIR", tmp_path)
    assert (
        prix.chercher_prix("mais", "sac", "Savalou", JOUR)["resultats"][0].net == 23700
    )


def test_verifier_signale_les_erreurs(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for f in prix.DATA_DIR.glob("*.csv"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    with open(tmp_path / "prix.csv", "a", encoding="utf-8") as f:
        f.write("riz,Lune,tas,12F,promo,21/11/2026,X\n")
    (tmp_path / "zones.csv").write_text(
        "localite,marche,distance_km,transport_fcfa_par_kg\nSavalou,Lune,1,1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prix, "DATA_DIR", tmp_path)
    erreurs = " ".join(verifier.verifier())
    for mot in [
        "produit 'riz'",
        "marché 'Lune'",
        "unité 'tas'",
        "prix '12F'",
        "type_prix",
        "date",
    ]:
        assert mot in erreurs


# ---------- Routes web ----------


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(appli, "JOURNAL", tmp_path / "journal.csv")
    return TestClient(appli.app)


def test_routes(client: TestClient) -> None:
    assert client.get("/sante").json() == {"ok": True}
    assert client.get("/health").json()["status"] == "ok"
    assert "tester" in client.get("/").json()
    assert "Lecture vocale" in client.get("/simulateur").text
    r = client.post(
        "/ussd", data={"sessionId": "t1", "phoneNumber": "+254711000001", "text": ""}
    )
    assert r.text.startswith("CON")
    assert (appli.JOURNAL).read_text(encoding="utf-8").count("\n") == 2
    s = client.post("/simulateur/ussd", data={"text": "1*1"}).json()
    assert s["ecran"].startswith("CON Mais") and "Maïs" in s["a_lire"]
    assert s["langue"] == "fr"
    assert client.post("/simulateur/ussd", data={"text": "2"}).json()["langue"] == "fon"
    p = client.get(
        "/prix", params={"produit": "mais", "unite": "sac", "localite": "Savalou"}
    )
    assert p.status_code == 200
    w = client.post("/webhook/whatsapp", json={"query_text": "maïs sac"})
    assert w.json()["channel"] == "whatsapp"
    v = client.post("/webhook/voice", json={"query_text": "", "dtmf_digit": "1"})
    assert v.json()["channel"] == "appel"


def test_journal_ne_bloque_pas(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(appli, "JOURNAL", tmp_path / "absent" / "journal.csv")
    appli.journaliser("s", "+254", "", "CON x")  # dossier absent : pas d'exception
    assert appli.masquer_numero("+254") != "+254"


# ---------- Bot WhatsApp (Twilio) ----------


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("maïs 2 sacs 15 000", (2, 15000)),
        ("gbadé sac 15000f", (1, 15000)),
        ("piment 3 kg", (3, None)),
        ("maïs sac", (1, None)),
    ],
)
def test_lire_quantite_et_offre(texte: str, attendu: tuple[float, int | None]) -> None:
    from src.whatsapp import lire_quantite_et_offre

    assert lire_quantite_et_offre(texte) == attendu


def test_reponses_whatsapp() -> None:
    from src.whatsapp import AIDE, repondre_whatsapp

    assert repondre_whatsapp("Bonjour") == AIDE
    assert repondre_whatsapp("riz").startswith("Je n'ai pas reconnu")
    r = repondre_whatsapp("maïs 2 sacs 15000", JOUR)
    assert "2 sacs" in r and "47 400 FCFA" in r and "17 400 FCFA" in r


def test_route_whatsapp(client: TestClient) -> None:
    r = client.post(
        "/whatsapp", data={"Body": "maïs sac 15000", "From": "whatsapp:+22901000000"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<Response><Message>" in r.text and "Glazoué" in r.text
    assert "+22901000000" not in appli.JOURNAL.read_text(encoding="utf-8")


def test_signature_twilio(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from src.whatsapp import signature_twilio, signature_valide

    url = "https://exemple.azurewebsites.net/whatsapp"
    champs = {"Body": "aide", "From": "whatsapp:+229"}
    bonne = signature_twilio("secret", url, champs)
    assert signature_valide("secret", url, champs, bonne)
    assert not signature_valide("secret", url, champs, None)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("WHATSAPP_WEBHOOK_URL", url)
    assert client.post("/whatsapp", data=champs).status_code == 403
    ok = client.post("/whatsapp", data=champs, headers={"X-Twilio-Signature": bonne})
    assert ok.status_code == 200


# ---------- Bot WhatsApp (Meta) ----------


def _notification_meta(texte: str | None) -> dict:  # type: ignore[type-arg]
    msg = {"from": "22901000000", "type": "text", "text": {"body": texte}}
    if texte is None:
        msg = {"from": "22901000000", "type": "audio"}
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


def test_verification_webhook_meta(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "jeton",
        "hub.challenge": "123",
    }
    assert client.get("/whatsapp/meta", params=params).status_code == 403
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "jeton")
    r = client.get("/whatsapp/meta", params=params)
    assert r.status_code == 200 and r.text == "123"


def test_route_whatsapp_meta(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import src.whatsapp as wa

    envoyes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        wa, "envoyer_message_meta", lambda n, t: envoyes.append((n, t)) or 200
    )
    r = client.post("/whatsapp/meta", json=_notification_meta("maïs sac 15000"))
    assert r.json() == {"traites": 1}
    assert envoyes[0][0] == "22901000000" and "Glazoué" in envoyes[0][1]
    client.post("/whatsapp/meta", json=_notification_meta(None))  # message vocal
    assert envoyes[1][1] == wa.AIDE
    statut = {"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]}
    assert client.post("/whatsapp/meta", json=statut).json() == {"traites": 0}
    assert "22901000000" not in appli.JOURNAL.read_text(encoding="utf-8")


def test_signature_meta(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import hashlib
    import hmac
    import json

    import src.whatsapp as wa

    monkeypatch.setattr(wa, "envoyer_message_meta", lambda n, t: 200)
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "secret")
    corps = json.dumps(_notification_meta("aide")).encode()
    assert client.post("/whatsapp/meta", content=corps).json() == {"traites": 0}
    sig = "sha256=" + hmac.new(b"secret", corps, hashlib.sha256).hexdigest()
    r = client.post(
        "/whatsapp/meta", content=corps, headers={"X-Hub-Signature-256": sig}
    )
    assert r.json() == {"traites": 1}


def test_envoyer_message_meta(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import src.whatsapp as wa

    appels: list[dict] = []  # type: ignore[type-arg]

    class Reponse:
        status_code = 200

    def faux_post(url: str, **kwargs) -> Reponse:  # type: ignore[no-untyped-def]
        appels.append({"url": url, **kwargs})
        return Reponse()

    monkeypatch.setattr(wa.httpx, "post", faux_post)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "111")
    monkeypatch.setenv("WHATSAPP_TOKEN", "tok")
    assert wa.envoyer_message_meta("22901000000", "Bonjour") == 200
    assert appels[0]["url"].endswith("/111/messages")
    assert appels[0]["headers"]["Authorization"] == "Bearer tok"
    assert appels[0]["json"]["text"]["body"] == "Bonjour"
