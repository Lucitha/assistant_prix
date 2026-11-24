"""Service prix et moteur de calcul, commun à tous les canaux.

Aucune IA ici : on lit les fichiers CSV de data/, on cherche le dernier prix
récent sur chaque marché proche, on le convertit dans l'unité du producteur,
puis on retire les frais (transport, manutention, taxe de marché).

Règle du DAT : un prix plus vieux que MAX_AGE_JOURS n'est jamais annoncé,
et aucun prix absent n'est deviné.

Les CSV sont relus à chaque demande : modifier data/prix.csv pendant que
le serveur tourne suffit pour que la réponse suivante en tienne compte.
"""

from __future__ import annotations

import csv
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

DATA_DIR = Path(
    os.getenv("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))
)
MAX_AGE_JOURS = int(os.getenv("MAX_AGE_JOURS", "7"))
UNITES = ["sac", "bassine", "bol", "kg"]


def lire_csv(nom_fichier: str) -> list[dict[str, str]]:
    """Lit un CSV de data/ (virgules ou points-virgules, avec ou sans BOM Excel).

    Une ligne avec trop de colonnes (virgule en trop) ne fait pas planter le
    serveur : les colonnes en surplus sont ignorées ; `python -m src.verifier`
    les signale.
    """
    with open(DATA_DIR / nom_fichier, encoding="utf-8-sig", newline="") as f:
        entete = f.readline()
        f.seek(0)
        separateur = ";" if entete.count(";") > entete.count(",") else ","
        return [
            {
                (cle or "").strip(): (valeur or "").strip()
                for cle, valeur in ligne.items()
                if cle is not None  # colonnes en surplus : ignorées
            }
            for ligne in csv.DictReader(f, delimiter=separateur)
        ]


def produits() -> list[dict[str, str]]:
    """Liste des produits : [{'code': 'mais', 'nom': 'Maïs'}, ...]."""
    return lire_csv("produits.csv")


def nom_produit(code: str) -> str:
    """Nom affiché d'un produit à partir de son code."""
    for ligne in produits():
        if ligne["code"] == code:
            return ligne["nom"]
    return code


def localites() -> list[str]:
    """Localités connues, sans doublon, dans l'ordre du fichier zones.csv."""
    vues: list[str] = []
    for ligne in lire_csv("zones.csv"):
        if ligne["localite"] not in vues:
            vues.append(ligne["localite"])
    return vues


def nom_marche(code: str) -> str:
    """Nom affiché d'un marché (avec accents)."""
    for ligne in lire_csv("marches.csv"):
        if ligne["code"] == code:
            return ligne["nom"]
    return code


def poids_kg(produit: str, unite: str) -> float | None:
    """Poids moyen en kg d'une unité pour un produit, ou None si inconnu."""
    for ligne in lire_csv("poids_unites.csv"):
        if ligne["produit"] == produit and ligne["unite"] == unite:
            return float(ligne["kg_moyen"])
    return None


def frais_par_kg(marche: str) -> tuple[float, float]:
    """(manutention, taxe de marché) en FCFA par kg ; (0, 0) si inconnus."""
    for ligne in lire_csv("frais_marche.csv"):
        if ligne["marche"] == marche:
            return float(ligne["manutention_fcfa_par_kg"]), float(
                ligne["taxe_fcfa_par_kg"]
            )
    return 0.0, 0.0


def cout_revient(produit: str, unite: str) -> int | None:
    """Coût de revient pour une unité du produit, ou None si inconnu."""
    kg = poids_kg(produit, unite)
    for ligne in lire_csv("cout_revient.csv"):
        if ligne["produit"] == produit and kg is not None:
            return round(float(ligne["cout_fcfa_par_kg"]) * kg)
    return None


@dataclass
class PrixMarche:
    """Résultat pour un marché et UNE unité. Chaque chiffre garde sa provenance."""

    marche: str
    prix: int
    transport: int
    manutention: int
    taxe: int
    net: int
    date_releve: str
    type_prix: str
    source: str

    @property
    def frais(self) -> int:
        """Total des frais pour une unité."""
        return self.transport + self.manutention + self.taxe


def _dernier_releve_recent(
    releves: list[dict[str, str]], marche: str, aujourd_hui: date
) -> dict[str, str] | None:
    """Relevé le plus récent d'un marché, s'il a moins de MAX_AGE_JOURS."""
    recents = [
        r
        for r in releves
        if r["marche"] == marche
        and 0
        <= (aujourd_hui - date.fromisoformat(r["date_releve"])).days
        <= MAX_AGE_JOURS
    ]
    if not recents:
        return None
    return max(recents, key=lambda r: r["date_releve"])


def chercher_prix(
    produit: str, unite: str, localite: str, aujourd_hui: date | None = None
) -> dict[str, Any]:
    """Prix récents de `produit` sur les marchés proches de `localite`, pour 1 `unite`.

    Renvoie {"resultats": [PrixMarche, ...] du meilleur net au moins bon,
             "sans_prix_recent": [noms des marchés sans relevé récent]}.
    """
    aujourd_hui = aujourd_hui or date.today()
    kg_cible = poids_kg(produit, unite)
    releves = [r for r in lire_csv("prix.csv") if r["produit"] == produit]

    resultats: list[PrixMarche] = []
    sans_prix: list[str] = []
    for zone in lire_csv("zones.csv"):
        if zone["localite"] != localite:
            continue
        marche = zone["marche"]
        dernier = _dernier_releve_recent(releves, marche, aujourd_hui)
        kg_source = poids_kg(produit, dernier["unite"]) if dernier else None
        if dernier is None or kg_source is None or kg_cible is None:
            sans_prix.append(nom_marche(marche))
            continue

        prix_converti = round(float(dernier["prix_fcfa"]) / kg_source * kg_cible)
        transport = round(float(zone["transport_fcfa_par_kg"]) * kg_cible)
        manut_kg, taxe_kg = frais_par_kg(marche)
        manutention = round(manut_kg * kg_cible)
        taxe = round(taxe_kg * kg_cible)
        resultats.append(
            PrixMarche(
                marche=nom_marche(marche),
                prix=prix_converti,
                transport=transport,
                manutention=manutention,
                taxe=taxe,
                net=prix_converti - transport - manutention - taxe,
                date_releve=dernier["date_releve"],
                type_prix=dernier["type_prix"],
                source=dernier["source"],
            )
        )

    resultats.sort(key=lambda p: p.net, reverse=True)
    return {"resultats": resultats, "sans_prix_recent": sans_prix}


def resultat_en_json(
    produit: str,
    unite: str,
    localite: str,
    offre_unitaire: int | None = None,
    quantite: float = 1,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Résultat détaillé (route /prix, WhatsApp, appel) ; montants pour `quantite` unités."""
    if quantite <= 0:
        raise ValueError("La quantité doit être strictement positive.")
    res = chercher_prix(produit, unite, localite, aujourd_hui)
    cout = cout_revient(produit, unite)
    lignes = []
    for p in res["resultats"]:
        ligne = asdict(p)
        ligne["frais"] = p.frais
        ligne["net_total"] = round(p.net * quantite)
        if offre_unitaire:
            ligne["ecart_avec_offre_total"] = round((p.net - offre_unitaire) * quantite)
        if cout is not None:
            ligne["marge_total"] = round((p.net - cout) * quantite)
        lignes.append(ligne)
    return {
        "produit": produit,
        "unite": unite,
        "localite": localite,
        "quantite": quantite,
        "offre_unitaire": offre_unitaire,
        "cout_revient_unitaire": cout,
        "offre_sous_cout_revient": bool(
            offre_unitaire and cout is not None and offre_unitaire < cout
        ),
        "max_age_jours": MAX_AGE_JOURS,
        "resultats": lignes,
        "sans_prix_recent": res["sans_prix_recent"],
        "note": "Repère chiffré : le producteur reste seul à décider de sa vente.",
    }
