import asyncio
import math
import logging
import os
import sqlite3
import sys
import shutil
import zipfile
import traceback
import resource
from pathlib import Path
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


# =========================================================
# CONFIG
# =========================================================

PROTECTED_MODULES = {
    "modules",
}

EXPECTED_MODULES = [
    "modules",
    "games",
    "sorting",
    "stats",
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

MODULE_ALIASES = {
    "game": "games",
    "games": "games",
    "sorting": "sorting",
    "sort": "sorting",
    "stats": "stats",
    "stat": "stats",
    "welcome": "welcome",
    "welkom": "welcome",
    "react": "react",
    "reactroles": "react",
    "roles": "react",
    "modules": "modules",
    "module": "modules",
    "levels": "levels",
    "level": "levels",
    "xp": "levels",
    "voice": "voice",
    "voices": "voice",
    "events": "events",
    "event": "events",
    "suggestions": "suggestions",
    "suggestie": "suggestions",
    "suggesties": "suggestions",
    "changelog": "changelog",
    "health": "health",
    "botinfo": "botinfo",
    "actionlog": "actionlog",
    "log": "actionlog",
    "logs": "actionlog",
    "birthdays": "birthdays",
    "birthday": "birthdays",
    "verjaardagen": "birthdays",
    "reminders": "reminders",
    "reminder": "reminders",
    "lfg": "lfg",
    "lookingforgroup": "lfg",
    "looking-for-group": "lfg",
    "groepzoeken": "lfg",
}

PANEL_DATABASE = "adminpanel.db"
PANEL_KEY = "main"
PANEL_COLOR = discord.Color.from_rgb(108, 39, 218)
BACKUP_DIR = Path("backups")
DATABASE_FILES = [
    Path("levenloos.db"),
    Path("levels.db"),
    Path("birthdays.db"),
    Path("lfg.db"),
    Path(PANEL_DATABASE),
]
MAX_AUDIT_ROWS = 250
MAX_ERROR_ROWS = 100
ACTIVE_GAME_CATEGORY_ID = 940987098427707412
GAME_PROPOSAL_CHANNEL_ID = 940336215331319858
ARCHIVE_CATEGORY_ID = 1545088593716973568
ARCHIVE_RESTORE_CHANNEL_ID = 1545089501745913916


# =========================================================
# LEVENLOOS UI
# =========================================================

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
COLOR_EMOJI = "<:color:1547724074472575126>"

GAMES_EMOJI = "<:gamesbutton:1547854165097717801>"
EVENTS_EMOJI = "<:events:1547854148601643008>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"
VOICE_EMOJI = "<:voice:1547737205429243924>"
XP_EMOJI = "<:xp:1547737203789144136>"

# Admin Panel
BACKUP_EMOJI = "<:backup:1547910825002668142>"
RESTART_EMOJI = "<:restart:1547910025031327844>"
VPS_EMOJI = "<:vps:1547909976138453132>"
OWNER_EMOJI = "<:owner:1547909935495385219>"
TOOLS_EMOJI = "<:tools:1547909911994695740>"
RESTORE_EMOJI = "<:restore:1547909870337007676>"
DATABASE_EMOJI = "<:database:1547909723498487808>"
ERRORS_EMOJI = "<:errors:1547909699754532904>"
LOGS_EMOJI = "<:logs:1547909611833794631>"
SYSTEM_EMOJI = "<:systeem:1547909591923163156>"
DASHBOARD_EMOJI = "<:dashboard:1547909568187605114>"
MODULES_EMOJI = "<:modules:1547909513808580658>"

# Bestaande LEVENLOOS iconen die binnen Admin Panel hergebruikt worden
BOT_EMOJI = "<:bot:1547733042150514748>"
COMMANDS_EMOJI = "<:berichten:1547737207778058250>"

logger = logging.getLogger(__name__)


# =========================================================
# PERMISSIONS
# =========================================================

def management_access(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True

    if member.guild_permissions.administrator:
        return True

    role_names = {
        role.name.lower()
        for role in member.roles
    }

    return (
        "admin" in role_names
        or "owner" in role_names
    )


def owner_access(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True

    role_names = {
        role.name.lower()
        for role in member.roles
    }

    return "owner" in role_names


# =========================================================
# HELPERS
# =========================================================

def normalise_module_name(name: str) -> str:
    cleaned = (
        name
        .strip()
        .lower()
        .replace("cogs.", "")
        .replace(".py", "")
    )

    return MODULE_ALIASES.get(
        cleaned,
        cleaned
    )


def extension_name(module_name: str) -> str:
    return f"cogs.{module_name}"


def module_label(module_name: str) -> str:
    return MODULE_LABELS.get(
        module_name,
        module_name.title()
    )


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


def is_admin_interaction(interaction: discord.Interaction) -> bool:
    return (
        interaction.guild is not None
        and isinstance(interaction.user, discord.Member)
        and management_access(interaction.user)
    )


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


def clean_result_text(value: str) -> str:
    text = str(value or "").strip()
    for prefix in ("✅ ", "❌ ", "⚠️ ", "ℹ️ "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def trim_text(value: str, limit: int = 1200) -> str:
    value = str(value or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def feedback_style(kind: str) -> tuple[str, str, discord.Colour]:
    if kind == "success":
        return "Gelukt", SUCCESS_EMOJI, discord.Colour.from_rgb(87, 242, 135)
    if kind == "error":
        return "Fout", ERROR_EMOJI, discord.Colour.from_rgb(237, 66, 69)
    if kind == "warning":
        return "Let op", WARNING_EMOJI, discord.Colour.from_rgb(254, 231, 92)
    return "Informatie", INFO_EMOJI, PANEL_COLOR


# =========================================================
# COMPONENTS V2 - SHARED
# =========================================================

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


class OwnedLayoutView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        *,
        timeout: float = 300,
        owner_only_required: bool = False,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.owner_only_required = owner_only_required

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

        if not is_admin_interaction(interaction):
            await self.cog.send_feedback(
                interaction,
                "Je hebt geen toegang meer tot dit beheermenu.",
                kind="error",
                title="Geen toegang",
            )
            return False

        if self.owner_only_required:
            member = interaction.user
            if not isinstance(member, discord.Member) or not owner_access(member):
                await self.cog.send_feedback(
                    interaction,
                    "Dit onderdeel is alleen voor de Owner.",
                    kind="error",
                    title="Owner vereist",
                )
                return False

        return True


class GenericActionButton(discord.ui.Button):
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


# =========================================================
# MODULE MANAGER
# =========================================================

class ModuleSelectButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "ModulePanelView",
        module_name: str,
    ):
        self.owner_view = owner_view
        self.module_name = module_name
        loaded = extension_name(module_name) in owner_view.cog.bot.extensions

        if module_name in PROTECTED_MODULES:
            style = discord.ButtonStyle.secondary
            emoji = LOCK_EMOJI
        elif loaded:
            style = discord.ButtonStyle.success
            emoji = SUCCESS_EMOJI
        else:
            style = discord.ButtonStyle.secondary
            emoji = NONE_EMOJI

        super().__init__(
            label=module_label(module_name),
            emoji=ui_emoji(emoji),
            style=style,
            custom_id=f"module:select:{module_name}",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=ModuleActionView(
                self.owner_view.cog,
                self.owner_view.author_id,
                self.module_name,
            ),
        )


class ModulePanelView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(cog.panel_content())
        ]

        if notice:
            children.append(
                discord.ui.TextDisplay(
                    f"> └ {INFO_EMOJI} {trim_text(clean_result_text(notice), 500)}"
                )
            )

        children.append(
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.small,
            )
        )

        for index in range(0, len(EXPECTED_MODULES), 5):
            children.append(
                discord.ui.ActionRow(
                    *[
                        ModuleSelectButton(self, module_name)
                        for module_name in EXPECTED_MODULES[index:index + 5]
                    ]
                )
            )

        children.append(
            discord.ui.TextDisplay(
                f"-# {SUCCESS_EMOJI} geladen • {NONE_EMOJI} uit • {LOCK_EMOJI} beschermd"
            )
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=PANEL_COLOR,
            )
        )


class ModuleActionView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        module_name: str,
    ):
        super().__init__(cog, author_id, timeout=600)
        self.module_name = module_name
        loaded = extension_name(module_name) in cog.bot.extensions

        if module_name in PROTECTED_MODULES:
            icon = LOCK_EMOJI
            state = "Beschermd"
            description = (
                "Deze module kan niet vanuit Discord worden uitgeschakeld of herladen."
            )
        elif loaded:
            icon = SUCCESS_EMOJI
            state = "Geladen"
            description = "Kies hieronder wat je met deze module wilt doen."
        else:
            icon = NONE_EMOJI
            state = "Uitgeschakeld"
            description = "Je kunt deze module hieronder weer laden."

        buttons: list[discord.ui.Button] = []

        if module_name not in PROTECTED_MODULES and loaded:
            buttons.extend(
                [
                    GenericActionButton(
                        self,
                        "reload",
                        "Reload",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    GenericActionButton(
                        self,
                        "unload",
                        "Uitschakelen",
                        emoji=DELETE_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                ]
            )
        elif module_name not in PROTECTED_MODULES:
            buttons.append(
                GenericActionButton(
                    self,
                    "load",
                    "Laden",
                    emoji=ADD_EMOJI,
                    style=discord.ButtonStyle.success,
                )
            )

        buttons.append(
            GenericActionButton(
                self,
                "back",
                "Terug",
                emoji=BACK_EMOJI,
            )
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {icon} {module_label(module_name)}\n"
                    f"> └ Status: **{state}**\n"
                    f"> └ {description}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(*buttons),
                accent_colour=PANEL_COLOR,
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=ModulePanelView(self.cog, self.author_id),
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        if action == "load":
            success, message = await self.cog.load_module(self.module_name)
            audit_action = f"Module load: {self.module_name}"
        elif action == "unload":
            success, message = await self.cog.unload_module(self.module_name)
            audit_action = f"Module unload: {self.module_name}"
        elif action == "reload":
            success, message = await self.cog.reload_module(self.module_name)
            audit_action = f"Module reload: {self.module_name}"
        else:
            success, message = False, "Onbekende moduleactie."
            audit_action = f"Module actie: {self.module_name}"

        await self.cog.audit(interaction, audit_action, message, success)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=ModulePanelView(
                self.cog,
                self.author_id,
                notice=message,
            ),
        )


class ModuleListView(OwnedLayoutView):
    def __init__(self, cog: "Modules", author_id: int):
        super().__init__(cog, author_id, timeout=180)
        lines = [
            "# Modules",
            "> └ Overzicht van de verwachte LEVENLOOS-modules.",
            "",
        ]

        for name in EXPECTED_MODULES:
            loaded = extension_name(name) in cog.bot.extensions
            icon = LOCK_EMOJI if name in PROTECTED_MODULES else (SUCCESS_EMOJI if loaded else ERROR_EMOJI)
            state = "beschermd" if name in PROTECTED_MODULES else ("geladen" if loaded else "niet geladen")
            lines.append(f"> └ {icon} **{module_label(name)}** • {state}")

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("\n".join(lines)),
                accent_colour=PANEL_COLOR,
            )
        )


