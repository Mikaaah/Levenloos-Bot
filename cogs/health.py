from __future__ import annotations

import asyncio
import logging
import resource
import shutil
import sqlite3
import time
from pathlib import Path

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIG
# ============================================================

PURPLE = discord.Color.from_rgb(108, 39, 218)
DB_PATH = Path("health.db")
STARTED_AT = time.monotonic()

logger = logging.getLogger(__name__)

DATABASE_PATHS = (
    Path("levenloos.db"),
    Path("levels.db"),
    Path("birthdays.db"),
    Path("profiles.db"),
    Path("lfg.db"),
    Path("adminpanel.db"),
    Path("health.db"),
    Path("voice.db"),
    Path("reminders.db"),
)


# ============================================================
# LEVENLOOS CUSTOM EMOJIS
# ============================================================

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
INFO_EMOJI = "<:info:1547724036107149413>"

REFRESH_EMOJI = "<:refresh:1547724055426244618>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"
STATUS_EMOJI = "<:status:1547738616501899364>"
BOT_EMOJI = "<:bot:1547733042150514748>"

VPS_EMOJI = "<:vps:1547909976138453132>"
DATABASE_EMOJI = "<:database:1547909723498487808>"
MODULES_EMOJI = "<:modules:1547909513808580658>"


# ============================================================
# HELPERS
# ============================================================

def management_access(
    member: discord.Member,
) -> bool:
    if (
        member.guild.owner_id == member.id
        or member.guild_permissions.administrator
    ):
        return True

    return any(
        role.name.casefold() in {"admin", "owner"}
        for role in member.roles
    )


def _format_duration(
    seconds: float,
) -> str:
    seconds = max(
        0,
        int(seconds),
    )

    days, seconds = divmod(
        seconds,
        86400,
    )
    hours, seconds = divmod(
        seconds,
        3600,
    )
    minutes, seconds = divmod(
        seconds,
        60,
    )

    parts = []

    if days:
        parts.append(
            f"{days}d"
        )

    if hours or days:
        parts.append(
            f"{hours}u"
        )

    if minutes or hours or days:
        parts.append(
            f"{minutes}m"
        )

    parts.append(
        f"{seconds}s"
    )

    return " ".join(parts)


def _memory_mb() -> float:
    # Linux ru_maxrss is KiB.
    return (
        resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss
        / 1024
    )


def _system_memory(
) -> tuple[float, float] | None:
    try:
        data: dict[str, int] = {}

        with open(
            "/proc/meminfo",
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                key, value = line.split(
                    ":",
                    1,
                )
                data[key] = int(
                    value.strip().split()[0]
                )

        total = data["MemTotal"] / 1024
        available = (
            data["MemAvailable"] / 1024
        )

        return (
            total - available,
            total,
        )
    except Exception:
        return None


def _quick_check(
    path: Path,
) -> tuple[str, bool, str]:
    try:
        if not path.exists():
            return (
                path.name,
                True,
                "niet aanwezig",
            )

        with sqlite3.connect(
            path,
            timeout=3,
        ) as db:
            row = db.execute(
                "PRAGMA quick_check"
            ).fetchone()

        result = (
            str(row[0])
            if row
            else "onbekend"
        )

        return (
            path.name,
            result.casefold() == "ok",
            result,
        )

    except Exception as exc:
        return (
            path.name,
            False,
            f"{type(exc).__name__}: {exc}",
        )


# ============================================================
# COMPONENTS V2 • FEEDBACK
# ============================================================

class HealthFeedbackView(
    discord.ui.LayoutView
):
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
            accent = discord.Color.from_rgb(
                87,
                242,
                135,
            )
            default_title = "Gelukt"

        elif kind == "error":
            icon = ERROR_EMOJI
            accent = discord.Color.from_rgb(
                237,
                66,
                69,
            )
            default_title = "Fout"

        elif kind == "warning":
            icon = WARNING_EMOJI
            accent = discord.Color.from_rgb(
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
                    f"# {icon} "
                    f"{title or default_title}\n"
                    + "\n".join(lines)
                ),
                accent_colour=accent,
            )
        )


