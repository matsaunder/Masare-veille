# 🔄 Système de Déduplication MASARE

## Problème résolu

**Avant** : Plusieurs issues pour la même société avec descriptions différentes
```
❌ Issue #1: AEROTECH — Score 9/10 — CA 38M€
❌ Issue #2: AEROTECH — Score 9/10 — CA 35M€  ← Doublon !
❌ Issue #3: AEROTECH — Score 9/10 — CA 38M€  ← Doublon !
```

**Après** : Une seule issue harmonisée, mise à jour
```
✅ Issue #1: AEROTECH — Score 9/10 — CA 38M€ — Mis à jour 2026-06-22 14:30
   (La description est harmonisée à chaque veille)
```

---

## Comment ça fonctionne

### Logique de déduplication

```
Pour chaque dossier (score ≥ 8):
  ↓
  1. Chercher issue existante avec même SIREN
     ↓
  2. Si trouvée → METTRE À JOUR la description
     ↓
  3. Si pas trouvée → CRÉER nouvelle issue
     ↓
  4. Tous les champs harmonisés (description, labels, etc.)
```

### Détection par SIREN

Le SIREN (numéro unique entreprise) est le critère principal :
- `AEROTECH COMPOSITES` SIREN `412897563` = toujours la même entité
- La description peut changer (CA, effectif, etc.) mais c'est la MÊME société

### Mise à jour automatique

À chaque veille, l'issue existante est mise à jour avec :
- ✅ Nouveau score (si changement)
- ✅ Informations actualisées
- ✅ Timestamp "Mis à jour : YYYY-MM-DD HH:MM"
- ✅ Labels harmonisés

---

## Implémentation

### Fichiers

- `veille_masare.py` — Script principal (v3 avec déduplication intégrée)
- `deduplicate_issues.py` — Utilitaire standalone (optionnel)

### Fonctions clés

```python
# 1. Chercher issue existante
existing = find_existing_issue(siren="412897563", token=TOKEN)

# 2. Si existe → Mettre à jour
if existing:
    update_github_issue(
        issue_num=existing["number"],
        titre="ALERTE [URGENT] — AEROTECH...",
        corps="...",
        labels=["alert-haute", "score-9", "BITD"],
        token=TOKEN
    )
else:
    # 3. Sinon → Créer nouvelle
    create_github_issue(dossier)
```

---

## Résultats visibles sur GitHub

### Avant (Sans déduplication)
```
Issues (3 ouvertes)
├─ #1  ALERTE — AEROTECH — Score 9 — CA 38M€
├─ #2  ALERTE — AEROTECH — Score 9 — CA 35M€ ← Obsolète
└─ #3  ALERTE — AEROTECH — Score 9 — CA 38M€ ← Doublon

History = Confusion, actions dupliquées
```

### Après (Avec déduplication)
```
Issues (1 ouvert)
├─ #1  ALERTE — AEROTECH — Score 9 — CA 38M€
│      Mis à jour 2026-06-22 14:30
│      Mis à jour 2026-06-23 08:00
│      Mis à jour 2026-06-24 08:15
│
└─ #2  ALERTE — PHARMA INNOV — Score 8 — CA ND
       (Autre dossier, pas de conflit)

History = Clair, une action par dossier
```

---

## Avantages

| Aspect | Avant | Après |
|--------|-------|-------|
| **Doublons** | 3-5 issues/dossier | 1 issue/dossier |
| **Harmonisation** | ❌ Descriptions divergentes | ✅ Harmonisée |
| **Traçabilité** | ❌ Confuse | ✅ Historique clair (GitHub timestamps) |
| **Actions** | ❌ Dupliquées | ✅ Une seule action par dossier |
| **Maintenance** | ❌ Fastidieuse | ✅ Automatisée |

---

## Test local

```bash
# Lancer 2 fois le script
GITHUB_TOKEN="token" python3 veille_masare.py
# → Issue créée #N

GITHUB_TOKEN="token" python3 veille_masare.py
# → Issue #N mise à jour (pas d'issue #N+1)
```

### Résultat attendu
```
🚀 MASARE Veille

🔔 ÉTAPE 6 — Issues GitHub...
   🔄 Issue #8 mise à jour: ALERTE [URGENT] — AEROTECH...
   ✓ Issue #9 créée: ALERTE [URGENT] — PHARMA...
   ✓ 2 issues gérées (score ≥ 8) — Pas de doublons

✅ Veille complète
```

---

## Champs harmonisés à chaque mise à jour

```markdown
## {nom}

**SIREN** : {siren}
**Score MASARE** : {score}/10
**Urgence** : {urgence}
**Mis à jour** : {datetime}  ← Timestamp mis à jour

| Champ | Valeur |
|-------|--------|
| Procédure | {procedure} |
| Tribunal | {tribunal} |
| Secteur | {naf_label} |
| CA | {ca_estim} M€ |
| Effectif | {effectif} |
| EBITDA | {ebitda} |
| Actifs | {actifs} |
| BITD | {flag_bitd} |
| Marque | {flag_marque} |
```

Tous les champs sont réaffectés à chaque veille → **Cohérence garantie**

---

## Limitations & Notes

- ⚠️ Détection par SIREN uniquement (pas par nom)
  → Si SIREN manquant → créer doublon
  → Solution : toujours avoir SIREN en BODACC

- ⚠️ Ne fermera pas les issues "obsolètes"
  → Issues existantes restent ouvertes
  → À fermer manuellement si dossier sortis (score < 8)

- ✅ Idempotent : Exécuter 10x = même résultat
  → Sûr pour crontab/GitHub Actions

---

## Prochaine étape

Pour éradiquer les **doublons existants** sur GitHub :
```bash
# Script de nettoyage (à créer)
python3 cleanup_duplicate_issues.py
```

Cela trouverait les issues dupliquées et les fusionnerait automatiquement.

---

**Résumé** : ✅ Déduplication automatique intégrée
- Pas d'issue dupliquée
- Harmonisation automatique
- Une source de vérité par dossier
