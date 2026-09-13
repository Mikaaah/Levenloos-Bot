import asyncio
import os
import platform
from datetime import datetime, timezone
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands, tasks


# =========================================================
# CONFIG
# =========================================================

BOT_VERSION = "1.0.0"
STATUS_ROTATION_MINUTES = 5

ACTIVE_GAME_CATEGORY_ID = 940987098427707412
GAME_PROPOSAL_CHANNEL_ID = 940336215331319858

ARCHIVE_CATEGORY_ID = 1545088593716973568
ARCHIVE_RESTORE_CHANNEL_ID = 1545089501745913916

DATABASE_FILES = {
    "Main": "levenloos.db",
    "Levels": "levels.db",
    "Birthdays": "birthdays.db",
    "Profiles": "profiles.db",
    "LFG": "lfg.db",
}

EXPECTED_MODULES = [
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
    "lfg",
]

MODULE_LABELS = {
    "modules": "Modules",
    "games": "Games",
    "sorting": "Sorting",
    "stats": "Stats",
    "profile": "Profile / Badges",
    "welcome": "Welcome",
    "react": "React Roles",
    "levels": "Levels",
    "voice": "Voice",
    "events": "Events",
    "suggestions": "Suggesties",
    "changelog": "Changelog",
    "health": "Health",
    "botinfo": "Bot Info",
    "actionlog": "Action Log",
    "birthdays": "Verjaardagen",
    "reminders": "Reminders",
    "lfg": "LFG",
}

PURPLE = discord.Color.from_rgb(108, 39, 218)

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
INFO_EMOJI = "<:info:1547724036107149413>"

REFRESH_EMOJI = "<:refresh:1547724055426244618>"
PREVIOUS_EMOJI = "<:previous:1547724049411739748>"
NEXT_EMOJI = "<:next:1547724052037247106>"

BOT_EMOJI = "<:bot:1547733042150514748>"
MODULES_EMOJI = "<:modules:1547909513808580658>"
COMMANDS_EMOJI = "<:berichten:1547737207778058250>"
USER_EMOJI = "<:user:1547737210986692679>"
VOICE_EMOJI = "<:voice:1547737205429243924>"
GAMES_EMOJI = "<:gamesbutton:1547854165097717801>"
XP_EMOJI = "<:xp:1547737203789144136>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"


# =========================================================
# HELPERS
# =========================================================

def format_number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []

    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}u")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts[:3])


def shorten(text: str, length: int = 40) -> str:
    text = str(text)

    if len(text) <= length:
        return text

    return text[: max(0, length - 1)] + "…"


def clean_game_channel_name(channel: discord.abc.GuildChannel) -> str:
    name = channel.name

    if name.startswith("▏"):
        name = name[1:]

    return name.replace("-", " ").strip().title()


def extension_loaded(bot: commands.Bot, module_name: str) -> bool:
    return f"cogs.{module_name}" in bot.extensions


def get_group_commands(
    command: app_commands.Command | app_commands.Group,
) -> Iterable[app_commands.Command]:
    if isinstance(command, app_commands.Group):
        for child in command.commands:
            if isinstance(child, app_commands.Group):
                yield from get_group_commands(child)
            else:
                yield child
    else:
        yield command


def command_path(command: app_commands.Command) -> str:
    parts = [command.name]
    parent = command.parent

    while parent is not None:
        parts.append(parent.name)
        parent = parent.parent

    parts.reverse()
    return "/" + " ".join(parts)


