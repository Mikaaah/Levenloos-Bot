import asyncio
import calendar
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

DATABASE_PATH = "levenloos.db"
ROOT = Path(__file__).resolve().parent.parent
BIRTHDAY_DATABASE_PATH = ROOT / "birthdays.db"

ACTIVE_GAME_CATEGORY_ID = 940987098427707412
GAME_PROPOSAL_CHANNEL_ID = 940336215331319858

STATS_CATEGORY_NAME = "📊 SERVER STATS"

MEMBER_UPDATE_MINUTES = 5
CALENDAR_UPDATE_MINUTES = 5
ROTATION_MINUTES = 20
MONTHLY_THROWBACK_CHECK_MINUTES = 60

TIMEZONE = ZoneInfo("Europe/Amsterdam")
PURPLE = discord.Colour.from_rgb(108, 39, 218)

DUTCH_MONTHS = (
    "",
    "JAN",
    "FEB",
    "MRT",
    "APR",
    "MEI",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OKT",
    "NOV",
    "DEC",
)

DUTCH_WEEKDAYS = (
    "MA",
    "DI",
    "WO",
    "DO",
    "VR",
    "ZA",
    "ZO",
)

DUTCH_MONTH_NAMES = (
    "",
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)

logger = logging.getLogger(__name__)


# ============================================================
# LEVENLOOS CUSTOM EMOJIS
# ============================================================

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
INFO_EMOJI = "<:info:1547724036107149413>"
REFRESH_EMOJI = "<:refresh:1547724055426244618>"


# ============================================================
# DATABASE
# ============================================================

