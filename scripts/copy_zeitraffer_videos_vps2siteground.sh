#!/bin/bash

# Verwendung:
# ./copy_zeitraffer_videos_vps2siteground.sh [<kamera>] [--run] [--list-file <datei>]
#
# Beispiel:
# ./copy_zeitraffer_videos_vps2siteground.sh --run
# ./copy_zeitraffer_videos_vps2siteground.sh "Scheunenviertel" --run
#
# Ohne <kamera> werden alle Kameras der Liste nacheinander bearbeitet.
# Mit --list-file wird die Liste aus der Datei gelesen statt aus der Liste der freigegebenen Videos.
# Ohne --run ist es ein Trockenlauf: Es wird nichts gesendet oder gelöscht.
#
# Ablauf:
# 1. Liest die Liste der freigegebenen Videos
# 2. Bricht ab, wenn die Liste leer ist
# 3. Ohne <kamera>: ruft sich selbst für jede Kamera der Liste auf
# 4. Lehnt unsichere Pfade ab
# 5. Überspringt Dateien, die schon mit gleicher Größe auf SiteGround liegen
# 6. Lädt die übrigen per FTP hoch (erst unter einem versteckten Namen, dann umbenannt)
# 7. Legt fehlende Ordner auf SiteGround automatisch an
# 8. Behält je Kamera und Zeitraum die zwei neuesten Videos
# 9. Löscht ältere Videos

set -euo pipefail


# ============================================================
# KONFIGURATION
# ============================================================

# SiteGround FTP: Die Zugangsdaten stehen nicht hier, sondern in config/siteground.env (siehe unten).
# Eine Umgebungsvariable mit gleichem Namen hat Vorrang (die Tests nutzen das).
SITEGROUND_HOST="${SITEGROUND_HOST:-}"
SITEGROUND_USER="${SITEGROUND_USER:-}"
SITEGROUND_PASS="${SITEGROUND_PASS:-}"

# Videos, die je Kamera und Zeitraum auf SiteGround bleiben: das neueste und das vorherige.
KEEP=2

# Zeitlimits für jeden FTP-Aufruf: Verbindung, und Abbruch, wenn zwei Minuten fast nichts fließt.
CURL_LIMITS=(--connect-timeout 30 --speed-limit 1000 --speed-time 120)


# ============================================================
# FUNKTIONEN
# ============================================================

error_exit() {
    echo "[ERROR] $1" >&2
    exit "${2:-1}"
}

info() {
    echo "[INFO] $1"
}

warn() {
    echo "[WARN] $1"
}


# ============================================================
# VORAUSSETZUNGEN PRÜFEN
# ============================================================

command -v curl >/dev/null 2>&1 \
    || error_exit "curl wurde nicht gefunden."


# ============================================================
# ARGUMENTE
# ============================================================

RUN=0
FOLDER=""
LIST_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --run)
            RUN=1
            shift
            ;;
        --list-file)
            LIST_FILE="${2:-}"
            [[ -n "$LIST_FILE" ]] || error_exit "--list-file braucht einen Dateinamen." 2
            shift 2
            ;;
        -*)
            error_exit "Verwendung: $0 [<kamera>] [--run]" 2
            ;;
        *)
            [[ -z "$FOLDER" ]] || error_exit "Verwendung: $0 [<kamera>] [--run]" 2
            FOLDER="$1"
            shift
            ;;
    esac
done

# Nur Buchstaben, Ziffern, "_" und "-": Der Name wird in Pfaden und Suchmustern benutzt.
if [[ -n "$FOLDER" && ! "$FOLDER" =~ ^[A-Za-z0-9_-]+$ ]]; then
    error_exit "Ungültiger Kameraname: $FOLDER" 2
fi


# ============================================================
# VERZEICHNISSE
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Die Zugangsdaten stehen in config/siteground.env (git ignoriert die Datei); mit SITEGROUND_CONFIG
# kann eine andere Datei angegeben werden. Je Zeile NAME=Wert: Alles nach dem ersten "=" ist der
# Wert, ohne Anführungszeichen und ohne Maskierung. Die Datei wird nur gelesen, nie ausgeführt.
# Eine Umgebungsvariable hat Vorrang: Die Datei füllt nur, was die Umgebung leer lässt.
CONFIG_FILE="${SITEGROUND_CONFIG:-$PROJECT_ROOT/config/siteground.env}"