def management_access(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True

    if member.guild_permissions.administrator:
        return True

    role_names = {role.name.lower() for role in member.roles}

    return "admin" in role_names or "owner" in role_names


# =========================================================
# COG
# =========================================================

class BotInfo(commands.Cog):

    info_group = app_commands.Group(
        name="bot",
        description="Informatie over de LEVENLOOS bot",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_index = 0

        if not hasattr(bot, "levenloos_started_at"):
            bot.levenloos_started_at = datetime.now(timezone.utc)

    async def cog_load(self):
        self.status_loop.start()
        print("[BOTINFO] Bot Info module geladen")

    def cog_unload(self):
        self.status_loop.cancel()

    # =====================================================
    # GENERAL DATA
    # =====================================================

    def uptime_seconds(self) -> float:
        started_at = getattr(
            self.bot,
            "levenloos_started_at",
            datetime.now(timezone.utc),
        )

        return (
            datetime.now(timezone.utc) - started_at
        ).total_seconds()

    def active_games_count(self, guild: discord.Guild) -> int:
        category = guild.get_channel(ACTIVE_GAME_CATEGORY_ID)

        if not isinstance(category, discord.CategoryChannel):
            return 0

        return sum(
            1
            for channel in category.channels
            if isinstance(channel, discord.TextChannel)
            and channel.id != GAME_PROPOSAL_CHANNEL_ID
        )

    def archived_games_count(self, guild: discord.Guild) -> int:
        category = guild.get_channel(ARCHIVE_CATEGORY_ID)

        if not isinstance(category, discord.CategoryChannel):
            return 0

        return sum(
            1
            for channel in category.channels
            if isinstance(channel, discord.TextChannel)
            and channel.id != ARCHIVE_RESTORE_CHANNEL_ID
        )

    def voice_now_count(self, guild: discord.Guild) -> int:
        return sum(
            1
            for channel in guild.voice_channels
            for member in channel.members
            if not member.bot
        )

    def command_list(self) -> list[app_commands.Command]:
        commands_found = []

        for root in self.bot.tree.get_commands():
            commands_found.extend(get_group_commands(root))

        commands_found.sort(
            key=lambda command: command_path(command).lower()
        )

        return commands_found

    async def get_stats_data(
        self,
        guild: discord.Guild,
    ) -> dict:
        data = {
            "week_messages": None,
            "active_users": None,
            "top_game": None,
            "top_game_messages": None,
            "voice_seconds": None,
            "top_player": None,
        }

        stats_cog = self.bot.get_cog("Stats")

        if stats_cog is None:
            return data

        try:
            if hasattr(stats_cog, "get_week_messages"):
                data["week_messages"] = await stats_cog.get_week_messages(
                    guild
                )
        except Exception:
            pass

        try:
            if hasattr(stats_cog, "get_active_users_count"):
                data["active_users"] = (
                    await stats_cog.get_active_users_count(guild)
                )
        except Exception:
            pass

        try:
            if hasattr(stats_cog, "get_top_game"):
                result = await stats_cog.get_top_game(guild)

                if result:
                    top_game, top_game_messages = result
                    data["top_game"] = top_game
                    data["top_game_messages"] = top_game_messages
        except Exception:
            pass

        try:
            if hasattr(stats_cog, "get_voice_totals"):
                totals = await stats_cog.get_voice_totals(guild)
                data["voice_seconds"] = sum(totals.values())
        except Exception:
            pass

        try:
            if hasattr(stats_cog, "get_top_player"):
                result = await stats_cog.get_top_player(guild)

                if result:
                    data["top_player"] = result[0]
        except Exception:
            pass

        return data

    # =====================================================
    # STATUS ROTATION
    # =====================================================

    async def build_statuses(
        self,
        guild: discord.Guild,
    ) -> list[tuple[discord.ActivityType, str]]:

        members = guild.member_count or len(guild.members)
        humans = sum(1 for member in guild.members if not member.bot)
        boosts = guild.premium_subscription_count or 0
        active_games = self.active_games_count(guild)
        archived_games = self.archived_games_count(guild)
        voice_now = self.voice_now_count(guild)
        commands_count = len(self.command_list())

        loaded_modules = sum(
            1
            for module in EXPECTED_MODULES
            if extension_loaded(self.bot, module)
        )

        latency_ms = round(self.bot.latency * 1000)
        stats = await self.get_stats_data(guild)

        # Discord activity/presence ondersteunt geen gerenderde
        # server-custom-emoji's zoals <:naam:id>. Unicode emoji's werken wel.
        statuses: list[tuple[discord.ActivityType, str]] = [
            (
                discord.ActivityType.watching,
                f"👥 {format_number(humans)} spelers in LEVENLOOS",
            ),
            (
                discord.ActivityType.playing,
                f"🎮 met {format_number(active_games)} actieve games",
            ),
            (
                discord.ActivityType.watching,
                f"📦 {format_number(archived_games)} gearchiveerde games",
            ),
            (
                discord.ActivityType.watching,
                f"🚀 {format_number(boosts)} server boosts",
            ),
            (
                discord.ActivityType.watching,
                f"🔊 {format_number(voice_now)} spelers in voice",
            ),
            (
                discord.ActivityType.playing,
                "✨ /level",
            ),
            (
                discord.ActivityType.playing,
                "🏆 /top",
            ),
            (
                discord.ActivityType.playing,
                "🎨 /react",
            ),
            (
                discord.ActivityType.playing,
                "🎂 /verjaardag",
            ),
            (
                discord.ActivityType.playing,
                "🗳️ /game vote",
            ),
            (
                discord.ActivityType.playing,
                "🔎 /lfg",
            ),
            (
                discord.ActivityType.watching,
                f"⌨️ {format_number(commands_count)} slash commands",
            ),
            (
                discord.ActivityType.watching,
                f"🧩 {loaded_modules}/{len(EXPECTED_MODULES)} modules",
            ),
            (
                discord.ActivityType.watching,
                f"⚡ {latency_ms}ms ping",
            ),
            (
                discord.ActivityType.playing,
                "🎮 LEVENLOOS",
            ),
            (
                discord.ActivityType.watching,
                "✨ jouw XP oplopen",
            ),
        ]

        if stats["week_messages"] is not None:
            statuses.append(
                (
                    discord.ActivityType.watching,
                    f"💬 {format_number(stats['week_messages'])} berichten deze week",
                )
            )

        if stats["active_users"] is not None:
            statuses.append(
                (
                    discord.ActivityType.watching,
                    f"🔥 {format_number(stats['active_users'])} actieve leden deze week",
                )
            )

        if stats["voice_seconds"] is not None:
            voice_hours = stats["voice_seconds"] / 3600

            statuses.append(
                (
                    discord.ActivityType.watching,
                    f"🔊 {voice_hours:.0f}u voice deze week",
                )
            )

        if stats["top_game"] is not None:
            game_name = clean_game_channel_name(
                stats["top_game"]
            )

            statuses.append(
                (
                    discord.ActivityType.watching,
                    f"🔥 {shorten(game_name, 30)} is #1",
                )
            )

        if stats["top_player"] is not None:
            statuses.append(
                (
                    discord.ActivityType.watching,
                    f"🏆 {shorten(stats['top_player'].display_name, 28)} is actiefste",
                )
            )

        fallback_statuses = [
            (
                discord.ActivityType.watching,
                "⬆️ nieuwe levels binnenkomen",
            ),
            (
                discord.ActivityType.playing,
                "🎨 met React Roles",
            ),
            (
                discord.ActivityType.watching,
                f"👤 {format_number(members)} accounts op de server",
            ),
            (
                discord.ActivityType.listening,
                "🎧 naar LEVENLOOS",
            ),
            (
                discord.ActivityType.watching,
                "🗳️ game votes",
            ),
        ]

        for status in fallback_statuses:
            if len(statuses) >= 20:
                break

            statuses.append(status)

        return statuses[:20]

    async def rotate_status(self):
        if not self.bot.guilds:
            return

        guild = max(
            self.bot.guilds,
            key=lambda item: item.member_count or 0,
        )

        statuses = await self.build_statuses(guild)

        if not statuses:
            return

        self.status_index %= len(statuses)

        activity_type, text = statuses[
            self.status_index
        ]

        activity = discord.Activity(
            type=activity_type,
            name=text,
        )

        await self.bot.change_presence(
            status=discord.Status.online,
            activity=activity,
        )

        print(
            f"[BOTINFO] Status {self.status_index + 1}/"
            f"{len(statuses)} → {text}"
        )

        self.status_index = (
            self.status_index + 1
        ) % len(statuses)

    @tasks.loop(minutes=STATUS_ROTATION_MINUTES)
    async def status_loop(self):
        try:
            await self.rotate_status()
        except Exception as exc:
            print(
                f"[BOTINFO STATUS] "
                f"{type(exc).__name__}: {exc}"
            )

    @status_loop.before_loop
    async def before_status_loop(self):
        await self.bot.wait_until_ready()

    # =====================================================
    # COMPONENTS V2 BUILDERS
    # =====================================================

    async def build_info_data(
        self,
        guild: discord.Guild,
    ) -> dict:
        ping = round(self.bot.latency * 1000)
        uptime = format_duration(
            self.uptime_seconds()
        )

        humans = sum(
            1
            for member in guild.members
            if not member.bot
        )
        bots = sum(
            1
            for member in guild.members
            if member.bot
        )

        active_games = self.active_games_count(
            guild
        )
        archived_games = self.archived_games_count(
            guild
        )
        voice_now = self.voice_now_count(
            guild
        )

        loaded_modules = [
            module
            for module in EXPECTED_MODULES
            if extension_loaded(
                self.bot,
                module,
            )
        ]

        command_count = len(
            self.command_list()
        )

        stats = await self.get_stats_data(
            guild
        )

        weekly_lines = []

        if stats["week_messages"] is not None:
            weekly_lines.append(
                f"> └ Berichten: **{format_number(stats['week_messages'])}**"
            )

        if stats["active_users"] is not None:
            weekly_lines.append(
                f"> └ Actieve leden: **{format_number(stats['active_users'])}**"
            )

        if stats["voice_seconds"] is not None:
            weekly_lines.append(
                f"> └ Voice: **{stats['voice_seconds'] / 3600:.1f} uur**"
            )

        if stats["top_game"] is not None:
            weekly_lines.append(
                f"> └ Top game: **{shorten(clean_game_channel_name(stats['top_game']), 32)}**"
            )

        if stats["top_player"] is not None:
            weekly_lines.append(
                f"> └ Actiefste: **{shorten(stats['top_player'].display_name, 32)}**"
            )

        if not weekly_lines:
            weekly_lines.append(
                "> └ Stats-module heeft nog geen weekdata."
            )

        database_lines = []

        for label, path in DATABASE_FILES.items():
            if os.path.exists(path):
                try:
                    size = os.path.getsize(path)
                    size_kb = size / 1024
                    database_lines.append(
                        f"> └ {SUCCESS_EMOJI} **{label}:** `{size_kb:.1f} KB`"
                    )
                except OSError:
                    database_lines.append(
                        f"> └ {WARNING_EMOJI} **{label}:** aanwezig"
                    )
            else:
                database_lines.append(
                    f"> └ **{label}:** niet aangemaakt"
                )

        bot_created = (
            discord.utils.format_dt(
                self.bot.user.created_at,
                style="D",
            )
            if self.bot.user is not None
            else "Onbekend"
        )

        avatar_url = (
            self.bot.user.display_avatar.url
            if self.bot.user is not None
            else None
        )

        return {
            "ping": ping,
            "uptime": uptime,
            "humans": humans,
            "bots": bots,
            "active_games": active_games,
            "archived_games": archived_games,
            "voice_now": voice_now,
            "loaded_modules": loaded_modules,
            "command_count": command_count,
            "weekly_lines": weekly_lines,
            "database_lines": database_lines,
            "bot_created": bot_created,
            "avatar_url": avatar_url,
        }

    def build_modules_data(
        self,
    ) -> tuple[list[str], list[str]]:
        loaded = []
        unloaded = []

        for module in EXPECTED_MODULES:
            label = MODULE_LABELS.get(
                module,
                module.title(),
            )

            if extension_loaded(
                self.bot,
                module,
            ):
                loaded.append(
                    f"> └ {SUCCESS_EMOJI} {label}"
                )
            else:
                unloaded.append(
                    f"> └ {ERROR_EMOJI} {label}"
                )

        return loaded, unloaded

    def build_commands_page(
        self,
        page: int = 0,
    ) -> tuple[str, int, int, int]:
        all_commands = self.command_list()
        per_page = 10

        pages = max(
            1,
            (
                len(all_commands)
                + per_page
                - 1
            )
            // per_page,
        )

        page = max(
            0,
            min(
                page,
                pages - 1,
            ),
        )

        start = page * per_page
        end = min(
            start + per_page,
            len(all_commands),
        )

        lines = []

        for command in all_commands[
            start:end
        ]:
            description = (
                command.description
                or "Geen beschrijving"
            )

            lines.append(
                f"### `{command_path(command)}`\n"
                f"> └ {shorten(description, 95)}"
            )

        if not lines:
            lines.append(
                "> └ Er zijn momenteel geen slash commands geladen."
            )

        body = (
            f"# {COMMANDS_EMOJI} Commands\n"
            "> └ Alle geladen slash commands van LEVENLOOS.\n\n"
            + "\n\n".join(lines)
        )

        return (
            body,
            page,
            pages,
            len(all_commands),
        )

    async def send_feedback(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
    ) -> None:
        view = BotFeedbackView(
            message,
            kind=kind,
            title=title,
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                view=view,
                ephemeral=True,
            )

    # =====================================================
    # /BOT INFO
    # =====================================================

    @info_group.command(
        name="info",
        description="Bekijk informatie en statistieken van de LEVENLOOS bot",
    )
    async def info_command(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        await interaction.response.defer()

        view = await BotInfoView.create(
            self,
            interaction.user.id,
            interaction.guild,
        )

        await interaction.followup.send(
            view=view,
        )

    # =====================================================
    # /BOT COMMANDS
    # =====================================================

    @info_group.command(
        name="commands",
        description="Bekijk alle slash commands van de LEVENLOOS bot",
    )
    async def commands_command(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.send_message(
            view=CommandPagesView(
                self,
                interaction.user.id,
                0,
            ),
            ephemeral=True,
        )

    # =====================================================
    # /BOT MODULES
    # =====================================================

    @info_group.command(
        name="modules",
        description="Bekijk welke botmodules geladen zijn",
    )
    async def modules_command(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.send_message(
            view=ModulesView(
                self,
                interaction.user.id,
            ),
            ephemeral=True,
        )

    # =====================================================
    # /BOT STATUS
    # =====================================================

    @info_group.command(
        name="status",
        description="Ga als admin direct naar de volgende botstatus",
    )
    async def status_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
        ):
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        if not management_access(
            interaction.user
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        await self.rotate_status()

        await self.send_feedback(
            interaction,
            "Botstatus doorgedraaid naar de volgende status.",
            kind="success",
            title="Status vernieuwd",
        )


# =========================================================
# COMPONENTS V2
# =========================================================

class BotFeedbackView(discord.ui.LayoutView):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
    ):
        super().__init__(
            timeout=180
        )

        if kind == "success":
            icon = SUCCESS_EMOJI
            accent = discord.Colour.from_rgb(
                87,
                242,
                135,
            )
            default_title = "Gelukt"
        elif kind == "error":
            icon = ERROR_EMOJI
            accent = discord.Colour.from_rgb(
                237,
                66,
                69,
            )
            default_title = "Fout"
        elif kind == "warning":
            icon = WARNING_EMOJI
            accent = discord.Colour.from_rgb(
                254,
                231,
                92,
            )
            default_title = "Let op"
        else:
            icon = INFO_EMOJI
            accent = PURPLE
            default_title = "Informatie"

        lines = [
            f"> └ {line}"
            for line in message.splitlines()
            if line.strip()
        ]

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {icon} {title or default_title}\n"
                    + "\n".join(lines)
                ),
                accent_colour=accent,
            )
        )


class BotInfoButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "BotInfoView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
        )
        self.owner_view = owner_view
        self.action = action

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.owner_view.handle(
            interaction,
            self.action,
        )


