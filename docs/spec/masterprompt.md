# Masterprompt — Loymem v11 (B2B loyalty en memberships, voor elk boekingssysteem)

Bouw Loymem: de klantbehoudlaag voor barbers en beautyzaken die met hun eigen agenda willen blijven werken.

Drie documenten zijn de functionele basis. Zet ze in de repository onder `docs/spec/`. Bij verschil geldt deze volgorde:

1. **"Loyaliteits- en membershipplatform — Volledig productdocument en bouwrichting"** (22 november 2026), `volledig-productdocument.pdf`. Het geconsolideerde document van Iwan en Dafna; dit wint.
2. **"Aanvulling productconcept: vrije plekken, meldingen en slimme acties"** (22 november 2026), `aanvulling-vrije-plekken.pdf`.
3. **"Loyalty and Membership Platform MVP Specification"** (22 november 2026), `mvp-spec.pdf`. Voor het datamodel, de statussen en de acceptatiecriteria waar de andere twee niets over zeggen.

Deze prompt gaat boven alle drie: hij beslist waar ze verschillen, scherpt regels aan die ze open laten, en legt vast wat er eerst gebouwd wordt. Waar hieronder "productdocument" staat, is document 1 bedoeld; "specificatie" is document 3.

Het is een B2B-product. Startdoelgroep: barbershops, kapsalons, schoonheids-, nagel-, brow- en lashstudio's; later andere afspraakbedrijven. Het werkt naast elk boekingssysteem en hangt van geen enkel systeem af; geen provider krijgt een voorkeursbehandeling in het datamodel of de flow. Barber Iwan (Almere) is de eerste pilotklant.

Lever werkende code, geen plan of mock-up. De enige uitzondering is de klikdemo in fase 0 (§3), die als demo herkenbaar is en niet in de productcode belandt. Neem uitvoeringsbeslissingen zelf en leg ze vast in `docs/decisions.md`. Stop alleen voor de punten onder "Beslissingen voor Iwan en Dafna" en werk intussen door met de standaardkeuze.

## 1. Positionering

Een digitale stempelkaart is eenvoudig te kopiëren, en Piggy, TAPPI, TapTime en Klantkaart.nl bieden al veel losse functies (productdocument §12). Loymem onderscheidt zich op de combinatie. De eerste vijf punten zijn de onderscheidingshypothese uit het productdocument; die worden in de pilot getoetst en nergens als bewezen of exclusief gepresenteerd. Drie punten komen erbij.

1. **Van afspraak naar terugkeer.** De zaak stelt per dienst een terugkeerperiode in (knipbeurt: 4 weken); dat werkt vanaf dag één, zonder historie. Heeft een klant minstens drie geregistreerde bezoeken, dan toont Loymem daarnaast zijn eigen ritme ("komt meestal na 3 weken") als suggestie, en de ondernemer kiest of dat ritme leidend wordt. Het systeem verzint nooit een vaste standaard per branche.
2. **Vrije plekken van vandaag vullen.** Zie §7.
3. **Membershipbeheer voor diensten.** Credits, bezoeken, gebruiksregels, pauzeren, verlengen en duidelijke voorwaarden, die worden opgesteld uit de ingestelde regels en de Nederlandse regels voor verlengen en opzeggen volgen (§8). Het overzicht toont de terugkerende maandomzet, opzeggingen en mislukte betalingen.
4. **Agenda-onafhankelijk.** De ondernemer houdt zijn boekingssoftware (§6).
5. **Retentie-inbox als startscherm.** Zie §4.
6. **Eerlijk bewijs van effect.** Elke campagne houdt standaard een willekeurige controlegroep achter (instelbaar, standaard 10%). Vrije-plekacties niet: daar telt of de plek gevuld is, en een controlegroep zou alleen de kans verkleinen dat dat lukt. Het rapport toont het verschil met de onzekerheid erbij, en zegt "niet aantoonbaar" als het verschil dat niet draagt. Bij één zaak met een paar honderd klanten zal dat vaak zo zijn; het rapport telt daarom ook over meerdere campagnes van hetzelfde soort op, en zegt hoeveel klanten er nog nodig zijn voor een uitspraak. Zo voldoet het aan de rapportageregel van het productdocument (§10) zonder dat de ondernemer zelf een vergelijking hoeft op te zetten.
7. **Binnen tien minuten live.** Een startpakket per type zaak met de startklare ideeën uit productdocument §8 (barber, kapsalon, beauty/nagels) die in fase 1 te bouwen zijn; "vriend meenemen" wacht op het referralprogramma uit fase 2, een voorbeeldmembership en een QR-poster om te printen. Klanten importeren uit de export van elk boekingssysteem via de CSV-mapping.
8. **Eerlijke prijs en vrije uitgang.** Onbeperkt klanten, programma's en campagnes in elk pakket, zoals het productdocument (§13) zegt; pakketten verschillen in automatisering, locaties, koppelingen en support. Berichtkosten (sms) staan zichtbaar en apart. Een bedrijf dat vertrekt, krijgt zijn volledige klantenbestand en historie mee.

