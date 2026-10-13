# Installing Director

[Русский](self-hosting.md)

## Requirements

- A server with Ubuntu 22.04+ or Debian 12+, amd64 or arm64
- At least 1 GB of memory (2 GB is more comfortable), at least 10 GB of disk
- A public IPv4 address and free ports 80 and 443
- root or sudo access

You create the Meta app after installing: the admin panel shows what goes
where. A detailed guide for the Meta app is on its way.

## Install

```sh
curl -fsSL https://opendirector.dev/install.sh | sudo bash
```

To read the script first:

```sh
curl -fsSLO https://opendirector.dev/install.sh
less install.sh
sudo bash install.sh
```

What the script does:

1. Checks the system, the CPU and that the ports are free.
2. Installs Docker if it is missing and pins its version, so `apt upgrade`
   does not update it behind your back.
3. Downloads the release files to `/opt/director` and creates `.env` with
   random secrets, readable only by root.
4. Builds an address like `203-0-113-5.sslip.io` from the server IP: HTTPS
   works on it right away, no domain needed.
5. Starts Director and waits for the Let's Encrypt certificate.
6. Prints a link to the first sign-in. It creates the owner and works once.

To install a specific version: `sudo DIRECTOR_VERSION=0.1.0 bash install.sh`.

## Your own domain

Point the domain's A record to the server IP and pass the domain on install:

```sh
curl -fsSL https://opendirector.dev/install.sh | sudo DIRECTOR_HOST=director.example.com bash
```

If Director is already installed: change `DIRECTOR_HOST` in
`/opt/director/.env` and run `cd /opt/director && docker compose up -d`.
Caddy gets the certificate by itself. Update the webhook and login addresses
in your Meta app.

## Updates

When a new version comes out, an "Update available" button appears above
your profile in the admin panel. The window shows what's new, and the "Update"
button does the rest: downloads the new version, saves a database dump and
`.env`, switches over and checks that everything is up. If the new version
does not start, Director brings back the previous one together with the
database. The admin panel is unavailable for a couple of minutes meanwhile.

You can also update from the server console:

```sh
curl -fsSL https://opendirector.dev/install.sh | sudo bash -s update
```

A specific version: `… | sudo bash -s update 0.2.0`.

The update log is in `/opt/director/run/update.log`. The button is run by the
`director-update` systemd service, which the installer sets up. If the button
does nothing, check `journalctl -u director-update`.

A test server can be offered pre-releases too: add `DIRECTOR_CHANNEL=rc` to
`/opt/director/.env` and run `cd /opt/director && docker compose up -d`.

## Backups

Director makes a backup only before an update: the last three are in
`/opt/director/backups` on the same disk. They will not help if you lose the
server.

What we recommend:

- turn on server snapshots at your hosting provider;
- dump the database on a schedule and copy it to another machine:

  ```sh
  # crontab -e, every day at 3:00
  0 3 * * * cd /opt/director && docker compose exec -T db pg_dump -U director -Fc director > /root/director-$(date +\%F).dump
  ```

- **keep a copy of `/opt/director/.env`.** Instagram tokens in the database
  are encrypted with `SECRET_KEY`, and a dump is useless without it.

To restore a dump (on the same Director version that made it):

```sh
cd /opt/director
docker compose stop api worker web
docker compose exec -T db dropdb -U director --force director
docker compose exec -T db createdb -U director director
docker compose exec -T db pg_restore -U director -d director < director.dump
docker compose up -d
```

## Delete a person's data on request

The `/privacy` page says a follower can ask to have their data deleted. There
is no automatic deletion yet, so you do it by hand with two commands on the
server.

First find the person's Instagram id by their username (without `@`):

```sh
cd /opt/director
docker compose exec -T db psql -U director -d director -v nick=username <<'SQL'
SELECT DISTINCT person_id FROM activity.event
  WHERE lower(data->>'username') = lower(:'nick');
SQL
```

The username is found if the person left comments. Direct messages arrive
without a username, only with an id.

Then put the id into `pid` and delete everything linked to it: their comments
and messages, replies to them, events and deliveries. It all runs in one
transaction: if something goes wrong, the database stays as it was.

```sh
docker compose exec -T db psql -U director -d director -v ON_ERROR_STOP=1 -v pid=1234567890 <<'SQL'
BEGIN;
-- all of the person's comments: replies under them are found by these ids
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

If the person writes again, Director treats them as new.

## Server tips

**Firewall.** The installer does not touch it: a firewall turned on without
an SSH rule locks you out of the server. If you want one, allow SSH first:

```sh
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw allow 443/udp
ufw enable
```

**Low memory.** On a 1 GB server without swap, the kernel can kill the
database during an update. Add 1 GB of swap:

```sh
fallocate -l 1G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Many VPS images run `fwupd`, a firmware update service. A virtual machine
does not need it, and it takes about 190 MB: `systemctl disable --now fwupd`.

## What is where

Everything is in `/opt/director`, with a description in its `README.md`.

## Uninstall

```sh
cd /opt/director && docker compose down -v
systemctl disable --now director-update.path
rm /etc/systemd/system/director-update.*
rm -rf /opt/director
```

`down -v` deletes the database too. Make a backup if you still need the data.
