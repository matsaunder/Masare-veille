"""
MASARE — Déduplication et nettoyage des issues GitHub
Étapes :
  0. Patcher les issues existantes sans lien Pappers (one-time migration)
  1. Fermer les issues auto-générées score < SCORE_MIN
  2. Fermer les issues auto-générées "Non classifié" (résidus ancien scoring)
  3. Fermer les issues auto-générées ancien format (sans analyse IA ni données financières)
  4. Dédupliquer les issues restantes par nom normalisé
"""

import os
import re
import unicodedata
import requests
from collections import defaultdict

REPO = os.environ.get("GITHUB_REPO", "matsaunder/Masare-veille")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
BASE_URL = f"https://api.github.com/repos/{REPO}"

SCORE_MIN = 14  # Doit correspondre au seuil dans bodacc.py
MARQUEUR_AUTO = "Généré automatiquement par MASARE-Veille"


def construire_lien_pappers(denomination: str, siren: str) -> str:
    """Construit le lien direct vers la fiche Pappers (même logique que bodacc.py)."""
    slug = denomination.lower().strip()
    slug = unicodedata.normalize("NFD", slug)
    slug = "".join(c for c in slug if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"https://www.pappers.fr/entreprise/{slug}-{siren}"


def extraire_siren_depuis_body(body: str) -> str:
    """Extrait le SIREN depuis le corps d'une issue MASARE.
    Cherche le mot SIREN puis les 9 chiffres consécutifs dans les 50 chars suivants.
    Couvre tous les formats de body (tableau markdown, texte libre, anciens formats).
    """
    m = re.search(r'SIREN.{0,50}?([0-9]{9})', body, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def patcher_lien_pappers(issue: dict) -> bool:
    """
    Ajoute le lien Pappers en tête du corps de l'issue si absent.
    Retourne True si le patch a été appliqué.
    """
    body = issue.get("body", "") or ""
    titre = issue.get("title", "")

    # Déjà patché ?
    if "pappers.fr/entreprise/" in body:
        return False

    siren = extraire_siren_depuis_body(body)
    if not siren:
        return False

    # Extraire la dénomination depuis le titre (format ALERTE … — DENOMINATION — Score …)
    m = re.search(r'ALERTE[^—–\-]*[—–\-]+\s*(.+?)\s*[—–\-]+\s*Score', titre, re.IGNORECASE)
    denomination = m.group(1).strip() if m else titre

    lien = construire_lien_pappers(denomination, siren)
    lien_line = f"🔗 [Fiche Pappers]({lien})\n\n"

    # Insérer après la première ligne "## DENOMINATION"
    if body.startswith("## "):
        newline_idx = body.index("\n")
        new_body = body[:newline_idx + 1] + "\n" + lien_line + body[newline_idx + 1:]
    else:
        new_body = lien_line + body

    resp = requests.patch(
        f"{BASE_URL}/issues/{issue['number']}",
        headers=HEADERS,
        json={"body": new_body},
    )
    statut = "✓" if resp.ok else f"✗ {resp.status_code}"
    print(f"    Lien Pappers ajouté #{issue['number']} ({denomination}) → {statut}")
    return resp.ok


def normalise_nom(titre: str) -> str:
    match = re.search(
        r'ALERTE[^—–\-]*[—–\-]+\s*(.+?)\s*[—–\-]+\s*Score',
        titre,
        re.IGNORECASE | re.UNICODE
    )
    if match:
        nom = match.group(1).strip()
    else:
        parties = re.split(r'\s*[—–]\s*|\s+-\s+', titre)
        nom = parties[1].strip() if len(parties) >= 2 else titre

    nom = nom.lower()
    for forme in ["scop sa", "scop", " holding", " groupe", " group",
                  " industries", " industrie", " sas", " sa", " sarl",
                  " srl", " sci", " sca", " eurl", " sasu"]:
        nom = nom.replace(forme, "")
    return re.sub(r"[^a-z0-9]", "", nom).strip()


def extraire_score(titre: str) -> float:
    """Extrait le score normalisé sur 20 (compatible anciens titres /10 et nouveaux /20)."""
    m20 = re.search(r'Score\s+([0-9]+(?:[.,][0-9]+)?)\s*/\s*20', titre, re.IGNORECASE)
    if m20:
        return float(m20.group(1).replace(",", "."))
    m10 = re.search(r'Score\s+([0-9]+(?:[.,][0-9]+)?)\s*/\s*10', titre, re.IGNORECASE)
    if m10:
        # Convertir le score /10 en /20 pour comparaison cohérente
        return float(m10.group(1).replace(",", ".")) * 2
    return 0.0


def est_auto_generee(issue: dict) -> bool:
    """Retourne True si l'issue a été créée automatiquement par MASARE-Veille."""
    body = issue.get("body", "") or ""
    return MARQUEUR_AUTO in body


def est_non_classifiee(titre: str) -> bool:
    return "non classif" in titre.lower()


MOTS_EXCLUS = [
    "non classif", "btp", "construction", "travaux publics", "maçonnerie",
    "transport routier", "fret", "messagerie", "livraison", "taxi", "vtc", "ambulance",
    "restaur", "café", "traiteur", "snack", "brasserie", "pizzeria", "fast-food",
    "commerce", "négoce", "grossiste", "distribution alimentaire", "supermarché",
    "ehpad", "maison de retraite", "clinique", "soins de suite",
    "aide à domicile", "service à la personne", "garde d'enfant",
]


def extraire_secteur_titre(titre: str) -> str:
    """Extrait le secteur depuis le titre d'une issue MASARE."""
    parties = re.split(r'\s*[—–]\s*', titre)
    # Format : ALERTE X — Dénomination — Score N/10 — Secteur — Urgence
    if len(parties) >= 5:
        return parties[3].strip().lower()
    if len(parties) >= 4:
        return parties[3].strip().lower()
    return ""


def est_secteur_exclu(titre: str) -> bool:
    """Retourne True si l'issue concerne un secteur exclu détectable depuis le titre."""
    secteur = extraire_secteur_titre(titre)
    return any(mot in secteur for mot in MOTS_EXCLUS)


def est_ancien_format(issue: dict) -> bool:
    """Retourne True si l'issue est auto-générée mais dans l'ancien format (sans données financières)."""
    body = issue.get("body", "") or ""
    return "📊 Données financières" not in body


def get_all_open_issues() -> list:
    issues, page = [], 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/issues",
            headers=HEADERS,
            params={"state": "open", "per_page": 100, "page": page},
        )
        resp.raise_for_status()
        batch = [i for i in resp.json() if "pull_request" not in i]
        if not batch:
            break
        issues.extend(batch)
        page += 1
    return issues


def fermer_issue(numero: int, raison: str):
    requests.post(
        f"{BASE_URL}/issues/{numero}/comments",
        headers=HEADERS,
        json={"body": f"⚠️ Issue fermée automatiquement — {raison}"},
    )
    resp = requests.patch(
        f"{BASE_URL}/issues/{numero}",
        headers=HEADERS,
        json={"state": "closed", "state_reason": "not_planned"},
    )
    statut = "✓ fermée" if resp.ok else f"✗ erreur {resp.status_code}"
    print(f"    Issue #{numero} → {statut}")


def main():
    if not TOKEN:
        print("[ERREUR] GITHUB_TOKEN non défini.")
        return

    print(f"[MASARE-Dedup] Chargement des issues sur {REPO}...")
    issues = get_all_open_issues()
    print(f"[MASARE-Dedup] {len(issues)} issue(s) ouverte(s)")

    total_fermes = 0

    # ── ÉTAPE 0 : Patcher le lien Pappers sur les issues existantes ─────────────
    # Toutes les issues (auto-générées ET manuelles) reçoivent le lien si absent.
    print(f"\n── Étape 0 : Ajout lien Pappers sur issues existantes (si absent)")
    n_patched = 0
    for issue in issues:
        if patcher_lien_pappers(issue):
            n_patched += 1
    print(f"  → {n_patched} issue(s) patchée(s) avec le lien Pappers")

    # ── ÉTAPE 1 : Fermer les issues auto-générées sous le seuil de score ───────
    print(f"\n── Étape 1 : Fermeture des issues auto-générées score < {SCORE_MIN}")
    issues_valides = []
    for issue in issues:
        if not est_auto_generee(issue):
            issues_valides.append(issue)
            continue
        score = extraire_score(issue["title"])
        if score > 0 and score < SCORE_MIN:
            print(f"  Score {score}/10 — #{issue['number']} {issue['title'][:60]}")
            fermer_issue(issue["number"], f"score {score}/10 sous le seuil {SCORE_MIN}/10")
            total_fermes += 1
        else:
            issues_valides.append(issue)

    print(f"  → {total_fermes} issue(s) fermée(s) pour score insuffisant")

    # ── ÉTAPE 2 : Fermer les issues auto-générées "Non classifié" ───────────────
    print(f"\n── Étape 2 : Fermeture des issues auto-générées 'Non classifié'")
    n_non_classif = 0
    issues_apres_etape2 = []
    for issue in issues_valides:
        if est_auto_generee(issue) and est_non_classifiee(issue["title"]):
            print(f"  Non classifié — #{issue['number']} {issue['title'][:60]}")
            fermer_issue(issue["number"], "secteur non classifié — résidu ancien scoring")
            total_fermes += 1
            n_non_classif += 1
        else:
            issues_apres_etape2.append(issue)

    print(f"  → {n_non_classif} issue(s) 'Non classifié' fermée(s)")

    # ── ÉTAPE 3 : Fermer les issues ancien format à secteur exclu ────────────────
    print(f"\n── Étape 3 : Fermeture des issues ancien format avec secteur exclu ou non pertinent")
    n_ancien_format = 0
    issues_apres_etape3 = []
    for issue in issues_apres_etape2:
        if est_auto_generee(issue) and est_ancien_format(issue) and est_secteur_exclu(issue["title"]):
            print(f"  Exclu — #{issue['number']} {issue['title'][:70]}")
            fermer_issue(issue["number"], "secteur exclu des critères MASARE")
            total_fermes += 1
            n_ancien_format += 1
        else:
            issues_apres_etape3.append(issue)

    print(f"  → {n_ancien_format} issue(s) secteur exclu fermée(s)")

    # ── ÉTAPE 4 : Dédupliquer les issues restantes ────────────────────────────
    print(f"\n── Étape 4 : Déduplication ({len(issues_apres_etape3)} issues restantes)")
    groupes = defaultdict(list)
    for issue in issues_apres_etape3:
        cle = normalise_nom(issue["title"])
        groupes[cle].append(issue)

    doublons = {k: v for k, v in groupes.items() if len(v) > 1}
    print(f"  {len(doublons)} groupe(s) avec doublons")

    for cle, groupe in doublons.items():
        print(f"\n  Groupe '{cle}' ({len(groupe)} issues)")
        principale = max(groupe, key=lambda i: (extraire_score(i["title"]), i["number"]))
        print(f"  Principale : #{principale['number']} — {principale['title'][:60]}")

        labels = list({lbl["name"] for i in groupe for lbl in i.get("labels", [])})
        requests.patch(f"{BASE_URL}/issues/{principale['number']}", headers=HEADERS, json={"labels": labels})

        for issue in groupe:
            if issue["number"] != principale["number"]:
                fermer_issue(issue["number"], f"doublon de #{principale['number']}")
                total_fermes += 1

    print(f"\n[MASARE-Dedup] Terminé — {total_fermes} issue(s) fermée(s) au total")


if __name__ == "__main__":
    main()