# =========================================================
# PERSISTENT ADMIN PANEL
# =========================================================

class AdminNavButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "AdminControlLayout",
        action: str,
        label: str,
        *,
        emoji: str | None,
        custom_id: str,
    ):
        super().__init__(
            label=label,
            emoji=ui_emoji(emoji),
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id,
        )
        self.owner_view = owner_view
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.handle(interaction, self.action)


class AdminControlLayout(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Modules",
        guild: discord.Guild | None = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog

        header = cog.main_panel_text(guild)
        if cog.bot.user is not None:
            header_item: discord.ui.Item = discord.ui.Section(
                discord.ui.TextDisplay(header),
                accessory=discord.ui.Thumbnail(
                    cog.bot.user.display_avatar.url,
                    description="LEVENLOOS Bot",
                ),
            )
        else:
            header_item = discord.ui.TextDisplay(header)

        self.add_item(
            discord.ui.Container(
                header_item,
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    "## Beheer\n"
                    "> └ Open hieronder een onderdeel. Submenu's verschijnen alleen voor jou."
                ),
                discord.ui.ActionRow(
                    AdminNavButton(self, "dashboard", "Dashboard", emoji=DASHBOARD_EMOJI, custom_id="levenloos:adminpanel:dashboard"),
                    AdminNavButton(self, "modules", "Modules", emoji=MODULES_EMOJI, custom_id="levenloos:adminpanel:modules"),
                    AdminNavButton(self, "system", "Systeem", emoji=SYSTEM_EMOJI, custom_id="levenloos:adminpanel:system"),
                    AdminNavButton(self, "diagnostics", "Diagnose", emoji=INFO_EMOJI, custom_id="levenloos:adminpanel:diagnostics"),
                ),
                discord.ui.ActionRow(
                    AdminNavButton(self, "logs", "Logs", emoji=LOGS_EMOJI, custom_id="levenloos:adminpanel:logs"),
                    AdminNavButton(self, "errors", "Errors", emoji=ERRORS_EMOJI, custom_id="levenloos:adminpanel:errors"),
                    AdminNavButton(self, "databases", "Database", emoji=DATABASE_EMOJI, custom_id="levenloos:adminpanel:databases"),
                    AdminNavButton(self, "tools", "Tools", emoji=TOOLS_EMOJI, custom_id="levenloos:adminpanel:tools"),
                ),
                discord.ui.ActionRow(
                    AdminNavButton(self, "reactroles", "React Roles", emoji=COLOR_EMOJI, custom_id="levenloos:adminpanel:reactroles"),
                    AdminNavButton(self, "refresh", "Refresh", emoji=REFRESH_EMOJI, custom_id="levenloos:adminpanel:refresh"),
                    AdminNavButton(self, "owner", "Owner", emoji=OWNER_EMOJI, custom_id="levenloos:adminpanel:owner"),
                ),
                discord.ui.TextDisplay(
                    "-# LEVENLOOS Admin Panel • persistent na botrestart"
                ),
                accent_colour=PANEL_COLOR,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_admin_interaction(interaction):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit controlepaneel is alleen voor Admins en de Owner.",
            kind="error",
            title="Geen toegang",
        )
        return False

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "dashboard":
            await interaction.response.send_message(
                view=DashboardView(self.cog, interaction.user.id, interaction.guild),
                ephemeral=True,
            )
            return

        if action == "modules":
            await interaction.response.send_message(
                view=ModulePanelView(self.cog, interaction.user.id),
                ephemeral=True,
            )
            return

        if action == "system":
            await interaction.response.send_message(
                view=SystemControlView(self.cog, interaction.user.id, interaction.guild),
                ephemeral=True,
            )
            return

        if action == "diagnostics":
            if interaction.guild is None:
                return
            await interaction.response.send_message(
                view=await DiagnosticsView.create(self.cog, interaction.user.id, interaction.guild),
                ephemeral=True,
            )
            return

        if action == "logs":
            await interaction.response.send_message(
                view=LogsView(self.cog, interaction.user.id),
                ephemeral=True,
            )
            return

        if action == "errors":
            await interaction.response.send_message(
                view=ErrorsView(self.cog, interaction.user.id),
                ephemeral=True,
            )
            return

        if action == "databases":
            await interaction.response.send_message(
                view=DatabaseView(self.cog, interaction.user.id),
                ephemeral=True,
            )
            return

        if action == "tools":
            await interaction.response.send_message(
                view=ToolsView(self.cog, interaction.user.id, interaction.guild),
                ephemeral=True,
            )
            return

        if action == "reactroles":
            await interaction.response.defer(ephemeral=True)
            react_cog = self.cog.bot.get_cog("ReactRoles")
            if react_cog is None or not hasattr(react_cog, "open_admin_control"):
                await interaction.edit_original_response(
                    content=None,
                    embed=None,
                    view=FeedbackView(
                        "React Roles-module is niet beschikbaar.",
                        kind="error",
                    ),
                )
                return
            try:
                await react_cog.open_admin_control(interaction)
            except Exception as exc:
                self.cog.record_error("react-admin-open", exc)
                logger.exception("React Roles-beheer openen mislukt.")
                await interaction.edit_original_response(
                    content=None,
                    embed=None,
                    view=FeedbackView(
                        "React Roles-beheer kon niet worden geopend.",
                        kind="error",
                    ),
                )
            return

        if action == "refresh":
            await interaction.response.defer(ephemeral=True, thinking=True)
            ok, message = await self.cog.refresh_saved_panel(
                guild=interaction.guild,
                recreate=False,
            )
            await self.cog.audit(interaction, "Panel refresh", message, ok)
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    clean_result_text(message),
                    kind="success" if ok else "error",
                    title="Admin Panel vernieuwd" if ok else "Refresh mislukt",
                ),
            )
            return

        if action == "owner":
            member = interaction.user
            if not isinstance(member, discord.Member) or not owner_access(member):
                await self.cog.send_feedback(
                    interaction,
                    "Dit onderdeel is alleen voor de Owner.",
                    kind="error",
                    title="Owner vereist",
                )
                return
            await interaction.response.send_message(
                view=OwnerControlView(self.cog, interaction.user.id),
                ephemeral=True,
            )


# =========================================================
# ADMIN SUBVIEWS
# =========================================================

class DashboardView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        guild: discord.Guild | None,
    ):
        super().__init__(cog, author_id, timeout=600)
        self.guild = guild
        body, accent = cog.dashboard_text(guild)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(body),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "refresh", "Vernieuwen", emoji=REFRESH_EMOJI, style=discord.ButtonStyle.primary)
                ),
                discord.ui.TextDisplay("-# Live gegevens • vernieuw met de knop"),
                accent_colour=accent,
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "refresh":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=DashboardView(self.cog, self.author_id, interaction.guild),
            )


class SystemControlView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        guild: discord.Guild | None,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)
        self.guild = guild
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(cog.system_text(guild))]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {INFO_EMOJI} {trim_text(clean_result_text(notice), 650)}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "sync", "Sync Commands", emoji=REFRESH_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "reload_all", "Reload All", emoji=REFRESH_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "fix", "Fix Bot", emoji=SUCCESS_EMOJI, style=discord.ButtonStyle.success),
                ),
                discord.ui.ActionRow(
                    GenericActionButton(self, "status", "Volgende Status", emoji=BOT_EMOJI),
                    GenericActionButton(self, "reactroles", "React Roles", emoji=COLOR_EMOJI),
                    GenericActionButton(self, "panel_refresh", "Panel Refresh", emoji=REFRESH_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=PANEL_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "reactroles":
            await interaction.response.defer(ephemeral=True)
            react_cog = self.cog.bot.get_cog("ReactRoles")
            if react_cog is None or not hasattr(react_cog, "open_admin_control"):
                await interaction.edit_original_response(
                    content=None,
                    embed=None,
                    view=FeedbackView("React Roles-module is niet beschikbaar.", kind="error"),
                )
                return
            try:
                await react_cog.open_admin_control(interaction)
            except Exception as exc:
                self.cog.record_error("react-admin-open", exc)
                logger.exception("React Roles-beheer openen mislukt.")
                await interaction.edit_original_response(
                    content=None,
                    embed=None,
                    view=FeedbackView("React Roles-beheer kon niet worden geopend.", kind="error"),
                )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ok = True

        if action == "sync":
            try:
                synced = await self.cog.bot.tree.sync()
                message = f"{len(synced)} globale slash commands gesynchroniseerd."
            except Exception as exc:
                self.cog.record_error("command-sync", exc)
                logger.exception("Command sync mislukt.")
                ok = False
                message = f"Command sync mislukt: {type(exc).__name__}: {exc}"
            audit_action = "Command sync"

        elif action == "reload_all":
            message = await self.cog.reload_all_modules()
            ok = "Fouten: `0`" in message
            audit_action = "Reload All"

        elif action == "fix":
            if interaction.guild is None:
                ok, message = False, "Server niet gevonden."
            else:
                message = await self.cog.run_auto_fix(interaction.guild)
                ok = "Problemen: `" not in message
            audit_action = "Auto Fix"

        elif action == "status":
            botinfo = self.cog.bot.get_cog("BotInfo")
            if botinfo is None or not hasattr(botinfo, "rotate_status"):
                ok, message = False, "De Bot Info-module is niet beschikbaar."
            else:
                try:
                    await botinfo.rotate_status()
                    message = "Botstatus doorgedraaid."
                except Exception as exc:
                    self.cog.record_error("status-rotate", exc)
                    logger.exception("Botstatus doordraaien mislukt.")
                    ok = False
                    message = f"Status kon niet worden aangepast: {type(exc).__name__}: {exc}"
            audit_action = "Volgende botstatus"

        elif action == "panel_refresh":
            if interaction.guild is None:
                ok, message = False, "Server niet gevonden."
            else:
                ok, message = await self.cog.refresh_saved_panel(interaction.guild, recreate=False)
            audit_action = "Panel refresh"

        else:
            ok, message, audit_action = False, "Onbekende systeemactie.", "Onbekende systeemactie"

        await self.cog.audit(interaction, audit_action, message, ok)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=SystemControlView(
                self.cog,
                self.author_id,
                interaction.guild,
                notice=message,
            ),
        )


class DiagnosticsView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        guild: discord.Guild,
        body: str,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)
        self.guild = guild
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(body)]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {INFO_EMOJI} {trim_text(clean_result_text(notice), 650)}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "rescan", "Opnieuw scannen", emoji=REFRESH_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "fix", "Auto Fix", emoji=SUCCESS_EMOJI, style=discord.ButtonStyle.success),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=PANEL_COLOR))

    @classmethod
    async def create(
        cls,
        cog: "Modules",
        author_id: int,
        guild: discord.Guild,
        *,
        notice: str | None = None,
    ):
        return cls(cog, author_id, guild, await cog.diagnostics_text(guild), notice=notice)

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "rescan":
            await interaction.response.defer(ephemeral=True, thinking=True)
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=await DiagnosticsView.create(self.cog, self.author_id, self.guild),
            )
            return

        if action == "fix":
            await interaction.response.defer(ephemeral=True, thinking=True)
            result = await self.cog.run_auto_fix(self.guild)
            ok = "Problemen: `" not in result
            await self.cog.audit(interaction, "Auto Fix", result, ok)
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=await DiagnosticsView.create(self.cog, self.author_id, self.guild, notice=result),
            )


