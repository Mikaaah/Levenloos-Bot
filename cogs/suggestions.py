import asyncio
import binascii
import io
import logging
import re
import struct
import zlib
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

DB_PATH = "levenloos.db"
PURPLE = discord.Colour.from_rgb(108, 39, 218)

SUGGESTION_COOLDOWN_MINUTES = 5
VOTING_DAYS = 7

HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")

logger = logging.getLogger(__name__)


# ============================================================
# LEVENLOOS CUSTOM EMOJIS
# ============================================================

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
COLOR_EMOJI = "<:color:1547724074472575126>"

ADD_EMOJI = "<:add:1547724100812931072>"
EDIT_EMOJI = "<:edit:1547724058894934116>"
DELETE_EMOJI = "<:delete:1547724056768286750>"
REFRESH_EMOJI = "<:refresh:1547724055426244618>"
BACK_EMOJI = "<:back:1547724054038052966>"
PREVIOUS_EMOJI = "<:previous:1547724049411739748>"
NEXT_EMOJI = "<:next:1547724052037247106>"
GRADIENT_EMOJI = "<:gradient:1547724045657575494>"
PASTE_EMOJI = "<:paste:1547724044231778345>"
FORMAT_EMOJI = "<:format:1547724042658906172>"
LOCK_EMOJI = "<:lock:1547724040888786966>"
NONE_EMOJI = "<:none:1547724038955208794>"
INFO_EMOJI = "<:info:1547724036107149413>"

# Nog aan te leveren. Tot die tijd worden de betreffende knoppen bewust
# zonder willekeurige Unicode-vervanger weergegeven.
GENERAL_EMOJI = "<:idea:1547733053785251951>"
BOT_EMOJI = "<:bot:1547733042150514748>"
EVENT_EMOJI = "<:event:1547733040493498439>"
LIST_EMOJI = "<:list:1547733039361163427>"


# ============================================================
# GENERIC HELPERS
# ============================================================

def has_management_access(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True

    if member.guild_permissions.administrator:
        return True

    role_names = {role.name.casefold() for role in member.roles}
    return "admin" in role_names or "owner" in role_names


def component_emoji(value: str | None) -> discord.PartialEmoji | None:
    if not value:
        return None

    try:
        emoji = discord.PartialEmoji.from_str(value)
    except Exception:
        logger.warning("Kon custom emoji niet parsen: %s", value)
        return None

    return emoji if emoji.name else None


def markdown_icon(value: str | None) -> str:
    return f"{value} " if value else ""


def normalize_hex(value: str) -> str:
    value = value.strip()

    if not value.startswith("#"):
        value = f"#{value}"

    if not HEX_RE.fullmatch(value):
        raise ValueError("Gebruik een HEX-kleur zoals `#A93BD6`.")

    return value.upper()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    payload = chunk_type + data
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", binascii.crc32(payload) & 0xFFFFFFFF)
    )


def make_gradient_png(
    color1: str,
    color2: str | None,
    width: int = 900,
    height: int = 180,
) -> bytes:
    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2 or color1)

    row = bytearray([0])

    for x in range(width):
        t = x / max(width - 1, 1)

        r = round(rgb1[0] + (rgb2[0] - rgb1[0]) * t)
        g = round(rgb1[1] + (rgb2[1] - rgb1[1]) * t)
        b = round(rgb1[2] + (rgb2[2] - rgb1[2]) * t)

        row.extend((r, g, b))

    raw = bytes(row) * height

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    return (
        signature
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )


def status_label(status: str) -> str:
    return {
        "active": "Open",
        "pending_review": "Wacht op beoordeling",
        "accepted": "Geaccepteerd",
        "rejected": "Afgewezen",
        "closed": "Gesloten",
        "cancelled": "Geannuleerd",
    }.get(status, status)


def status_icon(status: str) -> str | None:
    return {
        "active": INFO_EMOJI,
        "pending_review": WARNING_EMOJI,
        "accepted": SUCCESS_EMOJI,
        "rejected": ERROR_EMOJI,
        "closed": LOCK_EMOJI,
        "cancelled": NONE_EMOJI,
    }.get(status)


def status_text(status: str) -> str:
    return f"{markdown_icon(status_icon(status))}{status_label(status)}"


def type_info(suggestion_type: str) -> tuple[str | None, str]:
    return {
        "color": (COLOR_EMOJI, "Gradient"),
        "general": (GENERAL_EMOJI, "Algemeen"),
        "bot": (BOT_EMOJI, "Bot"),
        "event": (EVENT_EMOJI, "Event"),
    }.get(suggestion_type, (GENERAL_EMOJI, "Suggestie"))


def feedback_style(kind: str) -> tuple[str, str | None, discord.Colour]:
    if kind == "success":
        return "Gelukt", SUCCESS_EMOJI, discord.Colour.from_rgb(87, 242, 135)
    if kind == "error":
        return "Fout", ERROR_EMOJI, discord.Colour.from_rgb(237, 66, 69)
    if kind == "warning":
        return "Let op", WARNING_EMOJI, discord.Colour.from_rgb(254, 231, 92)
    return "Informatie", INFO_EMOJI, PURPLE


# ============================================================
# COMPONENTS V2: SMALL FEEDBACK
# ============================================================

class FeedbackView(discord.ui.LayoutView):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
    ):
        super().__init__(timeout=180)

        default_title, icon, accent = feedback_style(kind)
        heading = title or default_title

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"## {markdown_icon(icon)}{heading}\n"
                    f"> └ {message}"
                ),
                accent_colour=accent,
            )
        )


# ============================================================
# COMPONENTS V2: PUBLIC SUGGESTION CARD
# ============================================================

class VoteButton(discord.ui.Button):
    def __init__(
        self,
        cog: "Suggestions",
        suggestion_id: int,
        vote: int,
        count: int,
        disabled: bool = False,
    ):
        self.cog = cog
        self.suggestion_id = suggestion_id
        self.vote = vote

        if vote == 1:
            super().__init__(
                label=f"Voor • {count}",
                emoji=component_emoji(SUCCESS_EMOJI),
                style=discord.ButtonStyle.success,
                custom_id=f"suggestion:{suggestion_id}:up",
                disabled=disabled,
            )
        else:
            super().__init__(
                label=f"Tegen • {count}",
                emoji=component_emoji(ERROR_EMOJI),
                style=discord.ButtonStyle.danger,
                custom_id=f"suggestion:{suggestion_id}:down",
                disabled=disabled,
            )

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_vote(
            interaction,
            self.suggestion_id,
            self.vote,
        )


