from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks

try:
    from cogs.games import ACTIVE_GAME_CATEGORY_ID, management_access
except ImportError:
    ACTIVE_GAME_CATEGORY_ID = 940987098427707412

    def management_access(member: discord.Member) -> bool:
        if member.guild.owner_id == member.id:
            return True
        if member.guild_permissions.administrator:
            return True
        names = {role.name.lower() for role in member.roles}
        return "admin" in names or "owner" in names


DATABASE_PATH = "levenloos.db"
BRAND_COLOR = discord.Color.from_str("#6C27DA")
EVENT_CREATOR_ROLE_ID = 985989826950086717
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
DEFAULT_DURATION_MINUTES = 120
DEFAULT_POLL_HOURS = 24
VOICE_OPEN_MINUTES = 15
MAX_SLOTS_LIMIT = 99
EVENT_BANNER = "<:E1:1546897508738007081><:E2:1546897546964639754><:E3:1546897578719973377><:E4:1546897598022029368><:E5:1546897622453854238><:E6:1546897645786890374><:E7:1546897666355494963>"

EVENT_EMOJI = "<:events:1547854148601643008>"
GAMES_EMOJI = "<:gamesbutton:1547854165097717801>"
TIME_EMOJI = "<:tijd:1547854182298550373>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"
VOICE_EMOJI = "<:voice:1547737205429243924>"
USER_EMOJI = "<:user:1547737210986692679>"
LIST_EMOJI = "<:list:1547733039361163427>"

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
NONE_EMOJI = "<:none:1547724038955208794>"

logger = logging.getLogger(__name__)

STATUS_PLANNING = "planning"
STATUS_CONFIRMED = "confirmed"
STATUS_ACTIVE = "active"
STATUS_ENDED = "ended"
STATUS_CANCELLED = "cancelled"


# =========================================================
# HELPERS
# =========================================================


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_db(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def from_db(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def discord_ts(dt: datetime | None, style: str = "F") -> str:
    if not dt:
        return "Nog niet bepaald"
    return f"<t:{int(dt.timestamp())}:{style}>"


def parse_date(value: str) -> datetime:
    raw = value.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    raise ValueError("Gebruik voor de datum bijvoorbeeld `12-09-2026`.")


def parse_time(value: str) -> tuple[int, int]:
    raw = value.strip().replace(".", ":")
    for fmt in ("%H:%M", "%H"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.hour, parsed.minute
        except ValueError:
            pass
    raise ValueError(f"Ongeldige tijd `{value}`. Gebruik bijvoorbeeld `20:00`.")


def combine_amsterdam(date_value: str, time_value: str) -> datetime:
    date = parse_date(date_value)
    hour, minute = parse_time(time_value)
    local = datetime(date.year, date.month, date.day, hour, minute, tzinfo=AMSTERDAM)
    return local.astimezone(timezone.utc)


def clean_voice_name(name: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip()
    text = re.sub(r"\s+", "-", text).lower()
    return (text or "event")[:80]


def truncate(text: str, length: int) -> str:
    text = text.strip()
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def human_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}u {mins}m"
    if hours:
        return f"{hours} uur"
    return f"{mins} min"


def status_label(status: str) -> str:
    return {
        STATUS_PLANNING: "Planning",
        STATUS_CONFIRMED: "Bevestigd",
        STATUS_ACTIVE: "Bezig",
        STATUS_ENDED: "Afgelopen",
        STATUS_CANCELLED: "Geannuleerd",
    }.get(status, status.title())



def component_emoji(
    value: str | None,
) -> discord.PartialEmoji | None:
    if not value:
        return None

    try:
        emoji = discord.PartialEmoji.from_str(value)
    except Exception:
        logger.warning(
            "Kon custom emoji niet parsen: %s",
            value,
        )
        return None

    return emoji if emoji.name else None


def feedback_style(
    kind: str,
) -> tuple[str, str, discord.Colour]:
    if kind == "success":
        return (
            "Gelukt",
            SUCCESS_EMOJI,
            discord.Colour.from_rgb(87, 242, 135),
        )

    if kind == "error":
        return (
            "Fout",
            ERROR_EMOJI,
            discord.Colour.from_rgb(237, 66, 69),
        )

    if kind == "warning":
        return (
            "Let op",
            WARNING_EMOJI,
            discord.Colour.from_rgb(254, 231, 92),
        )

    return (
        "Informatie",
        INFO_EMOJI,
        BRAND_COLOR,
    )


@dataclass(slots=True)
class WizardState:
    guild_id: int
    author_id: int
    channel_id: int
    event_type: str = "Game Night"
    game_name: str | None = None
    game_role_id: int | None = None
    description: str = ""
    duration_minutes: int = DEFAULT_DURATION_MINUTES
    max_slots: int = 0
    time_options: list[datetime] = field(default_factory=list)
    game_options: list[tuple[str, int | None]] = field(default_factory=list)
    temporary_voice: bool = True


# =========================================================
# COMPONENTS V2 / SETUP MODALS
# =========================================================


EVENT_TYPES: tuple[tuple[str, str, str], ...] = (
    (
        "Game Night",
        "game_night",
        "Meerdere games op één avond, eventueel met game-stemming.",
    ),
    (
        "Casual Gaming",
        "casual",
        "Relaxed samen gamen zonder competitieve insteek.",
    ),
    (
        "Party Games",
        "party",
        "Party games zoals Among Us, PEAK of Pummel Party.",
    ),
    (
        "Competitive",
        "competitive",
        "Ranked, toernooi of een serieuzere speelsessie.",
    ),
    (
        "Community Event",
        "community",
        "Een bredere serveractiviteit of community-avond.",
    ),
    (
        "Anders",
        "other",
        "Voor een event dat niet in de andere types past.",
    ),
)

EVENT_TYPE_BY_VALUE = {
    value: label
    for label, value, _ in EVENT_TYPES
}

EVENT_TYPE_VALUE_BY_LABEL = {
    label: value
    for label, value, _ in EVENT_TYPES
}


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

        default_title, icon, accent = feedback_style(
            kind
        )

        lines = [
            f"> └ {line}"
            for line in message.splitlines()
            if line.strip()
        ]

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"# {icon} {title or default_title}\n"
                + "\n".join(lines)
            )
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
                accent_colour=accent,
            )
        )


class EventSetupModal(discord.ui.Modal):
    """First setup page: event identity, games and general behaviour."""

    def __init__(
        self,
        cog: "Events",
        state: WizardState,
        guild: discord.Guild,
    ):
        super().__init__(
            title="Event maken"
        )

        self.cog = cog
        self.state = state

        self.name = discord.ui.TextInput(
            label="Event naam",
            placeholder="Bijv. Party Game Night",
            required=False,
            default=state.game_name or None,
            max_length=100,
        )

        self.description = discord.ui.TextInput(
            label="Beschrijving",
            placeholder="Wat gaan jullie doen?",
            style=discord.TextStyle.paragraph,
            required=False,
            default=state.description or None,
            max_length=1000,
        )

        selected_type = (
            EVENT_TYPE_VALUE_BY_LABEL.get(
                state.event_type,
                "game_night",
            )
        )

        self.event_type = discord.ui.RadioGroup(
            required=True,
            options=[
                discord.RadioGroupOption(
                    label=label,
                    value=value,
                    description=description,
                    default=(
                        value == selected_type
                    ),
                )
                for label, value, description
                in EVENT_TYPES
            ],
        )

        selected_game_ids = {
            role_id
            for _, role_id
            in state.game_options
            if role_id is not None
        }

        games = cog.active_games(
            guild
        )[:25]

        self.games_select = None

        if games:
            self.games_select = discord.ui.Select(
                placeholder="Kies games (optioneel)",
                min_values=0,
                max_values=min(
                    10,
                    len(games),
                ),
                required=False,
                options=[
                    discord.SelectOption(
                        label=truncate(
                            name,
                            100,
                        ),
                        value=str(role_id),
                        default=(
                            role_id
                            in selected_game_ids
                        ),
                    )
                    for name, role_id in games
                ],
            )

        self.options = discord.ui.CheckboxGroup(
            required=False,
            min_values=0,
            max_values=1,
            options=[
                discord.CheckboxGroupOption(
                    label="Tijdelijk voicekanaal maken",
                    value="temporary_voice",
                    description=(
                        "Wordt 15 minuten voor de start geopend "
                        "en na afloop opgeruimd."
                    ),
                    default=state.temporary_voice,
                )
            ],
        )

        self.add_item(
            self.name
        )
        self.add_item(
            self.description
        )
        self.add_item(
            discord.ui.Label(
                text="Type event",
                description=(
                    "Dit beschrijft de soort avond; "
                    "de games kies je hieronder apart."
                ),
                component=self.event_type,
            )
        )

        if self.games_select is not None:
            self.add_item(
                discord.ui.Label(
                    text="Games",
                    description=(
                        "Kies actieve games. Staat je game er niet bij? "
                        "Voeg die daarna toe via Anders / eigen games."
                    ),
                    component=self.games_select,
                )
            )

        self.add_item(
            discord.ui.Label(
                text="Extra opties",
                description=(
                    "Algemene opties voor het event."
                ),
                component=self.options,
            )
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await self.cog.send_feedback(
                interaction,
                "Server niet gevonden.",
                kind="error",
            )
            return

        type_value = (
            self.event_type.value
            or "game_night"
        )

        self.state.event_type = (
            EVENT_TYPE_BY_VALUE.get(
                type_value,
                "Game Night",
            )
        )

        custom_name = str(
            self.name
        ).strip()

        self.state.game_name = (
            custom_name
            or self.state.event_type
        )

        self.state.game_role_id = None
        self.state.description = str(
            self.description
        ).strip()

        self.state.temporary_voice = (
            "temporary_voice"
            in set(
                self.options.values
                or []
            )
        )

        choices: list[
            tuple[str, int | None]
        ] = []

        if self.games_select is not None:
            for raw_id in (
                self.games_select.values
            ):
                role = interaction.guild.get_role(
                    int(raw_id)
                )

                if role is not None:
                    choices.append(
                        (
                            role.name
                            .removeprefix("◆")
                            .strip(),
                            role.id,
                        )
                    )

        # Eigen handmatig ingevoerde game-opties blijven behouden wanneer
        # iemand later alleen de basis van het event opnieuw aanpast.
        custom_choices = [
            (
                name,
                None,
            )
            for name, role_id
            in self.state.game_options
            if role_id is None
        ]

        self.state.game_options = (
            choices
            + custom_choices
        )

        view = SetupContinueView(
            self.cog,
            self.state,
        )

        if interaction.message is not None:
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=view,
            )
        else:
            await interaction.response.send_message(
                view=view,
                ephemeral=True,
            )



