# CI

De backendpoort draait op een eigen runner, label `loymem-ci`, als tweede
runnerdienst op dezelfde CI-server als Solven, met hoogstens één job tegelijk.
Zo verdringt Loymem de runners van Solven niet en kost het geen GitHub-minuten.

Zolang die runner er niet is, blijft de backendjob wachten. Hij wordt niet stil
naar GitHub verplaatst: dat kost geld en vraagt eerst toestemming.

De frontendjob is klein (een paar minuten) en draait op GitHub.

Lokaal: zie `README.md`.

## Runner aanzetten

1. GitHub, repository `loymem`: **Settings → Actions → Runners → New self-hosted
   runner**, Linux. Kopieer alleen het token uit de regel `./config.sh --url …
   --token XXXX` (een uur geldig).
2. Op de CI-server, als root, met `docs/ci/runner-installeren.sh`:

   ```bash
   RUNNER_TOKEN=XXXX bash runner-installeren.sh
   ```

   Het script zet de runner in `/opt/actions-runner-loymem` met het label
   `loymem-ci`. Docker, de gebruiker `runner` en de nachtelijke opruimronde
   deelt hij met Solven; die worden niet dubbel aangemaakt.
3. Op GitHub staat de runner daarna **Idle**, en de wachtende backendjob start.

De server heeft dan drie plekken (twee Solven, één Loymem). Draaien ze alle drie
tegelijk, dan worden ze trager. Loymem-toetsen duren een paar minuten, dus dat
valt mee; terug naar twee kan met `cd /opt/actions-runner-loymem && ./svc.sh stop
&& ./svc.sh uninstall`.
