# Koppelingen met boekingssystemen

Elke zaak kan Loymem volledig gebruiken met de boekingslink en de scan aan de
balie. Een koppeling maakt het werk lichter, nooit mogelijk.

## Generieke webhook (beschikbaar)

Voor elk systeem dat een HTTP-aanroep kan sturen bij een afgeronde afspraak.

- **Adres:** `POST /api/v1/hooks/<slug>/appointments`, te zien bij
  Instellingen → Koppeling met je agenda.
- **Ondertekening:** kop `X-Loymem-Timestamp` (Unix-seconden) en
  `X-Loymem-Signature: sha256=<hex>`, de HMAC-SHA256 met de sleutel over
  `<timestamp>.<ruwe body>`. Meer dan vijf minuten verschil wordt geweigerd.
- **Velden:** per zaak in te stellen met punten voor diepere velden. Nodig:
  afspraaknummer, status, en telefoon of e-mail. Optioneel: behandeling
  (vergeleken met de naam van de behandeling, hoofdletterongevoelig) en eindtijd
  (ISO 8601; zonder eindtijd telt het moment van ontvangst).
- **Wat telt:** alleen de statussen die de zaak als afgerond opgeeft. Een
  afspraak in de agenda (geboekt, bevestigd) of een onbekende status geeft nooit
  een stempel.
- **Hoogstens één stempel per periode**, ook als dezelfde afspraak twee keer
  binnenkomt of het bezoek al aan de balie gescand is.
- **Onbekende klant:** er wordt geen klant aangemaakt; aanmelden en toestemming
  blijven bij de klant. Uitkomst `unmatched`.
- **Uitkomsten** in de lijst "Laatste berichten": `stamped`, `duplicate`,
  `not_completion`, `unmatched`, `invalid`, `out_of_range`. Er wordt per bericht
  geen persoonsgegeven bewaard.

Voorbeeld (standaardvelden):

```json
{"id": "a-1", "status": "completed", "customer": {"phone": "0612345678"},
 "service": "Knippen", "ended_at": "2026-11-23T14:30:00+01:00"}
```

## Native koppelingen (matrix)

Nog niet onderzocht; volgt uit fase 0. Per systeem komt hier: koppelmethode,
autorisatie, kosten, partnervereisten, eigen spaarsysteem ja of nee,
geverifieerd ja of nee, bron en datum. Zonder vastgelegd bewijs toont het product
geen koppeling, alleen "boekingslink en medewerkerscan".

## Wallet-passen live bijwerken

Een Apple-pas bevat `webServiceURL` (`<publieke basis>/api/v1/wallet/apple`) en
een eigen token per pas (afgeleid van de serversleutel en de klant, nooit de
kaartlink). De telefoon meldt zich daarmee aan op Apples vaste paden onder
`/api/v1/wallet/apple/v1/…`: aanmelden, afmelden, vragen welke passen veranderd
zijn, de nieuwe pas ophalen en fouten melden.

`scripts/send_wallet_updates.py` draait elke minuut in de werker. Het vergelijkt
per pas wat hij laatst toonde (stempels, beloning, tegoed, naam, kleuren) met de
kaart nu. Is er iets veranderd, dan krijgt elk toestel met die pas een lege push
via APNs (HTTP/2, met het pascertificaat, onderwerp = pass type id) en haalt de
telefoon zelf de nieuwe pas op. Toestellen die Apple als verdwenen meldt, worden
vergeten. Een opgeslagen Google-pas krijgt zijn punten bijgewerkt via de
Wallet-API; een opgeslagen-maar-nooit-bewaarde pas wordt overgeslagen.

Pushes van Apple komen alleen aan in productie (niet via de sandbox). Nodig: de
sleutels die al voor de passen nodig zijn, en `LOYMEM_PUBLIC_BASE_URL` op het
echte https-adres.

## Boekingsmails doorsturen (systemen zonder open koppeling)

Salonized, Salonkee en Fresha hebben geen openbare koppeling. Ze mailen de zaak
wel bij elke online afspraak. De eigenaar maakt in Instellingen een eigen
ontvangstadres (`<slug>.<geheim>@<LOYMEM_INBOUND_MAIL_DOMAIN>`) en laat Gmail de
meldingen daarheen doorsturen; de bevestigingscode van Gmail verschijnt in het
scherm.

De maildienst (Postmark inbound, Mailgun routes of een eigen omzetter) roept
`POST /api/v1/hooks/mail?key=<LOYMEM_INBOUND_MAIL_KEY>` aan met JSON
(`to`, `from`, `subject`, `html`, `text`), Postmarks JSON of Mailguns
formuliervelden. Alleen mails van het boekingssysteem zelf tellen.

Wat het oplevert: wie al een afspraak heeft krijgt geen herinnering, vrijgekomen
tijden staan klaar om aan te bieden, en (als de zaak dat aanzet) een afgelopen,
niet geannuleerde afspraak telt als bezoek. Afspraken die de zaak zelf in de
agenda zet, mailt het systeem niet; die blijven via de scan aan de balie lopen.

Lezers per systeem staan in `backend/app/integrations/`; nu alleen Salonized
(Nederlandse mails, opbouw gecontroleerd op echte mails van november 2026).