class CustomGamesModal(discord.ui.Modal):
    """Allow event creators to add games that are not active server games."""

    def __init__(
        self,
        cog: "Events",
        state: WizardState,
    ):
        super().__init__(
            title="Andere games"
        )

        self.cog = cog
        self.state = state

        current_custom = [
            name
            for name, role_id
            in state.game_options
            if role_id is None
        ]

        self.games = discord.ui.TextInput(
            label="Eigen game-opties",
            placeholder=(
                "Bijv. Helldivers 2, Lethal Company, Mario Kart"
            ),
            style=discord.TextStyle.paragraph,
            required=False,
            default=(
                "\n".join(
                    current_custom
                )
                or None
            ),
            max_length=1000,
        )

        self.add_item(
            self.games
        )

    @staticmethod
    def parse_games(
        raw: str,
    ) -> list[str]:
        values = [
            value.strip()
            for value in re.split(
                r"[\n,;]+",
                raw,
            )
            if value.strip()
        ]

        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            cleaned = truncate(
                value,
                100,
            )
            key = cleaned.casefold()

            if key in seen:
                continue

            seen.add(
                key
            )
            result.append(
                cleaned
            )

        return result

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        custom_games = self.parse_games(
            str(
                self.games
            )
        )

        active_choices = [
            (
                name,
                role_id,
            )
            for name, role_id
            in self.state.game_options
            if role_id is not None
        ]

        active_names = {
            name.casefold()
            for name, _
            in active_choices
        }

        # Een handmatige optie die hetzelfde heet als een gekozen actieve game
        # hoeft niet dubbel in de stemming te verschijnen.
        custom_games = [
            name
            for name in custom_games
            if name.casefold()
            not in active_names
        ]

        total = (
            len(active_choices)
            + len(custom_games)
        )

        if total > 10:
            await self.cog.send_feedback(
                interaction,
                (
                    "Een event ondersteunt maximaal **10 game-opties**.\n"
                    f"Je hebt nu **{len(active_choices)} actieve games** "
                    f"en **{len(custom_games)} eigen opties** geselecteerd."
                ),
                kind="error",
                title="Te veel games",
            )
            return

        self.state.game_options = (
            active_choices
            + [
                (
                    name,
                    None,
                )
                for name in custom_games
            ]
        )

        view = SetupContinueView(
            self.cog,
            self.state,
        )

        if interaction.message is not None:
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=view,
            )
        else:
            await interaction.response.send_message(
                view=view,
                ephemeral=True,
            )


class SetupActionButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "SetupContinueView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = (
            discord.ButtonStyle.secondary
        ),
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(
                emoji
            ),
            style=style,
        )

        self.owner_view = owner_view
        self.action = action

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if self.action == "edit":
            if interaction.guild is None:
                await self.owner_view.cog.send_feedback(
                    interaction,
                    "Server niet gevonden.",
                    kind="error",
                )
                return

            await interaction.response.send_modal(
                EventSetupModal(
                    self.owner_view.cog,
                    self.owner_view.state,
                    interaction.guild,
                )
            )
            return

        if self.action == "custom_games":
            await interaction.response.send_modal(
                CustomGamesModal(
                    self.owner_view.cog,
                    self.owner_view.state,
                )
            )
            return

        if self.action == "planning":
            await interaction.response.send_modal(
                EventPlanningModal(
                    self.owner_view.cog,
                    self.owner_view.state,
                )
            )


class SetupContinueView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Events",
        state: WizardState,
        *,
        published: bool = False,
        event_id: int | None = None,
    ):
        super().__init__(
            timeout=900
            if not published
            else 180
        )

        self.cog = cog
        self.state = state

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                cog.wizard_text(
                    state,
                    published=published,
                    event_id=event_id,
                )
            )
        ]

        if not published:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.ActionRow(
                        SetupActionButton(
                            self,
                            "edit",
                            "Event aanpassen",
                            emoji=EDIT_EMOJI,
                        ),
                        SetupActionButton(
                            self,
                            "custom_games",
                            "Anders / eigen games",
                            emoji=GAMES_EMOJI,
                            style=(
                                discord.ButtonStyle.primary
                            ),
                        ),
                        SetupActionButton(
                            self,
                            "planning",
                            "Planning & publiceren",
                            emoji=TIME_EMOJI,
                            style=(
                                discord.ButtonStyle.success
                            ),
                        ),
                    ),
                    discord.ui.TextDisplay(
                        "-# Staat een game niet tussen de actieve games? "
                        "Gebruik **Anders / eigen games** en typ zelf "
                        "één of meer opties."
                    ),
                ]
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=BRAND_COLOR,
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == (
            self.state.author_id
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Deze eventsetup is niet van jou.",
            kind="error",
        )
        return False


class EventPlanningModal(discord.ui.Modal):
    """Second setup page: date, time, duration and capacity, then publish."""

    def __init__(
        self,
        cog: "Events",
        state: WizardState,
    ):
        super().__init__(
            title="Planning & publiceren"
        )

        self.cog = cog
        self.state = state

        date_default = None
        times_default = None

        if state.time_options:
            first = (
                state.time_options[0]
                .astimezone(AMSTERDAM)
            )

            date_default = first.strftime(
                "%d-%m-%Y"
            )

            times_default = ", ".join(
                dt.astimezone(AMSTERDAM)
                .strftime("%H:%M")
                for dt in state.time_options[:10]
            )

        self.date = discord.ui.TextInput(
            label="Datum",
            placeholder="12-09-2026",
            default=date_default,
            max_length=10,
        )

        self.times = discord.ui.TextInput(
            label="Tijd(en)",
            placeholder=(
                "20:00  of  20:00, 21:00, 22:00"
            ),
            default=times_default,
            max_length=80,
        )

        duration_values = (
            60,
            90,
            120,
            180,
            240,
            360,
        )

        self.duration = discord.ui.Select(
            placeholder="Kies de duur",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=human_duration(
                        minutes
                    ),
                    value=str(minutes),
                    default=(
                        minutes
                        == state.duration_minutes
                    ),
                )
                for minutes
                in duration_values
            ],
        )

        self.max_slots = discord.ui.TextInput(
            label="Max. deelnemers",
            placeholder="0 = onbeperkt",
            default=str(
                state.max_slots
            ),
            max_length=2,
        )

        self.add_item(
            self.date
        )
        self.add_item(
            self.times
        )
        self.add_item(
            discord.ui.Label(
                text="Duur",
                description=(
                    "Hoe lang het event ongeveer duurt."
                ),
                component=self.duration,
            )
        )
        self.add_item(
            self.max_slots
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await self.cog.send_feedback(
                interaction,
                "Server niet gevonden.",
                kind="error",
            )
            return

        raw_times = [
            value.strip()
            for value in re.split(
                r"[,;]",
                str(self.times),
            )
            if value.strip()
        ]

        if not raw_times:
            await self.cog.send_feedback(
                interaction,
                "Vul minimaal één tijd in.",
                kind="error",
            )
            return

        if len(raw_times) > 10:
            await self.cog.send_feedback(
                interaction,
                "Je kunt maximaal 10 tijdopties toevoegen.",
                kind="error",
            )
            return

        try:
            parsed = sorted(
                {
                    combine_amsterdam(
                        str(self.date).strip(),
                        value,
                    )
                    for value
                    in raw_times
                }
            )

            max_slots = int(
                str(
                    self.max_slots
                ).strip()
            )

            duration = int(
                self.duration.values[0]
            )

        except ValueError as exc:
            await self.cog.send_feedback(
                interaction,
                str(exc),
                kind="error",
            )
            return
        except (
            IndexError,
            TypeError,
        ):
            await self.cog.send_feedback(
                interaction,
                "Kies een geldige duur.",
                kind="error",
            )
            return

        if any(
            dt
            <= utc_now()
            + timedelta(minutes=5)
            for dt in parsed
        ):
            await self.cog.send_feedback(
                interaction,
                (
                    "Elke tijd moet minimaal "
                    "5 minuten in de toekomst liggen."
                ),
                kind="error",
            )
            return

        if not (
            0
            <= max_slots
            <= MAX_SLOTS_LIMIT
        ):
            await self.cog.send_feedback(
                interaction,
                (
                    "Max. deelnemers moet "
                    f"0 t/m {MAX_SLOTS_LIMIT} zijn."
                ),
                kind="error",
            )
            return

        self.state.time_options = parsed
        self.state.duration_minutes = duration
        self.state.max_slots = max_slots

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            event_id = await self.cog.publish_from_wizard(
                interaction,
                self.state,
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    (
                        "Ik mis permissies om dit event te publiceren. "
                        "Controleer **Manage Events**, **Manage Channels**, "
                        "**View Channel** en **Send Messages**."
                    ),
                    kind="error",
                    title="Publiceren mislukt",
                ),
            )
            return
        except (
            discord.HTTPException,
            RuntimeError,
        ) as exc:
            logger.exception(
                "Event publiceren mislukt."
            )

            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    (
                        "Het event kon niet worden gepubliceerd. "
                        f"`{truncate(str(exc), 300)}`"
                    ),
                    kind="error",
                    title="Publiceren mislukt",
                ),
            )
            return

        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=SetupContinueView(
                self.cog,
                self.state,
                published=True,
                event_id=event_id,
            ),
        )


class JoinTimeModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Events",
        event_id: int,
        options: list[dict],
    ):
        super().__init__(
            title="Deelnemen"
        )

        self.cog = cog
        self.event_id = event_id

        radio_options: list[
            discord.RadioGroupOption
        ] = []

        for index, option in enumerate(
            options[:10],
            start=1,
        ):
            starts = from_db(
                option["starts_at"]
            )

            if starts:
                local = starts.astimezone(
                    AMSTERDAM
                )

                label = local.strftime(
                    "%H:%M"
                )

                description = local.strftime(
                    "%A %d-%m-%Y"
                )
            else:
                label = (
                    f"Optie {index}"
                )
                description = None

            radio_options.append(
                discord.RadioGroupOption(
                    label=label,
                    value=str(
                        option["id"]
                    ),
                    description=description,
                )
            )

        self.time_choice = discord.ui.RadioGroup(
            custom_id=(
                f"levenloos:event:"
                f"{event_id}:time_choice"
            ),
            required=True,
            options=radio_options,
        )

        self.add_item(
            discord.ui.Label(
                text="Kies wanneer je kunt",
                description=(
                    "Je keuze telt meteen als stem "
                    "en je doet direct mee."
                ),
                component=self.time_choice,
            )
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not self.time_choice.value:
            await self.cog.send_feedback(
                interaction,
                "Kies één tijd om deel te nemen.",
                kind="error",
            )
            return

        option_id = int(
            self.time_choice.value
        )

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            message, event_url = (
                await self.cog.join_with_vote(
                    interaction,
                    self.event_id,
                    option_id,
                )
            )
        except Exception:
            logger.exception(
                "Deelname via RadioGroup mislukt "
                "voor event %s.",
                self.event_id,
            )

            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    (
                        "Je deelname kon niet worden opgeslagen. "
                        "Probeer het opnieuw."
                    ),
                    kind="error",
                ),
            )
            return

        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=ParticipationResultView(
                message,
                event_url=event_url,
            ),
        )


class JoinOptionsModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Events",
        event_id: int,
        time_options: list[dict],
        game_options: list[dict],
    ):
        super().__init__(
            title="Deelnemen"
        )

        self.cog = cog
        self.event_id = event_id
        self.time_choice = None
        self.game_choices = None

        if len(time_options) > 1:
            radio_options: list[
                discord.RadioGroupOption
            ] = []

            for index, option in enumerate(
                time_options[:10],
                start=1,
            ):
                starts = from_db(
                    option["starts_at"]
                )

                label = (
                    starts.astimezone(
                        AMSTERDAM
                    ).strftime("%H:%M")
                    if starts
                    else f"Optie {index}"
                )

                description = (
                    starts.astimezone(
                        AMSTERDAM
                    ).strftime(
                        "%A %d-%m-%Y"
                    )
                    if starts
                    else None
                )

                radio_options.append(
                    discord.RadioGroupOption(
                        label=label,
                        value=str(
                            option["id"]
                        ),
                        description=description,
                    )
                )

            self.time_choice = (
                discord.ui.RadioGroup(
                    custom_id=(
                        f"levenloos:event:"
                        f"{event_id}:time_choice"
                    ),
                    required=True,
                    options=radio_options,
                )
            )

            self.add_item(
                discord.ui.Label(
                    text="Kies wanneer je kunt",
                    description=(
                        "Je kunt één tijd kiezen."
                    ),
                    component=self.time_choice,
                )
            )

        if game_options:
            checkbox_options = [
                discord.CheckboxGroupOption(
                    label=truncate(
                        str(option["name"]),
                        100,
                    ),
                    value=str(
                        option["id"]
                    ),
                )
                for option
                in game_options[:10]
            ]

            self.game_choices = (
                discord.ui.CheckboxGroup(
                    custom_id=(
                        f"levenloos:event:"
                        f"{event_id}:game_choices"
                    ),
                    required=True,
                    min_values=1,
                    max_values=len(
                        checkbox_options
                    ),
                    options=checkbox_options,
                )
            )

            self.add_item(
                discord.ui.Label(
                    text="Welke games wil je spelen?",
                    description=(
                        "Je mag meerdere games aanvinken."
                    ),
                    component=self.game_choices,
                )
            )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        option_id = (
            int(
                self.time_choice.value
            )
            if (
                self.time_choice
                and self.time_choice.value
            )
            else None
        )

        game_ids = [
            int(value)
            for value in (
                self.game_choices.values
                if self.game_choices
                else []
            )
        ]

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            message, event_url = (
                await self.cog.join_with_choices(
                    interaction,
                    self.event_id,
                    option_id,
                    game_ids,
                )
            )
        except Exception:
            logger.exception(
                "Deelname met keuzes mislukt "
                "voor event %s.",
                self.event_id,
            )

            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    (
                        "Je deelname kon niet worden opgeslagen. "
                        "Probeer het opnieuw."
                    ),
                    kind="error",
                ),
            )
            return

        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=ParticipationResultView(
                message,
                event_url=event_url,
            ),
        )


class DiscordEventLinkButton(discord.ui.Button):
    def __init__(
        self,
        event_url: str,
        *,
        label: str = "Open Discord Event",
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(
                EVENT_EMOJI
            ),
            style=discord.ButtonStyle.link,
            url=event_url,
        )


class ParticipationResultView(discord.ui.LayoutView):
    def __init__(
        self,
        message: str,
        *,
        event_url: str | None = None,
    ):
        super().__init__(
            timeout=180
        )

        lower = message.casefold()

        if "wachtlijst" in lower:
            kind = "warning"
            title = "Wachtlijst"
        elif (
            "afgemeld" in lower
            or "gesloten" in lower
            or "ongeldig" in lower
        ):
            kind = "info"
            title = "Deelname bijgewerkt"
        else:
            kind = "success"
            title = "Je doet mee"

        _, icon, accent = feedback_style(
            kind
        )

        children: list[
            discord.ui.Item
        ] = [
            discord.ui.TextDisplay(
                f"# {icon} {title}\n"
                + "\n".join(
                    f"> └ {line}"
                    for line
                    in message.splitlines()
                    if line.strip()
                )
            )
        ]

        if event_url:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.ActionRow(
                        DiscordEventLinkButton(
                            event_url,
                            label="Zet mij op Interested",
                        )
                    ),
                    discord.ui.TextDisplay(
                        "-# Discord laat bots niet namens een gebruiker "
                        "de RSVP-status aanpassen."
                    ),
                ]
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=accent,
            )
        )


class DashboardButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "EventDashboardView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = (
            discord.ButtonStyle.secondary
        ),
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(
                emoji
            ),
            style=style,
            custom_id=(
                f"levenloos:event:"
                f"{owner_view.event_id}:{action}"
            ),
            disabled=disabled,
        )

        self.owner_view = owner_view
        self.action = action

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.owner_view.handle(
            interaction,
            self.action,
        )


class EventDashboardView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Events",
        event_id: int,
        sections: list[str],
        *,
        event_url: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            timeout=None
        )

        self.cog = cog
        self.event_id = event_id

        children: list[
            discord.ui.Item
        ] = []

        for index, section in enumerate(
            sections
        ):
            if index:
                children.append(
                    discord.ui.Separator(
                        visible=True,
                        spacing=(
                            discord.SeparatorSpacing.small
                        ),
                    )
                )

            children.append(
                discord.ui.TextDisplay(
                    section
                )
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    DashboardButton(
                        self,
                        "join",
                        "Deelnemen",
                        emoji=SUCCESS_EMOJI,
                        style=discord.ButtonStyle.success,
                        disabled=disabled,
                    ),
                    DashboardButton(
                        self,
                        "leave",
                        "Afmelden",
                        emoji=NONE_EMOJI,
                        disabled=disabled,
                    ),
                    DashboardButton(
                        self,
                        "manage",
                        "Beheren",
                        emoji=SETTINGS_EMOJI,
                        disabled=disabled,
                    ),
                    *(
                        [
                            DiscordEventLinkButton(
                                event_url
                            )
                        ]
                        if event_url
                        else []
                    ),
                ),
                discord.ui.TextDisplay(
                    f"-# Event #{event_id} • LEVENLOOS Events"
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=BRAND_COLOR,
            )
        )

    @classmethod
    async def create(
        cls,
        cog: "Events",
        event_id: int,
        *,
        disabled: bool = False,
    ) -> "EventDashboardView":
        event = await cog.get_event(
            event_id
        )

        if event is None:
            raise RuntimeError(
                "Event niet gevonden."
            )

        event_url = None

        if event["discord_event_id"]:
            event_url = (
                "https://discord.com/events/"
                f"{event['guild_id']}/"
                f"{event['discord_event_id']}"
            )

        return cls(
            cog,
            event_id,
            await cog.dashboard_sections(
                event_id
            ),
            event_url=event_url,
            disabled=disabled,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        event = await self.cog.get_event(
            self.event_id
        )

        if not event:
            await self.cog.send_feedback(
                interaction,
                "Dit event bestaat niet meer.",
                kind="error",
            )
            return

        if action == "join":
            if event["status"] in {
                STATUS_ENDED,
                STATUS_CANCELLED,
            }:
                await self.cog.send_feedback(
                    interaction,
                    "Dit event neemt geen aanmeldingen meer aan.",
                    kind="warning",
                )
                return

            time_options = (
                await self.cog.get_time_options(
                    self.event_id
                )
            )

            game_options = (
                await self.cog.get_game_options(
                    self.event_id
                )
            )

            if (
                game_options
                or (
                    event["status"]
                    == STATUS_PLANNING
                    and len(
                        time_options
                    ) > 1
                )
            ):
                if (
                    len(time_options) > 10
                    or len(game_options) > 10
                ):
                    await self.cog.send_feedback(
                        interaction,
                        (
                            "Dit event heeft te veel keuze-opties. "
                            "Maximaal 10 tijdopties en 10 games "
                            "worden ondersteund."
                        ),
                        kind="error",
                    )
                    return

                await interaction.response.send_modal(
                    JoinOptionsModal(
                        self.cog,
                        self.event_id,
                        time_options,
                        game_options,
                    )
                )
                return

            if (
                event["status"]
                == STATUS_PLANNING
            ):
                if not time_options:
                    await self.cog.send_feedback(
                        interaction,
                        "Er zijn geen tijdopties beschikbaar.",
                        kind="error",
                    )
                    return

                await interaction.response.defer(
                    ephemeral=True,
                    thinking=True,
                )

                message, event_url = (
                    await self.cog.join_with_vote(
                        interaction,
                        self.event_id,
                        int(
                            time_options[0]["id"]
                        ),
                    )
                )

                await interaction.edit_original_response(
                    content=None,
                    embed=None,
                    view=ParticipationResultView(
                        message,
                        event_url=event_url,
                    ),
                )
                return

            await self.cog.set_participant(
                interaction,
                self.event_id,
                "going",
            )
            return

        if action == "leave":
            await self.cog.set_participant(
                interaction,
                self.event_id,
                "leave",
            )
            return

        if action == "manage":
            if not await self.cog.can_manage_event(
                interaction,
                self.event_id,
            ):
                await self.cog.send_feedback(
                    interaction,
                    (
                        "Alleen de host, co-host of beheerder "
                        "kan dit event beheren."
                    ),
                    kind="error",
                    title="Geen toegang",
                )
                return

            await interaction.response.send_message(
                view=await EventManagementView.create(
                    self.cog,
                    self.event_id,
                    interaction.user.id,
                ),
                ephemeral=True,
            )


class ManagementButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "EventManagementView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = (
            discord.ButtonStyle.secondary
        ),
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(
                emoji
            ),
            style=style,
            disabled=disabled,
        )

        self.owner_view = owner_view
        self.action = action

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.owner_view.handle(
            interaction,
            self.action,
        )


class EventManagementView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Events",
        event_id: int,
        owner_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(
            timeout=600
        )

        self.cog = cog
        self.event_id = event_id
        self.owner_id = owner_id

        children: list[
            discord.ui.Item
        ] = [
            discord.ui.TextDisplay(
                body
            )
        ]

        if notice:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.TextDisplay(
                        f"## {INFO_EMOJI} Laatste actie\n"
                        f"> └ {notice}"
                    ),
                ]
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ManagementButton(
                        self,
                        "close_poll",
                        "Stemming sluiten",
                        emoji=LOCK_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ManagementButton(
                        self,
                        "refresh",
                        "Vernieuwen",
                        emoji=REFRESH_EMOJI,
                    ),
                    ManagementButton(
                        self,
                        "cancel",
                        "Event annuleren",
                        emoji=DELETE_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=BRAND_COLOR,
            )
        )

    @classmethod
    async def create(
        cls,
        cog: "Events",
        event_id: int,
        owner_id: int,
        *,
        notice: str | None = None,
    ) -> "EventManagementView":
        return cls(
            cog,
            event_id,
            owner_id,
            await cog.management_text(
                event_id
            ),
            notice=notice,
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id
            == self.owner_id
            and await self.cog.can_manage_event(
                interaction,
                self.event_id,
            )
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Geen toegang tot dit beheermenu.",
            kind="error",
        )
        return False

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action == "close_poll":
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )

            result = await self.cog.close_poll(
                self.event_id,
                interaction.guild,
            )

            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=await EventManagementView.create(
                    self.cog,
                    self.event_id,
                    self.owner_id,
                    notice=result,
                ),
            )
            return

        if action == "refresh":
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )

            await self.cog.refresh_dashboard(
                self.event_id
            )

            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=await EventManagementView.create(
                    self.cog,
                    self.event_id,
                    self.owner_id,
                    notice="Het openbare dashboard is vernieuwd.",
                ),
            )
            return

        if action == "cancel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=CancelConfirmView(
                    self.cog,
                    self.event_id,
                    self.owner_id,
                ),
            )


class CancelConfirmButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "CancelConfirmView",
        action: str,
    ):
        if action == "confirm":
            label = "Event annuleren"
            emoji = DELETE_EMOJI
            style = discord.ButtonStyle.danger
        else:
            label = "Terug"
            emoji = BACK_EMOJI
            style = discord.ButtonStyle.secondary

        super().__init__(
            label=label,
            emoji=component_emoji(
                emoji
            ),
            style=style,
        )

        self.owner_view = owner_view
        self.action = action

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if self.action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await EventManagementView.create(
                    self.owner_view.cog,
                    self.owner_view.event_id,
                    self.owner_view.owner_id,
                ),
            )
            return

        if not await self.owner_view.cog.can_manage_event(
            interaction,
            self.owner_view.event_id,
        ):
            await self.owner_view.cog.send_feedback(
                interaction,
                "Geen toegang.",
                kind="error",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await self.owner_view.cog.cancel_event(
            self.owner_view.event_id,
            interaction.guild,
        )

        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(
                "Het event is geannuleerd.",
                kind="success",
                title="Event geannuleerd",
            ),
        )


class CancelConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Events",
        event_id: int,
        owner_id: int,
    ):
        super().__init__(
            timeout=60
        )

        self.cog = cog
        self.event_id = event_id
        self.owner_id = owner_id

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Event annuleren\n"
                    f"> └ Event **#{event_id}** wordt geannuleerd.\n"
                    "> └ Het openbare dashboard wordt gesloten en "
                    "een leeg tijdelijk voicekanaal wordt opgeruimd."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    CancelConfirmButton(
                        self,
                        "confirm",
                    ),
                    CancelConfirmButton(
                        self,
                        "back",
                    ),
                ),
                accent_colour=discord.Colour.from_rgb(
                    237,
                    66,
                    69,
                ),
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id
            == self.owner_id
            and await self.cog.can_manage_event(
                interaction,
                self.event_id,
            )
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Geen toegang tot deze bevestiging.",
            kind="error",
        )
        return False


class EventChannelSelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        owner_view: "EventConfigView",
    ):
        super().__init__(
            placeholder="Dashboardkanaal",
            channel_types=[
                discord.ChannelType.text
            ],
            min_values=1,
            max_values=1,
        )

        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        channel = self.values[0]

        await self.owner_view.cog.set_config_value(
            self.owner_view.guild_id,
            "event_channel_id",
            channel.id,
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await EventConfigView.create(
                self.owner_view.cog,
                interaction.guild,
                self.owner_view.owner_id,
                notice=(
                    f"Dashboardkanaal ingesteld op "
                    f"{channel.mention}."
                ),
            ),
        )


class VoiceCategorySelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        owner_view: "EventConfigView",
    ):
        super().__init__(
            placeholder="Voicecategorie",
            channel_types=[
                discord.ChannelType.category
            ],
            min_values=1,
            max_values=1,
        )

        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        category = self.values[0]

        await self.owner_view.cog.set_config_value(
            self.owner_view.guild_id,
            "voice_category_id",
            category.id,
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await EventConfigView.create(
                self.owner_view.cog,
                interaction.guild,
                self.owner_view.owner_id,
                notice=(
                    f"Voicecategorie ingesteld op "
                    f"**{category.name}**."
                ),
            ),
        )


class EventConfigView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Events",
        guild: discord.Guild,
        owner_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(
            timeout=600
        )

        self.cog = cog
        self.guild_id = guild.id
        self.owner_id = owner_id

        children: list[
            discord.ui.Item
        ] = [
            discord.ui.TextDisplay(
                body
            )
        ]

        if notice:
            children.extend(
                [
                    discord.ui.TextDisplay(
                        f"> └ {SUCCESS_EMOJI} {notice}"
                    )
                ]
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"## {EVENT_EMOJI} Dashboardkanaal\n"
                    "> └ Kies waar openbare eventdashboards worden geplaatst."
                ),
                discord.ui.ActionRow(
                    EventChannelSelect(
                        self
                    )
                ),
                discord.ui.TextDisplay(
                    f"## {VOICE_EMOJI} Voicecategorie\n"
                    "> └ Kies waar tijdelijke event-voicekanalen verschijnen."
                ),
                discord.ui.ActionRow(
                    VoiceCategorySelect(
                        self
                    )
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=BRAND_COLOR,
            )
        )

    @classmethod
    async def create(
        cls,
        cog: "Events",
        guild: discord.Guild,
        owner_id: int,
        *,
        notice: str | None = None,
    ) -> "EventConfigView":
        return cls(
            cog,
            guild,
            owner_id,
            await cog.config_text(
                guild
            ),
            notice=notice,
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id
            == self.owner_id
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
            "Geen toegang tot dit configuratiemenu.",
            kind="error",
        )
        return False


class EventListView(discord.ui.LayoutView):
    def __init__(
        self,
        rows: list[aiosqlite.Row],
    ):
        super().__init__(
            timeout=180
        )

        lines = [
            f"# {EVENT_BANNER}",
            f"## {LIST_EMOJI} Geplande events",
        ]

        for row in rows:
            lines.extend(
                [
                    f"### {EVENT_EMOJI} {row['game_name']}",
                    f"> └ Event **#{row['id']}** • "
                    f"**{status_label(row['status'])}**",
                    f"> └ {discord_ts(from_db(row['starts_at']), 'f')}",
                ]
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "\n".join(lines)
                ),
                discord.ui.TextDisplay(
                    "-# Maximaal 15 actieve events worden getoond."
                ),
                accent_colour=BRAND_COLOR,
            )
        )


# =========================================================
# COG
# =========================================================



