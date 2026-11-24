# Voorwaarden: de vaste zinnen

*Een zaak kiest per onderwerp één zin; zelf schrijven kan niet. De zin die de
klant accepteert, wordt bij het opslaan op het plan vastgelegd. Deze lijst gaat
één keer naar de jurist (vraag 11 in `vragen-voor-de-jurist.md`). Een toets
houdt deze lijst gelijk aan `backend/app/services/policies.py`.*

## Ongebruikte bezoeken in een abonnement (de zaak kiest)

- **Vervallen per maand** (`expire_period`): Bezoeken die je in een maand niet gebruikt, vervallen aan het eind van die maand.
- **Eén maand doorschuiven** (`roll_one_period`): Bezoeken die je in een maand niet gebruikt, schuiven één maand door. Wat je ook die maand niet gebruikt, vervalt. Je oudste bezoeken gebruik je eerst.

## Ongebruikte bezoeken in een bundel (vast)

- Bezoeken die je niet gebruikt binnen de geldigheid, vervallen op de laatste dag. Je ziet op je kaart tot wanneer ze geldig zijn.

## Niet besteed tegoed (vast)

- Tegoed dat je niet besteedt binnen de geldigheid, vervalt op de laatste dag. Je ziet op je kaart hoeveel je nog hebt en tot wanneer.

## Niet komen of laat afmelden (de zaak kiest)

- **Kost niets** (`free`): Kom je niet, dan kost dat geen bezoek. Laat het ons wel even weten.
- **Alleen niet komen zonder afmelden** (`no_show_counts`): Kom je niet en heb je niet afgemeld, dan telt dat als een gebruikt bezoek. Afmelden kan tot het begin van je afspraak.
- **Tot 24 uur vooraf** (`late_24h`): Afmelden kan kosteloos tot 24 uur voor je afspraak. Meld je later af of kom je niet, dan telt dat als een gebruikt bezoek.
- **Tot 24 uur vooraf, eerste keer per jaar vrij** (`late_24h_first_free`): Afmelden kan kosteloos tot 24 uur voor je afspraak. Meld je later af of kom je niet, dan telt dat als een gebruikt bezoek. De eerste keer per jaar niet.

## Pauzeren (vast, tot het platform zelf kan pauzeren)

- Pauzeren kan niet. Opzeggen kan altijd, per het eind van de betaalde maand.

## Geld terug (vast, voor elk plan)

- Binnen 14 dagen na aankoop kun je zonder reden afzien van je aankoop; je krijgt je geld terug, min wat je al hebt gebruikt, naar verhouding. Stopt de zaak, dan krijg je terug wat je nog niet hebt gebruikt. Terugbetalen gaat via dezelfde manier waarop je betaalde.