class BotInfoView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: BotInfo,
        owner_id: int,
        guild_id: int,
        data: dict,
    ):
        super().__init__(
            timeout=900
        )
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        header_text = (
            f"# {BOT_EMOJI} LEVENLOOS Bot\n"
            "> └ De officiële bot van **LEVENLOOS**.\n"
            "-# Levels, games, LFG, React Roles, statistieken, "
            "verjaardagen en serverbeheer in één bot."
        )

        if data["avatar_url"]:
            header = discord.ui.Section(
                discord.ui.TextDisplay(
                    header_text
                ),
                accessory=discord.ui.Thumbnail(
                    data["avatar_url"],
                    description="LEVENLOOS bot",
                ),
            )
        else:
            header = discord.ui.TextDisplay(
                header_text
            )

        body = [
            header,
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            ),
            discord.ui.TextDisplay(
                f"## {BOT_EMOJI} Bot\n"
                f"> └ Ping: **{data['ping']} ms**\n"
                f"> └ Uptime: **{data['uptime']}**\n"
                f"> └ Versie: **{BOT_VERSION}**\n"
                f"> └ Discord.py: **{discord.__version__}**\n"
                f"> └ Python: **{platform.python_version()}**"
            ),
            discord.ui.TextDisplay(
                f"## {USER_EMOJI} Server\n"
                f"> └ Leden: **{format_number(data['humans'])}**\n"
                f"> └ Bots: **{format_number(data['bots'])}**\n"
                f"> └ Boosts: **{format_number(self._guild_boosts())}**\n"
                f"> └ In voice: **{format_number(data['voice_now'])}**\n"
                f"> └ Rollen: **{format_number(self._guild_roles())}**"
            ),
            discord.ui.TextDisplay(
                f"## {GAMES_EMOJI} Games\n"
                f"> └ Actief: **{format_number(data['active_games'])}**\n"
                f"> └ Gearchiveerd: **{format_number(data['archived_games'])}**\n"
                f"> └ Tekstkanalen: **{format_number(self._text_channels())}**\n"
                f"> └ Voicekanalen: **{format_number(self._voice_channels())}**\n"
                f"> └ Categorieën: **{format_number(self._categories())}**"
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            ),
            discord.ui.TextDisplay(
                f"## {XP_EMOJI} Deze week\n"
                + "\n".join(
                    data["weekly_lines"]
                )
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            ),
            discord.ui.TextDisplay(
                f"## {SETTINGS_EMOJI} Systeem\n"
                f"> └ Modules: **{len(data['loaded_modules'])}/{len(EXPECTED_MODULES)}**\n"
                f"> └ Commands: **{format_number(data['command_count'])}**\n"
                f"> └ Servers: **{format_number(len(cog.bot.guilds))}**\n"
                f"> └ OS: **{platform.system()} {platform.release()}**\n"
                f"> └ Statusrotatie: **{STATUS_ROTATION_MINUTES} min**"
            ),
            discord.ui.TextDisplay(
                f"## {INFO_EMOJI} Applicatie\n"
                f"> └ Naam: **{cog.bot.user.name if cog.bot.user else 'LEVENLOOS'}**\n"
                f"> └ ID: `{cog.bot.user.id if cog.bot.user else 'Onbekend'}`\n"
                f"> └ Aangemaakt: {data['bot_created']}"
            ),
            discord.ui.TextDisplay(
                "## Databases\n"
                + "\n".join(
                    data["database_lines"]
                )
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            ),
            discord.ui.ActionRow(
                BotInfoButton(
                    self,
                    "refresh",
                    "Vernieuwen",
                    emoji=REFRESH_EMOJI,
                    style=discord.ButtonStyle.primary,
                ),
                BotInfoButton(
                    self,
                    "commands",
                    "Commands",
                    emoji=COMMANDS_EMOJI,
                ),
                BotInfoButton(
                    self,
                    "modules",
                    "Modules",
                    emoji=MODULES_EMOJI,
                ),
            ),
            discord.ui.TextDisplay(
                "-# LEVENLOOS • Bot Info"
            ),
        ]

        self.add_item(
            discord.ui.Container(
                *body,
                accent_colour=PURPLE,
            )
        )

    @classmethod
    async def create(
        cls,
        cog: BotInfo,
        owner_id: int,
        guild: discord.Guild,
    ) -> "BotInfoView":
        data = await cog.build_info_data(
            guild
        )
        view = cls(
            cog,
            owner_id,
            guild.id,
            data,
        )
        view._guild = guild
        return view

    def _guild_obj(
        self,
    ) -> discord.Guild | None:
        guild = getattr(
            self,
            "_guild",
            None,
        )
        if guild is not None:
            return guild

        return self.cog.bot.get_guild(
            self.guild_id
        )

    def _guild_boosts(self) -> int:
        guild = self._guild_obj()
        return (
            guild.premium_subscription_count or 0
            if guild is not None
            else 0
        )

    def _guild_roles(self) -> int:
        guild = self._guild_obj()
        return len(guild.roles) if guild else 0

    def _text_channels(self) -> int:
        guild = self._guild_obj()
        return len(guild.text_channels) if guild else 0

    def _voice_channels(self) -> int:
        guild = self._guild_obj()
        return len(guild.voice_channels) if guild else 0

    def _categories(self) -> int:
        guild = self._guild_obj()
        return len(guild.categories) if guild else 0

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.owner_id:
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit menu hoort bij iemand anders.",
            kind="error",
            title="Geen toegang",
        )
        return False

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "refresh":
            guild = interaction.guild

            if guild is None:
                await self.cog.send_feedback(
                    interaction,
                    "De server kon niet worden gevonden.",
                    kind="error",
                )
                return

            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BotInfoView.create(
                    self.cog,
                    self.owner_id,
                    guild,
                ),
            )
            return

        if action == "commands":
            await interaction.response.send_message(
                view=CommandPagesView(
                    self.cog,
                    self.owner_id,
                    0,
                ),
                ephemeral=True,
            )
            return

        if action == "modules":
            await interaction.response.send_message(
                view=ModulesView(
                    self.cog,
                    self.owner_id,
                ),
                ephemeral=True,
            )


