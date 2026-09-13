from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
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

DATABASE_PATH = Path("lfg.db")
TZ = ZoneInfo("Europe/Amsterdam")
BRAND_COLOR = discord.Colour.from_str("#6C27DA")

MAX_ROLE_PINGS_PER_LFG = 5
MAX_ALLOWED_CHANNELS = 10
MAX_ALLOWED_PING_ROLES = 15
MAX_OVERVIEW_ITEMS = 12
DEFAULT_MAX_ACTIVE_PER_USER = 3
DEFAULT_DURATION_MINUTES = 120
DEFAULT_REMINDER_MINUTES = 15
DEFAULT_PING_DELETE_SECONDS = 8

logger = logging.getLogger(__name__)


# ============================================================
# LEVENLOOS CUSTOM EMOJIS
# ============================================================

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
INFO_EMOJI = "<:info:1547724036107149413>"

ADD_EMOJI = "<:add:1547724100812931072>"
EDIT_EMOJI = "<:edit:1547724058894934116>"
DELETE_EMOJI = "<:delete:1547724056768286750>"
REFRESH_EMOJI = "<:refresh:1547724055426244618>"
BACK_EMOJI = "<:back:1547724054038052966>"
LOCK_EMOJI = "<:lock:1547724040888786966>"
INFO_BUTTON_EMOJI = "<:info:1547724036107149413>"

GAMES_EMOJI = "<:gamesbutton:1547854165097717801>"
TIME_EMOJI = "<:tijd:1547854182298550373>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"
USER_EMOJI = "<:user:1547737210986692679>"
NOTIFICATION_EMOJI = "<:notificatie:1547738617659662488>"
STATUS_EMOJI = "<:status:1547738616501899364>"
VOICE_EMOJI = "<:voice:1547737205429243924>"
TEXT_EMOJI = "<:berichten:1547737207778058250>"


# ============================================================
# DATA
# ============================================================

@dataclass(slots=True)
class LFGConfig:
    guild_id: int
    default_channel_id: int = 0
    voice_category_id: int = 0
    auto_thread: bool = True
    default_waitlist: bool = True
    max_active_per_user: int = DEFAULT_MAX_ACTIVE_PER_USER
    default_duration_minutes: int = DEFAULT_DURATION_MINUTES
    default_reminder_minutes: int = DEFAULT_REMINDER_MINUTES
    ping_delete_seconds: int = DEFAULT_PING_DELETE_SECONDS


@dataclass(slots=True)
class LFGDraft:
    guild_id: int
    creator_id: int
    title: str = ""
    game: str = ""
    description: str = ""
    goal: str = "Casual"
    start_ts: int = 0
    duration_minutes: int = DEFAULT_DURATION_MINUTES
    slots: int = 5
    channel_id: int = 0
    voice_channel_id: int = 0
    role_ids: list[int] = field(default_factory=list)
    auto_thread: bool = True
    waitlist_enabled: bool = True
    reminder_minutes: int = DEFAULT_REMINDER_MINUTES


@dataclass(slots=True)
class LFGPost:
    id: int
    guild_id: int
    creator_id: int
    title: str
    game: str
    description: str
    goal: str
    start_ts: int
    duration_minutes: int
    slots: int
    channel_id: int
    message_id: int
    thread_id: int
    voice_channel_id: int
    auto_thread: bool
    waitlist_enabled: bool
    reminder_minutes: int
    reminder_sent: bool
    started_notified: bool
    status: str
    created_at: int


# ============================================================
# HELPERS
# ============================================================