Bewust niet: beloningen in ruil voor reviews. Google verbiedt het belonen van reviews; een reviewverzoek na een bezoek mag later wel, maar zonder enige koppeling aan stempels of beloningen.

## 2. Kader

- **Los van Solven.** Eigen repository, database, geheimen, hosting en merk. Een patroon overnemen mag; code, accounts of tabellen delen niet.
- **Er is nog geen codebase.** Kies de stack in `docs/decisions.md`: saai en bekend. Iwan werkt al met FastAPI, PostgreSQL en Next.js; wijk daar alleen van af met een reden.
- **Taal:** interface in het Nederlands via een vertaalbestand, zodat Engels later kan. Code en documentatie mogen Engels zijn.
- **Nieuw gedrag achter een vlag**, standaard uit, met een noodrem per onderdeel.
- **CI op de eigen runner van Solven** (besloten 22-11-2026). Zware controles (backend, e2e) draaien op de eigen Contabo-runner, niet op GitHub-hosted runners; kleine jobs mogen op GitHub. Een runner op een persoonlijk GitHub-account is per repository geregistreerd: zet daarom op dezelfde server een tweede runnerdienst neer, geregistreerd voor `loymem`, met een eigen label (`loymem-ci`) en hoogstens één gelijktijdige job, zodat de wachtrij van Solven niet vastloopt. Lukt registreren of installeren niet vanuit de sessie, meld dan precies welke stap Iwan moet doen. Tot de runner er is: alleen de kleine controles op GitHub, de zware lokaal in de sessie.
- **Geheimen** alleen via omgevingsvariabelen. Verzin geen sleutels, rechten of geslaagde koppelingen.

### Modelkeuze

Het beste model alleen waar het verschil maakt; waar het alleen in prijs verschilt, het goedkopere. Dat geldt voor het bouwen en voor AI in het product.

**Bij het bouwen** (wie het werk doet, ook subagents):

| Werk | Model | Waarom |
|---|---|---|
| Het ontwerpsysteem, de klantkaart, de scanflow, het startscherm en elke ontwerpbeoordeling (§2b) | Opus (beste) | Of het er luxe en vanzelfsprekend uitziet, is een eis van de eigenaar, en daar maakt het model het grootste verschil |
| Architectuur, datamodel, transactielogboek, idempotentie, tenantisolatie, rollen, betalingen, privacy, beveiligingsnalezing | Opus (beste) | Een fout hier is duur en niet in één stap terug te draaien |
| Gewone schermen, endpoints volgens een vastgelegd patroon, toetsen schrijven naar een bestaand voorbeeld, migraties zonder datamutatie, documentatie | Sonnet | Even goed bij een duidelijk patroon, veel goedkoper |
| Mechanisch werk: zoeken in de code, opmaak, vertaalbestanden aanvullen, lint- en typefouten met een duidelijke melding | Haiku | Geen oordeel nodig |

Twijfel je, begin dan met het goedkopere model en schaal op als de uitkomst een tweede poging nodig heeft. Leg per fase in `docs/decisions.md` vast welk model wat deed.

**In het product:** geen AI (§2b). Alles is regels en tellen. Besluiten Iwan en Dafna later anders, dan het kleinste model dat een vastgelegde evaluatie haalt, met een maandbudget per bedrijf en een harde stop, en zonder dat de gebruiker het als AI herkent.

## 2b. Ontwerp: luxe en moeiteloos

Een van de belangrijkste eisen. Loymem moet eruitzien alsof de beste productontwerper ter wereld het heeft gemaakt, en zo makkelijk zijn dat een ondernemer en zijn medewerkers het zonder uitleg gebruiken. Een scherm dat werkt maar er gewoon uitziet, is niet af.

