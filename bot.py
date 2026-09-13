import os
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SYNC_COMMANDS_ON_STARTUP = os.getenv("SYNC_COMMANDS_ON_STARTUP", "true").lower() in {"1", "true", "yes", "on"}

intents = discord.Intents.all()

COGS = (
    "modules",
    "games",
    "sorting",
    "stats",
    "profile",
    "welcome",
    "react",
    "levels",
    "voice",
    "events",
    "suggestions",
    "changelog",
    "health",
    "botinfo",
    "actionlog",
    "birthdays",
    "reminders",
)


class LevenloosTree(app_commands.CommandTree):
    """Global safety net so slash-command failures never disappear silently."""

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)

        # Volledige technische fout blijft beschikbaar voor beheer/debugging.
        print(f"[COMMAND ERROR] {type(original).__name__}: {original}")
        traceback.print_exception(type(original), original, original.__traceback__)

        # Sla de fout ook op in het bestaande Admin Panel -> Errors systeem.
        try:
            modules_cog = interaction.client.get_cog("Modules")
            if modules_cog is not None and hasattr(modules_cog, "record_error"):
                command = getattr(interaction, "command", None)
                command_name = getattr(command, "qualified_name", None) or "onbekend-command"
                modules_cog.record_error(f"slash:{command_name}", original)
        except Exception as log_exc:
            print(
                f"[COMMAND ERROR LOGGING] "
                f"{type(log_exc).__name__}: {log_exc}"
            )

        # Normale gebruikers krijgen nooit exception-namen, HTTP-codes,
        # databasefouten of tracebacks te zien.
        message = (
            "❌ Er ging iets mis bij dit command. "
            "Probeer het over een moment opnieuw."
        )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


# =========================================================
# BOT
# =========================================================

class LevenloosBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            tree_cls=LevenloosTree,
        )
        self.extension_failures: dict[str, str] = {}

    async def setup_hook(self):
        for cog in COGS:
            try:
                await self.load_extension(f"cogs.{cog}")
                print(f"[COGS] {cog.capitalize()} geladen")
            except Exception as exc:
                self.extension_failures[cog] = f"{type(exc).__name__}: {exc}"
                print(f"[COGS ERROR] {cog}: {type(exc).__name__}: {exc}")
                traceback.print_exc()

        if SYNC_COMMANDS_ON_STARTUP:
            try:
                synced = await self.tree.sync()
                print(f"[SYNC] {len(synced)} globale command(s) gesynchroniseerd")
            except Exception as exc:
                print(f"[SYNC ERROR] {type(exc).__name__}: {exc}")
                traceback.print_exc()
        else:
            print("[SYNC] Startup sync uitgeschakeld via SYNC_COMMANDS_ON_STARTUP=false")

    async def on_ready(self):
        if self.user is None:
            return

        print(f"[BOT] Ingelogd als {self.user} ({self.user.id})")
        print(f"[BOT] Actief op {len(self.guilds)} server(s)")
        if self.extension_failures:
            print(f"[BOT] Modules met laadfout: {', '.join(self.extension_failures)}")

        for guild in self.guilds:
            print(f"[BOT] Server: {guild.name} ({guild.id})")


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN ontbreekt in .env")
    bot = LevenloosBot()
    bot.run(DISCORD_TOKEN)
