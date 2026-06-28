#!/usr/bin/env bash
# Interactive .env setup for immich-trip-albums.
set -euo pipefail

ENV_FILE="${1:-.env}"

if [ -f "$ENV_FILE" ]; then
    printf '%s already exists. Overwrite? [y/N] ' "$ENV_FILE"
    read -r ans
    [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

prompt() {
    local var="$1" desc="$2" default="${3-}"
    if [ -n "$default" ]; then
        printf '%s (%s) [%s]: ' "$var" "$desc" "$default" >&2
    else
        printf '%s (%s): ' "$var" "$desc" >&2
    fi
    read -r value
    echo "${value:-$default}"
}

cat >&2 <<'PERMS'
Required Immich API key permissions:
  asset.read, album.create, album.read, album.update,
  album.delete, albumAsset.create

PERMS
echo "=== Immich connection ===" >&2
IMMICH_URL=$(prompt IMMICH_URL "base URL, e.g. https://immich.example.com")
IMMICH_API_KEY=$(prompt IMMICH_API_KEY "API key from Account Settings")

echo "" >&2
echo "=== Home location (used to filter out non-trip photos) ===" >&2
HOME_CITIES=$(prompt HOME_CITIES "comma-separated city names" "")
HOME_STATES=$(prompt HOME_STATES "comma-separated state names" "")
HOME_COUNTRIES=$(prompt HOME_COUNTRIES "comma-separated countries" "")
HOME_LAT=$(prompt HOME_LAT "home latitude, optional" "")
HOME_LON=$(prompt HOME_LON "home longitude, optional" "")
HOME_RADIUS_KM=$(prompt HOME_RADIUS_KM "radius in km for GPS home detection" "25")

echo "" >&2
echo "=== Trip clustering ===" >&2
GAP_MIN_DAYS=$(prompt GAP_MIN_DAYS "gaps shorter than this are never split, in days" "1.5")
GAP_MAX_DAYS=$(prompt GAP_MAX_DAYS "gaps longer than this are always split, in days" "6")
TRIP_GAP_FALLBACK_DAYS=$(prompt TRIP_GAP_FALLBACK_DAYS "split threshold for in-between gaps, in days" "4")
OUTLIER_MAX_ASSETS=$(prompt OUTLIER_MAX_ASSETS "clusters with <= this many assets are flagged as outliers" "2")

echo "" >&2
echo "=== Albums ===" >&2
ALBUM_PREFIX=$(prompt ALBUM_PREFIX "prefix for album names" "Trip —")

cat > "$ENV_FILE" <<EOF
IMMICH_URL=$IMMICH_URL
IMMICH_API_KEY=$IMMICH_API_KEY
HOME_CITIES=$HOME_CITIES
HOME_STATES=$HOME_STATES
HOME_COUNTRIES=$HOME_COUNTRIES
HOME_LAT=$HOME_LAT
HOME_LON=$HOME_LON
HOME_RADIUS_KM=$HOME_RADIUS_KM
GAP_MIN_DAYS=$GAP_MIN_DAYS
GAP_MAX_DAYS=$GAP_MAX_DAYS
TRIP_GAP_FALLBACK_DAYS=$TRIP_GAP_FALLBACK_DAYS
OUTLIER_MAX_ASSETS=$OUTLIER_MAX_ASSETS
ALBUM_PREFIX=$ALBUM_PREFIX
EOF

echo ""
echo "Wrote $ENV_FILE. Run: trip-albums --env $ENV_FILE"
