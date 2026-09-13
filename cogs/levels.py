from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from pathlib import Path
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = ROOT / "levels.db"
IMPORT_PATH = ROOT / "activityrank_import.json"

LEADERBOARD_BADGE = (
    "<:l1:1546517649377333248><:l2:1546517693144895579>"
    "<:l3:1546517717081788426><:l4:1546517745137623133>"
    "<:l5:1546517778410774618><:l6:1546517822048309330>"
    "<:l7:1546517850452140032><:l8:1546517874875703417>"
    "<:l9:1546517902629539880><:l10:1546517922317598743>"
)
LEVEL_BADGE = (
    "<:le1:1546518160268853258><:le2:1546518185073709127>"
    "<:le3:1546518207429345371><:le4:1546518229239730217>"
    "<:le5:1546518249997475880>"
)
XP_BADGE = (
    "<:x1:1547125829643800586><:x2:1547125884744499281>"
    "<:x3:1547125924665892887><:x4:1547125950150606951>"
    "<:x5:1547125982631034880><:x6:1547126005041471599>"
    "<:x7:1547126027371946036><:x8:1547126050947858432>"
    "<:x9:1547126072464642089>"
)
LEVEL_UP_ICON = "<:lvl:1546517601167999127>"
BRAND_COLOR = discord.Color.from_str("#6C27DA")

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
INFO_EMOJI = "<:info:1547724036107149413>"

ADD_EMOJI = "<:add:1547724100812931072>"
EDIT_EMOJI = "<:edit:1547724058894934116>"
DELETE_EMOJI = "<:delete:1547724056768286750>"
REFRESH_EMOJI = "<:refresh:1547724055426244618>"
BACK_EMOJI = "<:back:1547724054038052966>"
PREVIOUS_EMOJI = "<:previous:1547724049411739748>"
NEXT_EMOJI = "<:next:1547724052037247106>"
LOCK_EMOJI = "<:lock:1547724040888786966>"
NONE_EMOJI = "<:none:1547724038955208794>"
LIST_EMOJI = "<:list:1547733039361163427>"

# Nieuwe categorie-iconen kunnen later zonder verdere codewijzigingen
# worden ingevuld. Tot die tijd blijven deze knoppen bewust tekst-only.
XP_EMOJI = "<:xp:1547737203789144136>"
TEXT_EMOJI = "<:berichten:1547737207778058250>"
VOICE_EMOJI = "<:voice:1547737205429243924>"
NOTIFICATION_EMOJI = "<:notificatie:1547738617659662488>"
STATUS_EMOJI = "<:status:1547738616501899364>"
USER_EMOJI = "<:user:1547737210986692679>"

logger = logging.getLogger(__name__)
PROGRESS_BAR_LENGTH = 12

DEFAULTS = {
    "xp_text_enabled": "1",
    "xp_text": "10",
    "text_cooldown": "5",
    "xp_voice_enabled": "1",
    "xp_voice_per_minute": "5",
    "voice_solo": "0",
    "xp_invite_enabled": "1",
    "xp_invite": "250",
    "xp_reaction_enabled": "1",
    "xp_reaction": "10",
    "xp_wave_enabled": "1",
    "xp_wave": "150",
    "xp_congrats_enabled": "1",
    "xp_congrats": "100",
    "xp_birthday_enabled": "1",
    "xp_birthday": "500",
    "xp_game_vote_enabled": "1",
    "xp_game_vote": "100",
    "xp_game_suggestion_enabled": "1",
    "xp_game_suggestion": "75",
    "xp_game_success_enabled": "1",
    "xp_game_success": "500",
    "xp_suggestion_enabled": "1",
    "xp_suggestion": "100",
    "xp_suggestion_vote_enabled": "1",
    "xp_suggestion_vote": "50",
    "xp_suggestion_success_enabled": "1",
    "xp_suggestion_success": "200",
    "levelup_enabled": "0",
    "levelup_channel_id": "0",
    "level_roles_enabled": "0",
}

IMPORT_USERNAME_ALIASES = {
    "matohkie": "matoinkie",
    "swabemzeh1599": "swabemzen1599",
}

SOURCE_LABELS = {
    "text": "Tekstbericht",
    "voice": "Voice",
    "invite": "Invite",
    "reaction": "Reaction",
    "wave": "Zwaaien",
    "congrats": "Feliciteren",
    "birthday": "Jarig zijn",
    "game_vote": "Game vote",
    "game_suggestion": "Game suggestie",
    "game_success": "Succesvolle game",
    "suggestion": "Suggestie plaatsen",
    "suggestion_vote": "Suggestie stemmen",
    "suggestion_success": "Succesvolle suggestie",
    "manual": "Handmatige wijziging",
    "legacy_import": "ActivityRank import",
}

XP_KEYS = {
    "text": ("xp_text_enabled", "xp_text"),
    "voice": ("xp_voice_enabled", "xp_voice_per_minute"),
    "invite": ("xp_invite_enabled", "xp_invite"),
    "reaction": ("xp_reaction_enabled", "xp_reaction"),
    "wave": ("xp_wave_enabled", "xp_wave"),
    "congrats": ("xp_congrats_enabled", "xp_congrats"),
    "birthday": ("xp_birthday_enabled", "xp_birthday"),
    "game_vote": ("xp_game_vote_enabled", "xp_game_vote"),
    "game_suggestion": ("xp_game_suggestion_enabled", "xp_game_suggestion"),
    "game_success": ("xp_game_success_enabled", "xp_game_success"),
    "suggestion": ("xp_suggestion_enabled", "xp_suggestion"),
    "suggestion_vote": ("xp_suggestion_vote_enabled", "xp_suggestion_vote"),
    "suggestion_success": ("xp_suggestion_success_enabled", "xp_suggestion_success"),
}


