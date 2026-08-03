# DEPLOY — coyadmin.duckdns.org on GCP (P0.8, decision (w))

Deployed 2026-07-27. Host: GCP always-free e2-micro `coyadmin` (us-west1-b,
Debian 12, 30 GB pd-standard) in project `coyadmin-app`.

`[REVISED 2026-08-02 — decision (gg)]` The organisation has approved the
project, so the instance now runs the **real roster**, its DB seeded from a
copy of the dev DB so the host is a 1-to-1 replica (people plus leave,
ledger, statuses, duties, manning and overrides). The tarball is still a
**whitelist**: it ships `seed/people.csv`, the sanitized demo roster is gone
from the repo, and nothing else changed. Git stays off the VM.

Two things this revision does NOT change, both load-bearing now that real
data is live: `.flaskenv` stays out of the tarball (its `FLASK_DEBUG=1`
trips ProdConfig's refuse-to-boot guard), and **`DEV_LOGIN_SWITCHER` stays
off** — `/dev/switch/<id>` has no `@login_required` by design, so enabling it
here would let any visitor log in as anyone. `ProdConfig.validate` refuses to
boot on either; do not relax those checks. The supported way to see the app
as someone else on this host is decision (hh)'s admin-gated, **read-only**
"View as" (`/admin/people/<id>/view-as`): every non-GET is refused while the
impersonation marker is set, so it can never forge a decision.

## Topology

- Caddy (:80/:443) — auto-HTTPS via Let's Encrypt, `X-Robots-Tag: noindex`,
  serves `/robots.txt`, reverse-proxies to gunicorn.
- gunicorn `-w 2 -k gthread --threads 4` on 127.0.0.1:8000, systemd unit
  `delta.service`, user `delta` (nologin), app tree `/opt/delta/app`,
  venv `/opt/delta/venv`.
- DB `/var/lib/delta/delta.db` (dir 700; WAL). Config in `/etc/delta/env`
  (600: APP_CONFIG=prod, SECRET_KEY, DATABASE_URL, TZ=Asia/Singapore).
- The VM keeps an **ephemeral** external IP: `duckdns.timer` re-registers it
  with DuckDNS every 5 min (token in `/etc/duckdns/token`, 600). A static
  IPv4 is the one GCP item here that can bill.
- `delta-backup.timer` 03:30 SGT nightly: `sqlite3 .backup` → `age`-encrypt
  → `gs://coyadmin-app-backups` (30-day lifecycle purge). The VM's service
  account `delta-vm` has **objectCreator only** — it can upload but never
  list, read, or delete backups. ProdConfig applies ProxyFix (one hop) so
  rate limiting and https detection survive the proxy.
- age private key: Oliver's password manager (and `~\.age\delta-backup.key`
  on his machine). The VM holds only the public key
  (`/etc/delta/age.recipient`). Lose the private key = backups unreadable.

## One-time provisioning (as run, 2026-07-26/27)

```
gcloud auth login
gcloud projects create coyadmin-app --name="coyadmin"
gcloud billing projects link coyadmin-app --billing-account=<ACCOUNT_ID>
gcloud config set project coyadmin-app
gcloud services enable compute.googleapis.com storage.googleapis.com
gcloud iam service-accounts create delta-vm --display-name="coyadmin VM (no project roles; bucket-level only)"
gcloud compute firewall-rules create allow-web --direction=INGRESS --action=ALLOW \
    --rules=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 --target-tags=web --network=default
gcloud compute instances create coyadmin --zone=us-west1-b --machine-type=e2-micro \
    --image-family=debian-12 --image-project=debian-cloud \
    --boot-disk-size=30GB --boot-disk-type=pd-standard --tags=web \
    --service-account=delta-vm@coyadmin-app.iam.gserviceaccount.com --scopes=cloud-platform
gcloud storage buckets create gs://coyadmin-app-backups --location=us-west1 \
    --default-storage-class=STANDARD --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding gs://coyadmin-app-backups \
    --member="serviceAccount:delta-vm@coyadmin-app.iam.gserviceaccount.com" \
    --role="roles/storage.objectCreator"
gcloud storage buckets update gs://coyadmin-app-backups --lifecycle-file=deploy/lifecycle.json
```

DuckDNS: subdomain `coyadmin` under the owner's DuckDNS account; the token is
the only credential. `age-keygen` generated the backup keypair locally.

