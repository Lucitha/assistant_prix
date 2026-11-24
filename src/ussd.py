"""Logique du menu USSD, en français ou en fongbé.

Comment marche l'USSD avec Africa's Talking :
- À chaque fois que l'utilisateur tape quelque chose, Africa's Talking appelle
  notre URL (POST /ussd) avec le champ `text`.
- `text` contient TOUT ce que l'utilisateur a tapé depuis le début, séparé
  par des étoiles. Exemple : "" (premier écran), puis "1", puis "1*2"...
- Nous répondons du texte qui commence par :
    "CON " -> l'écran attend une nouvelle saisie (la session continue)
    "END " -> dernier écran (la session se termine)

Écrans : langue -> produit -> unité -> zone -> offre -> résultat.
Exemple complet : "1*1*1*1*15000" = français, maïs, sac, Savalou, offre 15 000 F.

Les textes affichés sont dans data/textes_ussd.csv (colonnes fr et fon).
Une case fon vide affiche le texte français : on remplit le fichier au fur et
à mesure que le locuteur fon valide les phrases, sans toucher au code.
"""

from __future__ import annotations

import unicodedata
from datetime import date

from src import prix

LIMITE_CARACTERES = 182  # un écran USSD ne doit pas dépasser ~182 caractères
RETOUR = "0"
LANGUES = ["fr", "fon"]
NOMS_LANGUES = ["Français", "Fongbè"]

# Lettres du fon absentes des téléphones simples : remplacées pour l'USSD.
LETTRES_FON = str.maketrans("ɔɛɖƆƐƉ", "oedOED")


def textes() -> dict[str, dict[str, str]]:
    """Textes du menu : {'titre_zone': {'fr': '...', 'fon': '...'}, ...}."""
    return {
        ligne["cle"]: {
            langue: ligne.get(langue, "").replace("\\n", "\n") for langue in LANGUES
        }
        for ligne in prix.lire_csv("textes_ussd.csv")
    }


def t(cle: str, langue: str, **valeurs: str) -> str:
    """Texte `cle` dans la langue demandée ; en français si la case fon est vide.

    Si le texte fon contient une erreur de {variable}, on revient au français
    plutôt que de planter devant le producteur.
    """
    entree = textes().get(cle, {"fr": cle, "fon": ""})
    texte = entree.get(langue) or entree["fr"]
    try:
        return texte.format(**valeurs)
    except (KeyError, IndexError, ValueError):
        return entree["fr"].format(**valeurs)


def formater_fcfa(montant: int) -> str:
    """25000 -> '25 000F'"""
    return f"{montant:,}".replace(",", " ") + "F"


def formater_date(iso: str) -> str:
    """'2026-11-21' -> '21/11'"""
    return f"{iso[8:10]}/{iso[5:7]}"


def menu(titre: str, options: list[str], retour: str | None = None) -> str:
    """Écran à choix numérotés ; `retour` = libellé de « 0. Retour » s'il y en a un."""
    lignes = [titre] + [f"{i}. {opt}" for i, opt in enumerate(options, start=1)]
    if retour:
        lignes.append(f"0. {retour}")
    return "CON " + "\n".join(lignes)


def choix_valide(saisie: str, nb_options: int) -> int | None:
    """Renvoie l'index (0, 1, 2...) si la saisie est un numéro du menu, sinon None."""
    if saisie.isdigit() and 1 <= int(saisie) <= nb_options:
        return int(saisie) - 1
    return None


def sans_accents(texte: str) -> str:
    """Les téléphones simples affichent mal les accents et les lettres du fon
    en USSD : on les remplace. 'Maïs, Bantè, Fɔngbè' -> 'Mais, Bante, Fongbe'."""
    decompose = unicodedata.normalize("NFKD", texte.translate(LETTRES_FON))
    return "".join(c for c in decompose if not unicodedata.combining(c))


def repondre(text: str, aujourd_hui: date | None = None) -> str:
    """Point d'entrée : calcule l'écran USSD à afficher, sans accents."""
    return sans_accents(_ecran(text, aujourd_hui))


def ecran_avec_accents(text: str, aujourd_hui: date | None = None) -> str:
    """Même écran, avec les accents : sert à la lecture vocale du simulateur."""
    return _ecran(text, aujourd_hui)


def rejouer_saisies(text: str) -> list[str]:
    """Liste des choix retenus ; « 0 » revient à l'écran précédent (sauf pour l'offre)."""
    choix: list[str] = []
    for saisie in [s.strip() for s in text.split("*")] if text else []:
        if saisie == RETOUR and 0 < len(choix) < 4:
            choix.pop()
            continue
        choix.append(saisie)
    return choix