def xp_for_level(level: int) -> int:
    if level <= 1:
        return 0
    return 100 * ((level * (level + 1) // 2) - 1)


def level_from_xp(total_xp: int) -> int:
    total_xp = max(0, int(total_xp))
    # Solve L(L+1)/2 <= total/100 + 1
    n = total_xp / 100 + 1
    level = max(1, int((math.sqrt(1 + 8 * n) - 1) // 2))
    while xp_for_level(level + 1) <= total_xp:
        level += 1
    while level > 1 and xp_for_level(level) > total_xp:
        level -= 1
    return level


def fmt_num(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def fmt_hours(seconds: int) -> str:
    return f"{seconds / 3600:.1f}".replace(".", ",")


def progress_bar(total_xp: int, level: int) -> tuple[str, int, int, int]:
    current_floor = xp_for_level(level)
    next_floor = xp_for_level(level + 1)
    span = max(1, next_floor - current_floor)
    progress = max(0, min(span, total_xp - current_floor))
    percent = int((progress / span) * 100)
    filled = round((progress / span) * PROGRESS_BAR_LENGTH)
    bar = "█" * filled + "░" * (PROGRESS_BAR_LENGTH - filled)
    return bar, percent, progress, span


def is_admin(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id or member.guild_permissions.administrator:
        return True
    return any(role.name.lower() in {"admin", "owner"} for role in member.roles)


async def init_db() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS levels_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                total_xp INTEGER NOT NULL DEFAULT 0,
                text_messages INTEGER NOT NULL DEFAULT 0,
                voice_seconds INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS levels_config (
                guild_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (guild_id, key)
            );
            CREATE TABLE IF NOT EXISTS levels_roles (
                guild_id INTEGER NOT NULL,
                level INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                keep_previous INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, level)
            );
            CREATE TABLE IF NOT EXISTS levels_xp_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                xp INTEGER NOT NULL,
                reference_id TEXT,
                actor_id INTEGER,
                created_at INTEGER NOT NULL,
                UNIQUE (guild_id, source, reference_id)
            );
            CREATE TABLE IF NOT EXISTS levels_exclusions (
                guild_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, kind, target_id)
            );
            CREATE TABLE IF NOT EXISTS levels_reaction_awards (
                guild_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                reactor_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, message_id, reactor_id)
            );
            CREATE TABLE IF NOT EXISTS levels_imports (
                guild_id INTEGER NOT NULL,
                import_name TEXT NOT NULL,
                imported_at INTEGER NOT NULL,
                rows_imported INTEGER NOT NULL,
                PRIMARY KEY (guild_id, import_name)
            );
            """
        )
        await db.commit()




# ============================================================
# COMPONENTS V2 HELPERS
# ============================================================

def component_emoji(value: str | None) -> discord.PartialEmoji | None:
    if not value:
        return None
    try:
        emoji = discord.PartialEmoji.from_str(value)
    except Exception:
        return None
    return emoji if emoji.name else None


def quoted(lines: list[str]) -> str:
    return "\n".join(f"> └ {line}" for line in lines)


def feedback_style(kind: str) -> tuple[str, str, discord.Colour]:
    if kind == "success":
        return "Gelukt", SUCCESS_EMOJI, discord.Colour.from_rgb(87, 242, 135)
    if kind == "error":
        return "Fout", ERROR_EMOJI, discord.Colour.from_rgb(237, 66, 69)
    if kind == "warning":
        return "Let op", WARNING_EMOJI, discord.Colour.from_rgb(254, 231, 92)
    return "Informatie", INFO_EMOJI, BRAND_COLOR


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

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {icon} {title or default_title}\n"
                    + "\n".join(
                        f"> └ {line}"
                        for line in message.splitlines()
                        if line.strip()
                    )
                ),
                accent_colour=accent,
            )
        )


class LevelUpView(discord.ui.LayoutView):
    def __init__(
        self,
        member: discord.Member,
        old_level: int,
        new_level: int,
    ):
        super().__init__(timeout=None)

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {LEVEL_UP_ICON} Level up\n"
                    f"> └ {member.mention} heeft level **{new_level}** bereikt.\n"
                    f"> └ Van level **{old_level}** naar **{new_level}**."
                ),
                accent_colour=BRAND_COLOR,
            )
        )


# ============================================================
# MODALS
# ============================================================

class ValueModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        source: str,
        current: int,
    ):
        super().__init__(
            title=f"{SOURCE_LABELS[source]} XP aanpassen",
            timeout=300,
        )
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.source = source
        self.value = discord.ui.TextInput(
            label="Nieuwe XP-waarde",
            default=str(current),
            required=True,
            max_length=7,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit menu is niet van jou.",
                kind="error",
            )
            return

        try:
            new = int(str(self.value.value).strip())
            if new < 0:
                raise ValueError
        except ValueError:
            await self.cog.send_feedback(
                interaction,
                "Vul een geldig positief getal in.",
                kind="error",
            )
            return

        _, value_key = XP_KEYS[self.source]
        old = await self.cog.get_int(self.guild_id, value_key)
        await self.cog.set_config(
            self.guild_id,
            value_key,
            str(new),
        )

        await self.cog.send_feedback(
            interaction,
            f"{SOURCE_LABELS[self.source]} is aangepast van "
            f"**{old} XP** naar **{new} XP**.",
            kind="success",
            title="XP-waarde aangepast",
        )


class CooldownModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        current: int,
    ):
        super().__init__(
            title="Message XP cooldown",
            timeout=300,
        )
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.value = discord.ui.TextInput(
            label="Aantal seconden",
            default=str(current),
            max_length=5,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await self.cog.send_feedback(
                interaction,
                "Dit menu is niet van jou.",
                kind="error",
            )
            return

        try:
            value = int(str(self.value.value).strip())
            if value < 0:
                raise ValueError
        except ValueError:
            await self.cog.send_feedback(
                interaction,
                "Vul een geldig aantal seconden in.",
                kind="error",
            )
            return

        await self.cog.set_config(
            self.guild_id,
            "text_cooldown",
            str(value),
        )

        await self.cog.send_feedback(
            interaction,
            f"De message XP cooldown staat nu op **{value} seconden**.",
            kind="success",
            title="Cooldown aangepast",
        )


class ManualXpModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Levels",
        guild_id: int,
        user_id: int,
        mode: str,
    ):
        title = {
            "add": "XP geven",
            "remove": "XP afnemen",
            "set": "XP instellen",
        }[mode]
        super().__init__(title=title, timeout=300)

        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode
        self.value = discord.ui.TextInput(
            label="Aantal XP",
            required=True,
            max_length=12,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        if (
            not isinstance(interaction.user, discord.Member)
            or not is_admin(interaction.user)
        ):
            await self.cog.send_feedback(
                interaction,
                "Je hebt geen toestemming om het levelsysteem te beheren.",
                kind="error",
            )
            return

        try:
            amount = int(str(self.value.value).strip())
            if amount < 0:
                raise ValueError
        except ValueError:
            await self.cog.send_feedback(
                interaction,
                "Vul een geldig positief getal in.",
                kind="error",
            )
            return

        row = await self.cog.get_user(
            self.guild_id,
            self.user_id,
        )
        current = row[0] if row else 0

        if self.mode == "add":
            new_total = current + amount
            delta = amount
        elif self.mode == "remove":
            if amount > current:
                await self.cog.send_feedback(
                    interaction,
                    "Een gebruiker kan niet onder **0 XP** komen.",
                    kind="error",
                )
                return
            new_total = current - amount
            delta = -amount
        else:
            new_total = amount
            delta = new_total - current

        await self.cog.set_total_xp(
            self.guild_id,
            self.user_id,
            new_total,
        )

        if delta:
            await self.cog.log_xp(
                self.guild_id,
                self.user_id,
                "manual",
                delta,
                f"manual:{interaction.id}",
                interaction.user.id,
            )

        member = (
            interaction.guild.get_member(self.user_id)
            if interaction.guild
            else None
        )
        mention = (
            member.mention
            if member
            else f"<@{self.user_id}>"
        )

        await self.cog.send_feedback(
            interaction,
            f"XP van {mention} staat nu op **{fmt_num(new_total)} XP**.",
            kind="success",
            title="XP bijgewerkt",
        )

        if member:
            await self.cog.apply_level_roles(member)


# ============================================================
# ADMIN CONFIG MENU
# ============================================================

class ConfigButton(discord.ui.Button):
    def __init__(
        self,
        parent: "ConfigView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
            style=style,
            disabled=disabled,
        )
        self.owner_view = parent
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.handle(interaction, self.action)


class ExclusionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, parent: "ConfigView"):
        super().__init__(
            placeholder="Rol uitsluiten / weer toestaan…",
            min_values=1,
            max_values=1,
        )
        self.owner_view = parent

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await self.owner_view.cog.toggle_exclusion(
            self.owner_view.guild_id,
            "role",
            role.id,
        )
        await self.owner_view.rebuild(interaction, "exclusions")


class UserPicker(discord.ui.UserSelect):
    def __init__(self, parent: "ConfigView"):
        super().__init__(
            placeholder="Kies een gebruiker…",
            min_values=1,
            max_values=1,
        )
        self.owner_view = parent

    async def callback(self, interaction: discord.Interaction):
        user = self.values[0]

        if getattr(user, "bot", False):
            await self.owner_view.cog.send_feedback(
                interaction,
                "Bots nemen niet deel aan het levelsysteem.",
                kind="error",
            )
            return

        member = (
            interaction.guild.get_member(user.id)
            if interaction.guild
            else None
        )

        if member is None:
            await self.owner_view.cog.send_feedback(
                interaction,
                "Deze gebruiker kon niet worden gevonden.",
                kind="error",
            )
            return

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await UserManageView.create(
                self.owner_view.cog,
                self.owner_view.owner_id,
                self.owner_view.guild_id,
                member.id,
            ),
        )


class ConfigView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        panel: str = "home",
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.panel = panel

    @classmethod
    async def create(
        cls,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        panel: str = "home",
    ):
        self = cls(cog, owner_id, guild_id, panel)
        await self.render()
        return self

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id == self.owner_id
            and isinstance(interaction.user, discord.Member)
            and is_admin(interaction.user)
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit beheermenu is niet van jou.",
            kind="error",
        )
        return False

    async def rebuild(
        self,
        interaction: discord.Interaction,
        panel: str | None = None,
    ):
        next_panel = panel or self.panel

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=await ConfigView.create(
                self.cog,
                self.owner_id,
                self.guild_id,
                next_panel,
            ),
        )

    async def render(self):
        self.clear_items()

        panel = self.panel

        if panel == "home":
            await self.render_home()
        elif panel == "toggles":
            await self.render_toggles()
        elif panel == "values":
            await self.render_values()
        elif panel == "text":
            await self.render_text()
        elif panel == "voice":
            await self.render_voice()
        elif panel == "roles":
            await self.render_roles()
        elif panel == "notifications":
            await self.render_notifications()
        elif panel == "exclusions":
            await self.render_exclusions()
        elif panel == "user":
            await self.render_user_picker()
        elif panel == "status":
            await self.render_status()
        else:
            self.panel = "home"
            await self.render_home()

    async def render_home(self):
        text = (
            f"# {LEVEL_BADGE}\n"
            "## Levels Config\n"
            "> └ Beheer hier het volledige levelsysteem.\n\n"
            "## XP\n"
            "> └ Schakel XP-bronnen in of uit en pas hun waardes aan.\n\n"
            "## Activiteit\n"
            "> └ Stel tekst-XP, voice-XP, levelrollen en meldingen in.\n\n"
            "## Beheer\n"
            "> └ Uitsluitingen, gebruikersbeheer en systeemstatus."
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(text),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "nav:toggles",
                        "XP-functies",
                        emoji=XP_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ConfigButton(
                        self,
                        "nav:values",
                        "XP-waardes",
                        emoji=EDIT_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:text",
                        "Tekst",
                        emoji=TEXT_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:voice",
                        "Voice",
                        emoji=VOICE_EMOJI,
                    ),
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "nav:roles",
                        "Levelrollen",
                        emoji=LEVEL_UP_ICON,
                    ),
                    ConfigButton(
                        self,
                        "nav:notifications",
                        "Meldingen",
                        emoji=NOTIFICATION_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:exclusions",
                        "Uitsluitingen",
                        emoji=LOCK_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:user",
                        "Gebruiker",
                        emoji=USER_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:status",
                        "Status",
                        emoji=STATUS_EMOJI,
                    ),
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_toggles(self):
        buttons: list[discord.ui.Button] = []

        lines = [
            f"# {LEVEL_BADGE}",
            "## XP-functies",
            "> └ Klik op een functie om deze aan of uit te zetten.",
            "",
        ]

        for source, (enabled_key, _) in XP_KEYS.items():
            enabled = await self.cog.get_bool(
                self.guild_id,
                enabled_key,
            )
            lines.append(
                f"> └ **{SOURCE_LABELS[source]}:** "
                f"{SUCCESS_EMOJI + ' Aan' if enabled else NONE_EMOJI + ' Uit'}"
            )

            buttons.append(
                ConfigButton(
                    self,
                    f"toggle:{source}",
                    SOURCE_LABELS[source],
                    style=(
                        discord.ButtonStyle.success
                        if enabled
                        else discord.ButtonStyle.secondary
                    ),
                )
            )

        rows = [
            discord.ui.ActionRow(*buttons[i : i + 5])
            for i in range(0, len(buttons), 5)
        ]

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("\n".join(lines)),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                *rows,
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    )
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_values(self):
        buttons: list[discord.ui.Button] = []
        lines = [
            f"# {LEVEL_BADGE}",
            "## XP-waardes",
        ]

        for source, (_, value_key) in XP_KEYS.items():
            value = await self.cog.get_int(
                self.guild_id,
                value_key,
            )
            suffix = "/min" if source == "voice" else ""
            lines.append(
                f"> └ **{SOURCE_LABELS[source]}:** "
                f"{fmt_num(value)} XP{suffix}"
            )
            buttons.append(
                ConfigButton(
                    self,
                    f"value:{source}",
                    SOURCE_LABELS[source],
                    emoji=EDIT_EMOJI,
                )
            )

        rows = [
            discord.ui.ActionRow(*buttons[i : i + 5])
            for i in range(0, len(buttons), 5)
        ]

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("\n".join(lines)),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                *rows,
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    )
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_text(self):
        value = await self.cog.get_int(
            self.guild_id,
            "xp_text",
        )
        cooldown = await self.cog.get_int(
            self.guild_id,
            "text_cooldown",
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {LEVEL_BADGE}\n"
                    "## Tekst XP\n"
                    f"> └ XP per bericht: **{fmt_num(value)} XP**\n"
                    f"> └ Cooldown: **{cooldown} seconden**\n\n"
                    "## Statistieken\n"
                    "> └ Berichten blijven meetellen voor activiteit, "
                    "ook wanneer de XP-cooldown actief is."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "value:text",
                        "XP aanpassen",
                        emoji=EDIT_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ConfigButton(
                        self,
                        "cooldown",
                        "Cooldown aanpassen",
                        emoji=EDIT_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    ),
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_voice(self):
        value = await self.cog.get_int(
            self.guild_id,
            "xp_voice_per_minute",
        )
        solo = await self.cog.get_bool(
            self.guild_id,
            "voice_solo",
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {LEVEL_BADGE}\n"
                    "## Voice XP\n"
                    f"> └ XP per minuut: **{fmt_num(value)} XP**\n"
                    f"> └ Solo voice: "
                    f"**{'Aan' if solo else 'Uit'}**\n\n"
                    "## Tellen\n"
                    "> └ Standaard telt voice pas wanneer minimaal "
                    "twee geldige gebruikers samen in voice zitten."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "value:voice",
                        "XP aanpassen",
                        emoji=EDIT_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ConfigButton(
                        self,
                        "voice_solo",
                        f"Solo voice {'uit' if solo else 'aan'}",
                        emoji=REFRESH_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    ),
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_roles(self):
        enabled = await self.cog.get_bool(
            self.guild_id,
            "level_roles_enabled",
        )
        roles = await self.cog.get_level_roles(
            self.guild_id
        )

        lines = [
            f"# {LEVEL_BADGE}",
            "## Levelrollen",
            f"> └ Automatisch uitdelen: "
            f"**{'Aan' if enabled else 'Uit'}**",
        ]

        if roles:
            lines.append("")
            lines.append("## Ingesteld")
            for level, role_id, keep_previous in roles:
                keep = (
                    " • vorige behouden"
                    if keep_previous
                    else ""
                )
                lines.append(
                    f"> └ Level **{level}** → <@&{role_id}>{keep}"
                )
        else:
            lines.extend(
                [
                    "",
                    "## Ingesteld",
                    "> └ Nog geen levelrollen opgeslagen.",
                ]
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("\n".join(lines)),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "roles_toggle",
                        (
                            "Automatisch uit"
                            if enabled
                            else "Automatisch aan"
                        ),
                        emoji=REFRESH_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "roles_sync",
                        "Rollen controleren",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# Rollen toevoegen of verwijderen kan met "
                    "`/levels role-set` en `/levels role-remove`."
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_notifications(self):
        enabled = await self.cog.get_bool(
            self.guild_id,
            "levelup_enabled",
        )
        channel_id = await self.cog.get_int(
            self.guild_id,
            "levelup_channel_id",
        )

        channel_text = (
            f"<#{channel_id}>"
            if channel_id
            else "Niet ingesteld"
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {LEVEL_BADGE}\n"
                    "## Meldingen\n"
                    f"> └ Level-up meldingen: "
                    f"**{'Aan' if enabled else 'Uit'}**\n"
                    f"> └ Kanaal: {channel_text}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "notifications_toggle",
                        (
                            "Meldingen uit"
                            if enabled
                            else "Meldingen aan"
                        ),
                        emoji=REFRESH_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "notifications_channel",
                        "Gebruik dit kanaal",
                        emoji=EDIT_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    ),
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_exclusions(self):
        counts = await self.cog.get_exclusion_counts(
            self.guild_id
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {LEVEL_BADGE}\n"
                    "## XP-uitsluitingen\n"
                    f"> └ Tekstkanalen: **{counts.get('text_channel', 0)}**\n"
                    f"> └ Voicekanalen: **{counts.get('voice_channel', 0)}**\n"
                    f"> └ Rollen: **{counts.get('role', 0)}**\n\n"
                    "## Aanpassen\n"
                    "> └ Klik opnieuw op een uitgesloten onderdeel "
                    "om het weer toe te staan."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "exclude_text",
                        "Dit tekstkanaal",
                        emoji=TEXT_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "exclude_voice",
                        "Mijn voicekanaal",
                        emoji=VOICE_EMOJI,
                    ),
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    ),
                ),
                discord.ui.ActionRow(
                    ExclusionRoleSelect(self)
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_user_picker(self):
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {LEVEL_BADGE}\n"
                    "## Gebruiker beheren\n"
                    "> └ Kies een gebruiker om XP, geschiedenis "
                    "en levelrollen te beheren."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    UserPicker(self)
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    )
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def render_status(self):
        status_text = await self.cog.render_status(
            self.guild_id
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(status_text),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ConfigButton(
                        self,
                        "nav:home",
                        "Terug",
                        emoji=BACK_EMOJI,
                    )
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action.startswith("nav:"):
            await self.rebuild(
                interaction,
                action.split(":", 1)[1],
            )
            return

        if action.startswith("toggle:"):
            source = action.split(":", 1)[1]
            enabled_key, _ = XP_KEYS[source]
            current = await self.cog.get_bool(
                self.guild_id,
                enabled_key,
            )
            await self.cog.set_config(
                self.guild_id,
                enabled_key,
                "0" if current else "1",
            )
            await self.rebuild(interaction, "toggles")
            return

        if action.startswith("value:"):
            source = action.split(":", 1)[1]
            _, value_key = XP_KEYS[source]
            current = await self.cog.get_int(
                self.guild_id,
                value_key,
            )
            await interaction.response.send_modal(
                ValueModal(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    source,
                    current,
                )
            )
            return

        if action == "cooldown":
            current = await self.cog.get_int(
                self.guild_id,
                "text_cooldown",
            )
            await interaction.response.send_modal(
                CooldownModal(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    current,
                )
            )
            return

        if action == "voice_solo":
            current = await self.cog.get_bool(
                self.guild_id,
                "voice_solo",
            )
            await self.cog.set_config(
                self.guild_id,
                "voice_solo",
                "0" if current else "1",
            )
            await self.cog.refresh_all_voice(
                self.guild_id
            )
            await self.rebuild(interaction, "voice")
            return

        if action == "roles_toggle":
            current = await self.cog.get_bool(
                self.guild_id,
                "level_roles_enabled",
            )
            await self.cog.set_config(
                self.guild_id,
                "level_roles_enabled",
                "0" if current else "1",
            )
            await self.rebuild(interaction, "roles")
            return

        if action == "roles_sync":
            if interaction.guild is None:
                return

            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )

            changed = 0
            for member in interaction.guild.members:
                if not member.bot:
                    changed += await self.cog.apply_level_roles(
                        member
                    )

            await self.cog.send_feedback(
                interaction,
                f"Levelrollen gecontroleerd. "
                f"**{changed} wijziging(en)** uitgevoerd.",
                kind="success",
                title="Levelrollen gecontroleerd",
            )
            return

        if action == "notifications_toggle":
            current = await self.cog.get_bool(
                self.guild_id,
                "levelup_enabled",
            )
            await self.cog.set_config(
                self.guild_id,
                "levelup_enabled",
                "0" if current else "1",
            )
            await self.rebuild(
                interaction,
                "notifications",
            )
            return

        if action == "notifications_channel":
            if interaction.channel_id is None:
                await self.cog.send_feedback(
                    interaction,
                    "Dit kanaal kon niet worden ingesteld.",
                    kind="error",
                )
                return

            await self.cog.set_config(
                self.guild_id,
                "levelup_channel_id",
                str(interaction.channel_id),
            )
            await self.rebuild(
                interaction,
                "notifications",
            )
            return

        if action == "exclude_text":
            if interaction.channel_id is None:
                return

            await self.cog.toggle_exclusion(
                self.guild_id,
                "text_channel",
                interaction.channel_id,
            )
            await self.rebuild(
                interaction,
                "exclusions",
            )
            return

        if action == "exclude_voice":
            member = interaction.user

            if (
                not isinstance(member, discord.Member)
                or not member.voice
                or not member.voice.channel
            ):
                await self.cog.send_feedback(
                    interaction,
                    "Je zit niet in een voicekanaal.",
                    kind="error",
                )
                return

            await self.cog.toggle_exclusion(
                self.guild_id,
                "voice_channel",
                member.voice.channel.id,
            )
            await self.cog.refresh_all_voice(
                self.guild_id
            )
            await self.rebuild(
                interaction,
                "exclusions",
            )


# ============================================================
# USER MANAGEMENT
# ============================================================

class UserManageButton(discord.ui.Button):
    def __init__(
        self,
        parent: "UserManageView",
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
        self.owner_view = parent
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.handle(interaction, self.action)


class UserManageView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        user_id: int,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.user_id = user_id

    @classmethod
    async def create(
        cls,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        user_id: int,
    ):
        self = cls(
            cog,
            owner_id,
            guild_id,
            user_id,
        )
        await self.render()
        return self

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id == self.owner_id
            and isinstance(interaction.user, discord.Member)
            and is_admin(interaction.user)
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit beheermenu is niet van jou.",
            kind="error",
        )
        return False

    async def render(self):
        guild = self.cog.bot.get_guild(
            self.guild_id
        )
        member = (
            guild.get_member(self.user_id)
            if guild
            else None
        )

        if member is None:
            body = (
                f"# {LEVEL_BADGE}\n"
                "## Gebruiker beheren\n"
                f"> └ {ERROR_EMOJI} Deze gebruiker is niet meer beschikbaar."
            )
        else:
            body = await self.cog.render_user_manage(
                member
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(body),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    UserManageButton(
                        self,
                        "add",
                        "XP geven",
                        emoji=ADD_EMOJI,
                        style=discord.ButtonStyle.success,
                    ),
                    UserManageButton(
                        self,
                        "remove",
                        "XP afnemen",
                        emoji=DELETE_EMOJI,
                        style=discord.ButtonStyle.danger,
                    ),
                    UserManageButton(
                        self,
                        "set",
                        "XP instellen",
                        emoji=EDIT_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                ),
                discord.ui.ActionRow(
                    UserManageButton(
                        self,
                        "history",
                        "XP geschiedenis",
                        emoji=LIST_EMOJI,
                    ),
                    UserManageButton(
                        self,
                        "back",
                        "Terug",
                        emoji=BACK_EMOJI,
                    ),
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action in {"add", "remove", "set"}:
            await interaction.response.send_modal(
                ManualXpModal(
                    self.cog,
                    self.guild_id,
                    self.user_id,
                    action,
                )
            )
            return

        if action == "history":
            history = await self.cog.render_history(
                self.guild_id,
                self.user_id,
            )
            await interaction.response.send_message(
                view=SimplePanelView(
                    "XP geschiedenis",
                    history,
                    icon=LIST_EMOJI,
                ),
                ephemeral=True,
            )
            return

        if action == "back":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=await ConfigView.create(
                    self.cog,
                    self.owner_id,
                    self.guild_id,
                    "user",
                ),
            )


class SimplePanelView(discord.ui.LayoutView):
    def __init__(
        self,
        title: str,
        body: str,
        *,
        icon: str = INFO_EMOJI,
        accent: discord.Colour = BRAND_COLOR,
    ):
        super().__init__(timeout=180)

        if body.lstrip().startswith("# "):
            display_text = body
        else:
            quoted_body = "\n".join(
                f"> └ {line}"
                for line in body.splitlines()
                if line.strip()
            )
            display_text = (
                f"# {icon} {title}\n"
                f"{quoted_body}"
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(display_text),
                accent_colour=accent,
            )
        )


# ============================================================
# PUBLIC PROFILE
# ============================================================

class LevelProfileView(discord.ui.LayoutView):
    def __init__(
        self,
        member: discord.Member,
        *,
        level: int,
        rank: int,
        total: int,
        messages: int,
        voice: int,
        progress: int,
        span: int,
        percent: int,
        needed: int,
        source_totals: dict[str, int],
        banner: str = LEVEL_BADGE,
        header_icon: str = LEVEL_UP_ICON,
        show_avatar: bool = False,
    ):
        super().__init__(timeout=None)

        extra_sources = [
            ("wave", "Zwaaien"),
            ("reaction", "Reacties"),
            ("invite", "Invites"),
            ("congrats", "Feliciteren"),
            ("birthday", "Verjaardag"),
            ("game_vote", "Game votes"),
            ("game_suggestion", "Game suggesties"),
            ("game_success", "Succesvolle games"),
            ("suggestion", "Suggesties"),
            ("suggestion_vote", "Suggestiestemmen"),
            ("suggestion_success", "Succesvolle suggesties"),
        ]

        extra_lines = [
            f"> └ **{label}:** "
            f"{fmt_num(source_totals.get(source, 0))} XP"
            for source, label in extra_sources
            if source_totals.get(source, 0)
        ]

        if not extra_lines:
            extra_lines = [
                "> └ Nog geen extra XP-bronnen geregistreerd."
            ]

        header = (
            f"# {banner}\n"
            f"## {header_icon} Level {level} • "
            f"{discord.utils.escape_markdown(member.display_name)}\n"
            f"> └ Rank **#{rank}** • **{fmt_num(total)} XP totaal**"
        )

        details = (
            "## Progressie\n"
            f"> └ **{percent}%** • "
            f"{fmt_num(progress)} / {fmt_num(span)} XP in dit level\n"
            f"> └ Nog **{fmt_num(needed)} XP** tot level **{level + 1}**\n\n"
            "## Activiteit\n"
            f"> └ Berichten: **{fmt_num(messages)}**\n"
            f"> └ Voice: **{fmt_hours(voice)} uur**\n\n"
            "## Extra XP\n"
            + "\n".join(extra_lines)
        )

        children: list[discord.ui.Item] = []

        if show_avatar:
            children.append(
                discord.ui.Section(
                    discord.ui.TextDisplay(header),
                    accessory=discord.ui.Thumbnail(
                        str(member.display_avatar.url),
                        description=f"Profielfoto van {member.display_name}",
                    ),
                )
            )
        else:
            children.append(
                discord.ui.TextDisplay(header)
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(details),
                discord.ui.TextDisplay(
                    "-# LEVENLOOS • Levels"
                ),
            ]
        )

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=BRAND_COLOR,
            )
        )


# ============================================================
# LEADERBOARD
# ============================================================

class LeaderboardButton(discord.ui.Button):
    def __init__(
        self,
        parent: "LeaderboardView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
            style=style,
            disabled=disabled,
        )
        self.owner_view = parent
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.handle(interaction, self.action)


class LeaderboardView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Levels",
        guild_id: int,
        user_id: int,
        sort_key: str = "xp",
        page: int = 0,
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.sort_key = sort_key
        self.page = page
        self.pages = 1

    @classmethod
    async def create(
        cls,
        cog: "Levels",
        guild_id: int,
        user_id: int,
        sort_key: str = "xp",
        page: int = 0,
    ):
        self = cls(
            cog,
            guild_id,
            user_id,
            sort_key,
            page,
        )
        await self.render()
        return self

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.user_id:
            return True

        await self.cog.send_feedback(
            interaction,
            "Open zelf `/top` om het leaderboard te bedienen.",
            kind="error",
        )
        return False

    async def render(self):
        self.clear_items()

        body, pages, normalized_page = (
            await self.cog.render_leaderboard(
                self.guild_id,
                self.sort_key,
                self.page,
            )
        )

        self.pages = pages
        self.page = normalized_page

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(body),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    LeaderboardButton(
                        self,
                        "prev",
                        "Vorige",
                        emoji=PREVIOUS_EMOJI,
                        disabled=self.page <= 0,
                    ),
                    LeaderboardButton(
                        self,
                        "xp",
                        "XP",
                        emoji=XP_EMOJI,
                        style=(
                            discord.ButtonStyle.primary
                            if self.sort_key == "xp"
                            else discord.ButtonStyle.secondary
                        ),
                    ),
                    LeaderboardButton(
                        self,
                        "messages",
                        "Berichten",
                        emoji=TEXT_EMOJI,
                        style=(
                            discord.ButtonStyle.primary
                            if self.sort_key == "messages"
                            else discord.ButtonStyle.secondary
                        ),
                    ),
                    LeaderboardButton(
                        self,
                        "voice",
                        "Voice",
                        emoji=VOICE_EMOJI,
                        style=(
                            discord.ButtonStyle.primary
                            if self.sort_key == "voice"
                            else discord.ButtonStyle.secondary
                        ),
                    ),
                    LeaderboardButton(
                        self,
                        "next",
                        "Volgende",
                        emoji=NEXT_EMOJI,
                        disabled=self.page >= self.pages - 1,
                    ),
                ),
                discord.ui.ActionRow(
                    LeaderboardButton(
                        self,
                        "mine",
                        "Mijn positie",
                        emoji=USER_EMOJI,
                    ),
                ),
                discord.ui.TextDisplay(
                    f"-# Pagina {self.page + 1}/{self.pages}"
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def refresh(
        self,
        interaction: discord.Interaction,
    ):
        await self.render()
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=self,
        )

    async def handle(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if action == "prev":
            self.page = max(0, self.page - 1)
        elif action == "next":
            self.page = min(
                self.pages - 1,
                self.page + 1,
            )
        elif action in {"xp", "messages", "voice"}:
            self.sort_key = action
            self.page = 0
        elif action == "mine":
            self.page = await self.cog.page_for_user(
                self.guild_id,
                self.user_id,
                self.sort_key,
            )

        await self.refresh(interaction)


# ============================================================
# IMPORT UI
# ============================================================

class ImportPreviewButton(discord.ui.Button):
    def __init__(
        self,
        parent: "ImportPreviewView",
        action: str,
        label: str,
        *,
        emoji: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
        self.owner_view = parent
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if self.action == "prev":
            self.owner_view.page = max(
                0,
                self.owner_view.page - 1,
            )
        else:
            self.owner_view.page = min(
                self.owner_view.total_pages - 1,
                self.owner_view.page + 1,
            )

        self.owner_view.render()

        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=self.owner_view,
        )


class ImportPreviewView(discord.ui.LayoutView):
    PAGE_SIZE = 20

    def __init__(
        self,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        matched,
        unmatched,
        duplicates,
        page: int = 0,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.matched = matched
        self.unmatched = unmatched
        self.duplicates = duplicates
        self.page = page
        self.total_pages = 1
        self.render()

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.owner_id:
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit importmenu is niet van jou.",
            kind="error",
        )
        return False

    def render(self):
        self.clear_items()

        self.total_pages = max(
            1,
            math.ceil(
                len(self.matched) / self.PAGE_SIZE
            ),
        )
        self.page = max(
            0,
            min(
                self.page,
                self.total_pages - 1,
            ),
        )

        start = self.page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE

        lines = [
            f"# {LEVEL_BADGE}",
            "## ActivityRank import preview",
            f"> └ {SUCCESS_EMOJI} Gekoppeld: **{len(self.matched)}**",
            f"> └ {WARNING_EMOJI} Niet gevonden: **{len(self.unmatched)}**",
            f"> └ {ERROR_EMOJI} Onduidelijk: **{len(self.duplicates)}**",
            "",
            "## Matches",
        ]

        for row, member in self.matched[start:end]:
            lines.append(
                f"> └ `{row['username']}` → {member.mention}"
            )

        if not self.matched:
            lines.append("> └ Geen matches.")

        if self.unmatched:
            lines.extend(
                [
                    "",
                    "## Niet gevonden",
                    *[
                        f"> └ `{row['username']}`"
                        for row in self.unmatched[:15]
                    ],
                ]
            )

        if self.duplicates:
            lines.extend(
                [
                    "",
                    "## Onduidelijke matches",
                ]
            )

            for row, candidates in self.duplicates[:10]:
                names = ", ".join(
                    member.mention
                    for member in candidates[:5]
                )
                lines.append(
                    f"> └ `{row['username']}` → {names}"
                )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("\n".join(lines)),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ImportPreviewButton(
                        self,
                        "prev",
                        "Vorige",
                        emoji=PREVIOUS_EMOJI,
                        disabled=self.page <= 0,
                    ),
                    ImportPreviewButton(
                        self,
                        "next",
                        "Volgende",
                        emoji=NEXT_EMOJI,
                        disabled=(
                            self.page
                            >= self.total_pages - 1
                        ),
                    ),
                ),
                discord.ui.TextDisplay(
                    f"-# Pagina {self.page + 1}/{self.total_pages} • "
                    "Er is nog niets aangepast."
                ),
                accent_colour=BRAND_COLOR,
            )
        )


class ImportConfirmButton(discord.ui.Button):
    def __init__(
        self,
        parent: "ImportConfirmView",
        action: str,
    ):
        if action == "go":
            label = "Importeren"
            emoji = SUCCESS_EMOJI
            style = discord.ButtonStyle.success
        else:
            label = "Annuleren"
            emoji = NONE_EMOJI
            style = discord.ButtonStyle.secondary

        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
            style=style,
        )
        self.owner_view = parent
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if self.action == "cancel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=FeedbackView(
                    "De ActivityRank-import is geannuleerd.",
                    kind="info",
                    title="Import geannuleerd",
                ),
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        result = await self.owner_view.cog.run_import(
            interaction.guild
        )

        kind = (
            "warning"
            if "al uitgevoerd" in result.lower()
            else "success"
        )

        await self.owner_view.cog.send_feedback(
            interaction,
            result,
            kind=kind,
            title="ActivityRank import",
        )


class ImportConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} ActivityRank import\n"
                    "> └ Deze actie importeert historische XP, berichten "
                    "en voice-tijd naar `levels.db`.\n"
                    "> └ Bestaande ActivityRank-XP wordt exact overgenomen "
                    "en niet opnieuw berekend."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ImportConfirmButton(self, "go"),
                    ImportConfirmButton(self, "cancel"),
                ),
                accent_colour=discord.Colour.from_rgb(
                    254,
                    231,
                    92,
                ),
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id == self.owner_id
            and isinstance(interaction.user, discord.Member)
            and is_admin(interaction.user)
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit importmenu is niet van jou.",
            kind="error",
        )
        return False


# ============================================================
# XP RECALCULATION CONFIRMATION
# ============================================================

class RecalculateButton(discord.ui.Button):
    def __init__(
        self,
        parent: "RecalculateConfirmView",
        action: str,
    ):
        if action == "confirm":
            label = "XP herberekenen"
            emoji = REFRESH_EMOJI
            style = discord.ButtonStyle.danger
        else:
            label = "Annuleren"
            emoji = NONE_EMOJI
            style = discord.ButtonStyle.secondary

        super().__init__(
            label=label,
            emoji=component_emoji(emoji),
            style=style,
        )
        self.owner_view = parent
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if self.action == "cancel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=FeedbackView(
                    "De herberekening is geannuleerd.",
                    kind="info",
                    title="Geannuleerd",
                ),
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )
        await self.owner_view.cog.perform_recalculate(
            interaction,
        )


class RecalculateConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Levels",
        owner_id: int,
        guild_id: int,
        text_rate: int,
        voice_rate: int,
        text_enabled: bool,
        voice_enabled: bool,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.guild_id = guild_id

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} XP herberekenen\n"
                    "> └ Dit vervangt de huidige `total_xp` van alle leden.\n\n"
                    "## Formule\n"
                    f"> └ Berichten × **{text_rate} XP** "
                    f"({'aan' if text_enabled else 'uit'})\n"
                    f"> └ Volledige voice-minuten × **{voice_rate} XP** "
                    f"({'aan' if voice_enabled else 'uit'})\n\n"
                    "## Belangrijk\n"
                    "> └ Andere XP-bronnen zoals waves, invites, reacties, "
                    "suggesties, verjaardagen en handmatige XP tellen daarna "
                    "**niet** meer mee in `total_xp`.\n"
                    "> └ De opgeslagen aantallen berichten en voice-tijd "
                    "blijven behouden."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    RecalculateButton(
                        self,
                        "confirm",
                    ),
                    RecalculateButton(
                        self,
                        "cancel",
                    ),
                ),
                accent_colour=discord.Colour.from_rgb(
                    254,
                    231,
                    92,
                ),
            )
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.user.id == self.owner_id
            and isinstance(interaction.user, discord.Member)
            and is_admin(interaction.user)
        ):
            return True

        await self.cog.send_feedback(
            interaction,
            "Dit bevestigingsmenu is niet van jou.",
            kind="error",
        )
        return False


class Levels(commands.Cog):
    levels = app_commands.Group(name="levels", description="Beheer het LEVENLOOS levelsysteem.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_last_xp: dict[tuple[int, int], float] = {}
        self.voice_sessions: dict[tuple[int, int], tuple[int, float]] = {}
        self.invite_cache: dict[int, dict[str, tuple[int, int]]] = {}
        self._voice_lock = asyncio.Lock()

    async def cog_load(self):
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Levels vereist discord.py 2.6+ voor Components V2."
            )

        await init_db()
        for guild in self.bot.guilds:
            await self.ensure_defaults(guild.id)
        asyncio.create_task(self._delayed_ready())

    async def _delayed_ready(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self.ensure_defaults(guild.id)
            await self.seed_default_roles(guild)
            await self.cache_invites(guild)
        await self.refresh_all_voice()

    async def ensure_defaults(self, guild_id: int):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for key, value in DEFAULTS.items():
                await db.execute("INSERT OR IGNORE INTO levels_config (guild_id,key,value) VALUES (?,?,?)", (guild_id, key, value))
            await db.commit()

    async def get_config(self, guild_id: int, key: str) -> str:
        await self.ensure_defaults(guild_id)
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT value FROM levels_config WHERE guild_id=? AND key=?", (guild_id, key))
            row = await cur.fetchone()
        return row[0] if row else DEFAULTS.get(key, "0")

    async def set_config(self, guild_id: int, key: str, value: str):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("INSERT INTO levels_config (guild_id,key,value) VALUES (?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value", (guild_id, key, value))
            await db.commit()

    async def get_int(self, guild_id: int, key: str) -> int:
        try:
            return int(await self.get_config(guild_id, key))
        except ValueError:
            return 0

    async def get_bool(self, guild_id: int, key: str) -> bool:
        return (await self.get_config(guild_id, key)) == "1"

    async def ensure_user(self, guild_id: int, user_id: int):
        now = int(time.time())
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO levels_users (guild_id,user_id,created_at,updated_at) VALUES (?,?,?,?)", (guild_id, user_id, now, now))
            await db.commit()

    async def get_user(self, guild_id: int, user_id: int):
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT total_xp,text_messages,voice_seconds FROM levels_users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            return await cur.fetchone()

    async def set_total_xp(self, guild_id: int, user_id: int, total: int):
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE levels_users SET total_xp=?,updated_at=? WHERE guild_id=? AND user_id=?", (max(0, total), int(time.time()), guild_id, user_id))
            await db.commit()

    async def log_xp(self, guild_id, user_id, source, xp, reference_id=None, actor_id=None) -> bool:
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("INSERT INTO levels_xp_log (guild_id,user_id,source,xp,reference_id,actor_id,created_at) VALUES (?,?,?,?,?,?,?)", (guild_id, user_id, source, xp, reference_id, actor_id, int(time.time())))
                await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def award_source(self, guild: discord.Guild, user_id: int, source: str, reference_id: Optional[str] = None, actor_id: Optional[int] = None) -> int:
        if source not in XP_KEYS:
            return 0
        enabled_key, value_key = XP_KEYS[source]
        if not await self.get_bool(guild.id, enabled_key):
            return 0
        amount = await self.get_int(guild.id, value_key)
        return await self.award_xp(guild, user_id, amount, source, reference_id, actor_id)

    async def award_xp(self, guild: discord.Guild, user_id: int, amount: int, source: str, reference_id: Optional[str] = None, actor_id: Optional[int] = None) -> int:
        if amount == 0:
            return 0
        member = guild.get_member(user_id)
        if member is not None and member.bot:
            return 0
        if reference_id is not None:
            if not await self.log_xp(guild.id, user_id, source, amount, reference_id, actor_id):
                return 0
        elif source not in {"text", "voice"}:
            await self.log_xp(guild.id, user_id, source, amount, None, actor_id)
        await self.ensure_user(guild.id, user_id)
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT total_xp FROM levels_users WHERE guild_id=? AND user_id=?", (guild.id, user_id))
            old_total = (await cur.fetchone())[0]
            new_total = max(0, old_total + amount)
            await db.execute("UPDATE levels_users SET total_xp=?,updated_at=? WHERE guild_id=? AND user_id=?", (new_total, int(time.time()), guild.id, user_id))
            await db.commit()
        if member and level_from_xp(new_total) > level_from_xp(old_total):
            await self.on_level_up(member, level_from_xp(old_total), level_from_xp(new_total))
        return amount

    async def on_level_up(
        self,
        member: discord.Member,
        old_level: int,
        new_level: int,
    ):
        await self.apply_level_roles(member)

        if not await self.get_bool(
            member.guild.id,
            "levelup_enabled",
        ):
            return

        channel_id = await self.get_int(
            member.guild.id,
            "levelup_channel_id",
        )
        channel = member.guild.get_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            return

        try:
            await channel.send(
                view=LevelUpView(
                    member,
                    old_level,
                    new_level,
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Level-up melding versturen mislukt voor user %s.",
                member.id,
            )

    async def excluded(self, guild_id: int, kind: str, target_id: int) -> bool:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT 1 FROM levels_exclusions WHERE guild_id=? AND kind=? AND target_id=?", (guild_id, kind, target_id))
            return await cur.fetchone() is not None

    async def toggle_exclusion(self, guild_id: int, kind: str, target_id: int):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT 1 FROM levels_exclusions WHERE guild_id=? AND kind=? AND target_id=?", (guild_id, kind, target_id))
            if await cur.fetchone():
                await db.execute("DELETE FROM levels_exclusions WHERE guild_id=? AND kind=? AND target_id=?", (guild_id, kind, target_id))
            else:
                await db.execute("INSERT INTO levels_exclusions (guild_id,kind,target_id) VALUES (?,?,?)", (guild_id, kind, target_id))
            await db.commit()

    async def member_excluded(self, member: discord.Member) -> bool:
        for role in member.roles:
            if await self.excluded(member.guild.id, "role", role.id):
                return True
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        await self.ensure_user(message.guild.id, message.author.id)
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE levels_users SET text_messages=text_messages+1,updated_at=? WHERE guild_id=? AND user_id=?", (int(time.time()), message.guild.id, message.author.id))
            await db.commit()
        if not await self.get_bool(message.guild.id, "xp_text_enabled"):
            return
        if await self.excluded(message.guild.id, "text_channel", message.channel.id) or await self.member_excluded(message.author):
            return
        cooldown = await self.get_int(message.guild.id, "text_cooldown")
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if now - self.message_last_xp.get(key, 0) < cooldown:
            return
        self.message_last_xp[key] = now
        await self.award_xp(message.guild, message.author.id, await self.get_int(message.guild.id, "xp_text"), "text")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or self.bot.user and payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild or not await self.get_bool(guild.id, "xp_reaction_enabled"):
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel) or await self.excluded(guild.id, "text_channel", channel.id):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        if message.author.bot or message.author.id == payload.user_id:
            return
        reactor = guild.get_member(payload.user_id)
        if reactor is None or reactor.bot or await self.member_excluded(reactor):
            return
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("INSERT INTO levels_reaction_awards (guild_id,message_id,reactor_id,author_id,created_at) VALUES (?,?,?,?,?)", (guild.id, message.id, payload.user_id, message.author.id, int(time.time())))
                await db.commit()
        except aiosqlite.IntegrityError:
            return
        await self.award_source(guild, message.author.id, "reaction", f"reaction:{message.id}:{payload.user_id}", payload.user_id)

    async def settle_voice_channels(self, guild: discord.Guild, channel_ids: set[int]):
        async with self._voice_lock:
            now = time.monotonic()
            affected = [(key, data) for key, data in list(self.voice_sessions.items()) if key[0] == guild.id and data[0] in channel_ids]
            for (gid, uid), (cid, started) in affected:
                delta = max(0, int(now - started))
                if delta:
                    await self.add_voice_seconds(guild, uid, delta)
                self.voice_sessions.pop((gid, uid), None)
            for cid in channel_ids:
                channel = guild.get_channel(cid)
                if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    continue
                valid = [m for m in channel.members if not m.bot and not await self.member_excluded(m)]
                if await self.excluded(guild.id, "voice_channel", cid):
                    valid = []
                solo = await self.get_bool(guild.id, "voice_solo")
                if not solo and len(valid) < 2:
                    valid = []
                for member in valid:
                    self.voice_sessions[(guild.id, member.id)] = (cid, now)

    async def add_voice_seconds(self, guild: discord.Guild, user_id: int, seconds: int):
        await self.ensure_user(guild.id, user_id)
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT voice_seconds,total_xp FROM levels_users WHERE guild_id=? AND user_id=?", (guild.id, user_id))
            old_seconds, old_xp = await cur.fetchone()
            new_seconds = old_seconds + seconds
            xp_add = 0
            if await self.get_bool(guild.id, "xp_voice_enabled"):
                rate = await self.get_int(guild.id, "xp_voice_per_minute")
                xp_add = (new_seconds // 60 - old_seconds // 60) * rate
            new_xp = old_xp + xp_add
            await db.execute("UPDATE levels_users SET voice_seconds=?,total_xp=?,updated_at=? WHERE guild_id=? AND user_id=?", (new_seconds, new_xp, int(time.time()), guild.id, user_id))
            await db.commit()
        member = guild.get_member(user_id)
        if member and level_from_xp(new_xp) > level_from_xp(old_xp):
            await self.on_level_up(member, level_from_xp(old_xp), level_from_xp(new_xp))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        ids = set()
        if before.channel:
            ids.add(before.channel.id)
        if after.channel:
            ids.add(after.channel.id)
        if ids:
            await self.settle_voice_channels(member.guild, ids)

    async def refresh_all_voice(self, guild_id: Optional[int] = None):
        guilds = [self.bot.get_guild(guild_id)] if guild_id else self.bot.guilds
        for guild in guilds:
            if not guild:
                continue
            ids = {c.id for c in guild.voice_channels}
            if ids:
                await self.settle_voice_channels(guild, ids)

    async def cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self.invite_cache[guild.id] = {i.code: (i.uses or 0, i.inviter.id if i.inviter else 0) for i in invites}

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        before = self.invite_cache.get(member.guild.id, {})
        try:
            invites = await member.guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        used_inviter = None
        for invite in invites:
            old_uses = before.get(invite.code, (0, 0))[0]
            if (invite.uses or 0) > old_uses:
                used_inviter = invite.inviter
                break
        self.invite_cache[member.guild.id] = {i.code: (i.uses or 0, i.inviter.id if i.inviter else 0) for i in invites}
        if used_inviter and not used_inviter.bot:
            await self.award_source(member.guild, used_inviter.id, "invite", f"invite_join:{member.id}", member.id)

    @commands.Cog.listener()
    async def on_suggestion_created(
        self,
        guild: discord.Guild,
        author_id: int,
        suggestion_id: int,
    ):
        await self.award_source(
            guild,
            author_id,
            "suggestion",
            f"suggestion:{suggestion_id}:created",
        )

    @commands.Cog.listener()
    async def on_suggestion_vote(
        self,
        guild: discord.Guild,
        voter_id: int,
        suggestion_id: int,
    ):
        await self.award_source(
            guild,
            voter_id,
            "suggestion_vote",
            f"suggestion:{suggestion_id}:vote:{voter_id}",
        )

    @commands.Cog.listener()
    async def on_suggestion_accepted(
        self,
        guild: discord.Guild,
        author_id: int,
        suggestion_id: int,
    ):
        await self.award_source(
            guild,
            author_id,
            "suggestion_success",
            f"suggestion:{suggestion_id}:success",
        )

    async def seed_default_roles(self, guild: discord.Guild):
        defaults = [(10, "Verslaafd", 0), (25, "Slaaploos", 0), (50, "Levenloos", 1), (100, "Needs Help", 1)]
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT COUNT(*) FROM levels_roles WHERE guild_id=?", (guild.id,))
            if (await cur.fetchone())[0] == 0:
                for lvl, name, keep in defaults:
                    role = discord.utils.find(lambda r: r.name.lower() == name.lower(), guild.roles)
                    if role:
                        await db.execute("INSERT OR IGNORE INTO levels_roles (guild_id,level,role_id,keep_previous) VALUES (?,?,?,?)", (guild.id, lvl, role.id, keep))
                await db.commit()

    async def get_level_roles(self, guild_id: int):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT level,role_id,keep_previous FROM levels_roles WHERE guild_id=? ORDER BY level", (guild_id,))
            return await cur.fetchall()

    async def apply_level_roles(self, member: discord.Member) -> int:
        if not await self.get_bool(member.guild.id, "level_roles_enabled"):
            return 0
        row = await self.get_user(member.guild.id, member.id)
        level = level_from_xp(row[0])
        roles_cfg = await self.get_level_roles(member.guild.id)
        if not roles_cfg:
            return 0
        eligible = [(lvl, rid, keep) for lvl, rid, keep in roles_cfg if lvl <= level]
        wanted_ids = set()
        if eligible:
            highest = eligible[-1]
            wanted_ids.add(highest[1])
            for lvl, rid, keep in eligible:
                if keep:
                    wanted_ids.add(rid)
        all_ids = {rid for _, rid, _ in roles_cfg}
        add = [member.guild.get_role(rid) for rid in wanted_ids if member.guild.get_role(rid) and rid not in {r.id for r in member.roles}]
        remove = [r for r in member.roles if r.id in all_ids and r.id not in wanted_ids]
        changed = len(add) + len(remove)
        try:
            if add:
                await member.add_roles(*add, reason="LEVENLOOS levelrollen")
            if remove:
                await member.remove_roles(*remove, reason="LEVENLOOS levelrollen")
        except (discord.Forbidden, discord.HTTPException):
            return 0
        return changed



    # ========================================================
    # COMPONENTS V2 FEEDBACK
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
    # RENDER HELPERS
    # ========================================================

    def config_home_text(self) -> str:
        return (
            f"# {LEVEL_BADGE}\n"
            "## Levels Config\n"
            "> └ Beheer hier het volledige levelsysteem."
        )

    async def render_toggle_panel(
        self,
        guild_id: int,
    ) -> str:
        lines = [
            f"# {LEVEL_BADGE}",
            "## XP-functies",
        ]

        for source, (enabled_key, _) in XP_KEYS.items():
            enabled = await self.get_bool(
                guild_id,
                enabled_key,
            )
            lines.append(
                f"> └ **{SOURCE_LABELS[source]}:** "
                f"{'Aan' if enabled else 'Uit'}"
            )

        return "\n".join(lines)

    async def render_values_panel(
        self,
        guild_id: int,
    ) -> str:
        lines = [
            f"# {LEVEL_BADGE}",
            "## XP-waardes",
        ]

        for source, (_, value_key) in XP_KEYS.items():
            value = await self.get_int(
                guild_id,
                value_key,
            )
            suffix = "/min" if source == "voice" else ""
            lines.append(
                f"> └ **{SOURCE_LABELS[source]}:** "
                f"{value} XP{suffix}"
            )

        return "\n".join(lines)

    async def render_text_panel(
        self,
        guild_id: int,
    ) -> str:
        return (
            f"# {LEVEL_BADGE}\n"
            "## Tekst XP\n"
            f"> └ XP per bericht: "
            f"**{await self.get_int(guild_id, 'xp_text')} XP**\n"
            f"> └ Cooldown: "
            f"**{await self.get_int(guild_id, 'text_cooldown')} seconden**\n\n"
            "## Statistieken\n"
            "> └ Berichten blijven altijd meetellen voor activiteit, "
            "ook wanneer de cooldown geen XP geeft."
        )

    async def render_voice_panel(
        self,
        guild_id: int,
    ) -> str:
        return (
            f"# {LEVEL_BADGE}\n"
            "## Voice XP\n"
            f"> └ XP per minuut: "
            f"**{await self.get_int(guild_id, 'xp_voice_per_minute')} XP**\n"
            f"> └ Solo voice: "
            f"**{'Aan' if await self.get_bool(guild_id, 'voice_solo') else 'Uit'}**\n\n"
            "## Tellen\n"
            "> └ Standaard telt voice alleen wanneer minimaal "
            "twee geldige gebruikers samen in voice zitten."
        )

    async def render_notifications(
        self,
        guild_id: int,
    ) -> str:
        channel_id = await self.get_int(
            guild_id,
            "levelup_channel_id",
        )

        return (
            f"# {LEVEL_BADGE}\n"
            "## Meldingen\n"
            f"> └ Level-up meldingen: "
            f"**{'Aan' if await self.get_bool(guild_id, 'levelup_enabled') else 'Uit'}**\n"
            f"> └ Kanaal: "
            f"{f'<#{channel_id}>' if channel_id else 'Niet ingesteld'}"
        )

    async def get_exclusion_counts(
        self,
        guild_id: int,
    ) -> dict[str, int]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT kind, COUNT(*)
                FROM levels_exclusions
                WHERE guild_id = ?
                GROUP BY kind
                """,
                (guild_id,),
            )
            return {
                str(kind): int(count)
                for kind, count in await cursor.fetchall()
            }

    async def render_exclusions(
        self,
        guild_id: int,
    ) -> str:
        counts = await self.get_exclusion_counts(
            guild_id
        )

        return (
            f"# {LEVEL_BADGE}\n"
            "## XP-uitsluitingen\n"
            f"> └ Tekstkanalen: "
            f"**{counts.get('text_channel', 0)}**\n"
            f"> └ Voicekanalen: "
            f"**{counts.get('voice_channel', 0)}**\n"
            f"> └ Rollen: "
            f"**{counts.get('role', 0)}**"
        )

    async def render_status(
        self,
        guild_id: int,
    ) -> str:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(total_xp), 0),
                    COALESCE(SUM(text_messages), 0),
                    COALESCE(SUM(voice_seconds), 0)
                FROM levels_users
                WHERE guild_id = ?
                """,
                (guild_id,),
            )

            users, xp, messages, voice = (
                await cursor.fetchone()
            )

        roles_enabled = await self.get_bool(
            guild_id,
            "level_roles_enabled",
        )

        return (
            f"# {LEVEL_BADGE}\n"
            "## Levels Status\n"
            f"> └ {SUCCESS_EMOJI} Systeem actief\n"
            "> └ Database: `levels.db`\n\n"
            "## Statistieken\n"
            f"> └ Spelers geregistreerd: **{users}**\n"
            f"> └ Totale XP: **{fmt_num(xp)}**\n"
            f"> └ Berichten geregistreerd: **{fmt_num(messages)}**\n"
            f"> └ Voice geregistreerd: **{fmt_hours(voice)} uur**\n\n"
            "## Levelrollen\n"
            f"> └ Eigen botrollen: "
            f"**{'Aan' if roles_enabled else 'Uit'}**"
        )

    async def render_user_manage(
        self,
        member: discord.Member,
    ) -> str:
        total, messages, voice = await self.get_user(
            member.guild.id,
            member.id,
        )

        return (
            f"# {LEVEL_BADGE}\n"
            f"## {discord.utils.escape_markdown(member.display_name)}\n"
            f"> └ {LEVEL_UP_ICON} Level "
            f"**{level_from_xp(total)}**\n"
            f"> └ Rank "
            f"**#{await self.rank_for_user(member.guild.id, member.id)}**\n"
            f"> └ **{fmt_num(total)} XP**\n\n"
            "## Activiteit\n"
            f"> └ Berichten: **{fmt_num(messages)}**\n"
            f"> └ Voice: **{fmt_hours(voice)} uur**"
        )

    async def render_history(
        self,
        guild_id: int,
        user_id: int,
    ) -> str:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT
                    source,
                    xp,
                    actor_id,
                    created_at
                FROM levels_xp_log
                WHERE guild_id = ?
                  AND user_id = ?
                ORDER BY id DESC
                LIMIT 15
                """,
                (
                    guild_id,
                    user_id,
                ),
            )
            rows = await cursor.fetchall()

        if not rows:
            return "Er zijn nog geen bijzondere XP-transacties."

        lines = []

        for source, xp, actor_id, created_at in rows:
            sign = "+" if xp >= 0 else ""
            label = SOURCE_LABELS.get(
                source,
                source.replace("_", " ").title(),
            )
            actor = (
                f" • door <@{actor_id}>"
                if actor_id and source == "manual"
                else ""
            )
            lines.append(
                f"{sign}{fmt_num(xp)} XP • {label}{actor}"
            )

        return "\n".join(lines)

    async def rank_for_user(
        self,
        guild_id: int,
        user_id: int,
    ):
        rows = await self.leaderboard_rows(
            guild_id,
            "xp",
        )

        for index, row in enumerate(
            rows,
            start=1,
        ):
            if row[0] == user_id:
                return index

        return 0

    async def get_xp_source_totals(
        self,
        guild_id: int,
        user_id: int,
    ) -> dict[str, int]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT
                    source,
                    COALESCE(SUM(xp), 0)
                FROM levels_xp_log
                WHERE guild_id = ?
                  AND user_id = ?
                GROUP BY source
                """,
                (
                    guild_id,
                    user_id,
                ),
            )

            return {
                source: int(total)
                for source, total in await cursor.fetchall()
            }

    async def render_profile(
        self,
        member: discord.Member,
        *,
        banner: str = LEVEL_BADGE,
        header_icon: str = LEVEL_UP_ICON,
        show_avatar: bool = False,
    ) -> LevelProfileView:
        total, messages, voice = await self.get_user(
            member.guild.id,
            member.id,
        )

        level = level_from_xp(total)
        rank = await self.rank_for_user(
            member.guild.id,
            member.id,
        )
        next_xp = xp_for_level(level + 1)
        needed = max(
            0,
            next_xp - total,
        )
        _, percent, progress, span = progress_bar(
            total,
            level,
        )
        source_totals = await self.get_xp_source_totals(
            member.guild.id,
            member.id,
        )

        return LevelProfileView(
            member,
            level=level,
            rank=rank,
            total=total,
            messages=messages,
            voice=voice,
            progress=progress,
            span=span,
            percent=percent,
            needed=needed,
            source_totals=source_totals,
            banner=banner,
            header_icon=header_icon,
            show_avatar=show_avatar,
        )

    async def leaderboard_rows(
        self,
        guild_id: int,
        sort_key: str,
    ):
        order = {
            "xp": "total_xp",
            "messages": "text_messages",
            "voice": "voice_seconds",
        }.get(
            sort_key,
            "total_xp",
        )

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                f"""
                SELECT
                    user_id,
                    total_xp,
                    text_messages,
                    voice_seconds
                FROM levels_users
                WHERE guild_id = ?
                ORDER BY
                    {order} DESC,
                    total_xp DESC,
                    user_id ASC
                """,
                (guild_id,),
            )
            rows = await cursor.fetchall()

        guild = self.bot.get_guild(
            guild_id
        )

        if guild is None:
            return rows

        return [
            row
            for row in rows
            if (
                (member := guild.get_member(row[0]))
                is not None
                and not member.bot
            )
        ]

    async def render_leaderboard(
        self,
        guild_id: int,
        sort_key: str = "xp",
        page: int = 0,
    ) -> tuple[str, int, int]:
        rows = await self.leaderboard_rows(
            guild_id,
            sort_key,
        )

        pages = max(
            1,
            math.ceil(len(rows) / 10),
        )
        page = max(
            0,
            min(
                page,
                pages - 1,
            ),
        )

        start = page * 10
        end = min(
            start + 10,
            len(rows),
        )

        titles = {
            "xp": f"{XP_EMOJI} Totale XP",
            "messages": "Berichten",
            "voice": "Voice",
        }

        guild = self.bot.get_guild(
            guild_id
        )

        lines = [
            f"# {LEADERBOARD_BADGE}",
            f"## {titles.get(sort_key, 'Totale XP')}",
            f"> └ Top "
            f"{start + 1 if rows else 0}-{end} "
            f"van **{len(rows)} spelers**",
            "",
        ]

        for index, row in enumerate(
            rows[start:end],
            start=start + 1,
        ):
            user_id, total, messages, voice = row
            member = (
                guild.get_member(user_id)
                if guild
                else None
            )
            name = (
                discord.utils.escape_markdown(
                    member.display_name
                )
                if member
                else f"Onbekende gebruiker ({user_id})"
            )
            level = level_from_xp(total)

            lines.append(
                f"**#{index} {name}**"
            )

            if sort_key == "messages":
                lines.append(
                    f"> └ **{fmt_num(messages)} berichten** • "
                    f"{LEVEL_UP_ICON} Level **{level}** • "
                    f"{XP_EMOJI} {fmt_num(total)} XP • "
                    f"{fmt_hours(voice)}u voice"
                )
            elif sort_key == "voice":
                lines.append(
                    f"> └ **{fmt_hours(voice)} uur voice** • "
                    f"{LEVEL_UP_ICON} Level **{level}** • "
                    f"{XP_EMOJI} {fmt_num(total)} XP • "
                    f"{fmt_num(messages)} berichten"
                )
            else:
                lines.append(
                    f"> └ {LEVEL_UP_ICON} Level **{level}** • "
                    f"{XP_EMOJI} **{fmt_num(total)} XP** • "
                    f"{fmt_num(messages)} berichten • "
                    f"{fmt_hours(voice)}u voice"
                )

        if not rows:
            lines.append(
                "> └ Er zijn nog geen levelgegevens beschikbaar."
            )

        return "\n".join(lines), pages, page

    async def page_for_user(self, guild_id, user_id, sort_key):
        rows = await self.leaderboard_rows(guild_id, sort_key)
        for i, row in enumerate(rows):
            if row[0] == user_id:
                return i // 10
        return 0

    def load_import_json(self):
        if not IMPORT_PATH.exists():
            raise FileNotFoundError(str(IMPORT_PATH))
        return json.loads(IMPORT_PATH.read_text(encoding="utf-8"))

    def match_import(self, guild: discord.Guild):
        data = self.load_import_json()
        matched, unmatched, duplicates = [], [], []
        for row in data:
            username = str(
                row.get("username", "")
            ).strip().lower()
            username = IMPORT_USERNAME_ALIASES.get(
                username,
                username,
            )
            candidates = []
            for member in guild.members:
                if member.bot:
                    continue
                names = {member.name.lower(), member.display_name.lower()}
                if getattr(member, "global_name", None):
                    names.add(member.global_name.lower())
                if username in names:
                    candidates.append(member)
            if len(candidates) == 1:
                matched.append((row, candidates[0]))
            elif not candidates:
                unmatched.append(row)
            else:
                duplicates.append((row, candidates))
        return matched, unmatched, duplicates

    async def run_import(self, guild: discord.Guild):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cur = await db.execute("SELECT 1 FROM levels_imports WHERE guild_id=? AND import_name='activityrank'", (guild.id,))
            if await cur.fetchone():
                return "⚠️ De ActivityRank-import is al uitgevoerd."
        matched, unmatched, duplicates = self.match_import(guild)
        now = int(time.time())
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for row, member in matched:
                total = int(row["total_xp"])
                messages = int(row.get("messages", 0))
                voice_seconds = int(round(float(row.get("voice_hours", 0)) * 3600))
                await db.execute(
                    "INSERT INTO levels_users (guild_id,user_id,total_xp,text_messages,voice_seconds,created_at,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET total_xp=excluded.total_xp,text_messages=excluded.text_messages,voice_seconds=excluded.voice_seconds,updated_at=excluded.updated_at",
                    (guild.id, member.id, total, messages, voice_seconds, now, now),
                )
                await db.execute("INSERT OR IGNORE INTO levels_xp_log (guild_id,user_id,source,xp,reference_id,created_at) VALUES (?,?,?,?,?,?)", (guild.id, member.id, "legacy_import", total, f"activityrank:{member.id}", now))
            await db.execute("INSERT INTO levels_imports (guild_id,import_name,imported_at,rows_imported) VALUES (?,?,?,?)", (guild.id, "activityrank", now, len(matched)))
            await db.commit()
        return f"✅ **ACTIVITYRANK IMPORT VOLTOOID**\n\nGeïmporteerd: **{len(matched)}** leden\nOvergeslagen: **{len(unmatched)}**\nOnduidelijk: **{len(duplicates)}**\n\nHistorische XP is opgeslagen in `levels.db`."



    # ========================================================
    # PUBLIC COMMANDS
    # ========================================================

    async def send_profile(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
        *,
        xp_profile: bool = False,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        target = member or interaction.user

        if (
            not isinstance(target, discord.Member)
            or target.bot
        ):
            await self.send_feedback(
                interaction,
                "Bots nemen niet deel aan het levelsysteem.",
                kind="error",
            )
            return

        view = await self.render_profile(
            target,
            banner=XP_BADGE if xp_profile else LEVEL_BADGE,
            header_icon=LEVEL_UP_ICON,
            show_avatar=xp_profile,
        )

        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name="level",
        description="Bekijk je level, XP en activiteit.",
    )
    async def level_cmd(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        await self.send_profile(
            interaction,
            member,
        )

    @app_commands.command(
        name="xp",
        description="Bekijk snel je huidige XP en level.",
    )
    async def xp_cmd(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        await self.send_profile(
            interaction,
            member,
            xp_profile=True,
        )

    @app_commands.command(
        name="top",
        description="Bekijk het LEVENLOOS leaderboard.",
    )
    async def top_cmd(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        view = await LeaderboardView.create(
            self,
            interaction.guild.id,
            interaction.user.id,
        )

        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ========================================================
    # ADMIN COMMANDS
    # ========================================================

    @levels.command(
        name="config",
        description="Open het levels configuratiepaneel.",
    )
    async def levels_config(
        self,
        interaction: discord.Interaction,
    ):
        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om het levelsysteem te beheren.",
                kind="error",
            )
            return

        await interaction.response.send_message(
            view=await ConfigView.create(
                self,
                interaction.user.id,
                interaction.guild.id,
            ),
            ephemeral=True,
        )

    @levels.command(
        name="status",
        description="Bekijk de status van het levelsysteem.",
    )
    async def levels_status(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen in een server.",
                kind="error",
            )
            return

        await interaction.response.send_message(
            view=SimplePanelView(
                "Levels Status",
                await self.render_status(
                    interaction.guild.id
                ),
                icon=LEVEL_UP_ICON,
            ),
            ephemeral=True,
        )

    @levels.command(
        name="herbereken-xp",
        description="Herbereken alle XP uit berichten en voice-tijd.",
    )
    @app_commands.describe(
        bevestigen="Optioneel: direct uitvoeren zonder bevestigingsknop.",
    )
    async def recalculate_xp(
        self,
        interaction: discord.Interaction,
        bevestigen: bool = False,
    ):
        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
            )
            return

        guild = interaction.guild

        if bevestigen:
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )
            await self.perform_recalculate(
                interaction
            )
            return

        text_rate = await self.get_int(
            guild.id,
            "xp_text",
        )
        voice_rate = await self.get_int(
            guild.id,
            "xp_voice_per_minute",
        )
        text_enabled = await self.get_bool(
            guild.id,
            "xp_text_enabled",
        )
        voice_enabled = await self.get_bool(
            guild.id,
            "xp_voice_enabled",
        )

        await interaction.response.send_message(
            view=RecalculateConfirmView(
                self,
                interaction.user.id,
                guild.id,
                text_rate,
                voice_rate,
                text_enabled,
                voice_enabled,
            ),
            ephemeral=True,
        )

    async def perform_recalculate(
        self,
        interaction: discord.Interaction,
    ):
        guild = interaction.guild

        if guild is None:
            return

        text_rate = await self.get_int(
            guild.id,
            "xp_text",
        )
        voice_rate = await self.get_int(
            guild.id,
            "xp_voice_per_minute",
        )
        text_enabled = await self.get_bool(
            guild.id,
            "xp_text_enabled",
        )
        voice_enabled = await self.get_bool(
            guild.id,
            "xp_voice_enabled",
        )

        await self.refresh_all_voice(
            guild.id
        )

        now = int(time.time())
        members = [
            member
            for member in guild.members
            if not member.bot
        ]
        member_ids = {
            member.id
            for member in members
        }

        async with aiosqlite.connect(DATABASE_PATH) as db:
            for member in members:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO levels_users (
                        guild_id,
                        user_id,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        guild.id,
                        member.id,
                        now,
                        now,
                    ),
                )
            await db.commit()

        changed = 0
        total_before = 0
        total_after = 0
        role_changes = 0

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT
                    user_id,
                    total_xp,
                    text_messages,
                    voice_seconds
                FROM levels_users
                WHERE guild_id = ?
                """,
                (guild.id,),
            )
            rows = await cursor.fetchall()

            for (
                user_id,
                old_xp,
                messages,
                voice_seconds,
            ) in rows:
                if user_id not in member_ids:
                    continue

                message_xp = (
                    int(messages) * text_rate
                    if text_enabled
                    else 0
                )
                voice_xp = (
                    (int(voice_seconds) // 60)
                    * voice_rate
                    if voice_enabled
                    else 0
                )
                new_xp = max(
                    0,
                    message_xp + voice_xp,
                )

                total_before += int(old_xp)
                total_after += new_xp

                if new_xp != int(old_xp):
                    changed += 1

                await db.execute(
                    """
                    UPDATE levels_users
                    SET
                        total_xp = ?,
                        updated_at = ?
                    WHERE guild_id = ?
                      AND user_id = ?
                    """,
                    (
                        new_xp,
                        now,
                        guild.id,
                        user_id,
                    ),
                )

            await db.commit()

        if await self.get_bool(
            guild.id,
            "level_roles_enabled",
        ):
            for member in members:
                role_changes += await self.apply_level_roles(
                    member
                )

        await self.send_feedback(
            interaction,
            (
                f"Leden verwerkt: **{len(members)}**\n"
                f"XP gewijzigd bij: **{changed}** leden\n"
                f"Totaal vóór: **{fmt_num(total_before)} XP**\n"
                f"Totaal na: **{fmt_num(total_after)} XP**\n"
                f"Berichten × **{text_rate} XP**\n"
                f"Voice-minuten × **{voice_rate} XP**\n"
                f"Levelrol-wijzigingen: **{role_changes}**"
            ),
            kind="success",
            title="XP herberekend",
        )

    @levels.command(
        name="import-preview",
        description="Controleer de ActivityRank import zonder iets te wijzigen.",
    )
    async def import_preview(
        self,
        interaction: discord.Interaction,
    ):
        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
            )
            return

        try:
            (
                matched,
                unmatched,
                duplicates,
            ) = self.match_import(
                interaction.guild
            )
        except FileNotFoundError:
            await self.send_feedback(
                interaction,
                "`activityrank_import.json` staat niet in de botmap.",
                kind="error",
            )
            return

        await interaction.response.send_message(
            view=ImportPreviewView(
                self,
                interaction.user.id,
                interaction.guild.id,
                matched,
                unmatched,
                duplicates,
            ),
            ephemeral=True,
        )

    @levels.command(
        name="import",
        description="Importeer de ActivityRank historie naar levels.db.",
    )
    async def import_cmd(
        self,
        interaction: discord.Interaction,
    ):
        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
            )
            return

        await interaction.response.send_message(
            view=ImportConfirmView(
                self,
                interaction.user.id,
                interaction.guild.id,
            ),
            ephemeral=True,
        )

    @levels.command(
        name="xp",
        description="Beheer handmatig XP van een gebruiker.",
    )
    @app_commands.describe(
        member="Gebruiker",
        actie="add, remove of set",
    )
    async def manual_xp(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        actie: str,
    ):
        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
            )
            return

        if member.bot:
            await self.send_feedback(
                interaction,
                "Bots nemen niet deel aan het levelsysteem.",
                kind="error",
            )
            return

        mode = actie.lower().strip()

        if mode not in {
            "add",
            "remove",
            "set",
        }:
            await self.send_feedback(
                interaction,
                "Gebruik `add`, `remove` of `set`.",
                kind="error",
            )
            return

        await interaction.response.send_modal(
            ManualXpModal(
                self,
                interaction.guild.id,
                member.id,
                mode,
            )
        )

    @levels.command(
        name="role-set",
        description="Koppel een Discordrol aan een level.",
    )
    async def role_set(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 2, 999],
        role: discord.Role,
        keep_previous: bool = False,
    ):
        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
            )
            return

        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO levels_roles (
                    guild_id,
                    level,
                    role_id,
                    keep_previous
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, level)
                DO UPDATE SET
                    role_id = excluded.role_id,
                    keep_previous = excluded.keep_previous
                """,
                (
                    interaction.guild.id,
                    level,
                    role.id,
                    int(keep_previous),
                ),
            )
            await db.commit()

        await self.send_feedback(
            interaction,
            f"{role.mention} is ingesteld voor level **{level}**.",
            kind="success",
            title="Levelrol ingesteld",
        )

    @levels.command(
        name="role-remove",
        description="Verwijder een levelrol.",
    )
    async def role_remove(
        self,
        interaction: discord.Interaction,
        level: int,
    ):
        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not is_admin(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toestemming om dit te doen.",
                kind="error",
            )
            return

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                DELETE FROM levels_roles
                WHERE guild_id = ?
                  AND level = ?
                """,
                (
                    interaction.guild.id,
                    level,
                ),
            )
            await db.commit()

        if cursor.rowcount <= 0:
            await self.send_feedback(
                interaction,
                f"Er is geen levelrol ingesteld voor level **{level}**.",
                kind="warning",
            )
            return

        await self.send_feedback(
            interaction,
            f"De levelrol voor level **{level}** is verwijderd.",
            kind="success",
            title="Levelrol verwijderd",
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
