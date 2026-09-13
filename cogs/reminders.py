from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks

DB_PATH = Path("reminders.db")
PURPLE = 0x9440D0


def parse_duration(value: str) -> timedelta:
    value = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)(m|h|d|w)", value)
    if not match:
        raise ValueError
    number = int(match.group(1))
    if number < 1:
        raise ValueError
    unit = match.group(2)
    delta = {
        "m": timedelta(minutes=number),
        "h": timedelta(hours=number),
        "d": timedelta(days=number),
        "w": timedelta(weeks=number),
    }[unit]
    if delta > timedelta(days=365):
        raise ValueError
    return delta


class ReminderModal(discord.ui.Modal, title="Nieuwe reminder"):
    def __init__(self, cog: "Reminders"):
        super().__init__(timeout=300)
        self.cog = cog
        self.when = discord.ui.RadioGroup(
            options=[
                discord.RadioGroupOption(label="Over 15 minuten", value="15m"),
                discord.RadioGroupOption(label="Over 30 minuten", value="30m"),
                discord.RadioGroupOption(label="Over 1 uur", value="1h"),
                discord.RadioGroupOption(label="Over 3 uur", value="3h"),
                discord.RadioGroupOption(label="Morgen", value="1d"),
                discord.RadioGroupOption(label="Zelf invullen", value="custom"),
            ]
        )
        self.custom = discord.ui.TextInput(
            label="Eigen tijd (alleen bij Zelf invullen)",
            placeholder="Bijv. 45m, 2h, 3d of 1w",
            required=False,
            max_length=12,
        )
        self.text = discord.ui.TextInput(
            label="Waar moet ik je aan herinneren?",
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.add_item(discord.ui.Label(text="Wanneer?", description="Kies een snelle optie of gebruik je eigen tijd.", component=self.when))
        self.add_item(self.custom)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.custom.value.strip() if self.when.value == "custom" else self.when.value
        try:
            delta = parse_duration(raw)
        except ValueError:
            await interaction.response.send_message("❌ Gebruik bij eigen tijd bijvoorbeeld `45m`, `2h`, `3d` of `1w`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        due = discord.utils.utcnow() + delta
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "INSERT INTO reminders(user_id,guild_id,channel_id,due_at,text) VALUES(?,?,?,?,?)",
                (interaction.user.id, interaction.guild_id, interaction.channel_id, due.isoformat(), self.text.value.strip()),
            )
            await db.commit()
            reminder_id = cur.lastrowid
        await interaction.followup.send(
            f"✅ Reminder `#{reminder_id}` staat voor <t:{int(due.timestamp())}:R>.\n└ {self.text.value.strip()[:200]}",
            ephemeral=True,
        )


class ReminderSelect(discord.ui.Select):
    def __init__(self, cog: "Reminders", user_id: int, rows):
        options = []
        for rid, due, text in rows[:25]:
            dt = discord.utils.parse_time(due)
            description = dt.strftime("%d-%m %H:%M") if dt else "Onbekende tijd"
            options.append(discord.SelectOption(label=f"#{rid} • {text[:75]}", value=str(rid), description=description, emoji="⏰"))
        super().__init__(placeholder="Kies een reminder om te annuleren…", options=options, min_values=1, max_values=1)
        self.cog = cog
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Dit is niet jouw reminderlijst.", ephemeral=True)
            return
        rid = int(self.values[0])
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("DELETE FROM reminders WHERE id=? AND user_id=? AND sent=0", (rid, self.user_id))
            await db.commit()
        await interaction.response.edit_message(
            content="✅ Reminder geannuleerd." if cur.rowcount else "❌ Die reminder bestaat niet meer.",
            embed=None,
            view=None,
        )


class ReminderListView(discord.ui.View):
    def __init__(self, cog: "Reminders", user_id: int, rows):
        super().__init__(timeout=180)
        if rows:
            self.add_item(ReminderSelect(cog, user_id, rows))


class Reminders(commands.Cog):
    reminder = app_commands.Group(name="reminder", description="Persoonlijke reminders")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS reminders(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    due_at TEXT NOT NULL,
                    text TEXT NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0
                )"""
            )
            await db.commit()
        self.dispatch_loop.start()

    def cog_unload(self):
        self.dispatch_loop.cancel()

    @tasks.loop(seconds=30)
    async def dispatch_loop(self):
        now = discord.utils.utcnow().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await (await db.execute(
                "SELECT id,user_id,guild_id,channel_id,text FROM reminders WHERE sent=0 AND due_at<=? ORDER BY due_at LIMIT 25",
                (now,),
            )).fetchall()
        for reminder_id, user_id, guild_id, channel_id, text in rows:
            sent = False
            guild = self.bot.get_guild(int(guild_id)) if guild_id else None
            channel = guild.get_channel(int(channel_id)) if guild and channel_id else None
            if isinstance(channel, discord.abc.Messageable):
                try:
                    await channel.send(f"⏰ <@{user_id}> **Reminder**\n> {text}", allowed_mentions=discord.AllowedMentions(users=True))
                    sent = True
                except discord.HTTPException:
                    pass
            if not sent:
                try:
                    user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
                    await user.send(f"⏰ **Reminder**\n> {text}")
                    sent = True
                except (discord.HTTPException, discord.NotFound):
                    pass
            if sent:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE reminders SET sent=1 WHERE id=?", (reminder_id,))
                    await db.commit()

    @dispatch_loop.before_loop
    async def before_dispatch(self):
        await self.bot.wait_until_ready()

    async def open_rows(self, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            return await (await db.execute(
                "SELECT id,due_at,text FROM reminders WHERE user_id=? AND sent=0 ORDER BY due_at LIMIT 25",
                (user_id,),
            )).fetchall()

    @reminder.command(name="maak", description="Maak een persoonlijke reminder met snelle tijdkeuze")
    async def create_reminder(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReminderModal(self))

    @reminder.command(name="lijst", description="Bekijk en beheer je open reminders")
    async def list_reminders(self, interaction: discord.Interaction):
        rows = await self.open_rows(interaction.user.id)
        if not rows:
            await interaction.response.send_message("⏰ Je hebt geen open reminders.", ephemeral=True)
            return
        lines = []
        for rid, due, text in rows:
            dt = discord.utils.parse_time(due)
            when = f"<t:{int(dt.timestamp())}:R>" if dt else due
            lines.append(f"> `#{rid}` • {when}\n> └ {text[:100]}")
        embed = discord.Embed(title="⏰ JOUW REMINDERS", description="\n\n".join(lines), color=PURPLE)
        embed.set_footer(text="Gebruik de dropdown hieronder om er eentje te annuleren.")
        await interaction.response.send_message(embed=embed, view=ReminderListView(self, interaction.user.id, rows), ephemeral=True)

    @reminder.command(name="annuleer", description="Annuleer een open reminder via nummer")
    async def cancel_reminder(self, interaction: discord.Interaction, nummer: int):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("DELETE FROM reminders WHERE id=? AND user_id=? AND sent=0", (nummer, interaction.user.id))
            await db.commit()
        await interaction.response.send_message("✅ Reminder geannuleerd." if cur.rowcount else "❌ Die open reminder kon ik niet vinden.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