# ============================================================
# CONFIG MODAL
# ============================================================

class HealthConfigModal(
    discord.ui.Modal,
    title="Health Panel • Instellingen",
):
    def __init__(
        self,
        cog: "Health",
        guild_id: int,
        refresh_minutes: int,
        show_loops: bool,
    ):
        super().__init__(
            timeout=300
        )

        self.cog = cog
        self.guild_id = guild_id

        self.interval = discord.ui.RadioGroup(
            options=[
                discord.RadioGroupOption(
                    label=(
                        f"Elke {minutes} "
                        f"minuut{'en' if minutes != 1 else ''}"
                    ),
                    value=str(minutes),
                    default=(
                        minutes == refresh_minutes
                    ),
                )
                for minutes
                in (
                    1,
                    5,
                    10,
                    15,
                )
            ]
        )

        self.details = (
            discord.ui.CheckboxGroup(
                required=False,
                min_values=0,
                max_values=1,
                options=[
                    discord.CheckboxGroupOption(
                        label=(
                            "Background loops "
                            "standaard tonen"
                        ),
                        value="loops",
                        default=show_loops,
                    )
                ],
            )
        )

        self.add_item(
            discord.ui.Label(
                text="Automatisch vernieuwen",
                description=(
                    "Hoe vaak het vaste "
                    "healthbericht wordt bijgewerkt."
                ),
                component=self.interval,
            )
        )

        self.add_item(
            discord.ui.Label(
                text="Extra details",
                description=(
                    "Meer technische informatie "
                    "in het vaste panel."
                ),
                component=self.details,
            )
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True
        )

        minutes = int(
            self.interval.value
        )
        show_loops = (
            "loops"
            in self.details.values
        )

        await self.cog.set_health_config(
            self.guild_id,
            minutes,
            show_loops,
        )

        self.cog.health_loop.change_interval(
            minutes=minutes
        )

        await self.cog.refresh_panel(
            interaction.guild
        )

        await interaction.followup.send(
            view=HealthFeedbackView(
                (
                    f"Auto-refresh: **{minutes} min**\n"
                    f"Loops standaard tonen: "
                    f"**{'ja' if show_loops else 'nee'}**"
                ),
                kind="success",
                title="Health instellingen opgeslagen",
            ),
            ephemeral=True,
        )


# ============================================================
# COMPONENTS V2 • PANEL BUTTONS
# ============================================================

class HealthActionButton(
    discord.ui.Button
):
    def __init__(
        self,
        cog: "Health",
        action: str,
        label: str,
        *,
        emoji: str,
        style: discord.ButtonStyle,
    ):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            custom_id=(
                f"levenloos:health:{action}"
            ),
        )

        self.cog = cog
        self.action = action

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.cog.handle_panel_action(
            interaction,
            self.action,
        )


def health_action_row(
    cog: "Health",
) -> discord.ui.ActionRow:
    return discord.ui.ActionRow(
        HealthActionButton(
            cog,
            "refresh",
            "Vernieuwen",
            emoji=REFRESH_EMOJI,
            style=discord.ButtonStyle.primary,
        ),
        HealthActionButton(
            cog,
            "check",
            "Volledige check",
            emoji=STATUS_EMOJI,
            style=discord.ButtonStyle.secondary,
        ),
        HealthActionButton(
            cog,
            "info",
            "Wat wordt gecheckt?",
            emoji=INFO_EMOJI,
            style=discord.ButtonStyle.secondary,
        ),
        HealthActionButton(
            cog,
            "config",
            "Instellingen",
            emoji=SETTINGS_EMOJI,
            style=discord.ButtonStyle.secondary,
        ),
    )


class HealthPersistentRegistrationView(
    discord.ui.LayoutView
):
    """Alleen voor persistent custom_id-herstel na een restart."""

    def __init__(
        self,
        cog: "Health",
    ):
        super().__init__(
            timeout=None
        )

        self.add_item(
            health_action_row(
                cog
            )
        )


