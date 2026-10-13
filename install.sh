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
# юниты кнопки «Обновить»; тесты подставляют свою папку
UNIT_DIR="${DIRECTOR_UNIT_DIR:-/etc/systemd/system}"

# Цвет только в терминал: в update.log коды цвета превратились бы в мусор,
# а его хвост показывает окно обновления в админке
say() {
  if [ -t 1 ]; then printf '\033[1m==> %s\033[0m\n' "$*"; else printf '==> %s\n' "$*"; fi
}
fail() {
  if [ -t 2 ]; then printf '\033[31mError: %s\033[0m\n' "$*" >&2; else printf 'Error: %s\n' "$*" >&2; fi
  # кнопка в админке ждёт итога в run/update-status: пишем, если его ещё нет
  if [ -n "${DIRECTOR_REQUEST:-}" ] && ! finished; then status "error: $*"; fi
  exit 1
}

# на доске уже итог: done, failed (после отката) или error
finished() { grep -qE '^[^ ]+ (done|failed|error)' "$DIR/run/update-status" 2>/dev/null; }

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
  for file in docker-compose.yml Caddyfile install.sh; do
    curl -fsSL -o "$1/$file" "$base/$file" || fail "cannot download $file of $VERSION"
  done
  grep -q '^services:' "$1/docker-compose.yml" || fail "broken docker-compose.yml in $VERSION"
  # кнопку в админке выполняет этот файл: systemd запускает его напрямую
  grep -q '^main() {' "$1/install.sh" || fail "broken install.sh in $VERSION"
  chmod 755 "$1/install.sh"
}

