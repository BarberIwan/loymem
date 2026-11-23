# Verwerkersovereenkomst (concept)

**Partijen**
1. De zaak die het platform gebruikt ("Verwerkingsverantwoordelijke").
2. De aanbieder van het platform, [naam, rechtsvorm, KvK, adres] ("Verwerker").

## 1. Onderwerp
Verwerker verwerkt persoonsgegevens van klanten van Verwerkingsverantwoordelijke
uitsluitend om het platform te leveren: digitale klantkaart, stempels en
beloningen, meldlijst en vrije plekken, berichten, abonnementen en bundels,
rapportage voor de zaak.

## 2. Gegevens en betrokkenen
- **Betrokkenen:** klanten van de zaak; medewerkers van de zaak met een account.
- **Gegevens klanten:** voornaam, telefoonnummer en/of e-mailadres, optioneel
  verjaardag (dag en maand, geen jaar), bezoeken en stempels, beloningen,
  toestemmingen per doel met datum en bron, voorkeuren voor de meldlijst,
  abonnementen en tegoed. Geen bijzondere persoonsgegevens.
- **Gegevens medewerkers:** naam, e-mailadres, rol, versleuteld wachtwoord,
  wie welke stempel of correctie deed.
- **Betalingen:** verlopen via het eigen betaalaccount van de zaak bij de
  betaaldienst. Verwerker ontvangt geen betaalkaart- of rekeninggegevens, alleen
  status, bedrag en kenmerken van de betaling.

## 3. Instructies
Verwerker verwerkt alleen op schriftelijke instructie van Verwerkingsverantwoordelijke;
het gebruik van het platform zoals ingesteld door de zaak geldt als instructie.
Verwerker gebruikt de gegevens niet voor eigen doeleinden. Cijfers over meerdere
zaken heen gebruikt Verwerker alleen geaggregeerd, zonder persoonsgegevens en
zonder dat een zaak of klant herleidbaar is. [Jurist: toetsen of dit zo mag of
apart moet worden toegestaan.]

## 4. Scheiding tussen zaken
Elke zaak heeft eigen klantprofielen. Een klant van twee zaken heeft twee losse
profielen; gegevens worden niet tussen zaken gedeeld. Technisch afgedwongen in
de applicatie en in de database (rij-beveiliging per zaak).

## 5. Beveiliging
- Versleutelde verbindingen (TLS); geheimen en koppeltokens versleuteld opgeslagen.
- Toegang voor medewerkers per rol; de medewerkerrol ziet geen contactgegevens.
- Kaartlinks en scancodes alleen als hash opgeslagen.
- Logboek van stempels en correcties dat niet te wijzigen is; auditlog van
  beheerhandelingen.
- Back-ups versleuteld, [frequentie en bewaartermijn invullen].

## 6. Subverwerkers
Verwerker schakelt alleen de subverwerkers uit `subverwerkers.md` in. Een nieuwe
subverwerker meldt Verwerker minstens 30 dagen vooraf; Verwerkingsverantwoordelijke
kan bezwaar maken en in dat geval de overeenkomst opzeggen.

## 7. Rechten van betrokkenen
Verwerker helpt bij inzage, correctie, verwijdering en overdraagbaarheid. In het
platform kan de zaak zelf: alle gegevens downloaden, een klant anonimiseren, en
klanten kunnen zelf berichten en meldingen uitzetten.

## 8. Datalekken
Verwerker meldt een (vermoedelijk) datalek zonder onredelijke vertraging en
uiterlijk binnen 24 uur na ontdekking, met de informatie die de zaak nodig heeft
voor een melding aan de Autoriteit Persoonsgegevens.

## 9. Bewaren en einde
Na beëindiging kan de zaak 30 dagen lang alle gegevens downloaden. Daarna
verwijdert Verwerker de gegevens, behalve wat wettelijk bewaard moet worden.
[Jurist: termijn en uitzonderingen bevestigen.]

## 10. Audit
Verwerker geeft op verzoek de informatie die nodig is om naleving aan te tonen.

## 11. Aansprakelijkheid
[Afstemmen met de algemene voorwaarden van het platform.]