**Ontwerpsysteem eerst.** Vóór het eerste scherm komt `DESIGN.md` met de ontwerptokens (kleur, typografie, ruimte, hoeken, schaduw, beweging) en de basiscomponenten. Elk scherm gebruikt alleen die tokens; een losse kleur of maat in een component is een fout. Eén beeldtaal voor alles wat Loymem zelf toont.

**Twee registers.**
- **De klantkaart is het pronkstuk.** Hij voelt als een premium pas: het merk van de zaak voorop (logo, eigen kleur), rustige diepte, mooie typografie, en een kleine, bevredigende animatie wanneer er een stempel bijkomt of een beloning klaarstaat. Elke zaak kan zijn kaart in een paar tikken op zijn eigen huisstijl zetten, en het ontwerpsysteem zorgt dat elke combinatie mooi blijft (contrast en leesbaarheid worden automatisch bewaakt).
- **Het werk van ondernemer en medewerker is rustig en snel.** Veel witruimte, één accentkleur, duidelijke hiërarchie, geen ruis. Luxe zit hier in precisie en rust, niet in versiering. De scanweergave werkt met één hand, ook in een donkere zaak.

**Richting.** Warm-neutrale basis, één sterke accentkleur, een moderne schreefloze letter voor de interface met eventueel één verfijnde schreefletter voor grote koppen op de kaart en de marketing. Referentieniveau: de rust van Linear, de precisie van Stripe, het gevoel van een Apple Wallet-pas. Niet kopiëren; dit is het lat-niveau.

**Bewust niet:** generieke kleurverlopen, glaseffecten, stockillustraties, emoji als iconen, schaduwen op alles, drukke dashboards met tien grafieken, en alles wat eruitziet als een standaard sjabloon.

**Geen enkel AI-kenmerk.** Niets aan Loymem mag verraden dat AI eraan meewerkte; het moet aanvoelen als het werk van een klein, eigenwijs ontwerpteam.
- *Beeld:* geen paarse of blauw-paarse verlopen, geen gloed of "aurora"-achtergronden, geen glinster- of sterretjesiconen, geen generieke 3D-blobs, geen AI-gegenereerde illustraties of foto's, geen standaard-iconenset zonder aanpassing, geen gelijkvormige kaartjesrasters met een icoon in een rondje. Echte foto's alleen van de zaak zelf; verder typografie, ruimte en de merkkleur.
- *Tekst:* geen AI-toon. Geen "ontgrendel", "naadloos", "moeiteloos", "tilt naar een hoger niveau", "in de snel veranderende wereld", geen drieslag-opsommingen, geen uitroeptekens, geen emoji, geen gedachtestreepjes als stijlmiddel. Korte zinnen in gewone spreektaal, zoals een barber het zelf zou zeggen. Elke tekst wordt hardop gelezen voordat hij erin gaat.
- *Product:* geen "AI"-labels, geen assistent-knoppen of chatballonnen. De AI-suggesties uit fase 3 van het productdocument vervallen tot Iwan en Dafna anders besluiten (§13).
- *Repository:* geen verwijzingen naar AI-hulpmiddelen in commits, pull requests, codecommentaar of documentatie van Loymem; ook geen standaardregels als "Co-Authored-By" of "Generated with". Commits en pull requests staan op naam van het team.
- De ontwerpbeoordeling per fase heeft een vaste vraag: "Zou iemand die veel AI-gemaakte sites ziet, hier iets van herkennen?" Is het antwoord ja, dan is het scherm niet af.

**Moeiteloos, toetsbaar:**
- Een nieuwe zaak zet zijn eerste kaart live zonder hulp, binnen tien minuten (onderscheid 7).
- Elke kerntaak (stempelen, inwisselen, een vrije plek aanbieden, een kans in de inbox afhandelen) kost hoogstens drie tikken.
- Geen vakjargon; elke lege staat laat een voorbeeld zien en de eerste stap.
- Werkt op 375 pixels breed net zo goed als op een groot scherm, met grote raakvlakken.
- WCAG 2.2 AA; beweging respecteert "verminder beweging".
- De klantkaart laadt snel op een mobiel netwerk; een kaart die hapert, voelt niet luxe.

