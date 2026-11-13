#!/bin/bash
# Aggiorna l'app sul server: pull del codice, copia di sicurezza dei dati,
# rebuild del container e controllo che risponda.
# Uso (dal PC):  ssh rikyru@192.168.1.124 '~/finance_app/deploy.sh'
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$APP_DIR/finance_data"
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/docker}"
SERVICE="${SERVICE:-finance_app}"
CONTAINER="${CONTAINER:-finance_dashboard}"
URL="${URL:-http://localhost:8501}"
KEEP=10

cd "$APP_DIR"
before="$(git rev-parse --short HEAD)"
git pull --ff-only -q
after="$(git rev-parse --short HEAD)"
echo "Codice: $before -> $after"
git log --oneline "$before..$after" | sed 's/^/  /'

# Copia di sicurezza del database prima di cambiare versione (ultime $KEEP)
snap="$DATA_DIR/backups_deploy/$(date +%Y%m%d_%H%M%S)_$after"
mkdir -p "$snap"
cp -a "$DATA_DIR"/finance.duckdb* "$DATA_DIR/rules.yaml" "$snap"/ 2>/dev/null || true
ls -1dt "$DATA_DIR"/backups_deploy/*/ | tail -n +$((KEEP + 1)) | xargs -r rm -rf
echo "Copia dati: $snap"

cd "$COMPOSE_DIR"
docker compose up -d --build --force-recreate "$SERVICE" 2>&1 | tail -2

for i in $(seq 1 30); do
  if curl -fs -o /dev/null "$URL"; then
    echo "OK: app online ($URL) dopo ${i}s"
    errors="$(docker logs --since 1m "$CONTAINER" 2>&1 | grep -ci traceback || true)"
    [ "$errors" -gt 0 ] && echo "ATTENZIONE: $errors traceback nei log" && docker logs --since 1m "$CONTAINER" 2>&1 | tail -20
    exit 0
  fi
  sleep 1
done
echo "ERRORE: l'app non risponde dopo 30s. Ultimi log:"
docker logs --tail 40 "$CONTAINER"
exit 1
