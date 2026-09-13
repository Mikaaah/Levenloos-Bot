from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = Path("voice.db")
PANEL_COLOR = discord.Colour.from_rgb(108, 39, 218)
DEFAULT_TEMPLATE = "{name} • VC"

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
EDIT_EMOJI = "<:edit:1547724058894934116>"
DELETE_EMOJI = "<:delete:1547724056768286750>"
REFRESH_EMOJI = "<:refresh:1547724055426244618>"
BACK_EMOJI = "<:back:1547724054038052966>"
LOCK_EMOJI = "<:lock:1547724040888786966>"
INFO_EMOJI = "<:info:1547724036107149413>"
VOICE_EMOJI = "<:voice:1547737205429243924>"
USER_EMOJI = "<:user:1547737210986692679>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"

logger = logging.getLogger(__name__)


def management_access(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id or member.guild_permissions.administrator:
        return True
    return any(r.name.lower() in {"admin", "owner"} for r in member.roles)


def ui_emoji(value: str | None):
    if not value:
        return None
    if value.startswith("<"):
        try:
            return discord.PartialEmoji.from_str(value)
        except Exception:
            logger.warning("Kon custom emoji niet parsen: %s", value)
            return None
    return value


def feedback_style(kind: str) -> tuple[str, str, discord.Colour]:
    if kind == "success":
        return "Gelukt", SUCCESS_EMOJI, discord.Colour.from_rgb(87, 242, 135)
    if kind == "error":
        return "Fout", ERROR_EMOJI, discord.Colour.from_rgb(237, 66, 69)
    if kind == "warning":
        return "Let op", WARNING_EMOJI, discord.Colour.from_rgb(254, 231, 92)
    return "Informatie", INFO_EMOJI, PANEL_COLOR


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
        default_title, icon, accent = feedback_style(kind)
        lines = [
            f"> └ {line}"
            for line in str(message).splitlines()
            if line.strip()
        ] or ["> └ —"]

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
                    discord.ui.TextDisplay(f"-# {footer}"),
                ]
            )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=accent,
            )
        )


@dataclass(slots=True)
class VoiceConfig:
    lobby_channel_id: int
    category_id: int
    default_limit: int = 0
    name_template: str = DEFAULT_TEMPLATE
    bitrate_kbps: int = 64
    default_locked: bool = False
    auto_delete: bool = True
    delete_delay: int = 0