**Hoe dat bewaakt wordt.**
- Elke fase eindigt met een ontwerpbeoordeling op schermafbeeldingen (mobiel en desktop) door een aparte beoordelaar die het werk niet zelf maakte, tegen deze paragraaf en `DESIGN.md`. Wat niet het niveau haalt, wordt verbeterd vóór de fase klaar is.
- Gebruik de ontwerpskills die in de sessie beschikbaar zijn voor kritiek en afwerking.
- In de demogesprekken (fase 0) wordt ook gemeten of ondernemers de kaart zonder hulp kunnen inrichten, en wat ze van de uitstraling vinden.
- Het logo en de huisstijl van Loymem zelf komen van een ontwerper of uit een aparte ontwerpronde (beslissing 1); tot dan een rustig woordmerk, geen zelfgemaakt beeldmerk.

## 3. Fasering

Het productdocument (§14) en de specificatie (§12) hebben elk een fasering. Deze geldt; elke stap is een werkende verticale flow met toetsen.

**Fase 0 — validatie, naast het bouwen.** Niets in fase 0 houdt fase 1a tegen: de bouw van fase 1a begint meteen, en fase 0 loopt ernaast.
- **Klikdemo** van drie onderdelen, zoals het productdocument aanbeveelt: de QR-klantenkaart, de Retentie-inbox en "Vul mijn vrije plekken vandaag". Op voorbeelddata, als één losse pagina of prototype, duidelijk gemarkeerd als demo. Iwan en Dafna leggen hem voor aan minstens vijf ondernemers. Leg per gesprek vast wat ze het meest willen, wat ze nu gebruiken (agenda, kassa, spaarsysteem) en of ze ervoor zouden betalen, in `docs/validatie/`. De uitkomst kan de volgorde van fase 1b tot en met 1g veranderen, maar houdt de bouw niet op; leg een wijziging vast in `docs/decisions.md`. Hergebruik voor de demo zoveel mogelijk de echte schermen uit fase 1a zodra die er zijn, in plaats van een apart prototype bij te houden.
- Stel vast welke boekingssystemen de doelgroep in Nederland het meest gebruikt, en leg per systeem in `docs/integrations.md` vast wat officieel beschikbaar is en wat werkelijk is geverifieerd, met bron en datum (§6). Begin met de systemen van de pilotbedrijven.
- Stel vast wat Apple Wallet en Google Wallet vragen (accounts, certificaten, goedkeuring, kosten, updates van passen). Bouw nog geen Wallet-knop.
- Leg vast welke snelle meldkanalen er zijn (sms, WhatsApp, een melding via de Wallet-kaart), met kosten en de regels van Apple en Google.
- Kies de betaalprovider (zie §9 en §13) en leg de vergelijking vast.
- Bouw een generieke nulmeting uit een export van het boekingssysteem van een pilotbedrijf (CSV met klant-ID en afspraakdatum): aantal klanten, herhaalbezoek binnen 6 en 12 weken, gemiddelde tijd tussen bezoeken. Bewaar alleen de cijfers, niet de export.

**Fase 1a — ontwerpsysteem, kaart en scan, end-to-end, met het startpakket (onderscheid 7):** eerst `DESIGN.md` en de basiscomponenten (§2b), dan
inschrijven via QR → webkaart → stempel door een medewerker → beloning één keer inwisselen → overzicht voor de eigenaar. Met rollen, transactielogboek, auditlog, boekingslink, CSV-import en -export, en terugkeerperiodes per dienst. Dit draait bij Barber Iwan voordat er iets bij komt.

**Fase 1b — Retentie-inbox, eerste versie (onderscheid 5, §4)**, met de kansen die zonder koppeling al te berekenen zijn.

**Fase 1c — vrije plekken, handmatige route (onderscheid 2, §7)**: meldlijst met klantvoorkeuren, plekken handmatig vrijgeven, gefaseerd versturen, claimen, sluiten.

**Fase 1d — bezoekbundels en memberships met betalingen (onderscheid 3)**, pas na de juridische check en de btw-vraag (§8). Tot die er zijn, kan de bouw doorgaan, maar gaat er niets te koop.

**Fase 1e — campagnes**, eerst via de kaart en e-mail, met de terugkeerperiode als eerste trigger en de controlegroep vanaf de eerste campagne (onderscheid 6).

**Fase 1f — Wallet-passen**, zodra fase 0 ze heeft gevalideerd en de accounts er zijn. De webkaart blijft altijd werken.

**Fase 1g — de eerste geverifieerde koppeling**, gekozen uit de matrix en de agenda's van de pilotbedrijven.