class LogsView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(cog.logs_text())]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "refresh", "Vernieuwen", emoji=REFRESH_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "clear", "Wis logs", emoji=DELETE_EMOJI, style=discord.ButtonStyle.danger),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=PANEL_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "refresh":
            await interaction.response.edit_message(content=None, embed=None, view=LogsView(self.cog, self.author_id))
            return
        if action == "clear":
            await interaction.response.edit_message(content=None, embed=None, view=ClearLogsConfirmView(self.cog, self.author_id))


class ClearLogsConfirmView(OwnedLayoutView):
    def __init__(self, cog: "Modules", author_id: int):
        super().__init__(cog, author_id, timeout=60)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Auditlogs wissen\n"
                    "> └ Alle bewaarde Admin Panel-auditregels worden verwijderd.\n"
                    "> └ Deze actie kan niet worden teruggedraaid."
                ),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "confirm", "Wis logs", emoji=DELETE_EMOJI, style=discord.ButtonStyle.danger),
                    GenericActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(content=None, embed=None, view=LogsView(self.cog, self.author_id))
            return
        self.cog.clear_audit_logs()
        await self.cog.audit(interaction, "Auditlogs gewist", "Adminpanel auditlog opgeschoond", True)
        await interaction.response.edit_message(content=None, embed=None, view=LogsView(self.cog, self.author_id, notice="Auditlogs gewist."))


class ErrorsView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)
        open_count = cog.unresolved_error_count()
        accent = discord.Colour.from_rgb(237, 66, 69) if open_count else discord.Colour.from_rgb(87, 242, 135)
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(cog.errors_text())]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {SUCCESS_EMOJI} {notice}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "refresh", "Vernieuwen", emoji=REFRESH_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "resolve", "Markeer opgelost", emoji=SUCCESS_EMOJI, style=discord.ButtonStyle.success, disabled=open_count == 0),
                    GenericActionButton(self, "purge", "Wis opgelost", emoji=DELETE_EMOJI, style=discord.ButtonStyle.danger),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=accent))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "refresh":
            await interaction.response.edit_message(content=None, embed=None, view=ErrorsView(self.cog, self.author_id))
            return
        if action == "resolve":
            count = self.cog.resolve_errors()
            await self.cog.audit(interaction, "Errors opgelost", f"{count} errors gemarkeerd als opgelost", True)
            await interaction.response.edit_message(content=None, embed=None, view=ErrorsView(self.cog, self.author_id, notice=f"{count} error(s) gemarkeerd als opgelost."))
            return
        if action == "purge":
            await interaction.response.edit_message(content=None, embed=None, view=PurgeErrorsConfirmView(self.cog, self.author_id))


class PurgeErrorsConfirmView(OwnedLayoutView):
    def __init__(self, cog: "Modules", author_id: int):
        super().__init__(cog, author_id, timeout=60)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Opgeloste errors wissen\n"
                    "> └ Alle als opgelost gemarkeerde errors worden permanent verwijderd."
                ),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "confirm", "Wis opgelost", emoji=DELETE_EMOJI, style=discord.ButtonStyle.danger),
                    GenericActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(content=None, embed=None, view=ErrorsView(self.cog, self.author_id))
            return
        count = self.cog.purge_resolved_errors()
        await self.cog.audit(interaction, "Opgeloste errors gewist", f"{count} regels verwijderd", True)
        await interaction.response.edit_message(content=None, embed=None, view=ErrorsView(self.cog, self.author_id, notice=f"{count} opgeloste error(s) verwijderd."))


class DatabaseView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(cog.database_text())]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {INFO_EMOJI} {trim_text(clean_result_text(notice), 550)}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "integrity", "Integrity Check", emoji=INFO_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "backup", "Backup maken", emoji=BACKUP_EMOJI, style=discord.ButtonStyle.success),
                    GenericActionButton(self, "backups", "Backups", emoji=BACKUP_EMOJI),
                    GenericActionButton(self, "refresh", "Vernieuwen", emoji=REFRESH_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=PANEL_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "refresh":
            await interaction.response.edit_message(content=None, embed=None, view=DatabaseView(self.cog, self.author_id))
            return
        if action == "backups":
            await interaction.response.edit_message(content=None, embed=None, view=BackupsView(self.cog, self.author_id))
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        if action == "integrity":
            result = await asyncio.to_thread(self.cog.database_integrity_report)
            ok = "fout" not in result.casefold() and "ontbreekt" not in result.casefold()
            await self.cog.audit(interaction, "Database integrity check", result, ok)
            message = result
        elif action == "backup":
            try:
                path = await asyncio.to_thread(self.cog.create_backup)
                message = f"Backup gemaakt: `{path.name}` • `{path.stat().st_size / 1024:.1f} KB`"
                ok = True
                await self.cog.audit(interaction, "Backup gemaakt", str(path), True)
            except Exception as exc:
                self.cog.record_error("backup", exc)
                logger.exception("Backup maken mislukt.")
                message = f"Backup mislukt: {type(exc).__name__}: {exc}"
                ok = False
                await self.cog.audit(interaction, "Backup mislukt", str(exc), False)
        else:
            message, ok = "Onbekende databaseactie.", False

        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=DatabaseView(self.cog, self.author_id, notice=message),
        )


class BackupsView(OwnedLayoutView):
    def __init__(self, cog: "Modules", author_id: int):
        super().__init__(cog, author_id, timeout=300)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(cog.backups_text()),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "back", "Terug", emoji=BACK_EMOJI)
                ),
                accent_colour=PANEL_COLOR,
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(content=None, embed=None, view=DatabaseView(self.cog, self.author_id))


class ToolsView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        guild: discord.Guild | None,
        *,
        notice: str | None = None,
    ):
        super().__init__(cog, author_id, timeout=600)
        self.guild = guild
        children: list[discord.ui.Item] = [discord.ui.TextDisplay(cog.tools_text())]
        if notice:
            children.append(discord.ui.TextDisplay(f"> └ {INFO_EMOJI} {trim_text(clean_result_text(notice), 650)}"))
        children.extend(
            [
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "games", "Games sorteren", emoji=GAMES_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "react", "React Roles refresh", emoji=COLOR_EMOJI, style=discord.ButtonStyle.primary),
                    GenericActionButton(self, "stats", "Stats refresh", emoji=REFRESH_EMOJI),
                ),
                discord.ui.ActionRow(
                    GenericActionButton(self, "events", "Events refresh", emoji=EVENTS_EMOJI),
                    GenericActionButton(self, "voice", "Voice cleanup", emoji=VOICE_EMOJI),
                    GenericActionButton(self, "levels", "Level roles sync", emoji=XP_EMOJI),
                ),
            ]
        )
        self.add_item(discord.ui.Container(*children, accent_colour=PANEL_COLOR))

    async def handle(self, interaction: discord.Interaction, action: str):
        if self.guild is None:
            await self.cog.send_feedback(interaction, "Server niet gevonden.", kind="error")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        if action == "games":
            ok, message = await self.cog.repair_game_sorting(self.guild)
            audit_action = "Games sorteren"
        elif action == "react":
            ok, message = await self.cog.refresh_react_roles(self.guild)
            audit_action = "React Roles refresh"
        elif action == "stats":
            ok, message = await self.cog.refresh_stats(self.guild)
            audit_action = "Stats refresh"
        elif action == "events":
            ok, message = await self.cog.refresh_events(self.guild)
            audit_action = "Events refresh"
        elif action == "voice":
            ok, message = await self.cog.cleanup_event_voice(self.guild)
            audit_action = "Voice cleanup"
        elif action == "levels":
            ok, message = await self.cog.sync_level_roles(self.guild)
            audit_action = "Level roles sync"
        else:
            ok, message, audit_action = False, "Onbekende toolactie.", "Onbekende toolactie"

        await self.cog.audit(interaction, audit_action, message, ok)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=ToolsView(self.cog, self.author_id, self.guild, notice=message),
        )


class OwnerControlView(OwnedLayoutView):
    def __init__(self, cog: "Modules", author_id: int):
        super().__init__(cog, author_id, timeout=300, owner_only_required=True)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(cog.owner_text()),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "restart", "Herstart Bot", emoji=RESTART_EMOJI, style=discord.ButtonStyle.danger),
                    GenericActionButton(self, "restore", "Backup Restore", emoji=RESTORE_EMOJI, style=discord.ButtonStyle.danger),
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "restart":
            await interaction.response.edit_message(content=None, embed=None, view=RestartConfirmView(self.cog, self.author_id))
            return
        if action == "restore":
            await interaction.response.edit_message(content=None, embed=None, view=BackupRestorePicker(self.cog, self.author_id))


class RestartConfirmView(OwnedLayoutView):
    def __init__(self, cog: "Modules", author_id: int):
        super().__init__(cog, author_id, timeout=60, owner_only_required=True)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Bot herstarten\n"
                    "> └ Het volledige Python-proces wordt opnieuw gestart.\n"
                    "> └ Gebruik dit alleen wanneer een module-reload niet voldoende is."
                ),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "confirm", "Ja, herstart", emoji=RESTART_EMOJI, style=discord.ButtonStyle.danger),
                    GenericActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(content=None, embed=None, view=OwnerControlView(self.cog, self.author_id))
            return

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=FeedbackView(
                "De bot wordt opnieuw gestart. Discord kan enkele seconden nodig hebben voordat alles weer online is.",
                kind="warning",
                title="Bot wordt herstart",
            ),
        )
        await asyncio.sleep(1.5)
        os.execl(sys.executable, sys.executable, *sys.argv)


