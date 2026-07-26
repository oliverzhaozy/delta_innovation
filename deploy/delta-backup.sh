#!/usr/bin/env bash
# Nightly DB backup: sqlite .backup (never cp a live WAL DB) -> age-encrypt
# -> GCS. The VM only holds the PUBLIC key; decryption needs the private key
# kept off-box (owner's password manager). Bucket IAM is objectCreator-only,
# so this box cannot read or delete what it has uploaded.
set -euo pipefail

recipient=$(cat /etc/delta/age.recipient)
stamp=$(date +%Y%m%d-%H%M%S)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

sqlite3 /var/lib/delta/delta.db ".backup '$tmp/delta.db'"
age -r "$recipient" -o "$tmp/delta-$stamp.db.age" "$tmp/delta.db"
gcloud storage cp "$tmp/delta-$stamp.db.age" gs://coyadmin-app-backups/
