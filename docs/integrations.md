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
