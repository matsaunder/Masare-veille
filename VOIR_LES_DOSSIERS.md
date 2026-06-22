# 📊 Comment Voir les Dossiers MASARE Proposés

## Situation actuelle

L'API BODACC contient surtout des **dépôts de comptes** (janvier 2025), pas les procédures collectives (RJ/LJ).

Les **vraies opportunités distressed** doivent être cherchées sur :

---

## 3 MÉTHODES POUR VOIR LES DOSSIERS

### 📱 MÉTHODE 1 : Sites publics (Instant)

#### 1. Infogreffe.fr
```
https://www.infogreffe.fr/
→ Recherche par : nom entreprise, SIREN
→ Filtre : "Procédures collectives en cours"
→ Affiche : Dates, mandataire, tribunal
```

#### 2. BODACC.fr (Manuel)
```
https://www.bodacc.fr/
→ Menu : "Procédures collectives"
→ Filtre par : Date, secteur, tribunal
→ Export : PDF des annonces
```

#### 3. Infogreffe Alertes
```
https://www.infogreffe.fr/alertes
→ Surveillance automatique par secteur
→ Notifications email quotidiennes
```

---

### 💻 MÉTHODE 2 : Script Python (Démonstration)

Voir les **dossiers de test** du rapport existant :

```bash
# Afficher rapport du 19 juin 2026
$ cat rapport_20260619.md

# Ou les afficher formatés (5 dossiers d'exemple) :
$ python3 << 'EOF'
import json

dossiers = [
    {
        "nom": "AEROTECH COMPOSITES SAS",
        "siren": "412897563",
        "score": 9,
        "secteur": "Défense & Aéronautique",
        "procedure": "Redressement judiciaire",
        "ca_m": 38,
        "urgence": "HAUTE",
    },
    {
        "nom": "PHARMA INNOV LABS",
        "siren": "455123789",
        "score": 8,
        "secteur": "Santé & Pharma",
        "procedure": "Redressement judiciaire",
        "ca_m": 5,
        "urgence": "HAUTE",
    },
    {
        "nom": "MECANICA PRECISION SARL",
        "siren": "328541102",
        "score": 7,
        "secteur": "Industrie manufacturière",
        "procedure": "Liquidation judiciaire",
        "ca_m": 8,
        "urgence": "HAUTE",
    },
]

print("\n" + "="*80)
print("🎯 DOSSIERS MASARE PROPOSÉS (Exemples)")
print("="*80 + "\n")

for d in sorted(dossiers, key=lambda x: -x['score']):
    icon = "🔴" if d['score'] >= 8 else "🟠" if d['score'] >= 6 else "🟡"
    print(f"{icon} [{d['urgence']}] {d['nom']}")
    print(f"   Score: {d['score']}/10 | SIREN: {d['siren']} | CA: {d['ca_m']}M€")
    print(f"   Secteur: {d['secteur']} | Procédure: {d['procedure']}\n")

EOF
```

---

### 🤖 MÉTHODE 3 : Script Python Automatisé (Production)

Pour exécuter le script de veille complète :

```bash
# Option A : Voir les dossiers du dernier rapport généré
$ cat rapport_$(date +%Y%m%d).md

# Option B : Générer un nouveau rapport (vide si pas de données)
$ python3 veille_masare_prod.py

# Option C : Voir rapport brut avec tous les détails
$ python3 << 'EOF'
import os
import glob

# Trouver le rapport le plus récent
rapports = sorted(glob.glob("rapport_*.md"), reverse=True)
if rapports:
    with open(rapports[0]) as f:
        print(f.read())
else:
    print("Aucun rapport trouvé. Exécuter : python3 veille_masare_prod.py")

EOF
```

---

## 🔍 OÙ CHERCHER LES PROCÉDURES COLLECTIVES (Maintenant)

### Sites recommandés :

| Site | Couverture | Actualité | Interface |
|------|-----------|-----------|-----------|
| **Infogreffe.fr** | France entière | Temps réel | 🟢 Excellente |
| **BODACC.fr** | France entière | 24-48h | 🟡 Complexe |
| **Societe.com** | France + Bilans | Bilans annuels | 🟢 Très bonne |
| **Pappers.fr** | France + Infos | Temps réel | 🟢 Excellente |
| **Capitaine Contract** | Marché sec. | Temps réel | 🟠 Payant |

---

## 📋 SECTEURS À SURVEILLER (MASARE TIER 1)

```
🎯 Défense & Aéronautique
   → Infogreffe : NAF 3030Z, 2811Z, 2829B
   → Alerte : Diminution carnet commandes Airbus/Dassault

🔐 Cybersécurité & Défense
   → Infogreffe : NAF 6201Z, 6202A, 6209Z, 7219Z
   → Alerte : Secteur en consolidation active

🏭 Industrie lourde manufacturière
   → Infogreffe : NAF 2511Z, 2512Z, 2550A, 2562B
   → Alerte : Cotation délicate post-crise énergétique
```

---

## 🚀 AUTOMATISER LA VEILLE (Option Meilleure)

Pour **recevoir alertes quotidiennes** :

### A. Infogreffe Alertes (Gratuit)
```
1. aller sur https://www.infogreffe.fr/alertes
2. Créer alertes par secteur (NAF)
3. Recevoir emails quotidiens
4. Filtrer score MASARE manuellement
```

### B. BODACC Abonnement (Payant)
```
1. S'abonner à flux BODACC.fr
2. Filtrer par procédures collectives
3. Importer données → veille_masare_prod.py
```

### C. Cron + Script (Recommandé)
```bash
# Configurer crontab
crontab -e

# Ajouter ligne :
0 8 * * * bash daily_veille.sh >> /tmp/masare-veille.log 2>&1

# Le script se déclenche chaque matin à 08:00
```

---

## 📲 WORKFLOW PROPOSÉ (Quotidien)

```
[08:00] → Cron déclenche script Python
    ↓
[08:05] → Scrape Infogreffe + BODACC API
    ↓
[08:10] → Score chaque dossier (MASARE 0-10)
    ↓
[08:15] → Génère rapport_YYYYMMDD.md
    ↓
[08:20] → Si score ≥ 8 : Crée GitHub Issue (ALERTE)
    ↓
[08:25] → Git push rapport sur branche dev
    ↓
✅ Rapport disponible : cat rapport_YYYYMMDD.md
```

---

## 🔗 LIENS DIRECTS

**Sites de recherche** :
- Infogreffe : https://www.infogreffe.fr/recherche
- BODACC : https://www.bodacc.fr/
- Societe.com : https://www.societe.com/cgi-bin/advanced
- Pappers : https://www.pappers.fr/

**Filtres par NAF** :
- Aéronautique : `https://www.infogreffe.fr/recherche?codeNaf=3030Z`
- Défense : `https://www.infogreffe.fr/recherche?codeNaf=2811Z`
- Cyber : `https://www.infogreffe.fr/recherche?codeNaf=6201Z`

---

## 💡 ASTUCE

Pour voir les **prochains dossiers disponibles** :

```bash
# Exécuter le script chaque jour
watch -n 3600 'python3 veille_masare_prod.py && cat rapport_$(date +%Y%m%d).md'

# Ou via GitHub Actions (automatique)
# Les rapports s'accumulent dans le repo
ls -lt rapport_*.md | head -10
```

---

**Prêt ?** Choisir la méthode et commencer à surveiller !
