# CI

De backendpoort draait op een eigen runner, label `loymem-ci`, als tweede
runnerdienst op dezelfde CI-server als Solven, met hoogstens één job tegelijk.
Zo verdringt Loymem de runners van Solven niet en kost het geen GitHub-minuten.

Zolang die runner er niet is, blijft de backendjob wachten. Hij wordt niet stil
naar GitHub verplaatst: dat kost geld en vraagt eerst toestemming.

De frontendjob is klein (een paar minuten) en draait op GitHub.

Lokaal: zie `README.md`.