# ============================================================
# COMPONENTS V2 • INFO
# ============================================================

class HealthInfoView(
    discord.ui.LayoutView
):
    def __init__(
        self,
    ):
        super().__init__(
            timeout=300
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {INFO_EMOJI} Health checks\n"
                    "> └ Een snelle technische controle "
                    "van de belangrijkste onderdelen van de bot."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=(
                        discord.SeparatorSpacing.small
                    ),
                ),
                discord.ui.TextDisplay(
                    f"## {BOT_EMOJI} Discord\n"
                    "> └ Ping / latency\n"
                    "> └ Geladen extensions en cogs\n"
                    "> └ Geregistreerde async taken"
                ),
                discord.ui.TextDisplay(
                    f"## {VPS_EMOJI} VPS\n"
                    "> └ Proces-RAM\n"
                    "> └ Totale VPS RAM\n"
                    "> └ Schijfgebruik\n"
                    "> └ Bot-uptime"
                ),
                discord.ui.TextDisplay(
                    f"## {DATABASE_EMOJI} Databases\n"
                    "> └ `PRAGMA quick_check` op alle "
                    "bekende SQLite-databases\n"
                    "> └ Een database die nog niet bestaat "
                    "wordt niet automatisch als fout gezien"
                ),
                discord.ui.TextDisplay(
                    f"## {MODULES_EMOJI} Volledige check\n"
                    "> └ Toont ook alle gevonden "
                    "`tasks.Loop` processen\n"
                    "> └ Zo zijn gestopte background loops "
                    "direct zichtbaar"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=(
                        discord.SeparatorSpacing.small
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# Dit panel is een snelle indicatie. "
                    "Het vervangt geen volledige VPS-monitoring."
                ),
                accent_colour=PURPLE,
            )
        )


# ============================================================
# COMPONENTS V2 • HEALTH DASHBOARD
# ============================================================

