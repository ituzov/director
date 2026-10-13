# Установка Директора

[English](self-hosting.en.md)

## Что нужно

- Сервер на Ubuntu 22.04+ или Debian 12+, процессор amd64 или arm64
- Память от 1 ГБ (с 2 ГБ спокойнее), диск от 10 ГБ
- Публичный IPv4 и свободные порты 80 и 443
- Доступ root или sudo

Приложение Meta создаёте после установки: админка подскажет, куда что
вписать. Подробная инструкция по приложению Meta готовится.

## Установка

```sh
curl -fsSL https://github.com/ituzov/director/releases/latest/download/install.sh | sudo bash
```

Если хотите сначала прочитать скрипт:

```sh
curl -fsSLO https://github.com/ituzov/director/releases/latest/download/install.sh
less install.sh
sudo bash install.sh
```

Что делает скрипт:

1. Проверяет систему, процессор и свободные порты.
2. Ставит Docker, если его нет, и закрепляет версию, чтобы `apt upgrade` не
   обновил его без вас.
3. Скачивает файлы релиза в `/opt/director` и создаёт `.env` со случайными
   секретами, доступный только root.
4. Собирает адрес вида `203-0-113-5.sslip.io` из IP сервера: по нему сразу
   работает HTTPS, домен не нужен.
5. Запускает Директор и ждёт сертификат Let's Encrypt.
6. Печатает ссылку на первый вход. По ней создаётся владелец, ссылка
   одноразовая.

Поставить конкретную версию: `sudo DIRECTOR_VERSION=0.1.0 bash install.sh`.

## Свой домен

Направьте A-запись домена на IP сервера и укажите домен при установке:

```sh
curl -fsSL https://github.com/ituzov/director/releases/latest/download/install.sh | sudo DIRECTOR_HOST=director.example.com bash
```

Если Директор уже стоит: поменяйте `DIRECTOR_HOST` в `/opt/director/.env` и
выполните `cd /opt/director && docker compose up -d`. Caddy сам получит
сертификат. В приложении Meta поменяйте адреса вебхука и входа на новые.

## Обновление

```sh
curl -fsSL https://github.com/ituzov/director/releases/latest/download/install.sh | sudo bash -s update
```

Конкретная версия: `… | sudo bash -s update 0.2.0`.

Пока скачиваются образы, работает старая версия. Перед переключением скрипт
сохраняет дамп базы и `.env`. Если новая версия не поднялась, он сам
возвращает прошлую вместе с базой и пишет, где лежит бэкап. Ход обновления
пишется в `/opt/director/run/update.log`.

## Бэкапы

Сам Директор делает бэкап только перед обновлением: последние три лежат в
`/opt/director/backups` на том же диске. От потери сервера они не спасут.

Что советуем:

- включить снапшоты сервера у хостера;
- снимать дамп базы по расписанию и уносить его на другую машину:

  ```sh
  # crontab -e, каждый день в 3:00
  0 3 * * * cd /opt/director && docker compose exec -T db pg_dump -U director -Fc director > /root/director-$(date +\%F).dump
  ```

- **сохранить `/opt/director/.env` отдельно.** Токены Instagram в базе
  зашифрованы `SECRET_KEY`, без него дамп бесполезен.

Восстановить дамп (на той же версии Директора, что его сняла):

```sh
cd /opt/director
docker compose stop api worker web
docker compose exec -T db dropdb -U director --force director
docker compose exec -T db createdb -U director director
docker compose exec -T db pg_restore -U director -d director < director.dump
docker compose up -d
```

## Удалить данные человека по просьбе

На странице `/privacy` написано, что подписчик может попросить удалить его
данные. Автоматического удаления пока нет, поэтому это делается вручную,
двумя командами на сервере.

Сначала найдите id человека в Instagram по нику (без `@`):

```sh
cd /opt/director
docker compose exec -T db psql -U director -d director -v nick=ник <<'SQL'
SELECT DISTINCT person_id FROM activity.event
  WHERE lower(data->>'username') = lower(:'nick');
SQL
```

Ник находится, если человек оставлял комментарии. Сообщения в директ
приходят без ника, только с id.

Затем подставьте id в `pid` и удалите всё, что с ним связано: его комменты и
сообщения, ответы ему, события и доставки. Всё удаляется одной транзакцией:
если что-то пошло не так, база останется как была.

```sh
docker compose exec -T db psql -U director -d director -v ON_ERROR_STOP=1 -v pid=1234567890 <<'SQL'
BEGIN;
-- все комменты человека: по ним же ищем ответы под комментами
CREATE TEMP TABLE forget_comments AS
SELECT comment_id FROM autoreplies.delivery WHERE person_id = :'pid'
UNION SELECT comment_id FROM activity.event WHERE person_id = :'pid'
UNION SELECT payload->>'id' FROM instagram.inbox
  WHERE kind = 'comment' AND payload->'from'->>'id' = :'pid';

DELETE FROM instagram.outbox
  WHERE payload->>'recipient_id' = :'pid'
     OR payload->>'comment_id' IN (SELECT comment_id FROM forget_comments);
DELETE FROM instagram.inbox
  WHERE payload->'from'->>'id' = :'pid' OR payload->'sender'->>'id' = :'pid';
DELETE FROM activity.event
  WHERE person_id = :'pid' OR comment_id IN (SELECT comment_id FROM forget_comments);
DELETE FROM autoreplies.delivery WHERE person_id = :'pid';
COMMIT;
SQL
```

Если человек напишет снова, Директор ответит ему как новому.

## Советы по серверу

**Файрвол.** Установщик его не трогает: включённый без правила для SSH
файрвол отрежет вас от сервера. Если хотите включить, сначала разрешите SSH:

```sh
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw allow 443/udp
ufw enable
```

**Мало памяти.** На сервере с 1 ГБ без подкачки ядро может убить базу в
момент обновления. Добавьте swap на 1 ГБ:

```sh
fallocate -l 1G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

На многих VPS работает `fwupd`, служба обновления прошивок. На виртуальной
машине она не нужна и занимает около 190 МБ: `systemctl disable --now fwupd`.

## Где что лежит

Всё в `/opt/director`, описание там же, в `README.md`.

## Удаление

```sh
cd /opt/director && docker compose down -v
systemctl disable --now director-update.path
rm /etc/systemd/system/director-update.*
rm -rf /opt/director
```

`down -v` удаляет и базу. Сделайте бэкап, если данные ещё нужны.
