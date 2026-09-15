#!/bin/bash

set -Eeuo pipefail

# --------------------------------------------------
# Konfiguration
# --------------------------------------------------

SOURCE="/mnt/cameras/camera01/test-camera"

BASE="/home/zruser/timelapse"
TEMP="$BASE/temp"
VIDEOS="$BASE/videos"
LOGS="$BASE/logs"

TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"

JOB="$TEMP/job_$TIMESTAMP"
OUTPUT="$VIDEOS/timelapse_$TIMESTAMP.mp4"
PARTIAL_OUTPUT="$VIDEOS/.timelapse_$TIMESTAMP.tmp.mp4"
LOGFILE="$LOGS/timelapse_$TIMESTAMP.log"

# --------------------------------------------------
# Logging
# --------------------------------------------------

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

fail() {
    log "ERROR: $*"
    log "Job wurde abgebrochen."
    log "Temporärer Ordner bleibt erhalten:"
    log "$JOB"
    exit 1
}

on_error() {
    local exit_code=$?

    log "UNERWARTETER FEHLER"
    log "Exit-Code: $exit_code"
    log "Zeile: ${BASH_LINENO[0]}"
    log "Befehl: $BASH_COMMAND"
    log "Temporäre Daten bleiben erhalten:"
    log "$JOB"

    exit "$exit_code"
}

trap on_error ERR

# --------------------------------------------------
# Vorbereitung
# --------------------------------------------------

mkdir -p "$TEMP" "$VIDEOS" "$LOGS"

mkdir "$JOB"

log "=================================================="
log "Timelapse Workflow gestartet"
log "=================================================="

log "Timestamp:          $TIMESTAMP"
log "Quelle:             $SOURCE"
log "Temporärer Ordner:  $JOB"
log "Video-Ausgabe:      $OUTPUT"
log "Logdatei:           $LOGFILE"

# --------------------------------------------------
# Voraussetzungen prüfen
# --------------------------------------------------

log "Prüfe Voraussetzungen..."

command -v ffmpeg >/dev/null 2>&1 \
    || fail "FFmpeg ist nicht installiert."

log "FFmpeg gefunden."

command -v ffprobe >/dev/null 2>&1 \
    || fail "FFprobe ist nicht installiert."

log "FFprobe gefunden."

if [ ! -d "$SOURCE" ]; then
    fail "Quellverzeichnis existiert nicht: $SOURCE"
fi

log "Quellverzeichnis existiert."

if [ ! -r "$SOURCE" ]; then
    fail "Quellverzeichnis ist nicht lesbar: $SOURCE"
fi

log "Quellverzeichnis ist lesbar."

if ! mountpoint -q /mnt/cameras/camera01; then
    fail "Kamera-Mount ist nicht aktiv: /mnt/cameras/camera01"
fi

log "Kamera-Mount ist aktiv."

# --------------------------------------------------
# Bilder suchen
# --------------------------------------------------

log "Suche JPG-Dateien..."

mapfile -d '' SOURCE_IMAGES < <(
    find "$SOURCE" \
        -maxdepth 1 \
        -type f \
        -iname '*.jpg' \
        -print0 |
    sort -z
)

IMAGE_COUNT="${#SOURCE_IMAGES[@]}"

log "Gefundene Bilder: $IMAGE_COUNT"

if [ "$IMAGE_COUNT" -eq 0 ]; then
    fail "Keine JPG-Dateien gefunden."
fi

# --------------------------------------------------
# Bilder kopieren
# --------------------------------------------------

log "Starte Kopiervorgang."
log "Quelle:"
log "$SOURCE"

log "Ziel:"
log "$JOB"

for IMAGE in "${SOURCE_IMAGES[@]}"; do

    FILENAME="$(basename "$IMAGE")"

    log "Kopiere: $FILENAME"

    cp -- "$IMAGE" "$JOB/"
done

COPIED_COUNT="$(
    find "$JOB" \
        -maxdepth 1 \
        -type f \
        -iname '*.jpg' |
    wc -l
)"

log "Kopierte Bilder: $COPIED_COUNT"

if [ "$COPIED_COUNT" -ne "$IMAGE_COUNT" ]; then
    fail "Anzahl kopierter Bilder stimmt nicht mit Quelle überein."
fi

log "Alle Bilder erfolgreich kopiert."

# --------------------------------------------------
# Speicherbedarf anzeigen
# --------------------------------------------------

JOB_SIZE="$(du -sh "$JOB" | cut -f1)"

log "Größe des temporären Jobs: $JOB_SIZE"

# --------------------------------------------------
# FFmpeg
# --------------------------------------------------

log "Starte FFmpeg."
log "Input:"
log "$JOB/*.jpg"

log "Temporäre Video-Datei:"
log "$PARTIAL_OUTPUT"

if ! ffmpeg \
    -hide_banner \
    -loglevel warning \
    -framerate 1 \
    -pattern_type glob \
    -i "$JOB/*.jpg" \
    -c:v libx264 \
    -pix_fmt yuv420p \
    "$PARTIAL_OUTPUT" \
    >> "$LOGFILE" 2>&1
then
    fail "FFmpeg konnte das Video nicht erstellen."
fi

log "FFmpeg wurde erfolgreich beendet."

# --------------------------------------------------
# Video prüfen
# --------------------------------------------------

if [ ! -f "$PARTIAL_OUTPUT" ]; then
    fail "Keine Videodatei erzeugt."
fi

if [ ! -s "$PARTIAL_OUTPUT" ]; then
    fail "Videodatei ist leer."
fi

VIDEO_SIZE="$(du -h "$PARTIAL_OUTPUT" | cut -f1)"

log "Video-Datei existiert."
log "Video-Größe: $VIDEO_SIZE"

if ! ffprobe \
    -v error \
    -select_streams v:0 \
    -show_entries stream=codec_name,width,height \
    -of default=noprint_wrappers=1 \
    "$PARTIAL_OUTPUT" \
    >> "$LOGFILE" 2>&1
then
    fail "FFprobe konnte keinen gültigen Videostream erkennen."
fi

log "Videostream erfolgreich geprüft."

# --------------------------------------------------
# Video finalisieren
# --------------------------------------------------

mv -- "$PARTIAL_OUTPUT" "$OUTPUT"

log "Video erfolgreich gespeichert:"
log "$OUTPUT"

# --------------------------------------------------
# Temporäre Daten löschen
# --------------------------------------------------

case "$JOB" in

    "$TEMP"/job_*)

        log "Entferne temporären Job:"
        log "$JOB"

        rm -rf -- "$JOB"

        ;;

    *)

        fail "Sicherheitsprüfung für Löschvorgang fehlgeschlagen."

        ;;

esac

if [ -d "$JOB" ]; then
    fail "Temporärer Ordner konnte nicht gelöscht werden."
fi

log "Temporäre Daten erfolgreich gelöscht."

# --------------------------------------------------
# Abschluss
# --------------------------------------------------

log "=================================================="
log "Workflow erfolgreich abgeschlossen"
log "Video:"
log "$OUTPUT"
log "=================================================="

exit 0