def langue_de(text: str) -> str:
    """Langue choisie au premier écran ('fr' par défaut)."""
    choix = rejouer_saisies(text)
    i = choix_valide(choix[0], len(LANGUES)) if choix else None
    return LANGUES[i] if i is not None else "fr"


def nom_produit(produit: dict[str, str], langue: str) -> str:
    """Nom du produit dans la langue (nom de produits.csv si absent des textes)."""
    cle = f"produit_{produit['code']}"
    return t(cle, langue) if cle in textes() else produit["nom"]


def _ecran(text: str, aujourd_hui: date | None = None) -> str:
    """Calcule l'écran USSD à afficher à partir de tout ce qui a été tapé."""
    choix = rejouer_saisies(text)
    etape = len(choix)

    # Écran 1 : langue
    if etape == 0:
        return menu(t("titre_langue", "fr"), NOMS_LANGUES)
    i_langue = choix_valide(choix[0], len(LANGUES))
    if i_langue is None:
        return "END " + t("choix_invalide", "fr")
    langue = LANGUES[i_langue]
    retour = t("retour", langue)

    # Écran 2 : produit
    liste_produits = prix.produits()
    noms = [nom_produit(p, langue) for p in liste_produits]
    if etape == 1:
        return menu(t("titre_produit", langue), noms, retour)
    i_produit = choix_valide(choix[1], len(liste_produits))
    if i_produit is None:
        return "END " + t("choix_invalide", langue)
    produit = {**liste_produits[i_produit], "nom": noms[i_produit]}

    # Écran 3 : unité
    if etape == 2:
        return menu(
            t("titre_unite", langue, produit=produit["nom"]),
            [t(f"unite_{u}", langue) for u in prix.UNITES],
            retour,
        )
    i_unite = choix_valide(choix[2], len(prix.UNITES))
    if i_unite is None:
        return "END " + t("choix_invalide", langue)
    unite = prix.UNITES[i_unite]

    # Écran 4 : zone
    liste_localites = prix.localites()
    if etape == 3:
        return menu(t("titre_zone", langue), liste_localites, retour)
    i_localite = choix_valide(choix[3], len(liste_localites))
    if i_localite is None:
        return "END " + t("choix_invalide", langue)
    localite = liste_localites[i_localite]

    # Écran 5 : offre de l'acheteur
    if etape == 4:
        return "CON " + t("question_offre", langue, unite=unite)
    saisie_offre = choix[4].replace(" ", "")
    if not saisie_offre.isdigit():
        return "END " + t("montant_invalide", langue)

    # Écran final : résultat
    return resultat(produit, unite, localite, int(saisie_offre), aujourd_hui, langue)


def pied_de_resultat(
    meilleur: prix.PrixMarche, offre: int, cout: int | None, langue: str = "fr"
) -> str:
    """Dernière ligne : comparaison avec l'offre, et alerte sur le coût de revient."""
    if offre <= 0:
        return t("pied_decider", langue)
    ecart = meilleur.net - offre
    if ecart > 0:
        pied = t(
            "pied_sous",
            langue,
            offre=formater_fcfa(offre),
            ecart=formater_fcfa(ecart),
            marche=meilleur.marche,
        )
    else:
        pied = t("pied_egale", langue, offre=formater_fcfa(offre))
    if cout is not None and offre < cout:
        pied += "\n" + t("alerte_cout", langue, cout=formater_fcfa(cout))
    return pied


def resultat(
    produit: dict[str, str],
    unite: str,
    localite: str,
    offre: int,
    aujourd_hui: date | None,
    langue: str = "fr",
) -> str:
    """Écran final : net après frais par marché, du meilleur au moins bon."""
    res = prix.chercher_prix(produit["code"], unite, localite, aujourd_hui)
    marches = res["resultats"]

    if not marches:
        # Règle du DAT : on ne devine jamais un prix.
        return "END " + t(
            "aucun_prix",
            langue,
            jours=str(prix.MAX_AGE_JOURS),
            produit=produit["nom"],
            unite=unite,
            localite=localite,
        )

    entete = t("entete_resultat", langue, produit=produit["nom"], unite=unite)
    pied = pied_de_resultat(
        marches[0], offre, prix.cout_revient(produit["code"], unite), langue
    )

    # On ajoute des marchés tant que l'écran ne dépasse pas la limite.
    lignes: list[str] = []
    for p in marches:
        ligne = f"{p.marche} {formater_fcfa(p.net)} ({formater_date(p.date_releve)})"
        essai = "\n".join([entete, *lignes, ligne, pied])
        if len("END " + essai) > LIMITE_CARACTERES:
            break
        lignes.append(ligne)

    return "END " + "\n".join([entete, *lignes, pied])
