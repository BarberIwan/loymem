# Testomgeving op één server

Alles draait met Docker Compose op één server: database, API, website, een
werker (mail en vrije plekken elke minuut, 's nachts abonnementen en de
saldocontrole) en Caddy voor https.

Benodigd: een server met Ubuntu 24.04, een (sub)domein dat naar die server
wijst, en Docker. De CI-server is daar niet voor bedoeld: die draait toetsen.

## Eerste keer

1. Log in op de server als root: `ssh root@<adres-van-de-server>`.
2. Installeer Docker: `curl -fsSL https://get.docker.com | sh`.
3. Haal de code op: `git clone https://github.com/BarberIwan/loymem.git /opt/platform`
   (de repository is privé: maak op GitHub een *fine-grained token* met alleen
   leesrecht op deze repository en gebruik dat als wachtwoord).
4. `cd /opt/platform/deploy && cp env.example .env && nano .env`. Vul in:
   - `LOYMEM_DOMAIN` en `LOYMEM_PUBLIC_BASE_URL` (met `https://`);
   - drie lange wachtwoorden (`POSTGRES_PASSWORD`, `LOYMEM_OWNER_PASSWORD`,
     `LOYMEM_APP_PASSWORD`), en dezelfde twee in de twee database-URL's;
   - `LOYMEM_SECRET_KEY`: `openssl rand -hex 32` geeft er een;
   - `LOYMEM_SIGNUP_CODE`: de code die je aan pilotzaken geeft.
   Opslaan: Ctrl+O, Enter, Ctrl+X.
5. Start: `docker compose up -d --build`. De eerste keer duurt dat een paar minuten.
6. Controleer: `docker compose ps` toont `api`, `web`, `worker`, `caddy` en `db`
   als *running* en `migrate` als *exited (0)*. Open `https://<domein>/inloggen`.
7. Maak de eerste zaak aan op `https://<domein>/aanmelden-zaak` met de code uit stap 4.

## Bijwerken

`cd /opt/platform && git pull && cd deploy && docker compose up -d --build`.
Migraties draaien automatisch vóór de API start.

## Mail aanzetten

In `.env`: `LOYMEM_EMAIL_DELIVERY=smtp` en de `LOYMEM_SMTP_*`-regels en
`LOYMEM_MAIL_FROM_ADDRESS` van de maildienst. Daarna
`docker compose up -d`. Zet bij het domein de SPF- en DKIM-records die de
maildienst opgeeft.

## Logboek bekijken

`docker compose logs -f api worker` (Ctrl+C om te stoppen).
