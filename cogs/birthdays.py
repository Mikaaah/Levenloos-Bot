from __future__ import annotations

import calendar
import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = ROOT / "birthdays.db"
TZ = ZoneInfo("Europe/Amsterdam")

DEFAULT_BIRTHDAY_CHANNEL_ID = 0
DEFAULT_BIRTHDAY_ROLE_ID = 1546798650070663199
BRAND_COLOR = discord.Colour.from_str("#6C27DA")

DEFAULT_ANNOUNCEMENT_TITLE = "{member_name} is jarig!"
DEFAULT_ANNOUNCEMENT_MESSAGE = (
    "Vandaag zetten we {member} even extra in het zonnetje. "
    "Maak er een mooie dag van!"
)
DEFAULT_BUTTON_LABEL = "Feliciteer!"
DEFAULT_FOOTER = "LEVENLOOS • Verjaardagen"

logger = logging.getLogger(__name__)


# ============================================================
# LEVENLOOS CUSTOM EMOJIS
# ============================================================

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
INFO_EMOJI = "<:info:1547724036107149413>"

EDIT_EMOJI = "<:edit:1547724058894934116>"
REFRESH_EMOJI = "<:refresh:1547724055426244618>"
BACK_EMOJI = "<:back:1547724054038052966>"
DELETE_EMOJI = "<:delete:1547724056768286750>"
USER_EMOJI = "<:user:1547737210986692679>"
NOTIFICATION_EMOJI = "<:notificatie:1547738617659662488>"
STATUS_EMOJI = "<:status:1547738616501899364>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"


# ============================================================
# DEFAULT RANDOM CONGRATULATIONS
# ============================================================

CONGRAT_MESSAGES = [
    "🎉 {user} wenst {member} een hele fijne verjaardag!",
    "🎂 {user} komt een stukje taart halen bij {member}.",
    "🥳 {user} feliciteert {member} met een nieuwe level-up!",
    "🎁 {user} heeft een denkbeeldig cadeau voor {member} meegenomen.",
    "🎈 {user} hangt de slingers op voor {member}.",
    "🍰 {user} reserveert alvast het grootste stuk taart voor {member}.",
    "🎮 {user} geeft {member} vandaag gratis birthday DLC.",
    "🏆 {user} geeft {member} de achievement **Weer een jaar verder**.",
    "✨ {user} wenst {member} een dag zonder bugs en met veel loot.",
    "🎲 {user} rolt een NAT 20 voor de verjaardag van {member}.",
    "⚔️ {user} geeft {member} vandaag +1 op alle birthday rolls.",
    "🐉 {user} heeft de draak overtuigd om {member} vandaag met rust te laten.",
    "🧱 {user} bouwt een enorme verjaardagstaart voor {member}.",
    "⛏️ {user} heeft diamonds gevonden voor de verjaardag van {member}.",
    "🧟 {user} belooft {member} vandaag niet te bijten.",
    "🏭 {user} legt de fabriek even stil voor de verjaardag van {member}.",
    "🚗 {user} geeft {member} de eerste aftrap van de dag.",
    "⚽ {user} zet {member} vandaag als jarige in de basis.",
    "🔦 {user} schijnt even de verjaardagsspotlight op {member}.",
    "🌾 {user} heeft een birthday crop voor {member} geplant.",
    "🎣 {user} vist een verjaardagscadeau op voor {member}.",
    "🗺️ {user} zet een birthday marker op de map voor {member}.",
    "🎮 {user} maakt vandaag een extra plek in de party voor {member}.",
    "🛡️ {user} geeft {member} vandaag birthday armor.",
    "🚀 {user} lanceert de felicitaties richting {member}.",
    "👑 {user} kroont {member} tot jarige van de dag.",
    "🎊 {user} gooit digitale confetti naar {member}.",
    "🍀 {user} wenst {member} een jaar vol goede RNG.",
    "⭐ {user} geeft {member} vandaag vijf sterren.",
    "📜 {user} schrijft de verjaardag van {member} in de lore.",
    "🎯 {user} raakt precies de juiste dag om {member} te feliciteren.",
    "🧩 {user} legt het verjaardagsstukje voor {member} op z'n plek.",
]

DEFAULT_CONGRAT_MESSAGES = "\n".join(CONGRAT_MESSAGES)


# ============================================================
# DATA
# ============================================================

@dataclass(slots=True)
class BirthdayConfig:
    guild_id: int
    channel_id: int
    announcements_enabled: bool
    announcement_title: str
    announcement_message: str
    button_label: str
    footer_text: str
    public_congrats_enabled: bool
    random_congrats_enabled: bool
    birthday_xp_enabled: bool
    congrats_xp_enabled: bool
    show_avatar: bool
    congrats_messages: str
    birthday_role_id: int


# ============================================================
# GENERIC HELPERS
# ============================================================

def is_admin(member: discord.Member) -> bool:
    if (
        member.guild.owner_id == member.id
        or member.guild_permissions.administrator
    ):
        return True

    return any(
        role.name.casefold() in {"admin", "owner"}
        for role in member.roles
    )


def month_name(month: int) -> str:
    names = [
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
    ]
    return names[month]


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


def format_birthday(
    day: int,
    month: int,
) -> str:
    return f"{day} {month_name(month)}"


def next_birthday_date(
    day: int,
    month: int,
    *,
    today: date | None = None,
) -> date:
    today = today or datetime.now(TZ).date()
    year = today.year

    for _ in range(8):
        try:
            candidate = date(
                year,
                month,
                day,
            )
        except ValueError:
            year += 1
            continue

        if candidate >= today:
            return candidate

        year += 1

    # Alleen theoretisch bereikbaar bij corrupte data.
    return today


def template_values(
    *,
    guild: discord.Guild,
    member: discord.Member,
    user: discord.Member | discord.User | None = None,
) -> dict[str, object]:
    now = datetime.now(TZ)

    values: dict[str, object] = {
        "member": member.mention,
        "member_name": member.display_name,
        "guild": guild.name,
        "date": format_birthday(now.day, now.month),
        "day": now.day,
        "month": month_name(now.month),
        "year": now.year,
    }

    if user is not None:
        values.update(
            {
                "user": user.mention,
                "user_name": getattr(
                    user,
                    "display_name",
                    user.name,
                ),
            }
        )

    return values


def render_template(
    template: str,
    values: dict[str, object],
) -> str:
    try:
        return template.format(**values)
    except (KeyError, ValueError, IndexError):
        logger.warning(
            "Ongeldige verjaardagstemplate gebruikt: %r",
            template,
        )
        return template


def validate_template(
    template: str,
    *,
    congrats: bool = False,
) -> bool:
    sample = {
        "member": "@Jarige",
        "member_name": "Jarige",
        "guild": "LEVENLOOS",
        "date": "12 september",
        "day": 12,
        "month": "september",
        "year": 2026,
    }

    if congrats:
        sample.update(
            {
                "user": "@Speler",
                "user_name": "Speler",
            }
        )

    try:
        template.format(**sample)
    except (KeyError, ValueError, IndexError):
        return False

    return True


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