async def initialise_stats_database():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_config (
                guild_id INTEGER PRIMARY KEY,
                category_id INTEGER NOT NULL,
                date_channel_id INTEGER NOT NULL DEFAULT 0,
                members_channel_id INTEGER NOT NULL,
                rotating_channel_id INTEGER NOT NULL,
                birthday_channel_id INTEGER NOT NULL DEFAULT 0,
                rotation_index INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_weekly_users (
                guild_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0,
                voice_seconds INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (
                    guild_id,
                    week_start,
                    user_id
                )
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_weekly_games (
                guild_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (
                    guild_id,
                    week_start,
                    channel_id
                )
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_voice_sessions (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                started_at REAL NOT NULL,
                PRIMARY KEY (
                    guild_id,
                    user_id
                )
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_monthly_users (
                guild_id INTEGER NOT NULL,
                month_key TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0,
                voice_seconds INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (
                    guild_id,
                    month_key,
                    user_id
                )
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_monthly_games (
                guild_id INTEGER NOT NULL,
                month_key TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (
                    guild_id,
                    month_key,
                    channel_id
                )
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_monthly_throwbacks (
                guild_id INTEGER NOT NULL,
                month_key TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                posted_at REAL NOT NULL,
                PRIMARY KEY (
                    guild_id,
                    month_key
                )
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_monthly_meta (
                guild_id INTEGER PRIMARY KEY,
                tracking_started_at REAL NOT NULL
            )
            """
        )

        # Backward-compatible uitbreiding van bestaande stats_config.
        cursor = await db.execute("PRAGMA table_info(stats_config)")
        config_columns = {
            str(row[1])
            for row in await cursor.fetchall()
        }

        if "date_channel_id" not in config_columns:
            await db.execute(
                "ALTER TABLE stats_config "
                "ADD COLUMN date_channel_id INTEGER NOT NULL DEFAULT 0"
            )

        if "birthday_channel_id" not in config_columns:
            await db.execute(
                "ALTER TABLE stats_config "
                "ADD COLUMN birthday_channel_id INTEGER NOT NULL DEFAULT 0"
            )

        if "throwback_channel_id" not in config_columns:
            await db.execute(
                "ALTER TABLE stats_config "
                "ADD COLUMN throwback_channel_id INTEGER NOT NULL DEFAULT 0"
            )

        if "throwback_enabled" not in config_columns:
            await db.execute(
                "ALTER TABLE stats_config "
                "ADD COLUMN throwback_enabled INTEGER NOT NULL DEFAULT 1"
            )

        # Bestaande tabellen/data blijven intact; deze indexes versnellen
        # alleen de terugkerende weekqueries.
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stats_weekly_users_guild_week
            ON stats_weekly_users(guild_id, week_start)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stats_weekly_games_guild_week
            ON stats_weekly_games(guild_id, week_start)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stats_voice_sessions_guild
            ON stats_voice_sessions(guild_id)
            """
        )

        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stats_monthly_users_guild_month
            ON stats_monthly_users(guild_id, month_key)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stats_monthly_games_guild_month
            ON stats_monthly_games(guild_id, month_key)
            """
        )

        await db.commit()

    logger.info("Stats-database klaar.")


# ============================================================
# WEEK HELPERS
# ============================================================

def get_week_start(
    moment: datetime | None = None,
) -> str:
    if moment is None:
        moment = datetime.now(TIMEZONE)
    elif moment.tzinfo is None:
        moment = moment.replace(tzinfo=TIMEZONE)
    else:
        moment = moment.astimezone(TIMEZONE)

    monday = moment - timedelta(days=moment.weekday())
    return monday.date().isoformat()


def get_week_start_timestamp() -> float:
    now = datetime.now(TIMEZONE)

    monday = (
        now
        - timedelta(days=now.weekday())
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    return monday.timestamp()


def get_month_key(
    moment: datetime | None = None,
) -> str:
    moment = moment or datetime.now(TIMEZONE)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TIMEZONE)
    else:
        moment = moment.astimezone(TIMEZONE)

    return f"{moment.year:04d}-{moment.month:02d}"


def month_key_parts(
    month_key: str,
) -> tuple[int, int]:
    year_text, month_text = month_key.split("-", 1)
    return int(year_text), int(month_text)


def month_bounds(
    month_key: str,
) -> tuple[datetime, datetime]:
    year, month = month_key_parts(month_key)

    start = datetime(
        year,
        month,
        1,
        tzinfo=TIMEZONE,
    )

    if month == 12:
        end = datetime(
            year + 1,
            1,
            1,
            tzinfo=TIMEZONE,
        )
    else:
        end = datetime(
            year,
            month + 1,
            1,
            tzinfo=TIMEZONE,
        )

    return start, end


def previous_month_key(
    moment: datetime | None = None,
) -> str:
    moment = moment or datetime.now(TIMEZONE)
    first_this_month = moment.astimezone(TIMEZONE).replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    previous = first_this_month - timedelta(days=1)
    return get_month_key(previous)


def month_display_name(
    month_key: str,
) -> str:
    year, month = month_key_parts(month_key)
    return (
        f"{DUTCH_MONTH_NAMES[month].upper()} "
        f"{year}"
    )


# ============================================================
# PERMISSIONS
# ============================================================

def management_access(
    member: discord.Member,
) -> bool:
    if member.guild.owner_id == member.id:
        return True

    if member.guild_permissions.administrator:
        return True

    role_names = {
        role.name.casefold()
        for role in member.roles
    }

    return "admin" in role_names or "owner" in role_names


# ============================================================
# TEXT / UI HELPERS
# ============================================================

def shorten(
    text: str,
    maximum: int = 70,
) -> str:
    text = str(text).strip()

    if len(text) <= maximum:
        return text

    return text[: maximum - 1] + "…"


def game_channel_display_name(
    channel: discord.TextChannel,
) -> str:
    name = channel.name.lstrip("▏│┃|◆ ")
    return name.replace("-", " ").title()


def format_number(
    number: int,
) -> str:
    return f"{number:,}".replace(",", ".")


def format_voice_hours(
    seconds: int,
) -> str:
    hours = seconds / 3600

    if hours < 10:
        return f"{hours:.1f}".replace(".", ",") + "u"

    return f"{hours:.0f}u"


def format_date_channel_name(
    moment: datetime | None = None,
) -> str:
    moment = moment or datetime.now(TIMEZONE)
    return (
        f"▏📅 {DUTCH_WEEKDAYS[moment.weekday()]} "
        f"{moment.day:02d} "
        f"{DUTCH_MONTHS[moment.month]} "
        f"{moment.year}"
    )


def birthday_stat_name(
    members: list[discord.Member],
) -> str:
    names = [
        shorten(
            member.display_name.replace("\n", " ").strip(),
            35,
        )
        for member in members
    ]

    if not names:
        return "▏🎂 Vandaag jarig"

    if len(names) == 1:
        return shorten(f"▏🎂 Jarig: {names[0]}", 100)

    if len(names) == 2:
        return shorten(
            f"▏🎂 Jarig: {names[0]} & {names[1]}",
            100,
        )

    return shorten(
        f"▏🎂 Jarig: {names[0]} +{len(names) - 1}",
        100,
    )


def feedback_accent(
    kind: str,
) -> discord.Colour:
    if kind == "success":
        return discord.Colour.from_rgb(87, 242, 135)

    if kind == "error":
        return discord.Colour.from_rgb(237, 66, 69)

    if kind == "warning":
        return discord.Colour.from_rgb(254, 231, 92)

    return PURPLE


def feedback_emoji(
    kind: str,
) -> str:
    return {
        "success": SUCCESS_EMOJI,
        "error": ERROR_EMOJI,
        "warning": WARNING_EMOJI,
        "info": INFO_EMOJI,
    }.get(kind, INFO_EMOJI)


class StatsFeedbackView(discord.ui.LayoutView):
    def __init__(
        self,
        title: str,
        lines: list[str],
        *,
        kind: str = "info",
        footer: str | None = None,
    ):
        super().__init__(timeout=180)

        text = (
            f"# {feedback_emoji(kind)} {title}\n"
            + "\n".join(
                f"> └ {line}"
                for line in lines
            )
        )

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(text),
        ]

        if footer:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.TextDisplay(
                        f"-# {footer}"
                    ),
                ]
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=feedback_accent(kind),
            )
        )


class StatsDetailView(discord.ui.LayoutView):
    def __init__(
        self,
        title: str,
        sections: list[tuple[str, list[str]]],
        *,
        footer: str | None = None,
    ):
        super().__init__(timeout=180)

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"# {INFO_EMOJI} {title}"
            )
        ]

        for heading, lines in sections:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.TextDisplay(
                        f"## {heading}\n"
                        + "\n".join(
                            f"> └ {line}"
                            for line in lines
                        )
                    ),
                ]
            )

        if footer:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.TextDisplay(
                        f"-# {footer}"
                    ),
                ]
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PURPLE,
            )
        )


class MonthlyThrowbackView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        month_key: str,
        total_messages: int,
        total_voice_seconds: int,
        active_members: int,
        top_messages: list[tuple[discord.Member, int]],
        top_voice: list[tuple[discord.Member, int]],
        top_overall: list[tuple[discord.Member, int, int]],
        top_games: list[tuple[str, int]],
        birthdays: list[tuple[discord.Member, int]],
        congratulations: int,
        tracking_started_at: float | None,
    ):
        super().__init__(timeout=None)

        year, month = month_key_parts(month_key)
        days_in_month = calendar.monthrange(year, month)[1]
        avg_messages = (
            total_messages / days_in_month
            if days_in_month
            else 0
        )
        avg_voice_seconds = (
            total_voice_seconds / days_in_month
            if days_in_month
            else 0
        )

        def medal(index: int) -> str:
            return ("🥇", "🥈", "🥉", "4.", "5.")[index]

        if top_messages:
            message_lines = [
                (
                    f"{medal(index)} {member.mention} • "
                    f"**{format_number(amount)}** berichten"
                )
                for index, (member, amount) in enumerate(
                    top_messages[:5]
                )
            ]
        else:
            message_lines = [
                "Nog geen berichtendata voor deze maand."
            ]

        if top_voice:
            voice_lines = [
                (
                    f"{medal(index)} {member.mention} • "
                    f"**{format_voice_hours(seconds)}**"
                )
                for index, (member, seconds) in enumerate(
                    top_voice[:5]
                )
            ]
        else:
            voice_lines = [
                "Nog geen voicedata voor deze maand."
            ]

        if top_overall:
            overall_lines = [
                (
                    f"{medal(index)} {member.mention} • "
                    f"{format_number(messages)} berichten + "
                    f"{format_voice_hours(voice_seconds)} voice"
                )
                for index, (
                    member,
                    messages,
                    voice_seconds,
                ) in enumerate(
                    top_overall[:5]
                )
            ]
        else:
            overall_lines = [
                "Nog geen activiteit voor deze maand."
            ]

        if top_games:
            game_lines = [
                (
                    f"{medal(index)} **{name}** • "
                    f"{format_number(messages)} berichten"
                )
                for index, (name, messages) in enumerate(
                    top_games[:5]
                )
            ]
        else:
            game_lines = [
                "Nog geen gamekanaaldata voor deze maand."
            ]

        if birthdays:
            birthday_lines = [
                (
                    f"**{day:02d} {DUTCH_MONTHS[month]}** • "
                    f"{member.mention}"
                )
                for member, day in birthdays[:12]
            ]
            if len(birthdays) > 12:
                birthday_lines.append(
                    f"En nog **{len(birthdays) - 12}** verjaardag(en)."
                )
        else:
            birthday_lines = [
                "Geen geregistreerde verjaardagen deze maand."
            ]

        tracking_note = (
            f"{month_display_name(month_key)} • "
            "automatisch gegenereerde maandthrowback"
        )

        if tracking_started_at:
            tracking_start = datetime.fromtimestamp(
                tracking_started_at,
                TIMEZONE,
            )
            month_start, month_end = month_bounds(month_key)
            if month_start < tracking_start < month_end:
                tracking_note += (
                    " • gedeeltelijke maanddata vanaf "
                    f"{tracking_start.day:02d} "
                    f"{DUTCH_MONTHS[tracking_start.month]} "
                    f"{tracking_start.year}"
                )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# Monthly Throwback • {month_display_name(month_key)}\n"
                    "> └ Alles wat er afgelopen maand op LEVENLOOS gebeurde."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    "## Maand in cijfers\n"
                    f"> └ Berichten: **{format_number(total_messages)}**\n"
                    f"> └ Voice: **{format_voice_hours(total_voice_seconds)}**\n"
                    f"> └ Actieve leden: **{format_number(active_members)}**\n"
                    f"> └ Gemiddeld: **{avg_messages:.0f} berichten/dag** "
                    f"• **{format_voice_hours(int(avg_voice_seconds))} voice/dag**"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    "## Meeste berichten\n"
                    + "\n".join(
                        f"> └ {line}"
                        for line in message_lines
                    )
                ),
                discord.ui.TextDisplay(
                    "## Meeste voice\n"
                    + "\n".join(
                        f"> └ {line}"
                        for line in voice_lines
                    )
                ),
                discord.ui.TextDisplay(
                    "## Meest actief overall\n"
                    + "\n".join(
                        f"> └ {line}"
                        for line in overall_lines
                    )
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    "## Populairste games\n"
                    + "\n".join(
                        f"> └ {line}"
                        for line in game_lines
                    )
                ),
                discord.ui.TextDisplay(
                    "## Verjaardagen\n"
                    + "\n".join(
                        f"> └ {line}"
                        for line in birthday_lines
                    )
                    + (
                        f"\n> └ Felicitaties verstuurd: "
                        f"**{format_number(congratulations)}**"
                        if congratulations
                        else ""
                    )
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"-# {tracking_note}"
                ),
                accent_colour=PURPLE,
            )
        )


class ThrowbackChannelSelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        owner_view: "ThrowbackConfigView",
    ):
        super().__init__(
            placeholder="Kies het throwback-kanaal...",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
            ],
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self.owner_view.check(interaction):
            return

        channel = self.values[0]

        await self.owner_view.cog.update_config_values(
            self.owner_view.guild_id,
            throwback_channel_id=channel.id,
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await ThrowbackConfigView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice=(
                    f"Throwback-kanaal ingesteld op <#{channel.id}>."
                ),
            ),
        )


class ThrowbackConfigButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "ThrowbackConfigView",
        action: str,
        label: str,
        *,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ):
        super().__init__(
            label=label,
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


class ThrowbackConfigView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Stats",
        owner_id: int,
        guild_id: int,
        body: str,
        *,
        enabled: bool,
        notice: str | None = None,
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.enabled = enabled

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(body)
        ]

        if notice:
            children.append(
                discord.ui.TextDisplay(
                    f"> └ {SUCCESS_EMOJI} {notice}"
                )
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ThrowbackChannelSelect(self)
                ),
                discord.ui.ActionRow(
                    ThrowbackConfigButton(
                        self,
                        "toggle",
                        (
                            "Automatisch uit"
                            if enabled
                            else "Automatisch aan"
                        ),
                        style=(
                            discord.ButtonStyle.danger
                            if enabled
                            else discord.ButtonStyle.success
                        ),
                    ),
                    ThrowbackConfigButton(
                        self,
                        "preview",
                        "Preview vorige maand",
                        style=discord.ButtonStyle.primary,
                    ),
                    ThrowbackConfigButton(
                        self,
                        "post",
                        "Post vorige maand",
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# De automatische throwback wordt één keer geplaatst "
                    "nadat een nieuwe maand is begonnen."
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PURPLE,
            )
        )

    @classmethod
    async def create(
        cls,
        cog: "Stats",
        owner_id: int,
        guild_id: int,
        *,
        notice: str | None = None,
    ) -> "ThrowbackConfigView":
        config = await cog.get_config(guild_id)

        if config is None:
            body = (
                "# Monthly Throwback\n"
                "> └ Serverstats zijn nog niet ingesteld.\n\n"
                "## Instellen\n"
                "> └ Gebruik eerst `/stats setup`."
            )
            enabled = False
        else:
            enabled = bool(config["throwback_enabled"])
            channel_id = config["throwback_channel_id"]

            body = (
                "# Monthly Throwback\n"
                "> └ Eén overzicht van de volledige afgelopen maand.\n\n"
                "## Instellingen\n"
                f"> └ Automatisch: **{'Aan' if enabled else 'Uit'}**\n"
                f"> └ Kanaal: "
                f"{f'<#{channel_id}>' if channel_id else '**niet ingesteld**'}\n"
                f"> └ Volgende maand: **{month_display_name(previous_month_key(datetime.now(TIMEZONE) + timedelta(days=32)))}**"
            )

        return cls(
            cog,
            owner_id,
            guild_id,
            body,
            enabled=enabled,
            notice=notice,
        )

    async def check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id == self.owner_id
            and isinstance(
                interaction.user,
                discord.Member,
            )
            and management_access(
                interaction.user
            )
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Geen toegang",
            ["Dit throwback-menu is niet van jou."],
            kind="error",
        )
        return False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return await self.check(interaction)

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if not await self.check(interaction):
            return

        guild = interaction.guild
        if guild is None:
            return

        if action == "toggle":
            await self.cog.update_config_values(
                self.guild_id,
                throwback_enabled=not self.enabled,
            )

            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await ThrowbackConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    notice=(
                        "Automatische throwbacks ingeschakeld."
                        if not self.enabled
                        else "Automatische throwbacks uitgeschakeld."
                    ),
                ),
            )
            return

        month_key = previous_month_key()

        if action == "preview":
            view = await self.cog.build_monthly_throwback_view(
                guild,
                month_key,
            )

            if view is None:
                await self.cog.send_feedback(
                    interaction,
                    "Nog geen maanddata",
                    [
                        "Er is voor de vorige maand nog geen "
                        "berichten- of voicedata beschikbaar."
                    ],
                    kind="warning",
                )
                return

            await interaction.response.send_message(
                view=view,
                ephemeral=True,
            )
            return

        if action == "post":
            ok, message = await self.cog.post_monthly_throwback(
                guild,
                month_key,
                automatic=False,
            )

            await self.cog.send_feedback(
                interaction,
                (
                    "Throwback geplaatst"
                    if ok
                    else "Throwback niet geplaatst"
                ),
                [message],
                kind="success" if ok else "warning",
            )


# ============================================================
# STATS COG
# ============================================================

class Stats(commands.Cog):
    stats = app_commands.Group(
        name="stats",
        description="Beheer de server statistieken",
    )

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db_lock = asyncio.Lock()
        self.ready_guilds: set[int] = set()

    # ========================================================
    # LOAD / UNLOAD
    # ========================================================

    async def cog_load(self):
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Stats vereist discord.py 2.6+ voor Components V2."
            )

        await initialise_stats_database()

        if not self.member_update_loop.is_running():
            self.member_update_loop.start()

        if not self.calendar_update_loop.is_running():
            self.calendar_update_loop.start()

        if not self.rotation_loop.is_running():
            self.rotation_loop.start()

        if not self.monthly_throwback_loop.is_running():
            self.monthly_throwback_loop.start()

        logger.info("Stats-module geladen.")

    def cog_unload(self):
        if self.member_update_loop.is_running():
            self.member_update_loop.cancel()

        if self.calendar_update_loop.is_running():
            self.calendar_update_loop.cancel()

        if self.rotation_loop.is_running():
            self.rotation_loop.cancel()

        if self.monthly_throwback_loop.is_running():
            self.monthly_throwback_loop.cancel()

    # ========================================================
    # FEEDBACK / VALIDATION
    # ========================================================

    async def send_feedback(
        self,
        interaction: discord.Interaction,
        title: str,
        lines: list[str],
        *,
        kind: str = "info",
        footer: str | None = None,
    ):
        view = StatsFeedbackView(
            title,
            lines,
            kind=kind,
            footer=footer,
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

    async def validate_management(
        self,
        interaction: discord.Interaction,
    ) -> discord.Guild | None:
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
        ):
            await self.send_feedback(
                interaction,
                "Niet beschikbaar",
                ["Dit command werkt alleen in een server."],
                kind="error",
            )
            return None

        if not management_access(interaction.user):
            await self.send_feedback(
                interaction,
                "Geen toegang",
                ["Alleen een admin of owner kan serverstats beheren."],
                kind="error",
            )
            return None

        return interaction.guild

    def bot_can_manage_channels(
        self,
        guild: discord.Guild,
    ) -> bool:
        bot_member = guild.me

        return (
            bot_member is not None
            and bot_member.guild_permissions.manage_channels
        )

    # ========================================================
    # CONFIG
    # ========================================================

    async def get_config(
        self,
        guild_id: int,
    ):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT
                    category_id,
                    date_channel_id,
                    members_channel_id,
                    rotating_channel_id,
                    birthday_channel_id,
                    rotation_index,
                    throwback_channel_id,
                    throwback_enabled
                FROM stats_config
                WHERE guild_id = ?
                """,
                (guild_id,),
            )

            row = await cursor.fetchone()

        if not row:
            return None

        return {
            "category_id": int(row[0]),
            "date_channel_id": int(row[1] or 0),
            "members_channel_id": int(row[2]),
            "rotating_channel_id": int(row[3]),
            "birthday_channel_id": int(row[4] or 0),
            "rotation_index": int(row[5]),
            "throwback_channel_id": int(row[6] or 0),
            "throwback_enabled": bool(row[7]),
        }

    async def save_config(
        self,
        guild_id: int,
        category_id: int,
        date_channel_id: int,
        members_channel_id: int,
        rotating_channel_id: int,
        *,
        birthday_channel_id: int = 0,
        rotation_index: int = 0,
    ):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO stats_config (
                    guild_id,
                    category_id,
                    date_channel_id,
                    members_channel_id,
                    rotating_channel_id,
                    birthday_channel_id,
                    rotation_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    category_id = excluded.category_id,
                    date_channel_id = excluded.date_channel_id,
                    members_channel_id = excluded.members_channel_id,
                    rotating_channel_id = excluded.rotating_channel_id,
                    birthday_channel_id = excluded.birthday_channel_id,
                    rotation_index = excluded.rotation_index
                """,
                (
                    guild_id,
                    category_id,
                    date_channel_id,
                    members_channel_id,
                    rotating_channel_id,
                    birthday_channel_id,
                    rotation_index,
                ),
            )
            await db.commit()

    async def update_config_values(
        self,
        guild_id: int,
        **values: int,
    ) -> None:
        allowed = {
            "date_channel_id",
            "birthday_channel_id",
            "rotation_index",
            "throwback_channel_id",
            "throwback_enabled",
        }

        clean = {
            key: int(value)
            for key, value in values.items()
            if key in allowed
        }

        if not clean:
            return

        assignments = ", ".join(
            f"{key} = ?"
            for key in clean
        )

        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                f"""
                UPDATE stats_config
                SET {assignments}
                WHERE guild_id = ?
                """,
                (*clean.values(), guild_id),
            )
            await db.commit()

    async def ensure_stats_structure(
        self,
        guild: discord.Guild,
    ) -> tuple[
        discord.CategoryChannel,
        discord.VoiceChannel,
        discord.VoiceChannel,
        discord.VoiceChannel,
        bool,
    ]:
        """
        Hergebruik bestaande onderdelen waar mogelijk.

        De datumstat is weer een vaste stat. Een eventueel bestaand oud
        datumkanaal wordt hergebruikt zodat /stats setup geen duplicaat maakt.
        """
        config = await self.get_config(guild.id)

        category = None
        date_channel = None
        members_channel = None
        rotating_channel = None
        birthday_channel_id = 0
        rotation_index = 0

        if config:
            category_candidate = guild.get_channel(
                config["category_id"]
            )
            date_candidate = guild.get_channel(
                config["date_channel_id"]
            )
            members_candidate = guild.get_channel(
                config["members_channel_id"]
            )
            rotating_candidate = guild.get_channel(
                config["rotating_channel_id"]
            )

            if isinstance(
                category_candidate,
                discord.CategoryChannel,
            ):
                category = category_candidate

            if isinstance(
                date_candidate,
                discord.VoiceChannel,
            ):
                date_channel = date_candidate

            if isinstance(
                members_candidate,
                discord.VoiceChannel,
            ):
                members_channel = members_candidate

            if isinstance(
                rotating_candidate,
                discord.VoiceChannel,
            ):
                rotating_channel = rotating_candidate

            birthday_channel_id = max(
                0,
                int(config["birthday_channel_id"]),
            )
            rotation_index = max(
                0,
                int(config["rotation_index"]),
            )

        created_any = False

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
            )
        }

        if category is None:
            category = await guild.create_category(
                STATS_CATEGORY_NAME,
                overwrites=overwrites,
                reason="LEVENLOOS serverstats setup",
            )
            created_any = True

        # Oude datumstat herkennen als de ID eerder niet meer in stats_config stond.
        if date_channel is None:
            date_channel = next(
                (
                    channel
                    for channel in category.voice_channels
                    if (
                        channel.name.startswith("▏📅")
                        or channel.name.startswith("📅")
                    )
                ),
                None,
            )

        if date_channel is None:
            date_channel = await guild.create_voice_channel(
                format_date_channel_name(),
                category=category,
                overwrites=overwrites,
                reason="LEVENLOOS datumstat setup",
            )
            created_any = True
        elif date_channel.category_id != category.id:
            await date_channel.edit(
                category=category,
                reason="LEVENLOOS datumstat herstellen",
            )

        if members_channel is None:
            members_channel = await guild.create_voice_channel(
                (
                    f"▏👥 Leden: "
                    f"{format_number(guild.member_count or 0)}"
                ),
                category=category,
                overwrites=overwrites,
                reason="LEVENLOOS serverstats setup",
            )
            created_any = True
        elif members_channel.category_id != category.id:
            await members_channel.edit(
                category=category,
                reason="LEVENLOOS serverstats herstellen",
            )

        if rotating_channel is None:
            rotating_channel = await guild.create_voice_channel(
                "▏📊 Stats worden geladen...",
                category=category,
                overwrites=overwrites,
                reason="LEVENLOOS serverstats setup",
            )
            created_any = True
        elif rotating_channel.category_id != category.id:
            await rotating_channel.edit(
                category=category,
                reason="LEVENLOOS serverstats herstellen",
            )

        await self.save_config(
            guild.id,
            category.id,
            date_channel.id,
            members_channel.id,
            rotating_channel.id,
            birthday_channel_id=birthday_channel_id,
            rotation_index=rotation_index,
        )

        return (
            category,
            date_channel,
            members_channel,
            rotating_channel,
            created_any,
        )

    # ========================================================
    # /STATS SETUP
    # ========================================================

    @stats.command(
        name="setup",
        description="Maak of herstel de serverstats-kanalen",
    )
    async def stats_setup(
        self,
        interaction: discord.Interaction,
    ):
        guild = await self.validate_management(interaction)

        if guild is None:
            return

        if not self.bot_can_manage_channels(guild):
            await self.send_feedback(
                interaction,
                "Ontbrekende permissie",
                [
                    "Mijn botrol heeft **Kanalen beheren** nodig "
                    "om de serverstats in te stellen."
                ],
                kind="error",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            (
                category,
                date_channel,
                members_channel,
                rotating_channel,
                created_any,
            ) = await self.ensure_stats_structure(guild)

            await asyncio.gather(
                self.update_date_channel(guild),
                self.update_members_channel(guild),
                self.update_birthday_channel(guild),
            )
            await self.update_rotating_channel(
                guild,
                force_current=True,
            )
        except discord.Forbidden:
            await self.send_feedback(
                interaction,
                "Setup mislukt",
                [
                    "Ik heb niet genoeg Discord-permissies "
                    "om de serverstats aan te maken of te herstellen."
                ],
                kind="error",
            )
            return
        except discord.HTTPException:
            logger.exception(
                "Discord-fout tijdens stats setup in guild %s.",
                guild.id,
            )
            await self.send_feedback(
                interaction,
                "Setup mislukt",
                [
                    "Discord kon de serverstats momenteel niet "
                    "aanmaken of herstellen."
                ],
                kind="error",
            )
            return
        except Exception:
            logger.exception(
                "Onverwachte fout tijdens stats setup in guild %s.",
                guild.id,
            )
            await self.send_feedback(
                interaction,
                "Setup mislukt",
                [
                    "Er ging intern iets mis. "
                    "De technische fout staat in de botlog."
                ],
                kind="error",
            )
            return

        await self.send_feedback(
            interaction,
            (
                "Serverstats aangemaakt"
                if created_any
                else "Serverstats bijgewerkt"
            ),
            [
                f"Categorie: **{category.name}**",
                f"Datum: {date_channel.mention}",
                f"Leden: {members_channel.mention}",
                f"Rotatie: {rotating_channel.mention}",
                "Verjaardagsstat verschijnt automatisch wanneer iemand jarig is.",
            ],
            kind="success",
            footer=(
                f"Vaste stats elke {CALENDAR_UPDATE_MINUTES} min gecontroleerd • "
                f"rotatie elke {ROTATION_MINUTES} min"
            ),
        )

    # ========================================================
    # /STATS UPDATE
    # ========================================================

    @stats.command(
        name="update",
        description="Werk alle serverstats direct bij",
    )
    async def stats_update(
        self,
        interaction: discord.Interaction,
    ):
        guild = await self.validate_management(interaction)

        if guild is None:
            return

        if not self.bot_can_manage_channels(guild):
            await self.send_feedback(
                interaction,
                "Ontbrekende permissie",
                [
                    "Mijn botrol heeft **Kanalen beheren** nodig "
                    "om de serverstats bij te werken."
                ],
                kind="error",
            )
            return

        if not await self.get_config(guild.id):
            await self.send_feedback(
                interaction,
                "Serverstats niet ingesteld",
                ["Gebruik eerst `/stats setup`."],
                kind="warning",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            await asyncio.gather(
                self.update_date_channel(guild),
                self.update_members_channel(guild),
                self.update_birthday_channel(guild),
            )
            await self.update_rotating_channel(
                guild,
                force_current=True,
            )
        except Exception:
            logger.exception(
                "Handmatige stats update mislukt in guild %s.",
                guild.id,
            )
            await self.send_feedback(
                interaction,
                "Bijwerken mislukt",
                [
                    "De serverstats konden niet volledig worden bijgewerkt. "
                    "Controleer de botlog."
                ],
                kind="error",
            )
            return

        await self.send_feedback(
            interaction,
            "Serverstats bijgewerkt",
            [
                "Datum, ledenaantal, verjaardag en huidige rotatiestat "
                "zijn gecontroleerd."
            ],
            kind="success",
        )

    # ========================================================
    # /STATS NEXT
    # ========================================================

    @stats.command(
        name="next",
        description="Toon direct de volgende roterende serverstat",
    )
    async def stats_next(
        self,
        interaction: discord.Interaction,
    ):
        guild = await self.validate_management(interaction)
        if guild is None:
            return

        config = await self.get_config(guild.id)
        if not config:
            await self.send_feedback(
                interaction,
                "Serverstats niet ingesteld",
                ["Gebruik eerst `/stats setup`."],
                kind="warning",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        ok = await self.update_rotating_channel(
            guild,
            force_current=False,
        )

        channel = guild.get_channel(
            config["rotating_channel_id"]
        )
        current = (
            channel.name
            if isinstance(channel, discord.VoiceChannel)
            else "onbekend"
        )

        await self.send_feedback(
            interaction,
            "Volgende stat",
            [
                (
                    f"Rotatie staat nu op **{current}**."
                    if ok
                    else "De rotatiestat kon niet worden bijgewerkt."
                )
            ],
            kind="success" if ok else "error",
        )

    # ========================================================
    # /STATS STATUS
    # ========================================================

    @stats.command(
        name="status",
        description="Controleer de serverstats-kanalen en achtergrondtaken",
    )
    async def stats_status(
        self,
        interaction: discord.Interaction,
    ):
        guild = await self.validate_management(interaction)
        if guild is None:
            return

        config = await self.get_config(guild.id)
        if not config:
            await self.send_feedback(
                interaction,
                "Serverstats niet ingesteld",
                ["Gebruik `/stats setup` om de structuur aan te maken."],
                kind="warning",
            )
            return

        category = guild.get_channel(config["category_id"])
        date_channel = guild.get_channel(config["date_channel_id"])
        members_channel = guild.get_channel(config["members_channel_id"])
        rotating_channel = guild.get_channel(config["rotating_channel_id"])
        birthday_channel = guild.get_channel(config["birthday_channel_id"])

        def status_line(
            label: str,
            channel: discord.abc.GuildChannel | None,
            expected_type: type,
        ) -> str:
            if isinstance(channel, expected_type):
                return f"{label}: **OK** — {channel.mention}"
            return f"{label}: **Ontbreekt / ongeldig**"

        sections = [
            (
                "Structuur",
                [
                    status_line("Categorie", category, discord.CategoryChannel),
                    status_line("Datum", date_channel, discord.VoiceChannel),
                    status_line("Leden", members_channel, discord.VoiceChannel),
                    status_line("Rotatie", rotating_channel, discord.VoiceChannel),
                    (
                        f"Verjaardag: **actief** — {birthday_channel.mention}"
                        if isinstance(birthday_channel, discord.VoiceChannel)
                        else "Verjaardag: niet actief vandaag"
                    ),
                    (
                        f"Throwback-kanaal: <#{config['throwback_channel_id']}>"
                        if config["throwback_channel_id"]
                        else "Throwback-kanaal: **niet ingesteld**"
                    ),
                ],
            ),
            (
                "Automatisch",
                [
                    (
                        "Leden-loop: **actief**"
                        if self.member_update_loop.is_running()
                        else "Leden-loop: **gestopt**"
                    ),
                    (
                        "Datum/verjaardag-loop: **actief**"
                        if self.calendar_update_loop.is_running()
                        else "Datum/verjaardag-loop: **gestopt**"
                    ),
                    (
                        "Rotatie-loop: **actief**"
                        if self.rotation_loop.is_running()
                        else "Rotatie-loop: **gestopt**"
                    ),
                    (
                        "Throwback-loop: **actief**"
                        if self.monthly_throwback_loop.is_running()
                        else "Throwback-loop: **gestopt**"
                    ),
                    (
                        "Automatische throwback: **Aan**"
                        if config["throwback_enabled"]
                        else "Automatische throwback: **Uit**"
                    ),
                    f"Rotatie-index: `{config['rotation_index']}`",
                    (
                        "Birthdays database: **beschikbaar**"
                        if BIRTHDAY_DATABASE_PATH.exists()
                        else "Birthdays database: **niet gevonden**"
                    ),
                ],
            ),
        ]

        await interaction.response.send_message(
            view=StatsDetailView(
                "Serverstats status",
                sections,
                footer=(
                    "Gebruik /stats setup om ontbrekende vaste kanalen te herstellen "
                    "of /stats update om alles direct te verversen."
                ),
            ),
            ephemeral=True,
        )

    # ========================================================
    # /STATS OVERZICHT
    # ========================================================

    @stats.command(
        name="overzicht",
        description="Bekijk alle actuele serverstats in één overzicht",
    )
    async def stats_overview(
        self,
        interaction: discord.Interaction,
    ):
        guild = await self.validate_management(interaction)
        if guild is None:
            return

        config = await self.get_config(guild.id)
        if not config:
            await self.send_feedback(
                interaction,
                "Serverstats niet ingesteld",
                ["Gebruik eerst `/stats setup`."],
                kind="warning",
            )
            return

        (
            active_games,
            week_messages,
            top_game_result,
            voice_totals,
            birthdays,
        ) = await asyncio.gather(
            self.get_active_games_count(guild),
            self.get_week_messages(guild),
            self.get_top_game(guild),
            self.get_voice_totals(guild),
            self.get_today_birthdays(guild),
        )

        top_game, top_game_messages = top_game_result
        top_player, _ = await self.get_top_player(
            guild,
            voice_totals=voice_totals,
        )

        top_player_messages = 0
        top_player_voice = 0
        if top_player is not None:
            top_player_messages = await self.get_week_user_messages(
                guild,
                top_player.id,
            )
            top_player_voice = voice_totals.get(
                top_player.id,
                0,
            )

        sections = [
            (
                "Vandaag",
                [
                    f"Datum: **{format_date_channel_name().removeprefix('▏📅 ')}**",
                    (
                        "Jarig: **"
                        + ", ".join(
                            member.display_name
                            for member in birthdays
                        )
                        + "**"
                        if birthdays
                        else "Jarig: **niemand geregistreerd**"
                    ),
                ],
            ),
            (
                "Server",
                [
                    f"Leden: **{format_number(guild.member_count or 0)}**",
                    f"Boosts: **{format_number(guild.premium_subscription_count or 0)}**",
                    f"Actieve games: **{format_number(active_games)}**",
                ],
            ),
            (
                "Deze week",
                [
                    f"Berichten: **{format_number(week_messages)}**",
                    f"Voice: **{format_voice_hours(sum(voice_totals.values()))}**",
                    (
                        f"#1 game: **{game_channel_display_name(top_game)}** "
                        f"• {format_number(top_game_messages)} berichten"
                        if top_game
                        else "#1 game: **nog geen data**"
                    ),
                    (
                        f"Actiefste: **{top_player.display_name}** "
                        f"• {format_number(top_player_messages)} berichten "
                        f"+ {format_voice_hours(top_player_voice)} voice"
                        if top_player
                        else "Actiefste: **nog geen data**"
                    ),
                ],
            ),
        ]

        await interaction.response.send_message(
            view=StatsDetailView(
                "Serverstats overzicht",
                sections,
                footer=(
                    f"Week vanaf {get_week_start()} • "
                    f"rotatie iedere {ROTATION_MINUTES} minuten"
                ),
            ),
            ephemeral=True,
        )

    # ========================================================
    # /STATS THROWBACK
    # ========================================================

    @stats.command(
        name="throwback",
        description="Bekijk de monthly throwback van de vorige maand",
    )
    async def stats_throwback(
        self,
        interaction: discord.Interaction,
    ):
        guild = await self.validate_management(interaction)
        if guild is None:
            return

        month_key = previous_month_key()

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        view = await self.build_monthly_throwback_view(
            guild,
            month_key,
        )

        if view is None:
            await self.send_feedback(
                interaction,
                "Nog geen maanddata",
                [
                    "Er is voor de vorige maand nog geen "
                    "berichten- of voicedata beschikbaar."
                ],
                kind="warning",
                footer=(
                    "Exacte maandtracking start vanaf het moment "
                    "dat deze versie van stats.py draait."
                ),
            )
            return

        await interaction.followup.send(
            view=view,
            ephemeral=True,
        )

    # ========================================================
    # /STATS THROWBACK-CONFIG
    # ========================================================

    @stats.command(
        name="throwback-config",
        description="Stel de automatische monthly throwback in",
    )
    async def stats_throwback_config(
        self,
        interaction: discord.Interaction,
    ):
        guild = await self.validate_management(interaction)
        if guild is None:
            return

        config = await self.get_config(guild.id)
        if config is None:
            await self.send_feedback(
                interaction,
                "Serverstats niet ingesteld",
                ["Gebruik eerst `/stats setup`."],
                kind="warning",
            )
            return

        await interaction.response.send_message(
            view=await ThrowbackConfigView.create(
                self,
                interaction.user.id,
                guild.id,
            ),
            ephemeral=True,
        )

    # ========================================================
    # MESSAGE TRACKING
    # ========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ):
        if (
            message.guild is None
            or message.author.bot
        ):
            return

        week = get_week_start()
        month_key = get_month_key()

        async with self.db_lock:
            try:
                async with aiosqlite.connect(
                    DATABASE_PATH
                ) as db:
                    await db.execute(
                        "PRAGMA busy_timeout=5000"
                    )

                    await db.execute(
                        """
                        INSERT INTO stats_weekly_users (
                            guild_id,
                            week_start,
                            user_id,
                            messages,
                            voice_seconds
                        )
                        VALUES (?, ?, ?, 1, 0)
                        ON CONFLICT(
                            guild_id,
                            week_start,
                            user_id
                        )
                        DO UPDATE SET
                            messages = messages + 1
                        """,
                        (
                            message.guild.id,
                            week,
                            message.author.id,
                        ),
                    )

                    await db.execute(
                        """
                        INSERT INTO stats_monthly_users (
                            guild_id,
                            month_key,
                            user_id,
                            messages,
                            voice_seconds
                        )
                        VALUES (?, ?, ?, 1, 0)
                        ON CONFLICT(
                            guild_id,
                            month_key,
                            user_id
                        )
                        DO UPDATE SET
                            messages = messages + 1
                        """,
                        (
                            message.guild.id,
                            month_key,
                            message.author.id,
                        ),
                    )

                    if (
                        isinstance(
                            message.channel,
                            discord.TextChannel,
                        )
                        and message.channel.category_id
                        == ACTIVE_GAME_CATEGORY_ID
                        and message.channel.id
                        != GAME_PROPOSAL_CHANNEL_ID
                    ):
                        await db.execute(
                            """
                            INSERT INTO stats_weekly_games (
                                guild_id,
                                week_start,
                                channel_id,
                                messages
                            )
                            VALUES (?, ?, ?, 1)
                            ON CONFLICT(
                                guild_id,
                                week_start,
                                channel_id
                            )
                            DO UPDATE SET
                                messages = messages + 1
                            """,
                            (
                                message.guild.id,
                                week,
                                message.channel.id,
                            ),
                        )

                        await db.execute(
                            """
                            INSERT INTO stats_monthly_games (
                                guild_id,
                                month_key,
                                channel_id,
                                messages
                            )
                            VALUES (?, ?, ?, 1)
                            ON CONFLICT(
                                guild_id,
                                month_key,
                                channel_id
                            )
                            DO UPDATE SET
                                messages = messages + 1
                            """,
                            (
                                message.guild.id,
                                month_key,
                                message.channel.id,
                            ),
                        )

                    await db.commit()

            except aiosqlite.Error:
                logger.exception(
                    "Berichtstatistiek opslaan mislukt "
                    "in guild %s.",
                    message.guild.id,
                )

    # ========================================================
    # VOICE TRACKING
    # ========================================================

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        guild = member.guild

        if (
            before.channel is None
            and after.channel is not None
        ):
            await self.start_voice_session(
                guild.id,
                member.id,
                after.channel.id,
                preserve_existing=False,
            )
            return

        if (
            before.channel is not None
            and after.channel is None
        ):
            await self.finish_voice_session(
                guild.id,
                member.id,
            )
            return

        if (
            before.channel is not None
            and after.channel is not None
            and before.channel.id != after.channel.id
        ):
            # UPSERT in plaats van een kale UPDATE: als een eerdere join-event
            # gemist is, wordt de sessie alsnog correct aangemaakt.
            await self.start_voice_session(
                guild.id,
                member.id,
                after.channel.id,
                preserve_existing=True,
            )

    async def start_voice_session(
        self,
        guild_id: int,
        user_id: int,
        channel_id: int,
        *,
        preserve_existing: bool = False,
    ):
        started_at = time.time()

        async with self.db_lock:
            try:
                async with aiosqlite.connect(
                    DATABASE_PATH
                ) as db:
                    if preserve_existing:
                        await db.execute(
                            """
                            INSERT INTO stats_voice_sessions (
                                guild_id,
                                user_id,
                                channel_id,
                                started_at
                            )
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(
                                guild_id,
                                user_id
                            )
                            DO UPDATE SET
                                channel_id = excluded.channel_id
                            """,
                            (
                                guild_id,
                                user_id,
                                channel_id,
                                started_at,
                            ),
                        )
                    else:
                        await db.execute(
                            """
                            INSERT INTO stats_voice_sessions (
                                guild_id,
                                user_id,
                                channel_id,
                                started_at
                            )
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(
                                guild_id,
                                user_id
                            )
                            DO UPDATE SET
                                channel_id = excluded.channel_id,
                                started_at = excluded.started_at
                            """,
                            (
                                guild_id,
                                user_id,
                                channel_id,
                                started_at,
                            ),
                        )

                    await db.commit()

            except aiosqlite.Error:
                logger.exception(
                    "Voice-sessie starten mislukt "
                    "voor user %s in guild %s.",
                    user_id,
                    guild_id,
                )

    async def finish_voice_session(
        self,
        guild_id: int,
        user_id: int,
    ):
        started_at = None
        ended_at = time.time()

        async with self.db_lock:
            try:
                async with aiosqlite.connect(
                    DATABASE_PATH
                ) as db:
                    cursor = await db.execute(
                        """
                        SELECT started_at
                        FROM stats_voice_sessions
                        WHERE guild_id = ?
                          AND user_id = ?
                        """,
                        (
                            guild_id,
                            user_id,
                        ),
                    )

                    row = await cursor.fetchone()

                    if row is None:
                        return

                    started_at = float(row[0])

                    await db.execute(
                        """
                        DELETE FROM stats_voice_sessions
                        WHERE guild_id = ?
                          AND user_id = ?
                        """,
                        (
                            guild_id,
                            user_id,
                        ),
                    )

                    await db.commit()

            except aiosqlite.Error:
                logger.exception(
                    "Voice-sessie afsluiten mislukt "
                    "voor user %s in guild %s.",
                    user_id,
                    guild_id,
                )
                return

        if started_at is not None:
            await self.add_voice_duration(
                guild_id,
                user_id,
                started_at,
                ended_at,
            )
            await self.add_monthly_voice_duration(
                guild_id,
                user_id,
                started_at,
                ended_at,
            )

    async def add_voice_duration(
        self,
        guild_id: int,
        user_id: int,
        started_at: float,
        ended_at: float,
    ):
        if ended_at <= started_at:
            return

        cursor_time = started_at

        while cursor_time < ended_at:
            local_start = datetime.fromtimestamp(
                cursor_time,
                TIMEZONE,
            )

            week = get_week_start(
                local_start
            )

            monday = (
                local_start
                - timedelta(
                    days=local_start.weekday()
                )
            ).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

            next_monday = monday + timedelta(days=7)

            chunk_end = min(
                ended_at,
                next_monday.timestamp(),
            )

            seconds = int(
                chunk_end - cursor_time
            )

            if seconds > 0:
                try:
                    async with aiosqlite.connect(
                        DATABASE_PATH
                    ) as db:
                        await db.execute(
                            """
                            INSERT INTO stats_weekly_users (
                                guild_id,
                                week_start,
                                user_id,
                                messages,
                                voice_seconds
                            )
                            VALUES (?, ?, ?, 0, ?)
                            ON CONFLICT(
                                guild_id,
                                week_start,
                                user_id
                            )
                            DO UPDATE SET
                                voice_seconds =
                                voice_seconds + excluded.voice_seconds
                            """,
                            (
                                guild_id,
                                week,
                                user_id,
                                seconds,
                            ),
                        )

                        await db.commit()

                except aiosqlite.Error:
                    logger.exception(
                        "Voice-duur opslaan mislukt "
                        "voor user %s in guild %s.",
                        user_id,
                        guild_id,
                    )
                    return

            cursor_time = chunk_end

    async def add_monthly_voice_duration(
        self,
        guild_id: int,
        user_id: int,
        started_at: float,
        ended_at: float,
    ) -> None:
        if ended_at <= started_at:
            return

        cursor_time = started_at

        while cursor_time < ended_at:
            local_start = datetime.fromtimestamp(
                cursor_time,
                TIMEZONE,
            )
            month_key = get_month_key(local_start)
            _, next_month = month_bounds(month_key)

            chunk_end = min(
                ended_at,
                next_month.timestamp(),
            )

            seconds = max(
                0,
                int(chunk_end - cursor_time),
            )

            if seconds > 0:
                try:
                    async with aiosqlite.connect(
                        DATABASE_PATH
                    ) as db:
                        await db.execute(
                            """
                            INSERT INTO stats_monthly_users (
                                guild_id,
                                month_key,
                                user_id,
                                messages,
                                voice_seconds
                            )
                            VALUES (?, ?, ?, 0, ?)
                            ON CONFLICT(
                                guild_id,
                                month_key,
                                user_id
                            )
                            DO UPDATE SET
                                voice_seconds =
                                voice_seconds + excluded.voice_seconds
                            """,
                            (
                                guild_id,
                                month_key,
                                user_id,
                                seconds,
                            ),
                        )
                        await db.commit()
                except aiosqlite.Error:
                    logger.exception(
                        "Maandelijkse voice-duur opslaan mislukt "
                        "voor user %s in guild %s.",
                        user_id,
                        guild_id,
                    )
                    return

            cursor_time = chunk_end

    # ========================================================
    # BOT READY / VOICE RECONCILIATION
    # ========================================================

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            if guild.id in self.ready_guilds:
                continue

            try:
                await self.ensure_monthly_tracking_started(
                    guild.id
                )
                await self.reconcile_voice_sessions(guild)

                if await self.get_config(guild.id):
                    await asyncio.gather(
                        self.update_date_channel(guild),
                        self.update_members_channel(guild),
                        self.update_birthday_channel(guild),
                    )
                    await self.update_rotating_channel(
                        guild,
                        force_current=True,
                    )
            except Exception:
                logger.exception(
                    "Stats startupcontrole mislukt voor guild %s.",
                    guild.id,
                )
                continue

            self.ready_guilds.add(guild.id)

    async def reconcile_voice_sessions(
        self,
        guild: discord.Guild,
    ):
        currently_connected: dict[int, int] = {}

        for channel in guild.voice_channels:
            for member in channel.members:
                if member.bot:
                    continue

                currently_connected[
                    member.id
                ] = channel.id

        now = time.time()

        async with self.db_lock:
            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                cursor = await db.execute(
                    """
                    SELECT user_id
                    FROM stats_voice_sessions
                    WHERE guild_id = ?
                    """,
                    (guild.id,),
                )

                rows = await cursor.fetchall()

                stored_ids = {
                    int(row[0])
                    for row in rows
                }

                stale_ids = (
                    stored_ids
                    - set(currently_connected)
                )

                if stale_ids:
                    await db.executemany(
                        """
                        DELETE FROM stats_voice_sessions
                        WHERE guild_id = ?
                          AND user_id = ?
                        """,
                        [
                            (
                                guild.id,
                                user_id,
                            )
                            for user_id in stale_ids
                        ],
                    )

                # Bestaande starttijden blijven behouden. Dit voorkomt dat
                # een botrestart de lopende voice-tijd opnieuw vanaf nul telt.
                for user_id, channel_id in (
                    currently_connected.items()
                ):
                    await db.execute(
                        """
                        INSERT INTO stats_voice_sessions (
                            guild_id,
                            user_id,
                            channel_id,
                            started_at
                        )
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(
                            guild_id,
                            user_id
                        )
                        DO UPDATE SET
                            channel_id = excluded.channel_id
                        """,
                        (
                            guild.id,
                            user_id,
                            channel_id,
                            now,
                        ),
                    )

                await db.commit()

        logger.info(
            "Voice-sessies gecontroleerd voor guild %s.",
            guild.id,
        )

    # ========================================================
    # DATE / BIRTHDAY DATA
    # ========================================================

    async def get_today_birthdays(
        self,
        guild: discord.Guild,
    ) -> list[discord.Member]:
        if not BIRTHDAY_DATABASE_PATH.exists():
            return []

        now = datetime.now(TIMEZONE)

        try:
            async with aiosqlite.connect(
                BIRTHDAY_DATABASE_PATH
            ) as db:
                cursor = await db.execute(
                    """
                    SELECT user_id
                    FROM birthdays
                    WHERE guild_id = ?
                      AND day = ?
                      AND month = ?
                    ORDER BY user_id ASC
                    """,
                    (
                        guild.id,
                        now.day,
                        now.month,
                    ),
                )
                rows = await cursor.fetchall()
        except aiosqlite.Error:
            logger.exception(
                "Verjaardagen uitlezen mislukt voor guild %s.",
                guild.id,
            )
            return []

        members = []
        for (user_id,) in rows:
            member = guild.get_member(int(user_id))
            if member is not None and not member.bot:
                members.append(member)

        members.sort(
            key=lambda member: member.display_name.casefold()
        )
        return members

    async def get_week_user_messages(
        self,
        guild: discord.Guild,
        user_id: int,
    ) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT messages
                FROM stats_weekly_users
                WHERE guild_id = ?
                  AND week_start = ?
                  AND user_id = ?
                """,
                (
                    guild.id,
                    get_week_start(),
                    user_id,
                ),
            )
            row = await cursor.fetchone()

        return int(row[0] or 0) if row else 0

    # ========================================================
    # MONTHLY THROWBACK DATA
    # ========================================================

    async def ensure_monthly_tracking_started(
        self,
        guild_id: int,
    ) -> float:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO stats_monthly_meta (
                    guild_id,
                    tracking_started_at
                )
                VALUES (?, ?)
                """,
                (
                    guild_id,
                    time.time(),
                ),
            )
            await db.commit()

            cursor = await db.execute(
                """
                SELECT tracking_started_at
                FROM stats_monthly_meta
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()

        return float(row[0])

    async def monthly_tracking_started_at(
        self,
        guild_id: int,
    ) -> float | None:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT tracking_started_at
                FROM stats_monthly_meta
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()

        return float(row[0]) if row else None

    async def get_month_birthdays(
        self,
        guild: discord.Guild,
        month_key: str,
    ) -> list[tuple[discord.Member, int]]:
        if not BIRTHDAY_DATABASE_PATH.exists():
            return []

        _, month = month_key_parts(month_key)

        try:
            async with aiosqlite.connect(
                BIRTHDAY_DATABASE_PATH
            ) as db:
                cursor = await db.execute(
                    """
                    SELECT user_id, day
                    FROM birthdays
                    WHERE guild_id = ?
                      AND month = ?
                    ORDER BY day ASC, user_id ASC
                    """,
                    (
                        guild.id,
                        month,
                    ),
                )
                rows = await cursor.fetchall()
        except aiosqlite.Error:
            logger.exception(
                "Maandverjaardagen uitlezen mislukt "
                "voor guild %s.",
                guild.id,
            )
            return []

        birthdays = []

        for user_id, day in rows:
            member = guild.get_member(
                int(user_id)
            )
            if (
                member is not None
                and not member.bot
            ):
                birthdays.append(
                    (
                        member,
                        int(day),
                    )
                )

        return birthdays

    async def get_month_congratulations(
        self,
        guild: discord.Guild,
        month_key: str,
    ) -> int:
        if not BIRTHDAY_DATABASE_PATH.exists():
            return 0

        month_start, month_end = month_bounds(
            month_key
        )

        try:
            async with aiosqlite.connect(
                BIRTHDAY_DATABASE_PATH
            ) as db:
                cursor = await db.execute(
                    """
                    SELECT COUNT(*)
                    FROM birthday_congrats
                    WHERE guild_id = ?
                      AND created_at >= ?
                      AND created_at < ?
                    """,
                    (
                        guild.id,
                        int(month_start.timestamp()),
                        int(month_end.timestamp()),
                    ),
                )
                row = await cursor.fetchone()
        except aiosqlite.Error:
            logger.exception(
                "Maandelijkse felicitaties uitlezen mislukt "
                "voor guild %s.",
                guild.id,
            )
            return 0

        return int(row[0] or 0)

    async def get_month_user_data(
        self,
        guild: discord.Guild,
        month_key: str,
    ) -> dict[int, dict[str, int]]:
        data: dict[int, dict[str, int]] = {}

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT
                    user_id,
                    messages,
                    voice_seconds
                FROM stats_monthly_users
                WHERE guild_id = ?
                  AND month_key = ?
                """,
                (
                    guild.id,
                    month_key,
                ),
            )
            rows = await cursor.fetchall()

            cursor = await db.execute(
                """
                SELECT
                    user_id,
                    started_at
                FROM stats_voice_sessions
                WHERE guild_id = ?
                """,
                (guild.id,),
            )
            active_rows = await cursor.fetchall()

        for user_id, messages, voice_seconds in rows:
            data[int(user_id)] = {
                "messages": int(messages or 0),
                "voice": int(voice_seconds or 0),
            }

        month_start, month_end = month_bounds(
            month_key
        )
        report_end = min(
            time.time(),
            month_end.timestamp(),
        )

        for user_id, started_at in active_rows:
            counted_from = max(
                float(started_at),
                month_start.timestamp(),
            )

            if report_end <= counted_from:
                continue

            user_id = int(user_id)
            seconds = int(
                report_end - counted_from
            )

            if user_id not in data:
                data[user_id] = {
                    "messages": 0,
                    "voice": 0,
                }

            data[user_id]["voice"] += seconds

        return data

    async def get_month_top_games(
        self,
        guild: discord.Guild,
        month_key: str,
    ) -> list[tuple[str, int]]:
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT
                    channel_id,
                    messages
                FROM stats_monthly_games
                WHERE guild_id = ?
                  AND month_key = ?
                ORDER BY
                    messages DESC,
                    channel_id ASC
                LIMIT 5
                """,
                (
                    guild.id,
                    month_key,
                ),
            )
            rows = await cursor.fetchall()

        result: list[tuple[str, int]] = []

        for channel_id, messages in rows:
            channel = guild.get_channel(
                int(channel_id)
            )

            if isinstance(
                channel,
                discord.TextChannel,
            ):
                name = game_channel_display_name(
                    channel
                )
            else:
                name = f"Verwijderd kanaal {channel_id}"

            result.append(
                (
                    name,
                    int(messages or 0),
                )
            )

        return result

    async def build_monthly_throwback_view(
        self,
        guild: discord.Guild,
        month_key: str,
    ) -> MonthlyThrowbackView | None:
        await self.ensure_monthly_tracking_started(
            guild.id
        )

        user_data = await self.get_month_user_data(
            guild,
            month_key,
        )

        valid_data: list[
            tuple[discord.Member, int, int]
        ] = []

        for user_id, values in user_data.items():
            member = guild.get_member(
                user_id
            )
            if (
                member is None
                or member.bot
            ):
                continue

            messages = int(
                values["messages"]
            )
            voice_seconds = int(
                values["voice"]
            )

            if messages <= 0 and voice_seconds <= 0:
                continue

            valid_data.append(
                (
                    member,
                    messages,
                    voice_seconds,
                )
            )

        total_messages = sum(
            item[1]
            for item in valid_data
        )
        total_voice_seconds = sum(
            item[2]
            for item in valid_data
        )

        if (
            total_messages <= 0
            and total_voice_seconds <= 0
        ):
            return None

        top_messages = sorted(
            (
                (member, messages)
                for member, messages, _
                in valid_data
                if messages > 0
            ),
            key=lambda item: (
                -item[1],
                item[0].display_name.casefold(),
            ),
        )[:5]

        top_voice = sorted(
            (
                (member, voice_seconds)
                for member, _, voice_seconds
                in valid_data
                if voice_seconds > 0
            ),
            key=lambda item: (
                -item[1],
                item[0].display_name.casefold(),
            ),
        )[:5]

        # Zelfde LEVENLOOS-logica als de weekscore:
        # 1 bericht = 1 punt, 1 minuut voice = 1 punt.
        top_overall = sorted(
            valid_data,
            key=lambda item: (
                -(
                    item[1]
                    + item[2] / 60
                ),
                item[0].display_name.casefold(),
            ),
        )[:5]

        (
            top_games,
            birthdays,
            congratulations,
            tracking_started_at,
        ) = await asyncio.gather(
            self.get_month_top_games(
                guild,
                month_key,
            ),
            self.get_month_birthdays(
                guild,
                month_key,
            ),
            self.get_month_congratulations(
                guild,
                month_key,
            ),
            self.monthly_tracking_started_at(
                guild.id
            ),
        )

        return MonthlyThrowbackView(
            month_key=month_key,
            total_messages=total_messages,
            total_voice_seconds=total_voice_seconds,
            active_members=len(valid_data),
            top_messages=top_messages,
            top_voice=top_voice,
            top_overall=top_overall,
            top_games=top_games,
            birthdays=birthdays,
            congratulations=congratulations,
            tracking_started_at=tracking_started_at,
        )

    async def throwback_already_posted(
        self,
        guild_id: int,
        month_key: str,
    ) -> bool:
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT 1
                FROM stats_monthly_throwbacks
                WHERE guild_id = ?
                  AND month_key = ?
                """,
                (
                    guild_id,
                    month_key,
                ),
            )
            row = await cursor.fetchone()

        return row is not None

    async def post_monthly_throwback(
        self,
        guild: discord.Guild,
        month_key: str,
        *,
        automatic: bool,
    ) -> tuple[bool, str]:
        config = await self.get_config(
            guild.id
        )

        if config is None:
            return False, "Serverstats zijn nog niet ingesteld."

        channel_id = int(
            config["throwback_channel_id"]
        )

        if not channel_id:
            return False, "Er is nog geen throwback-kanaal ingesteld."

        channel = guild.get_channel(
            channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return False, "Het ingestelde throwback-kanaal bestaat niet meer."

        if await self.throwback_already_posted(
            guild.id,
            month_key,
        ):
            return (
                False,
                f"De throwback van **{month_display_name(month_key)}** "
                "is al geplaatst.",
            )

        view = await self.build_monthly_throwback_view(
            guild,
            month_key,
        )

        if view is None:
            return (
                False,
                f"Er is nog geen maanddata voor **{month_display_name(month_key)}**.",
            )

        me = guild.me
        if (
            me is None
            or not channel.permissions_for(
                me
            ).send_messages
        ):
            return (
                False,
                f"Ik kan niet sturen in {channel.mention}.",
            )

        try:
            message = await channel.send(
                view=view,
                silent=automatic,
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Monthly throwback versturen mislukt "
                "voor guild %s.",
                guild.id,
            )
            return False, "Discord kon de throwback niet plaatsen."

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO stats_monthly_throwbacks (
                    guild_id,
                    month_key,
                    channel_id,
                    message_id,
                    posted_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    guild.id,
                    month_key,
                    channel.id,
                    message.id,
                    time.time(),
                ),
            )
            await db.commit()

        return (
            True,
            f"Throwback van **{month_display_name(month_key)}** "
            f"geplaatst in {channel.mention}.",
        )

    # ========================================================
    # WEEK DATA
    # ========================================================

    async def get_week_messages(
        self,
        guild: discord.Guild,
    ) -> int:
        week = get_week_start()

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT COALESCE(
                    SUM(messages),
                    0
                )
                FROM stats_weekly_users
                WHERE guild_id = ?
                  AND week_start = ?
                """,
                (
                    guild.id,
                    week,
                ),
            )

            row = await cursor.fetchone()

        return int(row[0] or 0)

    async def get_active_users_count(
        self,
        guild: discord.Guild,
    ) -> int:
        """
        Aantal leden met activiteit deze week.

        Lopende voice-sessies tellen direct mee, ook als die sessie nog niet
        is afgesloten en dus nog niet in stats_weekly_users staat.
        """
        week = get_week_start()

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT user_id
                FROM stats_weekly_users
                WHERE guild_id = ?
                  AND week_start = ?
                  AND (
                      messages > 0
                      OR voice_seconds > 0
                  )
                """,
                (
                    guild.id,
                    week,
                ),
            )

            weekly_rows = await cursor.fetchall()

            cursor = await db.execute(
                """
                SELECT user_id
                FROM stats_voice_sessions
                WHERE guild_id = ?
                """,
                (guild.id,),
            )

            active_voice_rows = await cursor.fetchall()

        ids = {
            int(row[0])
            for row in weekly_rows
        }
        ids.update(
            int(row[0])
            for row in active_voice_rows
        )

        return sum(
            1
            for user_id in ids
            if (
                (member := guild.get_member(user_id))
                is not None
                and not member.bot
            )
        )

    async def get_active_games_count(
        self,
        guild: discord.Guild,
    ) -> int:
        category = guild.get_channel(
            ACTIVE_GAME_CATEGORY_ID
        )

        if not isinstance(
            category,
            discord.CategoryChannel,
        ):
            return 0

        return sum(
            1
            for channel in category.text_channels
            if channel.id
            != GAME_PROPOSAL_CHANNEL_ID
        )

    async def get_top_game(
        self,
        guild: discord.Guild,
    ):
        category = guild.get_channel(
            ACTIVE_GAME_CATEGORY_ID
        )

        if not isinstance(
            category,
            discord.CategoryChannel,
        ):
            return None, 0

        channels = [
            channel
            for channel in category.text_channels
            if channel.id
            != GAME_PROPOSAL_CHANNEL_ID
        ]

        if not channels:
            return None, 0

        ids = [
            channel.id
            for channel in channels
        ]

        placeholders = ",".join(
            "?"
            for _ in ids
        )

        week = get_week_start()

        query = f"""
            SELECT
                channel_id,
                messages
            FROM stats_weekly_games
            WHERE guild_id = ?
              AND week_start = ?
              AND channel_id IN ({placeholders})
            ORDER BY
                messages DESC,
                channel_id ASC
            LIMIT 1
        """

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                query,
                (
                    guild.id,
                    week,
                    *ids,
                ),
            )

            row = await cursor.fetchone()

        if not row:
            return None, 0

        channel = guild.get_channel(
            int(row[0])
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return None, 0

        return channel, int(row[1])

    async def get_voice_totals(
        self,
        guild: discord.Guild,
    ):
        week = get_week_start()
        week_start_timestamp = (
            get_week_start_timestamp()
        )

        totals: dict[int, int] = {}

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT
                    user_id,
                    voice_seconds
                FROM stats_weekly_users
                WHERE guild_id = ?
                  AND week_start = ?
                """,
                (
                    guild.id,
                    week,
                ),
            )

            rows = await cursor.fetchall()

            for user_id, seconds in rows:
                user_id = int(user_id)

                totals[user_id] = (
                    totals.get(
                        user_id,
                        0,
                    )
                    + int(seconds or 0)
                )

            cursor = await db.execute(
                """
                SELECT
                    user_id,
                    started_at
                FROM stats_voice_sessions
                WHERE guild_id = ?
                """,
                (guild.id,),
            )

            active_rows = await cursor.fetchall()

        now = time.time()

        for user_id, started_at in active_rows:
            user_id = int(user_id)

            counted_from = max(
                float(started_at),
                week_start_timestamp,
            )

            seconds = max(
                0,
                int(now - counted_from),
            )

            totals[user_id] = (
                totals.get(user_id, 0)
                + seconds
            )

        return totals

    async def get_top_player(
        self,
        guild: discord.Guild,
        voice_totals: dict[int, int] | None = None,
    ):
        week = get_week_start()
        user_data: dict[int, dict[str, int]] = {}

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT
                    user_id,
                    messages,
                    voice_seconds
                FROM stats_weekly_users
                WHERE guild_id = ?
                  AND week_start = ?
                """,
                (
                    guild.id,
                    week,
                ),
            )

            rows = await cursor.fetchall()

        for (
            user_id,
            messages,
            voice_seconds,
        ) in rows:
            user_data[int(user_id)] = {
                "messages": int(messages or 0),
                "voice": int(voice_seconds or 0),
            }

        # get_voice_totals bevat completed + actieve voice en vervangt daarom
        # de opgeslagen voicewaarde in plaats van die nogmaals op te tellen.
        if voice_totals is None:
            voice_totals = await self.get_voice_totals(
                guild
            )

        for user_id, seconds in (
            voice_totals.items()
        ):
            if user_id not in user_data:
                user_data[user_id] = {
                    "messages": 0,
                    "voice": 0,
                }

            user_data[user_id]["voice"] = seconds

        best_member = None
        best_score = -1.0

        for user_id, data in user_data.items():
            member = guild.get_member(
                user_id
            )

            if (
                member is None
                or member.bot
            ):
                continue

            # Bestaande scoreformule behouden:
            # 1 bericht = 1 punt, 1 minuut voice = 1 punt.
            score = (
                data["messages"]
                + data["voice"] / 60
            )

            if score > best_score:
                best_score = score
                best_member = member

        return best_member, best_score

    # ========================================================
    # MEMBERS CHANNEL
    # ========================================================

    async def update_members_channel(
        self,
        guild: discord.Guild,
    ) -> bool:
        config = await self.get_config(guild.id)
        if not config:
            return False

        channel = guild.get_channel(
            config["members_channel_id"]
        )
        if not isinstance(channel, discord.VoiceChannel):
            return False

        desired_name = (
            f"▏👥 Leden: "
            f"{format_number(guild.member_count or 0)}"
        )

        if channel.name == desired_name:
            return True

        try:
            await channel.edit(
                name=desired_name,
                reason="LEVENLOOS serverstats ledenupdate",
            )
        except discord.Forbidden:
            logger.warning(
                "Geen toestemming om leden-statkanaal %s te hernoemen.",
                channel.id,
            )
            return False
        except discord.HTTPException:
            logger.exception(
                "Leden-statkanaal %s hernoemen mislukt.",
                channel.id,
            )
            return False

        return True

    # ========================================================
    # DATE CHANNEL
    # ========================================================

    async def update_date_channel(
        self,
        guild: discord.Guild,
    ) -> bool:
        config = await self.get_config(guild.id)
        if not config:
            return False

        channel = guild.get_channel(
            config["date_channel_id"]
        )

        if not isinstance(channel, discord.VoiceChannel):
            try:
                (
                    _,
                    channel,
                    _,
                    _,
                    _,
                ) = await self.ensure_stats_structure(guild)
            except (discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Datumstat herstellen mislukt in guild %s.",
                    guild.id,
                )
                return False

        desired_name = format_date_channel_name()

        if channel.name == desired_name:
            return True

        try:
            await channel.edit(
                name=desired_name,
                reason="LEVENLOOS datumstat dagelijkse update",
            )
        except discord.Forbidden:
            logger.warning(
                "Geen toestemming om datumstat %s te hernoemen.",
                channel.id,
            )
            return False
        except discord.HTTPException:
            logger.exception(
                "Datumstat %s hernoemen mislukt.",
                channel.id,
            )
            return False

        logger.info(
            "Datumstat bijgewerkt naar %s.",
            desired_name,
        )
        return True

    # ========================================================
    # BIRTHDAY CHANNEL
    # ========================================================

    async def update_birthday_channel(
        self,
        guild: discord.Guild,
    ) -> bool:
        config = await self.get_config(guild.id)
        if not config:
            return False

        category = guild.get_channel(
            config["category_id"]
        )
        if not isinstance(category, discord.CategoryChannel):
            return False

        birthdays = await self.get_today_birthdays(guild)
        channel = guild.get_channel(
            config["birthday_channel_id"]
        )

        if not birthdays:
            if isinstance(channel, discord.VoiceChannel):
                try:
                    await channel.delete(
                        reason="Geen verjaardag meer vandaag",
                    )
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception(
                        "Verjaardagsstat verwijderen mislukt in guild %s.",
                        guild.id,
                    )
                    return False

            if config["birthday_channel_id"]:
                await self.update_config_values(
                    guild.id,
                    birthday_channel_id=0,
                )
            return True

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=False,
            )
        }
        desired_name = birthday_stat_name(birthdays)

        if not isinstance(channel, discord.VoiceChannel):
            try:
                channel = await guild.create_voice_channel(
                    desired_name,
                    category=category,
                    overwrites=overwrites,
                    reason="LEVENLOOS verjaardagsstat",
                )
                await self.update_config_values(
                    guild.id,
                    birthday_channel_id=channel.id,
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Verjaardagsstat aanmaken mislukt in guild %s.",
                    guild.id,
                )
                return False
            return True

        try:
            changes = {}
            if channel.name != desired_name:
                changes["name"] = desired_name
            if channel.category_id != category.id:
                changes["category"] = category

            if changes:
                await channel.edit(
                    **changes,
                    reason="LEVENLOOS verjaardagsstat update",
                )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Verjaardagsstat bijwerken mislukt in guild %s.",
                guild.id,
            )
            return False

        return True

    # ========================================================
    # ROTATING CHANNEL
    # ========================================================

    async def update_rotating_channel(
        self,
        guild: discord.Guild,
        force_current: bool = False,
    ) -> bool:
        config = await self.get_config(guild.id)
        if not config:
            return False

        channel = guild.get_channel(
            config["rotating_channel_id"]
        )
        if not isinstance(channel, discord.VoiceChannel):
            return False

        rotation_index = max(
            0,
            int(config["rotation_index"]),
        )

        boosts = guild.premium_subscription_count or 0

        (
            active_games,
            week_messages,
            top_game_result,
            voice_totals,
        ) = await asyncio.gather(
            self.get_active_games_count(guild),
            self.get_week_messages(guild),
            self.get_top_game(guild),
            self.get_voice_totals(guild),
        )

        top_game, top_game_messages = top_game_result

        top_player, _ = await self.get_top_player(
            guild,
            voice_totals=voice_totals,
        )

        total_voice_seconds = sum(
            voice_totals.values()
        )

        if top_game:
            top_game_name = game_channel_display_name(
                top_game
            )
        else:
            top_game_name = "Nog geen data"

        top_player_messages = 0
        top_player_voice = 0

        if top_player:
            top_player_name = shorten(
                top_player.display_name,
                34,
            )
            top_player_messages = await self.get_week_user_messages(
                guild,
                top_player.id,
            )
            top_player_voice = voice_totals.get(
                top_player.id,
                0,
            )
        else:
            top_player_name = "Nog geen data"

        # Kanaalnamen ondersteunen geen custom serveremoji's.
        rotations = [
            (
                f"▏🚀 Boosts: "
                f"{format_number(boosts)}"
            ),
            (
                f"▏🎮 Games: "
                f"{format_number(active_games)} actief"
            ),
            (
                f"▏💬 Week: "
                f"{format_number(week_messages)} berichten"
            ),
            (
                f"▏🔥 #1 game: "
                f"{shorten(top_game_name, 42)}"
                + (
                    f" • {format_number(top_game_messages)} msg"
                    if top_game
                    else ""
                )
            ),
            (
                f"▏🔊 Voice: "
                f"{format_voice_hours(total_voice_seconds)} deze week"
            ),
            (
                f"▏🏆 Actiefste: "
                f"{top_player_name}"
                + (
                    f" • {format_number(top_player_messages)} msg "
                    f"+ {format_voice_hours(top_player_voice)}"
                    if top_player
                    else ""
                )
            ),
        ]

        rotation_index %= len(rotations)
        desired_name = shorten(
            rotations[rotation_index],
            100,
        )

        if channel.name != desired_name:
            try:
                await channel.edit(
                    name=desired_name,
                    reason="LEVENLOOS serverstats rotatie",
                )
            except discord.Forbidden:
                logger.warning(
                    "Geen toestemming om rotatiestatkanaal %s te hernoemen.",
                    channel.id,
                )
                return False
            except discord.HTTPException:
                logger.exception(
                    "Rotatiestatkanaal %s hernoemen mislukt.",
                    channel.id,
                )
                return False

        if force_current:
            return True

        new_index = (
            rotation_index + 1
        ) % len(rotations)

        await self.update_config_values(
            guild.id,
            rotation_index=new_index,
        )
        return True

    # ========================================================
    # BACKGROUND LOOPS
    # ========================================================

    @tasks.loop(
        minutes=MEMBER_UPDATE_MINUTES
    )
    async def member_update_loop(self):
        for guild in self.bot.guilds:
            try:
                await self.update_members_channel(
                    guild
                )
            except Exception:
                logger.exception(
                    "Members-loop mislukt voor guild %s.",
                    guild.id,
                )

    @member_update_loop.before_loop
    async def before_member_update_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(
        minutes=CALENDAR_UPDATE_MINUTES
    )
    async def calendar_update_loop(self):
        for guild in self.bot.guilds:
            try:
                await self.update_date_channel(guild)
                await self.update_birthday_channel(guild)
            except Exception:
                logger.exception(
                    "Datum/verjaardag-loop mislukt voor guild %s.",
                    guild.id,
                )

    @calendar_update_loop.before_loop
    async def before_calendar_update_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(
        minutes=ROTATION_MINUTES
    )
    async def rotation_loop(self):
        for guild in self.bot.guilds:
            try:
                await self.update_rotating_channel(
                    guild
                )
            except Exception:
                logger.exception(
                    "Rotatie-loop mislukt voor guild %s.",
                    guild.id,
                )

    @rotation_loop.before_loop
    async def before_rotation_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(
        minutes=MONTHLY_THROWBACK_CHECK_MINUTES
    )
    async def monthly_throwback_loop(self):
        now = datetime.now(TIMEZONE)

        # Niet midden in de nacht op de eerste dag posten.
        # Als de bot op dag 1 offline was, wordt later alsnog ingehaald.
        if now.day == 1 and now.hour < 9:
            return

        month_key = previous_month_key(now)

        for guild in self.bot.guilds:
            try:
                config = await self.get_config(
                    guild.id
                )

                if (
                    config is None
                    or not config["throwback_enabled"]
                    or not config["throwback_channel_id"]
                ):
                    continue

                if await self.throwback_already_posted(
                    guild.id,
                    month_key,
                ):
                    continue

                ok, message = await self.post_monthly_throwback(
                    guild,
                    month_key,
                    automatic=True,
                )

                if ok:
                    logger.info(
                        "Automatische monthly throwback geplaatst: %s",
                        message,
                    )
            except Exception:
                logger.exception(
                    "Monthly throwback-loop mislukt voor guild %s.",
                    guild.id,
                )

    @monthly_throwback_loop.before_loop
    async def before_monthly_throwback_loop(self):
        await self.bot.wait_until_ready()


# ============================================================
# EXTENSION SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Stats(bot)
    )