class HealthDashboardView(
    discord.ui.LayoutView
):
    def __init__(
        self,
        cog: "Health",
        data: dict,
        *,
        full: bool,
        persistent: bool,
    ):
        super().__init__(
            timeout=(
                None
                if persistent
                else 300
            )
        )

        score = data["score"]

        if score >= 85:
            state_emoji = SUCCESS_EMOJI
            state_text = "Gezond"
            accent = discord.Color.from_rgb(
                87,
                242,
                135,
            )
        elif score >= 60:
            state_emoji = WARNING_EMOJI
            state_text = "Aandacht"
            accent = discord.Color.from_rgb(
                254,
                231,
                92,
            )
        else:
            state_emoji = ERROR_EMOJI
            state_text = "Probleem"
            accent = discord.Color.from_rgb(
                237,
                66,
                69,
            )

        if data["sys_mem"] is not None:
            used, total = data["sys_mem"]
            system_memory_text = (
                f"**{used:.0f}/{total:.0f} MB**"
            )
        else:
            system_memory_text = (
                "**onbekend**"
            )

        db_lines = []

        for (
            name,
            ok,
            result,
        ) in data["checks"]:
            icon = (
                SUCCESS_EMOJI
                if ok
                else ERROR_EMOJI
            )

            db_lines.append(
                f"> └ {icon} `{name}` — {result}"
            )

        children: list[
            discord.ui.Item
        ] = [
            discord.ui.TextDisplay(
                f"# {STATUS_EMOJI} LEVENLOOS Health\n"
                f"> └ {state_emoji} Status: "
                f"**{state_text}**\n"
                f"> └ Health score: **{score}/100**\n"
                f"> └ Uptime: **{data['uptime']}**"
            ),
            discord.ui.Separator(
                visible=True,
                spacing=(
                    discord.SeparatorSpacing.small
                ),
            ),
            discord.ui.TextDisplay(
                f"## {BOT_EMOJI} Discord\n"
                f"> └ Ping: **{data['ping']} ms**\n"
                f"> └ Extensions: **{data['loaded']}**\n"
                f"> └ Cogs: **{data['cogs']}**\n"
                f"> └ Async tasks: **{data['task_count']}**"
            ),
            discord.ui.TextDisplay(
                f"## {VPS_EMOJI} VPS\n"
                f"> └ Proces-RAM: "
                f"**{data['memory']:.1f} MB**\n"
                f"> └ VPS RAM: {system_memory_text}\n"
                f"> └ Disk: **{data['disk_used']:.1f}% gebruikt**"
            ),
            discord.ui.Separator(
                visible=True,
                spacing=(
                    discord.SeparatorSpacing.small
                ),
            ),
            discord.ui.TextDisplay(
                f"## {DATABASE_EMOJI} Databases "
                f"• {data['ok_count']}/{len(data['checks'])} OK\n"
                + "\n".join(
                    db_lines
                )
            ),
        ]

        if full:
            loop_lines = (
                data["loop_lines"]
                or [
                    "> └ Geen background loops gevonden."
                ]
            )

            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=(
                            discord.SeparatorSpacing.small
                        ),
                    ),
                    discord.ui.TextDisplay(
                        f"## {MODULES_EMOJI} Background loops\n"
                        + "\n".join(
                            loop_lines
                        )
                    ),
                ]
            )

        children.extend(
            [
                discord.ui.Separator(
                    visible=True,
                    spacing=(
                        discord.SeparatorSpacing.small
                    ),
                ),
                health_action_row(
                    cog
                ),
                discord.ui.TextDisplay(
                    f"-# Automatisch vernieuwd "
                    f"<t:{data['timestamp']}:R> • LEVENLOOS"
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
# COG
# ============================================================

class Health(
    commands.Cog
):
    """Persistent Components V2 health dashboard voor LEVENLOOS."""

    health = app_commands.Group(
        name="health",
        description="Bot health en status",
    )

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self._panel_lock = (
            asyncio.Lock()
        )

    async def cog_load(
        self,
    ) -> None:
        if not hasattr(
            discord.ui,
            "LayoutView",
        ):
            raise RuntimeError(
                "Health vereist Discord Components V2."
            )

        await self._init_db()

        async with aiosqlite.connect(
            DB_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT refresh_minutes
                FROM health_config
                ORDER BY guild_id
                LIMIT 1
                """
            )
            row = await cursor.fetchone()

        if row:
            self.health_loop.change_interval(
                minutes=max(
                    1,
                    int(row[0]),
                )
            )

        # Herstelt de vier vaste panelknoppen na een botrestart.
        self.bot.add_view(
            HealthPersistentRegistrationView(
                self
            )
        )

        if not self.health_loop.is_running():
            self.health_loop.start()

        logger.info(
            "Health-module geladen."
        )

    def cog_unload(
        self,
    ) -> None:
        if self.health_loop.is_running():
            self.health_loop.cancel()

    # ========================================================
    # DATABASE
    # ========================================================

    async def _init_db(
        self,
    ) -> None:
        async with aiosqlite.connect(
            DB_PATH
        ) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS health_panel (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS health_config (
                    guild_id INTEGER PRIMARY KEY,
                    refresh_minutes INTEGER NOT NULL DEFAULT 5,
                    show_loops INTEGER NOT NULL DEFAULT 0
                )
                """
            )

            await db.commit()

    async def health_config(
        self,
        guild_id: int,
    ) -> tuple[int, bool]:
        async with aiosqlite.connect(
            DB_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT
                    refresh_minutes,
                    show_loops
                FROM health_config
                WHERE guild_id = ?
                """,
                (
                    guild_id,
                ),
            )
            row = await cursor.fetchone()

        if row is None:
            return (
                5,
                False,
            )

        return (
            int(row[0]),
            bool(row[1]),
        )

    async def set_health_config(
        self,
        guild_id: int,
        refresh_minutes: int,
        show_loops: bool,
    ) -> None:
        async with aiosqlite.connect(
            DB_PATH
        ) as db:
            await db.execute(
                """
                INSERT INTO health_config (
                    guild_id,
                    refresh_minutes,
                    show_loops
                )
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    refresh_minutes =
                        excluded.refresh_minutes,
                    show_loops =
                        excluded.show_loops
                """,
                (
                    guild_id,
                    refresh_minutes,
                    int(show_loops),
                ),
            )
            await db.commit()

    async def _panel_config(
        self,
        guild_id: int,
    ) -> tuple[int, int] | None:
        async with aiosqlite.connect(
            DB_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT
                    channel_id,
                    message_id
                FROM health_panel
                WHERE guild_id = ?
                """,
                (
                    guild_id,
                ),
            )
            row = await cursor.fetchone()

        if row is None:
            return None

        return (
            int(row[0]),
            int(row[1]),
        )

    async def _save_panel(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        async with aiosqlite.connect(
            DB_PATH
        ) as db:
            await db.execute(
                """
                INSERT INTO health_panel (
                    guild_id,
                    channel_id,
                    message_id
                )
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    channel_id =
                        excluded.channel_id,
                    message_id =
                        excluded.message_id
                """,
                (
                    guild_id,
                    channel_id,
                    message_id,
                ),
            )
            await db.commit()

    # ========================================================
    # DATA
    # ========================================================

    def loop_status_lines(
        self,
    ) -> list[str]:
        loops = []

        for (
            cog_name,
            cog,
        ) in self.bot.cogs.items():
            loop_attrs = []

            for attr_name in dir(cog):
                try:
                    attr = getattr(
                        cog,
                        attr_name,
                    )
                except Exception:
                    continue

                if not isinstance(
                    attr,
                    tasks.Loop,
                ):
                    continue

                icon = (
                    SUCCESS_EMOJI
                    if attr.is_running()
                    else ERROR_EMOJI
                )

                loop_attrs.append(
                    f"{icon} `{attr_name}`"
                )

            if loop_attrs:
                loops.append(
                    f"> └ **{cog_name}** • "
                    + " • ".join(
                        loop_attrs[:4]
                    )
                )

            if len(loops) >= 12:
                break

        return loops

    async def collect_health_data(
        self,
        *,
        full: bool,
    ) -> dict:
        ping = round(
            self.bot.latency * 1000
        )
        loaded = len(
            self.bot.extensions
        )
        cogs = len(
            self.bot.cogs
        )
        uptime = _format_duration(
            time.monotonic()
            - STARTED_AT
        )

        disk = shutil.disk_usage(
            "."
        )
        disk_used = (
            disk.used
            / disk.total
            * 100
            if disk.total
            else 0
        )

        memory = _memory_mb()
        sys_mem = _system_memory()

        task_count = len(
            [
                task
                for task
                in asyncio.all_tasks()
                if not task.done()
            ]
        )

        checks = await asyncio.gather(
            *(
                asyncio.to_thread(
                    _quick_check,
                    path,
                )
                for path
                in DATABASE_PATHS
            )
        )

        bad = [
            item
            for item
            in checks
            if not item[1]
        ]

        score = 100

        if ping > 300:
            score -= 15
        elif ping > 150:
            score -= 7

        if disk_used > 90:
            score -= 20
        elif disk_used > 80:
            score -= 10

        score -= min(
            40,
            len(bad) * 10,
        )

        loop_lines = (
            self.loop_status_lines()
            if full
            else []
        )

        stopped_loops = sum(
            line.count(
                ERROR_EMOJI
            )
            for line
            in loop_lines
        )

        if full and stopped_loops:
            score -= min(
                20,
                stopped_loops * 5,
            )

        score = max(
            0,
            score,
        )

        return {
            "ping": ping,
            "loaded": loaded,
            "cogs": cogs,
            "uptime": uptime,
            "disk_used": disk_used,
            "memory": memory,
            "sys_mem": sys_mem,
            "task_count": task_count,
            "checks": checks,
            "ok_count": (
                len(checks)
                - len(bad)
            ),
            "score": score,
            "loop_lines": loop_lines,
            "timestamp": int(
                discord.utils.utcnow().timestamp()
            ),
        }

    async def build_health_view(
        self,
        *,
        full: bool,
        persistent: bool,
    ) -> HealthDashboardView:
        data = await self.collect_health_data(
            full=full
        )

        return HealthDashboardView(
            self,
            data,
            full=full,
            persistent=persistent,
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
    ) -> None:
        view = HealthFeedbackView(
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
    # PANEL ACTIONS
    # ========================================================

    async def handle_panel_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        guild = interaction.guild

        if guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        member = interaction.user

        if action in {
            "refresh",
            "check",
            "config",
        }:
            if (
                not isinstance(
                    member,
                    discord.Member,
                )
                or not management_access(
                    member
                )
            ):
                await self.send_feedback(
                    interaction,
                    (
                        "Alleen beheer kan "
                        "deze actie uitvoeren."
                    ),
                    kind="error",
                    title="Geen toegang",
                )
                return

        if action == "refresh":
            await interaction.response.defer(
                ephemeral=True
            )

            ok = await self.refresh_panel(
                guild
            )

            await self.send_feedback(
                interaction,
                (
                    "Health panel vernieuwd."
                    if ok
                    else (
                        "Er is nog geen geldig "
                        "health panel. Gebruik `/health setup`."
                    )
                ),
                kind=(
                    "success"
                    if ok
                    else "warning"
                ),
            )
            return

        if action == "check":
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )

            await interaction.followup.send(
                view=await self.build_health_view(
                    full=True,
                    persistent=False,
                ),
                ephemeral=True,
            )
            return

        if action == "info":
            await interaction.response.send_message(
                view=HealthInfoView(),
                ephemeral=True,
            )
            return

        if action == "config":
            minutes, show_loops = (
                await self.health_config(
                    guild.id
                )
            )

            await interaction.response.send_modal(
                HealthConfigModal(
                    self,
                    guild.id,
                    minutes,
                    show_loops,
                )
            )

    # ========================================================
    # PANEL
    # ========================================================

    async def refresh_panel(
        self,
        guild: discord.Guild | None,
    ) -> bool:
        if guild is None:
            return False

        async with self._panel_lock:
            cfg = await self._panel_config(
                guild.id
            )

            if cfg is None:
                return False

            channel = guild.get_channel(
                cfg[0]
            )

            if not isinstance(
                channel,
                discord.TextChannel,
            ):
                return False

            me = guild.me

            if (
                me is None
                or not channel.permissions_for(
                    me
                ).send_messages
            ):
                return False

            try:
                message = await channel.fetch_message(
                    cfg[1]
                )

                _, show_loops = (
                    await self.health_config(
                        guild.id
                    )
                )

                await message.edit(
                    content=None,
                    embed=None,
                    view=await self.build_health_view(
                        full=show_loops,
                        persistent=True,
                    ),
                )

                return True

            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                return False

    async def remove_old_panel(
        self,
        guild: discord.Guild,
        old_config: tuple[int, int] | None,
        *,
        keep_message_id: int,
    ) -> None:
        if old_config is None:
            return

        old_channel_id, old_message_id = (
            old_config
        )

        if old_message_id == keep_message_id:
            return

        old_channel = guild.get_channel(
            old_channel_id
        )

        if not isinstance(
            old_channel,
            discord.TextChannel,
        ):
            return

        try:
            old_message = (
                await old_channel.fetch_message(
                    old_message_id
                )
            )

            await old_message.delete(
                reason=(
                    "Health panel verplaatst"
                )
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

    # ========================================================
    # LOOP
    # ========================================================

    @tasks.loop(
        minutes=5
    )
    async def health_loop(
        self,
    ) -> None:
        for guild in self.bot.guilds:
            try:
                await self.refresh_panel(
                    guild
                )
            except Exception:
                logger.exception(
                    "Health refresh mislukt "
                    "voor guild %s.",
                    guild.id,
                )

    @health_loop.before_loop
    async def before_health_loop(
        self,
    ) -> None:
        await self.bot.wait_until_ready()

    # ========================================================
    # /HEALTH SETUP
    # ========================================================

    @health.command(
        name="setup",
        description=(
            "Plaats of verplaats "
            "het permanente health panel"
        ),
    )
    @app_commands.describe(
        channel=(
            "Kanaal voor het health panel"
        )
    )
    async def setup_panel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not management_access(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        target = (
            channel
            or interaction.channel
        )

        if not isinstance(
            target,
            discord.TextChannel,
        ):
            await self.send_feedback(
                interaction,
                "Kies een tekstkanaal.",
                kind="error",
            )
            return

        me = interaction.guild.me

        if (
            me is None
            or not target.permissions_for(
                me
            ).send_messages
        ):
            await self.send_feedback(
                interaction,
                (
                    "Ik kan niet sturen "
                    f"in {target.mention}."
                ),
                kind="error",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        old_config = (
            await self._panel_config(
                interaction.guild.id
            )
        )

        _, show_loops = (
            await self.health_config(
                interaction.guild.id
            )
        )

        try:
            message = await target.send(
                view=await self.build_health_view(
                    full=show_loops,
                    persistent=True,
                ),
                silent=True,
            )
        except (
            discord.Forbidden,
            discord.HTTPException,
        ):
            logger.exception(
                "Health panel plaatsen mislukt "
                "in guild %s.",
                interaction.guild.id,
            )

            await self.send_feedback(
                interaction,
                "Discord kon het health panel niet plaatsen.",
                kind="error",
            )
            return

        await self._save_panel(
            interaction.guild.id,
            target.id,
            message.id,
        )

        await self.remove_old_panel(
            interaction.guild,
            old_config,
            keep_message_id=message.id,
        )

        await self.send_feedback(
            interaction,
            (
                f"Health panel geplaatst in "
                f"{target.mention}.\n"
                f"[Open het panel]({message.jump_url})"
            ),
            kind="success",
            title="Health panel geplaatst",
        )

    # ========================================================
    # /HEALTH CONFIG
    # ========================================================

    @health.command(
        name="config",
        description=(
            "Open de instellingen "
            "van het Health Panel"
        ),
    )
    async def config_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not management_access(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        minutes, show_loops = (
            await self.health_config(
                interaction.guild.id
            )
        )

        await interaction.response.send_modal(
            HealthConfigModal(
                self,
                interaction.guild.id,
                minutes,
                show_loops,
            )
        )

    # ========================================================
    # /HEALTH INFO
    # ========================================================

    @health.command(
        name="info",
        description=(
            "Bekijk precies wat "
            "het Health Panel controleert"
        ),
    )
    async def info_command(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.send_message(
            view=HealthInfoView(),
            ephemeral=True,
        )

    # ========================================================
    # /HEALTH REFRESH
    # ========================================================

    @health.command(
        name="refresh",
        description=(
            "Vernieuw het health panel direct"
        ),
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
            or not management_access(
                interaction.user
            )
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

        ok = await self.refresh_panel(
            interaction.guild
        )

        await self.send_feedback(
            interaction,
            (
                "Health panel vernieuwd."
                if ok
                else (
                    "Er is nog geen geldig "
                    "health panel. Gebruik `/health setup`."
                )
            ),
            kind=(
                "success"
                if ok
                else "warning"
            ),
        )

    # ========================================================
    # /HEALTH CHECK
    # ========================================================

    @health.command(
        name="check",
        description=(
            "Voer direct een volledige "
            "bot health check uit"
        ),
    )
    async def check_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
            or not management_access(
                interaction.user
            )
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await interaction.followup.send(
            view=await self.build_health_view(
                full=True,
                persistent=False,
            ),
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Health(bot)
    )