class CancelSuggestionButton(discord.ui.Button):
    def __init__(
        self,
        cog: "Suggestions",
        suggestion_id: int,
        disabled: bool = False,
    ):
        self.cog = cog
        self.suggestion_id = suggestion_id

        super().__init__(
            label="Annuleren",
            emoji=component_emoji(NONE_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id=f"suggestion:{suggestion_id}:cancel",
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_cancel(
            interaction,
            self.suggestion_id,
        )


class SuggestionVoteView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Suggestions",
        suggestion,
        upvotes: int = 0,
        downvotes: int = 0,
        disabled: bool = False,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.suggestion_id = int(suggestion["id"])

        suggestion_type = str(suggestion["suggestion_type"])
        icon, label = type_info(suggestion_type)

        title = str(suggestion["title"]).strip()
        status = str(suggestion["status"])

        header = (
            f"# {markdown_icon(icon)}{title}\n"
            f"## {label}\n"
            f"> └ Voorgesteld door <@{suggestion['author_id']}>\n"
            f"> └ Status: **{status_text(status)}**"
        )

        body_lines: list[str] = []

        if suggestion_type == "color":
            color1 = suggestion["color1"]
            color2 = suggestion["color2"]
            level = int(suggestion["level"] or 1)

            body_lines.extend(
                [
                    "## Gradient",
                    f"> └ Vrij vanaf level **{level}**",
                    f"> └ Kleuren: `{color1}` → `{color2}`",
                ]
            )
        elif suggestion["description"]:
            description = str(suggestion["description"]).strip()
            quoted = "\n".join(
                f"> └ {line}" if line.strip() else ">"
                for line in description.splitlines()
            )
            body_lines.extend(
                [
                    "## Beschrijving",
                    quoted,
                ]
            )

        footer_parts = [
            f"Suggestie #{self.suggestion_id}",
            f"{upvotes} voor",
            f"{downvotes} tegen",
        ]

        if status == "active":
            created_at = parse_datetime(str(suggestion["created_at"]))
            closes_at = created_at + timedelta(days=VOTING_DAYS)
            footer_parts.append(f"sluit <t:{int(closes_at.timestamp())}:R>")

        action_row = discord.ui.ActionRow(
            VoteButton(
                cog,
                self.suggestion_id,
                1,
                upvotes,
                disabled=disabled,
            ),
            VoteButton(
                cog,
                self.suggestion_id,
                -1,
                downvotes,
                disabled=disabled,
            ),
            CancelSuggestionButton(
                cog,
                self.suggestion_id,
                disabled=disabled,
            ),
        )

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(header),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            ),
        ]

        if body_lines:
            children.append(
                discord.ui.TextDisplay("\n".join(body_lines))
            )

        if suggestion_type == "color":
            children.append(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        "attachment://kleur-preview.png",
                        description=f"Gradientpreview voor {title}",
                    )
                )
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                action_row,
                discord.ui.TextDisplay(
                    "-# " + " • ".join(footer_parts)
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PURPLE,
            )
        )


# ============================================================
# COMPONENTS V2: SUGGESTION SETUP
# ============================================================

class SuggestionChannelSelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        cog: "Suggestions",
        owner_id: int,
    ):
        super().__init__(
            placeholder="Kies het suggestiekanaal…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            custom_id="suggestion_setup:channel",
        )
        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        if (
            interaction.user.id != self.owner_id
            or not isinstance(interaction.user, discord.Member)
            or not has_management_access(interaction.user)
        ):
            await self.cog.send_feedback(
                interaction,
                "Alleen beheer kan het suggestiekanaal aanpassen.",
                kind="error",
            )
            return

        if interaction.guild is None:
            await self.cog.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        channel = self.values[0]

        await interaction.response.defer(ephemeral=True)

        result, success = await self.cog.apply_suggestion_channel(
            interaction.guild,
            channel,
        )

        current = channel.id if success else await self.cog.get_suggestion_channel_id(
            interaction.guild.id
        )

        await interaction.edit_original_response(
            view=SuggestionSetupView(
                self.cog,
                self.owner_id,
                current_channel_id=current,
                notice=result,
                notice_kind="success" if success else "error",
            )
        )


class SuggestionSetupView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Suggestions",
        owner_id: int,
        *,
        current_channel_id: int | None = None,
        notice: str | None = None,
        notice_kind: str = "info",
    ):
        super().__init__(timeout=300)

        text = (
            "# Suggesties instellen\n"
            "> └ Kies het kanaal waarin suggesties en stemknoppen worden geplaatst."
        )

        if current_channel_id:
            text += f"\n> └ Huidig kanaal: <#{current_channel_id}>"

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(text),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            ),
            discord.ui.ActionRow(
                SuggestionChannelSelect(cog, owner_id)
            ),
        ]

        if notice:
            _, icon, _ = feedback_style(notice_kind)
            children.append(
                discord.ui.TextDisplay(
                    f"-# {markdown_icon(icon)}{notice}"
                )
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PURPLE,
            )
        )


# ============================================================
# MODALS
# ============================================================

class SimpleSuggestionModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Suggestions",
        suggestion_type: str,
        title: str,
    ):
        super().__init__(title=title, timeout=300)

        self.cog = cog
        self.suggestion_type = suggestion_type

        self.title_input = discord.ui.TextInput(
            label="Korte titel",
            placeholder="Waar gaat je idee over?",
            min_length=2,
            max_length=60,
        )
        self.description_input = discord.ui.TextInput(
            label="Beschrijving",
            style=discord.TextStyle.paragraph,
            placeholder="Leg duidelijk uit wat je bedoelt en waarom dit leuk of nuttig is.",
            min_length=5,
            max_length=1000,
        )

        self.add_item(self.title_input)
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.cog.check_cooldown(interaction):
            return

        await self.cog.create_suggestion(
            interaction,
            suggestion_type=self.suggestion_type,
            title=" ".join(self.title_input.value.split()).strip(),
            description=self.description_input.value.strip(),
        )


