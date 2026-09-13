import asyncio
import difflib
import logging
import re
import time
import unicodedata
from urllib.parse import urlparse

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONFIG
# ============================================================

DATABASE_PATH = "levenloos.db"

ACTIVE_GAME_CATEGORY_ID = 940987098427707412
GAME_PROPOSAL_CHANNEL_ID = 940336215331319858

ARCHIVE_CATEGORY_ID = 1545088593716973568
UNARCHIVE_CHANNEL_ID = 1545089501745913916

OWNER_DM_USER_ID = 267246682947715087

ACTIVE_ROLE_COLOR = discord.Color.from_str("#FFAE00")
ARCHIVE_ROLE_COLOR = discord.Color.from_str("#808080")
BRAND_COLOR = discord.Color.from_str("#6C27DA")

GAME_VOTE_REQUIRED = 3
GAME_VOTE_DURATION = 24 * 60 * 60
GAME_VOTE_START_COOLDOWN = 2 * 60 * 60

UNARCHIVE_VOTE_REQUIRED = 3
UNARCHIVE_VOTE_DURATION = 24 * 60 * 60

TEMP_ROLE_BUTTON_DURATION = 24 * 60 * 60

logger = logging.getLogger(__name__)


# ============================================================
# LEVENLOOS CUSTOM EMOJIS
# ============================================================

GAMES_EMOJI = "<:games:1546435140790517780>"

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"

ADD_EMOJI = "<:add:1547724100812931072>"
DELETE_EMOJI = "<:delete:1547724056768286750>"
REFRESH_EMOJI = "<:refresh:1547724055426244618>"
BACK_EMOJI = "<:back:1547724054038052966>"
LOCK_EMOJI = "<:lock:1547724040888786966>"
NONE_EMOJI = "<:none:1547724038955208794>"
INFO_EMOJI = "<:info:1547724036107149413>"


# ============================================================
# DATABASE
# ============================================================