**Pilot:** vijf bedrijven, waarvan minstens één beautyzaak, met minstens twee verschillende agenda's of agenda-werkwijzen (productdocument §15). De pilot is geslaagd als minstens drie bedrijven na de proefperiode tegen de aangeboden prijs willen doorgaan en de administratie van afspraken en beloningen zonder dubbele toekenning werkt. Waarderen ondernemers vooral de stempelkaart, dan versimpelen we; waarderen ze vrije plekken, memberships en terugkeeracties, dan investeren we daar verder in.

**Fase 2 en 3** zoals het productdocument, plus wat een B2B-product nodig heeft: zelfstandig aanmelden en inrichten door een bedrijf, abonnementen en facturen voor bedrijven via de betaalprovider, proefperiode, opzeggen en export bij vertrek.

## 4. De Retentie-inbox

Het startscherm van de ondernemer, zoals productdocument §5. Aanscherpingen:

- **Eerste versie zonder koppeling:** klant toe aan bezoek (terugkeerperiode verstreken, geen recente scan), beloning verdiend maar niet gebruikt, membershiptegoed ongebruikt of verlenging nadert, vrije plek die de ondernemer net heeft vrijgegeven, actie die afloopt. "Geen nieuwe afspraak" is zonder koppeling niet te weten; de kaart zegt dan eerlijk "geen bezoek geregistreerd sinds …" en niet "heeft geen afspraak".
- **Elke kans zegt waarom**, welke actie past en welke boekingslink wordt gebruikt. Goedkeuren, aanpassen of negeren in één tik. Negeren verbergt de kans voor een instelbare periode en wordt onthouden.
- **Geen scores of sterren** die betrouwbaarheid suggereren die er niet is; alleen de feiten die de kans veroorzaken.
- **Rustig:** standaard hoogstens tien kansen per dag, de belangrijkste eerst, zodat de inbox niet verandert in een lijst die niemand afwerkt.

## 5. Aanscherpingen op de documenten

Waar de specificatie iets opent of in het midden laat, geldt dit.

**Transactielogboek is de waarheid.** `LedgerEvent` is alleen toevoegen. `CustomerProgram.balance` is een afgeleide die altijd uit het logboek te herberekenen is; een nachtelijke controle meldt elk verschil. Een correctie is een tegenboeking met reden, alleen door eigenaar of manager, nooit een gewijzigde of verwijderde regel.

**Idempotentie in de database.** `idempotency_key` heeft een unieke constraint. Dubbele scans, herhaalde verzoeken en dubbele webhooks leveren één regel op, ook bij gelijktijdige verzoeken.

**Wie wat kan toekennen.**
- De QR-code van de klant identificeert de klant; hij kent nooit zelf iets toe. Een stempel komt alleen uit een ingelogde medewerkerssessie.
- De beloningscode op de klantkaart is kortlevend en eenmalig (bijvoorbeeld elke minuut vernieuwd), zodat een schermafbeelding niets oplevert.
- Per klant per programma hoogstens één stempel per instelbare periode, standaard per dag.
- Een medewerker kan niet stempelen of inwisselen op een klantprofiel met zijn eigen telefoonnummer of e-mailadres.
- Een overzicht voor de eigenaar toont ongewone patronen, zoals veel stempels door één medewerker in korte tijd, of veel correcties.

**Platformbeheerder.** Toegang tot klantgegevens alleen na een vastgelegde reden, tijdelijk, en zichtbaar in het auditlog van het bedrijf zelf.

**Klanttoegang.** De link naar de webkaart is een geheim met lange willekeurige sleutel; wie hem kwijt is, vraagt een nieuwe aan via een eenmalige link per e-mail of sms. Geen wachtwoord voor klanten. Een opnieuw aangevraagde link maakt de oude ongeldig.

**Eén klant, meerdere zaken.** Iemand die bij twee bedrijven op Loymem spaart, heeft twee profielen, elk van één bedrijf. Geen enkel bedrijf ziet dat de klant ook elders klant is, ook niet via hetzelfde telefoonnummer. Een kaartoverzicht voor de klant over meerdere zaken komt pas als daar toestemming en een besluit voor zijn.

**Gegevens.**
- Verjaardag alleen dag en maand, alleen als de klant hem zelf opgeeft.
- Klanten die via CSV worden geïmporteerd, krijgen geen marketing tot ze zelf toestemming geven. Een import levert nooit een `ConsentRecord` met status "toegestaan" op.
- Verwijderen anonimiseert het klantprofiel; logboekregels blijven bestaan zonder persoonsgegevens, zodat de administratie klopt.