class ColorSuggestionModal(discord.ui.Modal, title="Nieuwe gradient voorstellen"):
    def __init__(self, cog: "Suggestions"):
        super().__init__(timeout=300)
        self.cog = cog

        self.name_input = discord.ui.TextInput(
            label="Naam",
            placeholder="Bijv. Abyss",
            min_length=2,
            max_length=32,
        )
        self.colors_input = discord.ui.TextInput(
            label="Gradient",
            placeholder="#E00024 > #240006",
            min_length=15,
            max_length=30,
        )
        self.level = discord.ui.RadioGroup(
            options=[
                discord.RadioGroupOption(
                    label=f"Level {level}",
                    value=str(level),
                )
                for level in (10, 25, 50, 75, 100, 125, 150, 175, 200)
            ]
        )

        self.add_item(self.name_input)
        self.add_item(self.colors_input)
        self.add_item(
            discord.ui.Label(
                text="Vrijspelen op level",
                description="Kies één levelcategorie voor deze gradient.",
                component=self.level,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await self.cog.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        if not await self.cog.check_cooldown(interaction):
            return

        try:
            parts = [
                part.strip()
                for part in self.colors_input.value.split(">")
            ]

            if len(parts) != 2:
                raise ValueError

            color1 = normalize_hex(parts[0])
            color2 = normalize_hex(parts[1])
        except ValueError:
            await self.cog.send_feedback(
                interaction,
                "Gebruik exact twee HEX-kleuren, bijvoorbeeld "
                "`#E00024 > #240006`.",
                kind="error",
            )
            return

        clean_name = " ".join(
            self.name_input.value.split()
        ).strip()

        async with aiosqlite.connect(DB_PATH) as db:
            duplicate = await (
                await db.execute(
                    """
                    SELECT 1
                    FROM suggestions
                    WHERE guild_id = ?
                      AND suggestion_type = 'color'
                      AND LOWER(title) = LOWER(?)
                      AND status = 'active'
                    LIMIT 1
                    """,
                    (interaction.guild.id, clean_name),
                )
            ).fetchone()

        if duplicate:
            await self.cog.send_feedback(
                interaction,
                "Er staat al een open kleursuggestie met deze naam.",
                kind="warning",
            )
            return

        await self.cog.create_suggestion(
            interaction,
            suggestion_type="color",
            title=clean_name,
            level=int(self.level.value),
            color1=color1,
            color2=color2,
        )


# ============================================================
# COMPONENTS V2: MAIN MENU
# ============================================================

class SuggestionMenuButton(discord.ui.Button):
    def __init__(
        self,
        parent_view: "SuggestionMenuView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
            style=style,
            custom_id=f"suggestion_menu:{action}",
        )

        self.parent_view = parent_view
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        cog = self.parent_view.cog

        if self.action == "general":
            await interaction.response.send_modal(
                SimpleSuggestionModal(
                    cog,
                    "general",
                    "Algemene suggestie",
                )
            )
            return

        if self.action == "bot":
            await interaction.response.send_modal(
                SimpleSuggestionModal(
                    cog,
                    "bot",
                    "Bot suggestie",
                )
            )
            return

        if self.action == "event":
            await interaction.response.send_modal(
                SimpleSuggestionModal(
                    cog,
                    "event",
                    "Event suggestie",
                )
            )
            return

        if self.action == "color":
            await interaction.response.send_modal(
                ColorSuggestionModal(cog)
            )
            return

        if interaction.guild is None:
            await cog.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        if self.action == "mine":
            rows = await cog.recent_suggestions(
                interaction.guild.id,
                author_id=interaction.user.id,
                limit=10,
            )

            await interaction.response.edit_message(
                view=SuggestionMineView(
                    cog,
                    self.parent_view.user_id,
                    self.parent_view.admin,
                    rows,
                )
            )
            return

        if self.action == "info":
            await interaction.response.edit_message(
                view=SuggestionInfoView(
                    cog,
                    self.parent_view.user_id,
                    self.parent_view.admin,
                )
            )
            return

        if self.action == "manage":
            if (
                not self.parent_view.admin
                or not isinstance(interaction.user, discord.Member)
                or not has_management_access(interaction.user)
            ):
                await cog.send_feedback(
                    interaction,
                    "Alleen beheer kan suggesties beheren.",
                    kind="error",
                )
                return

            rows = await cog.recent_suggestions(
                interaction.guild.id,
                limit=25,
            )

            await interaction.response.edit_message(
                view=SuggestionAdminView(
                    cog,
                    self.parent_view.user_id,
                    rows,
                )
            )


class SuggestionMenuView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Suggestions",
        user_id: int,
        admin: bool = False,
        *,
        channel_id: int | None = None,
    ):
        super().__init__(timeout=300)

        self.cog = cog
        self.user_id = user_id
        self.admin = admin

        intro = (
            "# Suggesties\n"
            "> └ Kies hieronder wat je wilt voorstellen."
        )

        if channel_id:
            intro += f"\n> └ Nieuwe suggesties verschijnen in <#{channel_id}>."

        sections = (
            "## Algemeen\n"
            "> └ Ideeën en verbeteringen voor de server.\n\n"
            "## Bot\n"
            "> └ Nieuwe functies of wijzigingen voor de LEVENLOOS-bot.\n\n"
            "## Event\n"
            "> └ Stel een activiteit of event voor.\n\n"
            f"## {COLOR_EMOJI} Gradient\n"
            "> └ Stel een nieuwe gradient-kleurrol voor."
        )

        primary_row = discord.ui.ActionRow(
            SuggestionMenuButton(
                self,
                "general",
                "Algemeen",
                emoji=GENERAL_EMOJI,
            ),
            SuggestionMenuButton(
                self,
                "bot",
                "Bot",
                emoji=BOT_EMOJI,
            ),
            SuggestionMenuButton(
                self,
                "event",
                "Event",
                emoji=EVENT_EMOJI,
            ),
            SuggestionMenuButton(
                self,
                "color",
                "Gradient",
                emoji=GRADIENT_EMOJI,
            ),
        )

        secondary_items: list[discord.ui.Item] = [
            SuggestionMenuButton(
                self,
                "mine",
                "Mijn suggesties",
                emoji=LIST_EMOJI,
                style=discord.ButtonStyle.secondary,
            ),
            SuggestionMenuButton(
                self,
                "info",
                "Uitleg",
                emoji=INFO_EMOJI,
                style=discord.ButtonStyle.secondary,
            ),
        ]

        # Alleen admins/owners krijgen deze knop überhaupt in hun menu.
        if admin:
            secondary_items.append(
                SuggestionMenuButton(
                    self,
                    "manage",
                    "Beheer",
                    emoji=EDIT_EMOJI,
                    style=discord.ButtonStyle.secondary,
                )
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(intro),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(sections),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                primary_row,
                discord.ui.ActionRow(*secondary_items),
                discord.ui.TextDisplay(
                    f"-# Cooldown tussen nieuwe suggesties: "
                    f"{SUGGESTION_COOLDOWN_MINUTES} minuten."
                ),
                accent_colour=PURPLE,
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.user_id:
            return True

        await self.cog.send_feedback(
            interaction,
            "Open zelf `/suggestie menu` om een suggestie te maken.",
            kind="error",
        )
        return False


# ============================================================
# COMPONENTS V2: INFO / OWN SUGGESTIONS
# ============================================================

class BackToSuggestionMenuButton(discord.ui.Button):
    def __init__(
        self,
        cog: "Suggestions",
        owner_id: int,
        admin: bool,
    ):
        super().__init__(
            label="Terug",
            emoji=component_emoji(BACK_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id="suggestion_menu:back",
        )
        self.cog = cog
        self.owner_id = owner_id
        self.admin = admin

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return

        channel_id = await self.cog.get_suggestion_channel_id(
            interaction.guild.id
        )

        await interaction.response.edit_message(
            view=SuggestionMenuView(
                self.cog,
                self.owner_id,
                self.admin,
                channel_id=channel_id,
            )
        )


class SuggestionInfoView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Suggestions",
        owner_id: int,
        admin: bool,
    ):
        super().__init__(timeout=300)

        self.cog = cog
        self.owner_id = owner_id
        self.admin = admin

        text = (
            "# Suggesties\n"
            "> └ Open `/suggestie menu` en kies het type voorstel.\n"
            "> └ Je krijgt daarna alleen de invoervelden die daarvoor nodig zijn.\n\n"
            "## Stemmen\n"
            f"> └ Suggesties staan **{VOTING_DAYS} dagen** open.\n"
            "> └ Eén lid kan één stem uitbrengen en die later wijzigen of intrekken.\n\n"
            "## Soorten\n"
            "> └ **Algemeen** — serverideeën en verbeteringen.\n"
            "> └ **Bot** — functies of wijzigingen voor de bot.\n"
            "> └ **Event** — activiteiten en events.\n"
            f"> └ **{COLOR_EMOJI} Gradient** — twee HEX-kleuren met een level-eis."
        )

        if admin:
            text += (
                "\n\n## Beheer\n"
                "> └ Gebruik **Beheer** in het menu of `/suggestie beheer`.\n"
                "> └ Daar kun je accepteren, afwijzen, sluiten, heropenen of verwijderen."
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(text),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    BackToSuggestionMenuButton(
                        cog,
                        owner_id,
                        admin,
                    )
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
        )
        return False


class SuggestionMineView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Suggestions",
        owner_id: int,
        admin: bool,
        rows: list[dict],
    ):
        super().__init__(timeout=300)

        self.cog = cog
        self.owner_id = owner_id
        self.admin = admin

        if rows:
            lines = [
                f"> └ **#{row['id']}** • {status_text(row['status'])} "
                f"• {str(row['title'])[:55]}"
                for row in rows
            ]
            body = "\n".join(lines)
        else:
            body = "> └ Je hebt nog geen recente suggesties."

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "# Mijn suggesties\n"
                    f"{body}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    BackToSuggestionMenuButton(
                        cog,
                        owner_id,
                        admin,
                    )
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
        )
        return False


