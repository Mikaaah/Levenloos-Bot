# Bijdragen aan LEVENLOOS Discord Bot

Meld bugs en voorstellen via de [issues](https://github.com/Mikaaah/Levenloos-Bot/issues). Vermeld het commando of paneel, de gebruikte versie, benodigde rechten, stappen om het probleem te herhalen en het verwachte en werkelijke resultaat.

## Veilig testen

- Gebruik een aparte testbot en testserver. Test moderatie, rollen, meldingen en tijdelijke kanalen zonder de productieserver te wijzigen.
- Installeer de dependencies uit `requirements.txt` in een virtuele omgeving. Gebruik `.env.example` als voorbeeld voor je lokale configuratie.
- Deel nooit tokens, `.env`, databases, backups of persoonsgegevens. Maak logs en screenshots eerst schoon.
- Controleer rechten, commandosynchronisatie, herstarts en bestaande data bij wijzigingen aan de bijbehorende systemen.

## Pull requests

Houd wijzigingen gericht en beschrijf de aanleiding, het resultaat en de uitgevoerde tests. Vermeld expliciet wat nog niet is getest. Werk de [README](README.md) en [deploymentnotities](DEPLOY_NOTES.md) bij wanneer gedrag of installatie verandert. Bespreek grote wijzigingen eerst in een issue. Behoud bestaande commando's en data, of beschrijf vooraf een migratieplan.
