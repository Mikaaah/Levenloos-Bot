from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONFIG
# ============================================================

DATABASE_PATH = "levenloos.db"
BRAND_COLOR = discord.Colour.from_str("#6C27DA")

DEFAULT_WELCOME_CHANNEL_ID = 940328182471602256
DEFAULT_INFO_CHANNEL_ID = 940328225568079923
DEFAULT_REACT_ROLES_CHANNEL_ID = 940376085865037884

DEFAULT_JOIN_ROLE_IDS = (
    1080845388384309268,
    1080845392150798377,
    1080845390313697330,
    940331028344619110,
)

WELCOME_BADGE_URL = "https://i.imgur.com/YXFAOyd.png"

DEFAULT_WELCOME_TITLE = "WELKOM BIJ LEVENLOOS"
DEFAULT_WELCOME_MESSAGE = (
    "Welkom {member}! Je bent onze **{member_count}e speler**."
)
DEFAULT_INFO_MESSAGE = (
    "Lees {info_channel} voor de serverinfo en regels."
)
DEFAULT_ROLES_MESSAGE = (
    "Ga naar {roles_channel} om je games, genres en rollen te kiezen."
)
DEFAULT_LEAVE_MESSAGE = (
    "👋 **{member_name}** heeft LEVENLOOS verlaten."
)

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
NONE_EMOJI = "<:none:1547724038955208794>"
ROLES_EMOJI = "<:roll:1546435118455988332>"
WAVE_EMOJI = "<:wave:1547885668401938473>"


# ============================================================
# WAVE MESSAGES
# ============================================================

WAVE_MESSAGES = [
    "👋 {user} zwaait naar {member}!",
    "👋 {user} heet {member} welkom!",
    "👋 {user} komt even hallo zeggen tegen {member}.",
    "👋 {user} zwaait vrolijk naar {member}!",
    "👋 {user} verwelkomt {member} bij LEVENLOOS.",
    "👋 {user} kwam even langs om {member} welkom te heten.",
    "👋 {user} zegt hoi tegen {member}!",
    "👋 {user} heeft {member} gespot.",
    "👋 {user} sluit zich aan bij het welkomstcomité.",
    "👋 {user} is er ook even bij.",
    "👋 {user} heet onze nieuwe speler {member} welkom!",
    "👋 {user} komt even buurten bij {member}!",
    "👋 {user} geeft {member} een zwaai.",
    "👋 {user} verwelkomt {member} op de server.",
    "👋 {user} zegt even welkom tegen {member}.",
    "👋 {user} zag een nieuwe naam verschijnen: {member}.",
    "🧟 {user} checkt voor de zekerheid of {member} gebeten is.",
    "⛏️ {user} laat alvast wat diamonds over voor {member}.",
    "🦖 {user} maakt alvast plek voor de dino van {member}.",
    "⚡ {user} vraagt zich af welke starter {member} kiest.",
    "🚗 {user} stuurt de bal alvast richting {member}.",
    "🏭 {user} zet {member} alvast aan het werk in de fabriek.",
    "🌊 {user} hoopt dat {member} genoeg zuurstof heeft meegenomen.",
    "🔦 {user} heeft voor de zekerheid een zaklamp meegenomen voor {member}.",
    "👀 {user} vindt {member} een beetje sus.",
    "🪂 {user} laat {member} voor deze keer Jumpmaster zijn.",
    "🚀 {user} meldt {member} aan voor de volgende extractie.",
    "🛡️ {user} heeft nog wel een plekje in de squad voor {member}.",
    "🌾 {user} houdt een stukje farmland vrij voor {member}.",
    "🎣 {user} vist {member} uit de rivier.",
    "⚽ {user} zet {member} alvast in de basis.",
    "🔫 {user} bewaart wat ammo voor {member}.",
    "🧱 {user} zet alvast een crafting table neer voor {member}.",
    "🗺️ {user} zet {member} alvast op de map.",
    "🎮 {user} heeft alvast een plek in de party voor {member}.",
    "🧰 {user} bewaart wat loot voor {member}.",
    "🎲 {user} rolt een NAT 20 om {member} welkom te heten.",
    "🎲 {user} rolt initiative voor {member}.",
    "🐉 {user} houdt alvast een stoel aan tafel vrij voor {member}.",
    "🧙 {user} geeft {member} voor deze keer advantage.",
    "📜 {user} zet {member} alvast op de character sheet.",
    "🗡️ {user} schuift {member} een extra set dobbelstenen toe.",
    "🃏 {user} schudt de kaarten alvast voor {member}.",
    "♟️ {user} maakt alvast ruimte op het bord voor {member}.",
    "🎲 {user} hoopt dat de eerste roll van {member} beter is dan een NAT 1.",
    "🏰 {user} reserveert alvast een plek in de party voor {member}.",
    "📖 {user} slaat een nieuwe pagina open voor {member}.",
    "🧩 {user} legt alvast een extra speelstuk klaar voor {member}.",
]


# ============================================================
# DATA
# ============================================================

@dataclass(slots=True)
class WelcomeConfig:
    guild_id: int
    welcome_channel_id: int
    info_channel_id: int
    react_roles_channel_id: int
    welcome_title: str
    welcome_message: str
    info_message: str
    roles_message: str
    leave_message: str


