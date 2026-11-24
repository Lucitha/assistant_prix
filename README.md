# Session 01 · Agriculture · Assistant Prix

## Le cas d'usage en une phrase
Pour Abel, producteur de maïs et de piment près de Savalou, qui vend souvent sous le prix du marché faute de connaître les prix du jour, notre solution lui donne depuis un téléphone simple le dernier prix relevé sur les marchés proches, converti dans son unité et diminué des frais, ce qui lui permet de négocier avec un argument chiffré et de décider lui-même où et à quel prix vendre.

## Le problème de départ
Face à l'offre d'un acheteur venu au champ, le producteur n'a ni prix du jour fiable, ni repère sur ses frais de vente, ni moyen de comparer ses options. Dans l'exemple du cadrage, un sac de maïs vendu 15 000 F au champ se vendait 25 000 F au marché.

## Ce que fait la solution

| Canal | État | Où |
|---|---|---|
| **USSD** (`*384*…#`, tout téléphone) | **Fonctionne** avec le sandbox Africa's Talking | `src/ussd.py`, route `POST /ussd` |
| **Lecture vocale** des écrans | Démo dans le navigateur (synthèse vocale en français) | `src/simulateur.html`, page `/simulateur` |
| **Appel vocal** | Simulation : renvoie le texte que le serveur vocal lirait | `src/channels.py`, route `POST /webhook/voice` |
| **Bot WhatsApp** | **Fonctionne** avec l'API WhatsApp Cloud de Meta, numéro de test (texte libre : « maïs 2 sacs 15000 ») ; route Twilio prête pour un compte payant | `src/whatsapp.py`, routes `/whatsapp/meta` et `/whatsapp` |

Tous les canaux utilisent **le même moteur** (`src/prix.py`), sans IA :
1. dernier relevé de **moins de 7 jours** sur chaque marché proche ; sinon, « aucun prix récent » : **aucun prix n'est deviné** ;
2. conversion dans l'unité du producteur (sac, bassine, bol, kg) ;
3. **net = prix − transport − manutention − taxe de marché** ;
4. écart avec l'offre de l'acheteur, alerte si l'offre est **sous le coût de revient** ;
5. chaque chiffre garde sa date et sa source. Le producteur reste seul à décider.

## Lancer le projet
```bash
cd 01-agriculture
pip install -r requirements.txt
black .
pytest -x
python -m uvicorn src.app:app --reload
```
Puis ouvrir http://127.0.0.1:8000/simulateur (USSD avec lecture vocale) et http://127.0.0.1:8000/docs (API).

## Les données (`data/`)

| Fichier | Contenu | État |
|---|---|---|
| `prix.csv` | Relevés : produit, marché, unité, prix, type, date, source | **Démonstration** ; demande d'accès aux données AgroFlux envoyée le 23/11/2026 |
| `poids_unites.csv` | Poids moyen d'un sac, d'une bassine, d'un bol par produit | Hypothèses **à valider** par le groupement |
| `zones.csv` | Marchés proches de chaque localité, transport par kg | Hypothèses à valider |
| `frais_marche.csv` | Manutention et taxe par kg, par marché | Hypothèses à valider |
| `cout_revient.csv` | Coût de revient par kg et par produit | Hypothèses à valider avec SLAC |
| `produits.csv`, `marches.csv` | Référentiels | |

Après toute modification : `python -m src.verifier` (formats, dates, unités, fraîcheur des prix).

## Guide pas à pas
Installation, tunnel, Azure, WhatsApp, GitHub et démo : [`docs/GUIDE.md`](docs/GUIDE.md).

## Limites assumées et suite
Voir [`docs/architecture_et_limites.md`](docs/architecture_et_limites.md).