# ============================================================
# COMPONENTS V2: ADMIN PANEL
# ============================================================

class SuggestionAdminSelect(discord.ui.Select):
    def __init__(
        self,
        parent_view: "SuggestionAdminView",
        rows: list[dict],
    ):
        options: list[discord.SelectOption] = []

        for row in rows[:25]:
            icon, label = type_info(str(row["suggestion_type"]))

            options.append(
                discord.SelectOption(
                    label=f"#{row['id']} • {str(row['title'])[:70]}",
                    value=str(row["id"]),
                    description=(
                        f"{label} • {status_label(str(row['status']))}"
                    )[:100],
                    emoji=component_emoji(icon),
                    default=(
                        parent_view.selected_id is not None
                        and int(row["id"]) == parent_view.selected_id
                    ),
                )
            )

        super().__init__(
            placeholder="Kies een suggestie om te beheren…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="suggestion_admin:select",
        )

        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_id = int(self.values[0])

        suggestion = await self.parent_view.cog.get_suggestion(
            self.parent_view.selected_id
        )

        self.parent_view.render(suggestion)

        await interaction.response.edit_message(
            view=self.parent_view
        )


class SuggestionAdminActionButton(discord.ui.Button):
    def __init__(
        self,
        parent_view: "SuggestionAdminView",
        action: str,
        label: str,
        *,
        emoji: str | None,
        style: discord.ButtonStyle,
        disabled: bool,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
            style=style,
            custom_id=f"suggestion_admin:{action}",
            disabled=disabled,
        )

        self.parent_view = parent_view
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if self.action == "delete":
            if self.parent_view.selected_id is None:
                await self.parent_view.cog.send_feedback(
                    interaction,
                    "Kies eerst een suggestie.",
                    kind="warning",
                )
                return

            suggestion = await self.parent_view.cog.get_suggestion(
                self.parent_view.selected_id
            )

            if suggestion is None:
                await self.parent_view.cog.send_feedback(
                    interaction,
                    "Deze suggestie bestaat niet meer.",
                    kind="error",
                )
                return

            await interaction.response.edit_message(
                view=SuggestionDeleteConfirmView(
                    self.parent_view.cog,
                    self.parent_view.user_id,
                    self.parent_view.selected_id,
                    suggestion,
                )
            )
            return

        await self.parent_view.apply(
            interaction,
            self.action,
        )


