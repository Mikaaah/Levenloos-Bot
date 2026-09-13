# Deploy

Deze ZIP bevat bewust GEEN `.env`, databases, venv of backups. Laat die op de VPS staan.

## Aanbevolen deployment

Maak eerst een backup van de huidige code/database en vervang daarna alleen de codebestanden.

```bash
cd /root
cp -a levenloos-bot levenloos-bot-pre-overhaul
```

Pak de nieuwe ZIP tijdelijk uit en kopieer de code over de bestaande map zodat `.env`, databases en `venv` blijven bestaan.

```bash
cd /root
rm -rf levenloosbot-update
mkdir levenloosbot-update
unzip -o levenloosbot_overhaul.zip -d levenloosbot-update
cp -a levenloosbot-update/levenloos-bot/. /root/levenloos-bot/
```

Dependencies:

```bash
cd /root/levenloos-bot
./venv/bin/python -m pip install -r requirements.txt
```

Daarna:

```bash
sudo systemctl restart levenloos-bot
sudo journalctl -u levenloos-bot -f
```

Na command-wijzigingen moet Discord één keer gesynchroniseerd worden. Gebruik daarvoor de command-sync functie uit het Admin Panel als `SYNC_COMMANDS_ON_STARTUP=false` staat.

## Eerste checks

1. `/help` — controleer `/xp`, `/voice config`, `/suggestie menu`, `/health config`.
2. `/voice config` — kies lobby/categorie en stel format in.
3. `/health setup` of bestaand Health Panel vernieuwen.
4. `/suggestie menu` — test één modal zonder echt te posten als je daarvoor een testkanaal gebruikt.
5. `/adminpanel dashboard` — Health/Temp Voice-tools controleren.