if [[ -r "$CONFIG_FILE" ]]; then
    while IFS='=' read -r KEY VALUE || [[ -n "$KEY" ]]; do
        case "$KEY" in
            SITEGROUND_HOST|SITEGROUND_USER|SITEGROUND_PASS)
                [[ -n "${!KEY}" ]] || printf -v "$KEY" '%s' "$VALUE"
                ;;
        esac
    done < "$CONFIG_FILE"
fi

VIDEO_ROOT="${VIDEO_ROOT:-$PROJECT_ROOT/videos}"
LOCK_FILE="${LOCK_FILE:-$PROJECT_ROOT/state/siteground-delivery-${FOLDER:-alle}.lock}"

# Erlaubt ist nur <kamera>/<zeitraum>/<name>.mp4: kein Punkt am Anfang, kein "..".
SAFE_PATH='^[A-Za-z0-9_-]+/(daily|weekly|monthly|yearly)/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.mp4$'
VIDEO_NAME='^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.mp4$'


# ============================================================
# LISTE DER FREIGEGEBENEN VIDEOS EINLESEN
# ============================================================

if [[ -n "$LIST_FILE" ]]; then
    LIST=$(cat "$LIST_FILE") \
        || error_exit "Die Liste $LIST_FILE konnte nicht gelesen werden."
else
    LIST=$("$PROJECT_ROOT/.venv/bin/python3" "$SCRIPT_DIR/list-deliverable-videos.py") \
        || error_exit "Die Liste der freigegebenen Videos konnte nicht erstellt werden."
fi

# Eine leere Liste heißt: Davor ist etwas kaputt. Es wird nichts gesendet und nichts gelöscht.
if [[ -z "$(printf '%s' "$LIST" | tr -d '[:space:]')" ]]; then
    error_exit "Die Liste ist leer: Es wird nichts gesendet und nichts gelöscht."
fi


# ============================================================
# OHNE KAMERA: ALLE KAMERAS DER LISTE NACHEINANDER
# ============================================================

if [[ -z "$FOLDER" ]]; then

    CAMERAS=$(printf '%s\n' "$LIST" | cut -d/ -f1 | sed '/^$/d' | sort -u)
    CAMERA_COUNT=$(printf '%s\n' "$CAMERAS" | sed '/^$/d' | wc -l | tr -d ' ')

    info "$CAMERA_COUNT Kamera(s) auf der Liste."

    # Jede Kamera ist ein eigener Aufruf mit eigener Sperre, eigener Ausgabe und eigenem Ergebnis.
    CHILD_ARGS=()

    if [[ "$RUN" -eq 1 ]]; then
        CHILD_ARGS+=(--run)
    fi

    if [[ -n "$LIST_FILE" ]]; then
        CHILD_ARGS+=(--list-file "$LIST_FILE")
    fi

    ALL_OK=1

    while IFS= read -r CAMERA; do

        [[ -z "$CAMERA" ]] && continue

        echo "========================================"
        info "Kamera: $CAMERA"

        if ! bash "${BASH_SOURCE[0]}" "$CAMERA" ${CHILD_ARGS[@]+"${CHILD_ARGS[@]}"}; then
            warn "Der Lauf für $CAMERA ist fehlgeschlagen."
            ALL_OK=0
        fi

    done <<< "$CAMERAS"

    echo "========================================"

    if [[ "$ALL_OK" -ne 1 ]]; then
        error_exit "Mindestens eine Kamera ist fehlgeschlagen."
    fi

    info "Alle Kameras erfolgreich abgeschlossen."
    exit 0

fi


# ============================================================
# MIT KAMERA: NUR DIE EINTRÄGE DIESER KAMERA
# ============================================================

LIST=$(printf '%s\n' "$LIST" | grep "^$FOLDER/" || true)

# Keine Einträge heißt: Die Kamera ist nicht freigegeben oder der Name ist falsch.
if [[ -z "$(printf '%s' "$LIST" | tr -d '[:space:]')" ]]; then
    error_exit "Die Liste ist leer: Für $FOLDER wird nichts gesendet und nichts gelöscht."
fi

# Debug-Ausgabe (das Passwort wird nie angezeigt, nur ob es gesetzt ist)
if [[ -n "$SITEGROUND_PASS" ]]; then
    PASS_STATUS="***gesetzt***"
else
    PASS_STATUS="<nicht gesetzt>"
fi

if [[ "$RUN" -eq 1 ]]; then
    MODE="echter Lauf"
else
    MODE="Trockenlauf"
fi

