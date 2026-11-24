# Architecture et limites assumées · Session 01 Agriculture

## Architecture du MVP
```
Téléphone simple ──USSD──> Africa's Talking (sandbox) ──POST /ussd──┐
WhatsApp ──> Meta (numéro de test) ──POST /whatsapp/meta ──────────┤
Navigateur ──/simulateur (écran + lecture vocale)───────────────────┤
Démo API ──/webhook/voice, /webhook/whatsapp (simulations JSON)─────┤
                                                                     ▼
                                             FastAPI (src/app.py)
                                   ussd.py · whatsapp.py · channels.py · fon_assistant.py
                                                     │
                                         prix.py (moteur, sans IA)
                                                     │
                                         data/*.csv (prix, poids, frais)
```
Hébergement : Render (offre gratuite, sans carte bancaire), déployé depuis GitHub ; une visite automatique toutes les 10 minutes (cron-job.org) empêche la mise en veille. Journal des requêtes avec numéros masqués (HMAC-SHA256, clé dans les variables d'environnement).

## Principes
- **Aucun chiffre produit par une IA** : prix, conversions et frais viennent des données et du code.
- **Aucun prix deviné** : au-delà de 7 jours, un relevé n'est plus annoncé.
- **Le producteur décide** : la solution donne un repère daté et sourcé, sans conseil de vente.

## Limites assumées et suite prévue

| Sujet | Situation au 24/11/2026 | Suite |
|---|---|---|
| Prix réels | Données de démonstration ; AgroFlux (10 marchés dont Glazoué) n'a pas d'API publique, accès demandé le 23/11 | Import des données AgroFlux, puis agents de collecte pour les marchés non couverts |
| USSD au Bénin | Testé sur le simulateur Africa's Talking avec un numéro de test | Code USSD réel : accord avec MTN ou Moov, ou agrégateur couvrant le Bénin (numéros à 10 chiffres en 01) |
| Appel vocal | Le sandbox Africa's Talking ne gère pas la voix | Numéro vocal de production, menu à touches |
| WhatsApp | Bot réel via l'API WhatsApp Cloud de Meta en mode test : 5 numéros destinataires, jeton de 24 h. Twilio refuse les comptes d'essai au Bénin ; Africa's Talking est payant | Numéro WhatsApp vérifié au nom de SLAC, jeton permanent ; messages vocaux en fon |
| Voix en fon | Lecture en français seulement ; mots fon de `fon_assistant.py` à valider | Piste **J'aime Ma Langue** (ASIN/IIDiA) : corpus fon ouvert, classement FonBench, démo AgriFon à étudier ; phrases enregistrées par un locuteur fon ; les nombres en fon ne sont pas en base 10 et demandent une validation |
| Poids, frais, coûts | Hypothèses | Validation par SLAC et le groupement (pesées) |
