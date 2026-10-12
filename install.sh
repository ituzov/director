#!/usr/bin/env bash
# Установка Директора на чистый сервер:
#   curl -fsSL https://github.com/ituzov/director/releases/latest/download/install.sh | sudo bash
# Обновление (без версии до последней):
#   curl -fsSL https://github.com/ituzov/director/releases/latest/download/install.sh | sudo bash -s update [0.2.0]
# Переменные: DIRECTOR_VERSION (по умолчанию последний релиз),
# DIRECTOR_HOST (по умолчанию IP.sslip.io), DIRECTOR_DIR (/opt/director)
set -euo pipefail

REPO="ituzov/director"
DIR="${DIRECTOR_DIR:-/opt/director}"
# версию скрипта вписывает CI при релизе: обновлять должен скрипт той версии, на которую идём
SCRIPT_VERSION="dev"
# минорная версия: get.docker.com поставит последний патч к ней
DOCKER_VERSION="29.9"
# бэкапы перед обновлением: нужны для отката, а не для хранения
KEEP_BACKUPS=3

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
fail() {
  printf '\033[31mError: %s\033[0m\n' "$*" >&2
  exit 1
}

# Переменные .env, которые нужны этой версии. Список полный, а не «что нового»:
# скрипт, перепрыгнувший через несколько версий, создаст всё пропущенное.
# Строку убирают, только когда переменная не нужна ни одной поддерживаемой версии
required_env() {
  ensure_env POSTGRES_PASSWORD "openssl rand -hex 24"
  ensure_env SECRET_KEY "openssl rand -hex 32"
  ensure_env SETUP_TOKEN "openssl rand -hex 16"
}

# --- .env: единственное место, где файл меняется -------------------------------

env_get() { sed -n "s/^$1=//p" "$DIR/.env" | tail -1; }

# Дописать переменную, если её нет. Существующую не трогает никогда:
# перезапись SECRET_KEY сделала бы все токены Instagram нечитаемыми
ensure_env() {
  grep -q "^$1=" "$DIR/.env" && return 0
  printf '%s=%s\n' "$1" "$($2)" >>"$DIR/.env"
}

# Заменить строку версии атомарно: временный файл и mv, без половины файла при сбое
set_version() {
  local tmp="$DIR/.env.tmp"
  (
    umask 077
    sed "s/^DIRECTOR_VERSION=.*/DIRECTOR_VERSION=$1/" "$DIR/.env" >"$tmp"
  )
  mv "$tmp" "$DIR/.env"
}

# Каждая прежняя строка, кроме версии, на месте и с тем же значением
check_env() {
  local line
  while IFS= read -r line; do
    case "$line" in DIRECTOR_VERSION=* | "") continue ;; esac
    grep -qxF -- "$line" "$DIR/.env" || return 1
  done <"$1"
}

# --- проверки ------------------------------------------------------------------

check_system() {
  [ "$(id -u)" -eq 0 ] || fail "run as root: curl ... | sudo bash"
  [ -r /etc/os-release ] || fail "unknown OS: Ubuntu 22.04+ or Debian 12+ required"
  # shellcheck source=/dev/null
  . /etc/os-release
  case "${ID:-}" in
    ubuntu | debian) ;;
    *) fail "unsupported OS ${ID:-?}: Ubuntu 22.04+ or Debian 12+ required" ;;
  esac
  for tool in curl openssl ss flock; do
    command -v "$tool" >/dev/null || fail "$tool is missing: apt install curl openssl iproute2 util-linux"
  done
  case "$(uname -m)" in
    x86_64 | aarch64) ;;
    *) fail "unsupported CPU $(uname -m): amd64 or arm64 required" ;;
  esac
}

check_fresh() {
  # второй запуск перезаписал бы секреты, и токены Instagram стали бы нечитаемы
  [ ! -e "$DIR/.env" ] || fail "Director is already installed in $DIR, to update: install.sh update"
  for port in 80 443; do
    if ss -ltnH "sport = :$port" | grep -q .; then
      fail "port $port is busy: Director needs 80 and 443 for HTTPS"
    fi
  done
}

