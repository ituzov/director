#!/usr/bin/env bash
# проверки в одинарных кавычках нарочно: их выполняет eval в check
# shellcheck disable=SC2016
# Тесты install.sh: .env (секреты не теряются и не меняются при обновлении,
# недостающее дописывается, повтор ничего не меняет) и просьба из админки.
# Запуск: sudo bash install.test.sh, на Linux (нужны flock и root для владельца папок)
set -euo pipefail

DIRECTOR_TEST=1
DIRECTOR_DIR="$(mktemp -d)"
DIRECTOR_UNIT_DIR="$(mktemp -d)"
trap 'rm -rf "$DIRECTOR_DIR" "$DIRECTOR_UNIT_DIR"' EXIT
# shellcheck source=install.sh
. "$(dirname "$0")/install.sh"

failed=0
check() {
  if eval "$2"; then
    printf 'ok   %s\n' "$1"
  else
    printf 'FAIL %s\n' "$1"
    failed=1
  fi
}

# .env установки самой старой поддерживаемой версии: без SETUP_TOKEN, с лишним своим
old_env() {
  cat >"$DIR/.env" <<'ENV'
DIRECTOR_HOST=1-2-3-4.sslip.io
DIRECTOR_VERSION=0.1.0
POSTGRES_PASSWORD=old-password
SECRET_KEY=old-secret
OWNER_NOTE=keep me
ENV
  chmod 600 "$DIR/.env"
}

old_env
cp "$DIR/.env" "$DIR/before"
required_env
set_version 0.2.0
check "секреты не изменились" 'grep -qx "SECRET_KEY=old-secret" "$DIR/.env" && grep -qx "POSTGRES_PASSWORD=old-password" "$DIR/.env"'
check "чужая строка владельца на месте" 'grep -qx "OWNER_NOTE=keep me" "$DIR/.env"'
check "пропущенная переменная дописана" '[ -n "$(env_get SETUP_TOKEN)" ]'
check "версия новая и одна" '[ "$(grep -c "^DIRECTOR_VERSION=" "$DIR/.env")" = 1 ] && [ "$(env_get DIRECTOR_VERSION)" = 0.2.0 ]'
check "права 600 после замены версии" '[ "$(stat -c %a "$DIR/.env" 2>/dev/null || stat -f %Lp "$DIR/.env")" = 600 ]'
check "сверка с прежним проходит" 'check_env "$DIR/before"'

cp "$DIR/.env" "$DIR/after"
required_env
set_version 0.2.0
check "повтор ничего не меняет" 'cmp -s "$DIR/.env" "$DIR/after"'

# сломанный скрипт: строка потерялась или значение поменялось
grep -v "^SECRET_KEY=" "$DIR/after" >"$DIR/.env"
check "сверка ловит потерянную строку" '! check_env "$DIR/before"'
sed "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=new/" "$DIR/after" >"$DIR/.env"
check "сверка ловит изменённое значение" '! check_env "$DIR/before"'

# --- обновление: пишущие в базу на паузе, пока снимается дамп ----------------------
# всё внешнее заглушками, docker пишет вызовы в файл: проверяем их порядок
upgrade() {
  rm -f "$DIR/docker"
  old_env
  (
    check_system() { :; }
    check_installed() { :; }
    download_release() { touch "$1/docker-compose.yml" "$1/Caddyfile" "$1/install.sh"; }
    install_units() { :; }
    write_readme() { :; }
    wait_healthy() { :; }
    docker() {
      printf '%s\n' "$*" >>"$DIR/docker"
      case "$*" in *pg_dump*) printf '%s' "${DUMP:-}" ;; esac
    }
    SCRIPT_VERSION=0.2.0
    update 0.2.0
  ) >/dev/null 2>&1 || true
}
# номер строки первого вызова docker, подходящего под шаблон. Зовут его проверки
# через eval в check, shellcheck этого не видит
# shellcheck disable=SC2329
at() { grep -n -m1 -- "$1" "$DIR/docker" | cut -d: -f1; }

DUMP=dump upgrade
check "обновление дошло до конца" 'tail -n 1 "$DIR/run/update-status" | grep -q " done 0.1.0 -> 0.2.0$"'
check "обновление: api и worker на паузе до дампа" '[ "$(at "^compose stop api worker$")" -lt "$(at pg_dump)" ]'
check "обновление: новая версия запущена" 'grep -qx "compose up -d" "$DIR/docker"'
check "обновление: старые после старта не возвращаются" '! grep -q "^compose start" "$DIR/docker"'

DUMP="" upgrade
check "пустой дамп: api и worker возвращены" '[ "$(at "^compose start api worker$")" -gt "$(at pg_dump)" ]'
check "пустой дамп: новая версия не запускалась" '[ -n "$(at pg_dump)" ] && ! grep -q "^compose up" "$DIR/docker"'