class RenameVoiceModal(discord.ui.Modal):
    """Alleen vrije tekst blijft een modal: Discord heeft geen inline tekstveld in Components V2."""

    def __init__(
        self,
        cog: "Voice",
        channel: discord.VoiceChannel,
        panel_message_id: int | None,
    ):
        super().__init__(title="Voice naam wijzigen", timeout=180)
        self.cog = cog
        self.channel_id = channel.id
        self.panel_message_id = panel_message_id

        self.channel_name = discord.ui.TextInput(
            label="Kanaalnaam",
            default=channel.name,
            placeholder="Bijv. Mika's lobby",
            min_length=1,
            max_length=100,
        )
        self.add_item(self.channel_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = self.cog.get_temp_channel(interaction, self.channel_id)
        if channel is None:
            await self.cog.send_feedback(
                interaction,
                "Dit tijdelijke voicekanaal bestaat niet meer.",
                kind="error",
            )
            return

        if not await self.cog.can_control(interaction.user, channel):
            await self.cog.send_feedback(
                interaction,
                "Alleen de eigenaar of beheer kan dit kanaal aanpassen.",
                kind="error",
                title="Geen toegang",
            )
            return

        name = str(self.channel_name).strip()
        if not name:
            await self.cog.send_feedback(
                interaction,
                "Geef het kanaal een naam.",
                kind="error",
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await channel.edit(
                name=name,
                reason=f"Temp VC naam gewijzigd door {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception(
                "Temp VC %s naam wijzigen mislukt",
                channel.id,
                exc_info=exc,
            )
            await interaction.followup.send(
                view=FeedbackView(
                    f"De kanaalnaam kon niet worden aangepast: `{type(exc).__name__}`",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        await self.cog.refresh_control_panel(
            channel,
            message_id=self.panel_message_id,
        )
        await interaction.followup.send(
            view=FeedbackView(
                f"Naam gewijzigd naar **{name}**.",
                kind="success",
            ),
            ephemeral=True,
        )


class VoiceLimitModal(discord.ui.Modal):
    """Kleine invoer voor een vrije limiet van 0 t/m 99."""

    def __init__(
        self,
        cog: "Voice",
        channel: discord.VoiceChannel,
        panel_message_id: int | None,
    ):
        super().__init__(title="Voice limiet wijzigen", timeout=180)
        self.cog = cog
        self.channel_id = channel.id
        self.panel_message_id = panel_message_id

        self.user_limit = discord.ui.TextInput(
            label="User limit",
            default=str(channel.user_limit or 0),
            placeholder="0 = onbeperkt, maximaal 99",
            min_length=1,
            max_length=2,
        )
        self.add_item(self.user_limit)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = self.cog.get_temp_channel(interaction, self.channel_id)
        if channel is None:
            await self.cog.send_feedback(
                interaction,
                "Dit tijdelijke voicekanaal bestaat niet meer.",
                kind="error",
            )
            return

        if not await self.cog.can_control(interaction.user, channel):
            await self.cog.send_feedback(
                interaction,
                "Alleen de eigenaar of beheer kan dit kanaal aanpassen.",
                kind="error",
                title="Geen toegang",
            )
            return

        try:
            limit = int(str(self.user_limit).strip())
            if not 0 <= limit <= 99:
                raise ValueError
        except ValueError:
            await self.cog.send_feedback(
                interaction,
                "User limit moet een getal van **0 t/m 99** zijn.",
                kind="error",
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await channel.edit(
                user_limit=limit,
                reason=f"Temp VC limiet gewijzigd door {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception(
                "Temp VC %s limiet wijzigen mislukt",
                channel.id,
                exc_info=exc,
            )
            await interaction.followup.send(
                view=FeedbackView(
                    f"De limiet kon niet worden aangepast: `{type(exc).__name__}`",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        await self.cog.refresh_control_panel(
            channel,
            message_id=self.panel_message_id,
        )
        await interaction.followup.send(
            view=FeedbackView(
                (
                    "Limiet gewijzigd naar **onbeperkt**."
                    if limit == 0
                    else f"Limiet gewijzigd naar **{limit}**."
                ),
                kind="success",
            ),
            ephemeral=True,
        )


class VoicePanelButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "TempVoiceControlPanel",
        action: str,
        label: str,
        *,
        emoji: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        custom_id: str,
    ):
        super().__init__(
            label=label,
            emoji=ui_emoji(emoji),
            style=style,
            custom_id=custom_id,
        )
        self.owner_view = owner_view
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle(interaction, self.action)


class VoiceAccessSelect(discord.ui.UserSelect):
    def __init__(self, owner_view: "TempVoiceControlPanel"):
        super().__init__(
            placeholder="Geef gebruiker(s) toegang tot deze voice…",
            min_values=1,
            max_values=10,
            custom_id="levenloos:voicepanel:access",
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle_access(interaction, list(self.values))


class VoiceTransferSelect(discord.ui.UserSelect):
    def __init__(self, owner_view: "TempVoiceControlPanel"):
        super().__init__(
            placeholder="Draag eigendom over aan iemand in de voice…",
            min_values=1,
            max_values=1,
            custom_id="levenloos:voicepanel:transfer",
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle_transfer(interaction, list(self.values))


class VoicePrivacySelect(discord.ui.Select):
    def __init__(self, owner_view: "TempVoiceControlPanel", current_mode: str):
        labels = {
            "open": "Open",
            "locked": "Gesloten",
            "private": "Privé",
        }
        super().__init__(
            placeholder=f"Privacy: {labels.get(current_mode, 'Open')}",
            min_values=1,
            max_values=1,
            custom_id="levenloos:voicepanel:privacy",
            options=[
                discord.SelectOption(
                    label="Open",
                    value="open",
                    description="Zichtbaar en vrij te joinen.",
                    default=current_mode == "open",
                ),
                discord.SelectOption(
                    label="Gesloten",
                    value="locked",
                    description="Zichtbaar, alleen toegelaten leden kunnen joinen.",
                    default=current_mode == "locked",
                ),
                discord.SelectOption(
                    label="Privé",
                    value="private",
                    description="Onzichtbaar voor leden zonder expliciete toegang.",
                    default=current_mode == "private",
                ),
            ],
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle_privacy(interaction, self.values[0])


class VoiceKickSelect(discord.ui.UserSelect):
    def __init__(self, owner_view: "TempVoiceControlPanel"):
        super().__init__(
            placeholder="Verwijder iemand die nu in deze voice zit…",
            min_values=1,
            max_values=1,
            custom_id="levenloos:voicepanel:kick",
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle_kick(interaction, list(self.values))


class VoiceBlockSelect(discord.ui.UserSelect):
    def __init__(self, owner_view: "TempVoiceControlPanel"):
        super().__init__(
            placeholder="Blokkeer iemand voor deze voice…",
            min_values=1,
            max_values=1,
            custom_id="levenloos:voicepanel:block",
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle_block(interaction, list(self.values))


class VoiceDeleteConfirmButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "VoiceDeleteConfirmView",
        action: str,
        label: str,
        *,
        emoji: str,
        style: discord.ButtonStyle,
    ):
        super().__init__(
            label=label,
            emoji=ui_emoji(emoji),
            style=style,
        )
        self.owner_view = owner_view
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle(interaction, self.action)


class VoiceDeleteConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Voice",
        channel_id: int,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel_id = channel_id

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Voice verwijderen\n"
                    "> └ Weet je zeker dat dit tijdelijke voicekanaal weg mag?\n\n"
                    "-# De kanaalchat en het beheerpanel verdwijnen automatisch mee."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    VoiceDeleteConfirmButton(
                        self,
                        "confirm",
                        "Ja, verwijderen",
                        emoji=DELETE_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                    VoiceDeleteConfirmButton(
                        self,
                        "cancel",
                        "Annuleren",
                        emoji=BACK_EMOJI,
                        style=discord.ButtonStyle.secondary,
                    ),
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        channel = self.cog.get_temp_channel(
            interaction,
            self.channel_id,
        )

        if action == "cancel":
            await interaction.response.edit_message(
                view=FeedbackView(
                    "Verwijderen geannuleerd.",
                    kind="info",
                )
            )
            return

        if channel is None:
            await interaction.response.edit_message(
                view=FeedbackView(
                    "Dit tijdelijke voicekanaal bestaat al niet meer.",
                    kind="info",
                )
            )
            return

        if not await self.cog.can_control(interaction.user, channel):
            await self.cog.send_feedback(
                interaction,
                "Alleen de eigenaar of beheer kan dit kanaal verwijderen.",
                kind="error",
                title="Geen toegang",
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await channel.delete(
                reason=f"Temp VC verwijderd door {interaction.user}"
            )
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception(
                "Temp VC %s kon niet worden verwijderd",
                self.channel_id,
                exc_info=exc,
            )
            await interaction.followup.send(
                view=FeedbackView(
                    f"Het kanaal kon niet worden verwijderd: `{type(exc).__name__}`",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        await self.cog.forget_channel(self.channel_id)
        await interaction.followup.send(
            view=FeedbackView(
                "Tijdelijk voicekanaal verwijderd.",
                kind="success",
            ),
            ephemeral=True,
        )


class TempVoiceControlPanel(discord.ui.LayoutView):
    """Persistent Components V2 beheerpanel in de chat van iedere tijdelijke voice."""

    def __init__(
        self,
        cog: "Voice",
        channel: discord.VoiceChannel | None,
        *,
        persistent: bool = True,
        notice: str | None = None,
    ):
        super().__init__(timeout=None if persistent else 600)
        self.cog = cog
        self.channel_id = channel.id if channel is not None else None

        if channel is not None:
            owner_id = cog.cached_owner_id(channel.id)
            owner = f"<@{owner_id}>" if owner_id else "Onbekend"
            privacy_mode = cog.privacy_mode(channel)
            privacy_label = {
                "open": "Open",
                "locked": "Gesloten",
                "private": "Privé",
            }[privacy_mode]
            limit = "∞" if channel.user_limit == 0 else str(channel.user_limit)

            text = (
                f"# {VOICE_EMOJI} Voice beheer\n"
                "> └ Beheer dit tijdelijke voicekanaal rechtstreeks vanuit de kanaalchat.\n\n"
                f"## {USER_EMOJI} Eigenaar\n"
                f"> └ {owner}\n\n"
                f"## {SETTINGS_EMOJI} Instellingen\n"
                f"> └ Naam: **{channel.name}**\n"
                f"> └ Limiet: **{limit}**\n"
                f"> └ Privacy: **{privacy_label}**"
            )
        else:
            privacy_mode = "open"
            text = (
                f"# {VOICE_EMOJI} Voice beheer\n"
                "> └ Beheer dit tijdelijke voicekanaal rechtstreeks vanuit de kanaalchat."
            )

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(text),
        ]

        if notice:
            children.append(
                discord.ui.TextDisplay(
                    f"> └ {INFO_EMOJI} {notice}"
                )
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    VoicePanelButton(
                        self,
                        "rename",
                        "Naam",
                        emoji=EDIT_EMOJI,
                        style=discord.ButtonStyle.primary,
                        custom_id="levenloos:voicepanel:rename",
                    ),
                    VoicePanelButton(
                        self,
                        "limit",
                        "Limiet",
                        emoji=USER_EMOJI,
                        style=discord.ButtonStyle.secondary,
                        custom_id="levenloos:voicepanel:limit",
                    ),
                    VoicePanelButton(
                        self,
                        "claim",
                        "Claimen",
                        emoji=USER_EMOJI,
                        style=discord.ButtonStyle.secondary,
                        custom_id="levenloos:voicepanel:claim",
                    ),
                    VoicePanelButton(
                        self,
                        "refresh",
                        "Vernieuwen",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.secondary,
                        custom_id="levenloos:voicepanel:refresh",
                    ),
                    VoicePanelButton(
                        self,
                        "delete",
                        "Verwijderen",
                        emoji=DELETE_EMOJI,
                        style=discord.ButtonStyle.danger,
                        custom_id="levenloos:voicepanel:delete",
                    ),
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"## {LOCK_EMOJI} Privacy\n"
                    "> └ **Open:** zichtbaar en iedereen kan joinen.\n"
                    "> └ **Gesloten:** zichtbaar, alleen toegelaten leden kunnen joinen.\n"
                    "> └ **Privé:** onzichtbaar voor leden zonder toegang."
                ),
                discord.ui.ActionRow(
                    VoicePrivacySelect(self, privacy_mode)
                ),
                discord.ui.TextDisplay(
                    f"## {USER_EMOJI} Toegang geven\n"
                    "> └ Geef maximaal 10 gebruikers expliciete toegang. "
                    "Dit heft voor die gebruiker ook een eerdere blokkade op."
                ),
                discord.ui.ActionRow(
                    VoiceAccessSelect(self)
                ),
                discord.ui.TextDisplay(
                    f"## {USER_EMOJI} Leden beheren\n"
                    "> └ **Verwijderen:** haalt iemand nu uit de voice; diegene kan later opnieuw joinen.\n"
                    "> └ **Blokkeren:** haalt iemand eruit en voorkomt opnieuw joinen in deze tijdelijke voice."
                ),
                discord.ui.ActionRow(
                    VoiceKickSelect(self)
                ),
                discord.ui.ActionRow(
                    VoiceBlockSelect(self)
                ),
                discord.ui.TextDisplay(
                    f"## {USER_EMOJI} Eigenaar overdragen\n"
                    "> └ Kies iemand die op dit moment in het voicekanaal zit."
                ),
                discord.ui.ActionRow(
                    VoiceTransferSelect(self)
                ),
                discord.ui.TextDisplay(
                    "-# Alleen de eigenaar of beheer kan instellingen aanpassen. "
                    "Als de eigenaar vertrekt, kan iemand in de voice het kanaal claimen."
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PANEL_COLOR,
            )
        )

    def _message_id(
        self,
        interaction: discord.Interaction,
    ) -> int | None:
        if interaction.message is not None:
            return interaction.message.id
        return None

    async def _channel(
        self,
        interaction: discord.Interaction,
    ) -> discord.VoiceChannel | None:
        channel_id = self.channel_id or interaction.channel_id
        channel = self.cog.get_temp_channel(
            interaction,
            channel_id,
        )
        if channel is None:
            await self.cog.send_feedback(
                interaction,
                "Dit tijdelijke voicekanaal bestaat niet meer.",
                kind="error",
            )
        return channel

    async def _require_control(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
    ) -> bool:
        if await self.cog.can_control(interaction.user, channel):
            return True

        await self.cog.send_feedback(
            interaction,
            "Alleen de eigenaar of beheer kan deze instelling aanpassen.",
            kind="error",
            title="Geen toegang",
        )
        return False

    async def _refresh_shared(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
    ) -> None:
        if (
            interaction.message is not None
            and interaction.channel_id == channel.id
        ):
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=TempVoiceControlPanel(
                    self.cog,
                    channel,
                    persistent=True,
                ),
            )
        else:
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=TempVoiceControlPanel(
                    self.cog,
                    channel,
                    persistent=False,
                ),
            )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        channel = await self._channel(interaction)
        if channel is None:
            return

        if action == "claim":
            if not isinstance(interaction.user, discord.Member):
                await self.cog.send_feedback(
                    interaction,
                    "Dit werkt alleen voor serverleden.",
                    kind="error",
                )
                return

            if interaction.user not in channel.members:
                await self.cog.send_feedback(
                    interaction,
                    "Je moet in deze voice zitten om hem te claimen.",
                    kind="error",
                )
                return

            owner_id = await self.cog.temp_owner(channel.id)
            if owner_id == interaction.user.id:
                await self.cog.send_feedback(
                    interaction,
                    "Jij bent al eigenaar van dit voicekanaal.",
                    kind="info",
                )
                return

            owner_still_here = any(
                member.id == owner_id
                for member in channel.members
            )
            if owner_still_here:
                await self.cog.send_feedback(
                    interaction,
                    "De huidige eigenaar zit nog in het voicekanaal.",
                    kind="error",
                )
                return

            await interaction.response.defer(ephemeral=True)
            try:
                await self.cog.set_owner(channel, interaction.user)
                await self.cog.refresh_control_panel(channel)
            except (discord.Forbidden, discord.HTTPException) as exc:
                logger.exception(
                    "Temp VC %s claimen mislukt",
                    channel.id,
                    exc_info=exc,
                )
                await interaction.followup.send(
                    view=FeedbackView(
                        f"Claimen is mislukt: `{type(exc).__name__}`",
                        kind="error",
                    ),
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                view=FeedbackView(
                    "Jij bent nu eigenaar van dit tijdelijke voicekanaal.",
                    kind="success",
                ),
                ephemeral=True,
            )
            return

        if action == "refresh":
            if interaction.message is not None:
                await self._refresh_shared(interaction, channel)
            else:
                await self.cog.send_feedback(
                    interaction,
                    "Het beheerpanel is vernieuwd.",
                    kind="success",
                )
            return

        if not await self._require_control(interaction, channel):
            return

        panel_message_id = self._message_id(interaction)

        if action == "rename":
            await interaction.response.send_modal(
                RenameVoiceModal(
                    self.cog,
                    channel,
                    panel_message_id,
                )
            )
            return

        if action == "limit":
            await interaction.response.send_modal(
                VoiceLimitModal(
                    self.cog,
                    channel,
                    panel_message_id,
                )
            )
            return

        if action == "delete":
            await interaction.response.send_message(
                view=VoiceDeleteConfirmView(
                    self.cog,
                    channel.id,
                ),
                ephemeral=True,
            )

    async def handle_privacy(
        self,
        interaction: discord.Interaction,
        mode: str,
    ) -> None:
        channel = await self._channel(interaction)
        if channel is None:
            return
        if not await self._require_control(interaction, channel):
            return

        if mode not in {"open", "locked", "private"}:
            await self.cog.send_feedback(
                interaction,
                "Onbekende privacy-instelling.",
                kind="error",
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await self.cog.apply_privacy(
                channel,
                mode,
                actor=interaction.user,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception(
                "Temp VC %s privacy wijzigen naar %s mislukt",
                channel.id,
                mode,
                exc_info=exc,
            )
            await interaction.followup.send(
                view=FeedbackView(
                    f"Privacy kon niet worden aangepast: `{type(exc).__name__}`",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        await self.cog.refresh_control_panel(
            channel,
            message_id=(
                interaction.message.id
                if (
                    interaction.message is not None
                    and interaction.channel_id == channel.id
                )
                else None
            ),
        )

        labels = {
            "open": "Open",
            "locked": "Gesloten",
            "private": "Privé",
        }
        await interaction.followup.send(
            view=FeedbackView(
                f"Privacy staat nu op **{labels[mode]}**.",
                kind="success",
            ),
            ephemeral=True,
        )

    async def _selected_member(
        self,
        channel: discord.VoiceChannel,
        selected_users: list[discord.User | discord.Member],
    ) -> discord.Member | None:
        if not selected_users:
            return None
        return channel.guild.get_member(selected_users[0].id)

    async def _target_allowed(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        member: discord.Member,
        *,
        action: str,
    ) -> bool:
        owner_id = await self.cog.temp_owner(channel.id)

        if member.bot:
            await self.cog.send_feedback(
                interaction,
                "Bots kunnen niet via dit voicebeheer worden aangepast.",
                kind="error",
            )
            return False

        if member.id == owner_id:
            await self.cog.send_feedback(
                interaction,
                f"De eigenaar kan niet worden {action}. Draag eerst het eigendom over.",
                kind="error",
            )
            return False

        if (
            member.id == channel.guild.owner_id
            or member.guild_permissions.administrator
        ):
            await self.cog.send_feedback(
                interaction,
                "Serverbeheer kan niet via een tijdelijk voicekanaal worden aangepast.",
                kind="error",
            )
            return False

        return True

    async def handle_kick(
        self,
        interaction: discord.Interaction,
        selected_users: list[discord.User | discord.Member],
    ) -> None:
        channel = await self._channel(interaction)
        if channel is None:
            return
        if not await self._require_control(interaction, channel):
            return

        member = await self._selected_member(channel, selected_users)
        if member is None:
            await self.cog.send_feedback(
                interaction,
                "De gekozen gebruiker is niet beschikbaar.",
                kind="error",
            )
            return

        if not await self._target_allowed(
            interaction,
            channel,
            member,
            action="verwijderd",
        ):
            return

        if member not in channel.members:
            await self.cog.send_feedback(
                interaction,
                "Deze gebruiker zit momenteel niet in jouw voicekanaal.",
                kind="error",
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await member.move_to(
                None,
                reason=f"Uit tijdelijke VC verwijderd door {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception(
                "Lid %s verwijderen uit temp VC %s mislukt",
                member.id,
                channel.id,
                exc_info=exc,
            )
            await interaction.followup.send(
                view=FeedbackView(
                    f"Gebruiker verwijderen is mislukt: `{type(exc).__name__}`",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            view=FeedbackView(
                f"{member.mention} is uit de voice verwijderd. "
                "Diegene kan opnieuw joinen als de privacy-instellingen dat toestaan.",
                kind="success",
            ),
            ephemeral=True,
        )

    async def handle_block(
        self,
        interaction: discord.Interaction,
        selected_users: list[discord.User | discord.Member],
    ) -> None:
        channel = await self._channel(interaction)
        if channel is None:
            return
        if not await self._require_control(interaction, channel):
            return

        member = await self._selected_member(channel, selected_users)
        if member is None:
            await self.cog.send_feedback(
                interaction,
                "De gekozen gebruiker is niet beschikbaar.",
                kind="error",
            )
            return

        if not await self._target_allowed(
            interaction,
            channel,
            member,
            action="geblokkeerd",
        ):
            return

        await interaction.response.defer(ephemeral=True)

        overwrite = channel.overwrites_for(member)
        overwrite.connect = False
        overwrite.speak = None
        if self.cog.privacy_mode(channel) == "private":
            overwrite.view_channel = None

        try:
            await channel.set_permissions(
                member,
                overwrite=overwrite,
                reason=f"Geblokkeerd uit tijdelijke VC door {interaction.user}",
            )
            if member in channel.members:
                await member.move_to(
                    None,
                    reason=f"Geblokkeerd uit tijdelijke VC door {interaction.user}",
                )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception(
                "Lid %s blokkeren in temp VC %s mislukt",
                member.id,
                channel.id,
                exc_info=exc,
            )
            await interaction.followup.send(
                view=FeedbackView(
                    f"Gebruiker blokkeren is mislukt: `{type(exc).__name__}`",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            view=FeedbackView(
                f"{member.mention} is geblokkeerd voor deze tijdelijke voice. "
                "Via **Toegang geven** kun je de blokkade later weer opheffen.",
                kind="success",
            ),
            ephemeral=True,
        )

    async def handle_access(
        self,
        interaction: discord.Interaction,
        selected_users: list[discord.User | discord.Member],
    ) -> None:
        channel = await self._channel(interaction)
        if channel is None:
            return
        if not await self._require_control(interaction, channel):
            return

        members: list[discord.Member] = []
        for selected in selected_users:
            member = channel.guild.get_member(selected.id)
            if member is not None and not member.bot:
                members.append(member)

        if not members:
            await self.cog.send_feedback(
                interaction,
                "Er zijn geen geldige gebruikers geselecteerd.",
                kind="error",
            )
            return

        await interaction.response.defer(ephemeral=True)

        granted: list[discord.Member] = []
        for member in members:
            overwrite = channel.overwrites_for(member)
            overwrite.view_channel = True
            overwrite.connect = True
            overwrite.speak = True
            try:
                await channel.set_permissions(
                    member,
                    overwrite=overwrite,
                    reason=f"Temp VC toegang door {interaction.user}",
                )
                granted.append(member)
            except (discord.Forbidden, discord.HTTPException) as exc:
                logger.warning(
                    "Kon toegang tot temp VC %s niet geven aan %s: %s",
                    channel.id,
                    member.id,
                    exc,
                )

        if interaction.message is not None:
            await self.cog.refresh_control_panel(
                channel,
                message_id=interaction.message.id,
            )

        if granted:
            await interaction.followup.send(
                view=FeedbackView(
                    "Toegang gegeven aan "
                    + ", ".join(member.mention for member in granted)
                    + ".",
                    kind="success",
                ),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                view=FeedbackView(
                    "Toegang kon niet worden verleend.",
                    kind="error",
                ),
                ephemeral=True,
            )

    async def handle_transfer(
        self,
        interaction: discord.Interaction,
        selected_users: list[discord.User | discord.Member],
    ) -> None:
        channel = await self._channel(interaction)
        if channel is None:
            return
        if not await self._require_control(interaction, channel):
            return

        if not selected_users:
            await self.cog.send_feedback(
                interaction,
                "Kies een nieuwe eigenaar.",
                kind="error",
            )
            return

        member = channel.guild.get_member(selected_users[0].id)
        if member is None or member.bot:
            await self.cog.send_feedback(
                interaction,
                "De gekozen gebruiker is niet beschikbaar.",
                kind="error",
            )
            return

        if member not in channel.members:
            await self.cog.send_feedback(
                interaction,
                "De nieuwe eigenaar moet in dit voicekanaal zitten.",
                kind="error",
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await self.cog.set_owner(channel, member)
            await self.cog.refresh_control_panel(
                channel,
                message_id=(
                    interaction.message.id
                    if interaction.message is not None
                    else None
                ),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception(
                "Temp VC %s eigenaar overdragen mislukt",
                channel.id,
                exc_info=exc,
            )
            await interaction.followup.send(
                view=FeedbackView(
                    f"Eigendom overdragen is mislukt: `{type(exc).__name__}`",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            view=FeedbackView(
                f"{member.mention} is nu eigenaar van dit tijdelijke voicekanaal.",
                kind="success",
            ),
            ephemeral=True,
        )


class VoiceSettingsModal(discord.ui.Modal, title="Temp Voice • Instellingen"):
    def __init__(self, cog: "Voice", guild_id: int, cfg: VoiceConfig):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

        self.template = discord.ui.TextInput(
            label="Kanaalnaam format",
            default=cfg.name_template,
            placeholder="{name} • VC",
            max_length=100,
        )
        self.defaults = discord.ui.TextInput(
            label="Limiet / bitrate / verwijdervertraging",
            default=f"{cfg.default_limit} | {cfg.bitrate_kbps} | {cfg.delete_delay}",
            placeholder="0 | 64 | 0",
            max_length=30,
        )
        self.privacy = discord.ui.RadioGroup(
            options=[
                discord.RadioGroupOption(
                    label="Standaard open",
                    value="open",
                    description="Erft de toegang van de categorie.",
                    default=not cfg.default_locked,
                ),
                discord.RadioGroupOption(
                    label="Standaard gelockt",
                    value="locked",
                    description="Eigenaar opent zelf indien gewenst.",
                    default=cfg.default_locked,
                ),
            ]
        )
        self.behaviour = discord.ui.CheckboxGroup(
            min_values=0,
            max_values=1,
            required=False,
            options=[
                discord.CheckboxGroupOption(
                    label="Lege tijdelijke kanalen automatisch verwijderen",
                    value="auto_delete",
                    default=cfg.auto_delete,
                )
            ],
        )

        self.add_item(self.template)
        self.add_item(self.defaults)
        self.add_item(
            discord.ui.Label(
                text="Standaard privacy",
                description="Hoe nieuwe tijdelijke kanalen starten.",
                component=self.privacy,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Automatisch opruimen",
                description="Voorkomt lege tijdelijke voice kanalen.",
                component=self.behaviour,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            parts = [x.strip() for x in self.defaults.value.split("|")]
            if len(parts) != 3:
                raise ValueError

            limit, bitrate, delay = map(int, parts)

            if not 0 <= limit <= 99:
                raise ValueError
            if not 8 <= bitrate <= 384:
                raise ValueError
            if not 0 <= delay <= 3600:
                raise ValueError

            template = self.template.value.strip()
            template.format(
                name="Mika",
                username="mika",
                id="123",
                count=1,
            )
        except (ValueError, KeyError, IndexError):
            await self.cog.send_feedback(
                interaction,
                (
                    "Gebruik `limiet | bitrate_kbps | delete_delay_sec`, "
                    "bijvoorbeeld `0 | 64 | 0`.\n"
                    "Naamformat ondersteunt `{name}`, `{username}`, `{id}` en `{count}`."
                ),
                kind="error",
                title="Ongeldige instellingen",
            )
            return

        await interaction.response.defer(ephemeral=True)

        await self.cog.update_config(
            self.guild_id,
            name_template=template,
            default_limit=limit,
            bitrate_kbps=bitrate,
            default_locked=(self.privacy.value == "locked"),
            auto_delete=("auto_delete" in self.behaviour.values),
            delete_delay=delay,
        )

        cfg = await self.cog.config(self.guild_id)
        await interaction.followup.send(
            view=VoiceConfigView(
                self.cog,
                self.guild_id,
                interaction.user.id,
                cfg,
                notice="Instellingen opgeslagen.",
            ),
            ephemeral=True,
        )


class VoiceLobbySelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        cog: "Voice",
        guild_id: int,
        author_id: int,
    ):
        super().__init__(
            placeholder="Kies join-to-create voice kanaal…",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1,
        )
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0]
        await self.cog.update_config(
            self.guild_id,
            lobby_channel_id=channel.id,
        )
        cfg = await self.cog.config(self.guild_id)
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=VoiceChannelsView(
                self.cog,
                self.guild_id,
                self.author_id,
                cfg,
                notice=f"Join-to-create ingesteld op <#{channel.id}>.",
            ),
        )


class VoiceCategorySelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        cog: "Voice",
        guild_id: int,
        author_id: int,
    ):
        super().__init__(
            placeholder="Kies categorie voor tijdelijke kanalen…",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=1,
        )
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction) -> None:
        category = self.values[0]
        await self.cog.update_config(
            self.guild_id,
            category_id=category.id,
        )
        cfg = await self.cog.config(self.guild_id)
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=VoiceChannelsView(
                self.cog,
                self.guild_id,
                self.author_id,
                cfg,
                notice=f"Categorie ingesteld op <#{category.id}>.",
            ),
        )


class OwnedVoiceLayout(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Voice",
        author_id: int,
        *,
        timeout: float = 300,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author_id:
            await self.cog.send_feedback(
                interaction,
                "Dit beheermenu hoort bij iemand anders.",
                kind="error",
            )
            return False

        if (
            not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await self.cog.send_feedback(
                interaction,
                "Je hebt geen toegang meer tot dit beheermenu.",
                kind="error",
                title="Geen toegang",
            )
            return False

        return True


class VoiceChannelsBackButton(discord.ui.Button):
    def __init__(self, owner_view: "VoiceChannelsView"):
        super().__init__(
            label="Terug",
            emoji=ui_emoji(BACK_EMOJI),
            style=discord.ButtonStyle.secondary,
        )
        self.owner_view = owner_view

    async def callback(self, interaction: discord.Interaction) -> None:
        cfg = await self.owner_view.cog.config(self.owner_view.guild_id)
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=VoiceConfigView(
                self.owner_view.cog,
                self.owner_view.guild_id,
                self.owner_view.author_id,
                cfg,
            ),
        )


class VoiceChannelsView(OwnedVoiceLayout):
    def __init__(
        self,
        cog: "Voice",
        guild_id: int,
        author_id: int,
        cfg: VoiceConfig | None,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=300)
        self.guild_id = guild_id

        lobby = (
            f"<#{cfg.lobby_channel_id}>"
            if cfg and cfg.lobby_channel_id
            else "Niet ingesteld"
        )
        category = (
            f"<#{cfg.category_id}>"
            if cfg and cfg.category_id
            else "Niet ingesteld"
        )

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"# {VOICE_EMOJI} Temp Voice kanalen\n"
                "> └ Kies het join-to-create kanaal en de categorie voor nieuwe tijdelijke kanalen.\n\n"
                f"## {VOICE_EMOJI} Join-to-create\n"
                f"> └ {lobby}\n\n"
                f"## {SETTINGS_EMOJI} Categorie\n"
                f"> └ {category}"
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
                    VoiceLobbySelect(cog, guild_id, author_id)
                ),
                discord.ui.ActionRow(
                    VoiceCategorySelect(cog, guild_id, author_id)
                ),
                discord.ui.ActionRow(
                    VoiceChannelsBackButton(self)
                ),
                discord.ui.TextDisplay(
                    "-# Beide keuzes zijn later altijd opnieuw aanpasbaar."
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PANEL_COLOR,
            )
        )


class VoiceConfigActionButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "VoiceConfigView",
        action: str,
        label: str,
        *,
        emoji: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ):
        super().__init__(
            label=label,
            emoji=ui_emoji(emoji),
            style=style,
        )
        self.owner_view = owner_view
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.handle(interaction, self.action)


class VoiceConfigView(OwnedVoiceLayout):
    def __init__(
        self,
        cog: "Voice",
        guild_id: int,
        author_id: int,
        cfg: VoiceConfig | None,
        *,
        active_count: int | None = None,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)
        self.guild_id = guild_id

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                cog.config_text(
                    cfg,
                    active_count=active_count,
                )
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
                    VoiceConfigActionButton(
                        self,
                        "settings",
                        "Instellingen",
                        emoji=SETTINGS_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    VoiceConfigActionButton(
                        self,
                        "channels",
                        "Kanalen",
                        emoji=VOICE_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    VoiceConfigActionButton(
                        self,
                        "preview",
                        "Preview",
                        emoji=INFO_EMOJI,
                    ),
                ),
                discord.ui.ActionRow(
                    VoiceConfigActionButton(
                        self,
                        "cleanup",
                        "Opschonen",
                        emoji=DELETE_EMOJI,
                    ),
                    VoiceConfigActionButton(
                        self,
                        "info",
                        "Uitleg",
                        emoji=INFO_EMOJI,
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# Alleen beheer kan deze configuratie aanpassen."
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PANEL_COLOR,
            )
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await self.cog.send_feedback(
                interaction,
                "Dit onderdeel werkt alleen in een server.",
                kind="error",
            )
            return

        cfg = await self.cog.config(guild.id)

        if action == "settings":
            if cfg is None or not cfg.lobby_channel_id or not cfg.category_id:
                await self.cog.send_feedback(
                    interaction,
                    "Kies eerst het join-to-create kanaal en de categorie via **Kanalen**.",
                    kind="error",
                )
                return
            await interaction.response.send_modal(
                VoiceSettingsModal(self.cog, guild.id, cfg)
            )
            return

        if action == "channels":
            await interaction.response.send_message(
                view=VoiceChannelsView(
                    self.cog,
                    guild.id,
                    self.author_id,
                    cfg,
                ),
                ephemeral=True,
            )
            return

        if action == "preview":
            if cfg is None:
                await self.cog.send_feedback(
                    interaction,
                    "Temp Voice is nog niet ingesteld.",
                    kind="error",
                )
                return
            preview = self.cog.render_name(
                cfg,
                interaction.user,
                1,
            )
            await self.cog.send_feedback(
                interaction,
                f"Nieuwe VC voor jou: **{preview}**\nFormat: `{cfg.name_template}`",
                kind="info",
                title="Preview",
            )
            return

        if action == "cleanup":
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )
            deleted, stale = await self.cog.cleanup(guild)
            await interaction.followup.send(
                view=FeedbackView(
                    (
                        f"Lege VCs verwijderd: **{deleted}**\n"
                        f"Oude database-rijen verwijderd: **{stale}**"
                    ),
                    kind="success",
                    title="Opschonen voltooid",
                ),
                ephemeral=True,
            )
            return

        if action == "info":
            await interaction.response.send_message(
                view=VoiceInfoView(self.cog),
                ephemeral=True,
            )


class VoiceInfoView(discord.ui.LayoutView):
    def __init__(self, cog: "Voice"):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(cog.info_text()),
                discord.ui.TextDisplay(
                    "-# Gebruik `/voice beheer` terwijl je in jouw tijdelijke voice zit."
                ),
                accent_colour=PANEL_COLOR,
            )
        )


class Voice(commands.Cog):
    """Join-to-create tijdelijke voice channels met een eenvoudige configuratie-UI."""

    voice = app_commands.Group(name="voice", description="Tijdelijke voice channels")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._create_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._delete_tasks: dict[int, asyncio.Task] = {}
        self._owner_cache: dict[int, int] = {}
        self._panel_view_registered = False

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

    def config_text(
        self,
        cfg: VoiceConfig | None,
        *,
        active_count: int | None = None,
    ) -> str:
        lines = [
            f"# {VOICE_EMOJI} Temp Voice",
            "> └ Beheer de join-to-create voicekanalen van LEVENLOOS.",
            "",
        ]

        if cfg is None:
            lines.extend(
                [
                    f"## {WARNING_EMOJI} Nog niet ingesteld",
                    "> └ Kies via **Kanalen** eerst een lobby en categorie.",
                ]
            )
            return "\n".join(lines)

        lobby = (
            f"<#{cfg.lobby_channel_id}>"
            if cfg.lobby_channel_id
            else "Niet ingesteld"
        )
        category = (
            f"<#{cfg.category_id}>"
            if cfg.category_id
            else "Niet ingesteld"
        )

        lines.extend(
            [
                f"## {VOICE_EMOJI} Kanalen",
                f"> └ Join-to-create: {lobby}",
                f"> └ Categorie: {category}",
                "",
                f"## {SETTINGS_EMOJI} Standaardinstellingen",
                f"> └ Naamformat: `{cfg.name_template}`",
                f"> └ Limiet: `{'∞' if cfg.default_limit == 0 else cfg.default_limit}`",
                f"> └ Bitrate: `{cfg.bitrate_kbps} kbps`",
                f"> └ Privacy: `{'Gesloten' if cfg.default_locked else 'Open'}`",
                f"> └ Auto-delete: `{'Aan' if cfg.auto_delete else 'Uit'}` • delay `{cfg.delete_delay}s`",
            ]
        )

        if active_count is not None:
            lines.extend(
                [
                    "",
                    f"## {USER_EMOJI} Actief",
                    f"> └ Tijdelijke voicekanalen: **{active_count}**",
                ]
            )

        return "\n".join(lines)

    def info_text(self) -> str:
        return (
            f"# {VOICE_EMOJI} Temp Voice\n"
            "> └ Join het ingestelde **join-to-create** kanaal en de bot maakt automatisch jouw eigen tijdelijke voice.\n\n"
            f"## {SETTINGS_EMOJI} Automatisch beheerpanel\n"
            "> └ In de chat van iedere tijdelijke voice verschijnt direct een vast Components V2-beheerpanel.\n"
            "> └ Pas naam en limiet aan en kies **Open**, **Gesloten** of **Privé**.\n"
            "> └ Geef toegang, verwijder iemand uit de voice of blokkeer iemand voor deze tijdelijke voice.\n"
            "> └ `/voice beheer` opent hetzelfde beheer ook privé als alternatief.\n"
            "> └ Is de eigenaar vertrokken, dan kan iemand in de voice het kanaal direct claimen.\n"
            f"> └ {DELETE_EMOJI} Verwijderen vraagt altijd om een aparte bevestiging.\n\n"
            f"## {INFO_EMOJI} Invoer\n"
            "> └ Alleen vrije tekst zoals **naam** en een vrije **0-99 limiet** gebruikt een klein invoervenster; de rest gebeurt rechtstreeks vanuit het panel.\n\n"
            f"## {SETTINGS_EMOJI} Voor beheer\n"
            "> └ `/voice config` opent het volledige configuratiepaneel.\n"
            "> └ Naamformat ondersteunt `{name}`, `{username}`, `{id}` en `{count}`.\n"
            "> └ Limiet, bitrate, privacy, auto-delete en delete-delay zijn instelbaar."
        )

    async def cog_load(self) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS voice_config (
                    guild_id INTEGER PRIMARY KEY,
                    lobby_channel_id INTEGER NOT NULL DEFAULT 0,
                    category_id INTEGER NOT NULL DEFAULT 0,
                    default_limit INTEGER NOT NULL DEFAULT 0,
                    name_template TEXT NOT NULL DEFAULT '{name} • VC',
                    bitrate_kbps INTEGER NOT NULL DEFAULT 64,
                    default_locked INTEGER NOT NULL DEFAULT 0,
                    auto_delete INTEGER NOT NULL DEFAULT 1,
                    delete_delay INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS temp_voice (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    owner_id INTEGER NOT NULL,
                    panel_message_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # Backwards-compatible migraties voor een oudere voice.db.
            cursor = await db.execute("PRAGMA table_info(voice_config)")
            columns = {row[1] for row in await cursor.fetchall()}
            migrations = {
                "bitrate_kbps": "ALTER TABLE voice_config ADD COLUMN bitrate_kbps INTEGER NOT NULL DEFAULT 64",
                "default_locked": "ALTER TABLE voice_config ADD COLUMN default_locked INTEGER NOT NULL DEFAULT 0",
                "auto_delete": "ALTER TABLE voice_config ADD COLUMN auto_delete INTEGER NOT NULL DEFAULT 1",
                "delete_delay": "ALTER TABLE voice_config ADD COLUMN delete_delay INTEGER NOT NULL DEFAULT 0",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    await db.execute(statement)

            temp_cursor = await db.execute("PRAGMA table_info(temp_voice)")
            temp_columns = {row[1] for row in await temp_cursor.fetchall()}
            if "panel_message_id" not in temp_columns:
                await db.execute(
                    "ALTER TABLE temp_voice ADD COLUMN panel_message_id INTEGER"
                )

            owner_cursor = await db.execute(
                "SELECT channel_id, owner_id FROM temp_voice"
            )
            self._owner_cache = {
                int(row[0]): int(row[1])
                for row in await owner_cursor.fetchall()
            }
            await db.commit()

        if not self._panel_view_registered:
            self.bot.add_view(
                TempVoiceControlPanel(
                    self,
                    None,
                    persistent=True,
                )
            )
            self._panel_view_registered = True

    def cog_unload(self) -> None:
        for task in self._delete_tasks.values():
            task.cancel()

    async def config(self, guild_id: int) -> VoiceConfig | None:
        async with aiosqlite.connect(DB_PATH) as db:
            row = await (await db.execute(
                "SELECT lobby_channel_id, category_id, default_limit, name_template, bitrate_kbps, default_locked, auto_delete, delete_delay FROM voice_config WHERE guild_id=?",
                (guild_id,),
            )).fetchone()
        if not row:
            return None
        return VoiceConfig(
            lobby_channel_id=int(row[0]),
            category_id=int(row[1]),
            default_limit=int(row[2] or 0),
            name_template=str(row[3] or DEFAULT_TEMPLATE),
            bitrate_kbps=int(row[4] or 64),
            default_locked=bool(row[5]),
            auto_delete=bool(row[6]),
            delete_delay=int(row[7] or 0),
        )

    async def update_config(self, guild_id: int, **values) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO voice_config(guild_id,lobby_channel_id,category_id) VALUES(?,?,?)",
                (guild_id, 0, 0),
            )
            allowed = {"lobby_channel_id", "category_id", "default_limit", "name_template", "bitrate_kbps", "default_locked", "auto_delete", "delete_delay"}
            for key, value in values.items():
                if key not in allowed:
                    continue
                await db.execute(f"UPDATE voice_config SET {key}=? WHERE guild_id=?", (int(value) if isinstance(value, bool) else value, guild_id))
            await db.commit()

    def cached_owner_id(self, channel_id: int) -> int | None:
        return self._owner_cache.get(channel_id)

    async def temp_owner(self, channel_id: int) -> int | None:
        cached = self._owner_cache.get(channel_id)
        if cached is not None:
            return cached

        async with aiosqlite.connect(DB_PATH) as db:
            row = await (
                await db.execute(
                    "SELECT owner_id FROM temp_voice WHERE channel_id=?",
                    (channel_id,),
                )
            ).fetchone()

        if row is None:
            return None

        owner_id = int(row[0])
        self._owner_cache[channel_id] = owner_id
        return owner_id

    async def panel_message_id(self, channel_id: int) -> int | None:
        async with aiosqlite.connect(DB_PATH) as db:
            row = await (
                await db.execute(
                    "SELECT panel_message_id FROM temp_voice WHERE channel_id=?",
                    (channel_id,),
                )
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    async def set_panel_message_id(
        self,
        channel_id: int,
        message_id: int | None,
    ) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE temp_voice SET panel_message_id=? WHERE channel_id=?",
                (message_id, channel_id),
            )
            await db.commit()

    def get_temp_channel(
        self,
        interaction: discord.Interaction,
        channel_id: int | None,
    ) -> discord.VoiceChannel | None:
        if interaction.guild is None or channel_id is None:
            return None
        channel = interaction.guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.VoiceChannel):
            return None
        return channel

    async def refresh_control_panel(
        self,
        channel: discord.VoiceChannel,
        *,
        message_id: int | None = None,
    ) -> bool:
        target_id = message_id or await self.panel_message_id(channel.id)
        if target_id is None:
            return False

        try:
            message = await channel.fetch_message(target_id)
            await message.edit(
                content=None,
                embeds=[],
                view=TempVoiceControlPanel(
                    self,
                    channel,
                    persistent=True,
                ),
            )
            return True
        except discord.NotFound:
            if target_id == await self.panel_message_id(channel.id):
                await self.set_panel_message_id(channel.id, None)
            return False
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "Voice beheerpanel %s in kanaal %s kon niet worden vernieuwd: %s",
                target_id,
                channel.id,
                exc,
            )
            return False

    async def ensure_control_panel(
        self,
        channel: discord.VoiceChannel,
    ) -> discord.Message | None:
        existing_id = await self.panel_message_id(channel.id)

        if existing_id is not None:
            try:
                message = await channel.fetch_message(existing_id)
                await message.edit(
                    content=None,
                    embeds=[],
                    view=TempVoiceControlPanel(
                        self,
                        channel,
                        persistent=True,
                    ),
                )
                return message
            except discord.NotFound:
                await self.set_panel_message_id(channel.id, None)
            except (discord.Forbidden, discord.HTTPException) as exc:
                logger.warning(
                    "Bestaand voice beheerpanel in kanaal %s kon niet worden geopend: %s",
                    channel.id,
                    exc,
                )
                return None

        try:
            message = await channel.send(
                view=TempVoiceControlPanel(
                    self,
                    channel,
                    persistent=True,
                ),
                silent=True,
            )
            await self.set_panel_message_id(
                channel.id,
                message.id,
            )
            return message
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "Kon automatisch voice beheerpanel niet plaatsen in kanaal %s: %s",
                channel.id,
                exc,
            )
            return None

    async def restore_control_panels(
        self,
        guild: discord.Guild,
    ) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await (
                await db.execute(
                    "SELECT channel_id, owner_id FROM temp_voice WHERE guild_id=?",
                    (guild.id,),
                )
            ).fetchall()

        for channel_id, owner_id in rows:
            self._owner_cache[int(channel_id)] = int(owner_id)
            channel = guild.get_channel(int(channel_id))
            if isinstance(channel, discord.VoiceChannel):
                await self.ensure_control_panel(channel)

    def privacy_mode(self, channel: discord.VoiceChannel) -> str:
        overwrite = channel.overwrites_for(channel.guild.default_role)
        if overwrite.view_channel is False:
            return "private"
        if overwrite.connect is False:
            return "locked"
        return "open"

    async def apply_privacy(
        self,
        channel: discord.VoiceChannel,
        mode: str,
        *,
        actor: discord.abc.User | None = None,
    ) -> None:
        if mode not in {"open", "locked", "private"}:
            raise ValueError(f"Onbekende privacy mode: {mode}")

        guild = channel.guild
        everyone = channel.overwrites_for(guild.default_role)

        if mode == "open":
            everyone.view_channel = None
            everyone.connect = None
        elif mode == "locked":
            everyone.view_channel = None
            everyone.connect = False
        else:
            everyone.view_channel = False
            everyone.connect = False

        await channel.set_permissions(
            guild.default_role,
            overwrite=everyone,
            reason=(
                f"Temp VC privacy naar {mode}"
                + (f" door {actor}" if actor is not None else "")
            ),
        )

        owner_id = await self.temp_owner(channel.id)
        owner = guild.get_member(owner_id) if owner_id else None
        if owner is not None:
            owner_overwrite = channel.overwrites_for(owner)
            owner_overwrite.view_channel = True
            owner_overwrite.connect = True
            owner_overwrite.speak = True
            owner_overwrite.manage_channels = True
            owner_overwrite.move_members = True
            await channel.set_permissions(
                owner,
                overwrite=owner_overwrite,
                reason="Temp VC eigenaar toegang bewaken",
            )

        bot_member = guild.me
        if bot_member is not None:
            bot_overwrite = channel.overwrites_for(bot_member)
            bot_overwrite.view_channel = True
            bot_overwrite.connect = True
            bot_overwrite.send_messages = True
            bot_overwrite.read_message_history = True
            await channel.set_permissions(
                bot_member,
                overwrite=bot_overwrite,
                reason="Temp VC beheerpanel bereikbaar houden",
            )

    async def can_control(self, user: discord.abc.User, channel: discord.VoiceChannel) -> bool:
        return isinstance(user, discord.Member) and (management_access(user) or await self.temp_owner(channel.id) == user.id)

    async def set_owner(self, channel: discord.VoiceChannel, member: discord.Member) -> None:
        old_owner_id = await self.temp_owner(channel.id)
        old_owner = channel.guild.get_member(old_owner_id) if old_owner_id else None
        if old_owner is not None and old_owner != member:
            try:
                old_overwrite = channel.overwrites_for(old_owner)
                old_overwrite.manage_channels = None
                old_overwrite.move_members = None
                old_overwrite.view_channel = None
                old_overwrite.connect = None
                old_overwrite.speak = None
                await channel.set_permissions(
                    old_owner,
                    overwrite=old_overwrite,
                    reason="Temp VC owner gewijzigd",
                )
            except discord.HTTPException:
                pass
        new_overwrite = channel.overwrites_for(member)
        new_overwrite.view_channel = True
        new_overwrite.manage_channels = True
        new_overwrite.move_members = True
        new_overwrite.connect = True
        new_overwrite.speak = True
        await channel.set_permissions(
            member,
            overwrite=new_overwrite,
            reason="Temp VC owner gewijzigd",
        )
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE temp_voice SET owner_id=? WHERE channel_id=?",
                (member.id, channel.id),
            )
            await db.commit()
        self._owner_cache[channel.id] = member.id

    async def forget_channel(self, channel_id: int) -> None:
        task = self._delete_tasks.pop(channel_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM temp_voice WHERE channel_id=?",
                (channel_id,),
            )
            await db.commit()
        self._owner_cache.pop(channel_id, None)

    def render_name(self, cfg: VoiceConfig, member: discord.Member, count: int) -> str:
        try:
            name = cfg.name_template.format(
                name=member.display_name,
                username=member.name,
                id=member.id,
                count=count,
            )
        except (KeyError, ValueError, IndexError):
            name = f"{member.display_name} • VC"
        return name[:100]

    async def create_temp(self, member: discord.Member, cfg: VoiceConfig) -> discord.VoiceChannel | None:
        guild = member.guild
        category = guild.get_channel(cfg.category_id)
        if not isinstance(category, discord.CategoryChannel):
            return None
        async with aiosqlite.connect(DB_PATH) as db:
            count = (await (await db.execute("SELECT COUNT(*) FROM temp_voice WHERE guild_id=?", (guild.id,))).fetchone())[0] + 1
        name = self.render_name(cfg, member, count)
        me = guild.me
        if me is None:
            return None

        category_permissions = category.permissions_for(me)
        if not (
            category_permissions.view_channel
            and category_permissions.manage_channels
            and category_permissions.move_members
        ):
            logger.warning(
                "Temp Voice mist permissies in categorie %s op guild %s",
                category.id,
                guild.id,
            )
            return None

        default_overwrite = discord.PermissionOverwrite(
            connect=False if cfg.default_locked else None
        )
        overwrites = {
            guild.default_role: default_overwrite,
            member: discord.PermissionOverwrite(
                view_channel=True,
                manage_channels=True,
                move_members=True,
                connect=True,
                speak=True,
            ),
        }
        if me.id != member.id:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                send_messages=True,
                read_message_history=True,
            )

        bitrate = max(
            8000,
            min(int(cfg.bitrate_kbps) * 1000, guild.bitrate_limit),
        )
        channel = await guild.create_voice_channel(
            name,
            category=category,
            user_limit=max(0, min(99, cfg.default_limit)),
            bitrate=bitrate,
            overwrites=overwrites,
            reason=f"Tijdelijke VC voor {member}",
        )
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO temp_voice(
                    channel_id,
                    guild_id,
                    owner_id,
                    panel_message_id
                )
                VALUES(?,?,?,NULL)
                """,
                (channel.id, guild.id, member.id),
            )
            await db.commit()
        self._owner_cache[channel.id] = member.id

        await self.ensure_control_panel(channel)

        try:
            await member.move_to(
                channel,
                reason="Join-to-create tijdelijke VC",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "Kon lid %s niet naar tijdelijke VC %s verplaatsen: %s",
                member.id,
                channel.id,
                exc,
            )
            if not channel.members:
                await self.schedule_delete(channel, cfg)

        return channel

    async def schedule_delete(self, channel: discord.VoiceChannel, cfg: VoiceConfig) -> None:
        if not cfg.auto_delete:
            return
        old = self._delete_tasks.pop(channel.id, None)
        if old and not old.done():
            old.cancel()

        async def worker():
            try:
                if cfg.delete_delay:
                    await asyncio.sleep(cfg.delete_delay)
                fresh = channel.guild.get_channel(channel.id)
                if (
                    isinstance(fresh, discord.VoiceChannel)
                    and not fresh.members
                    and await self.temp_owner(fresh.id) is not None
                ):
                    try:
                        await fresh.delete(reason="Tijdelijke VC leeg")
                    except discord.NotFound:
                        pass
                    except (discord.Forbidden, discord.HTTPException) as exc:
                        logger.warning(
                            "Kon lege temp VC %s niet verwijderen: %s",
                            fresh.id,
                            exc,
                        )
                        return
                    await self.forget_channel(fresh.id)
            except asyncio.CancelledError:
                pass
            finally:
                self._delete_tasks.pop(channel.id, None)

        self._delete_tasks[channel.id] = asyncio.create_task(worker(), name=f"temp-vc-delete-{channel.id}")

    async def cleanup(self, guild: discord.Guild) -> tuple[int, int]:
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await (await db.execute("SELECT channel_id FROM temp_voice WHERE guild_id=?", (guild.id,))).fetchall()
        deleted = stale = 0
        cfg = await self.config(guild.id)
        for (channel_id,) in rows:
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.VoiceChannel):
                await self.forget_channel(int(channel_id))
                stale += 1
            elif not channel.members and (cfg is None or cfg.auto_delete):
                try:
                    await channel.delete(reason="Temp VC handmatige cleanup")
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException) as exc:
                    logger.warning(
                        "Kon temp VC %s niet opschonen: %s",
                        channel.id,
                        exc,
                    )
                    continue

                await self.forget_channel(channel.id)
                deleted += 1
        return deleted, stale

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        cfg = await self.config(member.guild.id)
        if (
            cfg
            and cfg.lobby_channel_id
            and cfg.category_id
            and after.channel
            and after.channel.id == cfg.lobby_channel_id
        ):
            lock_key = (member.guild.id, member.id)
            lock = self._create_locks.setdefault(lock_key, asyncio.Lock())
            async with lock:
                if (
                    member.voice
                    and member.voice.channel
                    and member.voice.channel.id != cfg.lobby_channel_id
                ):
                    return
                try:
                    created = await self.create_temp(member, cfg)
                    if created is None:
                        logger.warning(
                            "Temp VC niet aangemaakt voor lid %s op guild %s; controleer configuratie en permissies",
                            member.id,
                            member.guild.id,
                        )
                except Exception as exc:
                    logger.exception(
                        "Aanmaken temp VC mislukt voor lid %s",
                        member.id,
                        exc_info=exc,
                    )

        # Cancel pending deletion if somebody re-joins.
        if after.channel and after.channel.id in self._delete_tasks:
            task = self._delete_tasks.pop(after.channel.id)
            task.cancel()

        if before.channel and before.channel != after.channel and not before.channel.members:
            owner = await self.temp_owner(before.channel.id)
            if owner is not None:
                cfg = cfg or await self.config(member.guild.id)
                if cfg:
                    await self.schedule_delete(before.channel, cfg)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                await self.cleanup(guild)
                await self.restore_control_panels(guild)
            except Exception as exc:
                logger.exception(
                    "Startup cleanup/panel restore mislukt voor guild %s",
                    guild.id,
                    exc_info=exc,
                )

    @voice.command(
        name="setup",
        description="Snelle basissetup voor tijdelijke voice",
    )
    async def setup_voice(
        self,
        interaction: discord.Interaction,
        lobby: discord.VoiceChannel,
        category: discord.CategoryChannel,
    ):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        await self.update_config(
            interaction.guild.id,
            lobby_channel_id=lobby.id,
            category_id=category.id,
        )
        cfg = await self.config(interaction.guild.id)

        await interaction.response.send_message(
            view=VoiceConfigView(
                self,
                interaction.guild.id,
                interaction.user.id,
                cfg,
                notice="Basissetup opgeslagen.",
            ),
            ephemeral=True,
        )

    @voice.command(
        name="config",
        description="Open het complete Temp Voice configuratiepaneel",
    )
    async def config_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        cfg = await self.config(interaction.guild.id)
        await interaction.response.send_message(
            view=VoiceConfigView(
                self,
                interaction.guild.id,
                interaction.user.id,
                cfg,
            ),
            ephemeral=True,
        )

    @voice.command(
        name="beheer",
        description="Beheer je huidige tijdelijke voice kanaal",
    )
    async def manage_voice(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        channel = (
            interaction.user.voice.channel
            if interaction.user.voice
            else None
        )
        if not isinstance(channel, discord.VoiceChannel):
            await self.send_feedback(
                interaction,
                "Je zit niet in een voice kanaal.",
                kind="error",
            )
            return

        owner_id = await self.temp_owner(channel.id)
        if owner_id is None:
            await self.send_feedback(
                interaction,
                "Dit is geen tijdelijk voice kanaal van de bot.",
                kind="error",
            )
            return

        can_control = await self.can_control(
            interaction.user,
            channel,
        )

        if can_control:
            await interaction.response.send_message(
                view=TempVoiceControlPanel(
                    self,
                    channel,
                    persistent=False,
                ),
                ephemeral=True,
            )
            return

        owner_still_here = any(
            member.id == owner_id
            for member in channel.members
        )
        if owner_still_here:
            await self.send_feedback(
                interaction,
                "Alleen de eigenaar of beheer kan dit kanaal aanpassen.",
                kind="error",
                title="Geen toegang",
            )
            return

        await interaction.response.send_message(
            view=TempVoiceControlPanel(
                self,
                channel,
                persistent=False,
                notice="De huidige eigenaar is vertrokken. Gebruik **Claimen** om het beheer over te nemen.",
            ),
            ephemeral=True,
        )

    @voice.command(
        name="status",
        description="Bekijk tijdelijke voice status en configuratie",
    )
    async def voice_status(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        cfg = await self.config(interaction.guild.id)
        if not cfg:
            await self.send_feedback(
                interaction,
                "Tijdelijke voice is nog niet ingesteld. Gebruik `/voice config`.",
                kind="error",
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM temp_voice WHERE guild_id=?",
                (interaction.guild.id,),
            )
            row = await cursor.fetchone()
            count = int(row[0] if row else 0)

        await interaction.response.send_message(
            view=VoiceConfigView(
                self,
                interaction.guild.id,
                interaction.user.id,
                cfg,
                active_count=count,
            ),
            ephemeral=True,
        )

    @voice.command(
        name="info",
        description="Bekijk hoe tijdelijke voice werkt",
    )
    async def voice_info(
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

        await interaction.response.send_message(
            view=VoiceInfoView(self),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Voice(bot))