class BackupRestoreSelect(discord.ui.Select):
    def __init__(self, owner_view: "BackupRestorePicker"):
        self.owner_view = owner_view
        backups = owner_view.cog.list_backups()[:25]
        options = [
            discord.SelectOption(
                label=path.name[:100],
                value=path.name,
                description=f"{path.stat().st_size / 1024:.1f} KB",
            )
            for path in backups
        ] or [discord.SelectOption(label="Geen backups", value="__none__")]

        super().__init__(
            placeholder="Kies een backup om te herstellen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        filename = self.values[0]
        if filename == "__none__":
            await self.owner_view.cog.send_feedback(
                interaction,
                "Er zijn geen backups beschikbaar.",
                kind="info",
            )
            return

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=BackupRestoreConfirmView(
                self.owner_view.cog,
                self.owner_view.author_id,
                filename,
            ),
        )


class BackupRestorePicker(OwnedLayoutView):
    def __init__(self, cog: "Modules", author_id: int):
        super().__init__(cog, author_id, timeout=180, owner_only_required=True)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "# Backup Restore\n"
                    "> └ Kies de databasebackup die je wilt herstellen.\n"
                    f"> └ {WARNING_EMOJI} Restore overschrijft de huidige databasebestanden."
                ),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(BackupRestoreSelect(self)),
                discord.ui.ActionRow(
                    GenericActionButton(self, "back", "Terug", emoji=BACK_EMOJI)
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(content=None, embed=None, view=OwnerControlView(self.cog, self.author_id))


class BackupRestoreConfirmView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Modules",
        author_id: int,
        filename: str,
    ):
        super().__init__(cog, author_id, timeout=60, owner_only_required=True)
        self.filename = Path(filename).name
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Backup herstellen\n"
                    f"> └ Backup: `{self.filename}`\n"
                    "> └ De huidige databasebestanden worden overschreven.\n"
                    "> └ Er wordt eerst automatisch een veiligheidsbackup gemaakt."
                ),
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
                discord.ui.ActionRow(
                    GenericActionButton(self, "confirm", "Ja, restore", emoji=RESTORE_EMOJI, style=discord.ButtonStyle.danger),
                    GenericActionButton(self, "back", "Terug", emoji=BACK_EMOJI),
                ),
                accent_colour=discord.Colour.from_rgb(237, 66, 69),
            )
        )

    async def handle(self, interaction: discord.Interaction, action: str):
        if action == "back":
            await interaction.response.edit_message(content=None, embed=None, view=BackupRestorePicker(self.cog, self.author_id))
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await asyncio.to_thread(self.cog.restore_backup, self.filename)
            await self.cog.audit(interaction, "Backup hersteld", self.filename, True)
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    "Backup hersteld. Herstart de bot zodat alle modules de herstelde databases opnieuw openen.",
                    kind="success",
                    title="Backup hersteld",
                ),
            )
        except Exception as exc:
            self.cog.record_error("restore", exc)
            logger.exception("Backup restore mislukt.")
            await self.cog.audit(interaction, "Backup restore mislukt", str(exc), False)
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    f"Restore mislukt: {type(exc).__name__}: {exc}",
                    kind="error",
                ),
            )

# =========================================================
# MODULE COG
# =========================================================