class ModulesView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: BotInfo,
        owner_id: int,
    ):
        super().__init__(
            timeout=900
        )
        self.cog = cog
        self.owner_id = owner_id

        loaded, unloaded = (
            cog.build_modules_data()
        )

        loaded_text = (
            "\n".join(loaded)
            if loaded
            else "> └ Geen"
        )
        unloaded_text = (
            "\n".join(unloaded)
            if unloaded
            else "> └ Geen"
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {MODULES_EMOJI} Modules\n"
                    f"> └ **{len(loaded)}/{len(EXPECTED_MODULES)}** modules geladen."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"## {SUCCESS_EMOJI} Geladen\n"
                    f"{loaded_text}"
                ),
                discord.ui.TextDisplay(
                    f"## {ERROR_EMOJI} Uitgeschakeld\n"
                    f"{unloaded_text}"
                ),
                discord.ui.TextDisplay(
                    "-# LEVENLOOS • Modules"
                ),
                accent_colour=PURPLE,
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.owner_id:
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit menu hoort bij iemand anders.",
            kind="error",
            title="Geen toegang",
        )
        return False


class CommandPageButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "CommandPagesView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            disabled=disabled,
        )
        self.owner_view = owner_view
        self.action = action

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.owner_view.handle(
            interaction,
            self.action,
        )