SSH: `gcloud compute ssh` created `~\.ssh\google_compute_engine`; scripts use
native OpenSSH with that key (`ssh -i ~\.ssh\google_compute_engine Oliver@<ip>`).
Windows gotcha: OpenSSH refuses the key until ACLs are tightened —
`icacls <key> /inheritance:r /grant:r "$env:USERNAME:R"`.

## Ship a release (redeploy)

From the repo root on Windows (Git Bash). The tarball is a **whitelist** —
runtime code + roster/holiday seeds only. Widen it only by decision: `.git`,
`tests/`, and the unit's real document samples in `docs/` have no reason to
sit on an internet-facing host, and `.flaskenv` must stay out (its
FLASK_DEBUG=1 would trip ProdConfig's refuse-to-boot guard).

```
stage=$(mktemp -d) && mkdir -p "$stage/seed"
cp -r app migrations config.py wsgi.py requirements.txt "$stage/"
cp seed/people.csv seed/holidays_sg.csv "$stage/seed/"
find "$stage" -type d -name __pycache__ -prune -exec rm -rf {} \;
tar -czf delta-app.tar.gz -C "$stage" .
tar -tzf delta-app.tar.gz | grep -Ei 'instance|\.git|\.db$|flaskenv|docs/|tests/'
# ^ MUST print nothing. Then:
scp -i ~/.ssh/google_compute_engine delta-app.tar.gz Oliver@<ip>:/tmp/
scp -i ~/.ssh/google_compute_engine -r deploy Oliver@<ip>:/tmp/deploy
ssh -i ~/.ssh/google_compute_engine Oliver@<ip> "sudo sed -i 's/\r\$//' /tmp/deploy/* && sudo bash /tmp/deploy/setup.sh"
```

## Replicate the dev DB onto the host (decision (gg))

Ships the live data, not just the roster. Checkpoint the WAL first so the
`.db` file is current, then hand it over with the service stopped. `setup.sh`
runs `db upgrade` afterwards, and `seed-people` skips usernames that already
exist, so the copy survives the redeploy untouched.

```
.venv/Scripts/python -c "import sqlite3; sqlite3.connect('instance/delta.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')"
scp -i ~/.ssh/google_compute_engine instance/delta.db Oliver@<ip>:/tmp/delta.db
ssh -i ~/.ssh/google_compute_engine Oliver@<ip> "
  sudo systemctl stop delta.service
  sudo cp -a /var/lib/delta/delta.db /var/lib/delta/delta.db.bak-\$(date +%F)   # previous DB, kept
  sudo install -o delta -g delta -m 600 /tmp/delta.db /var/lib/delta/delta.db
  sudo rm -f /var/lib/delta/delta.db-wal /var/lib/delta/delta.db-shm /tmp/delta.db
  sudo systemctl start delta.service"
```

`setup.sh` is re-runnable: it replaces `/opt/delta/app` wholesale, keeps the
venv, `/etc/delta/env` (so SECRET_KEY and sessions survive), and the DB, then
runs `flask db upgrade` and restarts the service. Current IP: `nslookup
coyadmin.duckdns.org`, or the GCP console.

## Verify after any deploy

```
curl -s https://coyadmin.duckdns.org/health          # {"status":"ok"}
curl -sI https://coyadmin.duckdns.org/ | grep -i robots   # X-Robots-Tag: noindex, nofollow
```

Then log in from a phone (the P0.8 done-test).

## Restore drill (monthly, from Oliver's machine)

```
gcloud storage ls gs://coyadmin-app-backups/          # pick the newest
gcloud storage cp gs://coyadmin-app-backups/<obj> drill.db.age
age -d -i ~\.age\delta-backup.key -o drill.db drill.db.age
python -c "import sqlite3; c=sqlite3.connect('drill.db'); print(c.execute('PRAGMA integrity_check').fetchone(), c.execute('SELECT COUNT(*) FROM person').fetchone())"
```

To actually restore: stop `delta.service`, copy the decrypted file to
`/var/lib/delta/delta.db` (owner `delta`, mode 600), start the service.

## Runbook

- App logs: `sudo journalctl -u delta.service -e`
- Caddy/cert logs: `sudo journalctl -u caddy -e`
- Backup/DNS timers: `systemctl list-timers`, `sudo journalctl -u delta-backup.service -e`
- Restart app: `sudo systemctl restart delta.service`
- The VM cannot read its own backups by design; verifying an upload happened
  is done from Oliver's machine (`gcloud storage ls`), not the VM.
