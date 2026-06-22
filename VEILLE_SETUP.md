# Veille MASARE — Guide d'Automatisation

## Vue d'ensemble

Système de veille distressed **entièrement automatisé** pour MASARE.

### Processus quotidien (6 étapes)

```
BODACC API → Recoupement Web → Recherche Contacts → Scoring → Rapport → GitHub Issues
```

**Exécution** : 08:00 CET (ou sur demande)

## Architecture

### 1. Scripts principaux

| Fichier | Rôle |
|---------|------|
| `veille_masare_prod.py` | Script Python principal — 6 étapes complètes |
| `daily_veille.sh` | Wrapper shell — exécution, logs, git push |
| `.github/workflows/daily-veille.yml` | GitHub Actions — automatisation cloud |

### 2. Flux de données

```
ÉTAPE 1: BODACC API
├─ URL: https://bodacc-datadila.opendatasoft.com/api/
├─ Filtre: NAF + Procédures collectives
└─ Output: 0-100 dossiers/jour

ÉTAPE 2: Recoupement Web
├─ Query 1: BODACC + Infogreffe (redressement, liquidation)
├─ Query 2: Presse (distressed stories, 48h)
└─ Query 3: Notoriété (CA historique > 20M€)

ÉTAPE 3: Recherche Contacts
├─ Dirigeants (Pappers/Societe.com/LinkedIn)
├─ Mandataires (CNAJMJ)
├─ Actionnaires (Infogreffe, presse)
└─ Avocat/Conseil

ÉTAPE 4: Scoring MASARE (0-10)
├─ Actifs tangibles (0-3 pts)
├─ EBITDA historique (0-2 pts)
├─ Potentiel retournement (0-2 pts)
├─ Taille ticket (0-2 pts)
└─ Souveraineté/Stratégique (0-1 pt)

ÉTAPE 5: Génération Rapport
└─ Format: rapport_YYYYMMDD.md

ÉTAPE 6: GitHub Issues
├─ Si score ≥ 8 : Créer Issue ALERTE
└─ Label: alert-{urgence}
```

### 3. Critères de filtrage

**Score ≥ 6** : Rapport seulement  
**Score ≥ 8** : Rapport + GitHub Issue (ALERTE)

**Urgence** :
- `haute` : Liquidation judiciaire ou RJ imminente
- `moyenne` : Sauvegarde
- `faible` : Surveillance

## Installation

### Option A : Exécution locale (crontab)

```bash
# 1. Clone
git clone https://github.com/matsaunder/masare-veille.git
cd masare-veille

# 2. Permissions
chmod +x daily_veille.sh veille_masare_prod.py

# 3. Ajouter crontab
crontab -e
# Ajouter ligne :
# 0 8 * * * cd /home/user/Masare-veille && bash daily_veille.sh >> /tmp/masare-veille.log 2>&1

# 4. Tester
bash daily_veille.sh
```

### Option B : GitHub Actions (recommandé)

L'automation s'exécute automatiquement sur les serveurs GitHub.

**Setup** :
1. Push le repo sur GitHub
2. Vérifier `.github/workflows/daily-veille.yml` est actif
3. Vérifier que `GH_TOKEN` est disponible pour créer des issues

## Configuration requise

### Environnement local

```bash
# Python 3.9+
python3 --version

# GitHub CLI (pour créer les issues)
gh --version
gh auth login  # Une fois

# Git
git config user.email "your@email.com"
git config user.name "Your Name"
```

### Permissions Git

Branch développement : `claude/quirky-planck-l22gyq`  
Push automatique inclus dans `daily_veille.sh`

## Output

### Rapport (`rapport_YYYYMMDD.md`)

Markdown structuré avec :
- Résumé : nombre dossiers, scores, flags
- Dossiers retenus : fiches détaillées (score, contacts, synthèse)
- Tableau dossiers exclus

### GitHub Issues

**Titre** : `ALERTE [URGENT/STANDARD] — {Nom} — Score X/10 — {Secteur}`

**Labels** : `alert-haute`, `alert-moyenne`

**Body** : Fiche MASARE complète + tableau contacts + synthèse

## Maintenance

### Logs

```bash
# Voir les derniers logs
ls -lt /tmp/masare-veille-logs/ | head -5
tail -f /tmp/masare-veille-logs/veille_*.log
```

### Debug

```bash
# Exécution en verbose
python3 veille_masare_prod.py 2>&1

# Test BODACC API
python3 -c "
import urllib.request, json
url = 'https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records?limit=5'
req = urllib.request.Request(url, headers={'User-Agent': 'MASARE'})
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read())
    print(f'API OK — Total records: {data[\"total_count\"]}')
"

# Test GitHub CLI
gh issue list --repo matsaunder/masare-veille
```

### Amélioration future

**Phase 2** : Intégration WebFetch pour recherches web  
**Phase 3** : API Pappers/Societe.com pour enrichissement contacts  
**Phase 4** : ML scoring automatique (modèle entraîné sur historique)  
**Phase 5** : Alertes Slack/Email + Dashboard web

## Support

- Erreurs BODACC API : Vérifier connectivité, rate-limiting
- Erreurs GitHub CLI : `gh auth login` et vérifier permissions
- Logs : `/tmp/masare-veille-logs/`

---

**Dernière mise à jour** : 2026-06-22  
**Mainteneur** : MASARE SAS (Claude Code)