class Modules(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self._persistent_view_registered = False
        self._panel_refresh_task: asyncio.Task | None = None

    # =====================================================
    # GROUPS
    # =====================================================

    module = app_commands.Group(
        name="module",
        description="Beheer de modules van LEVENLOOS.",
    )

    adminpanel = app_commands.Group(
        name="adminpanel",
        description="Beheer het permanente LEVENLOOS adminpaneel.",
    )

    # =====================================================
    # LIFECYCLE
    # =====================================================

    async def cog_load(self):
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Modules vereist discord.py 2.6+ voor Components V2."
            )

        self.init_panel_database()

        if not self._persistent_view_registered:
            self.bot.add_view(AdminControlLayout(self))
            self._persistent_view_registered = True

        asyncio.create_task(self.restore_panel_after_startup())

        if self._panel_refresh_task is None or self._panel_refresh_task.done():
            self._panel_refresh_task = asyncio.create_task(self.panel_refresh_loop())

        logger.info("Modulemanager + persistent Admin Panel geladen.")

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
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.response.send_message(view=view, ephemeral=True)

    def cog_unload(self):
        if self._panel_refresh_task is not None:
            self._panel_refresh_task.cancel()

    async def panel_refresh_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await asyncio.sleep(300)
                location = self.get_panel_location()
                if location is None:
                    continue
                guild = self.bot.get_guild(location[0])
                if guild is not None:
                    await self.refresh_saved_panel(guild, recreate=False)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.record_error("panel-auto-refresh", exc)
                await asyncio.sleep(60)

    # =====================================================
    # ACCESS
    # =====================================================

    async def check_access(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return False

        member = interaction.user

        if not isinstance(
            member,
            discord.Member,
        ):
            return False

        if not management_access(member):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return False

        return True

    # =====================================================
    # PANEL DATABASE
    # =====================================================

    def init_panel_database(self):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(PANEL_DATABASE) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=5000")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_panel (
                    panel_key TEXT PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    guild_id INTEGER,
                    user_id INTEGER,
                    user_name TEXT,
                    action TEXT NOT NULL,
                    detail TEXT,
                    success INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    traceback TEXT,
                    resolved INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit(created_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_errors_resolved ON admin_errors(resolved, id DESC)"
            )
            db.commit()

    def save_panel_location(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ):
        with sqlite3.connect(PANEL_DATABASE) as db:
            db.execute(
                """
                INSERT INTO admin_panel (
                    panel_key,
                    guild_id,
                    channel_id,
                    message_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(panel_key) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id,
                    updated_at = excluded.updated_at
                """,
                (
                    PANEL_KEY,
                    guild_id,
                    channel_id,
                    message_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            db.commit()

    def get_panel_location(
        self,
    ) -> tuple[int, int, int] | None:
        with sqlite3.connect(PANEL_DATABASE) as db:
            row = db.execute(
                """
                SELECT guild_id, channel_id, message_id
                FROM admin_panel
                WHERE panel_key = ?
                """,
                (PANEL_KEY,),
            ).fetchone()

        if row is None:
            return None

        return (
            int(row[0]),
            int(row[1]),
            int(row[2]),
        )


    # =====================================================
    # AUDIT / ERRORS
    # =====================================================

    async def audit(
        self,
        interaction: discord.Interaction | None,
        action: str,
        detail: str = "",
        success: bool = True,
    ):
        guild_id = interaction.guild.id if interaction and interaction.guild else None
        user_id = interaction.user.id if interaction else None
        user_name = str(interaction.user) if interaction else "System"

        with sqlite3.connect(PANEL_DATABASE) as db:
            db.execute(
                """
                INSERT INTO admin_audit (
                    created_at, guild_id, user_id, user_name, action, detail, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    guild_id,
                    user_id,
                    user_name,
                    action[:120],
                    str(detail)[:1500],
                    1 if success else 0,
                ),
            )
            db.execute(
                "DELETE FROM admin_audit WHERE id NOT IN (SELECT id FROM admin_audit ORDER BY id DESC LIMIT ?)",
                (MAX_AUDIT_ROWS,),
            )
            db.commit()

        if interaction and interaction.guild:
            actionlog = self.bot.get_cog("Actionlog")
            if actionlog is not None and hasattr(actionlog, "send_log"):
                try:
                    icon = "✅" if success else "❌"
                    await actionlog.send_log(
                        interaction.guild,
                        f"{icon} Admin Panel • {action}",
                        description=(
                            f"**Door:** {interaction.user.mention}\n"
                            f"**Resultaat:** {'Gelukt' if success else 'Mislukt'}\n"
                            f"**Details:** {str(detail)[:1200] or '—'}"
                        ),
                        colour=discord.Color.green() if success else discord.Color.red(),
                    )
                except Exception:
                    pass

    def record_error(self, source: str, error: BaseException | str):
        if isinstance(error, BaseException):
            error_type = type(error).__name__
            message = str(error)
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            error_type = "Error"
            message = str(error)
            tb = ""

        with sqlite3.connect(PANEL_DATABASE) as db:
            db.execute(
                """
                INSERT INTO admin_errors (
                    created_at, source, error_type, message, traceback, resolved
                ) VALUES (?, ?, ?, ?, ?, 0)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    source[:120],
                    error_type[:120],
                    message[:1500],
                    tb[-8000:],
                ),
            )
            db.execute(
                "DELETE FROM admin_errors WHERE id NOT IN (SELECT id FROM admin_errors ORDER BY id DESC LIMIT ?)",
                (MAX_ERROR_ROWS,),
            )
            db.commit()

    def clear_audit_logs(self):
        with sqlite3.connect(PANEL_DATABASE) as db:
            db.execute("DELETE FROM admin_audit")
            db.commit()

    def resolve_errors(self) -> int:
        with sqlite3.connect(PANEL_DATABASE) as db:
            cur = db.execute("UPDATE admin_errors SET resolved = 1 WHERE resolved = 0")
            db.commit()
            return max(0, cur.rowcount)

    def purge_resolved_errors(self) -> int:
        with sqlite3.connect(PANEL_DATABASE) as db:
            cur = db.execute("DELETE FROM admin_errors WHERE resolved = 1")
            db.commit()
            return max(0, cur.rowcount)

    def unresolved_error_count(self) -> int:
        with sqlite3.connect(PANEL_DATABASE) as db:
            row = db.execute("SELECT COUNT(*) FROM admin_errors WHERE resolved = 0").fetchone()
        return int(row[0] if row else 0)

    # =====================================================
    # RESOURCE / DASHBOARD DATA
    # =====================================================

    def process_memory_mb(self) -> float:
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024
        except Exception:
            pass
        try:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return rss / 1024
        except Exception:
            return 0.0

    def system_memory(self) -> tuple[float, float, float]:
        total = available = 0
        try:
            values = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    key, value = line.split(":", 1)
                    values[key] = int(value.strip().split()[0])
            total = values.get("MemTotal", 0) / 1024
            available = values.get("MemAvailable", 0) / 1024
        except Exception:
            return 0.0, 0.0, 0.0
        used = max(0.0, total - available)
        pct = (used / total * 100) if total else 0.0
        return total, used, pct

    def disk_usage(self) -> tuple[float, float, float]:
        try:
            usage = shutil.disk_usage(".")
            total = usage.total / (1024 ** 3)
            used = usage.used / (1024 ** 3)
            pct = (usage.used / usage.total * 100) if usage.total else 0.0
            return total, used, pct
        except Exception:
            return 0.0, 0.0, 0.0

    def task_count(self) -> int:
        try:
            return len([task for task in asyncio.all_tasks() if not task.done()])
        except Exception:
            return 0

    def dashboard_text(
        self,
        guild: discord.Guild | None,
    ) -> tuple[str, discord.Colour]:
        loaded = sum(
            1
            for name in EXPECTED_MODULES
            if extension_name(name) in self.bot.extensions
        )
        missing = len(EXPECTED_MODULES) - loaded
        errors = self.unresolved_error_count()
        total_ram, used_ram, ram_pct = self.system_memory()
        disk_total, disk_used, disk_pct = self.disk_usage()
        db_ok = sum(1 for path in DATABASE_FILES if path.exists())
        health = max(0, 100 - (missing * 7) - min(errors * 5, 35))
        latency = self.bot.latency
        ping = round(latency * 1000) if isinstance(latency, (int, float)) and math.isfinite(latency) else 0
        if ping > 500:
            health = max(0, health - 10)

        if health >= 95:
            icon = SUCCESS_EMOJI
            accent = discord.Colour.from_rgb(87, 242, 135)
        elif health >= 75:
            icon = WARNING_EMOJI
            accent = discord.Colour.from_rgb(254, 231, 92)
        else:
            icon = ERROR_EMOJI
            accent = discord.Colour.from_rgb(237, 66, 69)

        if guild is not None:
            members = guild.member_count or len(guild.members)
            channels = len(guild.channels)
            voice_active = sum(
                1
                for channel in guild.voice_channels
                for member in channel.members
                if not member.bot
            )
        else:
            members = channels = voice_active = "—"

        load_text = (
            ", ".join(f"{value:.2f}" for value in os.getloadavg())
            if hasattr(os, "getloadavg")
            else "n/a"
        )

        text = (
            f"# {DASHBOARD_EMOJI} Live Dashboard\n"
            f"> └ System health: **{health}%**\n"
            f"> └ Modules: **{loaded}/{len(EXPECTED_MODULES)}** • Commands: **{self.command_count()}** • Ping: **{ping} ms**\n"
            f"> └ Onopgeloste errors: **{errors}**\n\n"
            f"## {BOT_EMOJI} Proces\n"
            f"> └ Uptime: `{format_duration(self.uptime_seconds())}`\n"
            f"> └ RAM bot: `{self.process_memory_mb():.1f} MB`\n"
            f"> └ Async tasks: `{self.task_count()}` • Python: `{sys.version.split()[0]}`\n\n"
            f"## {VPS_EMOJI} VPS\n"
            f"> └ RAM: `{used_ram:.0f}/{total_ram:.0f} MB` ({ram_pct:.0f}%)\n"
            f"> └ Disk: `{disk_used:.1f}/{disk_total:.1f} GB` ({disk_pct:.0f}%)\n"
            f"> └ Load: `{load_text}`\n\n"
            "## Discord\n"
            f"> └ Leden: `{members}` • Channels: `{channels}` • Voice: `{voice_active}`\n"
            f"> └ Guilds: `{len(self.bot.guilds)}`\n\n"
            f"## {DATABASE_EMOJI} Opslag\n"
            f"> └ Databases: `{db_ok}/{len(DATABASE_FILES)}` aanwezig • Backups: `{len(self.list_backups())}`"
        )
        return text, accent

    def logs_text(self) -> str:
        with sqlite3.connect(PANEL_DATABASE) as db:
            rows = db.execute(
                "SELECT created_at, user_name, action, detail, success FROM admin_audit ORDER BY id DESC LIMIT 12"
            ).fetchall()

        lines = [f"# {LOGS_EMOJI} Admin Audit Log", "> └ Laatste beheeracties uit het centrale adminpaneel.", ""]
        if not rows:
            lines.append("> └ Nog geen adminpanel-acties gelogd.")
        else:
            for created_at, user_name, action, detail, success in rows:
                try:
                    dt = datetime.fromisoformat(created_at)
                    stamp = f"<t:{int(dt.timestamp())}:R>"
                except Exception:
                    stamp = "onbekend"
                icon = SUCCESS_EMOJI if success else ERROR_EMOJI
                detail = trim_text((detail or "").replace("\n", " "), 120)
                lines.append(f"### {icon} {action}")
                lines.append(f"> └ {stamp} • `{user_name}`")
                lines.append(f"> └ {detail or '—'}")
        lines.append(f"\n-# Laatste {len(rows)} acties • maximaal {MAX_AUDIT_ROWS} bewaard")
        return "\n".join(lines)

    def errors_text(self) -> str:
        with sqlite3.connect(PANEL_DATABASE) as db:
            rows = db.execute(
                "SELECT id, created_at, source, error_type, message, resolved FROM admin_errors ORDER BY id DESC LIMIT 10"
            ).fetchall()

        total_open = self.unresolved_error_count()
        icon = ERROR_EMOJI if total_open else SUCCESS_EMOJI
        lines = [
            f"# {ERRORS_EMOJI} Error Center • {total_open} open",
            "> └ Panel- en modulefouten worden hier centraal bijgehouden.",
            "",
        ]

        if not rows:
            lines.append("> └ Geen errors geregistreerd.")
        else:
            for error_id, created_at, source, error_type, message, resolved in rows:
                item_icon = SUCCESS_EMOJI if resolved else ERROR_EMOJI
                try:
                    dt = datetime.fromisoformat(created_at)
                    stamp = f"<t:{int(dt.timestamp())}:R>"
                except Exception:
                    stamp = "onbekend"
                msg = trim_text((message or "").replace("\n", " "), 155)
                lines.append(f"### {item_icon} #{error_id} • {source}")
                lines.append(f"> └ {stamp} • `{error_type}`")
                lines.append(f"> └ {msg or '—'}")
        return "\n".join(lines)

    # =====================================================
    # DATABASE / BACKUP CENTER
    # =====================================================

    def database_status_rows(self) -> list[tuple[Path, str, float]]:
        rows = []
        for path in DATABASE_FILES:
            if not path.exists():
                rows.append((path, "⚫ ontbreekt", 0.0))
                continue
            size = path.stat().st_size / 1024
            try:
                with sqlite3.connect(path) as db:
                    result = db.execute("PRAGMA quick_check").fetchone()
                status = "🟢 OK" if result and result[0] == "ok" else "🔴 fout"
            except Exception:
                status = "🔴 fout"
            rows.append((path, status, size))
        return rows

    def database_text(self) -> str:
        rows = self.database_status_rows()
        lines = [
            f"# {DATABASE_EMOJI} Database Center",
            "> └ Controleer databases, maak backups en voer integrity checks uit.",
            "",
            f"## {DATABASE_EMOJI} Databases",
        ]
        for path, status, size in rows:
            lines.append(f"> └ **{path.name}** • {status} • `{size:.1f} KB`")
        lines.extend(
            [
                "",
                f"## {BACKUP_EMOJI} Backups",
                f"> └ Aantal: **{len(self.list_backups())}**",
                f"> └ Map: `{BACKUP_DIR}`",
                "> └ Backups bevatten alle aanwezige LEVENLOOS `.db`-bestanden.",
                "",
                "-# Restore is Owner-only en vraagt altijd om bevestiging.",
            ]
        )
        return "\n".join(lines)

    def database_integrity_report(self) -> str:
        lines = [f"{INFO_EMOJI} **DATABASE INTEGRITY CHECK**"]
        for path, status, size in self.database_status_rows():
            lines.append(f"> {status} `{path.name}` · {size:.1f} KB")
        return "\n".join(lines)

    def create_backup(self) -> Path:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = BACKUP_DIR / f"levenloos-backup-{stamp}.zip"
        existing = [p for p in DATABASE_FILES if p.exists()]
        if not existing:
            raise RuntimeError("Geen databasebestanden gevonden om te back-uppen.")
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in existing:
                # SQLite online backup gives a consistent copy even while the bot is running.
                temp = BACKUP_DIR / f".__backup_{path.name}"
                try:
                    with sqlite3.connect(path) as src, sqlite3.connect(temp) as dst:
                        src.backup(dst)
                    zf.write(temp, arcname=path.name)
                finally:
                    if temp.exists():
                        temp.unlink()
        return output

    def list_backups(self) -> list[Path]:
        if not BACKUP_DIR.exists():
            return []
        return sorted(BACKUP_DIR.glob("levenloos-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)

    def backups_text(self) -> str:
        backups = self.list_backups()[:15]
        lines = ["# Database Backups", "> └ Laatste lokale databasebackups.", ""]
        if not backups:
            lines.append("> └ Nog geen backups gemaakt.")
        else:
            for path in backups:
                ts = int(path.stat().st_mtime)
                lines.append(
                    f"> └ `{path.name}` • `{path.stat().st_size / 1024:.1f} KB` • <t:{ts}:R>"
                )
        return "\n".join(lines)

    def restore_backup(self, filename: str):
        safe_name = Path(filename).name
        path = BACKUP_DIR / safe_name
        if (
            not path.exists()
            or path.parent.resolve() != BACKUP_DIR.resolve()
            or not safe_name.startswith("levenloos-backup-")
            or path.suffix.lower() != ".zip"
            or not zipfile.is_zipfile(path)
        ):
            raise FileNotFoundError("Geldige backup niet gevonden.")
        safety = self.create_backup()
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            allowed = {p.name for p in DATABASE_FILES}
            if not names or not names.issubset(allowed):
                raise RuntimeError("Backup bevat onverwachte bestanden.")
            for name in names:
                data = zf.read(name)
                temp = Path(f".{name}.restore")
                temp.write_bytes(data)
                # Verify before replacing the live file.
                with sqlite3.connect(temp) as db:
                    result = db.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    temp.unlink(missing_ok=True)
                    raise RuntimeError(f"{name} faalde integrity check.")
                os.replace(temp, Path(name))
        return safety

    # =====================================================
    # BOT TOOLS
    # =====================================================

    def tools_text(self) -> str:
        def loaded(name: str) -> str:
            return SUCCESS_EMOJI if self.bot.get_cog(name) is not None else NONE_EMOJI

        return (
            f"# {TOOLS_EMOJI} Bot Tools\n"
            "> └ Directe onderhoudsacties voor de belangrijkste LEVENLOOS-systemen.\n\n"
            "## Beschikbaarheid\n"
            f"> └ {loaded('Sorting')} Games sortering\n"
            f"> └ {loaded('ReactRoles')} React Roles\n"
            f"> └ {loaded('Stats')} Stats\n"
            f"> └ {loaded('Events')} Events\n"
            f"> └ {loaded('Levels')} Levels\n\n"
            f"## {TOOLS_EMOJI} Acties\n"
            f"> └ {GAMES_EMOJI} Herstel de alfabetische gamevolgorde.\n"
            f"> └ {COLOR_EMOJI} Bouw het React Roles-menu opnieuw op.\n"
            f"> └ {EVENTS_EMOJI} Vernieuw actieve eventdashboards.\n"
            f"> └ {VOICE_EMOJI} Ruim lege/verlopen event-voicekanalen op.\n"
            f"> └ {XP_EMOJI} Synchroniseer levelrollen voor alle leden."
        )

    async def repair_game_sorting(self, guild: discord.Guild) -> tuple[bool, str]:
        try:
            from cogs.sorting import repair_category_sort
            active = guild.get_channel(ACTIVE_GAME_CATEGORY_ID)
            archive = guild.get_channel(ARCHIVE_CATEGORY_ID)
            changed = 0
            if isinstance(active, discord.CategoryChannel):
                changed += await repair_category_sort(active, GAME_PROPOSAL_CHANNEL_ID)
            if isinstance(archive, discord.CategoryChannel):
                changed += await repair_category_sort(archive, ARCHIVE_RESTORE_CHANNEL_ID)
            return True, f"✅ Game-sortering hersteld. `{changed}` channelposities aangepast."
        except Exception as exc:
            self.record_error("games-sort", exc)
            return False, f"❌ Sortering mislukt: `{type(exc).__name__}: {exc}`"

    async def refresh_react_roles(self, guild: discord.Guild) -> tuple[bool, str]:
        cog = self.bot.get_cog("ReactRoles")
        if cog is None or not hasattr(cog, "refresh_main_message"):
            return False, "❌ React Roles-module is niet beschikbaar."
        try:
            message = await cog.refresh_main_message(guild)
            url = getattr(message, "jump_url", None)
            return True, f"✅ React Roles-menu vernieuwd.{f'\n{url}' if url else ''}"
        except Exception as exc:
            self.record_error("react-refresh", exc)
            return False, f"❌ React Roles refresh mislukt: `{type(exc).__name__}: {exc}`"

    async def refresh_stats(self, guild: discord.Guild) -> tuple[bool, str]:
        cog = self.bot.get_cog("Stats")
        if cog is None:
            return False, "❌ Stats-module is niet beschikbaar."
        try:
            done = 0
            if hasattr(cog, "update_members_channel"):
                await cog.update_members_channel(guild)
                done += 1
            if hasattr(cog, "update_date_channel"):
                await cog.update_date_channel(guild)
                done += 1
            if hasattr(cog, "update_rotating_channel"):
                await cog.update_rotating_channel(guild)
                done += 1
            return True, f"✅ Stats vernieuwd. `{done}` update-acties uitgevoerd."
        except Exception as exc:
            self.record_error("stats-refresh", exc)
            return False, f"❌ Stats refresh mislukt: `{type(exc).__name__}: {exc}`"

    async def refresh_events(self, guild: discord.Guild) -> tuple[bool, str]:
        cog = self.bot.get_cog("Events")
        if cog is None or not hasattr(cog, "fetchall"):
            return False, "❌ Events-module is niet beschikbaar."
        try:
            rows = await cog.fetchall(
                "SELECT id FROM events WHERE guild_id = ? AND status IN ('planning','confirmed','active')",
                (guild.id,),
            )
            ok = 0
            failed = 0
            for row in rows:
                try:
                    await cog.refresh_dashboard(int(row["id"]))
                    ok += 1
                except Exception as exc:
                    failed += 1
                    self.record_error(f"event-refresh#{row['id']}", exc)
            return failed == 0, f"{'✅' if failed == 0 else '⚠️'} Events vernieuwd: `{ok}` gelukt, `{failed}` fouten."
        except Exception as exc:
            self.record_error("events-refresh", exc)
            return False, f"❌ Events refresh mislukt: `{type(exc).__name__}: {exc}`"

    async def cleanup_event_voice(self, guild: discord.Guild) -> tuple[bool, str]:
        cog = self.bot.get_cog("Events")
        if cog is None or not hasattr(cog, "fetchall"):
            return False, "❌ Events-module is niet beschikbaar."
        try:
            rows = await cog.fetchall(
                "SELECT id FROM events WHERE guild_id = ? AND voice_channel_id IS NOT NULL",
                (guild.id,),
            )
            before = len(rows)
            for row in rows:
                await cog.cleanup_voice(int(row["id"]), force_if_empty=False)
            rows_after = await cog.fetchall(
                "SELECT id FROM events WHERE guild_id = ? AND voice_channel_id IS NOT NULL",
                (guild.id,),
            )
            removed = max(0, before - len(rows_after))
            return True, f"✅ Voice cleanup klaar. `{removed}` lege/verlopen eventchannels verwijderd."
        except Exception as exc:
            self.record_error("voice-cleanup", exc)
            return False, f"❌ Voice cleanup mislukt: `{type(exc).__name__}: {exc}`"

    async def sync_level_roles(self, guild: discord.Guild) -> tuple[bool, str]:
        cog = self.bot.get_cog("Levels")
        if cog is None or not hasattr(cog, "apply_level_roles"):
            return False, "❌ Levels-module is niet beschikbaar."
        try:
            done = 0
            failed = 0
            for member in guild.members:
                if member.bot:
                    continue
                try:
                    await cog.apply_level_roles(member)
                    done += 1
                except Exception as exc:
                    failed += 1
                    self.record_error(f"level-sync:{member.id}", exc)
            return failed == 0, f"{'✅' if failed == 0 else '⚠️'} Levelrollen gesynchroniseerd: `{done}` leden, `{failed}` fouten."
        except Exception as exc:
            self.record_error("level-sync", exc)
            return False, f"❌ Levelrol-sync mislukt: `{type(exc).__name__}: {exc}`"

    # =====================================================
    # PANEL CONTENT
    # =====================================================

    def panel_content(self) -> str:
        loaded_count = sum(
            1
            for name in EXPECTED_MODULES
            if extension_name(name) in self.bot.extensions
        )
        return (
            f"# {MODULES_EMOJI} Modules\n"
            f"> └ **{loaded_count}/{len(EXPECTED_MODULES)}** verwachte modules zijn geladen.\n"
            "> └ Kies hieronder een module om hem te bekijken of beheren."
        )

    def uptime_seconds(self) -> float:
        started_at = getattr(
            self.bot,
            "levenloos_started_at",
            None,
        )

        if started_at is None:
            return 0

        if started_at.tzinfo is None:
            started_at = started_at.replace(
                tzinfo=timezone.utc,
            )

        return (
            datetime.now(timezone.utc)
            - started_at
        ).total_seconds()

    def command_count(self) -> int:
        count = 0

        def walk(command):
            nonlocal count

            if isinstance(command, app_commands.Group):
                for child in command.commands:
                    walk(child)
            else:
                count += 1

        for root in self.bot.tree.get_commands():
            walk(root)

        return count

    def main_panel_text(self, guild: discord.Guild | None) -> str:
        loaded = [
            name
            for name in EXPECTED_MODULES
            if extension_name(name) in self.bot.extensions
        ]
        missing = [
            name
            for name in EXPECTED_MODULES
            if extension_name(name) not in self.bot.extensions
        ]
        latency = self.bot.latency
        ping = (
            round(latency * 1000)
            if isinstance(latency, (int, float)) and math.isfinite(latency)
            else "—"
        )
        if guild is not None:
            members = guild.member_count or len(guild.members)
            channels = len(guild.channels)
            voice = sum(
                1
                for channel in guild.voice_channels
                for member in channel.members
                if not member.bot
            )
        else:
            members = channels = voice = "—"

        status_icon = SUCCESS_EMOJI if not missing else WARNING_EMOJI
        status = "Systeem online" if not missing else f"{len(missing)} module(s) vragen aandacht"
        text = (
            f"# {SYSTEM_EMOJI} LEVENLOOS • ADMIN CONTROL\n"
            f"> └ {status_icon} **{status}**\n"
            "-# Privé beheeromgeving voor Admins en Owner\n\n"
            f"## {DASHBOARD_EMOJI} Overzicht\n"
            f"> └ Ping: `{ping} ms` • Uptime: `{format_duration(self.uptime_seconds())}`\n"
            f"> └ {COMMANDS_EMOJI} Commands: `{self.command_count()}` • {MODULES_EMOJI} Modules: `{len(loaded)}/{len(EXPECTED_MODULES)}`\n"
            f"> └ Leden: `{members}` • Channels: `{channels}` • Voice: `{voice}`"
        )
        if missing:
            text += "\n> └ Niet geladen: " + ", ".join(f"`{module_label(name)}`" for name in missing)
        return text

    def system_text(self, guild: discord.Guild | None) -> str:
        loaded_count = sum(
            1
            for name in EXPECTED_MODULES
            if extension_name(name) in self.bot.extensions
        )
        latency = self.bot.latency
        ping = (
            round(latency * 1000)
            if isinstance(latency, (int, float)) and math.isfinite(latency)
            else "—"
        )
        return (
            f"# {SYSTEM_EMOJI} Systeemcontrole\n"
            "> └ Onderhoud, herstel en commandbeheer vanuit één scherm.\n\n"
            f"## {SYSTEM_EMOJI} Status\n"
            f"> └ Modules: **{loaded_count}/{len(EXPECTED_MODULES)}**\n"
            f"> └ Commands: **{self.command_count()}** • Ping: **{ping} ms**\n\n"
            f"## {TOOLS_EMOJI} Acties\n"
            "> └ Sync Commands synchroniseert de globale slash commands.\n"
            "> └ Reload All herlaadt alle niet-beschermde geladen modules.\n"
            "> └ Fix Bot herstelt alleen veilige botonderdelen."
        )

    async def diagnostics_text(self, guild: discord.Guild) -> str:
        loaded = [
            name
            for name in EXPECTED_MODULES
            if extension_name(name) in self.bot.extensions
        ]
        missing = [
            name
            for name in EXPECTED_MODULES
            if extension_name(name) not in self.bot.extensions
        ]
        location = self.get_panel_location()
        panel_status = "Niet ingesteld"

        if location is not None:
            saved_guild_id, channel_id, message_id = location
            if saved_guild_id != guild.id:
                panel_status = "Op andere server opgeslagen"
            else:
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        await channel.fetch_message(message_id)
                        panel_status = "Bereikbaar"
                    except discord.NotFound:
                        panel_status = "Bericht ontbreekt"
                    except discord.Forbidden:
                        panel_status = "Geen toegang"
                    except discord.HTTPException:
                        panel_status = "Discord API-fout"
                else:
                    panel_status = "Channel ontbreekt"

        missing_text = ", ".join(f"`{module_label(name)}`" for name in missing) if missing else "Geen"
        return (
            f"# {INFO_EMOJI} Diagnose\n"
            "> └ Controleert modules, commands, verbinding en het permanente paneel.\n\n"
            f"## {MODULES_EMOJI} Modules\n"
            f"> └ Geladen: **{len(loaded)}** • Ontbrekend: **{len(missing)}**\n"
            f"> └ Niet geladen: {missing_text}\n\n"
            f"## {COMMANDS_EMOJI} Commands & verbinding\n"
            f"> └ Commands in tree: **{self.command_count()}**\n"
            f"> └ Gateway ping: **{round(self.bot.latency * 1000)} ms** • Guilds: **{len(self.bot.guilds)}**\n\n"
            f"## {VPS_EMOJI} Admin Panel\n"
            f"> └ Status: **{panel_status}**\n\n"
            "-# Auto Fix herstelt alleen veilige botonderdelen."
        )

    def owner_text(self) -> str:
        return (
            f"# {OWNER_EMOJI} Owner Control\n"
            "> └ Kritieke botacties die niet beschikbaar zijn voor gewone Admins.\n\n"
            f"## {RESTART_EMOJI} Volledige herstart\n"
            "> └ Start het huidige Python-proces opnieuw.\n"
            "> └ Gebruik dit wanneer een gewone module-reload niet genoeg is.\n\n"
            f"## {RESTORE_EMOJI} Backup Restore\n"
            "> └ Herstelt een databasebackup na een extra bevestiging.\n\n"
            f"-# {WARNING_EMOJI} Kritieke acties vragen altijd om bevestiging."
        )

    # =====================================================
    # PANEL MESSAGE MANAGEMENT
    # =====================================================

    async def restore_panel_after_startup(self):
        await self.bot.wait_until_ready()

        await asyncio.sleep(2)

        location = self.get_panel_location()

        if location is None:
            return

        guild_id, channel_id, message_id = location

        guild = self.bot.get_guild(
            guild_id,
        )

        if guild is None:
            return

        channel = guild.get_channel(
            channel_id,
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        try:
            message = await channel.fetch_message(
                message_id,
            )

            await message.edit(
                content=None,
                embeds=[],
                view=AdminControlLayout(
                    self,
                    guild,
                ),
            )

            logger.info(
                "Adminpaneel hersteld: %s/%s/%s",
                guild.id,
                channel.id,
                message.id,
            )

        except discord.NotFound:
            logger.warning(
                "Opgeslagen adminpaneelbericht bestaat niet meer. Gebruik /adminpanel fix."
            )
        except discord.Forbidden:
            logger.warning(
                "Geen toegang tot opgeslagen adminpaneelchannel."
            )
        except discord.HTTPException as exc:
            logger.warning(
                "Adminpaneel kon niet worden vernieuwd: %s",
                exc,
            )

    async def refresh_saved_panel(
        self,
        guild: discord.Guild,
        recreate: bool,
    ) -> tuple[bool, str]:
        location = self.get_panel_location()

        if location is None:
            return (
                False,
                "❌ Er is nog geen adminpaneel ingesteld. Gebruik `/adminpanel setup`.",
            )

        saved_guild_id, channel_id, message_id = location

        if saved_guild_id != guild.id:
            return (
                False,
                "❌ Het opgeslagen adminpaneel hoort bij een andere server.",
            )

        channel = guild.get_channel(
            channel_id,
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return (
                False,
                "❌ Het opgeslagen adminpanel-channel bestaat niet meer.",
            )

        try:
            message = await channel.fetch_message(
                message_id,
            )

            await message.edit(
                content=None,
                embeds=[],
                view=AdminControlLayout(
                    self,
                    guild,
                ),
            )

            return (
                True,
                f"✅ Adminpaneel vernieuwd in {channel.mention}.",
            )

        except discord.NotFound:
            if not recreate:
                return (
                    False,
                    "❌ Het paneelbericht bestaat niet meer. Gebruik `/adminpanel fix`.",
                )

            try:
                message = await channel.send(
                    view=AdminControlLayout(
                        self,
                        guild,
                    ),
                )

                self.save_panel_location(
                    guild.id,
                    channel.id,
                    message.id,
                )

                return (
                    True,
                    f"✅ Paneelbericht opnieuw aangemaakt in {channel.mention}.",
                )
            except discord.HTTPException as exc:
                return (
                    False,
                    f"❌ Paneel kon niet opnieuw worden aangemaakt: `{exc}`",
                )

        except discord.Forbidden:
            return (
                False,
                "❌ Ik heb geen toegang om het adminpaneel te bewerken.",
            )
        except discord.HTTPException as exc:
            return (
                False,
                f"❌ Panel refresh mislukt: `{exc}`",
            )

    # =====================================================
    # INTERNAL MODULE ACTIONS
    # =====================================================

    async def load_module(
        self,
        module_name: str,
        sync_tree: bool = True,
    ) -> tuple[bool, str]:
        extension = extension_name(
            module_name,
        )

        if extension in self.bot.extensions:
            return (
                False,
                f"ℹ️ `{module_name}` is al geladen.",
            )

        try:
            await self.bot.load_extension(
                extension,
            )

            if sync_tree:
                await self.bot.tree.sync()

        except commands.ExtensionNotFound:
            return (
                False,
                f"❌ Module `{module_name}` bestaat niet.",
            )

        except commands.ExtensionFailed as exc:
            return (
                False,
                f"❌ `{module_name}` kon niet worden geladen.\n"
                f"`{type(exc.original).__name__}: {exc.original}`",
            )

        except commands.ExtensionError as exc:
            return (
                False,
                f"❌ `{module_name}` kon niet worden geladen.\n"
                f"`{type(exc).__name__}: {exc}`",
            )

        return (
            True,
            f"✅ Module `{module_name}` geladen.",
        )

    async def unload_module(
        self,
        module_name: str,
        sync_tree: bool = True,
    ) -> tuple[bool, str]:
        if module_name in PROTECTED_MODULES:
            return (
                False,
                "❌ De modulemanager kan zichzelf niet uitschakelen.",
            )

        extension = extension_name(
            module_name,
        )

        if extension not in self.bot.extensions:
            return (
                False,
                f"ℹ️ `{module_name}` is al uitgeschakeld.",
            )

        try:
            await self.bot.unload_extension(
                extension,
            )

            if sync_tree:
                await self.bot.tree.sync()

        except commands.ExtensionError as exc:
            return (
                False,
                f"❌ `{module_name}` kon niet worden uitgeschakeld.\n"
                f"`{type(exc).__name__}: {exc}`",
            )

        return (
            True,
            f"✅ Module `{module_name}` uitgeschakeld.",
        )

    async def reload_module(
        self,
        module_name: str,
        sync_tree: bool = True,
    ) -> tuple[bool, str]:
        if module_name in PROTECTED_MODULES:
            return (
                False,
                "❌ Gebruik voor `modules` zelf een normale botrestart.",
            )

        extension = extension_name(
            module_name,
        )

        if extension not in self.bot.extensions:
            return (
                False,
                f"❌ `{module_name}` is niet geladen.",
            )

        try:
            await self.bot.reload_extension(
                extension,
            )

            if sync_tree:
                await self.bot.tree.sync()

        except commands.ExtensionFailed as exc:
            return (
                False,
                f"❌ `{module_name}` kon niet worden herladen.\n"
                f"`{type(exc.original).__name__}: {exc.original}`",
            )

        except commands.ExtensionError as exc:
            return (
                False,
                f"❌ `{module_name}` kon niet worden herladen.\n"
                f"`{type(exc).__name__}: {exc}`",
            )

        return (
            True,
            f"✅ Module `{module_name}` herladen.",
        )

    async def reload_all_modules(self) -> str:
        successes = []
        failures = []

        for module_name in EXPECTED_MODULES:
            if module_name in PROTECTED_MODULES:
                continue

            extension = extension_name(
                module_name,
            )

            if extension not in self.bot.extensions:
                continue

            try:
                await self.bot.reload_extension(
                    extension,
                )
                successes.append(module_label(module_name))
            except Exception as exc:
                failures.append(
                    f"{module_label(module_name)}: "
                    f"{type(exc).__name__}"
                )

        try:
            await self.bot.tree.sync()
        except Exception as exc:
            failures.append(
                f"Command sync: {type(exc).__name__}"
            )

        location = self.get_panel_location()

        if location is not None:
            guild = self.bot.get_guild(
                location[0],
            )
            if guild is not None:
                await self.refresh_saved_panel(
                    guild,
                    recreate=False,
                )

        text = (
            f"♻️ **Reload All voltooid**\n"
            f"> ✅ Herladen: `{len(successes)}`\n"
            f"> ❌ Fouten: `{len(failures)}`"
        )

        if failures:
            text += (
                "\n\n**Fouten**\n"
                + "\n".join(
                    f"> • {item}"
                    for item in failures[:10]
                )
            )

        return text

    async def run_auto_fix(
        self,
        guild: discord.Guild,
    ) -> str:
        loaded_now = []
        failed = []

        for module_name in EXPECTED_MODULES:
            extension = extension_name(module_name)
            if extension in self.bot.extensions:
                continue
            try:
                await self.bot.load_extension(extension)
                loaded_now.append(module_label(module_name))
            except Exception as exc:
                failed.append(f"{module_label(module_name)}: {type(exc).__name__}")
                self.record_error(f"autofix-load:{module_name}", exc)

        sync_count = None
        try:
            synced = await self.bot.tree.sync()
            sync_count = len(synced)
        except Exception as exc:
            failed.append(f"Command sync: {type(exc).__name__}")
            self.record_error("autofix-command-sync", exc)

        database_report = await asyncio.to_thread(self.database_integrity_report)
        database_ok = "🔴" not in database_report and "❌" not in database_report
        if not database_ok:
            failed.append("Database integrity")

        repair_results = []

        ok, msg = await self.refresh_react_roles(guild)
        if self.bot.get_cog("ReactRoles") is not None:
            repair_results.append(("React Roles", ok))
            if not ok:
                failed.append("React Roles refresh")

        ok, msg = await self.refresh_stats(guild)
        if self.bot.get_cog("Stats") is not None:
            repair_results.append(("Stats", ok))
            if not ok:
                failed.append("Stats refresh")

        ok, msg = await self.refresh_events(guild)
        if self.bot.get_cog("Events") is not None:
            repair_results.append(("Events", ok))
            if not ok:
                failed.append("Events refresh")

        ok_sort, msg_sort = await self.repair_game_sorting(guild)
        if self.bot.get_cog("Sorting") is not None:
            repair_results.append(("Game sortering", ok_sort))
            if not ok_sort:
                failed.append("Game sortering")

        panel_ok, panel_message = await self.refresh_saved_panel(
            guild,
            recreate=True,
        )

        text = "🛠️ **AUTO FIX VOLTOOID**\n"
        text += (
            f"> ▶️ Modules hersteld: `{len(loaded_now)}`\n"
            if loaded_now else
            "> ▶️ Geen missende modules gevonden\n"
        )

        if sync_count is not None:
            text += f"> 🔁 Commands gesynchroniseerd: `{sync_count}`\n"

        text += f"> 💾 Databases: `{'OK' if database_ok else 'FOUT'}`\n"
        text += f"> 🖥️ Panel: `{'OK' if panel_ok else 'FOUT'}`\n"

        if repair_results:
            repaired = sum(1 for _, ok in repair_results if ok)
            text += f"> 🧰 Subsystemen: `{repaired}/{len(repair_results)}` OK\n"

        if failed:
            text += (
                f"> ⚠️ Problemen: `{len(failed)}`\n\n"
                + "\n".join(f"> • {item}" for item in failed[:12])
            )
        else:
            text += "> ✅ Geen fouten gevonden"

        if not panel_ok:
            text += f"\n\n{panel_message}"

        return text

    # =====================================================
    # /MODULE PANEL
    # =====================================================

    @module.command(
        name="panel",
        description="Open het interactieve modulepaneel.",
    )
    async def module_panel(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.check_access(
            interaction,
        ):
            return

        await interaction.response.send_message(
            view=ModulePanelView(
                self,
                interaction.user.id,
            ),
            ephemeral=True,
        )

    # =====================================================
    # /MODULE LIST
    # =====================================================

    @module.command(
        name="list",
        description="Bekijk welke botmodules geladen zijn.",
    )
    async def module_list(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.check_access(interaction):
            return
        await interaction.response.send_message(
            view=ModuleListView(self, interaction.user.id),
            ephemeral=True,
        )

    # =====================================================
    # /MODULE LOAD
    # =====================================================

    @module.command(
        name="load",
        description="Laad een uitgeschakelde botmodule.",
    )
    @app_commands.describe(
        naam="Bijvoorbeeld: stats, welcome of react",
    )
    async def module_load(
        self,
        interaction: discord.Interaction,
        naam: str,
    ):
        if not await self.check_access(interaction):
            return

        module_name = normalise_module_name(naam)
        await interaction.response.defer(ephemeral=True, thinking=True)
        success, message = await self.load_module(module_name)
        await self.audit(interaction, "Module laden: " + module_name, message, success)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(
                clean_result_text(message),
                kind="success" if success else "error",
                title="Module laden",
            ),
        )

    # =====================================================
    # /MODULE UNLOAD
    # =====================================================

    @module.command(
        name="unload",
        description="Schakel een geladen botmodule uit.",
    )
    @app_commands.describe(
        naam="Bijvoorbeeld: stats, welcome of react",
    )
    async def module_unload(
        self,
        interaction: discord.Interaction,
        naam: str,
    ):
        if not await self.check_access(interaction):
            return

        module_name = normalise_module_name(naam)
        await interaction.response.defer(ephemeral=True, thinking=True)
        success, message = await self.unload_module(module_name)
        await self.audit(interaction, "Module uitschakelen: " + module_name, message, success)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(
                clean_result_text(message),
                kind="success" if success else "error",
                title="Module uitschakelen",
            ),
        )

    # =====================================================
    # /MODULE RELOAD
    # =====================================================

    @module.command(
        name="reload",
        description="Herlaad een botmodule zonder botrestart.",
    )
    @app_commands.describe(
        naam="Bijvoorbeeld: stats, welcome of react",
    )
    async def module_reload(
        self,
        interaction: discord.Interaction,
        naam: str,
    ):
        if not await self.check_access(interaction):
            return

        module_name = normalise_module_name(naam)
        await interaction.response.defer(ephemeral=True, thinking=True)
        success, message = await self.reload_module(module_name)
        await self.audit(interaction, "Module herladen: " + module_name, message, success)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(
                clean_result_text(message),
                kind="success" if success else "error",
                title="Module herladen",
            ),
        )

    # =====================================================
    # /ADMINPANEL SETUP
    # =====================================================

    @adminpanel.command(
        name="setup",
        description="Plaats of verplaats het permanente admin controlepaneel.",
    )
    @app_commands.describe(
        channel="Channel waarin het adminpaneel moet komen",
    )
    async def adminpanel_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        if not await self.check_access(interaction):
            return

        target = channel
        if target is None:
            if not isinstance(interaction.channel, discord.TextChannel):
                await self.send_feedback(
                    interaction,
                    "Kies een tekstkanaal voor het adminpaneel.",
                    kind="error",
                )
                return
            target = interaction.channel

        await interaction.response.defer(ephemeral=True, thinking=True)
        bot_member = interaction.guild.me
        permissions = target.permissions_for(bot_member) if bot_member else None
        if permissions is None or not (
            permissions.view_channel
            and permissions.send_messages
            and permissions.read_message_history
        ):
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView(
                    "Ik mis permissies in dat kanaal. Nodig: View Channel, Send Messages en Read Message History.",
                    kind="error",
                    title="Permissies ontbreken",
                ),
            )
            return

        old_location = self.get_panel_location()
        if old_location is not None:
            old_guild_id, old_channel_id, old_message_id = old_location
            old_guild = self.bot.get_guild(old_guild_id)
            if old_guild is not None:
                old_channel = old_guild.get_channel(old_channel_id)
                if isinstance(old_channel, discord.TextChannel):
                    try:
                        old_message = await old_channel.fetch_message(old_message_id)
                        await old_message.delete()
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

        try:
            message = await target.send(
                view=AdminControlLayout(self, interaction.guild),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView("Ik kan daar geen adminpaneel plaatsen.", kind="error"),
            )
            return
        except discord.HTTPException as exc:
            self.record_error("adminpanel-setup", exc)
            logger.exception("Adminpaneel plaatsen mislukt.")
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=FeedbackView("Discord kon het adminpaneel niet plaatsen.", kind="error"),
            )
            return

        self.save_panel_location(interaction.guild.id, target.id, message.id)
        await self.audit(interaction, "Admin Panel setup", f"Geplaatst in {target}", True)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(
                f"Admin Panel geplaatst in {target.mention}. Het paneel blijft werken na een botrestart.",
                kind="success",
                title="Admin Panel geplaatst",
            ),
        )

    # =====================================================
    # /ADMINPANEL REFRESH
    # =====================================================

    @adminpanel.command(
        name="refresh",
        description="Vernieuw het opgeslagen admin controlepaneel.",
    )
    async def adminpanel_refresh(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.check_access(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await self.refresh_saved_panel(interaction.guild, recreate=False)
        await self.audit(interaction, "Panel refresh", message, ok)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(
                clean_result_text(message),
                kind="success" if ok else "error",
                title="Admin Panel vernieuwd" if ok else "Refresh mislukt",
            ),
        )

    # =====================================================
    # /ADMINPANEL FIX
    # =====================================================

    @adminpanel.command(
        name="fix",
        description="Herstel het adminpaneel en veilige botonderdelen.",
    )
    async def adminpanel_fix(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.check_access(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.run_auto_fix(interaction.guild)
        ok = "Problemen: `" not in result
        await self.audit(interaction, "Admin Panel Auto Fix", result, ok)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(
                trim_text(clean_result_text(result), 2200),
                kind="success" if ok else "warning",
                title="Auto Fix voltooid",
            ),
        )

    # =====================================================
    # /ADMINPANEL DASHBOARD
    # =====================================================

    @adminpanel.command(
        name="dashboard",
        description="Open het live admin dashboard.",
    )
    async def adminpanel_dashboard(self, interaction: discord.Interaction):
        if not await self.check_access(interaction):
            return
        await interaction.response.send_message(
            view=DashboardView(self, interaction.user.id, interaction.guild),
            ephemeral=True,
        )

    # =====================================================
    # /ADMINPANEL BACKUP
    # =====================================================

    @adminpanel.command(
        name="backup",
        description="Maak direct een backup van alle botdatabases.",
    )
    async def adminpanel_backup(self, interaction: discord.Interaction):
        if not await self.check_access(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            path = await asyncio.to_thread(self.create_backup)
            message = f"Backup gemaakt: `{path.name}` • `{path.stat().st_size / 1024:.1f} KB`"
            await self.audit(interaction, "Backup gemaakt", message, True)
            kind = "success"
        except Exception as exc:
            self.record_error("backup-command", exc)
            logger.exception("Backup command mislukt.")
            message = f"Backup mislukt: {type(exc).__name__}: {exc}"
            await self.audit(interaction, "Backup mislukt", message, False)
            kind = "error"
        await interaction.edit_original_response(
            content=None,
            embed=None,
            view=FeedbackView(message, kind=kind, title="Database backup"),
        )

    # =====================================================
    # /ADMINPANEL ERRORS
    # =====================================================

    @adminpanel.command(
        name="errors",
        description="Open het centrale error center.",
    )
    async def adminpanel_errors(self, interaction: discord.Interaction):
        if not await self.check_access(interaction):
            return
        await interaction.response.send_message(
            view=ErrorsView(self, interaction.user.id),
            ephemeral=True,
        )

    # =====================================================
    # /ADMINPANEL RESTORE (OWNER)
    # =====================================================

    @adminpanel.command(
        name="restore",
        description="Herstel een databasebackup (alleen Owner).",
    )
    async def adminpanel_restore(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not owner_access(interaction.user):
            await self.send_feedback(
                interaction,
                "Alleen de Owner kan databasebackups herstellen.",
                kind="error",
                title="Owner vereist",
            )
            return
        await interaction.response.send_message(
            view=BackupRestorePicker(self, interaction.user.id),
            ephemeral=True,
        )


# =========================================================
# EXTENSION SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(
        Modules(bot)
    )
