#!/usr/bin/env bash
# Установка Директора на чистый сервер:
#   curl -fsSL https://github.com/ituzov/director/releases/latest/download/install.sh | sudo bash
# Переменные: DIRECTOR_VERSION (по умолчанию последний релиз),
# DIRECTOR_HOST (по умолчанию IP.sslip.io), DIRECTOR_DIR (/opt/director)
set -euo pipefail

REPO="ituzov/director"
DIR="${DIRECTOR_DIR:-/opt/director}"
# минорная версия: get.docker.com поставит последний патч к ней
DOCKER_VERSION="29.9"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
fail() {
  printf '\033[31mError: %s\033[0m\n' "$*" >&2
  exit 1
}

check_system() {
  [ "$(id -u)" -eq 0 ] || fail "run as root: curl ... | sudo bash"
  [ -r /etc/os-release ] || fail "unknown OS: Ubuntu 22.04+ or Debian 12+ required"
  # shellcheck source=/dev/null
  . /etc/os-release
  case "${ID:-}" in
    ubuntu | debian) ;;
    *) fail "unsupported OS ${ID:-?}: Ubuntu 22.04+ or Debian 12+ required" ;;
  esac
  for tool in curl openssl ss; do
    command -v "$tool" >/dev/null || fail "$tool is missing: apt install curl openssl iproute2"
  done
  case "$(uname -m)" in
    x86_64 | aarch64) ;;
    *) fail "unsupported CPU $(uname -m): amd64 or arm64 required" ;;
  esac
  # второй запуск перезаписал бы секреты, и токены Instagram стали бы нечитаемы
  [ ! -e "$DIR/.env" ] || fail "Director is already installed in $DIR"
  for port in 80 443; do
    if ss -ltnH "sport = :$port" | grep -q .; then
      fail "port $port is busy: Director needs 80 and 443 for HTTPS"
    fi
  done
}

install_docker() {
  if command -v docker >/dev/null; then
    docker compose version >/dev/null 2>&1 || fail "docker is installed, but 'docker compose' is missing"
    say "Docker is already installed: $(docker --version)"
    return
  fi
  say "Installing Docker $DOCKER_VERSION"
  curl -fsSL https://get.docker.com | sh -s -- --version "$DOCKER_VERSION"
  # apt upgrade ставит патчи, но не новую мажорную версию: та бывает несовместимой
  # (Docker 29 поднял минимальный API и сломал чужие инструменты). Переезд на неё
  # делаем сами, проверив
  cat >/etc/apt/preferences.d/director-docker <<EOF
Package: docker-ce docker-ce-cli docker-ce-rootless-extras
Pin: version 5:${DOCKER_VERSION%%.*}.*
Pin-Priority: 1001
EOF
}

resolve_version() {
  if [ -n "${DIRECTOR_VERSION:-}" ]; then
    VERSION="${DIRECTOR_VERSION#v}"
  else
    # /releases/latest переадресует на /releases/tag/vX.Y.Z последнего релиза
    local url
    url="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")"
    case "$url" in
      */releases/tag/v*) VERSION="${url##*/tag/v}" ;;
      *) fail "no published release found; set DIRECTOR_VERSION" ;;
    esac
  fi
  [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || fail "bad version: $VERSION"
}

resolve_host() {
  if [ -n "${DIRECTOR_HOST:-}" ]; then
    HOST="$DIRECTOR_HOST"
    return
  fi
  local ip=""
  for service in https://api.ipify.org https://ifconfig.me/ip; do
    ip="$(curl -4 -fsS --max-time 5 "$service" || true)"
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && break
    ip=""
  done
  [ -n "$ip" ] || fail "cannot detect public IPv4; set DIRECTOR_HOST=your.domain"
  # sslip.io отвечает этим IP на любое имя вида 1-2-3-4.sslip.io: сертификат без своего домена
  HOST="${ip//./-}.sslip.io"
}

write_files() {
  say "Downloading Director $VERSION to $DIR"
  mkdir -p "$DIR"
  chmod 700 "$DIR"
  local base="https://github.com/$REPO/releases/download/v$VERSION"
  curl -fsSL -o "$DIR/docker-compose.yml" "$base/docker-compose.yml"
  curl -fsSL -o "$DIR/Caddyfile" "$base/Caddyfile"

  SETUP_TOKEN="$(openssl rand -hex 16)"
  # umask до записи: файл с секретами ни на миг не бывает читаем другими
  (
    umask 077
    cat >"$DIR/.env" <<EOF
DIRECTOR_HOST=$HOST
DIRECTOR_VERSION=$VERSION
POSTGRES_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 32)
SETUP_TOKEN=$SETUP_TOKEN
EOF
  )
}

start() {
  say "Starting Director"
  cd "$DIR"
  docker compose pull --quiet
  docker compose up -d

  say "Waiting for the API"
  local api status=""
  api="$(docker compose ps -q api)"
  for _ in $(seq 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$api" 2>/dev/null || true)"
    [ "$status" = healthy ] && break
    sleep 2
  done
  [ "$status" = healthy ] || fail "API did not start, see: cd $DIR && docker compose logs api"

  say "Waiting for the HTTPS certificate"
  # через 127.0.0.1: не все хостеры пускают сервер к своему же внешнему IP
  for _ in $(seq 60); do
    curl -fsS -o /dev/null --resolve "$HOST:443:127.0.0.1" "https://$HOST/login" && return
    sleep 2
  done
  fail "no HTTPS for $HOST, see: cd $DIR && docker compose logs caddy"
}

main() {
  check_system
  install_docker
  resolve_version
  resolve_host
  write_files
  start

  cat <<EOF

Director $VERSION is installed.

  Open:  https://$HOST/setup?token=$SETUP_TOKEN

Settings and secrets: $DIR/.env
Back up SECRET_KEY from it: without the key a database backup is useless.
EOF
}

# весь скрипт выше это функции: оборванная загрузка до этой строки ничего не выполнит
main "$@"