**Campagnes.** Kaartmeldingen en e-mail in de pilot. Sms en WhatsApp blijven uit tot Iwan en Dafna beslissen (§13); de kosten per bericht staan dan zichtbaar in de editor.

## 6. Boekingssystemen: los van elke provider

De specificatie (§6) staat. Aanscherpingen:

- **De medewerkerscan en de boekingslink zijn de basis voor elk bedrijf.** Een bedrijf kan het product volledig gebruiken zonder enige koppeling. Een koppeling maakt het werk lichter, nooit mogelijk.
- **Eén adaptercontract, geen providerlogica in de kern.** Code buiten `integrations/<provider>/` kent geen providernamen. Een nieuwe provider toevoegen raakt alleen zijn eigen map en de capability-matrix. Een statische toets bewaakt dat.
- **De capability-matrix is productinformatie.** Per provider: koppelmethode, autorisatie, kosten, partnervereisten, geverifieerd ja of nee, bron, datum. Het onboardingscherm leest daaruit wat een bedrijf kan kiezen; een provider zonder bewijs verschijnt als "boekingslink en medewerkerscan".
- **Eigen spaarsystemen van boekingssystemen.** Sommige boekingssystemen hebben zelf spaarpunten (Salonized bijvoorbeeld wel). Leg per provider vast of dat zo is. Bij de onboarding wijst het product erop dat dubbel sparen verwarrend is voor klanten, en laat het bedrijf kiezen; het zet nooit iets uit in het boekingssysteem.
- **Generieke webhook vóór native koppelingen.** Een bedrijf of zijn boekingssysteem kan afgeronde afspraken aanleveren via een ondertekende webhook met veldmapping, ook zonder dat wij een native connector hebben. Native connectors komen alleen voor providers met bevestigde officiële toegang, en de eerste wordt gekozen op basis van de matrix en de pilotbedrijven.

## 7. Vrije plekken en meldingen

De aanvulling staat; de handmatige route is de MVP en werkt zonder agenda-koppeling. Aanscherpingen:

- **Claimen in Loymem, boeken in de agenda.** Een klant claimt de aanbieding eerst in Loymem (het voordeel hoort dan bij hem, niet bij de plek) en gaat daarna naar de boekingslink. Bij de scan na de behandeling ziet de medewerker de geclaimde aanbieding en past hij die één keer toe als het bezoek binnen het aangeboden tijdslot valt. Zo is het effect te herleiden, ook zonder koppeling.
- **Gefaseerd versturen is standaard, al in de MVP** (het productdocument zet het in fase 2, maar het hangt niet van een koppeling af). Eerst een kleine groep (standaard 3 klanten per vrije plek), na een instelbare wachttijd de volgende. Zo krijgen niet twintig klanten een aanbieding voor één stoel, en komt de teleurstelling "al vergeven" zelden voor.
- **Wie eerst.** Volgorde: klanten op de meldlijst die "toe aan bezoek" zijn volgens de terugkeerperiode of hun eigen ritme (onderscheid 1), dan members als de ondernemer dat aanzet, dan de rest van de meldlijst. De ondernemer ziet de volgorde en de reden en kan klanten wegklikken.
- **Liever punten of een upgrade dan korting.** Standaardvoordeel is extra stempels of een upgrade. Korting kan, maar met een grens per klant (standaard hoogstens één last-minutekorting per 60 dagen), zodat vaste klanten niet leren wachten op korting. Het rapport toont hoeveel last-minuteboekingen van klanten kwamen die die week toch al aan de beurt waren.
- **Een snel kanaal is nodig.** Een last-minuteplek vraagt een melding binnen minuten. E-mail is te traag als enige kanaal. Het productdocument noemt e-mail en sms als startkanalen; sms kost per bericht. Tot Iwan en Dafna kiezen (§13), gaat de vrije-plekken-functie alleen live met e-mail en een duidelijke vermelding dat dat traag is.
- **Toestemming per doel.** Aanmelden voor de meldlijst is toestemming voor meldingen over plekken op het gekozen kanaal, niet voor andere marketing. Een plek die vrijkomt, is geen reden om iemand zonder die toestemming te benaderen.
- **Sluiten is hard.** Na "bezet", "verlopen" of "gesloten" toont elke geopende aanbieding "niet meer beschikbaar" en is claimen onmogelijk. Een tweede claim op een plek met één beschikbaarheid wordt server-side geweigerd.
- **Tijdzones en twee tijden.** De afspraaktijd en de uiterste boektijd worden allebei getoond en opgeslagen in de tijdzone van de vestiging, zoals de aanvulling zegt.