# ============================================================
# GENERIC HELPERS
# ============================================================

def owner_only(
    interaction: discord.Interaction,
) -> bool:
    return (
        interaction.guild is not None
        and interaction.guild.owner_id
        == interaction.user.id
    )


def component_emoji(
    value: str | None,
) -> discord.PartialEmoji | None:
    if not value:
        return None

    try:
        emoji = discord.PartialEmoji.from_str(
            value
        )
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
            discord.Colour.from_rgb(
                87,
                242,
                135,
            ),
        )

    if kind == "error":
        return (
            "Fout",
            ERROR_EMOJI,
            discord.Colour.from_rgb(
                237,
                66,
                69,
            ),
        )

    if kind == "warning":
        return (
            "Let op",
            WARNING_EMOJI,
            discord.Colour.from_rgb(
                254,
                231,
                92,
            ),
        )

    return (
        "Informatie",
        INFO_EMOJI,
        BRAND_COLOR,
    )


# ============================================================
# COMPONENTS V2 FEEDBACK
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
        super().__init__(
            timeout=180
        )

        default_title, icon, accent = (
            feedback_style(
                kind
            )
        )

        lines = [
            f"> └ {line}"
            for line in message.splitlines()
            if line.strip()
        ]

        children: list[
            discord.ui.Item
        ] = [
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
                        spacing=(
                            discord.SeparatorSpacing.small
                        ),
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
# PUBLIC WELCOME VIEW
# ============================================================

class WaveButton(discord.ui.Button):
    def __init__(
        self,
        cog: "Welcome",
        member_id: int,
        *,
        disabled: bool = False,
    ):
        super().__init__(
            label="Zwaai!",
            emoji=component_emoji(
                WAVE_EMOJI
            ),
            style=discord.ButtonStyle.secondary,
            custom_id=f"welcome_wave:{member_id}",
            disabled=disabled,
        )

        self.cog = cog
        self.member_id = member_id

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.cog.handle_wave(
            interaction,
            self.member_id,
        )


class WelcomeBackButton(discord.ui.Button):
    def __init__(
        self,
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
    ):
        super().__init__(
            label="Terug",
            emoji=component_emoji(
                BACK_EMOJI
            ),
            style=discord.ButtonStyle.secondary,
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit previewmenu is niet van jou.",
                kind="error",
            )
            return

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await WelcomeConfigView.create(
                self.cog,
                self.owner_id,
                self.guild_id,
            ),
        )


class WelcomeView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Welcome",
        member_id: int,
        *,
        title: str = "Welkom",
        welcome_text: str = "",
        info_text: str = "",
        roles_text: str = "",
        avatar_url: str | None = None,
        guild_name: str = "LEVENLOOS",
        preview: bool = False,
        owner_id: int | None = None,
        guild_id: int | None = None,
        restore_only: bool = False,
    ):
        super().__init__(
            timeout=None
            if not preview
            else 300
        )

        self.cog = cog
        self.member_id = member_id

        if restore_only:
            self.add_item(
                discord.ui.Container(
                    discord.ui.ActionRow(
                        WaveButton(
                            cog,
                            member_id,
                        )
                    ),
                    accent_colour=BRAND_COLOR,
                )
            )
            return

        # De avatar blijft rechts naast de titel staan, terwijl de welkomstzin
        # eronder de volledige kaartbreedte krijgt. Zo blijft de zin netter op één regel.
        if avatar_url:
            intro: discord.ui.Item = discord.ui.Section(
                discord.ui.TextDisplay(
                    f"# {title}"
                ),
                accessory=discord.ui.Thumbnail(
                    avatar_url,
                    description="Profielfoto van het nieuwe lid",
                ),
            )
        else:
            intro = discord.ui.TextDisplay(
                f"# {title}"
            )

        welcome_body = welcome_text
        if welcome_body.casefold().startswith("welkom "):
            welcome_body = welcome_body[7:].lstrip()

        welcome_line = discord.ui.TextDisplay(
            f"## {WAVE_EMOJI} Welkom\n"
            f"> └ {welcome_body}"
        )

        action_items: list[
            discord.ui.Button
        ] = [
            WaveButton(
                cog,
                member_id,
                disabled=preview,
            )
        ]

        if (
            preview
            and owner_id is not None
            and guild_id is not None
        ):
            action_items.append(
                WelcomeBackButton(
                    cog,
                    owner_id,
                    guild_id,
                )
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        WELCOME_BADGE_URL,
                        description=(
                            "LEVENLOOS welkomstbanner"
                        ),
                    )
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                intro,
                welcome_line,
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"## {INFO_EMOJI} Info & Regels\n"
                    f"> └ {info_text}"
                ),
                discord.ui.TextDisplay(
                    f"## {ROLES_EMOJI} Rollen kiezen\n"
                    f"> └ {roles_text}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    *action_items
                ),
                discord.ui.TextDisplay(
                    f"-# {guild_name} • Welkom"
                ),
                accent_colour=BRAND_COLOR,
            )
        )


# ============================================================
# CONFIG MODALS
# ============================================================

class WelcomeTextModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        config: WelcomeConfig,
    ):
        super().__init__(
            title="Welkomstteksten aanpassen",
            timeout=300,
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.welcome_title = discord.ui.TextInput(
            label="Titel",
            max_length=80,
            required=True,
            default=config.welcome_title,
        )

        self.welcome_message = discord.ui.TextInput(
            label="Welkomstbericht",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True,
            default=config.welcome_message,
        )

        self.info_message = discord.ui.TextInput(
            label="Info & regels tekst",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True,
            default=config.info_message,
        )

        self.roles_message = discord.ui.TextInput(
            label="React Roles tekst",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True,
            default=config.roles_message,
        )

        self.add_item(
            self.welcome_title
        )
        self.add_item(
            self.welcome_message
        )
        self.add_item(
            self.info_message
        )
        self.add_item(
            self.roles_message
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit configuratiemenu is niet van jou.",
                kind="error",
            )
            return

        await self.cog.update_config(
            self.guild_id,
            welcome_title=str(
                self.welcome_title
            ),
            welcome_message=str(
                self.welcome_message
            ),
            info_message=str(
                self.info_message
            ),
            roles_message=str(
                self.roles_message
            ),
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await WelcomeConfigView.create(
                self.cog,
                self.owner_id,
                self.guild_id,
                notice="Welkomstteksten opgeslagen.",
            ),
        )


class LeaveTextModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        current: str,
    ):
        super().__init__(
            title="Vertrekbericht aanpassen",
            timeout=300,
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.leave_message = discord.ui.TextInput(
            label="Vertrekbericht",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True,
            default=current,
        )

        self.add_item(
            self.leave_message
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit configuratiemenu is niet van jou.",
                kind="error",
            )
            return

        await self.cog.update_config(
            self.guild_id,
            leave_message=str(
                self.leave_message
            ),
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await WelcomeConfigView.create(
                self.cog,
                self.owner_id,
                self.guild_id,
                notice="Vertrekbericht opgeslagen.",
            ),
        )


# ============================================================
# CONFIG NAVIGATION BUTTONS
# ============================================================

class ConfigActionButton(discord.ui.Button):
    def __init__(
        self,
        owner_view,
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
        await self.owner_view.handle(
            interaction,
            self.action,
        )


# ============================================================
# CONFIG HOME
# ============================================================

class WelcomeConfigView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(
            timeout=600
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        children: list[
            discord.ui.Item
        ] = [
            discord.ui.TextDisplay(
                body
            )
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
                    ConfigActionButton(
                        self,
                        "texts",
                        "Teksten",
                        emoji=EDIT_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ConfigActionButton(
                        self,
                        "channels",
                        "Kanalen",
                        emoji=INFO_EMOJI,
                    ),
                    ConfigActionButton(
                        self,
                        "roles",
                        "Join rollen",
                        emoji=ROLES_EMOJI,
                    ),
                    ConfigActionButton(
                        self,
                        "leave",
                        "Vertrektekst",
                        emoji=EDIT_EMOJI,
                    ),
                ),
                discord.ui.ActionRow(
                    ConfigActionButton(
                        self,
                        "preview",
                        "Preview",
                        emoji=INFO_EMOJI,
                    ),
                    ConfigActionButton(
                        self,
                        "reset",
                        "Reset standaard",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# Alleen de server owner kan deze instellingen aanpassen."
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
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        *,
        notice: str | None = None,
    ):
        config = await cog.get_config(
            guild_id
        )

        roles = await cog.get_join_roles(
            guild_id
        )

        body = (
            "# Welkom Config\n"
            "> └ Beheer hier het volledige welkomstsysteem.\n\n"
            f"## {INFO_EMOJI} Kanalen\n"
            f"> └ Welkom: <#{config.welcome_channel_id}>\n"
            f"> └ Info & Regels: <#{config.info_channel_id}>\n"
            f"> └ React Roles: <#{config.react_roles_channel_id}>\n\n"
            f"## {ROLES_EMOJI} Join rollen\n"
            f"> └ Automatisch ingesteld: **{len(roles)} rollen**\n\n"
            "## Placeholders\n"
            "> └ `{member}` • `{member_name}` • `{member_count}`\n"
            "> └ `{info_channel}` • `{roles_channel}`"
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
        if (
            interaction.user.id
            == self.owner_id
            and owner_only(
                interaction
            )
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit configpanel is niet van jou.",
            kind="error",
        )
        return False

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action == "texts":
            config = await self.cog.get_config(
                self.guild_id
            )

            await interaction.response.send_modal(
                WelcomeTextModal(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    config,
                )
            )
            return

        if action == "channels":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await ChannelConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )
            return

        if action == "roles":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await JoinRolesView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )
            return

        if action == "leave":
            config = await self.cog.get_config(
                self.guild_id
            )

            await interaction.response.send_modal(
                LeaveTextModal(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    config.leave_message,
                )
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

            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await self.cog.build_welcome_view(
                    interaction.guild,
                    interaction.user,
                    preview=True,
                    owner_id=self.owner_id,
                ),
            )
            return

        if action == "reset":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=ResetConfirmView(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )


# ============================================================
# CHANNEL CONFIG
# ============================================================

class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        owner_view: "ChannelConfigView",
        kind: str,
    ):
        labels = {
            "welcome": "Kies het welkomstkanaal...",
            "info": "Kies Info & Regels...",
            "roles": "Kies React Roles...",
        }

        super().__init__(
            placeholder=labels[
                kind
            ],
            channel_types=[
                discord.ChannelType.text
            ],
            min_values=1,
            max_values=1,
        )

        self.owner_view = owner_view
        self.kind = kind

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != (
            self.owner_view.owner_id
        ):
            await self.owner_view.cog.send_feedback(
                interaction,
                "Dit menu is niet van jou.",
                kind="error",
            )
            return

        channel = self.values[0]

        column = {
            "welcome": "welcome_channel_id",
            "info": "info_channel_id",
            "roles": "react_roles_channel_id",
        }[
            self.kind
        ]

        await self.owner_view.cog.update_config(
            self.owner_view.guild_id,
            **{
                column: channel.id
            },
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await ChannelConfigView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice=(
                    f"Kanaal aangepast naar {channel.mention}."
                ),
            ),
        )


class ChannelConfigView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(
            timeout=600
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        children: list[
            discord.ui.Item
        ] = [
            discord.ui.TextDisplay(
                body
            )
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
                discord.ui.TextDisplay(
                    "## Welkomstkanaal\n"
                    "> └ Hier worden nieuwe leden verwelkomd."
                ),
                discord.ui.ActionRow(
                    WelcomeChannelSelect(
                        self,
                        "welcome",
                    )
                ),
                discord.ui.TextDisplay(
                    "## Info & Regels\n"
                    "> └ Dit kanaal wordt in de welkomstkaart genoemd."
                ),
                discord.ui.ActionRow(
                    WelcomeChannelSelect(
                        self,
                        "info",
                    )
                ),
                discord.ui.TextDisplay(
                    "## React Roles\n"
                    "> └ Hier kunnen leden hun games, genres en rollen kiezen."
                ),
                discord.ui.ActionRow(
                    WelcomeChannelSelect(
                        self,
                        "roles",
                    )
                ),
                discord.ui.ActionRow(
                    ConfigActionButton(
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
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        *,
        notice: str | None = None,
    ):
        config = await cog.get_config(
            guild_id
        )

        body = (
            "# Welkomstkanalen\n"
            "> └ Kies de drie kanalen die door het welkomstsysteem worden gebruikt.\n\n"
            f"## {INFO_EMOJI} Huidig\n"
            f"> └ Welkom: <#{config.welcome_channel_id}>\n"
            f"> └ Info & Regels: <#{config.info_channel_id}>\n"
            f"> └ React Roles: <#{config.react_roles_channel_id}>"
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
        if (
            interaction.user.id
            == self.owner_id
            and owner_only(
                interaction
            )
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit menu is niet van jou.",
            kind="error",
        )
        return False

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await WelcomeConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )


# ============================================================
# JOIN ROLE CONFIG
# ============================================================

class JoinRoleSelect(discord.ui.RoleSelect):
    def __init__(
        self,
        owner_view: "JoinRolesView",
    ):
        super().__init__(
            placeholder=(
                "Kies een join-rol om toe te voegen/verwijderen..."
            ),
            min_values=1,
            max_values=1,
        )

        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        role = self.values[0]

        if (
            role.is_default()
            or role.managed
        ):
            await self.owner_view.cog.send_feedback(
                interaction,
                "Deze rol kan niet als automatische join-rol worden gebruikt.",
                kind="error",
            )
            return

        guild = interaction.guild

        if guild is None:
            await self.owner_view.cog.send_feedback(
                interaction,
                "Server niet gevonden.",
                kind="error",
            )
            return

        bot_member = guild.me

        if (
            bot_member is None
            or not bot_member.guild_permissions.manage_roles
            or role >= bot_member.top_role
        ):
            await self.owner_view.cog.send_feedback(
                interaction,
                (
                    "Mijn botrol kan deze rol niet uitdelen. "
                    "Controleer **Rollen beheren** en de rolpositie."
                ),
                kind="error",
            )
            return

        added = await self.owner_view.cog.toggle_join_role(
            self.owner_view.guild_id,
            role.id,
        )

        state = (
            "toegevoegd aan"
            if added
            else "verwijderd uit"
        )

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await JoinRolesView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                notice=(
                    f"{role.mention} is {state} de automatische join-rollen."
                ),
            ),
        )


class JoinRolesView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(
            timeout=600
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        children: list[
            discord.ui.Item
        ] = [
            discord.ui.TextDisplay(
                body
            )
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
                    JoinRoleSelect(
                        self
                    )
                ),
                discord.ui.ActionRow(
                    ConfigActionButton(
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
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
        *,
        notice: str | None = None,
    ):
        role_ids = await cog.get_join_roles(
            guild_id
        )

        guild = cog.bot.get_guild(
            guild_id
        )

        lines = [
            f"# {ROLES_EMOJI} Automatische join-rollen",
            "> └ Nieuwe leden krijgen deze rollen direct bij binnenkomst.",
            "",
            "## Ingesteld",
        ]

        if role_ids:
            for role_id in role_ids[:20]:
                role = (
                    guild.get_role(
                        role_id
                    )
                    if guild
                    else None
                )

                lines.append(
                    f"> └ {role.mention if role else f'Onbekende rol (`{role_id}`)'}"
                )
        else:
            lines.append(
                "> └ Geen join-rollen ingesteld."
            )

        lines.extend(
            [
                "",
                "-# Selecteer een rol opnieuw om hem uit de lijst te verwijderen.",
            ]
        )

        return cls(
            cog,
            owner_id,
            guild_id,
            "\n".join(
                lines
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
            and owner_only(
                interaction
            )
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit menu is niet van jou.",
            kind="error",
        )
        return False

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await WelcomeConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                ),
            )


# ============================================================
# RESET CONFIRMATION
# ============================================================

class ResetConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Welcome",
        owner_id: int,
        guild_id: int,
    ):
        super().__init__(
            timeout=60
        )

        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Welkomstconfig resetten\n"
                    "> └ Alle aangepaste welkomstteksten, kanalen en join-rollen "
                    "worden teruggezet naar de standaardwaarden.\n"
                    f"> └ {ERROR_EMOJI} Dit overschrijft de huidige configuratie."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigActionButton(
                        self,
                        "confirm",
                        "Reset standaard",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                    ConfigActionButton(
                        self,
                        "back",
                        "Terug",
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
        if (
            interaction.user.id
            == self.owner_id
            and owner_only(
                interaction
            )
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit menu is niet van jou.",
            kind="error",
        )
        return False

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await WelcomeConfigView.create(
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
                view=await WelcomeConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    notice=(
                        "Welkomstconfig teruggezet naar de standaardwaarden."
                    ),
                ),
            )


# ============================================================
# COG
# ============================================================

class Welcome(commands.Cog):
    welkom = app_commands.Group(
        name="welkom",
        description="Welkomstsysteem van LEVENLOOS.",
    )

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # LOAD
    # ========================================================

    async def cog_load(
        self,
    ):
        if not hasattr(
            discord.ui,
            "LayoutView",
        ):
            raise RuntimeError(
                "Welcome vereist discord.py 2.6+ voor Components V2."
            )

        await self.init_db()
        await self.restore_views()

        logger.info(
            "Welcome-module geladen."
        )

    # ========================================================
    # DATABASE
    # ========================================================

    async def init_db(
        self,
    ):
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                "PRAGMA journal_mode=WAL"
            )
            await db.execute(
                "PRAGMA busy_timeout=5000"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_waves (
                    guild_id INTEGER NOT NULL,
                    welcomed_member_id INTEGER NOT NULL,
                    waving_user_id INTEGER NOT NULL,
                    PRIMARY KEY (
                        guild_id,
                        welcomed_member_id,
                        waving_user_id
                    )
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_config (
                    guild_id INTEGER PRIMARY KEY,
                    welcome_channel_id INTEGER NOT NULL,
                    info_channel_id INTEGER NOT NULL,
                    react_roles_channel_id INTEGER NOT NULL,
                    welcome_title TEXT NOT NULL,
                    welcome_message TEXT NOT NULL,
                    info_message TEXT NOT NULL,
                    roles_message TEXT NOT NULL,
                    leave_message TEXT NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_join_roles (
                    guild_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY (
                        guild_id,
                        role_id
                    )
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    message_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE (
                        guild_id,
                        member_id
                    )
                )
                """
            )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_welcome_messages_guild
                ON welcome_messages(guild_id)
                """
            )

            await db.commit()

    async def ensure_config(
        self,
        guild_id: int,
    ):
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO welcome_config (
                    guild_id,
                    welcome_channel_id,
                    info_channel_id,
                    react_roles_channel_id,
                    welcome_title,
                    welcome_message,
                    info_message,
                    roles_message,
                    leave_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    DEFAULT_WELCOME_CHANNEL_ID,
                    DEFAULT_INFO_CHANNEL_ID,
                    DEFAULT_REACT_ROLES_CHANNEL_ID,
                    DEFAULT_WELCOME_TITLE,
                    DEFAULT_WELCOME_MESSAGE,
                    DEFAULT_INFO_MESSAGE,
                    DEFAULT_ROLES_MESSAGE,
                    DEFAULT_LEAVE_MESSAGE,
                ),
            )

            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM welcome_join_roles
                WHERE guild_id = ?
                """,
                (
                    guild_id,
                ),
            )

            count = int(
                (await cursor.fetchone())[0]
            )

            if count == 0:
                await db.executemany(
                    """
                    INSERT OR IGNORE INTO welcome_join_roles (
                        guild_id,
                        role_id
                    )
                    VALUES (?, ?)
                    """,
                    [
                        (
                            guild_id,
                            role_id,
                        )
                        for role_id
                        in DEFAULT_JOIN_ROLE_IDS
                    ],
                )

            await db.commit()

    async def get_config(
        self,
        guild_id: int,
    ) -> WelcomeConfig:
        await self.ensure_config(
            guild_id
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT
                    guild_id,
                    welcome_channel_id,
                    info_channel_id,
                    react_roles_channel_id,
                    welcome_title,
                    welcome_message,
                    info_message,
                    roles_message,
                    leave_message
                FROM welcome_config
                WHERE guild_id = ?
                """,
                (
                    guild_id,
                ),
            )

            row = await cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Welkomstconfig kon niet worden geladen."
            )

        return WelcomeConfig(
            *row
        )

    async def update_config(
        self,
        guild_id: int,
        **changes,
    ):
        allowed = {
            "welcome_channel_id",
            "info_channel_id",
            "react_roles_channel_id",
            "welcome_title",
            "welcome_message",
            "info_message",
            "roles_message",
            "leave_message",
        }

        clean = {
            key: value
            for key, value
            in changes.items()
            if key in allowed
        }

        if not clean:
            return

        await self.ensure_config(
            guild_id
        )

        assignments = ", ".join(
            f"{key} = ?"
            for key in clean
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                f"""
                UPDATE welcome_config
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
    ):
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                """
                DELETE FROM welcome_config
                WHERE guild_id = ?
                """,
                (
                    guild_id,
                ),
            )

            await db.execute(
                """
                DELETE FROM welcome_join_roles
                WHERE guild_id = ?
                """,
                (
                    guild_id,
                ),
            )

            await db.commit()

        await self.ensure_config(
            guild_id
        )

    async def get_join_roles(
        self,
        guild_id: int,
    ) -> list[int]:
        await self.ensure_config(
            guild_id
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT role_id
                FROM welcome_join_roles
                WHERE guild_id = ?
                ORDER BY role_id
                """,
                (
                    guild_id,
                ),
            )

            return [
                int(
                    row[0]
                )
                for row
                in await cursor.fetchall()
            ]

    async def toggle_join_role(
        self,
        guild_id: int,
        role_id: int,
    ) -> bool:
        await self.ensure_config(
            guild_id
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT 1
                FROM welcome_join_roles
                WHERE guild_id = ?
                  AND role_id = ?
                """,
                (
                    guild_id,
                    role_id,
                ),
            )

            if await cursor.fetchone():
                await db.execute(
                    """
                    DELETE FROM welcome_join_roles
                    WHERE guild_id = ?
                      AND role_id = ?
                    """,
                    (
                        guild_id,
                        role_id,
                    ),
                )

                added = False
            else:
                await db.execute(
                    """
                    INSERT INTO welcome_join_roles (
                        guild_id,
                        role_id
                    )
                    VALUES (?, ?)
                    """,
                    (
                        guild_id,
                        role_id,
                    ),
                )

                added = True

            await db.commit()

        return added

    async def record_welcome_message(
        self,
        guild_id: int,
        channel_id: int,
        member_id: int,
        message_id: int,
    ):
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                """
                INSERT INTO welcome_messages (
                    message_id,
                    guild_id,
                    channel_id,
                    member_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, member_id)
                DO UPDATE SET
                    message_id = excluded.message_id,
                    channel_id = excluded.channel_id,
                    created_at = excluded.created_at
                """,
                (
                    message_id,
                    guild_id,
                    channel_id,
                    member_id,
                    int(
                        time.time()
                    ),
                ),
            )

            await db.commit()

    async def restore_views(
        self,
    ):
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            rows = await (
                await db.execute(
                    """
                    SELECT
                        message_id,
                        member_id
                    FROM welcome_messages
                    """
                )
            ).fetchall()

        restored = 0

        for message_id, member_id in rows:
            try:
                self.bot.add_view(
                    WelcomeView(
                        self,
                        int(
                            member_id
                        ),
                        restore_only=True,
                    ),
                    message_id=int(
                        message_id
                    ),
                )

                restored += 1
            except Exception:
                logger.exception(
                    "Welcome view herstellen mislukt voor message %s.",
                    message_id,
                )

        logger.info(
            "%s Welcome view(s) hersteld.",
            restored,
        )

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
        footer: str | None = None,
    ):
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

    # ========================================================
    # WELCOME RENDERING
    # ========================================================

    @staticmethod
    def format_template(
        template: str,
        *,
        member: discord.abc.User,
        member_count: int,
        info_channel_id: int,
        roles_channel_id: int,
    ) -> str:
        replacements = {
            "{member}": member.mention,
            "{member_name}": (
                member.display_name
            ),
            "{member_count}": str(
                member_count
            ),
            "{info_channel}": (
                f"<#{info_channel_id}>"
            ),
            "{roles_channel}": (
                f"<#{roles_channel_id}>"
            ),
        }

        for key, value in (
            replacements.items()
        ):
            template = template.replace(
                key,
                value,
            )

        return template

    async def build_welcome_view(
        self,
        guild: discord.Guild,
        member: discord.abc.User,
        *,
        preview: bool = False,
        owner_id: int | None = None,
    ) -> WelcomeView:
        config = await self.get_config(
            guild.id
        )

        member_count = (
            guild.member_count
            or 0
        )

        welcome_text = self.format_template(
            config.welcome_message,
            member=member,
            member_count=member_count,
            info_channel_id=(
                config.info_channel_id
            ),
            roles_channel_id=(
                config.react_roles_channel_id
            ),
        )

        info_text = self.format_template(
            config.info_message,
            member=member,
            member_count=member_count,
            info_channel_id=(
                config.info_channel_id
            ),
            roles_channel_id=(
                config.react_roles_channel_id
            ),
        )

        roles_text = self.format_template(
            config.roles_message,
            member=member,
            member_count=member_count,
            info_channel_id=(
                config.info_channel_id
            ),
            roles_channel_id=(
                config.react_roles_channel_id
            ),
        )

        return WelcomeView(
            self,
            member.id,
            title=config.welcome_title,
            welcome_text=welcome_text,
            info_text=info_text,
            roles_text=roles_text,
            avatar_url=str(
                member.display_avatar.url
            ),
            guild_name=guild.name,
            preview=preview,
            owner_id=owner_id,
            guild_id=guild.id,
        )

    # ========================================================
    # WAVE
    # ========================================================

    async def handle_wave(
        self,
        interaction: discord.Interaction,
        member_id: int,
    ):
        guild = interaction.guild

        if (
            guild is None
            or interaction.channel is None
        ):
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in de server.",
                kind="error",
            )
            return

        try:
            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                await db.execute(
                    """
                    INSERT INTO welcome_waves (
                        guild_id,
                        welcomed_member_id,
                        waving_user_id
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        guild.id,
                        member_id,
                        interaction.user.id,
                    ),
                )

                await db.commit()

        except aiosqlite.IntegrityError:
            await self.send_feedback(
                interaction,
                (
                    f"Je hebt <@{member_id}> "
                    "al welkom geheten."
                ),
                kind="info",
                title="Al gezwaaid",
            )
            return
        except aiosqlite.Error:
            logger.exception(
                "Welcome wave opslaan mislukt."
            )

            await self.send_feedback(
                interaction,
                "Je zwaai kon niet worden opgeslagen.",
                kind="error",
            )
            return

        member = guild.get_member(
            member_id
        )

        member_text = (
            member.mention
            if member
            else f"<@{member_id}>"
        )

        wave_message = random.choice(
            WAVE_MESSAGES
        ).format(
            user=interaction.user.mention,
            member=member_text,
        )

        await interaction.response.defer()

        try:
            await interaction.channel.send(
                wave_message,
                allowed_mentions=(
                    discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    )
                ),
            )
        except discord.HTTPException:
            logger.exception(
                "Welcome wave bericht versturen mislukt."
            )

        levels = self.bot.get_cog(
            "Levels"
        )

        if (
            levels is not None
            and hasattr(
                levels,
                "award_source",
            )
        ):
            try:
                await levels.award_source(
                    guild,
                    interaction.user.id,
                    "wave",
                    (
                        f"welcome_wave:{member_id}:"
                        f"{interaction.user.id}"
                    ),
                    member_id,
                )
            except Exception:
                logger.exception(
                    "Welcome wave XP toekennen mislukt."
                )

    # ========================================================
    # /WELKOM CONFIG
    # ========================================================

    @welkom.command(
        name="config",
        description="Open het welkomstconfiguratiepaneel.",
    )
    async def config_command(
        self,
        interaction: discord.Interaction,
    ):
        if not owner_only(
            interaction
        ):
            await self.send_feedback(
                interaction,
                (
                    "Alleen de server owner "
                    "kan dit configureren."
                ),
                kind="error",
                title="Geen toegang",
            )
            return

        await interaction.response.send_message(
            view=await WelcomeConfigView.create(
                self,
                interaction.user.id,
                interaction.guild.id,
            ),
            ephemeral=True,
        )

    # ========================================================
    # /WELKOM TEST
    # ========================================================

    @welkom.command(
        name="test",
        description="Stuur een test van het welkomstbericht.",
    )
    async def test_command(
        self,
        interaction: discord.Interaction,
    ):
        if not owner_only(
            interaction
        ):
            await self.send_feedback(
                interaction,
                (
                    "Alleen de server owner "
                    "kan dit testen."
                ),
                kind="error",
                title="Geen toegang",
            )
            return

        guild = interaction.guild

        if guild is None:
            return

        config = await self.get_config(
            guild.id
        )

        channel = guild.get_channel(
            config.welcome_channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            await self.send_feedback(
                interaction,
                (
                    "Het welkomstkanaal "
                    "kon niet worden gevonden."
                ),
                kind="error",
            )
            return

        try:
            await channel.send(
                view=await self.build_welcome_view(
                    guild,
                    interaction.user,
                    preview=True,
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )
        except discord.Forbidden:
            await self.send_feedback(
                interaction,
                (
                    "Ik kan geen bericht plaatsen "
                    "in het welkomstkanaal."
                ),
                kind="error",
            )
            return
        except discord.HTTPException:
            logger.exception(
                "Welkomsttest versturen mislukt."
            )

            await self.send_feedback(
                interaction,
                (
                    "Discord kon de welkomsttest "
                    "niet versturen."
                ),
                kind="error",
            )
            return

        await self.send_feedback(
            interaction,
            (
                f"Welkomsttest verstuurd in "
                f"{channel.mention}."
            ),
            kind="success",
            title="Test verstuurd",
        )

    # ========================================================
    # MEMBER JOIN / LEAVE
    # ========================================================

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member,
    ):
        if member.bot:
            return

        config = await self.get_config(
            member.guild.id
        )

        role_ids = await self.get_join_roles(
            member.guild.id
        )

        bot_member = member.guild.me

        roles = []

        for role_id in role_ids:
            role = member.guild.get_role(
                role_id
            )

            if (
                role is None
                or role.managed
                or role.is_default()
            ):
                continue

            if (
                bot_member is None
                or role >= bot_member.top_role
            ):
                logger.warning(
                    "Join-role %s staat boven de botrol en wordt overgeslagen.",
                    role_id,
                )
                continue

            roles.append(
                role
            )

        if (
            roles
            and bot_member is not None
            and bot_member.guild_permissions.manage_roles
        ):
            try:
                await member.add_roles(
                    *roles,
                    reason=(
                        "Automatische LEVENLOOS welkomstrollen"
                    ),
                )
            except discord.Forbidden:
                logger.warning(
                    (
                        "Kan join-rollen niet geven aan "
                        "%s (%s): onvoldoende rechten/rolpositie."
                    ),
                    member,
                    member.id,
                )
            except discord.HTTPException:
                logger.exception(
                    (
                        "Discord-fout bij join-rollen "
                        "voor member %s."
                    ),
                    member.id,
                )

        channel = member.guild.get_channel(
            config.welcome_channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            logger.warning(
                (
                    "Welkomstkanaal %s niet gevonden "
                    "in guild %s."
                ),
                config.welcome_channel_id,
                member.guild.id,
            )
            return

        try:
            view = await self.build_welcome_view(
                member.guild,
                member,
            )

            message = await channel.send(
                view=view,
                allowed_mentions=(
                    discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    )
                ),
            )

            await self.record_welcome_message(
                member.guild.id,
                channel.id,
                member.id,
                message.id,
            )

            self.bot.add_view(
                WelcomeView(
                    self,
                    member.id,
                    restore_only=True,
                ),
                message_id=message.id,
            )

        except discord.Forbidden:
            logger.warning(
                (
                    "Geen toestemming om welkom te sturen "
                    "in channel %s."
                ),
                channel.id,
            )
        except discord.HTTPException:
            logger.exception(
                "Welkomstbericht versturen mislukt."
            )

    @commands.Cog.listener()
    async def on_member_remove(
        self,
        member: discord.Member,
    ):
        if member.bot:
            return

        config = await self.get_config(
            member.guild.id
        )

        channel = member.guild.get_channel(
            config.welcome_channel_id
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        text = self.format_template(
            config.leave_message,
            member=member,
            member_count=(
                member.guild.member_count
                or 0
            ),
            info_channel_id=(
                config.info_channel_id
            ),
            roles_channel_id=(
                config.react_roles_channel_id
            ),
        )

        try:
            await channel.send(
                text,
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )
        except discord.HTTPException:
            logger.exception(
                "Vertrekbericht versturen mislukt."
            )

    # ========================================================
    # /ROLEALL
    # ========================================================

    @app_commands.command(
        name="roleall",
        description="Geef één rol aan alle serverleden.",
    )
    @app_commands.describe(
        rolnaam=(
            "De rol die je aan alle leden wilt geven."
        ),
    )
    async def roleall_command(
        self,
        interaction: discord.Interaction,
        rolnaam: discord.Role,
    ):
        if not owner_only(
            interaction
        ):
            await self.send_feedback(
                interaction,
                (
                    "Alleen de server owner "
                    "kan `/roleall` gebruiken."
                ),
                kind="error",
                title="Geen toegang",
            )
            return

        guild = interaction.guild

        if guild is None:
            return

        if rolnaam.is_default():
            await self.send_feedback(
                interaction,
                "@everyone kan niet worden uitgedeeld.",
                kind="error",
            )
            return

        if rolnaam.managed:
            await self.send_feedback(
                interaction,
                (
                    "Deze rol wordt door Discord "
                    "of een integratie beheerd."
                ),
                kind="error",
            )
            return

        bot_member = guild.me

        if (
            bot_member is None
            or not bot_member.guild_permissions.manage_roles
            or rolnaam >= bot_member.top_role
        ):
            await self.send_feedback(
                interaction,
                (
                    "Mijn botrol kan deze rol niet uitdelen. "
                    "Controleer **Rollen beheren** en de rolpositie."
                ),
                kind="error",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        added = 0
        already_had = 0
        failed = 0

        for member in guild.members:
            if rolnaam in member.roles:
                already_had += 1
                continue

            try:
                await member.add_roles(
                    rolnaam,
                    reason=(
                        f"/roleall door server owner "
                        f"{interaction.user}"
                    ),
                )

                added += 1

            except (
                discord.Forbidden,
                discord.HTTPException,
            ):
                failed += 1

            # Een kleine yield voorkomt dat een grote server deze loop
            # volledig in één event-loop burst uitvoert.
            await asyncio.sleep(
                0
            )

        await self.send_feedback(
            interaction,
            (
                f"Rol: {rolnaam.mention}\n"
                f"Toegevoegd: **{added}**\n"
                f"Hadden de rol al: **{already_had}**\n"
                f"Mislukt: **{failed}**"
            ),
            kind=(
                "warning"
                if failed
                else "success"
            ),
            title="/roleall voltooid",
        )


# ============================================================
# EXTENSION SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Welcome(bot)
    )
