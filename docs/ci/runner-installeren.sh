#!/usr/bin/env bash
# Eigen GitHub Actions-runner voor Solven, in één keer.
#
# Draai dit als root op een verse Ubuntu-server (24.04 LTS), NIET op de
# productieserver:
#
#   RUNNER_TOKEN=<token van GitHub> bash runner-installeren.sh
#
# Het token haal je op GitHub: Settings → Actions → Runners → New self-hosted
# runner → Linux. Op die pagina staat in de regel `./config.sh --url … --token
# XXXX` het token; het is een uur geldig.
#
# Wat het doet:
#   1. Docker installeren (beide poorten starten PostgreSQL in een container, de
#      e2e-poort draait in de Playwright-image).
#   2. Een gebruiker `runner` aanmaken, in de groep docker, zonder sudo.
#   3. De runner downloaden, registreren met het label `loymem-ci` en als dienst
#      starten, zodat hij een herstart overleeft.
#   4. Elke nacht oude Docker-images, build-resten en volumes zonder container
#      opruimen, zodat de schijf niet volloopt.
#   5. needrestart de runner en Docker laten overslaan, zodat een automatische
#      update geen lopende job afbreekt.
#
# Daarna op GitHub: Settings → Secrets and variables → Actions → Variables →
# In ci.yml staat runs-on: [self-hosted, loymem-ci]. Zie docs/ci.md.
#
# SEC-031: deze runner is niet-efemeer en `runner` zit in de docker-groep (in
# feite root). De opvolger, efemeer en met rootless Docker, staat klaar in
# runner-efemeer.sh / runner-efemeer.md. Dit script blijft voor herinstallatie
# van de huidige opzet; Docker en de runner komen nu wel van een gecontroleerde
# bron (SEC-049): de apt-bron van Docker met zijn sleutel, en een vaste
# runnerversie met een vastgezette sha256.

set -euo pipefail

REPO_URL="https://github.com/BarberIwan/loymem"
LABEL="loymem-ci"
RUNNER_USER="runner"
# Een tweede runner op dezelfde server: een eigen map en een eigen naam, zelfde
# label. Bijvoorbeeld:
#   Draait naast de runners van Solven op dezelfde server, in een eigen map.
# Elke runner heeft zijn eigen _work, dus ze delen geen werkmap. Sinds #1485
# zit de PostgreSQL-dienst op een vrije poort, dus twee jobs tegelijk botsen niet.
RUNNER_DIR="${RUNNER_DIR:-/opt/actions-runner-loymem}"
RUNNER_NAAM="${RUNNER_NAAM:-$(hostname)-loymem-ci}"

if [[ $EUID -ne 0 ]]; then
  echo "Draai dit als root (sudo -i)." >&2
  exit 1
fi
if [[ -z "${RUNNER_TOKEN:-}" ]]; then
  echo "RUNNER_TOKEN ontbreekt. Haal het op GitHub (zie de kop van dit script)." >&2
  exit 1
fi

echo "==> Systeem bijwerken en Docker installeren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl jq tar git
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io
fi
systemctl enable --now docker

echo "==> Gebruiker ${RUNNER_USER}"
if ! id "${RUNNER_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${RUNNER_USER}"
fi
usermod -aG docker "${RUNNER_USER}"

echo "==> Runner downloaden"
# Vast, niet "latest"; de runner werkt zichzelf daarna bij. De sha256 staat hier,
# niet uit dezelfde bron als de download; dezelfde als in runner-efemeer.sh.
VERSIE="2.338.0"
VERWACHT="af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32"
mkdir -p "${RUNNER_DIR}"
cd "${RUNNER_DIR}"
if [[ ! -f ./config.sh ]]; then
  curl -fsSL -o runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${VERSIE}/actions-runner-linux-x64-${VERSIE}.tar.gz"
  echo "${VERWACHT}  runner.tar.gz" | sha256sum --check --strict
  tar xzf runner.tar.gz
  rm runner.tar.gz
fi
./bin/installdependencies.sh
chown -R "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_DIR}"

echo "==> Registreren met label ${LABEL}"
sudo -u "${RUNNER_USER}" ./config.sh \
  --url "${REPO_URL}" \
  --token "${RUNNER_TOKEN}" \
  --name "${RUNNER_NAAM}" \
  --labels "${LABEL}" \
  --work _work \
  --unattended \
  --replace

echo "==> Als dienst starten"
./svc.sh install "${RUNNER_USER}"
./svc.sh start

echo "==> Nachtelijke opruiming"
# Volumes erbij (CI-27): `system prune` laat ze staan, en elke job laat er een
# achter (de postgres-dienst). Een volume van een lopende job hangt aan zijn
# container en blijft dus staan. De poorten en de wachtrij ruimen zelf ook op
# (scripts/ci_runner_schijf.sh); dit is het vangnet voor een stille dag.
cat >/etc/cron.daily/solven-runner-opruimen <<'OPRUIM'
#!/bin/sh
# Images ouder dan een week, losse build-resten en volumes zonder container weg;
# de lopende job raakt dit niet.
docker system prune --all --force --filter "until=168h" >/dev/null 2>&1 || true
docker volume prune --force >/dev/null 2>&1 || true
OPRUIM
chmod +x /etc/cron.daily/solven-runner-opruimen

echo "==> Updates herstarten de runner en Docker niet midden in een job"
# Ubuntu werkt zichzelf 's ochtends bij (apt-daily-upgrade, tussen 06:00 en
# 07:00 lokale tijd), en needrestart herstart daarna elke dienst die een
# bijgewerkte bibliotheek gebruikt. Voor de runner is dat een afgebroken job.
# Op 14 november 2026 kregen beide runners om 06:47 lokale tijd binnen 5 ms
# "The runner has received a shutdown signal" en waren ze binnen een minuut
# terug (CI-27). Dat past hierbij; bevestigd is het pas met het journaal
# (runner-diagnose.yml). De regel is hoe dan ook juist: de runner pakt een
# nieuwe bibliotheek op bij zijn volgende eigen herstart of die van de server.
mkdir -p /etc/needrestart/conf.d
cat >/etc/needrestart/conf.d/solven-runner.conf <<'NEEDRESTART'
# Nooit automatisch herstarten: dat breekt de lopende CI-job af.
$nrconf{override_rc}{qr(^actions\.runner\..+\.service$)} = 0;
$nrconf{override_rc}{qr(^solven-runner@.+\.service$)} = 0;
$nrconf{override_rc}{qr(^docker\.service$)} = 0;
$nrconf{override_rc}{qr(^containerd\.service$)} = 0;
NEEDRESTART

echo
echo "Klaar. De runner staat op GitHub onder Settings → Actions → Runners als 'Idle'."
echo "Zet nu de variabele CI_ZWARE_RUNNER = ${LABEL} (Settings → Secrets and variables → Actions → Variables)."