# --- просьба из админки ----------------------------------------------------------
# настоящий update не нужен: проверяем, что request передал и чего не тронул
update() { printf '%s %s\n' "$1" "${DIRECTOR_REQUEST:-}" >"$DIR/called"; }
mkdir -p "$DIR/request"
ask() { rm -f "$DIR/called"; (request) >/dev/null 2>&1 || true; }

printf '0.2.0\nrm -rf /\n' >"$DIR/request/update"
ask
check "просьба: версия из первой строки" '[ "$(cat "$DIR/called")" = "0.2.0 1" ]'
check "просьба: файл удалён" '[ ! -e "$DIR/request/update" ]'
check "просьба: статус сброшен" 'grep -q " requested 0.2.0$" "$DIR/run/update-status"'

printf '9.9.9\n' >"$DIR/secret"
ln -s "$DIR/secret" "$DIR/request/update"
ask
check "ссылку не читаем" '[ ! -e "$DIR/called" ]'
check "ссылку удаляем, цель цела" '[ ! -L "$DIR/request/update" ] && [ "$(cat "$DIR/secret")" = 9.9.9 ]'

# идёт другое обновление: его статус и лог на месте
printf '2026-01-01T00:00:00Z pull 0.3.0\n' >"$DIR/run/update-status"
printf 'pulling\n' >"$DIR/run/update.log"
flock "$DIR/.update.lock" sleep 3 &
sleep 0.5
printf '0.4.0\n' >"$DIR/request/update"
ask
kill $! 2>/dev/null || true
check "занято: update не запущен" '[ ! -e "$DIR/called" ]'
check "занято: статус чужого обновления цел" 'grep -q " pull 0.3.0$" "$DIR/run/update-status"'
check "занято: лог чужого обновления цел" '[ "$(cat "$DIR/run/update.log")" = pulling ]'

# итог на доске от fail: пишется, но не поверх отката
printf '2026-01-01T00:00:00Z pull 0.3.0\n' >"$DIR/run/update-status"
(DIRECTOR_REQUEST=1 fail "no network") >/dev/null 2>&1 || true
check "ошибка попала на доску" 'grep -q " error: no network$" "$DIR/run/update-status"'
printf '2026-01-01T00:00:00Z failed 0.3.0, rolled back to 0.2.0\n' >"$DIR/run/update-status"
(DIRECTOR_REQUEST=1 fail "update to 0.3.0 failed") >/dev/null 2>&1 || true
check "итог отката не затёрт" 'grep -q " failed 0.3.0, rolled back to 0.2.0$" "$DIR/run/update-status"'
printf '2026-01-01T00:00:00Z pull 0.3.0\n' >"$DIR/run/update-status"
(fail "from console") >/dev/null 2>&1 || true
check "из консоли доску не трогаем" 'grep -q " pull 0.3.0$" "$DIR/run/update-status"'

# --- вывод в файл без кодов цвета ------------------------------------------------------
# так его пишет обновление в run/update.log, а хвост лога показывает админка
check "say в файл без цвета" '[ "$(say "pull 0.2.0")" = "==> pull 0.2.0" ]'
check "ошибка в файл без цвета" '[ "$( (unset DIRECTOR_REQUEST; fail "no network") 2>&1)" = "Error: no network" ]'

# --- итог установки на доске ---------------------------------------------------------
# всё внешнее заглушками: проверяем только, чем установка заканчивает доску
(
  check_system() { :; }
  check_fresh() { :; }
  install_docker() { :; }
  resolve_host() { HOST=1-2-3-4.sslip.io; }
  download_release() { :; }
  install_units() { :; }
  write_readme() { :; }
  docker() { :; }
  wait_healthy() { status "waiting for https://$HOST to respond (up to 2 min)"; }
  DIRECTOR_VERSION=0.2.0 install
) >/dev/null 2>&1 || true
check "установка заканчивает доску итогом" 'tail -n 1 "$DIR/run/update-status" | grep -q " done 0.2.0: installed$"'
check "итог установки понятен как законченный" 'finished'

# --- юниты и папки кнопки ----------------------------------------------------------
# владелец папки меняется только от root: в CI тесты идут через sudo
if [ "$(id -u)" -eq 0 ]; then
  systemctl() { printf '%s\n' "$*" >>"$DIR/systemctl"; }
  (install_units) >/dev/null 2>&1 || true
  check "юниты: следят за просьбой" 'grep -qx "PathExists=$DIR/request/update" "$UNIT_DIR/director-update.path"'
  check "юниты: запускают request" 'grep -qx "ExecStart=$DIR/install.sh request" "$UNIT_DIR/director-update.service"'
  check "юниты: слежка включена" 'grep -qx "enable --now director-update.path" "$DIR/systemctl"'
  check "request/ у api (uid 1000), 700" '[ "$(stat -c %u:%a "$DIR/request")" = 1000:700 ]'
  check "run/ у root, 755" '[ "$(stat -c %u:%a "$DIR/run")" = 0:755 ]'
else
  printf 'skip юниты и папки: нужен root\n'
fi

exit "$failed"
