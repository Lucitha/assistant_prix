"""Vérifie les fichiers CSV de data/ avant de lancer ou de déployer.

Lancer :  python -m src.verifier

À faire après CHAQUE modification de data/prix.csv (par exemple après avoir
recopié des prix depuis AgroFlux), surtout si vous l'avez ouvert dans Excel :
Excel change souvent les dates (2026-11-21 devient 21/11/2026) et l'encodage.
"""

import csv
import re
import sys
from datetime import date

from src import prix


def verifier() -> list[str]:
    """Renvoie la liste des erreurs trouvées (liste vide = tout va bien)."""
    erreurs = []
    codes_produits = {p["code"] for p in prix.produits()}
    codes_marches = {m["code"] for m in prix.lire_csv("marches.csv")}

    colonnes = [
        "produit",
        "marche",
        "unite",
        "prix_fcfa",
        "type_prix",
        "date_releve",
        "source",
    ]
    lignes = prix.lire_csv("prix.csv")
    if lignes and list(lignes[0].keys()) != colonnes:
        erreurs.append(
            f"prix.csv : colonnes attendues {colonnes}, trouvées {list(lignes[0].keys())}"
        )
        return erreurs

    for n, r in enumerate(lignes, start=2):  # ligne 1 = en-tête
        ou = f"prix.csv ligne {n}"
        if r["produit"] not in codes_produits:
            erreurs.append(
                f"{ou} : produit '{r['produit']}' inconnu (attendu : {sorted(codes_produits)})"
            )
        if r["marche"] not in codes_marches:
            erreurs.append(f"{ou} : marché '{r['marche']}' absent de marches.csv")
        if r["unite"] not in prix.UNITES:
            erreurs.append(
                f"{ou} : unité '{r['unite']}' inconnue (attendu : {prix.UNITES})"
            )
        elif prix.poids_kg(r["produit"], r["unite"]) is None:
            erreurs.append(
                f"{ou} : pas de poids pour {r['produit']}/{r['unite']} dans poids_unites.csv"
            )
        if not r["prix_fcfa"].isdigit() or int(r["prix_fcfa"]) <= 0:
            erreurs.append(
                f"{ou} : prix '{r['prix_fcfa']}' invalide (nombre entier, sans espace ni F)"
            )
        if r["type_prix"] not in ("detail", "gros", "bord_champ"):
            erreurs.append(
                f"{ou} : type_prix '{r['type_prix']}' (attendu : detail, gros ou bord_champ)"
            )
        try:
            jour = date.fromisoformat(r["date_releve"])
            if jour > date.today():
                erreurs.append(f"{ou} : date {r['date_releve']} dans le futur")
        except ValueError:
            erreurs.append(
                f"{ou} : date '{r['date_releve']}' au mauvais format (attendu AAAA-MM-JJ)"
            )

    erreurs.extend(verifier_textes())

    for n, z in enumerate(prix.lire_csv("zones.csv"), start=2):
        if z["marche"] not in codes_marches:
            erreurs.append(
                f"zones.csv ligne {n} : marché '{z['marche']}' absent de marches.csv"
            )

    return erreurs


def colonnes_en_trop(nom_fichier: str) -> list[str]:
    """Lignes qui n'ont pas le même nombre de colonnes que l'en-tête."""
    with open(prix.DATA_DIR / nom_fichier, encoding="utf-8-sig", newline="") as f:
        entete = f.readline()
        f.seek(0)
        separateur = ";" if entete.count(";") > entete.count(",") else ","
        lignes = list(csv.reader(f, delimiter=separateur))
    attendu = len(lignes[0]) if lignes else 0
    return [
        f"{nom_fichier} ligne {n} : {len(ligne)} colonnes au lieu de {attendu} "
        "(virgule en trop ? mettre le texte entre guillemets s'il contient une virgule)"
        for n, ligne in enumerate(lignes[1:], start=2)
        if ligne and len(ligne) != attendu
    ]


def verifier_textes() -> list[str]:
    """Textes USSD : une traduction fon doit garder les mêmes {variables} que le français."""
    erreurs = colonnes_en_trop("textes_ussd.csv")
    variables = re.compile(r"\{(\w+)\}")
    for n, ligne in enumerate(prix.lire_csv("textes_ussd.csv"), start=2):
        fon = ligne.get("fon", "")
        if fon and set(variables.findall(fon)) != set(variables.findall(ligne["fr"])):
            erreurs.append(
                f"textes_ussd.csv ligne {n} ({ligne['cle']}) : le texte fon doit "
                f"contenir exactement {sorted(set(variables.findall(ligne['fr'])))}"
            )
    return erreurs


def resume_fraicheur() -> list[str]:
    """Pour chaque produit et marché : date du dernier relevé et s'il est encore annoncé."""
    derniers: dict[tuple, str] = {}
    for r in prix.lire_csv("prix.csv"):
        cle = (r["produit"], r["marche"])
        derniers[cle] = max(derniers.get(cle, ""), r["date_releve"])
    lignes = []
    for (produit, marche), d in sorted(derniers.items()):
        age = (date.today() - date.fromisoformat(d)).days
        etat = "OK" if age <= prix.MAX_AGE_JOURS else "TROP VIEUX, ne sera pas annoncé"
        lignes.append(f"  {produit:8} {marche:10} {d}  ({age} j)  {etat}")
    return lignes


if __name__ == "__main__":
    erreurs = verifier()
    if erreurs:
        print(f"{len(erreurs)} erreur(s) :")
        for e in erreurs:
            print("  -", e)
        sys.exit(1)
    print("Données valides. Fraîcheur des prix :")
    print("\n".join(resume_fraicheur()))