# api здоров и HTTPS отвечает. Не падает сам: при обновлении после него откат
wait_healthy() {
  local api status=""
  api="$(docker compose ps -q api)"
  status "waiting for api health check (up to 2 min)"
  for _ in $(seq 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$api" 2>/dev/null || true)"
    [ "$status" = healthy ] && break
    sleep 2
  done
  [ "$status" = healthy ] || return 1
  status "waiting for https://$HOST to respond (up to 2 min)"
  # через 127.0.0.1: не все хостеры пускают сервер к своему же внешнему IP
  for _ in $(seq 60); do
    curl -fs -o /dev/null --resolve "$HOST:443:127.0.0.1" "https://$HOST/login" && return 0
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

  # до compose up: папку request/ иначе создаст Docker, от root, и api не сможет писать
  install_units
  write_readme

  say "Starting Director"
  cd "$DIR"
  docker compose pull --quiet
  docker compose up -d
  say "Waiting for the API and the HTTPS certificate"
  wait_healthy || fail "Director did not start, see: cd $DIR && docker compose logs"
  # итог на доску: иначе там висит «waiting for https…», и окно обновления
  # в админке приняло бы его за идущее обновление
  status "done $VERSION: installed"

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
  # до переключения: упадут, и ничего ещё не тронуто. И до compose up: папку
  # request/ иначе создаст Docker, от root, и api не сможет писать
  install_units
  write_readme

  status "switch $OLD -> $VERSION"
  required_env
  set_version "$VERSION"
  if ! check_env "$BACKUP/.env"; then
    cp -p "$BACKUP/.env" "$DIR/.env"
    fail "the new script lost settings in .env, restored it, nothing else was changed"
  fi
  local file
  for file in docker-compose.yml Caddyfile install.sh; do
    # install.sh лежит на сервере с появлением кнопки: при первом обновлении его нет
    [ ! -e "$DIR/$file" ] || cp -p "$DIR/$file" "$DIR/$file.prev"
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
  for file in docker-compose.yml Caddyfile install.sh; do
    [ ! -e "$DIR/$file.prev" ] || mv "$DIR/$file.prev" "$DIR/$file"
  done
  # пишущих в базу останавливаем, чтобы восстановление не смешалось с записью
  docker compose stop api worker web >/dev/null 2>&1 || true
  # в пустую базу: --clean убрал бы только то, что есть в дампе, а таблицы
  # новой версии остались бы и сломали её миграции при следующем обновлении
  if ! {
    docker compose exec -T db dropdb -U director --force director &&
      docker compose exec -T db createdb -U director director &&
      docker compose exec -T db pg_restore -U director -d director <"$BACKUP/db.dump"
  }; then
    fail "rollback: cannot restore the database, backup is in $BACKUP"
  fi
  docker compose up -d
  docker image rm "ghcr.io/$REPO-api:$VERSION" "ghcr.io/$REPO-web:$VERSION" >/dev/null 2>&1 || true
  if wait_healthy; then
    status "failed $VERSION, rolled back to $OLD"
    fail "update to $VERSION failed, Director $OLD is back, backup is in $BACKUP"
  fi
  status "failed $VERSION, rollback to $OLD did not start"
  fail "rollback did not start, backup is in $BACKUP, see: cd $DIR && docker compose logs"
}

# --- кнопка «Обновить» в админке -----------------------------------------------
# api кладёт версию в request/update, systemd на хосте видит файл и запускает
# этот скрипт от root. У api нет ни Docker-сокета, ни root: худшее, что он может,
# попросить одну из опубликованных версий

# шапка юнитов: агент или человек, чистящий сервер, должен понять, что это
unit_header() {
  cat <<EOF
# Director (https://github.com/ituzov/director): "Update" button in the admin panel.
# Created by install.sh. $1
# Without it the button silently does nothing, the site keeps working.
# Remove only together with Director:
#   systemctl disable --now director-update.path
#   rm /etc/systemd/system/director-update.path /etc/systemd/system/director-update.service
#
# Директор: кнопка «Обновить» в админке. Создан install.sh. $2
# Без него кнопка молча не сработает, сам сайт продолжит работать.
# Удалять только вместе с Директором, команды выше.
EOF
}

install_units() {
  # command: утилита install, а не наша функция install() с тем же именем
  command install -d -m 755 "$DIR/run"
  # единственная папка на хосте, куда пишет api (uid 1000 в образе). root здесь
  # только читает и удаляет: запись по подложенной ссылке переписала бы файл хоста
  command install -d -m 700 -o 1000 -g 1000 "$DIR/request"
  {
    unit_header "Watches for the update request from api." \
      "Следит за просьбой об обновлении от api."
    cat <<EOF
[Unit]
Description=Director: start update when the admin panel asks (created by install.sh)

[Path]
PathExists=$DIR/request/update

[Install]
WantedBy=multi-user.target
EOF
  } >"$UNIT_DIR/director-update.path"
  {
    unit_header "Runs install.sh update with the requested version." \
      "Запускает install.sh update с запрошенной версией."
    cat <<EOF
[Unit]
Description=Director: update requested from the admin panel (created by install.sh)

[Service]
# пока работает, второй запуск не стартует; обновление идёт минуты, лимита нет
Type=oneshot
ExecStart=$DIR/install.sh request
EOF
  } >"$UNIT_DIR/director-update.service"
  systemctl daemon-reload
  systemctl enable --now director-update.path >/dev/null 2>&1
}

# что лежит в папке установки: человек или агент на сервере читает это первым
write_readme() {
  cat >"$DIR/README.md" <<EOF
# Director

Self-hosted Director: Instagram comment → direct message.
https://github.com/$REPO

- \`.env\`: settings and secrets. Do not delete it and do not lose SECRET_KEY:
  tokens in the database are encrypted with it.
- \`docker-compose.yml\`, \`Caddyfile\`, \`install.sh\`: files of the current
  version, replaced on update. \`*.prev\`: the previous version, for rollback.
- \`backups/\`: database dump and \`.env\` before each update, the last $KEEP_BACKUPS.
- \`request/\`: the admin panel asks for an update here (written by api).
- \`run/\`: update status and log (written by install.sh).
- systemd \`director-update.path\` and \`director-update.service\`: run the
  update when the admin panel asks. Created by install.sh.

Update: \`curl -fsSL https://opendirector.dev/install.sh | sudo bash -s update\`
Logs: \`cd $DIR && docker compose logs\`, \`journalctl -u director-update\`
Remove everything, including the database:
\`cd $DIR && docker compose down -v\`,
\`systemctl disable --now director-update.path\`, delete
\`/etc/systemd/system/director-update.*\` and this folder.

---

# Директор

Директор на своём сервере: коммент в Instagram → директ.

- \`.env\`: настройки и секреты. Не удаляй его и не теряй SECRET_KEY:
  им зашифрованы токены в базе.
- \`docker-compose.yml\`, \`Caddyfile\`, \`install.sh\`: файлы текущей версии,
  при обновлении заменяются. \`*.prev\`: прошлая версия, для отката.
- \`backups/\`: дамп базы и \`.env\` перед каждым обновлением, последние $KEEP_BACKUPS.
- \`request/\`: сюда админка кладёт просьбу обновиться (пишет api).
- \`run/\`: статус и лог обновления (пишет install.sh).
- systemd \`director-update.path\` и \`director-update.service\`: запускают
  обновление по просьбе из админки. Созданы install.sh.

Обновить: \`curl -fsSL https://opendirector.dev/install.sh | sudo bash -s update\`
Логи: \`cd $DIR && docker compose logs\`, \`journalctl -u director-update\`
Удалить всё вместе с базой:
\`cd $DIR && docker compose down -v\`,
\`systemctl disable --now director-update.path\`, удалить
\`/etc/systemd/system/director-update.*\` и эту папку.
EOF
}

request() {
  local file="$DIR/request/update" version=""
  # файл пишет api, а мы root: по ссылке не идём, больше 64 байт не читаем
  if [ -f "$file" ] && [ ! -L "$file" ]; then
    version="$(head -c 64 "$file" | head -n 1)"
  fi
  # удаляем до обновления: пока файл есть, systemd запускал бы нас снова
  rm -f "$file"
  [ -n "$version" ] || fail "empty update request"
  # нажали, пока идёт другое обновление: его статус и лог не трогаем
  exec 9>"$DIR/.update.lock"
  flock -n 9 || fail "another update is running"
  flock -u 9
  status "requested $version"
  export DIRECTOR_REQUEST=1
  update "$version" >"$DIR/run/update.log" 2>&1
}

main() {
  case "${1:-install}" in
    install) install ;;
    update) update "${2:-}" ;;
    # запускает systemd по просьбе из админки, руками не нужен
    request) request ;;
    *) fail "usage: install.sh [install | update [VERSION]]" ;;
  esac
}

# весь скрипт выше это функции: оборванная загрузка до этой строки ничего не выполнит.
# DIRECTOR_TEST: тесты подключают функции, не запуская установку
[ -n "${DIRECTOR_TEST:-}" ] || main "$@"