class CommandPagesView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: BotInfo,
        owner_id: int,
        page: int,
    ):
        super().__init__(
            timeout=900
        )
        self.cog = cog
        self.owner_id = owner_id

        (
            body,
            page,
            pages,
            total_commands,
        ) = cog.build_commands_page(
            page
        )

        self.page = page
        self.pages = pages

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    body
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    CommandPageButton(
                        self,
                        "previous",
                        "Vorige",
                        emoji=PREVIOUS_EMOJI,
                        style=discord.ButtonStyle.primary,
                        disabled=page <= 0,
                    ),
                    CommandPageButton(
                        self,
                        "page",
                        f"{page + 1}/{pages}",
                        disabled=True,
                    ),
                    CommandPageButton(
                        self,
                        "next",
                        "Volgende",
                        emoji=NEXT_EMOJI,
                        style=discord.ButtonStyle.primary,
                        disabled=page >= pages - 1,
                    ),
                ),
                discord.ui.TextDisplay(
                    f"-# {total_commands} commands • Pagina {page + 1}/{pages}"
                ),
                accent_colour=PURPLE,
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.owner_id:
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit menu hoort bij iemand anders.",
            kind="error",
            title="Geen toegang",
        )
        return False

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "page":
            return

        new_page = self.page

        if action == "previous":
            new_page = max(
                0,
                self.page - 1,
            )
        elif action == "next":
            new_page = min(
                self.pages - 1,
                self.page + 1,
            )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=CommandPagesView(
                self.cog,
                self.owner_id,
                new_page,
            ),
        )

# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(
        BotInfo(bot)
    )
