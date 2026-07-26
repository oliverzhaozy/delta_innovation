#!/usr/bin/env bash
# Re-register the VM's current public IP with DuckDNS. The VM uses an
# ephemeral external IP on purpose (a static IPv4 is the one GCP item that
# can bill); ip= empty makes DuckDNS use the request's source address.
set -euo pipefail

token=$(cat /etc/duckdns/token)
out=$(curl -fsS "https://www.duckdns.org/update?domains=coyadmin&token=${token}&ip=")
[ "$out" = "OK" ] || { echo "duckdns update failed: $out" >&2; exit 1; }
