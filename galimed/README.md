# GALIMED — brique clinique

Brique clinique open-source de [GALIMED AI](https://galimedai.org),
plateforme de pré-diagnostic assisté par IA de Groupe Business Thérapie.

Ce dossier implémente, en Python pur et sans dépendance tierce, des scores
cliniques publiés et un système de licence qui protège leur exploitation
commerciale. Le code est source-disponible et auditable par tous ; son
usage clinique ou commercial requiert une licence (voir
[LICENSE](LICENSE) et [COMMERCIAL.md](COMMERCIAL.md)).

## Pourquoi du code pur, sans dépendance

Cette brique doit pouvoir tourner sur un poste hospitalier isolé, sans
`pip install`. Tout ici — le calcul des scores comme les primitives
cryptographiques de la licence (Keccak-256, Ed25519) — est réimplémenté à
partir des spécifications publiées, avec une bibliothèque standard Python
uniquement.

## Modules

**Cœur clinique** — pur, testable sans aucune restriction commerciale :

- [`news2.py`](news2.py) — score NEWS2 (Royal College of Physicians, 2017),
  détection précoce de dégradation clinique.
- [`qsofa.py`](qsofa.py) — score qSOFA (Sepsis-3), dépistage du risque lié
  au sepsis. Réutilise les types de `news2.py` plutôt que d'en redéfinir.
- [`trend.py`](trend.py) — détection de dégradation sur une série de
  scores NEWS2 dans le temps (voir le module pour la justification des
  seuils, qui sont un ajout GALIMED documenté et non une règle officielle
  NEWS2).

**Licence et couche commerciale** — séparées du cœur clinique :

- [`ed25519.py`](ed25519.py) — Ed25519 (RFC 8032), signatures numériques.
  S'auto-teste contre les vecteurs de test publiés à l'import ; refuse de
  fonctionner si l'auto-test échoue.
- [`licensing.py`](licensing.py) — émission et vérification hors-ligne de
  clés de licence signées.
- [`gate.py`](gate.py) — plafond de 25 scorings gratuits, filigrane, et
  déblocage illimité avec une licence valide. Enveloppe n'importe quelle
  fonction de scoring (NEWS2, qSOFA) sans que celle-ci ait à en avoir
  connaissance.

**Garde-fou d'intégrité** (dans [`../tools/`](../tools/)) :

- `tools/keccak.py`, `tools/verify_integrity.py` — Keccak-256 / EIP-55
  réimplémentés from scratch, pour vérifier que l'adresse du contrat KHACN
  publiée dans le dépôt n'a pas été substituée.

## Lancer les tests

Bibliothèque standard uniquement — aucune installation requise.

```bash
cd galimed
python -m unittest discover -v
```

Chaque module a sa suite de tests dédiée (`test_news2.py`, `test_qsofa.py`,
`test_trend.py`, `test_ed25519.py`, `test_licensing.py`, `test_gate.py`),
exécutable individuellement :

```bash
python -m unittest test_news2 -v
```

Les tests de licence exercent explicitement les cas de rejet : clé
altérée, clé signée par une autre clé privée, clé expirée — les trois
doivent échouer, jamais passer silencieusement.

## Avertissement clinique

**Ces modules sont des aides au tri et à la surveillance. Ce ne sont pas
des diagnostics et ils ne remplacent jamais le jugement clinique.**

- NEWS2 et qSOFA ne sont validés que pour les populations et conditions
  d'usage décrites dans leurs sources respectives ; voir les docstrings de
  `news2.py` et `qsofa.py` pour les limites explicites (grossesse, âge,
  sensibilité du qSOFA, etc.).
- Le module `trend.py` implémente un seuil de dégradation qui est un ajout
  GALIMED, pas une règle officielle NEWS2 — voir sa docstring pour le
  détail des choix de conception.
- Aucun de ces modules n'est un dispositif médical au sens du règlement
  européen 2017/745 (MDR) ni n'a fait l'objet d'une évaluation FDA (voir
  [LICENSE](LICENSE), Article 5).
- Un score bas ne doit jamais faire écarter une inquiétude clinique.

## Aller plus loin

Cette brique est un composant parmi d'autres de la plateforme GALIMED AI.
Pour un déploiement clinique, une licence Clinic/Enterprise, ou en savoir
plus sur la plateforme complète : **https://galimedai.org**