info "Debug-Ausgabe:"
info "  Modus:           $MODE"
info "  Kamera:          $FOLDER"
info "  SITEGROUND_HOST: ${SITEGROUND_HOST:-<nicht gesetzt>}"
info "  SITEGROUND_USER: ${SITEGROUND_USER:-<nicht gesetzt>}"
info "  SITEGROUND_PASS: $PASS_STATUS"
info "  VIDEO_ROOT:      $VIDEO_ROOT"
info "  Liste:           ${LIST_FILE:-Liste der freigegebenen Videos}"

if [[ "$RUN" -eq 1 ]]; then

    # Zugangsdaten und Sperre braucht nur der echte Lauf, nicht der Trockenlauf.
    command -v flock >/dev/null 2>&1 \
        || error_exit "flock wurde nicht gefunden."

    if [[ -z "$SITEGROUND_HOST" || -z "$SITEGROUND_USER" || -z "$SITEGROUND_PASS" ]]; then
        error_exit "SITEGROUND_HOST, SITEGROUND_USER und SITEGROUND_PASS müssen ausgefüllt sein." 2
    fi

    # Es läuft immer nur ein Lauf je Kamera; die Sperre endet mit dem Prozess, egal wie er endet.
    mkdir -p "$(dirname "$LOCK_FILE")"
    exec 9>"$LOCK_FILE"
    flock -n 9 || error_exit "Es läuft bereits ein anderer Lauf." 3

else

    info "Trockenlauf: Es gibt keine Verbindung zu SiteGround."

fi

COUNT=$(printf '%s\n' "$LIST" | sed '/^$/d' | wc -l | tr -d ' ')

info "$COUNT Video(s) für $FOLDER auf der Liste."


# ============================================================
# UPLOAD ZU SITEGROUND
# ============================================================

UPLOADED=0
SKIPPED=0
FAILED=0
DELETED=0

# Ordner -> Name der Datei, die gesendet wurde oder schon dort lag.
# Ordner, in denen etwas fehlgeschlagen ist.
declare -A FOLDER_NEWEST=()
declare -A FOLDER_FAILED=()

while IFS= read -r REL; do

    [[ -z "$REL" ]] && continue

    if [[ ! "$REL" =~ $SAFE_PATH ]]; then
        warn "Unsicherer Listeneintrag wird abgelehnt: $REL"
        FAILED=$((FAILED + 1))
        continue
    fi

    DIR="${REL%/*}"
    LOCAL="$VIDEO_ROOT/$REL"

    if [[ ! -s "$LOCAL" ]]; then
        warn "Datei fehlt oder ist leer: $REL"
        FAILED=$((FAILED + 1))
        FOLDER_FAILED["$DIR"]=1
        continue
    fi

    FILE_SIZE=$(wc -c < "$LOCAL" | tr -d ' ')

    if [[ "$RUN" -ne 1 ]]; then
        info "[Trockenlauf] würde senden: $REL ($FILE_SIZE Bytes)"
        continue
    fi

    # Größe der Datei auf SiteGround. Leer, wenn sie nicht da ist oder die Größe
    # unbekannt bleibt (dann wird die Datei einfach noch einmal gesendet).
    REMOTE_SIZE=$(
        curl \
            --silent \
            --show-error \
            --fail \
            "${CURL_LIMITS[@]}" \
            --user "$SITEGROUND_USER:$SITEGROUND_PASS" \
            --head \
            "ftp://$SITEGROUND_HOST/$REL" 2>/dev/null \
        | tr -d '\r' \
        | awk -F': *' 'tolower($1) == "content-length" { print $2 }' \
        || true
    )

    if [[ "$REMOTE_SIZE" == "$FILE_SIZE" ]]; then

        info "Schon vorhanden: $REL"
        SKIPPED=$((SKIPPED + 1))
        FOLDER_NEWEST["$DIR"]="${REL##*/}"
        continue

    fi

    info "Upload zu SiteGround wird gestartet..."
    info "Ziel: /$REL ($FILE_SIZE Bytes)"

    # Zuerst unter einem versteckten Namen hochladen, damit ein halbes Video nie
    # seinen echten Namen hat. --ftp-create-dirs legt fehlende Ordner an.
    TEMP_NAME="$DIR/.${REL##*/}.part"

    if ! curl \
        --silent \
        --show-error \
        --fail \
        --verbose \
        "${CURL_LIMITS[@]}" \
        --ftp-create-dirs \
        --user "$SITEGROUND_USER:$SITEGROUND_PASS" \
        --upload-file "$LOCAL" \
        "ftp://$SITEGROUND_HOST/$TEMP_NAME"
    then
        warn "Upload fehlgeschlagen: $REL"
        FAILED=$((FAILED + 1))
        FOLDER_FAILED["$DIR"]=1
        continue
    fi

    # Danach auf den echten Namen umbenennen.
    if ! curl \
        --silent \
        --show-error \
        --fail \
        "${CURL_LIMITS[@]}" \
        --user "$SITEGROUND_USER:$SITEGROUND_PASS" \
        --quote "RNFR $TEMP_NAME" \
        --quote "RNTO $REL" \
        "ftp://$SITEGROUND_HOST/" \
        >/dev/null
    then
        warn "Umbenennen fehlgeschlagen: $REL"
        FAILED=$((FAILED + 1))
        FOLDER_FAILED["$DIR"]=1
        continue
    fi

    info "Upload erfolgreich."
    UPLOADED=$((UPLOADED + 1))
    FOLDER_NEWEST["$DIR"]="${REL##*/}"