def management_access(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True
    if member.guild_permissions.administrator:
        return True
    names = {role.name.casefold() for role in member.roles}
    return "admin" in names or "owner" in names


def ui_emoji(value: str | None):
    if not value:
        return None
    try:
        return discord.PartialEmoji.from_str(value)
    except Exception:
        logger.warning("Kon custom emoji niet parsen: %s", value)
        return None


def shorten(value: str, limit: int) -> str:
    value = str(value or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def format_duration(minutes: int) -> str:
    if minutes <= 0:
        return "onbepaald"
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}u {mins}m"
    if hours:
        return f"{hours}u"
    return f"{mins}m"


def parse_custom_datetime(value: str) -> int | None:
    value = value.strip()
    patterns = (
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%d-%m %H:%M",
        "%d/%m %H:%M",
    )
    now = datetime.now(TZ)

    for pattern in patterns:
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue

        if "%Y" not in pattern:
            parsed = parsed.replace(year=now.year)
            candidate = parsed.replace(tzinfo=TZ)
            if candidate < now - timedelta(minutes=1):
                candidate = candidate.replace(year=now.year + 1)
            return int(candidate.timestamp())

        return int(parsed.replace(tzinfo=TZ).timestamp())

    return None


def builder_time_options() -> list[discord.SelectOption]:
    """
    Bouw altijd unieke tijdopties.

    Voorheen konden na 20:00 zowel "Vanavond 20:00" als
    "Morgen 20:00" naar exact dezelfde timestamp wijzen.
    Discord weigert dubbele select-values, waardoor de Tijd-knop
    eindigde in "This interaction failed / did not respond".
    """
    now = datetime.now(TZ)

    today_20 = now.replace(
        hour=20,
        minute=0,
        second=0,
        microsecond=0,
    )

    if now < today_20:
        first_20 = today_20
        first_label = "Vanavond 20:00"

        second_20 = today_20 + timedelta(days=1)
        second_label = "Morgen 20:00"
    else:
        first_20 = today_20 + timedelta(days=1)
        first_label = "Morgen 20:00"

        second_20 = today_20 + timedelta(days=2)
        second_label = "Overmorgen 20:00"

    return [
        discord.SelectOption(
            label="Nu / zo snel mogelijk",
            value="now",
            description="Start over ongeveer 5 minuten.",
        ),
        discord.SelectOption(
            label="Over 30 minuten",
            value="30m",
        ),
        discord.SelectOption(
            label="Over 1 uur",
            value="1h",
        ),
        discord.SelectOption(
            label="Over 2 uur",
            value="2h",
        ),
        discord.SelectOption(
            label=first_label,
            value=f"ts:{int(first_20.timestamp())}",
        ),
        discord.SelectOption(
            label=second_label,
            value=f"ts:{int(second_20.timestamp())}",
        ),
        discord.SelectOption(
            label="Eigen datum & tijd",
            value="custom",
            description="Bijv. 15-09-2026 20:30",
        ),
    ]


def post_status_label(status: str) -> str:
    return {
        "open": "Open",
        "started": "Bezig",
        "closed": "Gesloten",
        "cancelled": "Geannuleerd",
    }.get(status, status.title())


def post_accent(status: str) -> discord.Colour:
    if status == "started":
        return discord.Colour.from_rgb(87, 242, 135)
    if status == "cancelled":
        return discord.Colour.from_rgb(237, 66, 69)
    if status == "closed":
        return discord.Colour.from_rgb(116, 127, 141)
    return BRAND_COLOR


# ============================================================
# DATABASE
# ============================================================

async def init_db() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS lfg_config (
                guild_id INTEGER PRIMARY KEY,
                default_channel_id INTEGER NOT NULL DEFAULT 0,
                voice_category_id INTEGER NOT NULL DEFAULT 0,
                auto_thread INTEGER NOT NULL DEFAULT 1,
                default_waitlist INTEGER NOT NULL DEFAULT 1,
                max_active_per_user INTEGER NOT NULL DEFAULT 3,
                default_duration_minutes INTEGER NOT NULL DEFAULT 120,
                default_reminder_minutes INTEGER NOT NULL DEFAULT 15,
                ping_delete_seconds INTEGER NOT NULL DEFAULT 8
            );

            CREATE TABLE IF NOT EXISTS lfg_allowed_channels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS lfg_ping_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS lfg_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                game TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT 'Casual',
                start_ts INTEGER NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 120,
                slots INTEGER NOT NULL DEFAULT 5,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL DEFAULT 0,
                thread_id INTEGER NOT NULL DEFAULT 0,
                voice_channel_id INTEGER NOT NULL DEFAULT 0,
                auto_thread INTEGER NOT NULL DEFAULT 1,
                waitlist_enabled INTEGER NOT NULL DEFAULT 1,
                reminder_minutes INTEGER NOT NULL DEFAULT 15,
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                started_notified INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lfg_post_roles (
                lfg_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (lfg_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS lfg_members (
                lfg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                ready INTEGER NOT NULL DEFAULT 0,
                joined_at INTEGER NOT NULL,
                PRIMARY KEY (lfg_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_lfg_posts_guild_status
            ON lfg_posts(guild_id, status, start_ts);

            CREATE INDEX IF NOT EXISTS idx_lfg_members_post_status
            ON lfg_members(lfg_id, status, joined_at);
            """
        )
        await db.commit()


# ============================================================
# FEEDBACK
# ============================================================

class FeedbackView(discord.ui.LayoutView):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
        footer: str | None = None,
    ):
        super().__init__(timeout=180)

        if kind == "success":
            default_title = "Gelukt"
            icon = SUCCESS_EMOJI
            accent = discord.Colour.from_rgb(87, 242, 135)
        elif kind == "error":
            default_title = "Fout"
            icon = ERROR_EMOJI
            accent = discord.Colour.from_rgb(237, 66, 69)
        elif kind == "warning":
            default_title = "Let op"
            icon = WARNING_EMOJI
            accent = discord.Colour.from_rgb(254, 231, 92)
        else:
            default_title = "Informatie"
            icon = INFO_EMOJI
            accent = BRAND_COLOR

        body = "\n".join(
            f"> └ {line}"
            for line in str(message).splitlines()
            if line.strip()
        ) or "> └ —"

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"# {icon} {title or default_title}\n{body}"
            )
        ]

        if footer:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.TextDisplay(f"-# {footer}"),
                ]
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=accent,
            )
        )


# ============================================================
# GENERIC BUTTON
# ============================================================

class ActionButton(discord.ui.Button):
    def __init__(
        self,
        owner_view,
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        custom_id: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=ui_emoji(emoji),
            style=style,
            custom_id=custom_id,
            disabled=disabled,
        )
        self.owner_view = owner_view
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.handle(interaction, self.action)


# ============================================================
# LFG PUBLIC CARD CONTROLS
# ============================================================

class LFGActionButton(discord.ui.Button):
    def __init__(
        self,
        cog: "LFG",
        lfg_id: int,
        action: str,
        label: str,
        *,
        emoji: str | None,
        style: discord.ButtonStyle,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=ui_emoji(emoji),
            style=style,
            custom_id=f"lfg:{action}:{lfg_id}",
            disabled=disabled,
        )
        self.cog = cog
        self.lfg_id = lfg_id
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_public_action(
            interaction,
            self.lfg_id,
            self.action,
        )


class LFGPersistentControls(discord.ui.LayoutView):
    def __init__(self, cog: "LFG", lfg_id: int):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.ActionRow(
                LFGActionButton(
                    cog,
                    lfg_id,
                    "join",
                    "Deelnemen",
                    emoji=ADD_EMOJI,
                    style=discord.ButtonStyle.primary,
                ),
                LFGActionButton(
                    cog,
                    lfg_id,
                    "maybe",
                    "Misschien",
                    emoji=INFO_EMOJI,
                    style=discord.ButtonStyle.secondary,
                ),
                LFGActionButton(
                    cog,
                    lfg_id,
                    "leave",
                    "Afmelden",
                    emoji=BACK_EMOJI,
                    style=discord.ButtonStyle.secondary,
                ),
                LFGActionButton(
                    cog,
                    lfg_id,
                    "ready",
                    "Klaar",
                    emoji=SUCCESS_EMOJI,
                    style=discord.ButtonStyle.success,
                ),
                LFGActionButton(
                    cog,
                    lfg_id,
                    "manage",
                    "Beheer",
                    emoji=SETTINGS_EMOJI,
                    style=discord.ButtonStyle.secondary,
                ),
            )
        )


class LFGCardView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "LFG",
        post: LFGPost,
        *,
        role_ids: list[int],
        members: list[tuple[int, str, bool, int]],
    ):
        super().__init__(timeout=None)

        joined = [row for row in members if row[1] == "joined"]
        waitlist = [row for row in members if row[1] == "waitlist"]
        maybe = [row for row in members if row[1] == "maybe"]
        ready_count = sum(1 for row in joined if row[2])

        if post.slots <= 0:
            slots_text = f"**{len(joined)}** bevestigd"
        else:
            slots_text = f"**{len(joined)}/{post.slots}** bevestigd"

        participant_mentions = [
            f"<@{user_id}>"
            for user_id, _, _, _ in joined[:8]
        ]
        if len(joined) > 8:
            participant_mentions.append(
                f"+{len(joined) - 8} meer"
            )

        people_line = (
            " • ".join(participant_mentions)
            if participant_mentions
            else "Nog niemand aangemeld."
        )

        role_line = (
            " ".join(f"<@&{role_id}>" for role_id in role_ids)
            if role_ids
            else "Geen specifieke rolping."
        )

        thread_line = (
            f"<#{post.thread_id}>"
            if post.thread_id
            else "Geen aparte LFG-chat."
        )
        voice_line = (
            f"<#{post.voice_channel_id}>"
            if post.voice_channel_id
            else "Niet gekozen."
        )

        status_extra = []
        if waitlist:
            status_extra.append(f"**{len(waitlist)}** wachtlijst")
        if maybe:
            status_extra.append(f"**{len(maybe)}** misschien")

        status_suffix = (
            " • " + " • ".join(status_extra)
            if status_extra
            else ""
        )

        body = (
            f"# {GAMES_EMOJI} {shorten(post.game, 55)} • {shorten(post.title, 70)}\n"
            f"> └ {shorten(post.description or 'Geen extra omschrijving.', 650)}\n\n"
            f"## {TIME_EMOJI} Wanneer\n"
            f"> └ <t:{post.start_ts}:F> • <t:{post.start_ts}:R>\n"
            f"> └ Duur: **{format_duration(post.duration_minutes)}** • Status: **{post_status_label(post.status)}**\n\n"
            f"## {USER_EMOJI} Spelers\n"
            f"> └ {slots_text}{status_suffix}\n"
            f"> └ Klaar: **{ready_count}/{len(joined)}**\n"
            f"> └ {people_line}\n\n"
            f"## {INFO_EMOJI} Details\n"
            f"> └ Host: <@{post.creator_id}> • Doel: **{shorten(post.goal, 80)}**\n"
            f"> └ Voice: {voice_line}\n"
            f"> └ LFG-chat: {thread_line}\n\n"
            f"## {NOTIFICATION_EMOJI} Pings\n"
            f"> └ {role_line}"
        )

        closed = post.status in {"closed", "cancelled"}
        started = post.status == "started"

        controls = discord.ui.ActionRow(
            LFGActionButton(
                cog,
                post.id,
                "join",
                "Deelnemen",
                emoji=ADD_EMOJI,
                style=discord.ButtonStyle.primary,
                disabled=closed,
            ),
            LFGActionButton(
                cog,
                post.id,
                "maybe",
                "Misschien",
                emoji=INFO_EMOJI,
                style=discord.ButtonStyle.secondary,
                disabled=closed or started,
            ),
            LFGActionButton(
                cog,
                post.id,
                "leave",
                "Afmelden",
                emoji=BACK_EMOJI,
                style=discord.ButtonStyle.secondary,
                disabled=closed,
            ),
            LFGActionButton(
                cog,
                post.id,
                "ready",
                "Klaar",
                emoji=SUCCESS_EMOJI,
                style=discord.ButtonStyle.success,
                disabled=closed,
            ),
            LFGActionButton(
                cog,
                post.id,
                "manage",
                "Beheer",
                emoji=SETTINGS_EMOJI,
                style=discord.ButtonStyle.secondary,
            ),
        )

        helper = (
            f"-# LFG #{post.id} • Wachtlijst {'aan' if post.waitlist_enabled else 'uit'}"
            f" • Reminder {post.reminder_minutes} min"
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(body),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                controls,
                discord.ui.TextDisplay(helper),
                accent_colour=post_accent(post.status),
            )
        )


# ============================================================
# BUILDER BASE
# ============================================================

class BuilderOwnedView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        *,
        timeout: float = 900,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id
        self.draft = draft

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit LFG-menu is niet van jou.",
                kind="error",
            )
            return False
        return True


# ============================================================
# BUILDER MODALS
# ============================================================

class LFGBasicsModal(discord.ui.Modal):
    def __init__(self, view: "LFGBuilderView"):
        super().__init__(title="LFG basis", timeout=300)
        self.owner_view = view
        draft = view.draft

        self.game = discord.ui.TextInput(
            label="Game",
            default=draft.game,
            placeholder="Bijv. Project Zomboid",
            max_length=80,
        )
        self.title_input = discord.ui.TextInput(
            label="Titel",
            default=draft.title,
            placeholder="Bijv. Louisville loot run",
            max_length=100,
        )
        self.description = discord.ui.TextInput(
            label="Omschrijving",
            default=draft.description,
            placeholder="Wat gaan jullie doen?",
            style=discord.TextStyle.paragraph,
            max_length=750,
            required=False,
        )
        self.goal = discord.ui.TextInput(
            label="Doel / stijl",
            default=draft.goal,
            placeholder="Casual, Ranked, Achievement hunt...",
            max_length=80,
            required=False,
        )

        self.add_item(self.game)
        self.add_item(self.title_input)
        self.add_item(self.description)
        self.add_item(self.goal)

    async def on_submit(self, interaction: discord.Interaction):
        self.owner_view.draft.game = str(self.game).strip()
        self.owner_view.draft.title = str(self.title_input).strip()
        self.owner_view.draft.description = str(self.description).strip()
        self.owner_view.draft.goal = str(self.goal).strip() or "Casual"

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await LFGBuilderView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice="Basisgegevens opgeslagen.",
            ),
        )


class LFGCustomTimeModal(discord.ui.Modal):
    def __init__(self, owner_view: "LFGTimeView"):
        super().__init__(title="Eigen datum & tijd", timeout=300)
        self.owner_view = owner_view
        self.value = discord.ui.TextInput(
            label="Datum en tijd",
            placeholder="15-09-2026 20:30",
            max_length=25,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        timestamp = parse_custom_datetime(str(self.value))
        if timestamp is None:
            await self.owner_view.cog.send_feedback(
                interaction,
                "Gebruik bijvoorbeeld `15-09-2026 20:30`.",
                kind="error",
                title="Ongeldige datum",
            )
            return

        if timestamp < int(time.time()) + 60:
            await self.owner_view.cog.send_feedback(
                interaction,
                "Kies een tijd die minimaal één minuut in de toekomst ligt.",
                kind="error",
            )
            return

        self.owner_view.draft.start_ts = timestamp

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGTimeView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice="Eigen datum en tijd opgeslagen.",
            ),
        )


# ============================================================
# BUILDER TIME PAGE
# ============================================================

class LFGStartSelect(discord.ui.Select):
    def __init__(self, owner_view: "LFGTimeView"):
        super().__init__(
            placeholder="Kies starttijd...",
            options=builder_time_options(),
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        now = int(time.time())

        if value == "custom":
            await interaction.response.send_modal(
                LFGCustomTimeModal(self.owner_view)
            )
            return
        if value == "now":
            timestamp = now + 5 * 60
        elif value == "30m":
            timestamp = now + 30 * 60
        elif value == "1h":
            timestamp = now + 60 * 60
        elif value == "2h":
            timestamp = now + 2 * 60 * 60
        elif value.startswith("ts:"):
            timestamp = int(value.split(":", 1)[1])
        else:
            return

        self.owner_view.draft.start_ts = timestamp
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGTimeView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice="Starttijd aangepast.",
            ),
        )


class LFGDurationSelect(discord.ui.Select):
    def __init__(self, owner_view: "LFGTimeView"):
        options = [
            discord.SelectOption(label="30 minuten", value="30"),
            discord.SelectOption(label="1 uur", value="60"),
            discord.SelectOption(label="1,5 uur", value="90"),
            discord.SelectOption(label="2 uur", value="120"),
            discord.SelectOption(label="3 uur", value="180"),
            discord.SelectOption(label="4 uur", value="240"),
            discord.SelectOption(label="6 uur", value="360"),
        ]
        super().__init__(
            placeholder="Kies verwachte duur...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        self.owner_view.draft.duration_minutes = int(self.values[0])
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGTimeView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice="Duur aangepast.",
            ),
        )


class LFGReminderSelect(discord.ui.Select):
    def __init__(self, owner_view: "LFGTimeView"):
        super().__init__(
            placeholder="Kies reminder...",
            options=[
                discord.SelectOption(label="Geen reminder", value="0"),
                discord.SelectOption(label="5 minuten vooraf", value="5"),
                discord.SelectOption(label="10 minuten vooraf", value="10"),
                discord.SelectOption(label="15 minuten vooraf", value="15"),
                discord.SelectOption(label="30 minuten vooraf", value="30"),
                discord.SelectOption(label="1 uur vooraf", value="60"),
            ],
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        self.owner_view.draft.reminder_minutes = int(self.values[0])
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGTimeView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice="Reminder aangepast.",
            ),
        )


class LFGTimeView(BuilderOwnedView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, owner_id, draft)

        start = (
            f"<t:{draft.start_ts}:F> • <t:{draft.start_ts}:R>"
            if draft.start_ts
            else "Nog niet gekozen."
        )
        body = (
            f"# {TIME_EMOJI} Tijd & planning\n"
            "> └ Stel de starttijd, duur en automatische reminder in.\n\n"
            f"## {STATUS_EMOJI} Huidig\n"
            f"> └ Start: {start}\n"
            f"> └ Duur: **{format_duration(draft.duration_minutes)}**\n"
            f"> └ Reminder: **{draft.reminder_minutes} min vooraf**"
        )

        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))

        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(LFGStartSelect(self)),
                discord.ui.ActionRow(LFGDurationSelect(self)),
                discord.ui.ActionRow(LFGReminderSelect(self)),
                discord.ui.ActionRow(
                    ActionButton(self, "back", "Terug", emoji=BACK_EMOJI)
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGBuilderView.create(
                    self.cog,
                    self.owner_id,
                    self.draft,
                ),
            )


# ============================================================
# BUILDER SLOTS PAGE
# ============================================================

class LFGSlotsSelect(discord.ui.Select):
    def __init__(self, owner_view: "LFGSlotsView"):
        options = [
            discord.SelectOption(label=f"{count} spelers", value=str(count))
            for count in range(2, 11)
        ] + [
            discord.SelectOption(label="12 spelers", value="12"),
            discord.SelectOption(label="16 spelers", value="16"),
            discord.SelectOption(label="Onbeperkt", value="0"),
        ]
        super().__init__(
            placeholder="Kies aantal plekken...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        self.owner_view.draft.slots = int(self.values[0])
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGSlotsView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice="Aantal plekken aangepast.",
            ),
        )


class LFGSlotsView(BuilderOwnedView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, owner_id, draft)
        slots = "Onbeperkt" if draft.slots <= 0 else str(draft.slots)
        body = (
            f"# {USER_EMOJI} Spelers\n"
            "> └ Bepaal hoeveel spelers kunnen deelnemen.\n\n"
            f"## {STATUS_EMOJI} Huidig\n"
            f"> └ Plekken: **{slots}**\n"
            f"> └ Wachtlijst: **{'Aan' if draft.waitlist_enabled else 'Uit'}**\n\n"
            "> └ Als de LFG vol zit en de wachtlijst aan staat, schuift de eerste wachtende automatisch door zodra iemand afmeldt."
        )
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(LFGSlotsSelect(self)),
                discord.ui.ActionRow(
                    ActionButton(
                        self,
                        "waitlist",
                        "Wachtlijst uit" if draft.waitlist_enabled else "Wachtlijst aan",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.secondary,
                    ),
                    ActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "waitlist":
            self.draft.waitlist_enabled = not self.draft.waitlist_enabled
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGSlotsView(
                    self.cog,
                    self.owner_id,
                    self.draft,
                    notice="Wachtlijst aangepast.",
                ),
            )
            return
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGBuilderView.create(self.cog, self.owner_id, self.draft),
            )


# ============================================================
# BUILDER CHANNEL PAGE
# ============================================================

class LFGDestinationSelect(discord.ui.ChannelSelect):
    def __init__(self, owner_view: "LFGChannelView"):
        super().__init__(
            placeholder="Kies waar deze LFG geplaatst wordt...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        allowed = await self.owner_view.cog.allowed_channel_ids(
            self.owner_view.draft.guild_id
        )
        if allowed and channel.id not in allowed:
            await self.owner_view.cog.send_feedback(
                interaction,
                "Dit kanaal is niet toegestaan voor LFG-posts. Vraag een admin om het toe te voegen via `/lfg config`.",
                kind="error",
                title="Kanaal niet toegestaan",
            )
            return

        self.owner_view.draft.channel_id = channel.id
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGChannelView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice=f"LFG-kanaal ingesteld op <#{channel.id}>.",
            ),
        )


class LFGChannelView(BuilderOwnedView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, owner_id, draft)
        body = (
            f"# {TEXT_EMOJI} Kanaal & chat\n"
            "> └ Kies het kanaal waarin de LFG komt te staan.\n\n"
            f"## {STATUS_EMOJI} Huidig\n"
            f"> └ LFG-kanaal: {f'<#{draft.channel_id}>' if draft.channel_id else '**niet gekozen**'}\n"
            f"> └ Automatische thread: **{'Aan' if draft.auto_thread else 'Uit'}**\n\n"
            "> └ Met een automatische thread krijgt iedere LFG zijn eigen schone chat zonder het hoofdkanaal vol te laten lopen."
        )
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(LFGDestinationSelect(self)),
                discord.ui.ActionRow(
                    ActionButton(
                        self,
                        "thread",
                        "Thread uit" if draft.auto_thread else "Thread aan",
                        emoji=TEXT_EMOJI,
                    ),
                    ActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "thread":
            self.draft.auto_thread = not self.draft.auto_thread
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGChannelView(
                    self.cog,
                    self.owner_id,
                    self.draft,
                    notice="Thread-instelling aangepast.",
                ),
            )
            return
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGBuilderView.create(self.cog, self.owner_id, self.draft),
            )


# ============================================================
# BUILDER ROLE PAGE
# ============================================================

class LFGPingRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner_view: "LFGRoleView"):
        super().__init__(
            placeholder="Kies maximaal 5 rolpings...",
            min_values=1,
            max_values=MAX_ROLE_PINGS_PER_LFG,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        allowed = await self.owner_view.cog.allowed_ping_role_ids(
            self.owner_view.draft.guild_id
        )
        selected = [role.id for role in self.values]
        invalid = [role_id for role_id in selected if role_id not in allowed]

        if invalid:
            await self.owner_view.cog.send_feedback(
                interaction,
                "Je kunt alleen rollen pingen die door een admin zijn toegestaan in `/lfg config`.",
                kind="error",
                title="Rolping niet toegestaan",
            )
            return

        self.owner_view.draft.role_ids = selected
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGRoleView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice=f"{len(selected)} rolping(s) geselecteerd.",
            ),
        )


class LFGRoleView(BuilderOwnedView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, owner_id, draft)
        roles = (
            " ".join(f"<@&{role_id}>" for role_id in draft.role_ids)
            if draft.role_ids
            else "Geen rolpings gekozen."
        )
        body = (
            f"# {NOTIFICATION_EMOJI} Rolpings\n"
            "> └ Kies welke goedgekeurde rollen een melding krijgen wanneer je publiceert.\n\n"
            f"## {STATUS_EMOJI} Gekozen\n"
            f"> └ {roles}\n\n"
            "> └ Alleen rollen die door admins zijn gewhitelist kunnen worden gepingd. De ping wordt als kort, los bericht gestuurd zodat de LFG-kaart zelf schoon blijft."
        )
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(LFGPingRoleSelect(self)),
                discord.ui.ActionRow(
                    ActionButton(self, "clear", "Pings wissen", emoji=DELETE_EMOJI),
                    ActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "clear":
            self.draft.role_ids = []
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGRoleView(self.cog, self.owner_id, self.draft, notice="Rolpings gewist."),
            )
            return
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGBuilderView.create(self.cog, self.owner_id, self.draft),
            )


# ============================================================
# BUILDER VOICE PAGE
# ============================================================

class LFGVoiceSelect(discord.ui.ChannelSelect):
    def __init__(self, owner_view: "LFGVoiceView"):
        super().__init__(
            placeholder="Kies een voicekanaal...",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.owner_view.draft.voice_channel_id = channel.id
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=LFGVoiceView(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.draft,
                notice=f"Voice ingesteld op <#{channel.id}>.",
            ),
        )


class LFGVoiceView(BuilderOwnedView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, owner_id, draft)
        body = (
            f"# {VOICE_EMOJI} Voice\n"
            "> └ Koppel alvast een voicekanaal aan de LFG.\n\n"
            f"## {STATUS_EMOJI} Huidig\n"
            f"> └ Voice: {f'<#{draft.voice_channel_id}>' if draft.voice_channel_id else '**niet gekozen**'}\n\n"
            "> └ Je kunt ook je huidige voice met één klik gebruiken. LFG maakt bewust geen extra voicekanaal aan; zo blijft dit samenwerken met je bestaande Voice-module."
        )
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(LFGVoiceSelect(self)),
                discord.ui.ActionRow(
                    ActionButton(self, "current", "Mijn huidige voice", emoji=VOICE_EMOJI),
                    ActionButton(self, "clear", "Geen voice", emoji=DELETE_EMOJI),
                    ActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "current":
            member = interaction.user
            if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
                await self.cog.send_feedback(
                    interaction,
                    "Je zit momenteel niet in een voicekanaal.",
                    kind="warning",
                )
                return
            self.draft.voice_channel_id = member.voice.channel.id
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGVoiceView(self.cog, self.owner_id, self.draft, notice="Je huidige voice is gekoppeld."),
            )
            return
        if action == "clear":
            self.draft.voice_channel_id = 0
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGVoiceView(self.cog, self.owner_id, self.draft, notice="Voice-koppeling verwijderd."),
            )
            return
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGBuilderView.create(self.cog, self.owner_id, self.draft),
            )


# ============================================================
# BUILDER PREVIEW
# ============================================================

class LFGPreviewView(BuilderOwnedView):
    def __init__(self, cog: "LFG", owner_id: int, draft: LFGDraft):
        super().__init__(cog, owner_id, draft)
        start = (
            f"<t:{draft.start_ts}:F> • <t:{draft.start_ts}:R>"
            if draft.start_ts
            else "Nog niet gekozen"
        )
        roles = " ".join(f"<@&{role_id}>" for role_id in draft.role_ids) or "Geen"
        body = (
            f"# {GAMES_EMOJI} Preview • {shorten(draft.game or 'Geen game', 55)}\n"
            f"> └ **{shorten(draft.title or 'Geen titel', 80)}**\n"
            f"> └ {shorten(draft.description or 'Geen omschrijving.', 650)}\n\n"
            f"## {TIME_EMOJI} Planning\n"
            f"> └ {start}\n"
            f"> └ Duur: **{format_duration(draft.duration_minutes)}** • Reminder: **{draft.reminder_minutes} min**\n\n"
            f"## {USER_EMOJI} Spelers\n"
            f"> └ Plekken: **{'Onbeperkt' if draft.slots <= 0 else draft.slots}** • Wachtlijst: **{'Aan' if draft.waitlist_enabled else 'Uit'}**\n\n"
            f"## {INFO_EMOJI} Bestemming\n"
            f"> └ Kanaal: {f'<#{draft.channel_id}>' if draft.channel_id else '**niet gekozen**'}\n"
            f"> └ Voice: {f'<#{draft.voice_channel_id}>' if draft.voice_channel_id else '**geen**'}\n"
            f"> └ Thread: **{'Aan' if draft.auto_thread else 'Uit'}**\n"
            f"> └ Rolpings: {roles}"
        )
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(body),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(ActionButton(self, "back", "Terug", emoji=BACK_EMOJI)),
                accent_colour=BRAND_COLOR,
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGBuilderView.create(self.cog, self.owner_id, self.draft),
            )


# ============================================================
# MAIN BUILDER
# ============================================================

class LFGBuilderView(BuilderOwnedView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, owner_id, draft)
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    ActionButton(self, "basics", "Basis", emoji=EDIT_EMOJI, style=discord.ButtonStyle.primary),
                    ActionButton(self, "time", "Tijd", emoji=TIME_EMOJI),
                    ActionButton(self, "slots", "Spelers", emoji=USER_EMOJI),
                    ActionButton(self, "channel", "Kanaal", emoji=TEXT_EMOJI),
                    ActionButton(self, "roles", "Rollen", emoji=NOTIFICATION_EMOJI),
                ),
                discord.ui.ActionRow(
                    ActionButton(self, "voice", "Voice", emoji=VOICE_EMOJI),
                    ActionButton(self, "preview", "Preview", emoji=INFO_EMOJI),
                    ActionButton(self, "publish", "Publiceren", emoji=SUCCESS_EMOJI, style=discord.ButtonStyle.success),
                    ActionButton(self, "cancel", "Annuleren", emoji=DELETE_EMOJI, style=discord.ButtonStyle.danger),
                ),
                discord.ui.TextDisplay(
                    "-# Je LFG wordt pas zichtbaar voor anderen nadat je op Publiceren klikt."
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    @classmethod
    async def create(
        cls,
        cog: "LFG",
        owner_id: int,
        draft: LFGDraft,
        *,
        notice: str | None = None,
    ) -> "LFGBuilderView":
        start = (
            f"<t:{draft.start_ts}:R>"
            if draft.start_ts
            else "Niet gekozen"
        )
        role_count = len(draft.role_ids)
        complete = all(
            [
                draft.game.strip(),
                draft.title.strip(),
                draft.start_ts > int(time.time()),
                draft.channel_id,
            ]
        )
        body = (
            f"# {GAMES_EMOJI} LFG maken\n"
            "> └ Bouw één overzichtelijke LFG met planning, rollen, voice en automatische opvolging.\n\n"
            f"## {INFO_EMOJI} Basis\n"
            f"> └ Game: **{shorten(draft.game, 70) if draft.game else 'Niet ingesteld'}**\n"
            f"> └ Titel: **{shorten(draft.title, 80) if draft.title else 'Niet ingesteld'}**\n"
            f"> └ Doel: **{shorten(draft.goal, 60)}**\n\n"
            f"## {TIME_EMOJI} Planning\n"
            f"> └ Start: **{start}** • Duur: **{format_duration(draft.duration_minutes)}**\n"
            f"> └ Reminder: **{draft.reminder_minutes} min**\n\n"
            f"## {USER_EMOJI} Groep\n"
            f"> └ Plekken: **{'∞' if draft.slots <= 0 else draft.slots}** • Wachtlijst: **{'Aan' if draft.waitlist_enabled else 'Uit'}**\n"
            f"> └ Rolpings: **{role_count}**\n\n"
            f"## {TEXT_EMOJI} Bestemming\n"
            f"> └ Kanaal: {f'<#{draft.channel_id}>' if draft.channel_id else '**Niet gekozen**'}\n"
            f"> └ Voice: {f'<#{draft.voice_channel_id}>' if draft.voice_channel_id else '**Geen**'} • Thread: **{'Aan' if draft.auto_thread else 'Uit'}**\n\n"
            f"## {STATUS_EMOJI} Klaar om te publiceren\n"
            f"> └ **{'Ja' if complete else 'Nog niet'}**"
        )
        return cls(cog, owner_id, draft, body, notice=notice)

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "basics":
            await interaction.response.send_modal(LFGBasicsModal(self))
            return
        if action == "time":
            try:
                time_view = LFGTimeView(
                    self.cog,
                    self.owner_id,
                    self.draft,
                )
                await interaction.response.edit_message(
                    content=None,
                    embed=None,
                    view=time_view,
                )
            except Exception:
                logger.exception(
                    "LFG tijdpagina openen mislukt voor gebruiker %s.",
                    interaction.user.id,
                )
                await self.cog.send_feedback(
                    interaction,
                    "De tijdpagina kon niet worden geopend. De fout staat in de botlog.",
                    kind="error",
                    title="Tijdpagina mislukt",
                )
            return
        if action == "slots":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGSlotsView(self.cog, self.owner_id, self.draft),
            )
            return
        if action == "channel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGChannelView(self.cog, self.owner_id, self.draft),
            )
            return
        if action == "roles":
            allowed = await self.cog.allowed_ping_role_ids(self.draft.guild_id)
            if not allowed:
                await self.cog.send_feedback(
                    interaction,
                    "Er zijn nog geen rolpings toegestaan. Een admin kan dit instellen via `/lfg config`.",
                    kind="warning",
                    title="Geen rolpings ingesteld",
                )
                return
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGRoleView(self.cog, self.owner_id, self.draft),
            )
            return
        if action == "voice":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGVoiceView(self.cog, self.owner_id, self.draft),
            )
            return
        if action == "preview":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=LFGPreviewView(self.cog, self.owner_id, self.draft),
            )
            return
        if action == "cancel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=FeedbackView(
                    "Je concept is gesloten. Er is niets gepubliceerd.",
                    kind="info",
                    title="LFG geannuleerd",
                ),
            )
            return
        if action == "publish":
            await self.cog.publish_draft(interaction, self.draft)


# ============================================================
# MANAGE PANEL
# ============================================================

class LFGManageRemoveSelect(discord.ui.UserSelect):
    def __init__(self, owner_view: "LFGManageView"):
        super().__init__(
            placeholder="Verwijder iemand uit deze LFG...",
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.remove_member(interaction, self.values[0].id)


class LFGManageView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "LFG",
        owner_id: int,
        post: LFGPost,
        summary: str,
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.post = post

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(summary),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    ActionButton(self, "refresh", "Vernieuwen", emoji=REFRESH_EMOJI),
                    ActionButton(self, "start", "Start nu", emoji=TIME_EMOJI, style=discord.ButtonStyle.primary),
                    ActionButton(self, "ping", "Ping deelnemers", emoji=NOTIFICATION_EMOJI),
                    ActionButton(self, "close", "Sluiten", emoji=LOCK_EMOJI),
                    ActionButton(self, "cancel", "Annuleren", emoji=DELETE_EMOJI, style=discord.ButtonStyle.danger),
                ),
                discord.ui.TextDisplay(
                    f"## {USER_EMOJI} Deelnemer verwijderen\n"
                    "> └ Gebruik dit alleen wanneer iemand niet meer mee kan doen of misbruik maakt van de LFG."
                ),
                discord.ui.ActionRow(LFGManageRemoveSelect(self)),
                discord.ui.TextDisplay("-# Alleen de maker en serverbeheer kunnen dit panel gebruiken."),
                accent_colour=BRAND_COLOR,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(interaction, "Dit beheermenu is niet van jou.", kind="error")
            return False
        post = await self.cog.get_post(self.post.id)
        if post is None:
            await self.cog.send_feedback(interaction, "Deze LFG bestaat niet meer.", kind="error")
            return False
        if not await self.cog.can_manage_post(interaction, post):
            await self.cog.send_feedback(interaction, "Je mag deze LFG niet beheren.", kind="error", title="Geen toegang")
            return False
        return True

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "refresh":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await self.cog.build_manage_view(self.owner_id, self.post.id),
            )
            return
        if action == "start":
            await self.cog.start_post_now(interaction, self.post.id)
            return
        if action == "ping":
            await self.cog.ping_participants(interaction, self.post.id)
            return
        if action == "close":
            await self.cog.close_post(interaction, self.post.id, cancelled=False)
            return
        if action == "cancel":
            await self.cog.close_post(interaction, self.post.id, cancelled=True)
            return

    async def remove_member(self, interaction: discord.Interaction, user_id: int):
        removed = await self.cog.remove_member(self.post.id, user_id)
        if not removed:
            await self.cog.send_feedback(
                interaction,
                "Deze gebruiker staat niet in deze LFG.",
                kind="info",
            )
            return
        await self.cog.promote_waitlist(self.post.id)
        await self.cog.refresh_card(self.post.id)
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await self.cog.build_manage_view(
                self.owner_id,
                self.post.id,
                notice=f"<@{user_id}> is uit de LFG verwijderd.",
            ),
        )


# ============================================================
# CONFIG PANEL
# ============================================================

class LFGConfigChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner_view: "LFGConfigChannelsView", mode: str):
        self.owner_view = owner_view
        self.mode = mode
        super().__init__(
            placeholder=(
                "Kies standaard LFG-kanaal..."
                if mode == "default"
                else "Kies toegestane LFG-kanalen..."
            ),
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1 if mode == "default" else MAX_ALLOWED_CHANNELS,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.mode == "default":
            channel = self.values[0]
            await self.owner_view.cog.update_config(
                self.owner_view.guild_id,
                default_channel_id=channel.id,
            )
            notice = f"Standaardkanaal ingesteld op <#{channel.id}>."
        else:
            ids = [channel.id for channel in self.values]
            await self.owner_view.cog.set_allowed_channels(self.owner_view.guild_id, ids)
            notice = f"{len(ids)} toegestane kanaal/kanalen opgeslagen."

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await LFGConfigChannelsView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice=notice,
            ),
        )


class LFGConfigChannelsView(discord.ui.LayoutView):
    def __init__(self, cog: "LFG", owner_id: int, guild_id: int, body: str, *, notice: str | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.TextDisplay(f"## {TEXT_EMOJI} Standaardkanaal\n> └ Wordt automatisch voorgeselecteerd bij nieuwe LFG's."),
                discord.ui.ActionRow(LFGConfigChannelSelect(self, "default")),
                discord.ui.TextDisplay(f"## {LOCK_EMOJI} Toegestane kanalen\n> └ Als deze lijst leeg is, mag ieder tekstkanaal worden gekozen."),
                discord.ui.ActionRow(LFGConfigChannelSelect(self, "allowed")),
                discord.ui.ActionRow(
                    ActionButton(self, "all", "Alle kanalen toestaan", emoji=REFRESH_EMOJI),
                    ActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    @classmethod
    async def create(cls, cog: "LFG", owner_id: int, guild_id: int, *, notice: str | None = None):
        config = await cog.get_config(guild_id)
        allowed = await cog.allowed_channel_ids(guild_id)
        allowed_text = (
            " ".join(f"<#{channel_id}>" for channel_id in sorted(allowed))
            if allowed
            else "Alle tekstkanalen"
        )
        body = (
            f"# {TEXT_EMOJI} LFG-kanalen\n"
            "> └ Bepaal waar leden hun LFG mogen publiceren.\n\n"
            f"> └ Standaard: {f'<#{config.default_channel_id}>' if config.default_channel_id else '**niet ingesteld**'}\n"
            f"> └ Toegestaan: {allowed_text}"
        )
        return cls(cog, owner_id, guild_id, body, notice=notice)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog.config_access(interaction, self.owner_id)

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "all":
            await self.cog.set_allowed_channels(self.guild_id, [])
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigChannelsView.create(self.cog, self.owner_id, self.guild_id, notice="Alle tekstkanalen zijn toegestaan."),
            )
            return
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigView.create(self.cog, self.owner_id, self.guild_id),
            )


class LFGConfigRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner_view: "LFGConfigRolesView"):
        super().__init__(
            placeholder="Kies rollen die LFG's mogen pingen...",
            min_values=1,
            max_values=MAX_ALLOWED_PING_ROLES,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction):
        roles = [role for role in self.values if not role.is_default()]
        await self.owner_view.cog.set_ping_roles(
            self.owner_view.guild_id,
            [role.id for role in roles],
        )
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await LFGConfigRolesView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice=f"{len(roles)} pingrol(len) opgeslagen.",
            ),
        )


class LFGConfigRolesView(discord.ui.LayoutView):
    def __init__(self, cog: "LFG", owner_id: int, guild_id: int, body: str, *, notice: str | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(LFGConfigRoleSelect(self)),
                discord.ui.ActionRow(
                    ActionButton(self, "clear", "Geen rolpings toestaan", emoji=DELETE_EMOJI),
                    ActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
                discord.ui.TextDisplay("-# Per LFG kunnen maximaal 5 van deze rollen tegelijk worden gepingd."),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    @classmethod
    async def create(cls, cog: "LFG", owner_id: int, guild_id: int, *, notice: str | None = None):
        role_ids = await cog.allowed_ping_role_ids(guild_id)
        roles = " ".join(f"<@&{role_id}>" for role_id in sorted(role_ids)) or "Geen rolpings toegestaan."
        body = (
            f"# {NOTIFICATION_EMOJI} LFG rolpings\n"
            "> └ Whitelist precies welke rollen leden vanuit een LFG mogen pingen.\n\n"
            f"## {STATUS_EMOJI} Toegestaan\n"
            f"> └ {roles}"
        )
        return cls(cog, owner_id, guild_id, body, notice=notice)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog.config_access(interaction, self.owner_id)

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "clear":
            await self.cog.set_ping_roles(self.guild_id, [])
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigRolesView.create(self.cog, self.owner_id, self.guild_id, notice="Alle rolpings zijn uitgeschakeld."),
            )
            return
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigView.create(self.cog, self.owner_id, self.guild_id),
            )


class LFGConfigLimitsModal(discord.ui.Modal):
    def __init__(self, owner_view: "LFGConfigView", config: LFGConfig):
        super().__init__(title="LFG standaarden", timeout=300)
        self.owner_view = owner_view
        self.max_active = discord.ui.TextInput(label="Max actieve LFG's per gebruiker", default=str(config.max_active_per_user), max_length=2)
        self.duration = discord.ui.TextInput(label="Standaardduur in minuten", default=str(config.default_duration_minutes), max_length=4)
        self.reminder = discord.ui.TextInput(label="Standaard reminder in minuten", default=str(config.default_reminder_minutes), max_length=3)
        self.ping_seconds = discord.ui.TextInput(label="Rolping verwijderen na seconden", default=str(config.ping_delete_seconds), max_length=3)
        self.add_item(self.max_active)
        self.add_item(self.duration)
        self.add_item(self.reminder)
        self.add_item(self.ping_seconds)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_active = int(str(self.max_active))
            duration = int(str(self.duration))
            reminder = int(str(self.reminder))
            ping_seconds = int(str(self.ping_seconds))
        except ValueError:
            await self.owner_view.cog.send_feedback(interaction, "Gebruik alleen hele getallen.", kind="error")
            return

        if not 1 <= max_active <= 10 or not 30 <= duration <= 720 or not 0 <= reminder <= 180 or not 0 <= ping_seconds <= 60:
            await self.owner_view.cog.send_feedback(
                interaction,
                "Gebruik: actieve LFG's `1-10`, duur `30-720`, reminder `0-180`, ping verwijderen `0-60`.",
                kind="error",
                title="Waarde buiten bereik",
            )
            return

        await self.owner_view.cog.update_config(
            self.owner_view.guild_id,
            max_active_per_user=max_active,
            default_duration_minutes=duration,
            default_reminder_minutes=reminder,
            ping_delete_seconds=ping_seconds,
        )
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await LFGConfigView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice="Standaarden opgeslagen.",
            ),
        )


class LFGConfigView(discord.ui.LayoutView):
    def __init__(self, cog: "LFG", owner_id: int, guild_id: int, body: str, *, notice: str | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    ActionButton(self, "channels", "Kanalen", emoji=TEXT_EMOJI, style=discord.ButtonStyle.primary),
                    ActionButton(self, "roles", "Pingrollen", emoji=NOTIFICATION_EMOJI),
                    ActionButton(self, "thread", "Auto-thread", emoji=TEXT_EMOJI),
                    ActionButton(self, "waitlist", "Wachtlijst", emoji=USER_EMOJI),
                    ActionButton(self, "limits", "Standaarden", emoji=SETTINGS_EMOJI),
                ),
                discord.ui.TextDisplay("-# Admins en de server owner kunnen deze instellingen aanpassen."),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))

    @classmethod
    async def create(cls, cog: "LFG", owner_id: int, guild_id: int, *, notice: str | None = None):
        config = await cog.get_config(guild_id)
        allowed_channels = await cog.allowed_channel_ids(guild_id)
        roles = await cog.allowed_ping_role_ids(guild_id)
        body = (
            f"# {SETTINGS_EMOJI} LFG Config\n"
            "> └ Beheer waar LFG's mogen komen en welke meldingen ze mogen sturen.\n\n"
            f"## {TEXT_EMOJI} Publiceren\n"
            f"> └ Standaardkanaal: {f'<#{config.default_channel_id}>' if config.default_channel_id else '**niet ingesteld**'}\n"
            f"> └ Toegestane kanalen: **{'alle' if not allowed_channels else len(allowed_channels)}**\n"
            f"> └ Auto-thread standaard: **{'Aan' if config.auto_thread else 'Uit'}**\n\n"
            f"## {NOTIFICATION_EMOJI} Pings & groep\n"
            f"> └ Pingrollen toegestaan: **{len(roles)}**\n"
            f"> └ Wachtlijst standaard: **{'Aan' if config.default_waitlist else 'Uit'}**\n\n"
            f"## {STATUS_EMOJI} Standaarden\n"
            f"> └ Max actief per gebruiker: **{config.max_active_per_user}**\n"
            f"> └ Duur: **{format_duration(config.default_duration_minutes)}** • Reminder: **{config.default_reminder_minutes} min**\n"
            f"> └ Rolping verdwijnt na: **{config.ping_delete_seconds}s**"
        )
        return cls(cog, owner_id, guild_id, body, notice=notice)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog.config_access(interaction, self.owner_id)

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "channels":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigChannelsView.create(self.cog, self.owner_id, self.guild_id),
            )
            return
        if action == "roles":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigRolesView.create(self.cog, self.owner_id, self.guild_id),
            )
            return
        config = await self.cog.get_config(self.guild_id)
        if action == "thread":
            await self.cog.update_config(self.guild_id, auto_thread=not config.auto_thread)
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigView.create(self.cog, self.owner_id, self.guild_id, notice="Auto-thread standaard aangepast."),
            )
            return
        if action == "waitlist":
            await self.cog.update_config(self.guild_id, default_waitlist=not config.default_waitlist)
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await LFGConfigView.create(self.cog, self.owner_id, self.guild_id, notice="Wachtlijst standaard aangepast."),
            )
            return
        if action == "limits":
            await interaction.response.send_modal(LFGConfigLimitsModal(self, config))


# ============================================================
# OVERVIEW VIEWS
# ============================================================

class LFGOverviewView(discord.ui.LayoutView):
    def __init__(self, title: str, body: str, *, footer: str | None = None):
        super().__init__(timeout=180)
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(f"# {GAMES_EMOJI} {title}\n{body}")]
        if footer:
            children.extend(
                [
                    discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                    discord.ui.TextDisplay(f"-# {footer}"),
                ]
            )
        self.add_item(discord.ui.Container(*children, accent_colour=BRAND_COLOR))


# ============================================================
# COG
# ============================================================

class LFG(commands.Cog):
    lfg = app_commands.Group(
        name="lfg",
        description="Looking For Group op LEVENLOOS.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_lock = asyncio.Lock()
        self._registered_view_ids: set[int] = set()

    async def cog_load(self):
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError("LFG vereist Discord Components V2.")
        await init_db()
        await self.register_active_views()
        if not self.scheduler_loop.is_running():
            self.scheduler_loop.start()
        logger.info("LFG-module geladen.")

    def cog_unload(self):
        if self.scheduler_loop.is_running():
            self.scheduler_loop.cancel()

    # --------------------------------------------------------
    # FEEDBACK / ACCESS
    # --------------------------------------------------------

    async def send_feedback(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
        footer: str | None = None,
    ):
        view = FeedbackView(message, kind=kind, title=title, footer=footer)
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.response.send_message(view=view, ephemeral=True)

    async def config_access(self, interaction: discord.Interaction, owner_id: int) -> bool:
        if (
            interaction.user.id == owner_id
            and isinstance(interaction.user, discord.Member)
            and management_access(interaction.user)
        ):
            return True
        await self.send_feedback(interaction, "Dit configuratiemenu is niet van jou of je hebt geen beheerrechten.", kind="error", title="Geen toegang")
        return False

    async def can_manage_post(self, interaction: discord.Interaction, post: LFGPost) -> bool:
        if interaction.user.id == post.creator_id:
            return True
        return isinstance(interaction.user, discord.Member) and management_access(interaction.user)

    # --------------------------------------------------------
    # CONFIG DB
    # --------------------------------------------------------

    async def get_config(self, guild_id: int) -> LFGConfig:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO lfg_config (guild_id) VALUES (?)",
                (guild_id,),
            )
            await db.commit()
            cursor = await db.execute(
                """
                SELECT default_channel_id, voice_category_id, auto_thread,
                       default_waitlist, max_active_per_user,
                       default_duration_minutes, default_reminder_minutes,
                       ping_delete_seconds
                FROM lfg_config
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()
        return LFGConfig(
            guild_id=guild_id,
            default_channel_id=int(row[0] or 0),
            voice_category_id=int(row[1] or 0),
            auto_thread=bool(row[2]),
            default_waitlist=bool(row[3]),
            max_active_per_user=int(row[4] or DEFAULT_MAX_ACTIVE_PER_USER),
            default_duration_minutes=int(row[5] or DEFAULT_DURATION_MINUTES),
            default_reminder_minutes=int(row[6] or DEFAULT_REMINDER_MINUTES),
            ping_delete_seconds=int(row[7] or DEFAULT_PING_DELETE_SECONDS),
        )

    async def update_config(self, guild_id: int, **values):
        await self.get_config(guild_id)
        allowed = {
            "default_channel_id",
            "voice_category_id",
            "auto_thread",
            "default_waitlist",
            "max_active_per_user",
            "default_duration_minutes",
            "default_reminder_minutes",
            "ping_delete_seconds",
        }
        clean = {
            key: int(value) if isinstance(value, bool) else value
            for key, value in values.items()
            if key in allowed
        }
        if not clean:
            return
        assignments = ", ".join(f"{key} = ?" for key in clean)
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                f"UPDATE lfg_config SET {assignments} WHERE guild_id = ?",
                (*clean.values(), guild_id),
            )
            await db.commit()

    async def allowed_channel_ids(self, guild_id: int) -> set[int]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT channel_id FROM lfg_allowed_channels WHERE guild_id = ?",
                (guild_id,),
            )
            rows = await cursor.fetchall()
        return {int(row[0]) for row in rows}

    async def set_allowed_channels(self, guild_id: int, channel_ids: list[int]):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("DELETE FROM lfg_allowed_channels WHERE guild_id = ?", (guild_id,))
            await db.executemany(
                "INSERT INTO lfg_allowed_channels (guild_id, channel_id) VALUES (?, ?)",
                [(guild_id, int(channel_id)) for channel_id in channel_ids],
            )
            await db.commit()

    async def allowed_ping_role_ids(self, guild_id: int) -> set[int]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT role_id FROM lfg_ping_roles WHERE guild_id = ?",
                (guild_id,),
            )
            rows = await cursor.fetchall()
        return {int(row[0]) for row in rows}

    async def set_ping_roles(self, guild_id: int, role_ids: list[int]):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("DELETE FROM lfg_ping_roles WHERE guild_id = ?", (guild_id,))
            await db.executemany(
                "INSERT INTO lfg_ping_roles (guild_id, role_id) VALUES (?, ?)",
                [(guild_id, int(role_id)) for role_id in role_ids],
            )
            await db.commit()

    # --------------------------------------------------------
    # POST DB
    # --------------------------------------------------------

    async def get_post(self, lfg_id: int) -> LFGPost | None:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT id, guild_id, creator_id, title, game, description, goal,
                       start_ts, duration_minutes, slots, channel_id, message_id,
                       thread_id, voice_channel_id, auto_thread, waitlist_enabled,
                       reminder_minutes, reminder_sent, started_notified, status,
                       created_at
                FROM lfg_posts
                WHERE id = ?
                """,
                (lfg_id,),
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return LFGPost(
            id=int(row[0]), guild_id=int(row[1]), creator_id=int(row[2]),
            title=str(row[3]), game=str(row[4]), description=str(row[5]), goal=str(row[6]),
            start_ts=int(row[7]), duration_minutes=int(row[8]), slots=int(row[9]),
            channel_id=int(row[10]), message_id=int(row[11]), thread_id=int(row[12]),
            voice_channel_id=int(row[13]), auto_thread=bool(row[14]),
            waitlist_enabled=bool(row[15]), reminder_minutes=int(row[16]),
            reminder_sent=bool(row[17]), started_notified=bool(row[18]),
            status=str(row[19]), created_at=int(row[20]),
        )

    async def get_post_role_ids(self, lfg_id: int) -> list[int]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT role_id FROM lfg_post_roles WHERE lfg_id = ? ORDER BY role_id", (lfg_id,))
            rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]

    async def get_members(self, lfg_id: int) -> list[tuple[int, str, bool, int]]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT user_id, status, ready, joined_at FROM lfg_members WHERE lfg_id = ? ORDER BY joined_at ASC",
                (lfg_id,),
            )
            rows = await cursor.fetchall()
        return [(int(row[0]), str(row[1]), bool(row[2]), int(row[3])) for row in rows]

    async def active_count_for_creator(self, guild_id: int, creator_id: int) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM lfg_posts WHERE guild_id = ? AND creator_id = ? AND status IN ('open','started')",
                (guild_id, creator_id),
            )
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def active_posts(self, guild_id: int | None = None) -> list[LFGPost]:
        query = """
            SELECT id, guild_id, creator_id, title, game, description, goal,
                   start_ts, duration_minutes, slots, channel_id, message_id,
                   thread_id, voice_channel_id, auto_thread, waitlist_enabled,
                   reminder_minutes, reminder_sent, started_notified, status,
                   created_at
            FROM lfg_posts
            WHERE status IN ('open','started')
        """
        params: tuple = ()
        if guild_id is not None:
            query += " AND guild_id = ?"
            params = (guild_id,)
        query += " ORDER BY start_ts ASC"
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
        return [
            LFGPost(
                id=int(row[0]), guild_id=int(row[1]), creator_id=int(row[2]),
                title=str(row[3]), game=str(row[4]), description=str(row[5]), goal=str(row[6]),
                start_ts=int(row[7]), duration_minutes=int(row[8]), slots=int(row[9]),
                channel_id=int(row[10]), message_id=int(row[11]), thread_id=int(row[12]),
                voice_channel_id=int(row[13]), auto_thread=bool(row[14]),
                waitlist_enabled=bool(row[15]), reminder_minutes=int(row[16]),
                reminder_sent=bool(row[17]), started_notified=bool(row[18]),
                status=str(row[19]), created_at=int(row[20]),
            )
            for row in rows
        ]

    async def set_member_status(self, lfg_id: int, user_id: int, status: str):
        async with self.db_lock:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    INSERT INTO lfg_members (lfg_id, user_id, status, ready, joined_at)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(lfg_id, user_id)
                    DO UPDATE SET status = excluded.status, ready = 0, joined_at = excluded.joined_at
                    """,
                    (lfg_id, user_id, status, int(time.time())),
                )
                await db.commit()

    async def remove_member(self, lfg_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM lfg_members WHERE lfg_id = ? AND user_id = ?",
                (lfg_id, user_id),
            )
            await db.commit()
        return cursor.rowcount > 0

    async def toggle_ready(self, lfg_id: int, user_id: int) -> tuple[bool, bool]:
        async with self.db_lock:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    "SELECT status, ready FROM lfg_members WHERE lfg_id = ? AND user_id = ?",
                    (lfg_id, user_id),
                )
                row = await cursor.fetchone()
                if not row or row[0] != "joined":
                    return False, False
                new_ready = 0 if bool(row[1]) else 1
                await db.execute(
                    "UPDATE lfg_members SET ready = ? WHERE lfg_id = ? AND user_id = ?",
                    (new_ready, lfg_id, user_id),
                )
                await db.commit()
        return True, bool(new_ready)

    async def joined_count(self, lfg_id: int) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM lfg_members WHERE lfg_id = ? AND status = 'joined'",
                (lfg_id,),
            )
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def promote_waitlist(self, lfg_id: int) -> int | None:
        post = await self.get_post(lfg_id)
        if post is None or post.slots <= 0 or not post.waitlist_enabled:
            return None
        if await self.joined_count(lfg_id) >= post.slots:
            return None

        async with self.db_lock:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    """
                    SELECT user_id FROM lfg_members
                    WHERE lfg_id = ? AND status = 'waitlist'
                    ORDER BY joined_at ASC LIMIT 1
                    """,
                    (lfg_id,),
                )
                row = await cursor.fetchone()
                if not row:
                    return None
                user_id = int(row[0])
                await db.execute(
                    "UPDATE lfg_members SET status = 'joined', ready = 0, joined_at = ? WHERE lfg_id = ? AND user_id = ?",
                    (int(time.time()), lfg_id, user_id),
                )
                await db.commit()
        await self.notify_user_promotion(post, user_id)
        return user_id

    # --------------------------------------------------------
    # CARD / MESSAGE HELPERS
    # --------------------------------------------------------

    async def build_card(self, post: LFGPost) -> LFGCardView:
        return LFGCardView(
            self,
            post,
            role_ids=await self.get_post_role_ids(post.id),
            members=await self.get_members(post.id),
        )

    async def fetch_post_message(self, post: LFGPost) -> discord.Message | None:
        guild = self.bot.get_guild(post.guild_id)
        if guild is None:
            return None
        channel = guild.get_channel(post.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        try:
            return await channel.fetch_message(post.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    def post_chat_target(self, post: LFGPost):
        guild = self.bot.get_guild(post.guild_id)
        if guild is None:
            return None
        if post.thread_id:
            thread = guild.get_thread(post.thread_id)
            if thread is not None:
                return thread
        return guild.get_channel(post.channel_id)

    async def refresh_card(self, lfg_id: int) -> bool:
        post = await self.get_post(lfg_id)
        if post is None or not post.message_id:
            return False
        message = await self.fetch_post_message(post)
        if message is None:
            return False
        try:
            await message.edit(
                content=None,
                embeds=[],
                view=await self.build_card(post),
            )
            return True
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("LFG-kaart %s vernieuwen mislukt.", lfg_id)
            return False

    async def notify_user_promotion(self, post: LFGPost, user_id: int):
        guild = self.bot.get_guild(post.guild_id)
        if guild is None:
            return
        target = self.post_chat_target(post)
        if target is None:
            return
        try:
            await target.send(
                f"<@{user_id}> er is een plek vrijgekomen: je bent automatisch van de wachtlijst naar **deelnemer** geschoven.",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            logger.exception("Wachtlijstpromotie melden mislukt voor LFG %s.", post.id)

    async def register_active_views(self):
        posts = await self.active_posts()
        for post in posts:
            if post.id in self._registered_view_ids:
                continue
            try:
                self.bot.add_view(LFGPersistentControls(self, post.id))
                self._registered_view_ids.add(post.id)
            except Exception:
                logger.exception("Persistent LFG-view %s registreren mislukt.", post.id)

    # --------------------------------------------------------
    # PUBLISH
    # --------------------------------------------------------

    async def publish_draft(self, interaction: discord.Interaction, draft: LFGDraft):
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            return

        if not draft.game.strip() or not draft.title.strip():
            await self.send_feedback(interaction, "Vul eerst **Game** en **Titel** in via Basis.", kind="warning", title="Nog niet compleet")
            return
        if draft.start_ts <= int(time.time()) + 30:
            await self.send_feedback(interaction, "Kies eerst een geldige starttijd in de toekomst.", kind="warning", title="Nog niet compleet")
            return
        if not draft.channel_id:
            await self.send_feedback(interaction, "Kies eerst een LFG-kanaal.", kind="warning", title="Nog niet compleet")
            return

        allowed_channels = await self.allowed_channel_ids(guild.id)
        if allowed_channels and draft.channel_id not in allowed_channels:
            await self.send_feedback(interaction, "Het gekozen kanaal is niet meer toegestaan.", kind="error")
            return

        allowed_roles = await self.allowed_ping_role_ids(guild.id)
        if any(role_id not in allowed_roles for role_id in draft.role_ids):
            await self.send_feedback(interaction, "Een gekozen rolping is niet meer toegestaan.", kind="error")
            return

        config = await self.get_config(guild.id)
        if await self.active_count_for_creator(guild.id, interaction.user.id) >= config.max_active_per_user and not management_access(interaction.user):
            await self.send_feedback(
                interaction,
                f"Je hebt al het maximum van **{config.max_active_per_user} actieve LFG's** bereikt.",
                kind="warning",
                title="Maximum bereikt",
            )
            return

        channel = guild.get_channel(draft.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await self.send_feedback(interaction, "Het gekozen LFG-kanaal bestaat niet meer.", kind="error")
            return

        me = guild.me
        if me is None or not channel.permissions_for(me).send_messages:
            await self.send_feedback(interaction, "Ik kan niet sturen in het gekozen kanaal.", kind="error", title="Ontbrekende permissie")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        async with self.db_lock:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO lfg_posts (
                        guild_id, creator_id, title, game, description, goal,
                        start_ts, duration_minutes, slots, channel_id,
                        voice_channel_id, auto_thread, waitlist_enabled,
                        reminder_minutes, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                    """,
                    (
                        guild.id,
                        interaction.user.id,
                        draft.title.strip(),
                        draft.game.strip(),
                        draft.description.strip(),
                        draft.goal.strip() or "Casual",
                        draft.start_ts,
                        draft.duration_minutes,
                        draft.slots,
                        draft.channel_id,
                        draft.voice_channel_id,
                        int(draft.auto_thread),
                        int(draft.waitlist_enabled),
                        draft.reminder_minutes,
                        int(time.time()),
                    ),
                )
                lfg_id = int(cursor.lastrowid)
                await db.executemany(
                    "INSERT INTO lfg_post_roles (lfg_id, role_id) VALUES (?, ?)",
                    [(lfg_id, role_id) for role_id in draft.role_ids],
                )
                await db.execute(
                    "INSERT INTO lfg_members (lfg_id, user_id, status, ready, joined_at) VALUES (?, ?, 'joined', 0, ?)",
                    (lfg_id, interaction.user.id, int(time.time())),
                )
                await db.commit()

        post = await self.get_post(lfg_id)
        if post is None:
            await interaction.followup.send(view=FeedbackView("De LFG kon niet uit de database worden geladen.", kind="error"), ephemeral=True)
            return

        try:
            message = await channel.send(
                view=await self.build_card(post),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception("LFG %s publiceren mislukt.", lfg_id)
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("UPDATE lfg_posts SET status = 'cancelled' WHERE id = ?", (lfg_id,))
                await db.commit()
            await interaction.followup.send(view=FeedbackView("Discord kon de LFG-kaart niet plaatsen.", kind="error"), ephemeral=True)
            return

        thread_id = 0
        if draft.auto_thread:
            try:
                thread = await message.create_thread(
                    name=shorten(f"LFG • {draft.game} • {interaction.user.display_name}", 90),
                    auto_archive_duration=1440,
                    reason=f"Automatische LFG-thread #{lfg_id}",
                )
                thread_id = thread.id
                await thread.send(
                    f"# {GAMES_EMOJI} LFG-chat\n> └ Gebruik deze thread voor afstemming zonder het hoofdkanaal vol te laten lopen."
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Kon thread voor LFG %s niet aanmaken.", lfg_id)

        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "UPDATE lfg_posts SET message_id = ?, thread_id = ? WHERE id = ?",
                (message.id, thread_id, lfg_id),
            )
            await db.commit()

        if draft.role_ids:
            mention_text = " ".join(f"<@&{role_id}>" for role_id in draft.role_ids)
            try:
                await channel.send(
                    f"{NOTIFICATION_EMOJI} Nieuwe LFG voor {mention_text} • **{shorten(draft.game, 80)}**",
                    allowed_mentions=discord.AllowedMentions(users=False, roles=True, everyone=False),
                    delete_after=config.ping_delete_seconds if config.ping_delete_seconds > 0 else None,
                )
            except discord.HTTPException:
                logger.warning("Rolping voor LFG %s kon niet worden verstuurd.", lfg_id)

        await self.refresh_card(lfg_id)
        if lfg_id not in self._registered_view_ids:
            try:
                self.bot.add_view(LFGPersistentControls(self, lfg_id))
                self._registered_view_ids.add(lfg_id)
            except Exception:
                logger.exception("Nieuwe persistent LFG-view registreren mislukt voor %s.", lfg_id)

        await interaction.followup.send(
            view=FeedbackView(
                f"Je LFG is gepubliceerd in {channel.mention}.\nLFG-ID: **#{lfg_id}**",
                kind="success",
                title="LFG gepubliceerd",
                footer="Je staat zelf direct als deelnemer ingeschreven.",
            ),
            ephemeral=True,
        )

    # --------------------------------------------------------
    # PUBLIC ACTIONS
    # --------------------------------------------------------

    async def handle_public_action(self, interaction: discord.Interaction, lfg_id: int, action: str):
        post = await self.get_post(lfg_id)
        if post is None or post.guild_id != getattr(interaction.guild, "id", None):
            await self.send_feedback(interaction, "Deze LFG bestaat niet meer.", kind="error")
            return

        if action == "manage":
            if not await self.can_manage_post(interaction, post):
                await self.send_feedback(interaction, "Alleen de maker of serverbeheer kan deze LFG beheren.", kind="error", title="Geen toegang")
                return
            await interaction.response.send_message(
                view=await self.build_manage_view(interaction.user.id, lfg_id),
                ephemeral=True,
            )
            return

        if post.status in {"closed", "cancelled"}:
            await self.send_feedback(interaction, "Deze LFG is al gesloten.", kind="warning")
            return

        if action == "join":
            members = await self.get_members(lfg_id)
            current = next((row for row in members if row[0] == interaction.user.id), None)
            if current and current[1] == "joined":
                await self.send_feedback(interaction, "Je doet al mee aan deze LFG.", kind="info")
                return

            joined = sum(1 for row in members if row[1] == "joined")
            if post.slots > 0 and joined >= post.slots:
                if not post.waitlist_enabled:
                    await self.send_feedback(interaction, "Deze LFG zit vol en de wachtlijst staat uit.", kind="warning", title="Vol")
                    return
                status = "waitlist"
                notice = "De LFG zit vol; je staat nu op de **wachtlijst**. Je schuift automatisch door wanneer er een plek vrijkomt."
            else:
                status = "joined"
                notice = "Je doet mee aan deze LFG."
            await self.set_member_status(lfg_id, interaction.user.id, status)
            await interaction.response.defer(ephemeral=True)
            await self.refresh_card(lfg_id)
            await interaction.followup.send(view=FeedbackView(notice, kind="success"), ephemeral=True)
            return

        if action == "maybe":
            if interaction.user.id == post.creator_id:
                await self.send_feedback(interaction, "Als maker sta je al als deelnemer ingeschreven.", kind="info")
                return
            await self.set_member_status(lfg_id, interaction.user.id, "maybe")
            await interaction.response.defer(ephemeral=True)
            await self.refresh_card(lfg_id)
            await interaction.followup.send(view=FeedbackView("Je staat nu op **Misschien**. Dit gebruikt geen spelersplek.", kind="success"), ephemeral=True)
            return

        if action == "leave":
            if interaction.user.id == post.creator_id:
                await self.send_feedback(interaction, "De maker kan zichzelf niet afmelden. Sluit of annuleer de LFG via Beheer.", kind="warning")
                return
            removed = await self.remove_member(lfg_id, interaction.user.id)
            if not removed:
                await self.send_feedback(interaction, "Je stond niet in deze LFG.", kind="info")
                return
            await interaction.response.defer(ephemeral=True)
            promoted = await self.promote_waitlist(lfg_id)
            await self.refresh_card(lfg_id)
            message = "Je bent afgemeld."
            if promoted:
                message += f"\n<@{promoted}> is automatisch doorgeschoven vanaf de wachtlijst."
            await interaction.followup.send(view=FeedbackView(message, kind="success"), ephemeral=True)
            return

        if action == "ready":
            ok, ready = await self.toggle_ready(lfg_id, interaction.user.id)
            if not ok:
                await self.send_feedback(interaction, "Je moet eerst als **deelnemer** in deze LFG staan.", kind="warning")
                return
            await interaction.response.defer(ephemeral=True)
            await self.refresh_card(lfg_id)
            await interaction.followup.send(
                view=FeedbackView(
                    "Je staat nu als **Klaar** gemarkeerd." if ready else "Je Klaar-status is weer uitgezet.",
                    kind="success",
                ),
                ephemeral=True,
            )

    # --------------------------------------------------------
    # MANAGE ACTIONS
    # --------------------------------------------------------

    async def build_manage_view(self, owner_id: int, lfg_id: int, *, notice: str | None = None) -> LFGManageView:
        post = await self.get_post(lfg_id)
        if post is None:
            raise ValueError("LFG bestaat niet")
        members = await self.get_members(lfg_id)
        joined = [row for row in members if row[1] == "joined"]
        waitlist = [row for row in members if row[1] == "waitlist"]
        maybe = [row for row in members if row[1] == "maybe"]
        ready = sum(1 for row in joined if row[2])
        summary = (
            f"# {SETTINGS_EMOJI} LFG Beheer • #{post.id}\n"
            f"> └ **{shorten(post.game, 60)} • {shorten(post.title, 70)}**\n\n"
            f"## {STATUS_EMOJI} Status\n"
            f"> └ {post_status_label(post.status)} • <t:{post.start_ts}:R>\n"
            f"> └ Deelnemers: **{len(joined)}** • Wachtlijst: **{len(waitlist)}** • Misschien: **{len(maybe)}**\n"
            f"> └ Klaar: **{ready}/{len(joined)}**"
        )
        if notice:
            summary += f"\n\n> └ {SUCCESS_EMOJI} {notice}"
        return LFGManageView(self, owner_id, post, summary)

    async def start_post_now(self, interaction: discord.Interaction, lfg_id: int):
        post = await self.get_post(lfg_id)
        if post is None:
            return
        now = int(time.time())
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "UPDATE lfg_posts SET start_ts = ?, status = 'started', started_notified = 1, reminder_sent = 1 WHERE id = ?",
                (now, lfg_id),
            )
            await db.commit()
        await interaction.response.defer(ephemeral=True)
        await self.send_start_notification(await self.get_post(lfg_id))
        await self.refresh_card(lfg_id)
        await interaction.followup.send(view=FeedbackView("De LFG is nu gestart.", kind="success"), ephemeral=True)

    async def close_post(self, interaction: discord.Interaction, lfg_id: int, *, cancelled: bool):
        status = "cancelled" if cancelled else "closed"
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE lfg_posts SET status = ? WHERE id = ?", (status, lfg_id))
            await db.commit()
        await interaction.response.defer(ephemeral=True)
        await self.refresh_card(lfg_id)
        post = await self.get_post(lfg_id)
        if post and post.thread_id:
            guild = self.bot.get_guild(post.guild_id)
            thread = guild.get_thread(post.thread_id) if guild else None
            if thread:
                try:
                    await thread.edit(archived=True, locked=False, reason="LFG gesloten")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await interaction.followup.send(
            view=FeedbackView(
                "De LFG is geannuleerd." if cancelled else "De LFG is gesloten.",
                kind="success",
            ),
            ephemeral=True,
        )

    async def ping_participants(self, interaction: discord.Interaction, lfg_id: int):
        post = await self.get_post(lfg_id)
        if post is None:
            return
        members = await self.get_members(lfg_id)
        ids = [user_id for user_id, status, _, _ in members if status in {"joined", "waitlist"}]
        if not ids:
            await self.send_feedback(interaction, "Er zijn nog geen deelnemers om te pingen.", kind="info")
            return
        guild = interaction.guild
        target = self.post_chat_target(post)
        if target is None:
            await self.send_feedback(interaction, "Het LFG-kanaal bestaat niet meer.", kind="error")
            return
        await interaction.response.defer(ephemeral=True)
        mentions = " ".join(f"<@{user_id}>" for user_id in ids[:40])
        try:
            await target.send(
                f"{NOTIFICATION_EMOJI} {mentions}\n> └ De host van LFG **#{lfg_id}** vraagt even jullie aandacht.",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            await interaction.followup.send(view=FeedbackView("De deelnemers konden niet worden gepingd.", kind="error"), ephemeral=True)
            return
        await interaction.followup.send(view=FeedbackView("Deelnemers zijn gepingd in de LFG-chat.", kind="success"), ephemeral=True)

    # --------------------------------------------------------
    # SCHEDULER
    # --------------------------------------------------------

    async def send_reminder(self, post: LFGPost):
        guild = self.bot.get_guild(post.guild_id)
        if guild is None:
            return
        members = await self.get_members(post.id)
        ids = [user_id for user_id, status, _, _ in members if status == "joined"]
        target = self.post_chat_target(post)
        if target is None:
            return
        mentions = " ".join(f"<@{user_id}>" for user_id in ids[:40])
        try:
            await target.send(
                f"{NOTIFICATION_EMOJI} {mentions}\n> └ **{shorten(post.game, 70)}** start <t:{post.start_ts}:R>. Zet jezelf op **Klaar** zodra je er bent.",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            logger.exception("LFG reminder %s versturen mislukt.", post.id)

    async def resolve_smart_voice(self, post: LFGPost) -> LFGPost:
        """Koppel bij de start automatisch de huidige voice van de host als er nog geen voice gekozen was."""
        if post.voice_channel_id:
            return post

        guild = self.bot.get_guild(post.guild_id)
        if guild is None:
            return post

        creator = guild.get_member(post.creator_id)
        if (
            creator is None
            or creator.voice is None
            or creator.voice.channel is None
        ):
            return post

        voice_channel_id = creator.voice.channel.id
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "UPDATE lfg_posts SET voice_channel_id = ? WHERE id = ?",
                (voice_channel_id, post.id),
            )
            await db.commit()

        refreshed = await self.get_post(post.id)
        return refreshed or post

    async def send_start_notification(self, post: LFGPost | None):
        if post is None:
            return
        post = await self.resolve_smart_voice(post)
        guild = self.bot.get_guild(post.guild_id)
        if guild is None:
            return
        members = await self.get_members(post.id)
        ids = [user_id for user_id, status, _, _ in members if status == "joined"]
        target = self.post_chat_target(post)
        if target is None:
            return
        mentions = " ".join(f"<@{user_id}>" for user_id in ids[:40])
        voice = f"\n> └ Voice: <#{post.voice_channel_id}>" if post.voice_channel_id else ""
        try:
            await target.send(
                f"# {GAMES_EMOJI} LFG begint nu\n> └ {mentions}\n> └ **{shorten(post.game, 70)} • {shorten(post.title, 80)}**{voice}",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            logger.exception("LFG startmelding %s versturen mislukt.", post.id)

    @tasks.loop(minutes=1)
    async def scheduler_loop(self):
        now = int(time.time())
        for post in await self.active_posts():
            try:
                if (
                    post.status == "open"
                    and not post.reminder_sent
                    and post.reminder_minutes > 0
                    and now >= post.start_ts - post.reminder_minutes * 60
                    and now < post.start_ts
                ):
                    await self.send_reminder(post)
                    async with aiosqlite.connect(DATABASE_PATH) as db:
                        await db.execute("UPDATE lfg_posts SET reminder_sent = 1 WHERE id = ?", (post.id,))
                        await db.commit()

                if post.status == "open" and now >= post.start_ts:
                    async with aiosqlite.connect(DATABASE_PATH) as db:
                        await db.execute(
                            "UPDATE lfg_posts SET status = 'started', started_notified = 1, reminder_sent = 1 WHERE id = ?",
                            (post.id,),
                        )
                        await db.commit()
                    post = await self.get_post(post.id)
                    await self.send_start_notification(post)
                    await self.refresh_card(post.id)

                if post and post.status == "started" and post.duration_minutes > 0:
                    if now >= post.start_ts + post.duration_minutes * 60:
                        async with aiosqlite.connect(DATABASE_PATH) as db:
                            await db.execute("UPDATE lfg_posts SET status = 'closed' WHERE id = ?", (post.id,))
                            await db.commit()
                        await self.refresh_card(post.id)
                        guild = self.bot.get_guild(post.guild_id)
                        thread = guild.get_thread(post.thread_id) if guild and post.thread_id else None
                        if thread:
                            try:
                                await thread.send(f"{STATUS_EMOJI} Deze LFG is automatisch gesloten omdat de geplande duur voorbij is.")
                                await thread.edit(archived=True, reason="LFG automatisch afgerond")
                            except (discord.Forbidden, discord.HTTPException):
                                pass
            except Exception:
                logger.exception("LFG scheduler fout bij post %s.", post.id)

    @scheduler_loop.before_loop
    async def before_scheduler_loop(self):
        await self.bot.wait_until_ready()

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    @lfg.command(name="maken", description="Maak een geavanceerde Looking For Group.")
    async def maken(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await self.send_feedback(interaction, "Dit command werkt alleen in een server.", kind="error")
            return
        config = await self.get_config(interaction.guild.id)
        allowed = await self.allowed_channel_ids(interaction.guild.id)
        default_channel_id = config.default_channel_id
        if default_channel_id and allowed and default_channel_id not in allowed:
            default_channel_id = 0
        if not default_channel_id and isinstance(interaction.channel, discord.TextChannel):
            if not allowed or interaction.channel.id in allowed:
                default_channel_id = interaction.channel.id
        draft = LFGDraft(
            guild_id=interaction.guild.id,
            creator_id=interaction.user.id,
            duration_minutes=config.default_duration_minutes,
            channel_id=default_channel_id,
            auto_thread=config.auto_thread,
            waitlist_enabled=config.default_waitlist,
            reminder_minutes=config.default_reminder_minutes,
        )
        await interaction.response.send_message(
            view=await LFGBuilderView.create(self, interaction.user.id, draft),
            ephemeral=True,
        )

    @lfg.command(name="overzicht", description="Bekijk alle actieve LFG's.")
    async def overzicht(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        posts = (await self.active_posts(interaction.guild.id))[:MAX_OVERVIEW_ITEMS]
        if not posts:
            await self.send_feedback(interaction, "Er zijn momenteel geen actieve LFG's.", kind="info", title="LFG overzicht")
            return
        lines = []
        for post in posts:
            members = await self.get_members(post.id)
            joined = sum(1 for row in members if row[1] == "joined")
            capacity = "∞" if post.slots <= 0 else str(post.slots)
            lines.append(
                f"> └ **#{post.id} • {shorten(post.game, 35)}** — {shorten(post.title, 45)}\n"
                f">   <t:{post.start_ts}:R> • {joined}/{capacity} • <#{post.channel_id}>"
            )
        await interaction.response.send_message(
            view=LFGOverviewView(
                "Actieve LFG's",
                "\n".join(lines),
                footer="Gebruik /lfg beheer <id> als je maker of beheerder bent.",
            ),
            ephemeral=True,
        )

    @lfg.command(name="mijn", description="Bekijk je eigen LFG's en deelnames.")
    async def mijn(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        async with aiosqlite.connect(DATABASE_PATH) as db:
            created_cursor = await db.execute(
                "SELECT id, game, title, start_ts, status FROM lfg_posts WHERE guild_id = ? AND creator_id = ? AND status IN ('open','started') ORDER BY start_ts",
                (interaction.guild.id, interaction.user.id),
            )
            created = await created_cursor.fetchall()
            joined_cursor = await db.execute(
                """
                SELECT p.id, p.game, p.title, p.start_ts, m.status
                FROM lfg_members m
                JOIN lfg_posts p ON p.id = m.lfg_id
                WHERE p.guild_id = ? AND m.user_id = ? AND p.status IN ('open','started') AND p.creator_id != ?
                ORDER BY p.start_ts
                """,
                (interaction.guild.id, interaction.user.id, interaction.user.id),
            )
            joined = await joined_cursor.fetchall()
        lines = ["## Gemaakt"]
        lines.extend(
            f"> └ **#{row[0]} • {shorten(row[1], 35)}** — <t:{int(row[3])}:R> • {post_status_label(str(row[4]))}"
            for row in created[:8]
        )
        if not created:
            lines.append("> └ Geen actieve eigen LFG's.")
        lines.append("\n## Deelname")
        lines.extend(
            f"> └ **#{row[0]} • {shorten(row[1], 35)}** — <t:{int(row[3])}:R> • **{str(row[4]).title()}**"
            for row in joined[:8]
        )
        if not joined:
            lines.append("> └ Je staat nergens anders ingeschreven.")
        await interaction.response.send_message(
            view=LFGOverviewView("Mijn LFG", "\n".join(lines)),
            ephemeral=True,
        )

    @lfg.command(name="beheer", description="Beheer een LFG die jij hebt gemaakt.")
    async def beheer(self, interaction: discord.Interaction, id: int | None = None):
        if interaction.guild is None:
            return
        post = await self.get_post(id) if id else None
        if post is None and id is None:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    "SELECT id FROM lfg_posts WHERE guild_id = ? AND creator_id = ? AND status IN ('open','started') ORDER BY created_at DESC LIMIT 1",
                    (interaction.guild.id, interaction.user.id),
                )
                row = await cursor.fetchone()
            if row:
                post = await self.get_post(int(row[0]))
        if post is None or post.guild_id != interaction.guild.id:
            await self.send_feedback(interaction, "LFG niet gevonden. Geef eventueel het ID mee, bijvoorbeeld `/lfg beheer 12`.", kind="error")
            return
        if not await self.can_manage_post(interaction, post):
            await self.send_feedback(interaction, "Je mag deze LFG niet beheren.", kind="error", title="Geen toegang")
            return
        await interaction.response.send_message(
            view=await self.build_manage_view(interaction.user.id, post.id),
            ephemeral=True,
        )

    @lfg.command(name="config", description="Open het LFG-configuratiepaneel.")
    async def config_command(self, interaction: discord.Interaction):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await self.send_feedback(interaction, "Alleen serverbeheer kan LFG configureren.", kind="error", title="Geen toegang")
            return
        await interaction.response.send_message(
            view=await LFGConfigView.create(self, interaction.user.id, interaction.guild.id),
            ephemeral=True,
        )

    @lfg.command(name="status", description="Bekijk de status van het LFG-systeem.")
    async def status_command(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return
        config = await self.get_config(interaction.guild.id)
        active = await self.active_posts(interaction.guild.id)
        channels = await self.allowed_channel_ids(interaction.guild.id)
        roles = await self.allowed_ping_role_ids(interaction.guild.id)
        body = (
            f"> └ Scheduler: **{'Actief' if self.scheduler_loop.is_running() else 'Gestopt'}**\n"
            f"> └ Actieve LFG's: **{len(active)}**\n"
            f"> └ Toegestane kanalen: **{'alle' if not channels else len(channels)}**\n"
            f"> └ Pingrollen: **{len(roles)}**\n"
            f"> └ Default kanaal: {f'<#{config.default_channel_id}>' if config.default_channel_id else '**niet ingesteld**'}\n"
            f"> └ Auto-thread: **{'Aan' if config.auto_thread else 'Uit'}**"
        )
        await interaction.response.send_message(
            view=LFGOverviewView("LFG status", body, footer="Admins kunnen alles aanpassen via /lfg config."),
            ephemeral=True,
        )

    @lfg.command(name="info", description="Bekijk hoe het LFG-systeem werkt.")
    async def info_command(self, interaction: discord.Interaction):
        body = (
            f"## {ADD_EMOJI} Maken\n"
            "> └ `/lfg maken` opent een wizard voor game, tijd, duur, spelers, kanaal, rolpings en voice.\n\n"
            f"## {USER_EMOJI} Deelnemen\n"
            "> └ Vol? Dan kom je automatisch op de wachtlijst en schuif je door zodra er plek is.\n"
            "> └ **Misschien** reserveert geen plek. **Klaar** is de check-in voor de start.\n\n"
            f"## {NOTIFICATION_EMOJI} Automatisch\n"
            "> └ Reminders, startmeldingen, automatische afsluiting en optionele LFG-threads worden door de bot geregeld.\n"
            "> └ Geen voice gekozen? Bij de start koppelt de bot automatisch de huidige voice van de host als die in een kanaal zit.\n\n"
            f"## {SETTINGS_EMOJI} Beheer\n"
            "> └ De maker kan deelnemers pingen/verwijderen, direct starten, sluiten of annuleren."
        )
        await interaction.response.send_message(
            view=LFGOverviewView("Looking For Group", body),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LFG(bot))
