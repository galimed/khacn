# GALIMED — Licences commerciales

Ce document décrit les offres commerciales de la brique clinique GALIMED, la
procédure d'activation d'une licence, et la mise en place technique du
paiement. Les conditions juridiques complètes sont dans [LICENSE](LICENSE) ;
ce document ne s'y substitue pas.

Contact : **contact@groupe-businesstherapie.net** — https://galimedai.org

---

## 1. Offres

| | **Évaluation** | **Clinic** | **Enterprise** |
|---|---|---|---|
| Prix | Gratuit | Sur devis | Sur devis |
| Usage | Audit du code, tests, démonstration interne | Un établissement / cabinet, usage clinique | Plusieurs établissements, intégration éditeur |
| Scorings | 25 au total, puis blocage (`gate.py`) | Illimité | Illimité |
| Filigrane sur les résultats | Oui | Non | Non |
| Usage clinique ou commercial | **Interdit** (voir [LICENSE](LICENSE), Article 3) | Autorisé | Autorisé |
| Support | Communautaire (issues GitHub) | Support par email | Support prioritaire, SLA sur devis |
| Modules inclus | Tous (news2, qsofa, trend) | Tous | Tous, + conditions d'intégration/redistribution négociables |
| Durée de licence | — | Annuelle ou perpétuelle, au choix | Annuelle ou perpétuelle, au choix |

Le passage de 25 scorings gratuits n'est qu'une limite technique de
confort ; il ne vaut en aucun cas autorisation d'usage clinique ou
commercial en deçà de ce seuil (voir LICENSE, Article 2).

Pour un devis Clinic ou Enterprise, écrire à
contact@groupe-businesstherapie.net en précisant l'établissement, le volume
de scorings attendu, et les modules concernés.

---

## 2. Procédure d'activation

1. **Devis et accord** — le client convient d'une offre par email avec
   Groupe Business Thérapie.
2. **Paiement** — le client règle via un lien de paiement PayPal Business
   (facture ou paiement récurrent selon l'offre).
3. **Confirmation de paiement** — PayPal notifie le serveur GALIMED via un
   webhook `PAYMENT.CAPTURE.COMPLETED`. Le serveur **vérifie la signature du
   webhook avant toute action** (section 4) — un événement dont la
   signature ne peut être vérifiée est journalisé et rejeté, jamais traité
   comme un paiement confirmé.
4. **Émission de la licence** — une fois le webhook vérifié, le serveur
   (qui détient seul la clé privée Ed25519, jamais présente dans ce dépôt)
   appelle `licensing.issue_license()` avec le destinataire, la formule
   (`clinic` ou `enterprise`) et la date d'expiration convenue.
5. **Livraison** — la clé de licence est envoyée par email au client, avec
   les instructions de la section 5.
6. **Non-réception** — en l'absence de webhook (ex. réseau du client
   filtrant les notifications sortantes de PayPal), le paiement reste
   visible dans le tableau de bord PayPal ; une émission manuelle de la
   licence reste possible sur vérification directe du paiement.

---

## 3. Mise en place PayPal Business

1. Créer un compte **PayPal Business** sur paypal.com.
2. Dans le [PayPal Developer Dashboard](https://developer.paypal.com/), créer
   une application REST pour obtenir un `Client ID` et un `Client Secret`.
3. Créer un webhook pointant vers l'endpoint de réception du serveur
   GALIMED, abonné à l'événement `PAYMENT.CAPTURE.COMPLETED` (et
   `BILLING.SUBSCRIPTION.ACTIVATED` / `.CANCELLED` si des licences par
   abonnement sont proposées). Noter le `Webhook ID` généré.
4. **Stocker les identifiants uniquement en variables d'environnement**,
   jamais dans le dépôt :

   ```bash
   PAYPAL_CLIENT_ID=...
   PAYPAL_CLIENT_SECRET=...
   PAYPAL_WEBHOOK_ID=...
   PAYPAL_ENV=live   # ou "sandbox" en test
   ```

   Ces variables vivent dans le gestionnaire de secrets de l'environnement
   de production (jamais dans un fichier `.env` commité — voir `.gitignore`
   à la racine du dépôt, qui exclut déjà `__pycache__/`). Idem pour la clé
   privée Ed25519 utilisée par `licensing.issue_license()` : elle est
   générée une fois hors de ce dépôt et conservée dans le même
   gestionnaire de secrets, jamais en clair dans le code ou dans un commit.

5. Utiliser le sandbox PayPal (`PAYPAL_ENV=sandbox`) pour tout test
   d'intégration avant bascule en `live`.

---

## 4. Vérification obligatoire de la signature du webhook

Un webhook non authentifié est une invitation à forger des paiements. Avant
qu'un événement `PAYMENT.CAPTURE.COMPLETED` ne déclenche `issue_license()`,
le serveur doit impérativement :

1. Recevoir le corps brut de la requête et ses en-têtes
   (`Paypal-Transmission-Id`, `Paypal-Transmission-Time`,
   `Paypal-Transmission-Sig`, `Paypal-Cert-Url`, `Paypal-Auth-Algo`).
2. Appeler l'API PayPal `POST /v1/notifications/verify-webhook-signature`
   avec ces en-têtes, le corps de l'événement, et le `PAYPAL_WEBHOOK_ID`
   (jamais valider une signature localement sans repasser par cette API,
   sauf implémentation ultérieure explicitement auditée).
3. Ne traiter l'événement **que si** la réponse contient
   `"verification_status": "SUCCESS"`. Tout autre statut est rejeté et
   journalisé comme tentative suspecte.
4. Vérifier l'idempotence par l'identifiant de capture PayPal
   (`resource.id`) avant d'émettre une licence, pour qu'une notification
   PayPal retransmise (les webhooks PayPal peuvent être livrés plusieurs
   fois) ne déclenche pas une seconde émission.
5. Ne jamais émettre de licence sur la seule foi d'un montant ou d'un
   email présent dans le payload sans l'étape 2 : un attaquant qui connaît
   la forme du payload mais pas la signature ne doit jamais pouvoir
   obtenir de licence.

---

## 5. Activation côté client

Une fois la clé de licence reçue par email, le client la fournit à sa
brique GALIMED, par exemple :

```bash
export GALIMED_LICENSE_KEY="eyJ..."
```

```python
import os
from gate import Gate

gate = Gate(license_key=os.environ["GALIMED_LICENSE_KEY"])
assert gate.licensed
```

La vérification est entièrement locale et hors-ligne (voir
[licensing.py](licensing.py)) : aucune connexion réseau n'est nécessaire
pour valider la licence, y compris dans un environnement hospitalier isolé.
