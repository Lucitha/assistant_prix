# Assistant Prix · Session 01 Agriculture

## Le cas d'usage en une phrase
Pour Abel, producteur de maïs et de piment près de Savalou, qui vend souvent sous le prix du marché faute de connaître les prix du jour, notre solution lui donne depuis un téléphone simple le dernier prix relevé sur les marchés proches, converti dans son unité et diminué des frais, ce qui lui permet de négocier avec un argument chiffré et de décider lui-même où et à quel prix vendre.

## Le problème de départ
Face à l'offre d'un acheteur venu au champ, le producteur n'a ni prix du jour fiable, ni repère sur ses frais de vente, ni moyen de comparer ses options. Dans l'exemple du cadrage, un sac de maïs vendu 15 000 F au champ se vendait 25 000 F au marché.

## Ce que fait la solution

| Canal | État | Où |
|---|---|---|
| **USSD** (`*384*3328#`, tout téléphone) | **Fonctionne** avec le sandbox Africa's Talking, en français et en fongbè | `src/ussd.py`, route `POST /ussd` |
| **Lecture vocale** des écrans | Démo dans le navigateur, en français (aucune voix fon disponible) | `src/simulateur.html`, page `/simulateur` |
| **Bot WhatsApp** | **Fonctionne** avec l'API WhatsApp Cloud de Meta (numéro de test) : texte libre « maïs 2 sacs 15000 » ; route Twilio prête pour un compte payant | `src/whatsapp.py`, routes `/whatsapp/meta` et `/whatsapp` |
| **Appel vocal** | Simulation : renvoie le texte que le serveur vocal lirait | `src/channels.py`, route `POST /webhook/voice` |

Tous les canaux utilisent **le même moteur** (`src/prix.py`), **sans IA** :
1. dernier relevé de **moins de 7 jours** sur chaque marché proche ; sinon, « aucun prix récent » : **aucun prix n'est deviné** ;
2. conversion dans l'unité du producteur (sac, bassine, bol, kg) ;
3. **net = prix − transport − manutention − taxe de marché** ;
4. écart avec l'offre de l'acheteur, et alerte si l'offre est **sous le coût de revient** ;
5. chaque chiffre garde sa date et sa source. Le producteur reste seul à décider.

## Démarrage rapide (Windows, PowerShell)
```powershell
cd C:\wamp64\www\cours\isheero\assistant_prix
.\..venv-prix\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.verifier      # « Données valides »
black .
pytest                      # 49 passed
python -m uvicorn src.app:app --reload
```
Puis ouvrir :
- http://127.0.0.1:8000/simulateur : téléphone USSD avec lecture vocale ;
- http://127.0.0.1:8000/docs : documentation de l'API, chaque route y est testable.

Prérequis : Python 3.11 ou plus (testé avec Python 3.13). Pas à pas complet, tunnel, Render, WhatsApp et démo : [`docs/GUIDE.md`](docs/GUIDE.md).

## Organisation du dossier
```
assistant_prix/
├── src/
│   ├── app.py             routes web FastAPI et journal (numéros masqués)
│   ├── prix.py            moteur de prix et de calcul, sans IA
│   ├── ussd.py            écrans USSD (français / fongbè)
│   ├── whatsapp.py        bot WhatsApp (Meta, Twilio)
│   ├── channels.py        réponses WhatsApp et appel construites sur le moteur
│   ├── fon_assistant.py   compréhension d'une demande libre (mots-clés)
│   ├── verifier.py        contrôle des fichiers CSV
│   └── simulateur.html    téléphone USSD dans le navigateur
├── data/                  données CSV (voir plus bas)
├── tests/test_solution.py tests automatiques (pytest)
├── docs/                  GUIDE.md, architecture_et_limites.md
├── requirements.txt
└── pyproject.toml
```

## Routes de l'API

| Route | Rôle |
|---|---|
| `GET /sante`, `GET /health` | Supervision : le service répond |
| `POST /ussd` | Appelée par Africa's Talking à chaque saisie USSD |
| `GET /simulateur`, `POST /simulateur/ussd` | Simulateur USSD du navigateur |
| `GET /prix?produit=mais&unite=sac&localite=Savalou&offre=15000` | Même calcul, en JSON |
| `GET /whatsapp/meta`, `POST /whatsapp/meta` | Vérification et messages du webhook Meta |
| `POST /whatsapp` | Webhook Twilio (compte payant) |
| `POST /webhook/whatsapp`, `POST /webhook/voice` | Simulations JSON des canaux WhatsApp et appel |
| `GET /` | Liens utiles pour tester |

## Les données (`data/`)

| Fichier | Contenu | État |
|---|---|---|
| `prix.csv` | Relevés : produit, marché, unité, prix, type, date, source | **Démonstration** (source `DEMO`), valables jusqu'au 27-28/11/2026 ; accès aux données AgroFlux demandé le 23/11/2026 |
| `poids_unites.csv` | Poids moyen d'un sac, d'une bassine, d'un bol par produit | Hypothèses **à valider** par le groupement |
| `zones.csv` | Marchés proches de chaque localité, distance, transport par kg | Hypothèses à valider |
| `frais_marche.csv` | Manutention et taxe par kg, par marché | Hypothèses à valider |
| `cout_revient.csv` | Coût de revient par kg et par produit | Hypothèses à valider avec SLAC |
| `textes_ussd.csv` | Textes du menu USSD, colonnes `fr` et `fon` | Traductions fon proposées, **à valider** par un locuteur |
| `produits.csv`, `marches.csv` | Référentiels | |
| `journal.csv` | Journal des requêtes, créé par le serveur | Non versionné |

Les CSV sont relus à chaque requête : une modification est prise en compte sans redémarrer le serveur. **Après toute modification, lancer `python -m src.verifier`** : il contrôle les colonnes, les formats, les dates, les unités, les `{variables}` des textes fon et la fraîcheur des prix.

Règles pour éviter les erreurs :
- modifier les CSV avec **VS Code**, pas Excel (Excel change les dates et l'encodage) ;
- une phrase qui contient une virgule se met **entre guillemets** ;
- dans `textes_ussd.csv`, ne **jamais traduire** les mots entre accolades (`{produit}`, `{offre}`…).

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `CLE_SECRETE` | Clé HMAC pour masquer les numéros dans le journal | valeur de développement : **à changer en ligne** |
| `JOURNAL_PATH` | Emplacement du journal | `data/journal.csv` |
| `DATA_DIR` | Dossier des CSV | `data/` |
| `MAX_AGE_JOURS` | Âge maximal d'un prix annoncé | `7` |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Bot WhatsApp Meta | vides |
| `GRAPH_API_VERSION` | Version de l'API de Meta | `v23.0` |
| `TWILIO_AUTH_TOKEN`, `WHATSAPP_WEBHOOK_URL` | Signature des requêtes Twilio | vides |

## Limites assumées et suite
Voir [`docs/architecture_et_limites.md`](docs/architecture_et_limites.md) : prix réels (AgroFlux), code USSD réel au Bénin, appel vocal, voix en fon, validation des hypothèses.

