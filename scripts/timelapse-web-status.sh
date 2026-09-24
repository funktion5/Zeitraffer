#!/bin/bash

# Shared status-file helpers for web-triggered timelapse jobs.

STATUS_ROOT="${TIMELAPSE_WEB_STATUS_ROOT:-/home/zruser/timelapse/state/web-jobs}"


# Return whether a job ID is exactly 32 lowercase hexadecimal characters.
is_valid_job_id() {
	local job_id="$1"

	[[ "$job_id" =~ ^[a-f0-9]{32}$ ]]
}


# Atomically write one allowed state for a validated web job ID.
write_job_status() {
	local job_id="$1"
	local status="$2"
	local temporary_file

	if ! is_valid_job_id "$job_id"; then
		echo "Invalid job ID." >&2
		return 64
	fi

	case "$status" in
		running|completed|failed)
			;;
		*)
			echo "Invalid job status: $status" >&2
			return 64
			;;
	esac

	mkdir -p -m 755 "$STATUS_ROOT"
	temporary_file="$(mktemp "${STATUS_ROOT}/.${job_id}.XXXXXX")"

	if ! printf '%s\n' "$status" >"$temporary_file"; then
		rm -f "$temporary_file"
		return 1
	fi

	chmod 644 "$temporary_file"
	mv -f "$temporary_file" "${STATUS_ROOT}/${job_id}.status"
}
