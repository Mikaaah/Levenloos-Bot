# LEVENLOOS bot — revisie 2026-09-09

Deze revisie is gemaakt op basis van de daadwerkelijk geüploade VPS-code.

## Belangrijkste UX-wijzigingen

- `/xp` is weer een snelle member-command naast `/level`.
- `/help` is opgeschoond: makkelijke/panel-commands staan vooraan; legacy/power shortcuts vervuilen het hoofdhelp-menu niet meer.
- `/bot commands` blijft verwijderd omdat `/help` dezelfde functie beter en permission-aware uitvoert.
- Suggesties hebben nu `/suggestie menu` met knoppen + modals voor Algemeen, Bot, Event en Gradient.
- Suggestie-gradients gebruiken een radio-keuze voor levels 10/25/50/75/100/125/150/175/200.
- `/suggestie beheer` gebruikt een dropdown met recente suggesties en actieknoppen; ID + actie overtypen is niet meer nodig.
- `/suggestie setup` gebruikt een channel dropdown in plaats van een lange slash-parameterflow.
- Temp Voice heeft `/voice config` als centraal configuratiepanel.
- Temp Voice naamformat ondersteunt `{name}`, `{username}`, `{id}` en `{count}`.
- Temp Voice configuratie: lobby, categorie, naamformat, standaard user limit, bitrate, standaard privacy, auto-delete en delete-delay.
- Temp Voice beheer: rename, limit, lock/unlock, owner transfer, claim en delete-confirmatie.
- Health Panel heeft duidelijke uitleg + configureerbare refresh interval + optionele loopdetails.
- Reminders gebruiken radio-presets voor tijd en een dropdown om open reminders te annuleren.

## Betrouwbaarheid / onderhoud

- De dubbele `interaction.response.defer()` in suggestiebeheer is verwijderd.
- Suggesties worden via het ingestelde suggestiekanaal geplaatst; de menu-flow hoeft niet meer per se vanuit dat kanaal geopend te worden.
- `bot.py` start alleen nog wanneer het bestand direct wordt uitgevoerd (`if __name__ == "__main__"`). Hierdoor kunnen modules offline geïmporteerd en gecontroleerd worden.
- Token-validatie gebeurt pas bij daadwerkelijke start, niet bij import.
- Temp Voice database heeft backwards-compatible migrations voor nieuwe configvelden.
- Admin Panel Temp Voice-status is aangepast aan het nieuwe configmodel.
- Alle bekende databases blijven onderdeel van Health/Admin backup-controles.
- `.gitignore` dekt nu ook SQLite WAL/SHM en backups.
- Lege ongebruikte `roles.py` is uit de distributie gehaald; deze werd niet geladen.

## Controle uitgevoerd

- Alle Python-bestanden: `compileall` / syntax OK.
- Alle cogs konden offline in discord.py 2.7.1 geladen en als commands geregistreerd worden zonder command-conflicten.
- Geregistreerde root commands bevatten o.a. `/help`, `/level`, `/xp`, `/top`, `/voice`, `/suggestie`, `/health`, `/reminder` en `/adminpanel`.
- Moderne discord.py 2.7.1 modalcomponenten (`RadioGroup`, `CheckboxGroup`, `Label`, channel/user selects) zijn tegen de meegeleverde 2.7.1-installatie geïmporteerd/geïnstantieerd.

Een echte Discord API-integratietest kan pas op de VPS met de bot ingelogd worden uitgevoerd. Start daarom na deployment met live journal logs.