class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}
        self._views_restored = False

    def cog_unload(self) -> None:
        if self.maintenance_loop.is_running():
            self.maintenance_loop.cancel()

    event = app_commands.Group(
        name="event",
        description="Plan en beheer events op LEVENLOOS.",
    )

    async def cog_load(self) -> None:
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Events vereist discord.py 2.6+ voor Components V2."
            )

        if not hasattr(discord.ui, "RadioGroup"):
            raise RuntimeError(
                "Events vereist discord.py 2.7+ voor RadioGroup."
            )

        await self.init_db()

        if not self.maintenance_loop.is_running():
            self.maintenance_loop.start()

        logger.info("Events-module geladen.")

    async def send_feedback(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
        footer: str | None = None,
    ) -> None:
        view = FeedbackView(
            message,
            kind=kind,
            title=title,
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

    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    async def init_db(self) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA busy_timeout = 5000")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    game_name TEXT NOT NULL,
                    game_role_id INTEGER,
                    event_type TEXT NOT NULL DEFAULT 'Game Event',
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planning',
                    max_slots INTEGER NOT NULL DEFAULT 0,
                    duration_minutes INTEGER NOT NULL DEFAULT 120,
                    starts_at TEXT,
                    ends_at TEXT,
                    poll_closes_at TEXT,
                    discord_event_id INTEGER,
                    dashboard_channel_id INTEGER,
                    dashboard_message_id INTEGER,
                    voice_channel_id INTEGER,
                    voice_opened INTEGER NOT NULL DEFAULT 0,
                    temporary_voice INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_time_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    starts_at TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    UNIQUE(event_id, starts_at),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_time_votes (
                    event_id INTEGER NOT NULL,
                    option_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, user_id),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                    FOREIGN KEY(option_id) REFERENCES event_time_options(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_game_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    role_id INTEGER,
                    sort_order INTEGER NOT NULL,
                    UNIQUE(event_id, name),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_game_votes (
                    event_id INTEGER NOT NULL,
                    option_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, option_id, user_id),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                    FOREIGN KEY(option_id) REFERENCES event_game_options(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_participants (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    queue_position INTEGER,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, user_id),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_hosts (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY(event_id, user_id),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_reminders (
                    event_id INTEGER NOT NULL,
                    offset_minutes INTEGER NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(event_id, offset_minutes),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS event_config (
                    guild_id INTEGER PRIMARY KEY,
                    event_channel_id INTEGER,
                    voice_category_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_events_guild_status ON events(guild_id, status);
                CREATE INDEX IF NOT EXISTS idx_event_participants_status ON event_participants(event_id, status);
                CREATE INDEX IF NOT EXISTS idx_event_time_votes_option ON event_time_votes(option_id);
                CREATE INDEX IF NOT EXISTS idx_event_game_votes_option ON event_game_votes(option_id);
                CREATE INDEX IF NOT EXISTS idx_event_reminders_sent ON event_reminders(event_id, sent);
                """
            )
            columns = {row[1] for row in await (await db.execute("PRAGMA table_info(events)")).fetchall()}
            if "event_type" not in columns:
                await db.execute("ALTER TABLE events ADD COLUMN event_type TEXT NOT NULL DEFAULT 'Game Event'")
            await db.commit()

    async def fetchone(self, query: str, params: tuple = ()) -> aiosqlite.Row | None:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                return await cursor.fetchall()

    async def get_event(self, event_id: int) -> aiosqlite.Row | None:
        return await self.fetchone("SELECT * FROM events WHERE id = ?", (event_id,))

    async def get_time_options(self, event_id: int) -> list[dict]:
        rows = await self.fetchall(
            """
            SELECT o.id, o.starts_at, o.sort_order, COUNT(v.user_id) AS votes
            FROM event_time_options o
            LEFT JOIN event_time_votes v ON v.option_id = o.id
            WHERE o.event_id = ?
            GROUP BY o.id
            ORDER BY o.sort_order ASC
            """,
            (event_id,),
        )
        return [dict(row) for row in rows]

    async def get_game_options(self, event_id: int) -> list[dict]:
        rows = await self.fetchall(
            """
            SELECT o.id, o.name, o.role_id, o.sort_order, COUNT(v.user_id) AS votes
            FROM event_game_options o
            LEFT JOIN event_game_votes v ON v.option_id = o.id
            WHERE o.event_id = ?
            GROUP BY o.id
            ORDER BY o.sort_order ASC
            """,
            (event_id,),
        )
        return [dict(row) for row in rows]

    async def get_config(self, guild_id: int) -> aiosqlite.Row | None:
        return await self.fetchone("SELECT * FROM event_config WHERE guild_id = ?", (guild_id,))

    async def set_config_value(self, guild_id: int, column: str, value: int) -> None:
        if column not in {"event_channel_id", "voice_category_id"}:
            raise ValueError("Ongeldige configkolom")
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO event_config(guild_id) VALUES (?)", (guild_id,))
            await db.execute(f"UPDATE event_config SET {column} = ? WHERE guild_id = ?", (value, guild_id))
            await db.commit()

    # -----------------------------------------------------
    # GAME INTEGRATION
    # -----------------------------------------------------

    def active_games(self, guild: discord.Guild) -> list[tuple[str, int]]:
        category = guild.get_channel(ACTIVE_GAME_CATEGORY_ID)
        active_slugs: set[str] = set()
        if isinstance(category, discord.CategoryChannel):
            active_slugs = {channel.name.removeprefix("▏").lower() for channel in category.text_channels}
        games: list[tuple[str, int]] = []
        for role in guild.roles:
            if not role.name.startswith("◆ "):
                continue
            name = role.name[2:].strip()
            slug = clean_voice_name(name)
            if not active_slugs or slug in active_slugs:
                games.append((name, role.id))
        games.sort(key=lambda item: item[0].casefold())
        return games

    @commands.Cog.listener()
    async def on_game_catalog_changed(self, guild: discord.Guild, game_name: str, action: str) -> None:
        if action == "removed":
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("UPDATE events SET game_role_id = NULL, updated_at = ? WHERE guild_id = ? AND game_name = ?", (to_db(utc_now()), guild.id, game_name))
                await db.commit()

    # -----------------------------------------------------
    # COMPONENTS V2 RENDERERS
    # -----------------------------------------------------

    def wizard_text(
        self,
        state: WizardState,
        *,
        published: bool = False,
        event_id: int | None = None,
    ) -> str:
        title = (
            "Event gepubliceerd"
            if published
            else "Event setup"
        )

        intro = (
            "De setup is afgerond."
            if published
            else (
                "De basis staat klaar. Controleer dit en "
                "vul daarna de planning in."
            )
        )

        lines = [
            f"# {EVENT_BANNER}",
            f"## {EVENT_EMOJI} {title}",
            f"> └ {intro}",
            "",
            f"## {EVENT_EMOJI} Event",
            f"> └ **Type:** {state.event_type}",
            f"> └ **Naam:** {state.game_name or state.event_type}",
        ]

        if state.description:
            lines.append(
                f"> └ {state.description}"
            )

        lines.extend(
            [
                "",
                f"## {TIME_EMOJI} Planning",
            ]
        )

        if state.time_options:
            for index, dt in enumerate(
                state.time_options,
                start=1,
            ):
                lines.append(
                    f"> └ **{index}.** "
                    f"{discord_ts(dt, 'f')} • "
                    f"{discord_ts(dt, 'R')}"
                )
        else:
            lines.append(
                "> └ Nog geen datum en tijd ingesteld."
            )

        lines.extend(
            [
                "",
                f"## {GAMES_EMOJI} Games",
            ]
        )

        if state.game_options:
            for name, _ in state.game_options:
                lines.append(
                    f"> └ **{name}**"
                )
        else:
            lines.append(
                "> └ Geen game-stemming ingesteld."
            )

        lines.extend(
            [
                "",
                f"## {SETTINGS_EMOJI} Instellingen",
                f"> └ Duur: **{human_duration(state.duration_minutes)}**",
                f"> └ Deelnemers: "
                f"**{state.max_slots if state.max_slots else 'Onbeperkt'}**",
                f"> └ {VOICE_EMOJI} Tijdelijk voicekanaal: "
                f"**{'Aan' if state.temporary_voice else 'Uit'}**",
            ]
        )

        if state.temporary_voice:
            lines.append(
                "> └ Voice opent **15 minuten vooraf** en "
                "wordt na afloop verwijderd zodra het leeg is."
            )

        if published and event_id is not None:
            lines.extend(
                [
                    "",
                    f"-# Event #{event_id}",
                ]
            )

        return "\n".join(lines)

    async def dashboard_sections(
        self,
        event_id: int,
    ) -> list[str]:
        event = await self.get_event(
            event_id
        )

        if event is None:
            raise RuntimeError(
                "Event niet gevonden"
            )

        starts = from_db(
            event["starts_at"]
        )

        status = status_label(
            event["status"]
        )

        description = (
            event["description"]
            or "Geen extra beschrijving opgegeven."
        )

        host_name = await self.user_display_name(
            int(event["guild_id"]),
            int(event["host_id"]),
        )

        header = [
            f"# {EVENT_BANNER}",
            f"## {EVENT_EMOJI} {event['game_name']}",
            f"> └ **Type:** {event['event_type']}",
            f"> └ {description}",
            "",
            f"## {EVENT_EMOJI} Event informatie",
            f"> └ Status: **{status}**",
            (
                f"> └ Wanneer: **{discord_ts(starts, 'F')}**"
                if starts
                else "> └ Wanneer: **Wordt bepaald**"
            ),
        ]

        if starts:
            header.append(
                f"> └ Start: {discord_ts(starts, 'R')}"
            )

        header.extend(
            [
                f"> └ Duur: **{human_duration(int(event['duration_minutes']))}**",
                f"> └ Host: **{host_name}**",
            ]
        )

        sections = [
            "\n".join(header)
        ]

        going = await self.fetchall(
            """
            SELECT user_id
            FROM event_participants
            WHERE event_id = ?
              AND status = 'going'
            ORDER BY joined_at ASC
            """,
            (event_id,),
        )

        waitlist = await self.fetchall(
            """
            SELECT user_id
            FROM event_participants
            WHERE event_id = ?
              AND status = 'waitlist'
            ORDER BY queue_position ASC, joined_at ASC
            """,
            (event_id,),
        )

        capacity = int(
            event["max_slots"]
            or 0
        )

        participants = [
            f"## {USER_EMOJI} Deelnemers"
            + (
                f" • {len(going)}/{capacity}"
                if capacity
                else f" • {len(going)}"
            )
        ]

        participant_value = self.mention_list(
            [
                row["user_id"]
                for row in going
            ]
        )

        if participant_value == "Nog niemand.":
            participants.append(
                "> └ Nog niemand. Klik op **Deelnemen** om mee te doen."
            )
        else:
            participants.append(
                f"> └ {participant_value}"
            )

        if waitlist:
            participants.extend(
                [
                    "",
                    f"### Wachtlijst • {len(waitlist)}",
                    f"> └ {self.mention_list([row['user_id'] for row in waitlist], numbered=True)}",
                ]
            )

        sections.append(
            "\n".join(participants)
        )

        if event["status"] == STATUS_PLANNING:
            options = await self.get_time_options(
                event_id
            )

            planning_lines = [
                f"## {TIME_EMOJI} Planning"
            ]

            for index, option in enumerate(
                options,
                start=1,
            ):
                voters = await self.fetchall(
                    """
                    SELECT user_id
                    FROM event_time_votes
                    WHERE option_id = ?
                    ORDER BY created_at ASC
                    """,
                    (option["id"],),
                )

                voter_mentions = " ".join(
                    f"<@{row['user_id']}>"
                    for row in voters[:12]
                )

                count = int(
                    option["votes"]
                )

                vote_word = (
                    "stem"
                    if count == 1
                    else "stemmen"
                )

                planning_lines.append(
                    f"### {index}. "
                    f"{discord_ts(from_db(option['starts_at']), 'f')}"
                )

                line = (
                    f"> └ **{count} {vote_word}**"
                )

                if voter_mentions:
                    line += (
                        f" • {voter_mentions}"
                    )

                planning_lines.append(
                    line
                )

            closes = from_db(
                event["poll_closes_at"]
            )

            if closes:
                planning_lines.extend(
                    [
                        "",
                        f"> └ Stemming sluit "
                        f"{discord_ts(closes, 'R')}",
                    ]
                )

            sections.append(
                "\n".join(
                    planning_lines
                )
            )

        game_options = await self.get_game_options(
            event_id
        )

        if game_options:
            game_lines = [
                f"## {GAMES_EMOJI} Welke game spelen we?"
            ]

            for option in game_options:
                voters = await self.fetchall(
                    """
                    SELECT user_id
                    FROM event_game_votes
                    WHERE option_id = ?
                    ORDER BY created_at ASC
                    """,
                    (option["id"],),
                )

                mentions = " ".join(
                    f"<@{row['user_id']}>"
                    for row in voters[:12]
                )

                count = int(
                    option["votes"]
                )

                vote_word = (
                    "stem"
                    if count == 1
                    else "stemmen"
                )

                game_lines.append(
                    f"### {option['name']}"
                )

                line = (
                    f"> └ **{count} {vote_word}**"
                )

                if mentions:
                    line += (
                        f" • {mentions}"
                    )

                game_lines.append(
                    line
                )

            sections.append(
                "\n".join(
                    game_lines
                )
            )

        return sections

    async def management_text(
        self,
        event_id: int,
    ) -> str:
        event = await self.get_event(
            event_id
        )

        if not event:
            return (
                f"# {EVENT_BANNER}\n"
                f"## {ERROR_EMOJI} Event niet gevonden"
            )

        host_name = await self.user_display_name(
            int(event["guild_id"]),
            int(event["host_id"]),
        )

        return (
            f"# {EVENT_BANNER}\n"
            f"## {SETTINGS_EMOJI} Event beheren\n"
            f"> └ **{event['game_name']}**\n"
            f"> └ Type: **{event['event_type']}**\n\n"
            f"## {EVENT_EMOJI} Details\n"
            f"> └ Event: **#{event_id}**\n"
            f"> └ Status: **{status_label(event['status'])}**\n"
            f"> └ Host: **{host_name}**"
        )

    async def config_text(
        self,
        guild: discord.Guild,
    ) -> str:
        config = await self.get_config(
            guild.id
        )

        event_channel = (
            guild.get_channel(
                config["event_channel_id"]
            )
            if (
                config
                and config["event_channel_id"]
            )
            else None
        )

        voice_category = (
            guild.get_channel(
                config["voice_category_id"]
            )
            if (
                config
                and config["voice_category_id"]
            )
            else None
        )

        event_channel_text = (
            event_channel.mention
            if isinstance(
                event_channel,
                discord.TextChannel,
            )
            else "Niet ingesteld"
        )

        voice_category_text = (
            f"**{voice_category.name}**"
            if isinstance(
                voice_category,
                discord.CategoryChannel,
            )
            else "Niet ingesteld"
        )

        return (
            f"# {EVENT_BANNER}\n"
            f"## {SETTINGS_EMOJI} Event Config\n"
            "> └ Stel de standaardlocaties voor events in.\n\n"
            f"## {SETTINGS_EMOJI} Huidige instellingen\n"
            f"> └ Dashboardkanaal: {event_channel_text}\n"
            f"> └ Voicecategorie: {voice_category_text}"
        )

    async def user_display_name(self, guild_id: int, user_id: int) -> str:
        """Resolve a Discord user ID to a readable server/player name."""
        guild = self.bot.get_guild(guild_id)
        if guild is not None:
            member = guild.get_member(user_id)
            if member is not None:
                return member.display_name
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
            if member is not None:
                return member.display_name

        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except (discord.NotFound, discord.HTTPException):
                user = None
        if user is not None:
            return user.global_name or user.name
        return "Onbekend"

    @staticmethod
    def mention_list(user_ids: Iterable[int], *, numbered: bool = False) -> str:
        ids = list(user_ids)
        if not ids:
            return "Nog niemand."
        shown = ids[:20]
        text = "\n".join(f"`{i}` <@{uid}>" for i, uid in enumerate(shown, 1)) if numbered else " ".join(f"<@{uid}>" for uid in shown)
        if len(ids) > len(shown):
            text += f"\n+ {len(ids) - len(shown)} meer"
        return text

    # -----------------------------------------------------
    # PUBLISH / SCHEDULED EVENT
    # -----------------------------------------------------

    async def publish_from_wizard(self, interaction: discord.Interaction, state: WizardState) -> int:
        guild = interaction.guild
        if guild is None:
            raise RuntimeError("Dit werkt alleen in een server.")
        config = await self.get_config(guild.id)
        channel_id = config["event_channel_id"] if config else None
        dashboard_channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(dashboard_channel, discord.TextChannel):
            dashboard_channel = guild.get_channel(state.channel_id)
        if not isinstance(dashboard_channel, discord.TextChannel):
            raise RuntimeError("Geen geldig dashboardkanaal gevonden.")

        now = utc_now()
        status = STATUS_PLANNING if len(state.time_options) > 1 else STATUS_CONFIRMED
        starts_at = state.time_options[0] if len(state.time_options) == 1 else None
        ends_at = starts_at + timedelta(minutes=state.duration_minutes) if starts_at else None
        poll_closes = None
        if len(state.time_options) > 1:
            poll_closes = min(now + timedelta(hours=DEFAULT_POLL_HOURS), min(state.time_options) - timedelta(minutes=30))
            if poll_closes <= now:
                poll_closes = now + timedelta(minutes=5)

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                INSERT INTO events(guild_id, host_id, game_name, game_role_id, event_type, description,
                    status, max_slots, duration_minutes, starts_at, ends_at, poll_closes_at,
                    dashboard_channel_id, temporary_voice, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guild.id, state.author_id, state.game_name, state.game_role_id, state.event_type, state.description,
                 status, state.max_slots, state.duration_minutes, to_db(starts_at), to_db(ends_at),
                 to_db(poll_closes), dashboard_channel.id, 1 if state.temporary_voice else 0,
                 to_db(now), to_db(now)),
            )
            event_id = int(cursor.lastrowid)
            for index, dt in enumerate(state.time_options):
                await db.execute("INSERT INTO event_time_options(event_id, starts_at, sort_order) VALUES (?, ?, ?)", (event_id, to_db(dt), index))
            for index, (name, role_id) in enumerate(state.game_options):
                await db.execute(
                    "INSERT INTO event_game_options(event_id, name, role_id, sort_order) VALUES (?, ?, ?, ?)",
                    (event_id, name, role_id, index),
                )
            await db.execute("INSERT INTO event_hosts(event_id, user_id) VALUES (?, ?)", (event_id, state.author_id))
            # With one fixed time, the host is immediately a participant.
            # With multiple planning options, nobody can be a participant without choosing
            # an option first: the host uses Deelnemen just like everyone else.
            if len(state.time_options) == 1:
                await db.execute(
                    "INSERT INTO event_participants(event_id, user_id, status, queue_position, joined_at) VALUES (?, ?, 'going', NULL, ?)",
                    (event_id, state.author_id, to_db(now)),
                )
            for offset in (1440, 120, 30, 0):
                await db.execute("INSERT INTO event_reminders(event_id, offset_minutes, sent) VALUES (?, ?, 0)", (event_id, offset))
            await db.commit()

        try:
            if status == STATUS_CONFIRMED:
                await self.create_official_event(
                    event_id,
                    guild,
                )

            dashboard_view = await EventDashboardView.create(
                self,
                event_id,
            )

            message = await dashboard_channel.send(
                view=dashboard_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )

            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("UPDATE events SET dashboard_message_id = ?, updated_at = ? WHERE id = ?", (message.id, to_db(utc_now()), event_id))
                await db.commit()
            self.bot.add_view(
                dashboard_view,
                message_id=message.id,
            )
            return event_id
        except Exception:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("DELETE FROM events WHERE id = ?", (event_id,))
                await db.commit()
            raise

    async def create_official_event(self, event_id: int, guild: discord.Guild) -> discord.ScheduledEvent:
        event = await self.get_event(event_id)
        if event is None:
            raise RuntimeError("Event niet gevonden.")
        if event["discord_event_id"]:
            existing = guild.get_scheduled_event(event["discord_event_id"])
            if existing:
                return existing
        starts = from_db(event["starts_at"])
        ends = from_db(event["ends_at"])
        if starts is None or ends is None:
            raise RuntimeError("Het event heeft nog geen definitieve tijd.")
        # Important: no voice channel is created here. It appears 15 minutes before start.
        scheduled = await guild.create_scheduled_event(
            name=truncate(event["game_name"], 100),
            description=truncate(event["description"] or "LEVENLOOS event", 1000),
            start_time=starts,
            end_time=ends,
            privacy_level=discord.PrivacyLevel.guild_only,
            entity_type=discord.EntityType.external,
            location="LEVENLOOS Discord",
            reason=f"LEVENLOOS event #{event_id}",
        )
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE events SET discord_event_id = ?, voice_channel_id = NULL, voice_opened = 0, updated_at = ? WHERE id = ?", (scheduled.id, to_db(utc_now()), event_id))
            await db.commit()
        return scheduled

    async def ensure_voice_channel(self, event_id: int) -> None:
        event = await self.get_event(event_id)
        if not event or not event["temporary_voice"] or event["voice_channel_id"]:
            return
        starts = from_db(event["starts_at"])
        if not starts or utc_now() < starts - timedelta(minutes=VOICE_OPEN_MINUTES):
            return
        guild = self.bot.get_guild(event["guild_id"])
        if not guild:
            return
        config = await self.get_config(guild.id)
        category_id = config["voice_category_id"] if config else None
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = None
        voice_channel = await guild.create_voice_channel(
            f"Event | {clean_voice_name(event['game_name'])}",
            category=category,
            overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)},
            reason=f"Tijdelijk voicekanaal voor event #{event_id}",
        )
        if event["discord_event_id"]:
            scheduled = guild.get_scheduled_event(event["discord_event_id"])
            if scheduled:
                try:
                    await scheduled.edit(channel=voice_channel, entity_type=discord.EntityType.voice, reason=f"Voicekanaal koppelen aan LEVENLOOS event #{event_id}")
                except Exception:
                    try:
                        await voice_channel.delete(reason=f"Koppelen Scheduled Event #{event_id} mislukt")
                    except Exception:
                        pass
                    raise
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE events SET voice_channel_id = ?, voice_opened = 1, updated_at = ? WHERE id = ?", (voice_channel.id, to_db(utc_now()), event_id))
            await db.commit()
        await self.refresh_dashboard(event_id)

    # -----------------------------------------------------
    # PARTICIPANTS / VOTING
    # -----------------------------------------------------

    async def _register_going(self, event_id: int, user_id: int) -> str:
        event = await self.get_event(event_id)
        if not event:
            return "Event niet gevonden."
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT status FROM event_participants WHERE event_id = ? AND user_id = ?", (event_id, user_id))
            existing = await cursor.fetchone()
            cursor = await db.execute("SELECT COUNT(*) FROM event_participants WHERE event_id = ? AND status = 'going'", (event_id,))
            going_count = (await cursor.fetchone())[0]
            max_slots = int(event["max_slots"])
            already_going = existing and existing["status"] == "going"
            if max_slots and going_count >= max_slots and not already_going:
                cursor = await db.execute("SELECT COALESCE(MAX(queue_position), 0) + 1 FROM event_participants WHERE event_id = ? AND status = 'waitlist'", (event_id,))
                position = (await cursor.fetchone())[0]
                await db.execute(
                    """
                    INSERT INTO event_participants(event_id, user_id, status, queue_position, joined_at)
                    VALUES (?, ?, 'waitlist', ?, ?)
                    ON CONFLICT(event_id, user_id)
                    DO UPDATE SET status = 'waitlist', queue_position = excluded.queue_position
                    """,
                    (event_id, user_id, position, to_db(utc_now())),
                )
                await db.commit()
                return f"Het event zit vol. Je staat op wachtlijstpositie {position}."
            await db.execute(
                """
                INSERT INTO event_participants(event_id, user_id, status, queue_position, joined_at)
                VALUES (?, ?, 'going', NULL, ?)
                ON CONFLICT(event_id, user_id)
                DO UPDATE SET status = 'going', queue_position = NULL
                """,
                (event_id, user_id, to_db(utc_now())),
            )
            await db.commit()
        return "Je doet mee."

    async def join_with_vote(
        self, interaction: discord.Interaction, event_id: int, option_id: int
    ) -> tuple[str, str | None]:
        """Register a planning vote and participation as one persistent action.

        The vote and participant row are committed in the same transaction so
        a successful confirmation can never mean that only half of the action
        was saved. The public dashboard is refreshed before we return.
        """
        event = await self.get_event(event_id)
        if not event or event["status"] != STATUS_PLANNING:
            return "De stemming is gesloten.", None

        valid = await self.fetchone(
            "SELECT id FROM event_time_options WHERE id = ? AND event_id = ?",
            (option_id, event_id),
        )
        if not valid:
            return "Ongeldige optie.", None

        lock = self._locks.setdefault(event_id, asyncio.Lock())
        async with lock:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                db.row_factory = aiosqlite.Row

                # Work out whether this user should be going or waitlisted.
                cursor = await db.execute(
                    "SELECT status FROM event_participants WHERE event_id = ? AND user_id = ?",
                    (event_id, interaction.user.id),
                )
                existing = await cursor.fetchone()

                cursor = await db.execute(
                    "SELECT COUNT(*) AS c FROM event_participants WHERE event_id = ? AND status = 'going'",
                    (event_id,),
                )
                going_count = int((await cursor.fetchone())["c"])
                max_slots = int(event["max_slots"] or 0)
                already_going = bool(existing and existing["status"] == "going")

                if max_slots and going_count >= max_slots and not already_going:
                    cursor = await db.execute(
                        "SELECT COALESCE(MAX(queue_position), 0) + 1 AS p FROM event_participants WHERE event_id = ? AND status = 'waitlist'",
                        (event_id,),
                    )
                    position = int((await cursor.fetchone())["p"])
                    participant_status = "waitlist"
                    queue_position = position
                    participant_message = f"Het event zit vol. Je staat op wachtlijstpositie {position}."
                else:
                    participant_status = "going"
                    queue_position = None
                    participant_message = "Je doet mee."

                now = to_db(utc_now())
                await db.execute(
                    """
                    INSERT INTO event_time_votes(event_id, option_id, user_id, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(event_id, user_id)
                    DO UPDATE SET option_id = excluded.option_id, created_at = excluded.created_at
                    """,
                    (event_id, option_id, interaction.user.id, now),
                )
                await db.execute(
                    """
                    INSERT INTO event_participants(event_id, user_id, status, queue_position, joined_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(event_id, user_id)
                    DO UPDATE SET
                        status = excluded.status,
                        queue_position = excluded.queue_position,
                        joined_at = excluded.joined_at
                    """,
                    (
                        event_id,
                        interaction.user.id,
                        participant_status,
                        queue_position,
                        now,
                    ),
                )
                await db.commit()

                # Verify what was actually persisted before telling the user it worked.
                cursor = await db.execute(
                    "SELECT status FROM event_participants WHERE event_id = ? AND user_id = ?",
                    (event_id, interaction.user.id),
                )
                saved_participant = await cursor.fetchone()
                cursor = await db.execute(
                    "SELECT option_id FROM event_time_votes WHERE event_id = ? AND user_id = ?",
                    (event_id, interaction.user.id),
                )
                saved_vote = await cursor.fetchone()

                if not saved_participant or not saved_vote or int(saved_vote["option_id"]) != option_id:
                    raise RuntimeError(
                        f"Event {event_id}: deelname/stem van gebruiker {interaction.user.id} kon niet worden bevestigd in de database"
                    )

        # Refresh the public card immediately after the committed transaction.
        await self.refresh_dashboard(event_id)

        event = await self.get_event(event_id)
        event_url: str | None = None
        extra = "Je tijdkeuze is meteen als stem opgeslagen."

        if event and event["discord_event_id"]:
            event_url = (
                "https://discord.com/events/"
                f"{event['guild_id']}/"
                f"{event['discord_event_id']}"
            )

            extra += (
                "\nKlik hieronder ook op **Zet mij op Interested** "
                "om je Discord RSVP te registreren."
            )
        else:
            extra += (
                "\nZodra de winnende tijd vaststaat verschijnt het "
                "officiële Discord-event."
            )

        return (
            f"{participant_message}\n{extra}",
            event_url,
        )

    async def join_with_choices(
        self, interaction: discord.Interaction, event_id: int, option_id: int | None, game_option_ids: list[int]
    ) -> tuple[str, str | None]:
        event = await self.get_event(event_id)
        if not event or event["status"] in {STATUS_ENDED, STATUS_CANCELLED}:
            return "Dit event neemt geen aanmeldingen meer aan.", None

        game_options = await self.get_game_options(event_id)
        valid_game_ids = {int(option["id"]) for option in game_options}
        selected_game_ids = {int(value) for value in game_option_ids}
        if game_options and (not selected_game_ids or not selected_game_ids.issubset(valid_game_ids)):
            return "Kies minimaal één geldige game.", None

        if event["status"] == STATUS_PLANNING:
            time_options = await self.get_time_options(event_id)
            if len(time_options) > 1:
                valid_time_ids = {int(option["id"]) for option in time_options}
                if option_id is None or option_id not in valid_time_ids:
                    return "Kies één geldige tijd.", None
            elif time_options:
                option_id = int(time_options[0]["id"])

        lock = self._locks.setdefault(event_id, asyncio.Lock())
        async with lock:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                now = to_db(utc_now())
                if event["status"] == STATUS_PLANNING and option_id is not None:
                    await db.execute(
                        """INSERT INTO event_time_votes(event_id, option_id, user_id, created_at)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(event_id, user_id) DO UPDATE SET option_id=excluded.option_id, created_at=excluded.created_at""",
                        (event_id, option_id, interaction.user.id, now),
                    )

                await db.execute(
                    "DELETE FROM event_game_votes WHERE event_id = ? AND user_id = ?",
                    (event_id, interaction.user.id),
                )
                for game_id in selected_game_ids:
                    await db.execute(
                        "INSERT INTO event_game_votes(event_id, option_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                        (event_id, game_id, interaction.user.id, now),
                    )
                await db.commit()

            participant_message = await self._register_going(event_id, interaction.user.id)

        await self.refresh_dashboard(event_id)
        event = await self.get_event(event_id)
        extras: list[str] = []
        if option_id is not None and event and event["status"] == STATUS_PLANNING:
            extras.append("Je tijdkeuze is als stem opgeslagen.")
        if selected_game_ids:
            extras.append("Je gamekeuze(s) zijn opgeslagen. Je mag meerdere games kiezen.")

        event_url: str | None = None

        if event and event["discord_event_id"]:
            event_url = (
                "https://discord.com/events/"
                f"{event['guild_id']}/"
                f"{event['discord_event_id']}"
            )

            extras.append(
                "Klik hieronder ook op **Zet mij op Interested** "
                "om je Discord RSVP te registreren."
            )

        return (
            participant_message
            + (
                "\n"
                + "\n".join(extras)
                if extras
                else ""
            ),
            event_url,
        )

    async def set_participant(self, interaction: discord.Interaction, event_id: int, action: str) -> None:
        event = await self.get_event(event_id)
        if not event or event["status"] in {STATUS_ENDED, STATUS_CANCELLED}:
            await interaction.response.send_message("Dit event neemt geen aanmeldingen meer aan.", ephemeral=True)
            return
        lock = self._locks.setdefault(event_id, asyncio.Lock())
        async with lock:
            if action == "leave":
                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.execute("DELETE FROM event_participants WHERE event_id = ? AND user_id = ?", (event_id, interaction.user.id))
                    await db.execute("DELETE FROM event_time_votes WHERE event_id = ? AND user_id = ?", (event_id, interaction.user.id))
                    await db.execute("DELETE FROM event_game_votes WHERE event_id = ? AND user_id = ?", (event_id, interaction.user.id))
                    await db.commit()
                message = "Je bent afgemeld. Je eventuele tijd- en gamestemmen zijn ook verwijderd."
                promoted = await self.promote_waitlist(event_id)
                if promoted:
                    await self.notify_promoted(event, promoted)
            else:
                message = await self._register_going(event_id, interaction.user.id)
        event_url = None

        if (
            action != "leave"
            and event["discord_event_id"]
        ):
            event_url = (
                "https://discord.com/events/"
                f"{event['guild_id']}/"
                f"{event['discord_event_id']}"
            )

            message += (
                "\nKlik hieronder ook op **Zet mij op Interested** "
                "om je Discord RSVP te registreren."
            )

        await interaction.response.send_message(
            view=ParticipationResultView(
                message,
                event_url=event_url,
            ),
            ephemeral=True,
        )

        await self.refresh_dashboard(
            event_id
        )

    async def promote_waitlist(self, event_id: int) -> int | None:
        event = await self.get_event(event_id)
        if not event or not event["max_slots"]:
            return None
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT COUNT(*) AS c FROM event_participants WHERE event_id = ? AND status = 'going'", (event_id,))
            going = (await cursor.fetchone())["c"]
            if going >= event["max_slots"]:
                return None
            cursor = await db.execute("SELECT user_id FROM event_participants WHERE event_id = ? AND status = 'waitlist' ORDER BY queue_position ASC, joined_at ASC LIMIT 1", (event_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            user_id = row["user_id"]
            await db.execute("UPDATE event_participants SET status = 'going', queue_position = NULL WHERE event_id = ? AND user_id = ?", (event_id, user_id))
            cursor = await db.execute("SELECT user_id FROM event_participants WHERE event_id = ? AND status = 'waitlist' ORDER BY queue_position ASC, joined_at ASC", (event_id,))
            rows = await cursor.fetchall()
            for position, wait_row in enumerate(rows, 1):
                await db.execute("UPDATE event_participants SET queue_position = ? WHERE event_id = ? AND user_id = ?", (position, event_id, wait_row["user_id"]))
            await db.commit()
            return int(user_id)

    async def notify_promoted(self, event: aiosqlite.Row, user_id: int) -> None:
        channel = self.bot.get_channel(event["dashboard_channel_id"])
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(f"<@{user_id}> er is een plek vrijgekomen voor **{event['game_name']}**. Je staat nu bij de deelnemers.", allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            except discord.HTTPException:
                pass

    async def close_poll(self, event_id: int, guild: discord.Guild | None) -> str:
        if guild is None:
            return "Server niet gevonden."
        lock = self._locks.setdefault(event_id, asyncio.Lock())
        async with lock:
            event = await self.get_event(event_id)
            if not event:
                return "Event niet gevonden."
            if event["status"] != STATUS_PLANNING:
                return "De stemming is al gesloten."
            options = await self.get_time_options(event_id)
            if not options:
                return "Er zijn geen datumopties."
            winner = sorted(options, key=lambda item: (-int(item["votes"]), from_db(item["starts_at"])))[0]
            starts = from_db(winner["starts_at"])
            if starts is None or starts <= utc_now():
                return "De winnende datum ligt niet meer in de toekomst."
            ends = starts + timedelta(minutes=event["duration_minutes"])
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("UPDATE events SET status = ?, starts_at = ?, ends_at = ?, poll_closes_at = NULL, updated_at = ? WHERE id = ?", (STATUS_CONFIRMED, to_db(starts), to_db(ends), to_db(utc_now()), event_id))
                await db.commit()
            try:
                await self.create_official_event(event_id, guild)
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self.refresh_dashboard(event_id)
                return f"Stemming gesloten, maar het officiële Discord Event kon niet worden gemaakt: `{truncate(str(exc), 250)}`"
            await self.refresh_dashboard(event_id)
            return f"Stemming gesloten. Gekozen: {discord_ts(starts)}."

    # -----------------------------------------------------
    # MANAGEMENT / DASHBOARD
    # -----------------------------------------------------

    async def can_manage_event(self, interaction: discord.Interaction, event_id: int) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return False
        if management_access(interaction.user):
            return True
        event = await self.get_event(event_id)
        if not event:
            return False
        if event["host_id"] == interaction.user.id:
            return True
        host = await self.fetchone("SELECT 1 FROM event_hosts WHERE event_id = ? AND user_id = ?", (event_id, interaction.user.id))
        return host is not None

    async def cancel_event(self, event_id: int, guild: discord.Guild | None) -> None:
        event = await self.get_event(event_id)
        if not event:
            return
        if guild and event["discord_event_id"]:
            scheduled = guild.get_scheduled_event(event["discord_event_id"])
            if scheduled:
                try:
                    await scheduled.cancel(reason=f"LEVENLOOS event #{event_id} geannuleerd")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (STATUS_CANCELLED, to_db(utc_now()), event_id))
            await db.commit()
        await self.refresh_dashboard(event_id, disable=True)
        await self.cleanup_voice(event_id, force_if_empty=True)

    async def refresh_dashboard(self, event_id: int, *, disable: bool = False) -> None:
        event = await self.get_event(event_id)
        if not event or not event["dashboard_message_id"]:
            return

        channel_id = int(event["dashboard_channel_id"] or 0)
        channel = self.bot.get_channel(channel_id)

        # get_channel() only checks cache. Fall back to Discord's API so a
        # cache miss cannot make a successful join look as if nothing happened.
        if not isinstance(channel, discord.TextChannel):
            guild = self.bot.get_guild(int(event["guild_id"]))
            if guild is not None:
                try:
                    fetched = await guild.fetch_channel(channel_id)
                    if isinstance(fetched, discord.TextChannel):
                        channel = fetched
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                    logger.warning(
                        "Kon dashboardkanaal voor event %s niet ophalen: %s",
                        event_id,
                        exc,
                    )
                    return

        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "Dashboardkanaal voor event %s is niet beschikbaar (%s).",
                event_id,
                channel_id,
            )
            return

        try:
            message = await channel.fetch_message(int(event["dashboard_message_id"]))
            disabled = disable or event["status"] in {STATUS_ENDED, STATUS_CANCELLED}
            await message.edit(
                content=None,
                embed=None,
                view=await EventDashboardView.create(
                    self,
                    event_id,
                    disabled=disabled,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            # Never hide dashboard update failures; they are essential when
            # debugging a join that was saved but not rendered.
            logger.warning(
                "Kon dashboard van event %s niet verversen: %s: %s",
                event_id,
                type(exc).__name__,
                exc,
            )

    async def restore_views(self) -> None:
        if self._views_restored:
            return
        rows = await self.fetchall(
            """
            SELECT id, dashboard_message_id
            FROM events
            WHERE status IN ('planning', 'confirmed', 'active')
              AND dashboard_message_id IS NOT NULL
            """
        )

        restored = 0

        for row in rows:
            try:
                view = await EventDashboardView.create(
                    self,
                    int(row["id"]),
                )

                self.bot.add_view(
                    view,
                    message_id=int(
                        row["dashboard_message_id"]
                    ),
                )

                restored += 1

            except Exception:
                logger.exception(
                    "Eventdashboard view herstellen mislukt voor event %s.",
                    row["id"],
                )

        self._views_restored = True

        logger.info(
            "%s eventdashboard view(s) hersteld.",
            restored,
        )

    # -----------------------------------------------------
    # VOICE / REMINDERS / MAINTENANCE
    # -----------------------------------------------------

    async def cleanup_voice(self, event_id: int, *, force_if_empty: bool = False) -> None:
        event = await self.get_event(event_id)
        if not event or not event["voice_channel_id"]:
            return
        guild = self.bot.get_guild(event["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(event["voice_channel_id"])
        if not isinstance(channel, discord.VoiceChannel):
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("UPDATE events SET voice_channel_id = NULL, updated_at = ? WHERE id = ?", (to_db(utc_now()), event_id))
                await db.commit()
            return
        if channel.members:
            return
        ends = from_db(event["ends_at"])
        # Normal cleanup: only after the event has ended. No fixed grace timer.
        # force_if_empty is used for cancelled/completed scheduled events.
        if not force_if_empty and (not ends or utc_now() < ends):
            return
        try:
            await channel.delete(reason=f"Tijdelijk eventkanaal #{event_id} opgeruimd")
        except (discord.Forbidden, discord.HTTPException):
            return
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE events SET voice_channel_id = NULL, updated_at = ? WHERE id = ?", (to_db(utc_now()), event_id))
            await db.commit()

    async def send_due_reminders(self, event_id: int) -> None:
        event = await self.get_event(event_id)
        if not event or event["status"] not in {STATUS_CONFIRMED, STATUS_ACTIVE}:
            return
        starts = from_db(event["starts_at"])
        if not starts:
            return
        rows = await self.fetchall("SELECT offset_minutes FROM event_reminders WHERE event_id = ? AND sent = 0 ORDER BY offset_minutes DESC", (event_id,))
        now = utc_now()
        for row in rows:
            offset = row["offset_minutes"]
            due = starts - timedelta(minutes=offset)
            if now < due:
                continue
            if now - due > timedelta(minutes=45) and offset != 0:
                await self.mark_reminder_sent(event_id, offset)
                continue
            channel = self.bot.get_channel(event["dashboard_channel_id"])
            if isinstance(channel, discord.TextChannel):
                participants = await self.fetchall("SELECT user_id FROM event_participants WHERE event_id = ? AND status IN ('going','waitlist') ORDER BY joined_at ASC", (event_id,))
                mentions = " ".join(f"<@{row['user_id']}>" for row in participants[:40])
                text = f"**{event['game_name']}** begint nu!" if offset == 0 else f"**{event['game_name']}** begint {discord_ts(starts, 'R')}."
                content = f"{mentions}\n{text}" if mentions else text
                try:
                    await channel.send(content, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                except discord.HTTPException:
                    pass
            await self.mark_reminder_sent(event_id, offset)

    async def mark_reminder_sent(self, event_id: int, offset: int) -> None:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE event_reminders SET sent = 1 WHERE event_id = ? AND offset_minutes = ?", (event_id, offset))
            await db.commit()

    @tasks.loop(minutes=1)
    async def maintenance_loop(self) -> None:
        now = utc_now()
        rows = await self.fetchall("SELECT * FROM events WHERE status IN ('planning', 'confirmed', 'active', 'ended')")
        for event in rows:
            event_id = event["id"]
            try:
                if event["status"] == STATUS_PLANNING:
                    closes = from_db(event["poll_closes_at"])
                    if closes and now >= closes:
                        guild = self.bot.get_guild(event["guild_id"])
                        await self.close_poll(event_id, guild)
                    continue
                starts = from_db(event["starts_at"])
                ends = from_db(event["ends_at"])
                if not starts or not ends:
                    continue
                if event["status"] in {STATUS_CONFIRMED, STATUS_ACTIVE}:
                    if event["temporary_voice"] and now >= starts - timedelta(minutes=VOICE_OPEN_MINUTES) and not event["voice_channel_id"]:
                        await self.ensure_voice_channel(event_id)
                    await self.send_due_reminders(event_id)
                    if event["status"] == STATUS_CONFIRMED and now >= starts:
                        async with aiosqlite.connect(DATABASE_PATH) as db:
                            await db.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (STATUS_ACTIVE, to_db(now), event_id))
                            await db.commit()
                        await self.refresh_dashboard(event_id)
                    if now >= ends:
                        async with aiosqlite.connect(DATABASE_PATH) as db:
                            await db.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (STATUS_ENDED, to_db(now), event_id))
                            await db.commit()
                        await self.refresh_dashboard(event_id, disable=True)
                # Keep checking ended events until the VC becomes empty.
                if now >= ends:
                    await self.cleanup_voice(event_id)
            except Exception as exc:
                logger.exception(
                    "Maintenance fout voor event #%s: %s",
                    event_id,
                    exc,
                )

    @maintenance_loop.before_loop
    async def before_maintenance(self) -> None:
        await self.bot.wait_until_ready()
        await self.restore_views()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if before.channel is None or before.channel == after.channel:
            return
        row = await self.fetchone("SELECT id, ends_at, status FROM events WHERE voice_channel_id = ? ORDER BY id DESC LIMIT 1", (before.channel.id,))
        if not row or before.channel.members:
            return
        ends = from_db(row["ends_at"])
        if row["status"] in {STATUS_ENDED, STATUS_CANCELLED} or (ends and utc_now() >= ends):
            await self.cleanup_voice(row["id"], force_if_empty=True)

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before: discord.ScheduledEvent, after: discord.ScheduledEvent) -> None:
        row = await self.fetchone("SELECT id FROM events WHERE discord_event_id = ?", (after.id,))
        if not row:
            return
        if after.status == discord.EventStatus.active:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (STATUS_ACTIVE, to_db(utc_now()), row["id"]))
                await db.commit()
            await self.refresh_dashboard(row["id"])
        elif after.status in {discord.EventStatus.completed, discord.EventStatus.cancelled}:
            new_status = STATUS_CANCELLED if after.status == discord.EventStatus.cancelled else STATUS_ENDED
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (new_status, to_db(utc_now()), row["id"]))
                await db.commit()
            await self.refresh_dashboard(row["id"], disable=True)
            await self.cleanup_voice(row["id"], force_if_empty=True)

    # -----------------------------------------------------
    # SLASH COMMANDS
    # -----------------------------------------------------

    @event.command(
        name="setup",
        description="Maak een nieuw event.",
    )
    async def event_setup(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        member = interaction.user

        event_role = interaction.guild.get_role(
            EVENT_CREATOR_ROLE_ID
        )

        has_event_role = (
            isinstance(
                member,
                discord.Member,
            )
            and any(
                role.id
                == EVENT_CREATOR_ROLE_ID
                for role in member.roles
            )
        )

        if not has_event_role:
            role_text = (
                event_role.mention
                if event_role
                else "<@&985989826950086717>"
            )

            await self.send_feedback(
                interaction,
                (
                    "Alleen leden met de "
                    f"{role_text} rol kunnen events aanmaken."
                ),
                kind="error",
                title="Geen toegang",
            )
            return

        state = WizardState(
            guild_id=interaction.guild.id,
            author_id=interaction.user.id,
            channel_id=interaction.channel_id,
        )

        await interaction.response.send_modal(
            EventSetupModal(
                self,
                state,
                interaction.guild,
            )
        )

    @event.command(
        name="beheer",
        description="Open het beheer van een event.",
    )
    @app_commands.describe(
        event_id="Het nummer onderaan het eventdashboard",
    )
    async def event_manage(
        self,
        interaction: discord.Interaction,
        event_id: int,
    ) -> None:
        if not await self.can_manage_event(
            interaction,
            event_id,
        ):
            await self.send_feedback(
                interaction,
                "Event niet gevonden of je hebt geen toegang.",
                kind="error",
            )
            return

        await interaction.response.send_message(
            view=await EventManagementView.create(
                self,
                event_id,
                interaction.user.id,
            ),
            ephemeral=True,
        )

    @event.command(
        name="lijst",
        description="Bekijk geplande events.",
    )
    async def event_list(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        rows = await self.fetchall(
            """
            SELECT
                id,
                game_name,
                status,
                starts_at
            FROM events
            WHERE guild_id = ?
              AND status IN (
                  'planning',
                  'confirmed',
                  'active'
              )
            ORDER BY
                CASE
                    WHEN starts_at IS NULL
                    THEN 1
                    ELSE 0
                END,
                starts_at ASC,
                id DESC
            LIMIT 15
            """,
            (
                interaction.guild.id,
            ),
        )

        if not rows:
            await self.send_feedback(
                interaction,
                "Er zijn geen actieve events.",
                kind="info",
                title="Geen events",
            )
            return

        await interaction.response.send_message(
            view=EventListView(
                rows
            ),
            ephemeral=True,
        )

    @event.command(
        name="config",
        description="Configureer het eventsysteem.",
    )
    async def event_config(
        self,
        interaction: discord.Interaction,
    ) -> None:
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
                "Geen toegang.",
                kind="error",
            )
            return

        await interaction.response.send_message(
            view=await EventConfigView.create(
                self,
                interaction.guild,
                interaction.user.id,
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Events(bot))
