#!/bin/bash
# MASARE Veille — Exécution quotidienne
# Usage: crontab -e => 0 8 * * * cd /home/user/Masare-veille && bash daily_veille.sh

set -e

LOG_DIR="/tmp/masare-veille-logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/veille_$(date +%Y%m%d_%H%M%S).log"

echo "🚀 Veille MASARE — $(date)" | tee "$LOG_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"

# Exécute le script Python principal
cd /home/user/Masare-veille
python3 veille_masare_prod.py 2>&1 | tee -a "$LOG_FILE"

RAPPORT_DATE=$(date +%Y%m%d)
RAPPORT_FILE="rapport_${RAPPORT_DATE}.md"

if [ -f "$RAPPORT_FILE" ]; then
    echo "" | tee -a "$LOG_FILE"
    echo "✅ Rapport généré : $RAPPORT_FILE" | tee -a "$LOG_FILE"

    # Commit et push automatique si rapport existe
    git config user.email "veille@masare.fr" || git config user.email "claude@claude.ai"
    git config user.name "MASARE Veille Bot" || git config user.name "Claude"

    git add "$RAPPORT_FILE" 2>/dev/null || true
    git commit -m "Veille automatisée — $RAPPORT_DATE" 2>/dev/null || echo "Aucun changement à committer" | tee -a "$LOG_FILE"

    # Push sur branche de dev si configurée
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    git push origin "$BRANCH" -q 2>/dev/null || echo "⚠️  Push échoué" | tee -a "$LOG_FILE"

    echo "📊 Rapport archivé et synchronisé" | tee -a "$LOG_FILE"
else
    echo "⚠️  Rapport non généré" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "✅ Veille quotidienne terminée — Logs : $LOG_FILE" | tee -a "$LOG_FILE"