done <<< "$LIST"

if [[ "$RUN" -ne 1 ]]; then
    info "Trockenlauf beendet: Es wurde nichts gesendet oder gelöscht. Mit --run ausführen."
    [[ "$FAILED" -eq 0 ]] || exit 1
    exit 0
fi


# ============================================================
# NUR DIE LETZTEN VIDEOS BEHALTEN (NUR WO ALLES ANGEKOMMEN IST)
# ============================================================

for DIR in "${!FOLDER_NEWEST[@]}"; do

    if [[ -n "${FOLDER_FAILED[$DIR]:-}" ]]; then
        warn "Aufräumen von $DIR übersprungen: dort ist etwas fehlgeschlagen."
        continue
    fi

    NEWEST="${FOLDER_NEWEST[$DIR]}"

    info "Dateiliste auf SiteGround wird geladen: $DIR"

    if ! NAMES=$(
        curl \
            --silent \
            --show-error \
            --fail \
            "${CURL_LIMITS[@]}" \
            --user "$SITEGROUND_USER:$SITEGROUND_PASS" \
            --list-only \
            "ftp://$SITEGROUND_HOST/$DIR/" \
        | tr -d '\r'
    ); then
        warn "Dateiliste von $DIR nicht lesbar, dort wird nicht aufgeräumt."
        continue
    fi

    # Eine Liste ohne die gerade gesendete Datei ist nicht vertrauenswürdig.
    if ! printf '%s\n' "$NAMES" | grep -qxF "$NEWEST"; then
        warn "$NEWEST fehlt in der Dateiliste von $DIR, dort wird nicht aufgeräumt."
        continue
    fi

    # Nur fertige Videos zählen: versteckte und temporäre Namen und andere Dateien
    # werden weder behalten noch gelöscht.
    VIDEOS=$({ printf '%s\n' "$NAMES" | grep -E "$VIDEO_NAME" | sort; } || true)
    VIDEO_COUNT=$(printf '%s\n' "$VIDEOS" | sed '/^$/d' | wc -l | tr -d ' ')

    info "$VIDEO_COUNT Video(s) in $DIR gefunden."

    if [[ "$VIDEO_COUNT" -le "$KEEP" ]]; then
        info "Nur $VIDEO_COUNT Video(s) vorhanden. Keine Bereinigung notwendig."
        continue
    fi

    info "Alte Videos werden gelöscht. Die letzten $KEEP bleiben erhalten."

    OLD_VIDEOS=$(printf '%s\n' "$VIDEOS" | head -n -"$KEEP")

    while IFS= read -r OLD_VIDEO; do

        [[ -z "$OLD_VIDEO" ]] && continue

        info "Lösche altes Video: $DIR/$OLD_VIDEO"

        if curl \
            --silent \
            --show-error \
            --fail \
            "${CURL_LIMITS[@]}" \
            --user "$SITEGROUND_USER:$SITEGROUND_PASS" \
            --quote "DELE $DIR/$OLD_VIDEO" \
            "ftp://$SITEGROUND_HOST/" \
            >/dev/null
        then
            DELETED=$((DELETED + 1))
        else
            warn "Konnte $DIR/$OLD_VIDEO nicht löschen."
        fi

    done <<< "$OLD_VIDEOS"

done


# ============================================================
# FERTIG
# ============================================================

echo "----------------------------------------"
info "Ergebnis: hochgeladen=$UPLOADED übersprungen=$SKIPPED fehlgeschlagen=$FAILED gelöscht=$DELETED"

if [[ "$FAILED" -ne 0 ]]; then
    echo "----------------------------------------"
    exit 1
fi

info "Vorgang erfolgreich abgeschlossen."
echo "----------------------------------------"