class SuggestionAdminBackButton(discord.ui.Button):
    def __init__(
        self,
        cog: "Suggestions",
        owner_id: int,
    ):
        super().__init__(
            label="Terug",
            emoji=component_emoji(BACK_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id="suggestion_admin:back",
        )

        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return

        channel_id = await self.cog.get_suggestion_channel_id(
            interaction.guild.id
        )

        await interaction.response.edit_message(
            view=SuggestionMenuView(
                self.cog,
                self.owner_id,
                True,
                channel_id=channel_id,
            )
        )


class SuggestionAdminRefreshButton(discord.ui.Button):
    def __init__(
        self,
        parent_view: "SuggestionAdminView",
    ):
        super().__init__(
            label="Vernieuwen",
            emoji=component_emoji(REFRESH_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id="suggestion_admin:refresh",
        )

        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return

        rows = await self.parent_view.cog.recent_suggestions(
            interaction.guild.id,
            limit=25,
        )

        self.parent_view.rows = rows

        if self.parent_view.selected_id is not None:
            selected = next(
                (
                    row
                    for row in rows
                    if int(row["id"]) == self.parent_view.selected_id
                ),
                None,
            )
        else:
            selected = None

        self.parent_view.render(
            selected,
            notice="Lijst vernieuwd.",
            notice_kind="success",
        )

        await interaction.response.edit_message(
            view=self.parent_view
        )


class SuggestionAdminView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Suggestions",
        user_id: int,
        rows: list[dict],
        *,
        selected_id: int | None = None,
        notice: str | None = None,
        notice_kind: str = "info",
    ):
        super().__init__(timeout=300)

        self.cog = cog
        self.user_id = user_id
        self.rows = rows
        self.selected_id = selected_id

        selected = next(
            (
                row
                for row in rows
                if selected_id is not None
                and int(row["id"]) == selected_id
            ),
            None,
        )

        self.render(
            selected,
            notice=notice,
            notice_kind=notice_kind,
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id == self.user_id
            and isinstance(interaction.user, discord.Member)
            and has_management_access(interaction.user)
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Alleen beheer kan dit menu gebruiken.",
            kind="error",
        )
        return False

    def render(
        self,
        suggestion,
        *,
        notice: str | None = None,
        notice_kind: str = "info",
    ):
        self.clear_items()

        if suggestion is None:
            selection_text = (
                "## Selectie\n"
                "> └ Kies hierboven een suggestie om de beheeracties te gebruiken."
            )
            status = None
        else:
            icon, label = type_info(
                str(suggestion["suggestion_type"])
            )
            status = str(suggestion["status"])

            selection_text = (
                "## Selectie\n"
                f"> └ **#{suggestion['id']}** • "
                f"{markdown_icon(icon)}{label}\n"
                f"> └ Titel: **{suggestion['title']}**\n"
                f"> └ Status: **{status_text(status)}**\n"
                f"> └ Maker: <@{suggestion['author_id']}>"
            )

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                "# Suggesties beheren\n"
                f"> └ Recente suggesties: **{len(self.rows)}**\n"
                "> └ Selecteer een suggestie en kies daarna een actie."
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            ),
        ]

        if self.rows:
            children.append(
                discord.ui.ActionRow(
                    SuggestionAdminSelect(
                        self,
                        self.rows,
                    )
                )
            )
        else:
            children.append(
                discord.ui.TextDisplay(
                    f"> └ {INFO_EMOJI} Er zijn nog geen suggesties."
                )
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(selection_text),
            ]
        )

        no_selection = suggestion is None

        children.append(
            discord.ui.ActionRow(
                SuggestionAdminActionButton(
                    self,
                    "accepted",
                    "Accepteren",
                    emoji=SUCCESS_EMOJI,
                    style=discord.ButtonStyle.success,
                    disabled=no_selection or status == "accepted",
                ),
                SuggestionAdminActionButton(
                    self,
                    "rejected",
                    "Afwijzen",
                    emoji=ERROR_EMOJI,
                    style=discord.ButtonStyle.danger,
                    disabled=no_selection or status == "rejected",
                ),
                SuggestionAdminActionButton(
                    self,
                    "closed",
                    "Sluiten",
                    emoji=LOCK_EMOJI,
                    style=discord.ButtonStyle.secondary,
                    disabled=no_selection or status == "closed",
                ),
                SuggestionAdminActionButton(
                    self,
                    "active",
                    "Heropenen",
                    emoji=REFRESH_EMOJI,
                    style=discord.ButtonStyle.secondary,
                    disabled=no_selection or status == "active",
                ),
            )
        )

        children.append(
            discord.ui.ActionRow(
                SuggestionAdminActionButton(
                    self,
                    "delete",
                    "Verwijderen",
                    emoji=DELETE_EMOJI,
                    style=discord.ButtonStyle.danger,
                    disabled=no_selection,
                ),
                SuggestionAdminRefreshButton(self),
                SuggestionAdminBackButton(
                    self.cog,
                    self.user_id,
                ),
            )
        )

        if notice:
            _, icon, _ = feedback_style(notice_kind)
            children.append(
                discord.ui.TextDisplay(
                    f"-# {markdown_icon(icon)}{notice}"
                )
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PURPLE,
            )
        )

    async def apply(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if self.selected_id is None:
            await self.cog.send_feedback(
                interaction,
                "Kies eerst een suggestie.",
                kind="warning",
            )
            return

        if interaction.guild is None:
            return

        await interaction.response.defer(ephemeral=True)

        result, success = await self.cog.manage_suggestion(
            interaction.guild,
            self.selected_id,
            action,
        )

        self.rows = await self.cog.recent_suggestions(
            interaction.guild.id,
            limit=25,
        )

        suggestion = await self.cog.get_suggestion(
            self.selected_id
        )

        self.render(
            suggestion,
            notice=result,
            notice_kind="success" if success else "error",
        )

        await interaction.edit_original_response(
            view=self
        )


class ConfirmDeleteButton(discord.ui.Button):
    def __init__(
        self,
        parent_view: "SuggestionDeleteConfirmView",
    ):
        super().__init__(
            label="Definitief verwijderen",
            emoji=component_emoji(DELETE_EMOJI),
            style=discord.ButtonStyle.danger,
            custom_id="suggestion_admin:confirm_delete",
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return

        await interaction.response.defer(ephemeral=True)

        result, success = await self.parent_view.cog.manage_suggestion(
            interaction.guild,
            self.parent_view.suggestion_id,
            "delete",
        )

        rows = await self.parent_view.cog.recent_suggestions(
            interaction.guild.id,
            limit=25,
        )

        await interaction.edit_original_response(
            view=SuggestionAdminView(
                self.parent_view.cog,
                self.parent_view.user_id,
                rows,
                notice=result,
                notice_kind="success" if success else "error",
            )
        )


class CancelDeleteButton(discord.ui.Button):
    def __init__(
        self,
        parent_view: "SuggestionDeleteConfirmView",
    ):
        super().__init__(
            label="Terug",
            emoji=component_emoji(BACK_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id="suggestion_admin:cancel_delete",
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return

        rows = await self.parent_view.cog.recent_suggestions(
            interaction.guild.id,
            limit=25,
        )

        await interaction.response.edit_message(
            view=SuggestionAdminView(
                self.parent_view.cog,
                self.parent_view.user_id,
                rows,
                selected_id=self.parent_view.suggestion_id,
            )
        )


class SuggestionDeleteConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Suggestions",
        user_id: int,
        suggestion_id: int,
        suggestion,
    ):
        super().__init__(timeout=180)

        self.cog = cog
        self.user_id = user_id
        self.suggestion_id = suggestion_id

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Suggestie verwijderen\n"
                    f"> └ Je staat op het punt **#{suggestion_id}** definitief te verwijderen.\n"
                    f"> └ Titel: **{suggestion['title']}**\n\n"
                    f"{ERROR_EMOJI} **Dit verwijdert ook alle opgeslagen stemmen.**"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfirmDeleteButton(self),
                    CancelDeleteButton(self),
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id == self.user_id
            and isinstance(interaction.user, discord.Member)
            and has_management_access(interaction.user)
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Alleen beheer kan deze actie uitvoeren.",
            kind="error",
        )
        return False


# ============================================================
# COG
# ============================================================

class Suggestions(commands.Cog):
    suggestie = app_commands.Group(
        name="suggestie",
        description="Suggesties voor LEVENLOOS.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_lock = asyncio.Lock()

    async def cog_load(self):
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Suggestions vereist discord.py 2.6+ voor Components V2."
            )

        if not hasattr(discord.ui, "RadioGroup"):
            raise RuntimeError(
                "Suggestions vereist discord.py 2.7+ voor het gradientformulier."
            )

        await self.init_db()
        await self.restore_views()

        if not self.expire_suggestions.is_running():
            self.expire_suggestions.start()

        logger.info("Suggestions-module geladen.")

    async def cog_unload(self):
        self.expire_suggestions.cancel()

    # ========================================================
    # FEEDBACK
    # ========================================================

    async def send_feedback(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
    ):
        view = FeedbackView(
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

    # ========================================================
    # DATABASE
    # ========================================================

    async def init_db(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS suggestions_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    author_id INTEGER NOT NULL,
                    suggestion_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    level INTEGER,
                    color1 TEXT,
                    color2 TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS suggestion_votes (
                    suggestion_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    vote INTEGER NOT NULL CHECK(vote IN (-1, 1)),
                    PRIMARY KEY (suggestion_id, user_id),
                    FOREIGN KEY (suggestion_id)
                        REFERENCES suggestions(id)
                        ON DELETE CASCADE
                )
                """
            )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_suggestions_guild_status
                ON suggestions(guild_id, status)
                """
            )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_suggestion_votes_suggestion
                ON suggestion_votes(suggestion_id)
                """
            )

            await db.commit()

    async def get_suggestion_channel_id(
        self,
        guild_id: int,
    ) -> int | None:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """
                SELECT channel_id
                FROM suggestions_config
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()

        return int(row[0]) if row else None

    async def set_suggestion_channel(
        self,
        guild_id: int,
        channel_id: int,
    ):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO suggestions_config (
                    guild_id,
                    channel_id
                )
                VALUES (?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    channel_id = excluded.channel_id
                """,
                (guild_id, channel_id),
            )
            await db.commit()

    async def apply_suggestion_channel(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
    ) -> tuple[str, bool]:
        if not isinstance(channel, discord.TextChannel):
            return "Kies een normaal tekstkanaal.", False

        bot_member = guild.me

        if bot_member is None:
            return "Ik kon mijn eigen botlid niet vinden.", False

        try:
            await channel.set_permissions(
                guild.default_role,
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                add_reactions=False,
                use_application_commands=True,
                reason="LEVENLOOS suggestiekanaal setup",
            )

            await channel.set_permissions(
                bot_member,
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                manage_messages=True,
                use_application_commands=True,
                reason="LEVENLOOS suggestiekanaal setup",
            )
        except discord.Forbidden:
            return (
                "Ik heb niet genoeg rechten om de kanaalpermissies aan te passen.",
                False,
            )
        except discord.HTTPException:
            logger.exception(
                "Discord-fout tijdens instellen suggestiekanaal %s in guild %s.",
                channel.id,
                guild.id,
            )
            return (
                "Discord kon de kanaalpermissies niet aanpassen.",
                False,
            )

        await self.set_suggestion_channel(
            guild.id,
            channel.id,
        )

        return (
            f"{channel.mention} is nu het suggestiekanaal.",
            True,
        )

    async def recent_suggestions(
        self,
        guild_id: int,
        author_id: int | None = None,
        limit: int = 25,
    ) -> list[dict]:
        query = "SELECT * FROM suggestions WHERE guild_id = ?"
        params: list[object] = [guild_id]

        if author_id is not None:
            query += " AND author_id = ?"
            params.append(author_id)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(25, limit)))

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            rows = await (
                await db.execute(
                    query,
                    tuple(params),
                )
            ).fetchall()

        return [dict(row) for row in rows]

    async def get_suggestion(
        self,
        suggestion_id: int,
    ):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM suggestions
                WHERE id = ?
                """,
                (suggestion_id,),
            )

            return await cursor.fetchone()

    async def get_vote_counts(
        self,
        suggestion_id: int,
    ) -> tuple[int, int]:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """
                SELECT
                    SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END)
                FROM suggestion_votes
                WHERE suggestion_id = ?
                """,
                (suggestion_id,),
            )
            row = await cursor.fetchone()

        return int(row[0] or 0), int(row[1] or 0)

    # ========================================================
    # MENU / VALIDATION
    # ========================================================

    async def ensure_suggestion_form_available(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return False

        channel_id = await self.get_suggestion_channel_id(
            interaction.guild.id
        )

        if channel_id is None:
            await self.send_feedback(
                interaction,
                "Er is nog geen suggestiekanaal ingesteld. "
                "Een admin kan `/suggestie setup` gebruiken.",
                kind="warning",
            )
            return False

        channel = interaction.guild.get_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            await self.send_feedback(
                interaction,
                "Het ingestelde suggestiekanaal bestaat niet meer. "
                "Een admin kan `/suggestie setup` opnieuw uitvoeren.",
                kind="error",
            )
            return False

        return True

    async def check_cooldown(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return False

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(minutes=SUGGESTION_COOLDOWN_MINUTES)
        ).isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """
                SELECT created_at
                FROM suggestions
                WHERE guild_id = ?
                  AND author_id = ?
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    interaction.guild.id,
                    interaction.user.id,
                    cutoff,
                ),
            )

            row = await cursor.fetchone()

        if row is None:
            return True

        last_time = parse_datetime(str(row[0]))
        retry_at = last_time + timedelta(
            minutes=SUGGESTION_COOLDOWN_MINUTES
        )

        remaining_seconds = max(
            1,
            int(
                (
                    retry_at
                    - datetime.now(timezone.utc)
                ).total_seconds()
            ),
        )

        minutes = max(
            1,
            (remaining_seconds + 59) // 60,
        )

        await self.send_feedback(
            interaction,
            f"Wacht nog ongeveer **{minutes} minuut/minuten** "
            "voordat je een nieuwe suggestie plaatst.",
            kind="warning",
        )
        return False

    # ========================================================
    # PUBLIC CARD BUILD / PERSISTENCE
    # ========================================================

    def build_suggestion_view(
        self,
        suggestion,
        upvotes: int,
        downvotes: int,
        *,
        disabled: bool | None = None,
    ) -> SuggestionVoteView:
        if disabled is None:
            disabled = str(suggestion["status"]) != "active"

        return SuggestionVoteView(
            self,
            suggestion,
            upvotes,
            downvotes,
            disabled=disabled,
        )

    async def restore_views(self):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            rows = await (
                await db.execute(
                    """
                    SELECT *
                    FROM suggestions
                    WHERE status = 'active'
                      AND message_id IS NOT NULL
                    """
                )
            ).fetchall()

        restored = 0

        for suggestion in rows:
            try:
                upvotes, downvotes = await self.get_vote_counts(
                    int(suggestion["id"])
                )

                self.bot.add_view(
                    self.build_suggestion_view(
                        suggestion,
                        upvotes,
                        downvotes,
                    ),
                    message_id=int(suggestion["message_id"]),
                )

                restored += 1
            except Exception:
                logger.exception(
                    "Persistent view herstellen mislukt voor suggestie %s.",
                    suggestion["id"],
                )

        if restored:
            logger.info(
                "%s actieve suggestie-view(s) hersteld.",
                restored,
            )

    async def update_suggestion_message(
        self,
        suggestion_id: int,
        *,
        disabled: bool | None = None,
    ) -> str:
        suggestion = await self.get_suggestion(suggestion_id)

        if suggestion is None:
            return "missing"

        guild = self.bot.get_guild(
            int(suggestion["guild_id"])
        )

        if guild is None:
            return "missing"

        channel = guild.get_channel(
            int(suggestion["channel_id"])
        )

        if (
            not isinstance(channel, discord.TextChannel)
            or suggestion["message_id"] is None
        ):
            return "missing"

        try:
            message = await channel.fetch_message(
                int(suggestion["message_id"])
            )
        except (discord.NotFound, discord.Forbidden):
            return "missing"
        except discord.HTTPException:
            logger.exception(
                "Suggestiebericht ophalen mislukt voor #%s.",
                suggestion_id,
            )
            return "failed"

        upvotes, downvotes = await self.get_vote_counts(
            suggestion_id
        )

        view = self.build_suggestion_view(
            suggestion,
            upvotes,
            downvotes,
            disabled=disabled,
        )

        try:
            # embed=None/content=None is nodig bij migratie van oude legacy
            # suggestieberichten naar een echte Components V2-message.
            await message.edit(
                content=None,
                embed=None,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.NotFound, discord.Forbidden):
            return "missing"
        except discord.HTTPException:
            logger.exception(
                "Suggestiebericht bijwerken mislukt voor #%s.",
                suggestion_id,
            )
            return "failed"

        return "updated"

    # ========================================================
    # CREATE / MANAGE
    # ========================================================

    async def create_suggestion(
        self,
        interaction: discord.Interaction,
        suggestion_type: str,
        title: str,
        description: str | None = None,
        level: int | None = None,
        color1: str | None = None,
        color2: str | None = None,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        channel_id = await self.get_suggestion_channel_id(
            interaction.guild.id
        )

        target_channel = (
            interaction.guild.get_channel(channel_id)
            if channel_id
            else None
        )

        if not isinstance(
            target_channel,
            discord.TextChannel,
        ):
            await self.send_feedback(
                interaction,
                "Het suggestiekanaal is niet meer geldig. "
                "Laat een admin `/suggestie setup` uitvoeren.",
                kind="error",
            )
            return

        created_at = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """
                INSERT INTO suggestions (
                    guild_id,
                    channel_id,
                    author_id,
                    suggestion_type,
                    title,
                    description,
                    level,
                    color1,
                    color2,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.guild.id,
                    target_channel.id,
                    interaction.user.id,
                    suggestion_type,
                    title,
                    description,
                    level,
                    color1,
                    color2,
                    created_at,
                ),
            )

            suggestion_id = cursor.lastrowid
            await db.commit()

        suggestion = await self.get_suggestion(
            int(suggestion_id)
        )

        if suggestion is None:
            await self.send_feedback(
                interaction,
                "De suggestie kon niet uit de database worden teruggelezen.",
                kind="error",
            )
            return

        view = self.build_suggestion_view(
            suggestion,
            0,
            0,
        )

        file = None

        if suggestion_type == "color":
            try:
                preview_bytes = make_gradient_png(
                    str(color1),
                    str(color2),
                )

                file = discord.File(
                    io.BytesIO(preview_bytes),
                    filename="kleur-preview.png",
                )
            except Exception:
                logger.exception(
                    "Gradientpreview genereren mislukt voor suggestie #%s.",
                    suggestion_id,
                )

        try:
            if file is not None:
                message = await target_channel.send(
                    view=view,
                    file=file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                message = await target_channel.send(
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Suggestie #%s kon niet in kanaal %s worden geplaatst.",
                suggestion_id,
                target_channel.id,
            )

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    DELETE FROM suggestions
                    WHERE id = ?
                    """,
                    (suggestion_id,),
                )
                await db.commit()

            await self.send_feedback(
                interaction,
                "Ik kon de suggestie niet in het ingestelde kanaal plaatsen.",
                kind="error",
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE suggestions
                SET message_id = ?
                WHERE id = ?
                """,
                (
                    message.id,
                    suggestion_id,
                ),
            )
            await db.commit()

        self.bot.add_view(
            view,
            message_id=message.id,
        )

        self.bot.dispatch(
            "suggestion_created",
            interaction.guild,
            interaction.user.id,
            suggestion_id,
        )

        await self.send_feedback(
            interaction,
            f"Je suggestie is geplaatst: {message.jump_url}",
            kind="success",
            title="Suggestie geplaatst",
        )

    async def manage_suggestion(
        self,
        guild: discord.Guild,
        suggestion_id: int,
        action: str,
    ) -> tuple[str, bool]:
        suggestion = await self.get_suggestion(
            suggestion_id
        )

        if (
            suggestion is None
            or int(suggestion["guild_id"]) != guild.id
        ):
            return "Ik kan die suggestie niet vinden.", False

        previous_status = str(suggestion["status"])

        channel = guild.get_channel(
            int(suggestion["channel_id"])
        )

        message = None

        if (
            isinstance(channel, discord.TextChannel)
            and suggestion["message_id"] is not None
        ):
            try:
                message = await channel.fetch_message(
                    int(suggestion["message_id"])
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                message = None

        if action == "delete":
            if message is not None:
                try:
                    await message.delete()
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):
                    logger.warning(
                        "Suggestiebericht #%s kon niet worden verwijderd.",
                        suggestion_id,
                    )

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    DELETE FROM suggestion_votes
                    WHERE suggestion_id = ?
                    """,
                    (suggestion_id,),
                )
                await db.execute(
                    """
                    DELETE FROM suggestions
                    WHERE id = ?
                    """,
                    (suggestion_id,),
                )
                await db.commit()

            return (
                f"Suggestie **#{suggestion_id}** is definitief verwijderd.",
                True,
            )

        if action not in {
            "accepted",
            "rejected",
            "closed",
            "active",
        }:
            return "Onbekende beheeractie.", False

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE suggestions
                SET status = ?
                WHERE id = ?
                """,
                (
                    action,
                    suggestion_id,
                ),
            )
            await db.commit()

        if (
            action == "accepted"
            and previous_status != "accepted"
        ):
            self.bot.dispatch(
                "suggestion_accepted",
                guild,
                int(suggestion["author_id"]),
                suggestion_id,
            )

        updated = await self.get_suggestion(
            suggestion_id
        )

        if updated is not None and message is not None:
            upvotes, downvotes = await self.get_vote_counts(
                suggestion_id
            )

            view = self.build_suggestion_view(
                updated,
                upvotes,
                downvotes,
                disabled=(action != "active"),
            )

            try:
                await message.edit(
                    content=None,
                    embed=None,
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                logger.exception(
                    "Publieke suggestie #%s bijwerken na beheeractie mislukt.",
                    suggestion_id,
                )

        action_name = {
            "accepted": "geaccepteerd",
            "rejected": "afgewezen",
            "closed": "gesloten",
            "active": "heropend",
        }[action]

        return (
            f"Suggestie **#{suggestion_id}** is {action_name}.",
            True,
        )

    # ========================================================
    # VOTING / CANCELLING
    # ========================================================

    async def handle_vote(
        self,
        interaction: discord.Interaction,
        suggestion_id: int,
        vote: int,
    ):
        if interaction.user.bot:
            await self.send_feedback(
                interaction,
                "Bots kunnen niet stemmen.",
                kind="error",
            )
            return

        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Deze stemactie hoort bij een server.",
                kind="error",
            )
            return

        suggestion = await self.get_suggestion(
            suggestion_id
        )

        if (
            suggestion is None
            or int(suggestion["guild_id"]) != interaction.guild.id
            or str(suggestion["status"]) != "active"
        ):
            await self.send_feedback(
                interaction,
                "Deze suggestie is niet meer open voor stemmen.",
                kind="warning",
            )
            return

        await interaction.response.defer()

        vote_counts_for_xp = False

        async with self.db_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    """
                    SELECT vote
                    FROM suggestion_votes
                    WHERE suggestion_id = ?
                      AND user_id = ?
                    """,
                    (
                        suggestion_id,
                        interaction.user.id,
                    ),
                )

                existing = await cursor.fetchone()

                if existing and int(existing[0]) == vote:
                    await db.execute(
                        """
                        DELETE FROM suggestion_votes
                        WHERE suggestion_id = ?
                          AND user_id = ?
                        """,
                        (
                            suggestion_id,
                            interaction.user.id,
                        ),
                    )
                else:
                    vote_counts_for_xp = True

                    await db.execute(
                        """
                        INSERT INTO suggestion_votes (
                            suggestion_id,
                            user_id,
                            vote
                        )
                        VALUES (?, ?, ?)
                        ON CONFLICT(suggestion_id, user_id)
                        DO UPDATE SET
                            vote = excluded.vote
                        """,
                        (
                            suggestion_id,
                            interaction.user.id,
                            vote,
                        ),
                    )

                await db.commit()

            upvotes, downvotes = await self.get_vote_counts(
                suggestion_id
            )

        suggestion = await self.get_suggestion(
            suggestion_id
        )

        if suggestion is None:
            return

        view = self.build_suggestion_view(
            suggestion,
            upvotes,
            downvotes,
        )

        if interaction.message is not None:
            try:
                await interaction.message.edit(
                    content=None,
                    embed=None,
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                logger.exception(
                    "Stemweergave bijwerken mislukt voor suggestie #%s.",
                    suggestion_id,
                )

        if vote_counts_for_xp:
            self.bot.dispatch(
                "suggestion_vote",
                interaction.guild,
                interaction.user.id,
                suggestion_id,
            )

    async def handle_cancel(
        self,
        interaction: discord.Interaction,
        suggestion_id: int,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Deze actie hoort bij een server.",
                kind="error",
            )
            return

        suggestion = await self.get_suggestion(
            suggestion_id
        )

        if (
            suggestion is None
            or int(suggestion["guild_id"]) != interaction.guild.id
        ):
            await self.send_feedback(
                interaction,
                "Deze suggestie bestaat niet meer.",
                kind="error",
            )
            return

        if interaction.user.id != int(suggestion["author_id"]):
            await self.send_feedback(
                interaction,
                "Alleen de maker kan deze suggestie annuleren.",
                kind="error",
            )
            return

        if str(suggestion["status"]) != "active":
            await self.send_feedback(
                interaction,
                "Deze suggestie kan niet meer geannuleerd worden.",
                kind="warning",
            )
            return

        await interaction.response.defer()

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE suggestions
                SET status = 'cancelled'
                WHERE id = ?
                  AND status = 'active'
                """,
                (suggestion_id,),
            )
            await db.commit()

        result = await self.update_suggestion_message(
            suggestion_id,
            disabled=True,
        )

        if result == "failed":
            logger.warning(
                "Geannuleerde suggestie #%s kon visueel niet worden bijgewerkt.",
                suggestion_id,
            )

    # ========================================================
    # EXPIRATION
    # ========================================================

    @tasks.loop(minutes=5)
    async def expire_suggestions(self):
        try:
            cutoff = (
                datetime.now(timezone.utc)
                - timedelta(days=VOTING_DAYS)
            ).isoformat()

            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    """
                    SELECT id
                    FROM suggestions
                    WHERE status = 'active'
                      AND created_at <= ?
                    """,
                    (cutoff,),
                )

                rows = await cursor.fetchall()

                if not rows:
                    return

                ids = [
                    int(row[0])
                    for row in rows
                ]

                await db.executemany(
                    """
                    UPDATE suggestions
                    SET status = 'pending_review'
                    WHERE id = ?
                      AND status = 'active'
                    """,
                    [
                        (suggestion_id,)
                        for suggestion_id in ids
                    ],
                )

                await db.commit()

            for suggestion_id in ids:
                await self.update_suggestion_message(
                    suggestion_id,
                    disabled=True,
                )

        except Exception:
            logger.exception(
                "Automatisch verlopen van suggesties is mislukt."
            )

    @expire_suggestions.before_loop
    async def before_expire_suggestions(self):
        await self.bot.wait_until_ready()

    # ========================================================
    # SUGGESTION CHANNEL CLEANUP
    # ========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ):
        if (
            message.author.bot
            or message.guild is None
        ):
            return

        channel_id = await self.get_suggestion_channel_id(
            message.guild.id
        )

        if (
            channel_id is None
            or message.channel.id != channel_id
        ):
            return

        try:
            await message.delete()
        except (
            discord.Forbidden,
            discord.NotFound,
        ):
            pass
        except discord.HTTPException:
            logger.exception(
                "Bericht verwijderen uit suggestiekanaal %s mislukt.",
                message.channel.id,
            )

    # ========================================================
    # SLASH COMMANDS
    # ========================================================

    @suggestie.command(
        name="menu",
        description="Open het suggestiemenu.",
    )
    async def menu_command(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.ensure_suggestion_form_available(
            interaction
        ):
            return

        assert interaction.guild is not None

        channel_id = await self.get_suggestion_channel_id(
            interaction.guild.id
        )

        admin = (
            isinstance(interaction.user, discord.Member)
            and has_management_access(interaction.user)
        )

        await interaction.response.send_message(
            view=SuggestionMenuView(
                self,
                interaction.user.id,
                admin,
                channel_id=channel_id,
            ),
            ephemeral=True,
        )

    @suggestie.command(
        name="setup",
        description="Stel het suggestiekanaal in.",
    )
    async def setup_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not has_management_access(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Alleen een admin of owner kan dit instellen.",
                kind="error",
            )
            return

        current = await self.get_suggestion_channel_id(
            interaction.guild.id
        )

        await interaction.response.send_message(
            view=SuggestionSetupView(
                self,
                interaction.user.id,
                current_channel_id=current,
            ),
            ephemeral=True,
        )

    @suggestie.command(
        name="kleur",
        description="Open direct het formulier voor een gradient-suggestie.",
    )
    async def color_command(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.ensure_suggestion_form_available(
            interaction
        ):
            return

        await interaction.response.send_modal(
            ColorSuggestionModal(self)
        )

    @suggestie.command(
        name="algemeen",
        description="Open direct het formulier voor een algemene suggestie.",
    )
    async def general_command(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.ensure_suggestion_form_available(
            interaction
        ):
            return

        await interaction.response.send_modal(
            SimpleSuggestionModal(
                self,
                "general",
                "Algemene suggestie",
            )
        )

    @suggestie.command(
        name="bot",
        description="Open direct het formulier voor een bot-suggestie.",
    )
    async def bot_command(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.ensure_suggestion_form_available(
            interaction
        ):
            return

        await interaction.response.send_modal(
            SimpleSuggestionModal(
                self,
                "bot",
                "Bot suggestie",
            )
        )

    @suggestie.command(
        name="event",
        description="Open direct het formulier voor een event-suggestie.",
    )
    async def event_command(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.ensure_suggestion_form_available(
            interaction
        ):
            return

        await interaction.response.send_modal(
            SimpleSuggestionModal(
                self,
                "event",
                "Event suggestie",
            )
        )

    @suggestie.command(
        name="beheer",
        description="Open het suggestie-beheerpanel.",
    )
    async def manage_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not has_management_access(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Alleen een admin of owner kan suggesties beheren.",
                kind="error",
            )
            return

        rows = await self.recent_suggestions(
            interaction.guild.id,
            limit=25,
        )

        await interaction.response.send_message(
            view=SuggestionAdminView(
                self,
                interaction.user.id,
                rows,
            ),
            ephemeral=True,
        )

    @suggestie.command(
        name="refresh",
        description="Werk alle bestaande suggestieberichten opnieuw bij.",
    )
    async def refresh_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not has_management_access(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Alleen een admin of owner kan suggesties vernieuwen.",
                kind="error",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=VOTING_DAYS)
        ).isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """
                SELECT id
                FROM suggestions
                WHERE guild_id = ?
                ORDER BY id ASC
                """,
                (interaction.guild.id,),
            )

            rows = await cursor.fetchall()

            await db.execute(
                """
                UPDATE suggestions
                SET status = 'pending_review'
                WHERE guild_id = ?
                  AND status = 'active'
                  AND created_at <= ?
                """,
                (
                    interaction.guild.id,
                    cutoff,
                ),
            )

            await db.commit()

        updated = 0
        missing = 0
        failed = 0

        for (suggestion_id,) in rows:
            result = await self.update_suggestion_message(
                int(suggestion_id)
            )

            if result == "updated":
                updated += 1
            elif result == "missing":
                missing += 1
            else:
                failed += 1

            # Handmatige bulk-refresh blijft bewust iets gespreid om de
            # Discord API niet onnodig hard te raken.
            await asyncio.sleep(0.25)

        summary = (
            f"Bijgewerkt: **{updated}**\n"
            f"Niet gevonden: **{missing}**\n"
            f"Mislukt: **{failed}**"
        )

        await self.send_feedback(
            interaction,
            summary.replace("\n", "\n> └ "),
            kind="success" if failed == 0 else "warning",
            title="Suggesties vernieuwd",
        )

    @suggestie.command(
        name="info",
        description="Bekijk informatie over het suggestiesysteem.",
    )
    async def info_command(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        admin = (
            isinstance(interaction.user, discord.Member)
            and has_management_access(interaction.user)
        )

        await interaction.response.send_message(
            view=SuggestionInfoView(
                self,
                interaction.user.id,
                admin,
            ),
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(
        Suggestions(bot)
    )