## 8. Memberships en bundels: wettelijke grenzen

Bovenop specificatie §7, en te laten bevestigen door een jurist vóór er iets te koop gaat:

- Automatisch verlengen alleen als de klant daarna maandelijks kan opzeggen.
- Een membership dat online is afgesloten, is online op te zeggen vanuit de klantkaart, zonder belverzoek of terugwinstap.
- Looptijd, verlenging, opzegtermijn, bedenktijd en de regels voor no-show en pauzeren staan vóór aankoop zichtbaar, met een versienummer van de voorwaarden (`terms_version`) dat bij de aankoop wordt vastgelegd.
- Een bezoekbundel is vooruitbetaald tegoed. Leg vast wat er met ongebruikte bezoeken gebeurt bij opzeggen, bij verloop en bij sluiting van de zaak.
- De btw-behandeling van bundels en memberships laat Iwan door zijn boekhouder bevestigen.
- Een credit kan bij het claimen of boeken tijdelijk worden gereserveerd en wordt pas na het afgeronde bezoek definitief verbruikt; bij annulering komt de reservering vrij volgens de voorwaarden (productdocument §7). Reservering, verbruik en vrijgave zijn elk een regel in het transactielogboek.
- De status volgt uit ondertekende events van de betaalprovider, idempotent verwerkt. Medewerkers kunnen de betaalstatus niet wijzigen (zoals de specificatie zegt).

## 9. Betalingen, privacy en B2B-afspraken

- **Loymem houdt geen geld van klanten vast.** Een membership of bundel wordt betaald aan de zaak zelf. Standaard via Mollie Connect: elk bedrijf koppelt zijn eigen Mollie-account en ontvangt de betalingen rechtstreeks. Loymem start betalingen en verwerkt de status, maar het geld loopt er niet doorheen. Wijk daar niet van af zonder besluit; geld van anderen vasthouden vraagt een vergunning.
- **Het abonnement van het bedrijf zelf** (Start, Groei, Premium) is een aparte stroom, van het bedrijf aan Loymem, en raakt de betalingen van de zaak niet.
- **Rollen in de AVG.** Het bedrijf is verwerkingsverantwoordelijke voor zijn klantgegevens; Loymem is verwerker. Daarvoor zijn nodig vóór het eerste betalende bedrijf: een verwerkersovereenkomst, een lijst van subverwerkers (hosting, e-mail, sms) en een privacyverklaring die het bedrijf aan zijn klanten kan tonen. Concepten in `docs/legal/`, te laten nakijken door een jurist; claim nergens juridische conformiteit.
- **Eigen gebruik van gegevens.** Loymem gebruikt klantgegevens van een bedrijf alleen voor dat bedrijf. Cijfers over meerdere bedrijven heen (bijvoorbeeld voor productbeslissingen) alleen geaggregeerd en zonder persoonsgegevens, en alleen als de verwerkersovereenkomst dat toestaat.

## 10. Rapportage

Zoals de specificatie §5 en §13: waargenomen aantallen apart van geschat effect. Vergelijk met de nulmeting uit fase 0 en met de controlegroep (onderscheid 6), en zeg nergens dat het platform iets heeft "opgeleverd" zonder dat de vergelijking dat draagt.

## 11. Klaar wanneer

De acceptatiecriteria uit specificatie §11, plus deze toetsen:

- `test_enroll_and_use_without_booking_integration`
- `test_core_has_no_provider_names` (statisch: geen providernaam buiten `integrations/`)
- `test_generic_webhook_completion_single_ledger_event`
- `test_duplicate_scan_single_stamp` en `test_concurrent_scan_single_stamp`
- `test_reward_redeemed_once_concurrently`
- `test_screenshot_of_reward_code_is_rejected` (verlopen code)
- `test_calendar_item_is_not_completion` en `test_unknown_status_is_not_completion`
- `test_balance_matches_ledger`
- `test_correction_is_reversal_by_manager_only`
- `test_staff_cannot_stamp_own_profile`
- `test_staff_scope_is_narrow` (geen export, geen contactgegevens buiten de scanflow)
- `test_tenant_isolation`
- `test_import_grants_no_marketing_consent`
- `test_opt_out_keeps_rewards`
- `test_return_period_per_service_drives_opportunity`
- `test_personal_rhythm_only_suggested_after_three_visits`
- `test_inbox_without_integration_never_claims_no_appointment`
- `test_credit_reserved_then_consumed_or_released_once`
- `test_campaign_holdout_never_receives_message`
- `test_report_says_not_demonstrable_without_significant_difference`
- `test_exit_export_contains_all_customers_and_ledger`
- `test_slot_offer_closes_and_rejects_second_claim`
- `test_staged_send_waits_before_next_group`
- `test_claimed_offer_applied_once_only_within_slot`
- `test_waitlist_consent_does_not_allow_other_marketing`
- `test_last_minute_discount_limit_per_customer`
- `test_membership_cancel_online` (fase 1d)
- `test_customer_profiles_never_shared_between_businesses`
- `test_reissued_card_link_invalidates_old_link`
- `test_free_slot_offer_has_no_holdout`
- `test_brand_colour_keeps_contrast_aa` (elke merkkleur die een zaak kiest, houdt leesbare tekst op de kaart)
- `test_no_raw_colour_or_spacing_outside_tokens` (statisch)
- Ontwerpbeoordeling per fase vastgelegd in `docs/design-reviews/`, met schermafbeeldingen
- `test_copy_has_no_banned_phrases` (statisch: de verboden woorden uit §2b, emoji en uitroeptekens in `messages/nl.json` en `en.json`)
- `test_repo_has_no_ai_attribution` (statisch: geen "Co-Authored-By", "Generated with" of namen van AI-hulpmiddelen in de repository)
- Geen koppeling als beschikbaar getoond zonder vastgelegd bewijs in `docs/integrations.md`.

## 12. Buiten de pilot (fase 1)

Zelfstandig aanmelden en abonnementen voor bedrijven (dat is fase 2), een marketingsite, een eigen app, kassakoppelingen, punten, prepaid tegoed, coupons en referrals (specificatie fase 2), en elke koppeling zonder geverifieerde officiële toegang.

## 13. Beslissingen voor Iwan en Dafna

Productdocument §16 plus wat de code-, markt- en juridische check opleverde. Werk door met de standaardkeuze.

| # | Beslissing | Standaard tot er een antwoord is |
|---|---|---|
| 1 | Naam en uitstraling | Loymem (besloten 22-11-2026, in plaats van Loyvara), neutraal genoeg voor barbers én beauty. Slogan voorlopig "vaste klanten, vaste omzet", ondertitel "loyalty en memberships, naast je eigen agenda". Iwan registreert loymem.com en loymem.nl; merkregister nakijken vóór een logo |
| 2 | Starten met Barber Iwan als eerste praktijktest | Ja |
| 3 | De vijf pilotbedrijven en hun agenda's | Barber Iwan plus vier uit de demogesprekken, minstens één beautyzaak en twee agenda's |
| 4 | Membershipregels in de eerste versie | Maandmembership met vast aantal bezoeken, maandelijks opzegbaar, credit pas verbruikt na afgerond bezoek |
| 5 | Meldkanalen en kosten | E-mail; sms na keuze van leverancier en kosten; WhatsApp en Wallet-meldingen later |
| 6 | Betaalprovider en abonnementsmodel | Mollie, na vastgelegde vergelijking |
| 7 | Prijs na de proefperiode | Testprijzen uit productdocument §13: Start €29, Groei €59, Premium €99 per vestiging per maand; geen blijvende korting vóór de betaalbereidheid gemeten is |
| 8 | Hosting | Aparte server, niet die van Solven |
| 9 | Standaardvoordeel bij last-minute | Extra stempels of upgrade; korting hoogstens één keer per 60 dagen per klant |
| 10 | Jurist (opzeggen, tegoed, voorwaarden, privacy) en boekhouder (btw) | Niets te koop vóór beide |
| 11 | Welke boekingssystemen als eerste officiële toegang aanvragen | Die van de pilotbedrijven, na de matrix uit fase 0 |
| 12 | Rechtsvorm en eigendom van Loymem tussen Iwan en Dafna (wie bezit de code, het domein en het merk, en wie factureert) | Vastleggen vóór het eerste betalende bedrijf en vóór de merkregistratie; tot dan registreert Iwan de domeinen op zijn naam |

## 14. Eindrapport

Kort: wat werkt bij de pilotbedrijven · welke koppelingen geverifieerd zijn en welke niet · wat wacht op een account, sleutel, jurist, boekhouder of besluit · één concrete volgende stap.