check_installed() {
  [ -e "$DIR/.env" ] || fail "Director is not installed in $DIR"
  docker compose version >/dev/null 2>&1 || fail "'docker compose' is missing"
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

# --- версия, адрес, файлы релиза -----------------------------------------------

resolve_version() {
  if [ -n "${1:-}" ]; then
    VERSION="${1#v}"
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

# Файлы релиза во временную папку: рабочие не трогаем, пока всё не скачано
download_release() {
  local base="https://github.com/$REPO/releases/download/v$VERSION" file
  for file in docker-compose.yml Caddyfile; do
    curl -fsSL -o "$1/$file" "$base/$file" || fail "cannot download $file of $VERSION"
  done
  grep -q '^services:' "$1/docker-compose.yml" || fail "broken docker-compose.yml in $VERSION"
}

# api здоров и HTTPS отвечает. Не падает сам: при обновлении после него откат
wait_healthy() {
  local api status=""
  api="$(docker compose ps -q api)"
  for _ in $(seq 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$api" 2>/dev/null || true)"
    [ "$status" = healthy ] && break
    sleep 2
  done
  [ "$status" = healthy ] || return 1
  # через 127.0.0.1: не все хостеры пускают сервер к своему же внешнему IP
  for _ in $(seq 60); do
    curl -fsS -o /dev/null --resolve "$HOST:443:127.0.0.1" "https://$HOST/login" && return 0
    sleep 2
  done
  return 1
}

# Шаг обновления для админки: одна строка, без секретов
status() {
  say "$*"
  mkdir -p "$DIR/run"
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >"$DIR/run/update-status.tmp"
  mv "$DIR/run/update-status.tmp" "$DIR/run/update-status"
}

# --- установка -------------------------------------------------------------------

install() {
  check_system
  check_fresh
  install_docker
  resolve_version "${DIRECTOR_VERSION:-}"
  resolve_host

  say "Downloading Director $VERSION to $DIR"
  mkdir -p "$DIR"
  chmod 700 "$DIR"
  download_release "$DIR"
  # umask до записи: файл с секретами ни на миг не бывает читаем другими
  (
    umask 077
    printf 'DIRECTOR_HOST=%s\nDIRECTOR_VERSION=%s\n' "$HOST" "$VERSION" >"$DIR/.env"
  )
  required_env

  say "Starting Director"
  cd "$DIR"
  docker compose pull --quiet
  docker compose up -d
  say "Waiting for the API and the HTTPS certificate"
  wait_healthy || fail "Director did not start, see: cd $DIR && docker compose logs"

  cat <<EOF

Director $VERSION is installed.

  Open:  https://$HOST/setup?token=$(env_get SETUP_TOKEN)

Settings and secrets: $DIR/.env
Back up SECRET_KEY from it: without the key a database backup is useless.
EOF
}

# --- обновление ------------------------------------------------------------------

update() {
  check_system
  check_installed
  resolve_version "${1:-${DIRECTOR_VERSION:-}}"
  cd "$DIR"

  # обновлять должен скрипт целевой версии: он знает её переменные и шаги
  if [ "$VERSION" != "$SCRIPT_VERSION" ] && [ -z "${DIRECTOR_REEXEC:-}" ]; then
    local script
    script="$(mktemp)"
    curl -fsSL -o "$script" "https://github.com/$REPO/releases/download/v$VERSION/install.sh" ||
      fail "cannot download install.sh of $VERSION"
    DIRECTOR_REEXEC=1 exec bash "$script" update "$VERSION"
  fi

  # нажали «Обновить» в админке и одновременно запустили из консоли: второй ждать не будет
  exec 9>"$DIR/.update.lock"
  flock -n 9 || fail "another update is running"

  OLD="$(env_get DIRECTOR_VERSION)"
  HOST="$(env_get DIRECTOR_HOST)"
  if [ "$OLD" = "$VERSION" ]; then
    status "done $VERSION: already up to date"
    return
  fi

  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT

  # всё тяжёлое, пока работает старая версия: оборвётся здесь, ничего не тронуто
  status "download $OLD -> $VERSION"
  download_release "$TMP"
  status "pull $VERSION"
  DIRECTOR_VERSION="$VERSION" docker compose -f "$TMP/docker-compose.yml" \
    --project-directory "$DIR" pull --quiet

  status "backup $OLD"
  BACKUP="$DIR/backups/$(date -u +%Y%m%d-%H%M%S)-$OLD"
  (
    umask 077
    mkdir -p "$BACKUP"
    # дамп без ключа бесполезен: токены в базе зашифрованы SECRET_KEY, поэтому вместе
    docker compose exec -T db pg_dump -U director -Fc director >"$BACKUP/db.dump"
    cp -p "$DIR/.env" "$BACKUP/.env"
  )
  [ -s "$BACKUP/db.dump" ] || fail "database backup is empty, nothing was changed"

  status "switch $OLD -> $VERSION"
  required_env
  set_version "$VERSION"
  if ! check_env "$BACKUP/.env"; then
    cp -p "$BACKUP/.env" "$DIR/.env"
    fail "the new script lost settings in .env, restored it, nothing else was changed"
  fi
  local file
  for file in docker-compose.yml Caddyfile; do
    cp -p "$DIR/$file" "$DIR/$file.prev"
    mv "$TMP/$file" "$DIR/$file"
  done

  status "start $VERSION"
  if ! docker compose up -d || ! wait_healthy; then
    rollback
  fi

  status "cleanup"
  docker image rm "ghcr.io/$REPO-api:$OLD" "ghcr.io/$REPO-web:$OLD" >/dev/null 2>&1 || true
  # самые старые бэкапы прочь, последние KEEP_BACKUPS остаются
  find "$DIR/backups" -mindepth 1 -maxdepth 1 -type d | sort | head -n "-$KEEP_BACKUPS" |
    xargs -r rm -rf
  status "done $OLD -> $VERSION"
}

# Новая версия не поднялась: старые файлы, база из бэкапа (миграции могли
# изменить схему), старая версия. Переменные, что дописал ensure_env, остаются:
# старая версия про них не знает и не читает
rollback() {
  status "rollback $VERSION -> $OLD"
  set_version "$OLD"
  local file
  for file in docker-compose.yml Caddyfile; do
    mv "$DIR/$file.prev" "$DIR/$file"
  done
  # пишущих в базу останавливаем, чтобы восстановление не смешалось с записью
  docker compose stop api worker web >/dev/null 2>&1 || true
  docker compose exec -T db pg_restore -U director -d director --clean --if-exists \
    <"$BACKUP/db.dump" ||
    fail "rollback: cannot restore the database, backup is in $BACKUP"
  docker compose up -d
  if wait_healthy; then
    status "failed $VERSION, rolled back to $OLD"
    fail "update to $VERSION failed, Director $OLD is back, backup is in $BACKUP"
  fi
  status "failed $VERSION, rollback to $OLD did not start"
  fail "rollback did not start, backup is in $BACKUP, see: cd $DIR && docker compose logs"
}

main() {
  case "${1:-install}" in
    install) install ;;
    update) update "${2:-}" ;;
    *) fail "usage: install.sh [install | update [VERSION]]" ;;
  esac
}

# весь скрипт выше это функции: оборванная загрузка до этой строки ничего не выполнит.
# DIRECTOR_TEST: тесты подключают функции, не запуская установку
[ -n "${DIRECTOR_TEST:-}" ] || main "$@"
