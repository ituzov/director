#!/usr/bin/env bash
# проверки в одинарных кавычках нарочно: их выполняет eval в check
# shellcheck disable=SC2016
# Тесты работы install.sh с .env: секреты не теряются и не меняются при обновлении,
# недостающее дописывается, повтор ничего не меняет. Запуск: bash install.test.sh
set -euo pipefail

DIRECTOR_TEST=1
DIRECTOR_DIR="$(mktemp -d)"
trap 'rm -rf "$DIRECTOR_DIR"' EXIT
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

exit "$failed"