# ============================================================
# DATABASE
# ============================================================

async def init_db() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS birthdays (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                day INTEGER NOT NULL,
                month INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                updated_by INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS birthday_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL DEFAULT 0,
                announcements_enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS birthday_posts (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                message_id INTEGER,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id, year)
            );

            CREATE TABLE IF NOT EXISTS birthday_congrats (
                guild_id INTEGER NOT NULL,
                birthday_user_id INTEGER NOT NULL,
                congratulator_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (
                    guild_id,
                    birthday_user_id,
                    congratulator_id,
                    year
                )
            );
            """
        )

        # Backward-compatible uitbreidingen van de bestaande configuratie.
        cursor = await db.execute(
            "PRAGMA table_info(birthday_config)"
        )
        config_columns = {
            str(row[1])
            for row in await cursor.fetchall()
        }

        migrations = {
            "announcement_title": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN announcement_title TEXT NOT NULL DEFAULT ''"
            ),
            "announcement_message": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN announcement_message TEXT NOT NULL DEFAULT ''"
            ),
            "button_label": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN button_label TEXT NOT NULL DEFAULT ''"
            ),
            "footer_text": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN footer_text TEXT NOT NULL DEFAULT ''"
            ),
            "public_congrats_enabled": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN public_congrats_enabled INTEGER NOT NULL DEFAULT 1"
            ),
            "random_congrats_enabled": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN random_congrats_enabled INTEGER NOT NULL DEFAULT 1"
            ),
            "birthday_xp_enabled": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN birthday_xp_enabled INTEGER NOT NULL DEFAULT 1"
            ),
            "congrats_xp_enabled": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN congrats_xp_enabled INTEGER NOT NULL DEFAULT 1"
            ),
            "show_avatar": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN show_avatar INTEGER NOT NULL DEFAULT 1"
            ),
            "congrats_messages": (
                "ALTER TABLE birthday_config "
                "ADD COLUMN congrats_messages TEXT NOT NULL DEFAULT ''"
            ),
            "birthday_role_id": (
                "ALTER TABLE birthday_config "
                f"ADD COLUMN birthday_role_id INTEGER NOT NULL DEFAULT {DEFAULT_BIRTHDAY_ROLE_ID}"
            ),
        }

        for column, statement in migrations.items():
            if column not in config_columns:
                await db.execute(statement)

        cursor = await db.execute(
            "PRAGMA table_info(birthday_posts)"
        )
        post_columns = {
            str(row[1])
            for row in await cursor.fetchall()
        }

        if "xp_awarded" not in post_columns:
            await db.execute(
                "ALTER TABLE birthday_posts "
                "ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0"
            )

        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_birthdays_guild_date
            ON birthdays(guild_id, month, day)
            """
        )

        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_birthday_congrats_post
            ON birthday_congrats(
                guild_id,
                birthday_user_id,
                year
            )
            """
        )

        await db.commit()

    logger.info("Birthdays-database klaar.")


# ============================================================
# COMPONENTS V2 FEEDBACK
# ============================================================

class BirthdayFeedbackView(discord.ui.LayoutView):
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


# ============================================================
# PUBLIC BIRTHDAY CARD
# ============================================================

class BirthdayAnnouncementView(discord.ui.LayoutView):
    def __init__(
        self,
        member: discord.Member,
        config: BirthdayConfig,
        *,
        year: int,
        congratulations: int = 0,
        birthday_xp: int = 0,
        preview: bool = False,
    ):
        super().__init__(
            timeout=300 if preview else None
        )

        values = template_values(
            guild=member.guild,
            member=member,
        )

        title = render_template(
            config.announcement_title,
            values,
        )
        body = render_template(
            config.announcement_message,
            values,
        )
        footer = render_template(
            config.footer_text,
            values,
        )

        intro_text = (
            f"# 🎂 {title}\n"
            f"> └ {body}"
        )

        if config.show_avatar:
            intro: discord.ui.Item = discord.ui.Section(
                discord.ui.TextDisplay(
                    intro_text
                ),
                accessory=discord.ui.Thumbnail(
                    member.display_avatar.url,
                    description=(
                        f"Profielfoto van {member.display_name}"
                    ),
                ),
            )
        else:
            intro = discord.ui.TextDisplay(
                intro_text
            )

        status_lines = [
            f"> └ Felicitaties: **{congratulations}**"
        ]

        if birthday_xp > 0:
            status_lines.append(
                f"> └ Birthday bonus: **+{birthday_xp} XP**"
            )

        action_row = discord.ui.ActionRow(
            discord.ui.Button(
                label=config.button_label[:80],
                emoji="🎉",
                style=discord.ButtonStyle.success,
                custom_id=(
                    f"birthday_congrats:"
                    f"{member.id}:"
                    f"{year}"
                ),
                disabled=preview,
            )
        )

        self.add_item(
            discord.ui.Container(
                intro,
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"## {STATUS_EMOJI} Verjaardag\n"
                    + "\n".join(status_lines)
                ),
                action_row,
                discord.ui.TextDisplay(
                    f"-# {footer}"
                ),
                accent_colour=BRAND_COLOR,
            )
        )


# ============================================================
# OVERVIEW
# ============================================================

class BirthdayOverviewView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        total: int,
        today_members: list[discord.Member],
        upcoming: list[
            tuple[discord.Member, int, int, int]
        ],
    ):
        super().__init__(timeout=180)

        if today_members:
            today_text = ", ".join(
                member.mention
                for member in today_members
            )
        else:
            today_text = "Niemand uit de lijst is vandaag jarig."

        upcoming_lines = []

        for member, day, month, days_until in upcoming:
            if days_until == 0:
                when = "vandaag"
            elif days_until == 1:
                when = "morgen"
            else:
                when = f"over {days_until} dagen"

            upcoming_lines.append(
                f"> └ {member.mention} • "
                f"**{format_birthday(day, month)}** • {when}"
            )

        if not upcoming_lines:
            upcoming_lines = [
                "> └ Nog geen verjaardagen ingesteld."
            ]

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "# 🎂 Verjaardagen\n"
                    "> └ Bekijk wie er binnenkort jarig is."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"## {STATUS_EMOJI} Vandaag\n"
                    f"> └ {today_text}"
                ),
                discord.ui.TextDisplay(
                    f"## {USER_EMOJI} Binnenkort\n"
                    + "\n".join(upcoming_lines)
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"-# {total} verjaardagen geregistreerd"
                ),
                accent_colour=BRAND_COLOR,
            )
        )


# ============================================================
# CONFIG BUTTONS
# ============================================================

class ConfigButton(discord.ui.Button):
    def __init__(
        self,
        owner_view,
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
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


# ============================================================
# CONFIG MODALS
# ============================================================

class BirthdayTextModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        config: BirthdayConfig,
    ):
        super().__init__(
            title="Verjaardagsteksten",
            timeout=300,
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.title_input = discord.ui.TextInput(
            label="Titel",
            default=config.announcement_title,
            max_length=100,
            required=True,
        )

        self.message_input = discord.ui.TextInput(
            label="Verjaardagsbericht",
            default=config.announcement_message,
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
        )

        self.button_input = discord.ui.TextInput(
            label="Knoptekst",
            default=config.button_label,
            max_length=80,
            required=True,
        )

        self.footer_input = discord.ui.TextInput(
            label="Footer",
            default=config.footer_text,
            max_length=100,
            required=True,
        )

        self.add_item(self.title_input)
        self.add_item(self.message_input)
        self.add_item(self.button_input)
        self.add_item(self.footer_input)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit configuratiemenu is niet van jou.",
                kind="error",
            )
            return

        title = str(self.title_input).strip()
        message = str(self.message_input).strip()
        button = str(self.button_input).strip()
        footer = str(self.footer_input).strip()

        if (
            not validate_template(title)
            or not validate_template(message)
            or not validate_template(footer)
        ):
            await self.cog.send_feedback(
                interaction,
                (
                    "Een van de teksten bevat een ongeldige placeholder.\n"
                    "Gebruik alleen `{member}`, `{member_name}`, `{guild}`, "
                    "`{date}`, `{day}`, `{month}` en `{year}`."
                ),
                kind="error",
                title="Ongeldige tekst",
            )
            return

        if not button:
            await self.cog.send_feedback(
                interaction,
                "De knoptekst mag niet leeg zijn.",
                kind="error",
            )
            return

        await self.cog.update_config(
            self.guild_id,
            announcement_title=title,
            announcement_message=message,
            button_label=button,
            footer_text=footer,
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await BirthdayConfigView.create(
                self.cog,
                self.owner_id,
                self.guild_id,
                notice="Teksten opgeslagen.",
            ),
        )


class CongratulationsModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        config: BirthdayConfig,
    ):
        super().__init__(
            title="Automatische felicitaties",
            timeout=300,
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.messages = discord.ui.TextInput(
            label="Felicitaties — één per regel",
            style=discord.TextStyle.paragraph,
            default=config.congrats_messages[:4000],
            placeholder=(
                "{user} feliciteert {member}!\n"
                "{user} zet de taart klaar voor {member}."
            ),
            max_length=4000,
            required=True,
        )

        self.add_item(self.messages)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit configuratiemenu is niet van jou.",
                kind="error",
            )
            return

        messages = [
            line.strip()
            for line in str(self.messages).splitlines()
            if line.strip()
        ]

        if not messages:
            await self.cog.send_feedback(
                interaction,
                "Voeg minimaal één felicitatie toe.",
                kind="error",
            )
            return

        invalid = [
            line
            for line in messages
            if not validate_template(
                line,
                congrats=True,
            )
        ]

        if invalid:
            await self.cog.send_feedback(
                interaction,
                (
                    "Minimaal één felicitatie bevat een ongeldige placeholder.\n"
                    "Gebruik `{user}`, `{user_name}`, `{member}`, "
                    "`{member_name}` en `{guild}`."
                ),
                kind="error",
                title="Ongeldige felicitatie",
            )
            return

        await self.cog.update_config(
            self.guild_id,
            congrats_messages="\n".join(messages),
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await BirthdayConfigView.create(
                self.cog,
                self.owner_id,
                self.guild_id,
                notice=(
                    f"{len(messages)} automatische felicitaties opgeslagen."
                ),
            ),
        )


# ============================================================
# CHANNEL CONFIG
# ============================================================

class BirthdayChannelSelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        owner_view: "BirthdayChannelView",
    ):
        super().__init__(
            placeholder="Kies het verjaardagskanaal...",
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

        await self.owner_view.cog.update_config(
            self.owner_view.guild_id,
            channel_id=channel.id,
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await BirthdayChannelView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice=(
                    f"Verjaardagskanaal ingesteld op <#{channel.id}>."
                ),
            ),
        )


class BirthdayChannelView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(body),
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
                    BirthdayChannelSelect(self)
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "back",
                        "Terug",
                        emoji=BACK_EMOJI,
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
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        *,
        notice: str | None = None,
    ) -> "BirthdayChannelView":
        config = await cog.get_config(guild_id)

        body = (
            f"# {NOTIFICATION_EMOJI} Kanaal\n"
            "> └ Kies waar de verjaardagskaarten automatisch geplaatst worden.\n\n"
            f"## {STATUS_EMOJI} Huidige instelling\n"
            f"> └ Kanaal: "
            f"{f'<#{config.channel_id}>' if config.channel_id else '**niet ingesteld**'}"
        )

        return cls(
            cog,
            owner_id,
            guild_id,
            body,
            notice=notice,
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return await self.cog.config_access(
            interaction,
            self.owner_id,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )


class BirthdayRoleSelect(discord.ui.RoleSelect):
    def __init__(
        self,
        owner_view: "BirthdayRoleView",
    ):
        super().__init__(
            placeholder="Kies de verjaardagsrol...",
            min_values=1,
            max_values=1,
        )
        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        role = self.values[0]

        if interaction.guild is None:
            return

        if role.is_default():
            await self.owner_view.cog.send_feedback(
                interaction,
                "De @everyone-rol kan niet als verjaardagsrol worden gebruikt.",
                kind="error",
            )
            return

        await self.owner_view.cog.update_config(
            self.owner_view.guild_id,
            birthday_role_id=role.id,
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await BirthdayRoleView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice=f"Verjaardagsrol ingesteld op {role.mention}.",
            ),
        )


class BirthdayRoleView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(body),
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
                    BirthdayRoleSelect(self)
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "back",
                        "Terug",
                        emoji=BACK_EMOJI,
                    )
                ),
                discord.ui.TextDisplay(
                    "-# De rol wordt automatisch toegevoegd op de verjaardag "
                    "en weer verwijderd zodra de dag voorbij is."
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
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        *,
        notice: str | None = None,
    ) -> "BirthdayRoleView":
        config = await cog.get_config(guild_id)

        body = (
            f"# {USER_EMOJI} Verjaardagsrol\n"
            "> └ Kies welke rol leden automatisch krijgen op hun verjaardag.\n\n"
            f"## {STATUS_EMOJI} Huidige rol\n"
            f"> └ <@&{config.birthday_role_id}>"
        )

        return cls(
            cog,
            owner_id,
            guild_id,
            body,
            notice=notice,
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return await self.cog.config_access(
            interaction,
            self.owner_id,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )


# ============================================================
# BEHAVIOUR CONFIG
# ============================================================

class BirthdayBehaviourView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        config: BirthdayConfig,
        *,
        notice: str | None = None,
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.config = config

        def state(value: bool) -> str:
            return "Aan" if value else "Uit"

        body = (
            f"# {SETTINGS_EMOJI} Gedrag\n"
            "> └ Schakel onderdelen van het verjaardagssysteem los van elkaar in of uit.\n\n"
            f"## {STATUS_EMOJI} Status\n"
            f"> └ Automatische kaarten: **{state(config.announcements_enabled)}**\n"
            f"> └ Openbare felicitaties: **{state(config.public_congrats_enabled)}**\n"
            f"> └ Willekeurige felicitaties: **{state(config.random_congrats_enabled)}**\n"
            f"> └ Birthday XP: **{state(config.birthday_xp_enabled)}**\n"
            f"> └ Feliciteer XP: **{state(config.congrats_xp_enabled)}**\n"
            f"> └ Profielfoto op kaart: **{state(config.show_avatar)}**"
        )

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(body),
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
                    ConfigButton(
                        self,
                        "announcements",
                        (
                            "Kaarten uit"
                            if config.announcements_enabled
                            else "Kaarten aan"
                        ),
                        emoji=NOTIFICATION_EMOJI,
                        style=(
                            discord.ButtonStyle.danger
                            if config.announcements_enabled
                            else discord.ButtonStyle.success
                        ),
                    ),
                    ConfigButton(
                        self,
                        "public",
                        (
                            "Openbaar uit"
                            if config.public_congrats_enabled
                            else "Openbaar aan"
                        ),
                        emoji=USER_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "random",
                        (
                            "Random uit"
                            if config.random_congrats_enabled
                            else "Random aan"
                        ),
                        emoji=REFRESH_EMOJI,
                    ),
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "birthday_xp",
                        (
                            "Birthday XP uit"
                            if config.birthday_xp_enabled
                            else "Birthday XP aan"
                        ),
                        emoji=STATUS_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "congrats_xp",
                        (
                            "Feliciteer XP uit"
                            if config.congrats_xp_enabled
                            else "Feliciteer XP aan"
                        ),
                        emoji=STATUS_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "avatar",
                        (
                            "Avatar uit"
                            if config.show_avatar
                            else "Avatar aan"
                        ),
                        emoji=USER_EMOJI,
                    ),
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "back",
                        "Terug",
                        emoji=BACK_EMOJI,
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

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return await self.cog.config_access(
            interaction,
            self.owner_id,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )
            return

        mapping = {
            "announcements": (
                "announcements_enabled",
                not self.config.announcements_enabled,
                "Automatische verjaardagskaarten aangepast.",
            ),
            "public": (
                "public_congrats_enabled",
                not self.config.public_congrats_enabled,
                "Openbare felicitaties aangepast.",
            ),
            "random": (
                "random_congrats_enabled",
                not self.config.random_congrats_enabled,
                "Willekeurige felicitaties aangepast.",
            ),
            "birthday_xp": (
                "birthday_xp_enabled",
                not self.config.birthday_xp_enabled,
                "Birthday XP aangepast.",
            ),
            "congrats_xp": (
                "congrats_xp_enabled",
                not self.config.congrats_xp_enabled,
                "Feliciteer XP aangepast.",
            ),
            "avatar": (
                "show_avatar",
                not self.config.show_avatar,
                "Profielfoto-instelling aangepast.",
            ),
        }

        if action not in mapping:
            return

        column, value, notice = mapping[action]

        await self.cog.update_config(
            self.guild_id,
            **{column: value},
        )

        config = await self.cog.get_config(
            self.guild_id
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=BirthdayBehaviourView(
                self.cog,
                self.owner_id,
                self.guild_id,
                config,
                notice=notice,
            ),
        )


# ============================================================
# RESET
# ============================================================

class BirthdayResetView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Config resetten\n"
                    "> └ Hiermee worden alleen de instellingen teruggezet.\n"
                    "> └ Ingestelde verjaardagen en eerdere felicitaties blijven bewaard."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "confirm",
                        "Ja, reset",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                    ConfigButton(
                        self,
                        "cancel",
                        "Annuleren",
                        emoji=BACK_EMOJI,
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
        return await self.cog.config_access(
            interaction,
            self.owner_id,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "cancel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )
            return

        if action == "confirm":
            await self.cog.reset_config(
                self.guild_id
            )

            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    notice="Verjaardagsconfig teruggezet naar standaard.",
                ),
            )


# ============================================================
# CONFIG HOME
# ============================================================

class BirthdayConfigView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(timeout=600)

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(body),
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
                    ConfigButton(
                        self,
                        "texts",
                        "Teksten",
                        emoji=EDIT_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ConfigButton(
                        self,
                        "channel",
                        "Kanaal",
                        emoji=NOTIFICATION_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "congratulations",
                        "Felicitaties",
                        emoji=USER_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "behaviour",
                        "Gedrag",
                        emoji=SETTINGS_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "role",
                        "Rol",
                        emoji=USER_EMOJI,
                    ),
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "preview",
                        "Preview",
                        emoji=INFO_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "reset",
                        "Reset standaard",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# Admins en de server owner kunnen dit systeem configureren."
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
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        *,
        notice: str | None = None,
    ) -> "BirthdayConfigView":
        config = await cog.get_config(
            guild_id
        )

        message_count = len(
            [
                line
                for line in config.congrats_messages.splitlines()
                if line.strip()
            ]
        )

        def state(value: bool) -> str:
            return "Aan" if value else "Uit"

        body = (
            "# 🎂 Verjaardagen Config\n"
            "> └ Beheer hier het volledige verjaardagssysteem.\n\n"
            f"## {NOTIFICATION_EMOJI} Automatisch bericht\n"
            f"> └ Kanaal: "
            f"{f'<#{config.channel_id}>' if config.channel_id else '**niet ingesteld**'}\n"
            f"> └ Verjaardagskaarten: **{state(config.announcements_enabled)}**\n\n"
            f"## {USER_EMOJI} Feliciteren\n"
            f"> └ Openbare reacties: **{state(config.public_congrats_enabled)}**\n"
            f"> └ Willekeurige teksten: **{state(config.random_congrats_enabled)}**\n"
            f"> └ Beschikbare felicitaties: **{message_count}**\n\n"
            f"## {STATUS_EMOJI} Extra\n"
            f"> └ Birthday XP: **{state(config.birthday_xp_enabled)}**\n"
            f"> └ Feliciteer XP: **{state(config.congrats_xp_enabled)}**\n"
            f"> └ Profielfoto: **{state(config.show_avatar)}**\n"
            f"> └ Verjaardagsrol: <@&{config.birthday_role_id}>\n\n"
            "## Placeholders\n"
            "> └ Kaart: `{member}` • `{member_name}` • `{guild}` • `{date}`\n"
            "> └ Ook: `{day}` • `{month}` • `{year}`\n"
            "> └ Felicitaties extra: `{user}` • `{user_name}`"
        )

        return cls(
            cog,
            owner_id,
            guild_id,
            body,
            notice=notice,
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return await self.cog.config_access(
            interaction,
            self.owner_id,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "texts":
            config = await self.cog.get_config(
                self.guild_id
            )

            await interaction.response.send_modal(
                BirthdayTextModal(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    config,
                )
            )
            return

        if action == "congratulations":
            config = await self.cog.get_config(
                self.guild_id
            )

            await interaction.response.send_modal(
                CongratulationsModal(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    config,
                )
            )
            return

        if action == "channel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayChannelView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )
            return

        if action == "behaviour":
            config = await self.cog.get_config(
                self.guild_id
            )

            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=BirthdayBehaviourView(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    config,
                ),
            )
            return

        if action == "role":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayRoleView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )
            return

        if action == "preview":
            if interaction.guild is None:
                await self.cog.send_feedback(
                    interaction,
                    "Server niet gevonden.",
                    kind="error",
                )
                return

            config = await self.cog.get_config(
                self.guild_id
            )

            member = interaction.user
            if not isinstance(member, discord.Member):
                return

            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=BirthdayPreviewView(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    member,
                    config,
                ),
            )
            return

        if action == "reset":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=BirthdayResetView(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )


class BirthdayPreviewView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Birthdays",
        owner_id: int,
        guild_id: int,
        member: discord.Member,
        config: BirthdayConfig,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        card = BirthdayAnnouncementView(
            member,
            config,
            year=datetime.now(TZ).year,
            congratulations=7,
            birthday_xp=250 if config.birthday_xp_enabled else 0,
            preview=True,
        )

        # BirthdayAnnouncementView heeft één container; hergebruik die in
        # dezelfde V2-layout en voeg een terugknop toe.
        for item in list(card.children):
            self.add_item(item)

        self.add_item(
            discord.ui.ActionRow(
                ConfigButton(
                    self,
                    "back",
                    "Terug naar config",
                    emoji=BACK_EMOJI,
                )
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return await self.cog.config_access(
            interaction,
            self.owner_id,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await BirthdayConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )


# ============================================================
# COG
# ============================================================

class Birthdays(commands.Cog):
    verjaardag = app_commands.Group(
        name="verjaardag",
        description="Verjaardagen op LEVENLOOS.",
    )

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    async def cog_load(self) -> None:
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Birthdays vereist Components V2."
            )

        await init_db()

        if not self.birthday_loop.is_running():
            self.birthday_loop.start()

        logger.info("Birthdays-module geladen.")

    def cog_unload(self) -> None:
        if self.birthday_loop.is_running():
            self.birthday_loop.cancel()

    # ========================================================
    # FEEDBACK / ACCESS
    # ========================================================

    async def send_feedback(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
        footer: str | None = None,
    ) -> None:
        view = BirthdayFeedbackView(
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

    async def config_access(
        self,
        interaction: discord.Interaction,
        owner_id: int,
    ) -> bool:
        if (
            interaction.user.id == owner_id
            and isinstance(
                interaction.user,
                discord.Member,
            )
            and is_admin(interaction.user)
        ):
            return True

        await self.send_feedback(
            interaction,
            "Dit configuratiemenu is niet van jou.",
            kind="error",
            title="Geen toegang",
        )
        return False

    # ========================================================
    # CONFIG DATABASE
    # ========================================================

    async def get_config(
        self,
        guild_id: int,
    ) -> BirthdayConfig:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO birthday_config (
                    guild_id,
                    channel_id,
                    announcements_enabled
                )
                VALUES (?, ?, 1)
                """,
                (
                    guild_id,
                    DEFAULT_BIRTHDAY_CHANNEL_ID,
                ),
            )
            await db.commit()

            cursor = await db.execute(
                """
                SELECT
                    channel_id,
                    announcements_enabled,
                    announcement_title,
                    announcement_message,
                    button_label,
                    footer_text,
                    public_congrats_enabled,
                    random_congrats_enabled,
                    birthday_xp_enabled,
                    congrats_xp_enabled,
                    show_avatar,
                    congrats_messages,
                    birthday_role_id
                FROM birthday_config
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()

        return BirthdayConfig(
            guild_id=guild_id,
            channel_id=int(row[0] or 0),
            announcements_enabled=bool(row[1]),
            announcement_title=(
                str(row[2]).strip()
                or DEFAULT_ANNOUNCEMENT_TITLE
            ),
            announcement_message=(
                str(row[3]).strip()
                or DEFAULT_ANNOUNCEMENT_MESSAGE
            ),
            button_label=(
                str(row[4]).strip()
                or DEFAULT_BUTTON_LABEL
            ),
            footer_text=(
                str(row[5]).strip()
                or DEFAULT_FOOTER
            ),
            public_congrats_enabled=bool(row[6]),
            random_congrats_enabled=bool(row[7]),
            birthday_xp_enabled=bool(row[8]),
            congrats_xp_enabled=bool(row[9]),
            show_avatar=bool(row[10]),
            congrats_messages=(
                str(row[11]).strip()
                or DEFAULT_CONGRAT_MESSAGES
            ),
            birthday_role_id=int(
                row[12]
                or DEFAULT_BIRTHDAY_ROLE_ID
            ),
        )

    async def update_config(
        self,
        guild_id: int,
        **values,
    ) -> None:
        await self.get_config(guild_id)

        allowed = {
            "channel_id",
            "announcements_enabled",
            "announcement_title",
            "announcement_message",
            "button_label",
            "footer_text",
            "public_congrats_enabled",
            "random_congrats_enabled",
            "birthday_xp_enabled",
            "congrats_xp_enabled",
            "show_avatar",
            "congrats_messages",
            "birthday_role_id",
        }

        clean = {
            key: (
                int(value)
                if isinstance(value, bool)
                else value
            )
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
                UPDATE birthday_config
                SET {assignments}
                WHERE guild_id = ?
                """,
                (
                    *clean.values(),
                    guild_id,
                ),
            )
            await db.commit()

    async def reset_config(
        self,
        guild_id: int,
    ) -> None:
        config = await self.get_config(
            guild_id
        )

        await self.update_config(
            guild_id,
            channel_id=config.channel_id,
            announcements_enabled=True,
            announcement_title=DEFAULT_ANNOUNCEMENT_TITLE,
            announcement_message=DEFAULT_ANNOUNCEMENT_MESSAGE,
            button_label=DEFAULT_BUTTON_LABEL,
            footer_text=DEFAULT_FOOTER,
            public_congrats_enabled=True,
            random_congrats_enabled=True,
            birthday_xp_enabled=True,
            congrats_xp_enabled=True,
            show_avatar=True,
            congrats_messages=DEFAULT_CONGRAT_MESSAGES,
            birthday_role_id=DEFAULT_BIRTHDAY_ROLE_ID,
        )

    # ========================================================
    # BIRTHDAY DATABASE
    # ========================================================

    async def get_birthday(
        self,
        guild_id: int,
        user_id: int,
    ):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT day, month
                FROM birthdays
                WHERE guild_id = ?
                  AND user_id = ?
                """,
                (
                    guild_id,
                    user_id,
                ),
            )
            return await cursor.fetchone()

    async def set_birthday(
        self,
        guild_id: int,
        user_id: int,
        day: int,
        month: int,
        actor_id: int,
        allow_update: bool,
    ) -> bool:
        now = int(time.time())

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT 1
                FROM birthdays
                WHERE guild_id = ?
                  AND user_id = ?
                """,
                (
                    guild_id,
                    user_id,
                ),
            )
            exists = await cursor.fetchone() is not None

            if exists and not allow_update:
                return False

            if exists:
                await db.execute(
                    """
                    UPDATE birthdays
                    SET day = ?,
                        month = ?,
                        updated_at = ?,
                        updated_by = ?
                    WHERE guild_id = ?
                      AND user_id = ?
                    """,
                    (
                        day,
                        month,
                        now,
                        actor_id,
                        guild_id,
                        user_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO birthdays (
                        guild_id,
                        user_id,
                        day,
                        month,
                        created_at,
                        updated_at,
                        updated_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        user_id,
                        day,
                        month,
                        now,
                        now,
                        actor_id,
                    ),
                )

            await db.commit()

        return True

    def valid_date(
        self,
        day: int,
        month: int,
    ) -> bool:
        if not 1 <= month <= 12:
            return False

        max_day = (
            29
            if month == 2
            else calendar.monthrange(
                2025,
                month,
            )[1]
        )
        return 1 <= day <= max_day

    async def congratulations_count(
        self,
        guild_id: int,
        birthday_user_id: int,
        year: int,
    ) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM birthday_congrats
                WHERE guild_id = ?
                  AND birthday_user_id = ?
                  AND year = ?
                """,
                (
                    guild_id,
                    birthday_user_id,
                    year,
                ),
            )
            row = await cursor.fetchone()

        return int(row[0] or 0)

    async def birthday_post_xp(
        self,
        guild_id: int,
        user_id: int,
        year: int,
    ) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT xp_awarded
                FROM birthday_posts
                WHERE guild_id = ?
                  AND user_id = ?
                  AND year = ?
                """,
                (
                    guild_id,
                    user_id,
                    year,
                ),
            )
            row = await cursor.fetchone()

        return int(row[0] or 0) if row else 0

    async def all_birthdays(
        self,
        guild: discord.Guild,
    ) -> list[tuple[discord.Member, int, int]]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT user_id, day, month
                FROM birthdays
                WHERE guild_id = ?
                """,
                (guild.id,),
            )
            rows = await cursor.fetchall()

        result = []

        for user_id, day, month in rows:
            member = guild.get_member(
                int(user_id)
            )
            if (
                member is None
                or member.bot
            ):
                continue

            result.append(
                (
                    member,
                    int(day),
                    int(month),
                )
            )

        return result

    # ========================================================
    # XP
    # ========================================================

    async def award_levels_source(
        self,
        guild: discord.Guild,
        user_id: int,
        source: str,
        source_key: str,
        subject_id: int,
    ) -> int:
        levels = self.bot.get_cog(
            "Levels"
        )

        if (
            levels is None
            or not hasattr(
                levels,
                "award_source",
            )
        ):
            return 0

        try:
            return int(
                await levels.award_source(
                    guild,
                    user_id,
                    source,
                    source_key,
                    subject_id,
                )
                or 0
            )
        except Exception:
            logger.exception(
                "Birthday XP via Levels toekennen mislukt."
            )
            return 0

    # ========================================================
    # PUBLIC CARD HELPERS
    # ========================================================

    async def build_announcement_view(
        self,
        member: discord.Member,
        *,
        year: int,
        preview: bool = False,
    ) -> BirthdayAnnouncementView:
        config = await self.get_config(
            member.guild.id
        )

        count = (
            7
            if preview
            else await self.congratulations_count(
                member.guild.id,
                member.id,
                year,
            )
        )

        xp = (
            250
            if preview and config.birthday_xp_enabled
            else await self.birthday_post_xp(
                member.guild.id,
                member.id,
                year,
            )
        )

        return BirthdayAnnouncementView(
            member,
            config,
            year=year,
            congratulations=count,
            birthday_xp=xp,
            preview=preview,
        )

    async def refresh_birthday_message(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        year: int,
    ) -> None:
        if interaction.message is None:
            return

        try:
            await interaction.message.edit(
                content=None,
                embeds=[],
                view=await self.build_announcement_view(
                    member,
                    year=year,
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Birthday kaart kon niet worden vernieuwd."
            )

    # ========================================================
    # /VERJAARDAG INSTELLEN
    # ========================================================

    @verjaardag.command(
        name="instellen",
        description="Stel éénmalig je verjaardag in.",
    )
    async def instellen(
        self,
        interaction: discord.Interaction,
        dag: app_commands.Range[int, 1, 31],
        maand: app_commands.Range[int, 1, 12],
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

        if not self.valid_date(
            dag,
            maand,
        ):
            await self.send_feedback(
                interaction,
                "Dat is geen geldige datum.",
                kind="error",
            )
            return

        existing = await self.get_birthday(
            interaction.guild.id,
            interaction.user.id,
        )

        if existing:
            await self.send_feedback(
                interaction,
                (
                    "Je verjaardag staat al ingesteld op "
                    f"**{format_birthday(existing[0], existing[1])}**.\n"
                    "Alleen een admin kan deze datum wijzigen."
                ),
                kind="warning",
                title="Al ingesteld",
            )
            return

        await self.set_birthday(
            interaction.guild.id,
            interaction.user.id,
            dag,
            maand,
            interaction.user.id,
            False,
        )

        await self.send_feedback(
            interaction,
            (
                "Je verjaardag is ingesteld op "
                f"**{format_birthday(dag, maand)}**.\n"
                "Neem contact op met een admin als de datum ooit aangepast moet worden."
            ),
            kind="success",
            title="Verjaardag ingesteld",
        )

    # ========================================================
    # /VERJAARDAG WIJZIG
    # ========================================================

    @verjaardag.command(
        name="wijzig",
        description="Wijzig als admin de verjaardag van een lid.",
    )
    async def wijzig(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        dag: app_commands.Range[int, 1, 31],
        maand: app_commands.Range[int, 1, 12],
    ) -> None:
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
                title="Geen toegang",
            )
            return

        if not self.valid_date(
            dag,
            maand,
        ):
            await self.send_feedback(
                interaction,
                "Dat is geen geldige datum.",
                kind="error",
            )
            return

        await self.set_birthday(
            interaction.guild.id,
            member.id,
            dag,
            maand,
            interaction.user.id,
            True,
        )

        await self.send_feedback(
            interaction,
            (
                f"De verjaardag van {member.mention} is gewijzigd naar "
                f"**{format_birthday(dag, maand)}**."
            ),
            kind="success",
        )

    # ========================================================
    # /VERJAARDAG VERWIJDER
    # ========================================================

    @verjaardag.command(
        name="verwijder",
        description="Verwijder als admin de verjaardag van een lid.",
    )
    async def verwijder(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
                title="Geen toegang",
            )
            return

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                DELETE FROM birthdays
                WHERE guild_id = ?
                  AND user_id = ?
                """,
                (
                    interaction.guild.id,
                    member.id,
                ),
            )
            await db.commit()

        if cursor.rowcount == 0:
            await self.send_feedback(
                interaction,
                f"{member.mention} had geen verjaardag ingesteld.",
                kind="info",
            )
            return

        await self.send_feedback(
            interaction,
            f"De verjaardag van {member.mention} is verwijderd.",
            kind="success",
        )

    # ========================================================
    # /VERJAARDAG INFO
    # ========================================================

    @verjaardag.command(
        name="info",
        description="Bekijk een ingestelde verjaardag.",
    )
    async def info(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        target = member or interaction.user

        if not isinstance(
            target,
            discord.Member,
        ):
            return

        row = await self.get_birthday(
            interaction.guild.id,
            target.id,
        )

        if not row:
            await self.send_feedback(
                interaction,
                f"{target.mention} heeft nog geen verjaardag ingesteld.",
                kind="info",
                title="Geen verjaardag",
            )
            return

        next_date = next_birthday_date(
            int(row[0]),
            int(row[1]),
        )
        days = (
            next_date
            - datetime.now(TZ).date()
        ).days

        when = (
            "vandaag"
            if days == 0
            else "morgen"
            if days == 1
            else f"over {days} dagen"
        )

        await self.send_feedback(
            interaction,
            (
                f"{target.mention}: **{format_birthday(row[0], row[1])}**.\n"
                f"Volgende verjaardag: **{when}**."
            ),
            kind="info",
            title="Verjaardag",
        )

    # ========================================================
    # /VERJAARDAG OVERZICHT
    # ========================================================

    @verjaardag.command(
        name="overzicht",
        description="Bekijk de aankomende verjaardagen.",
    )
    async def overzicht(
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

        rows = await self.all_birthdays(
            interaction.guild
        )
        today = datetime.now(TZ).date()

        calculated = []

        for member, day, month in rows:
            next_date = next_birthday_date(
                day,
                month,
                today=today,
            )

            calculated.append(
                (
                    member,
                    day,
                    month,
                    (next_date - today).days,
                )
            )

        calculated.sort(
            key=lambda item: (
                item[3],
                item[0].display_name.casefold(),
            )
        )

        today_members = [
            item[0]
            for item in calculated
            if item[3] == 0
        ]

        await interaction.response.send_message(
            view=BirthdayOverviewView(
                total=len(calculated),
                today_members=today_members,
                upcoming=calculated[:12],
            ),
            ephemeral=True,
        )

    # ========================================================
    # /VERJAARDAG CONFIG
    # ========================================================

    @verjaardag.command(
        name="config",
        description="Open het volledige verjaardagen-configuratiepaneel.",
    )
    async def config(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Alleen een admin of owner kan verjaardagen configureren.",
                kind="error",
                title="Geen toegang",
            )
            return

        await interaction.response.send_message(
            view=await BirthdayConfigView.create(
                self,
                interaction.user.id,
                interaction.guild.id,
            ),
            ephemeral=True,
        )

    # ========================================================
    # /VERJAARDAG TEST
    # ========================================================

    @verjaardag.command(
        name="test",
        description="Bekijk een preview van de verjaardagskaart.",
    )
    async def test(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Alleen een admin of owner kan deze preview gebruiken.",
                kind="error",
                title="Geen toegang",
            )
            return

        config = await self.get_config(
            interaction.guild.id
        )

        await interaction.response.send_message(
            view=BirthdayAnnouncementView(
                interaction.user,
                config,
                year=datetime.now(TZ).year,
                congratulations=7,
                birthday_xp=(
                    250
                    if config.birthday_xp_enabled
                    else 0
                ),
                preview=True,
            ),
            ephemeral=True,
        )

    # ========================================================
    # CONGRATULATE BUTTON
    # ========================================================

    @commands.Cog.listener()
    async def on_interaction(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if (
            interaction.type
            is not discord.InteractionType.component
            or not interaction.data
        ):
            return

        custom_id = interaction.data.get(
            "custom_id",
            "",
        )

        if not custom_id.startswith(
            "birthday_congrats:"
        ):
            return

        parts = custom_id.split(":")

        if (
            len(parts) != 3
            or interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
        ):
            return

        try:
            birthday_user_id = int(parts[1])
            year = int(parts[2])
        except ValueError:
            await self.send_feedback(
                interaction,
                "Deze verjaardagsknop is ongeldig.",
                kind="error",
            )
            return

        if interaction.user.id == birthday_user_id:
            await self.send_feedback(
                interaction,
                "Je kunt jezelf niet feliciteren.",
                kind="warning",
                title="Dat telt niet",
            )
            return

        if interaction.user.bot:
            return

        member = interaction.guild.get_member(
            birthday_user_id
        )

        if member is None:
            await self.send_feedback(
                interaction,
                "De jarige is niet meer op de server.",
                kind="error",
            )
            return

        try:
            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                await db.execute(
                    """
                    INSERT INTO birthday_congrats (
                        guild_id,
                        birthday_user_id,
                        congratulator_id,
                        year,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        interaction.guild.id,
                        birthday_user_id,
                        interaction.user.id,
                        year,
                        int(time.time()),
                    ),
                )
                await db.commit()
        except aiosqlite.IntegrityError:
            await self.send_feedback(
                interaction,
                f"Je hebt {member.mention} dit jaar al gefeliciteerd.",
                kind="info",
                title="Al gefeliciteerd",
            )
            return
        except aiosqlite.Error:
            logger.exception(
                "Birthday felicitatie opslaan mislukt."
            )
            await self.send_feedback(
                interaction,
                "Je felicitatie kon niet worden opgeslagen.",
                kind="error",
            )
            return

        config = await self.get_config(
            interaction.guild.id
        )

        amount = 0
        if config.congrats_xp_enabled:
            amount = await self.award_levels_source(
                interaction.guild,
                interaction.user.id,
                "congrats",
                (
                    f"birthday_congrats:"
                    f"{birthday_user_id}:"
                    f"{interaction.user.id}:"
                    f"{year}"
                ),
                birthday_user_id,
            )

        await interaction.response.defer(
            ephemeral=True
        )

        public_sent = False

        if (
            config.public_congrats_enabled
            and interaction.channel is not None
        ):
            values = template_values(
                guild=interaction.guild,
                member=member,
                user=interaction.user,
            )

            if config.random_congrats_enabled:
                choices = [
                    line.strip()
                    for line in config.congrats_messages.splitlines()
                    if line.strip()
                ]
                template = (
                    random.choice(choices)
                    if choices
                    else "{user} feliciteert {member}!"
                )
            else:
                template = "{user} feliciteert {member}!"

            message = render_template(
                template,
                values,
            )

            try:
                await interaction.channel.send(
                    message,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
                public_sent = True
            except discord.HTTPException:
                logger.exception(
                    "Openbare birthday felicitatie versturen mislukt."
                )

        await self.refresh_birthday_message(
            interaction,
            member,
            year,
        )

        confirmation = (
            f"Je hebt {member.mention} gefeliciteerd."
        )

        if amount > 0:
            confirmation += (
                f"\nJe kreeg **+{amount} XP**."
            )

        if (
            config.public_congrats_enabled
            and not public_sent
        ):
            confirmation += (
                "\nDe openbare felicitatie kon niet worden geplaatst."
            )

        await interaction.followup.send(
            view=BirthdayFeedbackView(
                confirmation,
                kind="success",
                title="Gefeliciteerd!",
            ),
            ephemeral=True,
        )

    # ========================================================
    # BIRTHDAY ROLE
    # ========================================================

    async def today_birthday_user_ids(
        self,
        guild_id: int,
        now: datetime,
    ) -> set[int]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT user_id
                FROM birthdays
                WHERE guild_id = ?
                  AND day = ?
                  AND month = ?
                """,
                (
                    guild_id,
                    now.day,
                    now.month,
                ),
            )
            rows = await cursor.fetchall()

        return {
            int(row[0])
            for row in rows
        }

    async def reconcile_birthday_role(
        self,
        guild: discord.Guild,
        now: datetime,
    ) -> None:
        config = await self.get_config(
            guild.id
        )

        role = guild.get_role(
            config.birthday_role_id
        )

        if role is None:
            logger.warning(
                "Verjaardagsrol %s bestaat niet in guild %s.",
                config.birthday_role_id,
                guild.id,
            )
            return

        me = guild.me
        if me is None:
            return

        if (
            not me.guild_permissions.manage_roles
            or role >= me.top_role
        ):
            logger.warning(
                "Bot kan verjaardagsrol %s niet beheren in guild %s.",
                role.id,
                guild.id,
            )
            return

        birthday_ids = await self.today_birthday_user_ids(
            guild.id,
            now,
        )

        # Voeg de rol toe aan iedereen die vandaag jarig is.
        for user_id in birthday_ids:
            member = guild.get_member(
                user_id
            )

            if (
                member is None
                or member.bot
                or role in member.roles
            ):
                continue

            try:
                await member.add_roles(
                    role,
                    reason="Automatische verjaardagsrol",
                )
                logger.info(
                    "Verjaardagsrol %s toegevoegd aan %s (%s).",
                    role.id,
                    member,
                    member.id,
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Verjaardagsrol toevoegen mislukt voor %s in guild %s.",
                    user_id,
                    guild.id,
                )

        # Verwijder de rol zodra de verjaardag voorbij is.
        for member in list(role.members):
            if (
                member.bot
                or member.id in birthday_ids
            ):
                continue

            try:
                await member.remove_roles(
                    role,
                    reason="Verjaardag voorbij",
                )
                logger.info(
                    "Verjaardagsrol %s verwijderd van %s (%s).",
                    role.id,
                    member,
                    member.id,
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Verjaardagsrol verwijderen mislukt voor %s in guild %s.",
                    member.id,
                    guild.id,
                )

    # ========================================================
    # BIRTHDAY LOOP
    # ========================================================

    @tasks.loop(minutes=10)
    async def birthday_loop(self) -> None:
        now = datetime.now(TZ)

        for guild in self.bot.guilds:
            try:
                await self.process_birthdays(
                    guild,
                    now,
                )
            except Exception:
                logger.exception(
                    "Birthday-loop mislukt voor guild %s.",
                    guild.id,
                )

    async def process_birthdays(
        self,
        guild: discord.Guild,
        now: datetime,
    ) -> None:
        config = await self.get_config(
            guild.id
        )

        # De verjaardagsrol werkt onafhankelijk van verjaardagsmeldingen.
        await self.reconcile_birthday_role(
            guild,
            now,
        )

        if (
            not config.announcements_enabled
            or not config.channel_id
        ):
            return

        channel = guild.get_channel(
            config.channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            logger.warning(
                "Birthday kanaal %s bestaat niet in guild %s.",
                config.channel_id,
                guild.id,
            )
            return

        me = guild.me

        if (
            me is None
            or not channel.permissions_for(me).send_messages
        ):
            logger.warning(
                "Bot kan niet sturen in birthday kanaal %s.",
                channel.id,
            )
            return

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT user_id
                FROM birthdays
                WHERE guild_id = ?
                  AND day = ?
                  AND month = ?
                """,
                (
                    guild.id,
                    now.day,
                    now.month,
                ),
            )
            users = [
                int(row[0])
                for row in await cursor.fetchall()
            ]

        for user_id in users:
            member = guild.get_member(
                user_id
            )

            if (
                member is None
                or member.bot
            ):
                continue

            try:
                async with aiosqlite.connect(
                    DATABASE_PATH
                ) as db:
                    await db.execute(
                        """
                        INSERT INTO birthday_posts (
                            guild_id,
                            user_id,
                            year,
                            created_at,
                            xp_awarded
                        )
                        VALUES (?, ?, ?, ?, 0)
                        """,
                        (
                            guild.id,
                            user_id,
                            now.year,
                            int(time.time()),
                        ),
                    )
                    await db.commit()
            except aiosqlite.IntegrityError:
                continue

            amount = 0

            if config.birthday_xp_enabled:
                amount = await self.award_levels_source(
                    guild,
                    user_id,
                    "birthday",
                    f"birthday:{user_id}:{now.year}",
                    user_id,
                )

            try:
                message = await channel.send(
                    view=BirthdayAnnouncementView(
                        member,
                        config,
                        year=now.year,
                        congratulations=0,
                        birthday_xp=amount,
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except discord.HTTPException:
                logger.exception(
                    "Birthday kaart versturen mislukt voor %s.",
                    user_id,
                )

                # Post-reservering verwijderen zodat de loop later opnieuw
                # kan proberen wanneer Discord tijdelijk faalde.
                async with aiosqlite.connect(
                    DATABASE_PATH
                ) as db:
                    await db.execute(
                        """
                        DELETE FROM birthday_posts
                        WHERE guild_id = ?
                          AND user_id = ?
                          AND year = ?
                        """,
                        (
                            guild.id,
                            user_id,
                            now.year,
                        ),
                    )
                    await db.commit()
                continue

            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                await db.execute(
                    """
                    UPDATE birthday_posts
                    SET message_id = ?,
                        xp_awarded = ?
                    WHERE guild_id = ?
                      AND user_id = ?
                      AND year = ?
                    """,
                    (
                        message.id,
                        amount,
                        guild.id,
                        user_id,
                        now.year,
                    ),
                )
                await db.commit()

    @birthday_loop.before_loop
    async def before_birthday_loop(self) -> None:
        await self.bot.wait_until_ready()


# ============================================================
# EXTENSION SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Birthdays(bot)
    )
