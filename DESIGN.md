# Loymem ontwerpsysteem

Eén beeldtaal voor alles wat Loymem toont. Elke kleur, maat, hoek, schaduw en
beweging komt uit `frontend/src/styles/tokens.css`. Een losse waarde in een
component is een fout; `test_no_raw_colour_or_spacing_outside_tokens` vindt hem.

## Houding

- **Twee registers.** De klantkaart is een pas: het merk van de zaak voorop,
  rustige diepte, een grote schreefletter. Het werk van eigenaar en medewerker is
  papier en inkt: wit, één accent, strakke regels, geen versiering.
- **Precisie boven effect.** Uitlijning op een raster van 4, cijfers in
  tabelcijfers, één gewicht verschil tussen kop en tekst. Geen kaders om
  kaders.
- **Stil.** Eén accentkleur per scherm. Rood alleen voor iets dat misging.
  Geen illustraties, geen iconen in rondjes, geen kleurverlopen behalve de ene
  lichtval op de kaart.

## Kleur

| Token | Waarde | Gebruik |
|---|---|---|
| `--paper` | `#F6F4EF` | achtergrond van werkschermen |
| `--surface` | `#FFFFFF` | vlakken op papier |
| `--ink` | `#1B1916` | tekst, primaire knop |
| `--ink-2` | `#5A544C` | tweede tekst |
| `--ink-3` | `#6F685F` | labels, hulptekst (4,9:1 op papier) |
| `--line` | `#E4DFD6` | lijnen, randen |
| `--line-strong` | `#CFC8BC` | rand van invoervelden |
| `--accent` | `#1F4A38` | de ene accentkleur: actief, gelukt, nu |
| `--accent-soft` | `#E6EEE9` | achtergrond bij accent |
| `--danger` | `#9A2B1E` | fout, onomkeerbaar |
| `--danger-soft` | `#F6E7E3` | achtergrond bij fout |
| `--night` | `#12110F` | scanweergave, donkere zaak |

De kaart gebruikt de merkkleur van de zaak. De tekstkleur op de kaart wordt
berekend (`app/services/brand.py`): inkt of ivoor, welke het hoogste contrast
geeft, en altijd minimaal 4,5:1. Een zaak kan dus elke kleur kiezen zonder dat
de kaart onleesbaar wordt.

## Letter

- Interface: **Schibsted Grotesk** (variabel). Strak, iets eigenwijs, goed
  leesbaar klein.
- Kaart en grote koppen: **Newsreader** (display-optiek). Alleen voor de naam
  van de zaak, de beloning en de koppen van marketing.
- Cijfers altijd `font-variant-numeric: tabular-nums`.

| Token | Maat / regel | Gebruik |
|---|---|---|
| `--text-xs` | 12 / 16 | metadata, nooit zinnen |
| `--text-sm` | 14 / 20 | labels, hulptekst |
| `--text-md` | 16 / 24 | lopende tekst, invoer |
| `--text-lg` | 20 / 28 | kop van een vlak |
| `--text-xl` | 28 / 34 | kop van een scherm |
| `--text-display` | 44 / 46 | kaart, groot cijfer |

Gewichten: 420 tekst, 560 nadruk. Spatiëring op koppen −0,01 em, op kleine
hoofdletterlabels +0,06 em.

## Ruimte

Raster van 4: `--space-1` 4 · `--space-2` 8 · `--space-3` 12 · `--space-4` 16 ·
`--space-5` 24 · `--space-6` 32 · `--space-7` 48 · `--space-8` 64. Raakvlakken
minimaal `--hit` 48 px. Leesbreedte `--measure` 34 rem; werkschermen tot
`--page` 60 rem.

## Hoeken en lijnen

`--radius-sm` 6 (velden, knoppen) · `--radius-md` 10 (vlakken) · `--radius-pass`
20 (de kaart). Lijnen `--hairline` 1 px in `--line`. Geen schaduw op vlakken; een
vlak scheidt zich door papier en lijn.

## Diepte

Alleen de kaart heeft diepte: `--shadow-pass`, twee lagen, laag en zacht, en
één lichtval van boven (`--pass-sheen`). Niets anders zweeft.

## Beweging

| Token | Waarde | Gebruik |
|---|---|---|
| `--ease-out` | `cubic-bezier(.2,.7,.2,1)` | alles wat verschijnt |
| `--dur-quick` | 120 ms | knop, focus |
| `--dur-base` | 200 ms | vlak, melding |
| `--dur-stamp` | 520 ms | een stempel valt op de kaart |

Stempelen, lijsten, tabwissels: geen animatie behalve de terugmelding. De kaart
krijgt één beweging: de nieuwe stempel zakt in zijn vak en het vak kleurt. Bij
`prefers-reduced-motion` alleen de kleur.

## Componenten

`Button` (primair inkt, tweede lijn, gevaar), `Field` (label boven, hulp onder,
fout onder in `--danger`), `Panel`, `Stat` (label, cijfer, één regel uitleg),
`Pass` (de kaart), `StampRow`, `Notice`, `EmptyState` (één zin, een voorbeeld,
de eerste stap), `Wordmark` (rustig woordmerk, geen beeldmerk tot beslissing 1).

## Tekst

Korte zinnen, gewone spreektaal, je-vorm. Geen uitroeptekens, geen emoji, geen
gedachtestreepjes, geen opsommingen van drie als stijl. Verboden woorden staan
in `backend/tests/static/test_copy.py`. Elke tekst gaat via `messages/nl.json` en
`messages/en.json`.