async def initialise_database():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS game_button_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                creator_id INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS game_button_support (
                vote_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                UNIQUE(vote_id, user_id)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS game_vote_state (
                guild_id INTEGER PRIMARY KEY,
                last_vote_started_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS temp_role_buttons_v2 (
                message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS unarchive_button_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                creator_id INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS unarchive_button_support (
                vote_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                UNIQUE(vote_id, user_id)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS game_catalog_metadata (
                guild_id INTEGER NOT NULL,
                normalized_name TEXT NOT NULL,
                steam_url TEXT,
                PRIMARY KEY (guild_id, normalized_name)
            )
            """
        )

        # Backward-compatible migratie voor bestaande databases.
        for table_name in (
            "game_button_votes",
            "temp_role_buttons_v2",
        ):
            columns = {
                str(row[1])
                for row in await (
                    await db.execute(
                        f"PRAGMA table_info({table_name})"
                    )
                ).fetchall()
            }

            if "steam_url" not in columns:
                await db.execute(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN steam_url TEXT"
                )

        # Backward-compatible indexes; bestaande tabellen en data blijven intact.
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_game_votes_active
            ON game_button_votes(guild_id, status, expires_at)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_game_support_vote
            ON game_button_support(vote_id)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_unarchive_votes_active
            ON unarchive_button_votes(guild_id, normalized_name, status, expires_at)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_unarchive_support_vote
            ON unarchive_button_support(vote_id)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_temp_role_buttons_active
            ON temp_role_buttons_v2(guild_id, status, expires_at)
            """
        )

        await db.commit()

    logger.info("Game database klaar.")


# ============================================================
# GENERIC HELPERS
# ============================================================

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


def clean_game_name(
    name: str,
) -> str:
    name = name.strip()

    name = re.sub(
        r"^[◆▏│┃|\s]+",
        "",
        name,
    )

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    return name.strip().title()


def normalize_game_name(
    name: str,
) -> str:
    name = clean_game_name(name)

    name = unicodedata.normalize(
        "NFKD",
        name,
    )

    name = "".join(
        character
        for character in name
        if not unicodedata.combining(
            character
        )
    )

    name = name.lower()

    name = re.sub(
        r"[^a-z0-9]",
        "",
        name,
    )

    return name


def channel_slug(
    game_name: str,
) -> str:
    text = unicodedata.normalize(
        "NFKD",
        game_name,
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text,
    )

    text = text.strip("-")

    return f"▏{text}"


def role_name(
    game_name: str,
) -> str:
    return f"◆ {game_name}"


def normalize_steam_link(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    value = value.strip()

    if not value:
        return None

    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            "Gebruik een volledige Steam-link die begint met `https://`."
        )

    hostname = (parsed.hostname or "").casefold()

    allowed = (
        hostname == "s.team"
        or hostname == "steampowered.com"
        or hostname.endswith(".steampowered.com")
    )

    if not allowed:
        raise ValueError(
            "Gebruik een link van de Steam Store."
        )

    if parsed.scheme == "http":
        value = "https://" + value[len("http://"):]

    return value


def game_channel_topic(
    game_name: str,
    steam_url: str | None = None,
) -> str:
    topic = (
        f"Gamekanaal voor {game_name} • "
        "Praat hier over de game, deel tips/screenshots en speel samen."
    )

    if steam_url:
        topic += f" • Steam: {steam_url}"

    return topic[:1024]


async def save_game_steam_link(
    guild_id: int,
    game_name: str,
    steam_url: str | None,
):
    normalized = normalize_game_name(
        game_name
    )

    if not normalized:
        return

    async with aiosqlite.connect(
        DATABASE_PATH
    ) as db:
        if steam_url:
            await db.execute(
                """
                INSERT INTO game_catalog_metadata (
                    guild_id,
                    normalized_name,
                    steam_url
                )
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, normalized_name)
                DO UPDATE SET
                    steam_url = excluded.steam_url
                """,
                (
                    guild_id,
                    normalized,
                    steam_url,
                ),
            )
        else:
            await db.execute(
                """
                INSERT OR IGNORE INTO game_catalog_metadata (
                    guild_id,
                    normalized_name,
                    steam_url
                )
                VALUES (?, ?, NULL)
                """,
                (
                    guild_id,
                    normalized,
                ),
            )

        await db.commit()


async def get_game_steam_link(
    guild_id: int,
    game_name: str,
) -> str | None:
    normalized = normalize_game_name(
        game_name
    )

    if not normalized:
        return None

    async with aiosqlite.connect(
        DATABASE_PATH
    ) as db:
        cursor = await db.execute(
            """
            SELECT steam_url
            FROM game_catalog_metadata
            WHERE guild_id = ?
              AND normalized_name = ?
            """,
            (
                guild_id,
                normalized,
            ),
        )
        row = await cursor.fetchone()

    if not row or not row[0]:
        return None

    return str(row[0])


async def delete_game_metadata(
    guild_id: int,
    game_name: str,
):
    normalized = normalize_game_name(
        game_name
    )

    if not normalized:
        return

    async with aiosqlite.connect(
        DATABASE_PATH
    ) as db:
        await db.execute(
            """
            DELETE FROM game_catalog_metadata
            WHERE guild_id = ?
              AND normalized_name = ?
            """,
            (
                guild_id,
                normalized,
            ),
        )
        await db.commit()


def management_access(
    member: discord.Member,
) -> bool:
    if member.guild.owner_id == member.id:
        return True

    if member.guild_permissions.administrator:
        return True

    names = {
        role.name.casefold()
        for role in member.roles
    }

    return "admin" in names or "owner" in names


def status_label(
    status: str,
) -> str:
    return {
        "active": "Open",
        "passed": "Geslaagd",
        "expired": "Verlopen",
        "cancelled": "Geannuleerd",
    }.get(status, status.title())


def status_icon(
    status: str,
) -> str:
    return {
        "active": INFO_EMOJI,
        "passed": SUCCESS_EMOJI,
        "expired": LOCK_EMOJI,
        "cancelled": NONE_EMOJI,
    }.get(status, INFO_EMOJI)


def schedule_background_task(
    bot: commands.Bot,
    coroutine,
):
    cog = bot.get_cog("Games")

    if cog is not None and hasattr(
        cog,
        "schedule_background",
    ):
        return cog.schedule_background(
            coroutine
        )

    return asyncio.create_task(
        coroutine
    )


# ============================================================
# GAME SEARCH
# ============================================================

def find_game_role(
    guild: discord.Guild,
    game_name: str,
):
    wanted = normalize_game_name(
        game_name
    )

    for role in guild.roles:
        if not role.name.startswith("◆"):
            continue

        existing = normalize_game_name(
            role.name
        )

        if existing == wanted:
            return role

    return None


def find_active_game_channel(
    guild: discord.Guild,
    game_name: str,
):
    category = guild.get_channel(
        ACTIVE_GAME_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        return None

    wanted = normalize_game_name(
        game_name
    )

    for channel in category.text_channels:
        existing = normalize_game_name(
            channel.name
        )

        if existing == wanted:
            return channel

    return None


def find_archived_game_channel(
    guild: discord.Guild,
    game_name: str,
):
    category = guild.get_channel(
        ARCHIVE_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        return None

    wanted = normalize_game_name(
        game_name
    )

    for channel in category.text_channels:
        existing = normalize_game_name(
            channel.name
        )

        if existing == wanted:
            return channel

    return None


def all_game_names(
    guild: discord.Guild,
):
    result = []

    for role in guild.roles:
        if not role.name.startswith("◆"):
            continue

        result.append(
            clean_game_name(
                role.name
            )
        )

    return result


def find_near_match(
    guild: discord.Guild,
    game_name: str,
):
    wanted = normalize_game_name(
        game_name
    )

    if not wanted:
        return None

    for existing_name in all_game_names(
        guild
    ):
        existing = normalize_game_name(
            existing_name
        )

        similarity = difflib.SequenceMatcher(
            None,
            wanted,
            existing,
        ).ratio()

        if similarity >= 0.82:
            return existing_name

    return None


# ============================================================
# SORTING
# ============================================================

async def sort_category(
    category: discord.CategoryChannel,
    pinned_channel_id: int,
):
    channels = list(
        category.text_channels
    )

    pinned = None
    others = []

    for channel in channels:
        if channel.id == pinned_channel_id:
            pinned = channel
        else:
            others.append(channel)

    others.sort(
        key=lambda channel: normalize_game_name(
            channel.name
        )
    )

    target = []

    if pinned:
        target.append(pinned)

    target.extend(others)

    try:
        for wanted_position, channel in enumerate(
            target
        ):
            if channel.position == wanted_position:
                continue

            await channel.edit(
                position=wanted_position,
                reason="Gamekanalen alfabetisch sorteren",
            )

            # Bewust gespreid om channel-position rate limits te beperken.
            await asyncio.sleep(0.65)

    except asyncio.TimeoutError:
        logger.warning(
            "Sorteren van categorie %s kreeg een timeout.",
            category.id,
        )
    except discord.Forbidden:
        logger.warning(
            "Geen toestemming om categorie %s te sorteren.",
            category.id,
        )
    except discord.HTTPException:
        logger.exception(
            "Discord-fout tijdens sorteren van categorie %s.",
            category.id,
        )


async def sort_active_games(
    guild: discord.Guild,
):
    category = guild.get_channel(
        ACTIVE_GAME_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        return

    try:
        await asyncio.wait_for(
            sort_category(
                category,
                GAME_PROPOSAL_CHANNEL_ID,
            ),
            timeout=30,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Sorteren actieve games timeout in guild %s.",
            guild.id,
        )


async def sort_archived_games(
    guild: discord.Guild,
):
    category = guild.get_channel(
        ARCHIVE_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        return

    try:
        await asyncio.wait_for(
            sort_category(
                category,
                UNARCHIVE_CHANNEL_ID,
            ),
            timeout=30,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Sorteren archief timeout in guild %s.",
            guild.id,
        )


# ============================================================
# ROLE SELECTOR FUTURE HOOK
# ============================================================

def notify_role_system(
    bot: commands.Bot,
    guild: discord.Guild,
    game_name: str,
    action: str,
):
    """
    Rollen-/reactmodules kunnen luisteren naar:

    @commands.Cog.listener()
    async def on_game_catalog_changed(
        self,
        guild,
        game_name,
        action,
    ):
        ...

    Mogelijke actions:
    created
    archived
    unarchived
    removed
    """
    bot.dispatch(
        "game_catalog_changed",
        guild,
        game_name,
        action,
    )


# ============================================================
# GAME CATALOG ACTIONS
# ============================================================

async def create_game(
    bot: commands.Bot,
    guild: discord.Guild,
    game_name: str,
    steam_url: str | None = None,
):
    game_name = clean_game_name(
        game_name
    )

    if steam_url:
        await save_game_steam_link(
            guild.id,
            game_name,
            steam_url,
        )
    else:
        steam_url = await get_game_steam_link(
            guild.id,
            game_name,
        )

    role = find_game_role(
        guild,
        game_name,
    )

    if role is None:
        role = await guild.create_role(
            name=role_name(
                game_name
            ),
            color=ACTIVE_ROLE_COLOR,
            reason=f"Game aangemaakt: {game_name}",
        )
    else:
        try:
            await role.edit(
                name=role_name(
                    game_name
                ),
                color=ACTIVE_ROLE_COLOR,
                reason=f"Game geactiveerd: {game_name}",
            )
        except discord.HTTPException:
            logger.exception(
                "Game role %s kon niet worden bijgewerkt.",
                role.id,
            )

    category = guild.get_channel(
        ACTIVE_GAME_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        raise RuntimeError(
            "Active game category niet gevonden."
        )

    channel = find_active_game_channel(
        guild,
        game_name,
    )

    if channel is None:
        archived = find_archived_game_channel(
            guild,
            game_name,
        )

        if archived:
            channel = archived

            await channel.edit(
                category=category,
                reason=f"Game geactiveerd: {game_name}",
            )
        else:
            overwrites = {
                guild.default_role:
                    discord.PermissionOverwrite(
                        view_channel=False,
                    ),
                role:
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
            }

            channel = await guild.create_text_channel(
                channel_slug(
                    game_name
                ),
                category=category,
                overwrites=overwrites,
                topic=game_channel_topic(
                    game_name,
                    steam_url,
                ),
                reason=f"Game aangemaakt: {game_name}",
            )

    await channel.edit(
        name=channel_slug(
            game_name
        ),
        topic=game_channel_topic(
            game_name,
            steam_url,
        ),
        overwrites={
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False,
                ),
            role:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                ),
        },
        reason=f"Gamekanaal bijgewerkt: {game_name}",
    )

    await sort_active_games(
        guild
    )

    notify_role_system(
        bot,
        guild,
        game_name,
        "created",
    )

    return role, channel


async def archive_game(
    bot: commands.Bot,
    guild: discord.Guild,
    game_name: str,
):
    game_name = clean_game_name(
        game_name
    )

    channel = find_active_game_channel(
        guild,
        game_name,
    )

    if channel is None:
        return None

    category = guild.get_channel(
        ARCHIVE_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        raise RuntimeError(
            "Archive category niet gevonden."
        )

    role = find_game_role(
        guild,
        game_name,
    )

    steam_url = await get_game_steam_link(
        guild.id,
        game_name,
    )

    archive_topic = (
        f"Gearchiveerd gamekanaal voor {game_name} • "
        "Dit kanaal is alleen-lezen."
    )

    if steam_url:
        archive_topic += f" • Steam: {steam_url}"

    await channel.edit(
        category=category,
        topic=archive_topic[:1024],
        overwrites={
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    add_reactions=False,
                    create_public_threads=False,
                    create_private_threads=False,
                    send_messages_in_threads=False,
                    read_message_history=True,
                ),
        },
        reason=f"Game gearchiveerd: {game_name}",
    )

    if role:
        try:
            await role.edit(
                color=ARCHIVE_ROLE_COLOR,
                reason=f"Game gearchiveerd: {game_name}",
            )
        except discord.HTTPException:
            logger.exception(
                "Game role %s kon niet grijs worden gemaakt.",
                role.id,
            )

    await sort_archived_games(
        guild
    )

    notify_role_system(
        bot,
        guild,
        game_name,
        "archived",
    )

    return channel


async def unarchive_game_now(
    bot: commands.Bot,
    guild: discord.Guild,
    game_name: str,
):
    game_name = clean_game_name(
        game_name
    )

    channel = find_archived_game_channel(
        guild,
        game_name,
    )

    if channel is None:
        return None

    category = guild.get_channel(
        ACTIVE_GAME_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        raise RuntimeError(
            "Active category niet gevonden."
        )

    role = find_game_role(
        guild,
        game_name,
    )

    steam_url = await get_game_steam_link(
        guild.id,
        game_name,
    )

    if role is None:
        role = await guild.create_role(
            name=role_name(
                game_name
            ),
            color=ACTIVE_ROLE_COLOR,
            reason=f"Game teruggezet: {game_name}",
        )
    else:
        try:
            await role.edit(
                color=ACTIVE_ROLE_COLOR,
                reason=f"Game teruggezet: {game_name}",
            )
        except discord.HTTPException:
            logger.exception(
                "Game role %s kon niet worden geactiveerd.",
                role.id,
            )

    await channel.edit(
        category=category,
        name=channel_slug(
            game_name
        ),
        topic=game_channel_topic(
            game_name,
            steam_url,
        ),
        overwrites={
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False,
                ),
            role:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                ),
        },
        reason=f"Game teruggezet: {game_name}",
    )

    await sort_active_games(
        guild
    )

    notify_role_system(
        bot,
        guild,
        game_name,
        "unarchived",
    )

    return channel


# ============================================================
# COMPONENTS V2 FEEDBACK
# ============================================================

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

        body_lines = [
            f"> └ {line}"
            for line in message.splitlines()
            if line.strip()
        ]

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"# {icon} {title or default_title}\n"
                + "\n".join(body_lines)
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
# STEAM LINK BUTTON
# ============================================================

class SteamLinkButton(discord.ui.Button):
    def __init__(
        self,
        steam_url: str,
    ):
        super().__init__(
            label="Steam",
            style=discord.ButtonStyle.link,
            url=steam_url,
        )


# ============================================================
# OWNER DM
# ============================================================

class OwnerNewGameView(discord.ui.LayoutView):
    def __init__(
        self,
        guild: discord.Guild,
        game_name: str,
        role: discord.Role,
        game_channel: discord.TextChannel,
        react_synced: bool,
        steam_url: str | None = None,
    ):
        super().__init__(timeout=180)

        react_line = (
            f"{SUCCESS_EMOJI} Automatisch toegevoegd aan "
            "**React Roles → Games**."
            if react_synced
            else (
                f"{WARNING_EMOJI} Automatisch toevoegen aan "
                "React Roles is niet gelukt."
            )
        )

        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"# {GAMES_EMOJI} Nieuwe game toegevoegd\n"
                f"## {game_name}\n"
                f"> └ Server: **{guild.name}**\n"
                f"> └ Rol: **{role.name}**\n"
                f"> └ Kanaal: {game_channel.mention}\n\n"
                "## React Roles\n"
                f"> └ {react_line}\n\n"
                "## Tijdelijke toegang\n"
                f"> └ De **Pak {role.name}**-knop blijft "
                "**24 uur** beschikbaar."
            )
        ]

        if steam_url:
            children.extend(
                [
                    discord.ui.Separator(
                        visible=True,
                        spacing=discord.SeparatorSpacing.small,
                    ),
                    discord.ui.ActionRow(
                        SteamLinkButton(
                            steam_url
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


async def notify_owner_new_game(
    bot: commands.Bot,
    guild: discord.Guild,
    game_name: str,
    role: discord.Role,
    game_channel: discord.TextChannel,
    react_synced: bool = False,
    steam_url: str | None = None,
):
    try:
        owner = bot.get_user(
            OWNER_DM_USER_ID
        )

        if owner is None:
            owner = await bot.fetch_user(
                OWNER_DM_USER_ID
            )

        await owner.send(
            view=OwnerNewGameView(
                guild,
                game_name,
                role,
                game_channel,
                react_synced,
                steam_url,
            )
        )

        logger.info(
            "Owner DM verstuurd voor game %s in guild %s.",
            game_name,
            guild.id,
        )

    except discord.Forbidden:
        logger.warning(
            "Owner accepteert geen DM's."
        )
    except discord.HTTPException:
        logger.exception(
            "Owner DM mislukt voor game %s.",
            game_name,
        )


# ============================================================
# TEMPORARY ROLE BUTTON
# ============================================================

class TempRoleButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "TempRoleView",
        *,
        disabled: bool = False,
    ):
        super().__init__(
            label=f"Pak ◆ {owner_view.game_name}",
            emoji=component_emoji(
                ADD_EMOJI
            ),
            style=(
                discord.ButtonStyle.success
                if not disabled
                else discord.ButtonStyle.secondary
            ),
            custom_id=(
                f"temp_game_role:"
                f"{owner_view.role_id}"
            ),
            disabled=disabled,
        )

        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.owner_view.claim_role(
            interaction
        )


class TempRoleView(discord.ui.LayoutView):
    def __init__(
        self,
        role_id: int,
        game_name: str,
        expires_at: int | None = None,
        steam_url: str | None = None,
        *,
        disabled: bool = False,
        status: str = "active",
    ):
        super().__init__(timeout=None)

        self.role_id = role_id
        self.game_name = game_name
        self.expires_at = expires_at
        self.steam_url = steam_url
        self.status = status

        if status == "expired":
            title = (
                f"# {LOCK_EMOJI} Tijdelijke toegang verlopen"
            )
            helper = (
                "> └ Deze tijdelijke knop is niet meer beschikbaar."
            )
        else:
            title = (
                f"# {GAMES_EMOJI} {game_name} is toegevoegd"
            )
            helper = (
                "> └ Wil je toegang tot het nieuwe gamekanaal?\n"
                f"> └ Pak hieronder tijdelijk **◆ {game_name}**."
            )

        footer = (
            f"-# Beschikbaar tot <t:{expires_at}:R>"
            if expires_at and status == "active"
            else "-# Tijdelijke game-role toegang"
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"{title}\n"
                    f"{helper}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    *(
                        [
                            TempRoleButton(
                                self,
                                disabled=disabled,
                            ),
                            SteamLinkButton(
                                steam_url
                            ),
                        ]
                        if steam_url
                        else [
                            TempRoleButton(
                                self,
                                disabled=disabled,
                            )
                        ]
                    )
                ),
                discord.ui.TextDisplay(
                    footer
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def claim_role(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                view=FeedbackView(
                    "Dit werkt alleen op een server.",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(
            self.role_id
        )

        if role is None:
            await interaction.response.send_message(
                view=FeedbackView(
                    "Deze game-role bestaat niet meer.",
                    kind="error",
                ),
                ephemeral=True,
            )
            return

        member = interaction.user

        if not isinstance(
            member,
            discord.Member,
        ):
            return

        if role in member.roles:
            await interaction.response.send_message(
                view=FeedbackView(
                    f"Je hebt **{role.name}** al.",
                    kind="info",
                    title="Rol al actief",
                ),
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(
                role,
                reason="Tijdelijke game role button",
            )

            await interaction.response.send_message(
                view=FeedbackView(
                    f"Je hebt **{role.name}** gekregen.",
                    kind="success",
                    title="Game-role toegevoegd",
                ),
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                view=FeedbackView(
                    "Ik kan deze role niet geven. "
                    "Controleer mijn role-positie.",
                    kind="error",
                ),
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception(
                "Game-role %s geven aan user %s mislukt.",
                role.id,
                member.id,
            )
            await interaction.response.send_message(
                view=FeedbackView(
                    "Discord kon de game-role momenteel niet toevoegen.",
                    kind="error",
                ),
                ephemeral=True,
            )


async def create_temporary_role_button(
    bot: commands.Bot,
    proposal_channel: discord.TextChannel,
    game_name: str,
    role: discord.Role,
    steam_url: str | None = None,
):
    expires_at = (
        int(time.time())
        + TEMP_ROLE_BUTTON_DURATION
    )

    view = TempRoleView(
        role.id,
        game_name,
        expires_at,
        steam_url,
    )

    message = await proposal_channel.send(
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )

    async with aiosqlite.connect(
        DATABASE_PATH
    ) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO temp_role_buttons_v2 (
                message_id,
                guild_id,
                channel_id,
                role_id,
                game_name,
                expires_at,
                status,
                steam_url
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                message.id,
                proposal_channel.guild.id,
                proposal_channel.id,
                role.id,
                game_name,
                expires_at,
                steam_url,
            ),
        )

        await db.commit()

    bot.add_view(
        view,
        message_id=message.id,
    )

    schedule_background_task(
        bot,
        expire_temporary_role_button(
            bot,
            message.id,
            proposal_channel.guild.id,
            proposal_channel.id,
            role.id,
            game_name,
            expires_at,
            steam_url,
        ),
    )

    return message


async def expire_temporary_role_button(
    bot,
    message_id,
    guild_id,
    channel_id,
    role_id,
    game_name,
    expires_at,
    steam_url=None,
):
    delay = max(
        0,
        expires_at - int(
            time.time()
        ),
    )

    await asyncio.sleep(
        delay
    )

    async with aiosqlite.connect(
        DATABASE_PATH
    ) as db:
        cursor = await db.execute(
            """
            UPDATE temp_role_buttons_v2
            SET status = 'expired'
            WHERE message_id = ?
              AND status = 'active'
            """,
            (message_id,),
        )

        await db.commit()

        if cursor.rowcount <= 0:
            return

    guild = bot.get_guild(
        guild_id
    )

    if not guild:
        return

    channel = guild.get_channel(
        channel_id
    )

    if not isinstance(
        channel,
        discord.TextChannel,
    ):
        return

    try:
        message = await channel.fetch_message(
            message_id
        )

        await message.edit(
            content=None,
            embed=None,
            view=TempRoleView(
                role_id,
                game_name,
                expires_at,
                steam_url,
                disabled=True,
                status="expired",
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    except discord.NotFound:
        pass
    except discord.Forbidden:
        logger.warning(
            "Geen toegang om verlopen temp role-message %s bij te werken.",
            message_id,
        )
    except discord.HTTPException:
        logger.exception(
            "Temp role-message %s verlopen maken mislukt.",
            message_id,
        )


# ============================================================
# GAME VOTE VIEW
# ============================================================

class GameVoteSupportButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "GameVoteView",
        *,
        disabled: bool = False,
    ):
        super().__init__(
            label="Steun voorstel",
            emoji=component_emoji(
                SUCCESS_EMOJI
            ),
            style=discord.ButtonStyle.success,
            custom_id=(
                f"game_vote_support:"
                f"{owner_view.vote_id}"
            ),
            disabled=disabled,
        )

        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.owner_view.cog.handle_game_vote_support(
            interaction,
            self.owner_view.vote_id,
        )


class GameVoteView(discord.ui.LayoutView):
    def __init__(
        self,
        cog,
        vote_id: int,
        game_name: str = "Game",
        creator_id: int | None = None,
        count: int = 0,
        expires_at: int | None = None,
        status: str = "active",
        steam_url: str | None = None,
        *,
        disabled: bool | None = None,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.vote_id = vote_id
        self.game_name = game_name
        self.creator_id = creator_id
        self.count = count
        self.expires_at = expires_at
        self.status = status
        self.steam_url = steam_url

        if disabled is None:
            disabled = status != "active"

        lines = [
            f"# {GAMES_EMOJI} Nieuwe game voorgesteld",
            f"## {game_name}",
        ]

        if creator_id:
            lines.append(
                f"> └ Voorgesteld door <@{creator_id}>"
            )

        lines.extend(
            [
                f"> └ Stemmen: **{count}/{GAME_VOTE_REQUIRED}**",
                f"> └ Status: **{status_icon(status)} {status_label(status)}**",
            ]
        )

        if expires_at and status == "active":
            lines.append(
                f"> └ Sluit <t:{expires_at}:R>"
            )

        if status == "passed":
            lines.extend(
                [
                    "",
                    "## Resultaat",
                    f"> └ {SUCCESS_EMOJI} De game is toegevoegd.",
                ]
            )
        elif status == "expired":
            lines.extend(
                [
                    "",
                    "## Resultaat",
                    f"> └ {LOCK_EMOJI} De vote heeft niet op tijd "
                    f"{GAME_VOTE_REQUIRED} stemmen gehaald.",
                ]
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "\n".join(lines)
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    *(
                        [
                            GameVoteSupportButton(
                                self,
                                disabled=disabled,
                            ),
                            SteamLinkButton(
                                steam_url
                            ),
                        ]
                        if steam_url
                        else [
                            GameVoteSupportButton(
                                self,
                                disabled=disabled,
                            )
                        ]
                    )
                ),
                discord.ui.TextDisplay(
                    f"-# Vote #{vote_id} • "
                    "De maker telt als eerste stem."
                ),
                accent_colour=BRAND_COLOR,
            )
        )


# ============================================================
# UNARCHIVE VOTE VIEW
# ============================================================

class UnarchiveVoteSupportButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "UnarchiveVoteView",
        *,
        disabled: bool = False,
    ):
        super().__init__(
            label="Steun terugzetten",
            emoji=component_emoji(
                REFRESH_EMOJI
            ),
            style=discord.ButtonStyle.primary,
            custom_id=(
                f"unarchive_vote_support:"
                f"{owner_view.vote_id}"
            ),
            disabled=disabled,
        )

        self.owner_view = owner_view

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.owner_view.cog.handle_unarchive_support(
            interaction,
            self.owner_view.vote_id,
        )


class UnarchiveVoteView(discord.ui.LayoutView):
    def __init__(
        self,
        cog,
        vote_id: int,
        game_name: str = "Game",
        creator_id: int | None = None,
        count: int = 0,
        expires_at: int | None = None,
        status: str = "active",
        *,
        disabled: bool | None = None,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.vote_id = vote_id
        self.game_name = game_name
        self.creator_id = creator_id
        self.count = count
        self.expires_at = expires_at
        self.status = status

        if disabled is None:
            disabled = status != "active"

        lines = [
            f"# {REFRESH_EMOJI} Game terugzetten",
            f"## {game_name}",
        ]

        if creator_id:
            lines.append(
                f"> └ Aangevraagd door <@{creator_id}>"
            )

        lines.extend(
            [
                f"> └ Stemmen: **{count}/{UNARCHIVE_VOTE_REQUIRED}**",
                f"> └ Status: **{status_icon(status)} {status_label(status)}**",
            ]
        )

        if expires_at and status == "active":
            lines.append(
                f"> └ Sluit <t:{expires_at}:R>"
            )

        if status == "passed":
            lines.extend(
                [
                    "",
                    "## Resultaat",
                    f"> └ {SUCCESS_EMOJI} De game is teruggezet.",
                ]
            )
        elif status == "expired":
            lines.extend(
                [
                    "",
                    "## Resultaat",
                    f"> └ {LOCK_EMOJI} De vote is verlopen.",
                ]
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "\n".join(lines)
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    UnarchiveVoteSupportButton(
                        self,
                        disabled=disabled,
                    )
                ),
                discord.ui.TextDisplay(
                    f"-# Vote #{vote_id} • "
                    "De aanvrager telt als eerste stem."
                ),
                accent_colour=BRAND_COLOR,
            )
        )


# ============================================================
# REMOVE CONFIRMATION
# ============================================================

class RemoveConfirmButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "RemoveConfirmView",
        action: str,
    ):
        if action == "confirm":
            label = "Definitief verwijderen"
            emoji = DELETE_EMOJI
            style = discord.ButtonStyle.danger
        else:
            label = "Annuleren"
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
        if self.action == "cancel":
            await interaction.response.edit_message(
                content=None,
                embed=None,
                view=FeedbackView(
                    "De game is niet verwijderd.",
                    kind="info",
                    title="Verwijderen geannuleerd",
                ),
            )
            self.owner_view.stop()
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            removed = await self.owner_view.cog.remove_game_now(
                interaction.guild,
                self.owner_view.game_name,
            )
        except Exception:
            logger.exception(
                "Game %s verwijderen mislukt.",
                self.owner_view.game_name,
            )

            await self.owner_view.cog.send_feedback(
                interaction,
                "De game kon niet volledig worden verwijderd. "
                "Controleer de botlog.",
                kind="error",
            )
            return

        if not removed:
            await self.owner_view.cog.send_feedback(
                interaction,
                f"**{self.owner_view.game_name}** bestaat niet meer.",
                kind="warning",
            )
            return

        await self.owner_view.cog.send_feedback(
            interaction,
            f"**{self.owner_view.game_name}** is volledig verwijderd.",
            kind="success",
            title="Game verwijderd",
        )

        self.owner_view.stop()


class RemoveConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        cog,
        user_id,
        game_name,
    ):
        super().__init__(timeout=60)

        self.cog = cog
        self.user_id = user_id
        self.game_name = game_name

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {WARNING_EMOJI} Game verwijderen\n"
                    f"## {game_name}\n"
                    "> └ Het gamekanaal en de bijbehorende game-role "
                    "worden definitief verwijderd.\n"
                    f"> └ {ERROR_EMOJI} Deze actie kan niet via de bot "
                    "ongedaan worden gemaakt."
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    RemoveConfirmButton(
                        self,
                        "confirm",
                    ),
                    RemoveConfirmButton(
                        self,
                        "cancel",
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
            interaction.user.id == self.user_id
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
            "Alleen degene die dit beheermenu opende kan bevestigen.",
            kind="error",
        )
        return False


# ============================================================
# GAME COG
# ============================================================

class Games(commands.Cog):
    game = app_commands.Group(
        name="game",
        description="Beheer gamekanalen",
    )

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.game_vote_lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

    # ========================================================
    # LOAD / UNLOAD
    # ========================================================

    async def cog_load(
        self,
    ):
        if not hasattr(
            discord.ui,
            "LayoutView",
        ):
            raise RuntimeError(
                "Games vereist discord.py 2.6+ voor Components V2."
            )

        await initialise_database()

        await self.restore_game_votes()
        await self.restore_temp_buttons()
        await self.restore_unarchive_votes()

        logger.info(
            "Games-module geladen."
        )

    def cog_unload(
        self,
    ):
        for task in list(
            self._background_tasks
        ):
            task.cancel()

        self._background_tasks.clear()

    def schedule_background(
        self,
        coroutine,
    ):
        task = asyncio.create_task(
            coroutine
        )

        self._background_tasks.add(
            task
        )

        task.add_done_callback(
            self._background_tasks.discard
        )

        return task

    # ========================================================
    # FEEDBACK / VALIDATION
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

    async def require_management(
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
                "Dit command werkt alleen op een server.",
                kind="error",
            )
            return None

        if not management_access(
            interaction.user
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return None

        return interaction.guild

    async def get_game_vote(
        self,
        vote_id: int,
    ):
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM game_button_votes
                WHERE id = ?
                """,
                (vote_id,),
            )

            return await cursor.fetchone()

    async def get_game_vote_count(
        self,
        vote_id: int,
    ) -> int:
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM game_button_support
                WHERE vote_id = ?
                """,
                (vote_id,),
            )

            row = await cursor.fetchone()

        return int(row[0] or 0)

    async def get_unarchive_vote(
        self,
        vote_id: int,
    ):
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM unarchive_button_votes
                WHERE id = ?
                """,
                (vote_id,),
            )

            return await cursor.fetchone()

    async def get_unarchive_vote_count(
        self,
        vote_id: int,
    ) -> int:
        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM unarchive_button_support
                WHERE vote_id = ?
                """,
                (vote_id,),
            )

            row = await cursor.fetchone()

        return int(row[0] or 0)

    def build_game_vote_view(
        self,
        vote,
        count: int,
        *,
        status: str | None = None,
    ) -> GameVoteView:
        effective_status = (
            status
            or str(vote["status"])
        )

        return GameVoteView(
            self,
            int(vote["id"]),
            str(vote["game_name"]),
            int(vote["creator_id"]),
            count,
            int(vote["expires_at"]),
            effective_status,
            str(vote["steam_url"]) if vote["steam_url"] else None,
            disabled=(
                effective_status != "active"
            ),
        )

    def build_unarchive_vote_view(
        self,
        vote,
        count: int,
        *,
        status: str | None = None,
    ) -> UnarchiveVoteView:
        effective_status = (
            status
            or str(vote["status"])
        )

        return UnarchiveVoteView(
            self,
            int(vote["id"]),
            str(vote["game_name"]),
            int(vote["creator_id"]),
            count,
            int(vote["expires_at"]),
            effective_status,
            disabled=(
                effective_status != "active"
            ),
        )

    # ========================================================
    # /GAME SETUP
    # ========================================================

    @game.command(
        name="setup",
        description="Maak een gamekanaal aan",
    )
    @app_commands.describe(
        game_name="Naam van de game",
        steamlink="Optionele Steam Store-link",
    )
    async def setup_game(
        self,
        interaction: discord.Interaction,
        game_name: str,
        steamlink: str | None = None,
    ):
        guild = await self.require_management(
            interaction
        )

        if guild is None:
            return

        game_name = clean_game_name(
            game_name
        )

        try:
            steam_url = normalize_steam_link(
                steamlink
            )
        except ValueError as exc:
            await self.send_feedback(
                interaction,
                str(exc),
                kind="error",
                title="Ongeldige Steam-link",
            )
            return

        if not normalize_game_name(
            game_name
        ):
            await self.send_feedback(
                interaction,
                "Vul een geldige gamenaam in.",
                kind="error",
            )
            return

        if (
            find_active_game_channel(
                guild,
                game_name,
                steam_url,
            )
            or find_archived_game_channel(
                guild,
                game_name,
            )
        ):
            await self.send_feedback(
                interaction,
                f"**{game_name}** bestaat al.",
                kind="warning",
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            role, channel = await create_game(
                self.bot,
                guild,
                game_name,
            )
        except Exception:
            logger.exception(
                "Game %s aanmaken mislukt in guild %s.",
                game_name,
                guild.id,
            )

            await self.send_feedback(
                interaction,
                "De game kon niet worden aangemaakt. "
                "Controleer de botlog voor de technische fout.",
                kind="error",
            )
            return

        await self.send_feedback(
            interaction,
            (
                f"**{game_name}** is aangemaakt.\n"
                f"Rol: **{role.name}**\n"
                f"Kanaal: {channel.mention}"
                + (
                    f"\nSteam: {steam_url}"
                    if steam_url
                    else ""
                )
            ),
            kind="success",
            title="Game aangemaakt",
        )

    # ========================================================
    # /GAME ARCHIVE
    # ========================================================

    @game.command(
        name="archive",
        description="Archiveer een gamekanaal",
    )
    async def archive_command(
        self,
        interaction: discord.Interaction,
        game_name: str,
    ):
        guild = await self.require_management(
            interaction
        )

        if guild is None:
            return

        game_name = clean_game_name(
            game_name
        )

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        try:
            channel = await archive_game(
                self.bot,
                guild,
                game_name,
            )
        except Exception:
            logger.exception(
                "Game %s archiveren mislukt.",
                game_name,
            )
            await self.send_feedback(
                interaction,
                "De game kon niet worden gearchiveerd. "
                "Controleer de botlog.",
                kind="error",
            )
            return

        if channel is None:
            await self.send_feedback(
                interaction,
                f"Actieve game **{game_name}** niet gevonden.",
                kind="warning",
            )
            return

        await self.send_feedback(
            interaction,
            f"**{game_name}** is naar het archief verplaatst.",
            kind="success",
            title="Game gearchiveerd",
        )

    # ========================================================
    # /GAME REMOVE
    # ========================================================

    @game.command(
        name="remove",
        description="Verwijder een game volledig",
    )
    async def remove_command(
        self,
        interaction: discord.Interaction,
        game_name: str,
    ):
        guild = await self.require_management(
            interaction
        )

        if guild is None:
            return

        game_name = clean_game_name(
            game_name
        )

        if not (
            find_active_game_channel(
                guild,
                game_name,
            )
            or find_archived_game_channel(
                guild,
                game_name,
            )
            or find_game_role(
                guild,
                game_name,
            )
        ):
            await self.send_feedback(
                interaction,
                f"**{game_name}** is niet gevonden.",
                kind="warning",
            )
            return

        await interaction.response.send_message(
            view=RemoveConfirmView(
                self,
                interaction.user.id,
                game_name,
            ),
            ephemeral=True,
        )

    async def remove_game_now(
        self,
        guild,
        game_name,
    ) -> bool:
        if guild is None:
            return False

        active = find_active_game_channel(
            guild,
            game_name,
        )

        archived = find_archived_game_channel(
            guild,
            game_name,
        )

        role = find_game_role(
            guild,
            game_name,
        )

        removed = bool(
            active
            or archived
            or role
        )

        if active:
            await active.delete(
                reason=f"Game verwijderd: {game_name}",
            )

        if archived:
            await archived.delete(
                reason=f"Game verwijderd: {game_name}",
            )

        if role:
            try:
                await role.delete(
                    reason=f"Game verwijderd: {game_name}",
                )
            except discord.Forbidden:
                logger.warning(
                    "Geen toestemming om game-role %s te verwijderen.",
                    role.id,
                )
            except discord.HTTPException:
                logger.exception(
                    "Game-role %s verwijderen mislukt.",
                    role.id,
                )

        if not removed:
            return False

        await sort_active_games(
            guild
        )

        await sort_archived_games(
            guild
        )

        await delete_game_metadata(
            guild.id,
            game_name,
        )

        notify_role_system(
            self.bot,
            guild,
            game_name,
            "removed",
        )

        return True

    # ========================================================
    # /GAME VOTE
    # ========================================================

    @game.command(
        name="vote",
        description="Start een vote voor een nieuwe game",
    )
    @app_commands.describe(
        game_name="Naam van de game",
        steamlink="Optionele Steam Store-link",
    )
    async def game_vote(
        self,
        interaction: discord.Interaction,
        game_name: str,
        steamlink: str | None = None,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen op een server.",
                kind="error",
            )
            return

        if (
            interaction.channel_id
            != GAME_PROPOSAL_CHANNEL_ID
        ):
            await self.send_feedback(
                interaction,
                (
                    "`/game vote` kan alleen gebruikt worden "
                    f"in <#{GAME_PROPOSAL_CHANNEL_ID}>."
                ),
                kind="error",
            )
            return

        game_name = clean_game_name(
            game_name
        )

        normalized = normalize_game_name(
            game_name
        )

        try:
            steam_url = normalize_steam_link(
                steamlink
            )
        except ValueError as exc:
            await self.send_feedback(
                interaction,
                str(exc),
                kind="error",
                title="Ongeldige Steam-link",
            )
            return

        if not normalized:
            await self.send_feedback(
                interaction,
                "Vul een geldige gamenaam in.",
                kind="error",
            )
            return

        guild = interaction.guild

        async with self.game_vote_lock:
            if (
                find_active_game_channel(
                    guild,
                    game_name,
                )
                or find_archived_game_channel(
                    guild,
                    game_name,
                )
            ):
                await self.send_feedback(
                    interaction,
                    f"**{game_name}** bestaat al.",
                    kind="warning",
                )
                return

            near = find_near_match(
                guild,
                game_name,
            )

            if near:
                await self.send_feedback(
                    interaction,
                    (
                        f"**{game_name}** lijkt erg op de bestaande "
                        f"game **{near}**.\n"
                        "Gebruik de bestaande naam of laat een admin "
                        "dit controleren."
                    ),
                    kind="warning",
                )
                return

            now = int(
                time.time()
            )

            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                await db.execute(
                    "PRAGMA busy_timeout=5000"
                )

                cursor = await db.execute(
                    """
                    SELECT id, game_name
                    FROM game_button_votes
                    WHERE guild_id = ?
                      AND status = 'active'
                      AND expires_at > ?
                    LIMIT 1
                    """,
                    (
                        guild.id,
                        now,
                    ),
                )

                active_vote = await cursor.fetchone()

                if active_vote:
                    await self.send_feedback(
                        interaction,
                        (
                            "Er loopt al een actieve game-vote voor "
                            f"**{active_vote[1]}**.\n"
                            "Er kan maar **1 game-vote tegelijk** lopen."
                        ),
                        kind="warning",
                    )
                    return

                cursor = await db.execute(
                    """
                    SELECT last_vote_started_at
                    FROM game_vote_state
                    WHERE guild_id = ?
                    """,
                    (guild.id,),
                )

                row = await cursor.fetchone()

                if row:
                    last_started = int(
                        row[0]
                    )

                    remaining = (
                        GAME_VOTE_START_COOLDOWN
                        - (
                            now
                            - last_started
                        )
                    )

                    if remaining > 0:
                        minutes = (
                            remaining + 59
                        ) // 60

                        await self.send_feedback(
                            interaction,
                            (
                                "Er kan maximaal **1 nieuwe game-vote "
                                "per 2 uur** gestart worden.\n"
                                f"Probeer over ongeveer **{minutes} minuten** "
                                "opnieuw."
                            ),
                            kind="warning",
                        )
                        return

                expires_at = (
                    now
                    + GAME_VOTE_DURATION
                )

                cursor = await db.execute(
                    """
                    INSERT INTO game_button_votes (
                        guild_id,
                        channel_id,
                        creator_id,
                        game_name,
                        normalized_name,
                        created_at,
                        expires_at,
                        status,
                        steam_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    """,
                    (
                        guild.id,
                        interaction.channel_id,
                        interaction.user.id,
                        game_name,
                        normalized,
                        now,
                        expires_at,
                        steam_url,
                    ),
                )

                vote_id = cursor.lastrowid

                await db.execute(
                    """
                    INSERT INTO game_button_support (
                        vote_id,
                        user_id
                    )
                    VALUES (?, ?)
                    """,
                    (
                        vote_id,
                        interaction.user.id,
                    ),
                )

                await db.execute(
                    """
                    INSERT INTO game_vote_state (
                        guild_id,
                        last_vote_started_at
                    )
                    VALUES (?, ?)
                    ON CONFLICT(guild_id)
                    DO UPDATE SET
                        last_vote_started_at =
                        excluded.last_vote_started_at
                    """,
                    (
                        guild.id,
                        now,
                    ),
                )

                await db.commit()

            vote = await self.get_game_vote(
                int(vote_id)
            )

            if vote is None:
                await self.send_feedback(
                    interaction,
                    "De game-vote kon niet uit de database worden geladen.",
                    kind="error",
                )
                return

            view = self.build_game_vote_view(
                vote,
                1,
            )

            await interaction.response.send_message(
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )

            message = await interaction.original_response()

            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                await db.execute(
                    """
                    UPDATE game_button_votes
                    SET message_id = ?
                    WHERE id = ?
                    """,
                    (
                        message.id,
                        vote_id,
                    ),
                )

                await db.commit()

            self.bot.add_view(
                view,
                message_id=message.id,
            )

            self.schedule_background(
                self.expire_game_vote(
                    int(vote_id),
                    expires_at,
                )
            )

    async def handle_game_vote_support(
        self,
        interaction,
        vote_id,
    ):
        now = int(
            time.time()
        )

        async with self.game_vote_lock:
            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                db.row_factory = aiosqlite.Row

                cursor = await db.execute(
                    """
                    SELECT *
                    FROM game_button_votes
                    WHERE id = ?
                    """,
                    (vote_id,),
                )

                vote = await cursor.fetchone()

                if not vote:
                    await self.send_feedback(
                        interaction,
                        "Deze vote bestaat niet meer.",
                        kind="error",
                    )
                    return

                if (
                    str(vote["status"]) != "active"
                    or int(vote["expires_at"]) <= now
                ):
                    await self.send_feedback(
                        interaction,
                        "Deze vote is niet meer actief.",
                        kind="warning",
                    )
                    return

                try:
                    await db.execute(
                        """
                        INSERT INTO game_button_support (
                            vote_id,
                            user_id
                        )
                        VALUES (?, ?)
                        """,
                        (
                            vote_id,
                            interaction.user.id,
                        ),
                    )
                except aiosqlite.IntegrityError:
                    await self.send_feedback(
                        interaction,
                        "Je hebt deze vote al gesteund.",
                        kind="info",
                        title="Stem al geregistreerd",
                    )
                    return

                cursor = await db.execute(
                    """
                    SELECT COUNT(*)
                    FROM game_button_support
                    WHERE vote_id = ?
                    """,
                    (vote_id,),
                )

                row = await cursor.fetchone()
                count = int(
                    row[0] or 0
                )

                await db.commit()

            if count < GAME_VOTE_REQUIRED:
                await interaction.response.defer(
                    ephemeral=True
                )

                updated_vote = await self.get_game_vote(
                    vote_id
                )

                if (
                    updated_vote is not None
                    and interaction.message is not None
                ):
                    try:
                        await interaction.message.edit(
                            content=None,
                            embed=None,
                            view=self.build_game_vote_view(
                                updated_vote,
                                count,
                            ),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    except discord.HTTPException:
                        logger.exception(
                            "Game-vote %s bijwerken mislukt.",
                            vote_id,
                        )

                await self.send_feedback(
                    interaction,
                    (
                        f"Je stem is toegevoegd.\n"
                        f"De vote staat nu op "
                        f"**{count}/{GAME_VOTE_REQUIRED}**."
                    ),
                    kind="success",
                    title="Stem toegevoegd",
                )
                return

            # ------------------------------------------------
            # VOTE GESLAAGD
            # ------------------------------------------------

            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                await db.execute(
                    """
                    UPDATE game_button_votes
                    SET status = 'passed'
                    WHERE id = ?
                      AND status = 'active'
                    """,
                    (vote_id,),
                )

                await db.commit()

            guild = self.bot.get_guild(
                int(vote["guild_id"])
            )

            if guild is None:
                await self.send_feedback(
                    interaction,
                    "De server kon niet meer worden gevonden.",
                    kind="error",
                )
                return

            try:
                role, game_channel = await create_game(
                    self.bot,
                    guild,
                    str(vote["game_name"]),
                    (
                        str(vote["steam_url"])
                        if vote["steam_url"]
                        else None
                    ),
                )
            except Exception:
                logger.exception(
                    "Game aanmaken na geslaagde vote %s mislukt.",
                    vote_id,
                )
                await self.send_feedback(
                    interaction,
                    "De vote is geslaagd, maar de game kon niet "
                    "automatisch worden aangemaakt. Controleer de botlog.",
                    kind="error",
                )
                return

            react_synced = False
            react_cog = self.bot.get_cog(
                "ReactRoles"
            )

            if (
                react_cog is not None
                and hasattr(
                    react_cog,
                    "ensure_voted_game",
                )
            ):
                try:
                    react_synced = bool(
                        await react_cog.ensure_voted_game(
                            guild,
                            role,
                            str(vote["game_name"]),
                        )
                    )
                except Exception:
                    logger.exception(
                        "React Roles sync mislukt na game-vote %s.",
                        vote_id,
                    )

            proposal_channel = guild.get_channel(
                GAME_PROPOSAL_CHANNEL_ID
            )

            if isinstance(
                proposal_channel,
                discord.TextChannel,
            ):
                try:
                    await create_temporary_role_button(
                        self.bot,
                        proposal_channel,
                        str(vote["game_name"]),
                        role,
                        (
                            str(vote["steam_url"])
                            if vote["steam_url"]
                            else None
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Tijdelijke game-role knop maken mislukt voor vote %s.",
                        vote_id,
                    )

            await notify_owner_new_game(
                self.bot,
                guild,
                str(vote["game_name"]),
                role,
                game_channel,
                react_synced=react_synced,
                steam_url=(
                    str(vote["steam_url"])
                    if vote["steam_url"]
                    else None
                ),
            )

            await interaction.response.defer(
                ephemeral=True
            )

            passed_vote = await self.get_game_vote(
                vote_id
            )

            if (
                passed_vote is not None
                and interaction.message is not None
            ):
                try:
                    await interaction.message.edit(
                        content=None,
                        embed=None,
                        view=self.build_game_vote_view(
                            passed_vote,
                            count,
                            status="passed",
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    logger.exception(
                        "Geslaagde game-vote %s visueel bijwerken mislukt.",
                        vote_id,
                    )

            await self.send_feedback(
                interaction,
                (
                    f"**{vote['game_name']}** heeft "
                    f"{GAME_VOTE_REQUIRED} stemmen gehaald "
                    "en is toegevoegd."
                ),
                kind="success",
                title="Game-vote geslaagd",
            )

    async def expire_game_vote(
        self,
        vote_id,
        expires_at,
    ):
        delay = max(
            0,
            expires_at - int(
                time.time()
            ),
        )

        await asyncio.sleep(
            delay
        )

        async with self.game_vote_lock:
            async with aiosqlite.connect(
                DATABASE_PATH
            ) as db:
                db.row_factory = aiosqlite.Row

                cursor = await db.execute(
                    """
                    SELECT *
                    FROM game_button_votes
                    WHERE id = ?
                    """,
                    (vote_id,),
                )

                vote = await cursor.fetchone()

                if not vote:
                    return

                if str(vote["status"]) != "active":
                    return

                await db.execute(
                    """
                    UPDATE game_button_votes
                    SET status = 'expired'
                    WHERE id = ?
                      AND status = 'active'
                    """,
                    (vote_id,),
                )

                await db.commit()

        guild = self.bot.get_guild(
            int(vote["guild_id"])
        )

        if not guild:
            return

        channel = guild.get_channel(
            int(vote["channel_id"])
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        if vote["message_id"] is None:
            return

        try:
            message = await channel.fetch_message(
                int(vote["message_id"])
            )

            count = await self.get_game_vote_count(
                vote_id
            )

            await message.edit(
                content=None,
                embed=None,
                view=self.build_game_vote_view(
                    vote,
                    count,
                    status="expired",
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        except discord.NotFound:
            pass
        except discord.Forbidden:
            logger.warning(
                "Geen toegang om verlopen game-vote %s bij te werken.",
                vote_id,
            )
        except discord.HTTPException:
            logger.exception(
                "Game-vote %s verlopen maken mislukt.",
                vote_id,
            )

    # ========================================================
    # /GAME UNARCHIVE
    # ========================================================

    @game.command(
        name="unarchive",
        description="Zet een gearchiveerde game terug",
    )
    async def unarchive_command(
        self,
        interaction: discord.Interaction,
        game_name: str,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit command werkt alleen op een server.",
                kind="error",
            )
            return

        game_name = clean_game_name(
            game_name
        )

        channel = find_archived_game_channel(
            interaction.guild,
            game_name,
        )

        if channel is None:
            await self.send_feedback(
                interaction,
                f"Gearchiveerde game **{game_name}** niet gevonden.",
                kind="warning",
            )
            return

        member = interaction.user

        if (
            isinstance(
                member,
                discord.Member,
            )
            and management_access(
                member
            )
        ):
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )

            try:
                restored = await unarchive_game_now(
                    self.bot,
                    interaction.guild,
                    game_name,
                )
            except Exception:
                logger.exception(
                    "Game %s direct terugzetten mislukt.",
                    game_name,
                )
                await self.send_feedback(
                    interaction,
                    "De game kon niet worden teruggezet. "
                    "Controleer de botlog.",
                    kind="error",
                )
                return

            if restored is None:
                await self.send_feedback(
                    interaction,
                    f"**{game_name}** is niet meer in het archief gevonden.",
                    kind="warning",
                )
                return

            await self.send_feedback(
                interaction,
                f"**{game_name}** is direct teruggezet.",
                kind="success",
                title="Game teruggezet",
            )
            return

        await self.create_unarchive_vote(
            interaction,
            game_name,
        )

    async def create_unarchive_vote(
        self,
        interaction,
        game_name,
    ):
        guild = interaction.guild

        if guild is None:
            return

        vote_channel = guild.get_channel(
            UNARCHIVE_CHANNEL_ID
        )

        if not isinstance(
            vote_channel,
            discord.TextChannel,
        ):
            await self.send_feedback(
                interaction,
                "Het kanaal voor terugzet-votes is niet gevonden.",
                kind="error",
            )
            return

        now = int(
            time.time()
        )

        expires_at = (
            now
            + UNARCHIVE_VOTE_DURATION
        )

        normalized = normalize_game_name(
            game_name
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            cursor = await db.execute(
                """
                SELECT id
                FROM unarchive_button_votes
                WHERE guild_id = ?
                  AND normalized_name = ?
                  AND status = 'active'
                  AND expires_at > ?
                LIMIT 1
                """,
                (
                    guild.id,
                    normalized,
                    now,
                ),
            )

            existing = await cursor.fetchone()

            if existing:
                await self.send_feedback(
                    interaction,
                    "Voor deze game loopt al een vote om hem terug te zetten.",
                    kind="warning",
                )
                return

            cursor = await db.execute(
                """
                INSERT INTO unarchive_button_votes (
                    guild_id,
                    channel_id,
                    creator_id,
                    game_name,
                    normalized_name,
                    created_at,
                    expires_at,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    guild.id,
                    vote_channel.id,
                    interaction.user.id,
                    game_name,
                    normalized,
                    now,
                    expires_at,
                ),
            )

            vote_id = cursor.lastrowid

            await db.execute(
                """
                INSERT INTO unarchive_button_support (
                    vote_id,
                    user_id
                )
                VALUES (?, ?)
                """,
                (
                    vote_id,
                    interaction.user.id,
                ),
            )

            await db.commit()

        vote = await self.get_unarchive_vote(
            int(vote_id)
        )

        if vote is None:
            await self.send_feedback(
                interaction,
                "De terugzet-vote kon niet worden geladen.",
                kind="error",
            )
            return

        view = self.build_unarchive_vote_view(
            vote,
            1,
        )

        try:
            message = await vote_channel.send(
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            await self.send_feedback(
                interaction,
                "Ik kan geen bericht plaatsen in het terugzet-kanaal.",
                kind="error",
            )
            return
        except discord.HTTPException:
            logger.exception(
                "Unarchive-vote %s plaatsen mislukt.",
                vote_id,
            )
            await self.send_feedback(
                interaction,
                "Discord kon de terugzet-vote niet plaatsen.",
                kind="error",
            )
            return

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                """
                UPDATE unarchive_button_votes
                SET message_id = ?
                WHERE id = ?
                """,
                (
                    message.id,
                    vote_id,
                ),
            )

            await db.commit()

        self.bot.add_view(
            view,
            message_id=message.id,
        )

        self.schedule_background(
            self.expire_unarchive_vote(
                int(vote_id),
                expires_at,
            )
        )

        await self.send_feedback(
            interaction,
            (
                f"De vote voor **{game_name}** is gestart in "
                f"{vote_channel.mention}."
            ),
            kind="success",
            title="Terugzet-vote gestart",
        )

    async def handle_unarchive_support(
        self,
        interaction,
        vote_id,
    ):
        now = int(
            time.time()
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM unarchive_button_votes
                WHERE id = ?
                """,
                (vote_id,),
            )

            vote = await cursor.fetchone()

            if not vote:
                await self.send_feedback(
                    interaction,
                    "Deze vote bestaat niet meer.",
                    kind="error",
                )
                return

            if (
                str(vote["status"]) != "active"
                or int(vote["expires_at"]) <= now
            ):
                await self.send_feedback(
                    interaction,
                    "Deze vote is niet meer actief.",
                    kind="warning",
                )
                return

            try:
                await db.execute(
                    """
                    INSERT INTO unarchive_button_support (
                        vote_id,
                        user_id
                    )
                    VALUES (?, ?)
                    """,
                    (
                        vote_id,
                        interaction.user.id,
                    ),
                )

            except aiosqlite.IntegrityError:
                await self.send_feedback(
                    interaction,
                    "Je hebt deze vote al gesteund.",
                    kind="info",
                    title="Stem al geregistreerd",
                )
                return

            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM unarchive_button_support
                WHERE vote_id = ?
                """,
                (vote_id,),
            )

            count = int(
                (await cursor.fetchone())[0]
            )

            await db.commit()

        if count < UNARCHIVE_VOTE_REQUIRED:
            await interaction.response.defer(
                ephemeral=True
            )

            current_vote = await self.get_unarchive_vote(
                vote_id
            )

            if (
                current_vote is not None
                and interaction.message is not None
            ):
                try:
                    await interaction.message.edit(
                        content=None,
                        embed=None,
                        view=self.build_unarchive_vote_view(
                            current_vote,
                            count,
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    logger.exception(
                        "Unarchive-vote %s bijwerken mislukt.",
                        vote_id,
                    )

            await self.send_feedback(
                interaction,
                (
                    f"Je stem is toegevoegd.\n"
                    f"De vote staat nu op "
                    f"**{count}/{UNARCHIVE_VOTE_REQUIRED}**."
                ),
                kind="success",
                title="Stem toegevoegd",
            )
            return

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            await db.execute(
                """
                UPDATE unarchive_button_votes
                SET status = 'passed'
                WHERE id = ?
                  AND status = 'active'
                """,
                (vote_id,),
            )

            await db.commit()

        guild = self.bot.get_guild(
            int(vote["guild_id"])
        )

        if guild:
            try:
                await unarchive_game_now(
                    self.bot,
                    guild,
                    str(vote["game_name"]),
                )
            except Exception:
                logger.exception(
                    "Game terugzetten na unarchive-vote %s mislukt.",
                    vote_id,
                )
                await self.send_feedback(
                    interaction,
                    "De vote is geslaagd, maar de game kon niet "
                    "automatisch worden teruggezet. Controleer de botlog.",
                    kind="error",
                )
                return

        await interaction.response.defer(
            ephemeral=True
        )

        passed_vote = await self.get_unarchive_vote(
            vote_id
        )

        if (
            passed_vote is not None
            and interaction.message is not None
        ):
            try:
                await interaction.message.edit(
                    content=None,
                    embed=None,
                    view=self.build_unarchive_vote_view(
                        passed_vote,
                        count,
                        status="passed",
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                logger.exception(
                    "Geslaagde unarchive-vote %s visueel bijwerken mislukt.",
                    vote_id,
                )

        await self.send_feedback(
            interaction,
            f"**{vote['game_name']}** wordt teruggezet.",
            kind="success",
            title="Vote geslaagd",
        )

    async def expire_unarchive_vote(
        self,
        vote_id,
        expires_at,
    ):
        delay = max(
            0,
            expires_at - int(
                time.time()
            ),
        )

        await asyncio.sleep(
            delay
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT *
                FROM unarchive_button_votes
                WHERE id = ?
                """,
                (vote_id,),
            )

            vote = await cursor.fetchone()

            if not vote:
                return

            if str(vote["status"]) != "active":
                return

            await db.execute(
                """
                UPDATE unarchive_button_votes
                SET status = 'expired'
                WHERE id = ?
                  AND status = 'active'
                """,
                (vote_id,),
            )

            await db.commit()

        guild = self.bot.get_guild(
            int(vote["guild_id"])
        )

        if not guild:
            return

        channel = guild.get_channel(
            int(vote["channel_id"])
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        if vote["message_id"] is None:
            return

        try:
            message = await channel.fetch_message(
                int(vote["message_id"])
            )

            count = await self.get_unarchive_vote_count(
                vote_id
            )

            await message.edit(
                content=None,
                embed=None,
                view=self.build_unarchive_vote_view(
                    vote,
                    count,
                    status="expired",
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        except discord.NotFound:
            pass
        except discord.Forbidden:
            logger.warning(
                "Geen toegang om verlopen unarchive-vote %s bij te werken.",
                vote_id,
            )
        except discord.HTTPException:
            logger.exception(
                "Unarchive-vote %s verlopen maken mislukt.",
                vote_id,
            )

    # ========================================================
    # RESTORE PERSISTENT COMPONENTS
    # ========================================================

    async def restore_game_votes(
        self,
    ):
        now = int(
            time.time()
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            db.row_factory = aiosqlite.Row

            rows = await (
                await db.execute(
                    """
                    SELECT *
                    FROM game_button_votes
                    WHERE status = 'active'
                    """
                )
            ).fetchall()

        restored = 0

        for vote in rows:
            vote_id = int(
                vote["id"]
            )
            expires_at = int(
                vote["expires_at"]
            )

            if expires_at <= now:
                self.schedule_background(
                    self.expire_game_vote(
                        vote_id,
                        now,
                    )
                )
                continue

            if vote["message_id"]:
                count = await self.get_game_vote_count(
                    vote_id
                )

                self.bot.add_view(
                    self.build_game_vote_view(
                        vote,
                        count,
                    ),
                    message_id=int(
                        vote["message_id"]
                    ),
                )

                restored += 1

            self.schedule_background(
                self.expire_game_vote(
                    vote_id,
                    expires_at,
                )
            )

        logger.info(
            "%s actieve game-vote view(s) hersteld.",
            restored,
        )

    async def restore_temp_buttons(
        self,
    ):
        now = int(
            time.time()
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            db.row_factory = aiosqlite.Row

            rows = await (
                await db.execute(
                    """
                    SELECT *
                    FROM temp_role_buttons_v2
                    WHERE status = 'active'
                    """
                )
            ).fetchall()

        restored = 0

        for row in rows:
            message_id = int(
                row["message_id"]
            )
            guild_id = int(
                row["guild_id"]
            )
            channel_id = int(
                row["channel_id"]
            )
            role_id = int(
                row["role_id"]
            )
            game_name = str(
                row["game_name"]
            )
            expires_at = int(
                row["expires_at"]
            )
            steam_url = (
                str(row["steam_url"])
                if row["steam_url"]
                else None
            )

            if expires_at > now:
                self.bot.add_view(
                    TempRoleView(
                        role_id,
                        game_name,
                        expires_at,
                        steam_url,
                    ),
                    message_id=message_id,
                )

                restored += 1

            self.schedule_background(
                expire_temporary_role_button(
                    self.bot,
                    message_id,
                    guild_id,
                    channel_id,
                    role_id,
                    game_name,
                    expires_at,
                    steam_url,
                )
            )

        logger.info(
            "%s actieve tijdelijke game-role view(s) hersteld.",
            restored,
        )

    async def restore_unarchive_votes(
        self,
    ):
        now = int(
            time.time()
        )

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:
            db.row_factory = aiosqlite.Row

            rows = await (
                await db.execute(
                    """
                    SELECT *
                    FROM unarchive_button_votes
                    WHERE status = 'active'
                    """
                )
            ).fetchall()

        restored = 0

        for vote in rows:
            vote_id = int(
                vote["id"]
            )
            expires_at = int(
                vote["expires_at"]
            )

            if vote["message_id"] and expires_at > now:
                count = await self.get_unarchive_vote_count(
                    vote_id
                )

                self.bot.add_view(
                    self.build_unarchive_vote_view(
                        vote,
                        count,
                    ),
                    message_id=int(
                        vote["message_id"]
                    ),
                )

                restored += 1

            self.schedule_background(
                self.expire_unarchive_vote(
                    vote_id,
                    expires_at,
                )
            )

        logger.info(
            "%s actieve unarchive-vote view(s) hersteld.",
            restored,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Games(bot)
    )
