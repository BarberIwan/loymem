# Beslissingen

Elke regel: wat er besloten is, waarom, en wat het terugdraaien kost.

## LM-01 Stack
Backend FastAPI, SQLAlchemy 2, Pydantic v2, Alembic, PostgreSQL 16, Python 3.12+.
Frontend Next.js (app router), TypeScript, next-intl, pnpm. Geen CSS-framework:
CSS-modules op de tokens uit `DESIGN.md`, zodat een losse kleur of maat statisch
te vinden is. Bekend gereedschap, dezelfde vorm als Solven, één persoon kan het
onderhouden.

## LM-02 Tenant-scheiding in twee lagen
Elke query filtert zelf op `business_id`. Daaronder Row Level Security op elke
tabel met klant- of zaakgegevens, op `app.current_business_id`, met `FORCE ROW
LEVEL SECURITY`. De app verbindt als rol zonder `BYPASSRLS`. Publieke routes
lopen via de slug van de zaak (`/aanmelden/<slug>`, `/k/<slug>/<sleutel>`), zodat
er nooit buiten een zaak gezocht hoeft te worden. Inloggen zoekt de zaak via één
`SECURITY DEFINER`-functie die alleen `business_id` en `staff_id` teruggeeft.

## LM-03 Stempel-idempotentie via de periode
De sleutel van een stempel is `stamp:<klantprogramma>:<periode>`. De periode is
de kalenderdag in de tijdzone van de zaak (standaard) of een blok van N uur.
Dubbele en gelijktijdige scans botsen op de unieke constraint en leveren één
regel. Een tweede stempel op dezelfde dag kan dus alleen door de periode te
verkorten, niet door twee keer te scannen.

## LM-04 Logboek is alleen toevoegen
`ledger_events` en `audit_log` hebben een databasetrigger die `UPDATE` en
`DELETE` weigert. Een correctie is een tegenboeking met `reverses_id` (uniek, dus
één keer) en een reden, alleen door eigenaar of manager. `customer_programs.balance`
is een afgeleide; `herbereken_saldo` en de toets `test_balance_matches_ledger`
bewaken dat hij klopt.

## LM-05 Beloningscode
De kaart vraagt een code van zes cijfers die 90 seconden geldig is en één keer
gebruikt kan worden. Een schermafbeelding is na anderhalve minuut niets waard.
Inwisselen zet de beloning met `WHERE status = 'beschikbaar'` op ingewisseld en
schrijft een logboekregel met sleutel `redeem:<beloning>`; twee kassa's tegelijk
leveren één inwisseling.

## LM-06 Klantlink en scancode zijn twee geheimen
De kaartlink (`/k/<slug>/<sleutel>`) geeft de klant toegang tot zijn kaart. De
scancode in de QR identificeert de klant bij de medewerker en kent nooit iets
toe. Beide worden alleen gehasht opgeslagen. Een nieuwe link aanvragen gaat via
een eenmalige link (30 minuten); gebruiken ervan vervangt beide geheimen, zodat de
oude link en de oude QR niet meer werken.

## LM-07 Sessies van medewerkers
Ondertekende sessie in een `HttpOnly`-cookie met `SameSite=Lax`, 12 uur. Elke
wijzigende aanvraag moet de kop `X-Loymem: 1` dragen (geen formulier van een
andere site kan die zetten). De frontend praat via een rewrite op hetzelfde
domein met de API.

## LM-08 Verzenden in de pilot
E-mail gaat via een uitgaande wachtrij (`outbox`). In ontwikkeling en toetsen
wordt alleen gelogd. Sms en WhatsApp staan uit tot het besluit uit §13.

## LM-09 Fase-0-specificaties niet als code-eis
`docs/spec/` bevat de opdracht en de drie productdocumenten zoals ze zijn
aangeleverd. De statische toetsen op tekst en herkomst slaan die map over; het
zijn bronstukken, geen producttekst.

## LM-10 Mail via gewone SMTP
Versturen loopt via de uitgaande wachtrij en SMTP met STARTTLS, zodat elke
maildienst werkt zodra adres en sleutels gezet zijn (`LOYMEM_EMAIL_DELIVERY=smtp`,
`LOYMEM_SMTP_*`, `LOYMEM_MAIL_FROM_ADDRESS`). Berichten waar een klant nee tegen
kan zeggen hebben een afmeldlink en `List-Unsubscribe`. De link opent een pagina
die zelf afmeldt, zodat linkscanners van mailprogramma's niemand afmelden.
Vijf mislukte pogingen, dan blijft het bericht staan met de fout erbij.
