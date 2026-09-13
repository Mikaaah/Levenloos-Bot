import asyncio
import logging
import re

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands


LOGGER = logging.getLogger(__name__)

if not all(
    hasattr(discord.ui, component)
    for component in ("LayoutView", "Container", "TextDisplay", "Separator", "ActionRow")
):
    raise RuntimeError(
        "react(3).py vereist discord.py 2.6 of nieuwer voor Discord Components V2."
    )

# =========================================================
# CONFIG
# =========================================================

DATABASE_PATH = "levenloos.db"

DEFAULT_ROLE_CHANNEL_ID = 940376085865037884
ADMIN_ACCESS_ROLE_ID = 940331020434161674
DIVIDER_ROLE_ID = 1546599899682967662

REACT_ROLES_BANNER = (
    "<:r1:1546442663903895604>"
    "<:r2:1546442688595890186>"
    "<:r3:1546442710439829566>"
    "<:r4:1546442734062141460>"
    "<:r5:1546442754777686087>"
    "<:r6:1546442824025899018>"
    "<:r7:1546442846792450128>"
    "<:r8:1546442879012962344>"
    "<:r9:1546442901272137768>"
)

GAMES_EMOJI = "<:games:1546435140790517780>"
GENRES_EMOJI = "<:genres:1546435084897222686>"
ROLES_EMOJI = "<:roll:1546435118455988332>"

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

ITEMS_PER_PAGE = 20

# Admin beheer UI
MAX_BULK_ROLES = 10
COLOR_ROLE_PREFIX = "◆ "
DEFAULT_COLOR_LEVEL = 100

BRAND_COLOUR = discord.Colour.from_rgb(108, 39, 218)
ADMIN_VIEW_TIMEOUT = 900


# =========================================================
# ACCESS
# =========================================================

def management_access(
    member: discord.Member
) -> bool:

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
        or
        "owner" in role_names
    )


# =========================================================
# DATABASE
# =========================================================

async def initialise_database():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS react_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS react_items (
                guild_id INTEGER NOT NULL,
                section TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                button_name TEXT NOT NULL,
                emoji TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                min_level INTEGER NOT NULL DEFAULT 1,
                item_group TEXT NOT NULL DEFAULT 'roles',
                PRIMARY KEY (guild_id, section, role_id)
            )
            """
        )

        migrations = (
            "ALTER TABLE react_config ADD COLUMN message_id INTEGER",
            "ALTER TABLE react_items ADD COLUMN min_level INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE react_items ADD COLUMN item_group TEXT NOT NULL DEFAULT 'roles'",
        )
        for statement in migrations:
            try:
                await db.execute(statement)
            except aiosqlite.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

        await db.commit()

    LOGGER.info("React Roles-database klaar")


# =========================================================
# HELPERS
# =========================================================

def section_info(
    section: str
) -> tuple[str, str, str]:

    if section == "game":
        return (
            "Games",
            GAMES_EMOJI,
            "Kies de games die je speelt."
        )

    if section == "genre":
        return (
            "Genres",
            GENRES_EMOJI,
            "Kies je favoriete gamegenres."
        )

    if section == "color":
        return (
            "Kleuren",
            COLOR_EMOJI,
            "Kies één kleur die je hebt vrijgespeeld."
        )

    if section == "roles":
        return (
            "Rollen",
            ROLES_EMOJI,
            "Kies de extra rollen die bij jou passen."
        )

    return (
        "Roles",
        ROLES_EMOJI,
        "Kies de overige rollen die bij jou passen."
    )


def clean_role_name(
    role: discord.Role
) -> str:

    return role.name.lstrip(
        "◆ "
    ).strip()


def parse_emoji(
    value: str | None,
    default: str
) -> str:

    if value is None:
        return default

    value = value.strip()

    if not value:
        return default

    emoji = discord.PartialEmoji.from_str(
        value
    )

    if not emoji.name:
        raise ValueError(
            "Ongeldige emoji"
        )

    return value



def normalise_hex(value: str) -> int:
    """Parse #RRGGBB / RRGGBB naar een integer kleurwaarde."""
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError("Gebruik een HEX-kleur zoals #A93BD6.")
    return int(value, 16)


def hex_string(value: int) -> str:
    return f"#{value:06X}"


def interpolate_colour(start: int, end: int, index: int, total: int) -> int:
    if total <= 1:
        return start

    ratio = index / (total - 1)

    sr, sg, sb = (start >> 16) & 255, (start >> 8) & 255, start & 255
    er, eg, eb = (end >> 16) & 255, (end >> 8) & 255, end & 255

    r = round(sr + (er - sr) * ratio)
    g = round(sg + (eg - sg) * ratio)
    b = round(sb + (eb - sb) * ratio)

    return (r << 16) | (g << 8) | b


def formatted_colour_role_name(name: str) -> str:
    cleaned = name.strip()
    while cleaned.startswith("◆"):
        cleaned = cleaned[1:].strip()
    return f"{COLOR_ROLE_PREFIX}{cleaned}"[:100]
def partial_emoji_or_none(
    value: str | None,
    guild: discord.Guild | None = None,
) -> discord.PartialEmoji | None:
    # Application emoji's staan niet in guild.emojis. Alleen syntactisch parsen
    # voorkomt dat geldige app-emoji's op andere servers verdwijnen.
    _ = guild
    if not value:
        return None
    try:
        emoji = discord.PartialEmoji.from_str(value)
    except Exception:
        return None
    return emoji if emoji.name else None


def make_text_container(
    content: str,
    *,
    accent_colour: discord.Colour | int | None = BRAND_COLOUR,
) -> discord.ui.Container:
    return discord.ui.Container(
        discord.ui.TextDisplay(content),
        accent_colour=accent_colour,
    )


def add_action_rows(
    container: discord.ui.Container,
    buttons: list[discord.ui.Button],
) -> None:
    for start in range(0, len(buttons), 5):
        container.add_item(discord.ui.ActionRow(*buttons[start:start + 5]))


# =========================================================
# REACT COG
# =========================================================

class ReactRoles(
    commands.Cog
):

    react = app_commands.Group(
        name="react",
        description="Beheer het React Roles-systeem"
    )

    game = app_commands.Group(
        name="game",
        description="Beheer game-rollen",
        parent=react
    )

    genre = app_commands.Group(
        name="genre",
        description="Beheer genre-rollen",
        parent=react
    )

    role_group = app_commands.Group(
        name="role",
        description="Beheer algemene rollen",
        parent=react
    )

    def __init__(
        self,
        bot: commands.Bot
    ):

        self.bot = bot

    async def cog_load(self):
        await initialise_database()
        LOGGER.info("React-role module geladen")

    # =====================================================
    # CONFIG
    # =====================================================

    async def get_config(
        self,
        guild_id: int
    ):

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:

            cursor = await db.execute(
                """
                SELECT
                    channel_id,
                    message_id
                FROM react_config
                WHERE guild_id = ?
                """,
                (
                    guild_id,
                )
            )

            return await cursor.fetchone()

    async def set_config(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int | None
    ):

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:

            await db.execute(
                """
                INSERT INTO react_config (
                    guild_id,
                    channel_id,
                    message_id
                )
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id
                """,
                (
                    guild_id,
                    channel_id,
                    message_id,
                )
            )

            await db.commit()

    # =====================================================
    # PUBLIC MAIN MENU
    # =====================================================

    def build_main_view(self, guild: discord.Guild) -> discord.ui.LayoutView:
        view = discord.ui.LayoutView(timeout=None)
        container = make_text_container(self.main_content())
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.ActionRow(
                discord.ui.Button(
                    label="Games",
                    emoji=partial_emoji_or_none(GAMES_EMOJI, guild),
                    style=discord.ButtonStyle.primary,
                    custom_id="react_open:game",
                ),
                discord.ui.Button(
                    label="Genres",
                    emoji=partial_emoji_or_none(GENRES_EMOJI, guild),
                    style=discord.ButtonStyle.primary,
                    custom_id="react_open:genre",
                ),
                discord.ui.Button(
                    label="Rollen",
                    emoji=partial_emoji_or_none(ROLES_EMOJI, guild),
                    style=discord.ButtonStyle.primary,
                    custom_id="react_open:role",
                ),
            )
        )
        view.add_item(container)
        return view

    def main_content(self) -> str:
        return (
            f"# {REACT_ROLES_BANNER}\n\n"
            "Kies hieronder welke rollen bij jou passen.\n\n"
            f"## {GAMES_EMOJI} Games\n"
            "> └ Kies de games die je speelt.\n\n"
            f"## {GENRES_EMOJI} Genres\n"
            "> └ Kies je favoriete gamegenres.\n\n"
            f"## {ROLES_EMOJI} Rollen\n"
            "> └ Kies kleuren en overige serverrollen.\n\n"
            "-# Klik een gekozen optie opnieuw aan om de rol weer te verwijderen."
        )

    async def refresh_main_message(self, guild: discord.Guild):
        config = await self.get_config(guild.id)
        if config:
            channel_id, message_id = config
        else:
            channel_id = DEFAULT_ROLE_CHANNEL_ID
            message_id = None

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError("React Roles-kanaal niet gevonden.")

        message = None
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                message = None
            except discord.Forbidden as exc:
                raise RuntimeError("Ik kan het bestaande React Roles-bericht niet ophalen.") from exc
            except discord.HTTPException as exc:
                raise RuntimeError("Discord kon het React Roles-bericht niet ophalen.") from exc

        view = self.build_main_view(guild)
        if message is not None:
            await message.edit(
                content=None,
                embeds=[],
                attachments=[],
                view=view,
            )
        else:
            message = await channel.send(view=view)
            await self.set_config(guild.id, channel.id, message.id)

        return message

    # =====================================================
    # ITEMS
    # =====================================================

    async def get_entries(
        self,
        guild: discord.Guild,
        section: str,
    ) -> list[dict]:
        db_section = "role" if section in {"color", "roles"} else section

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                SELECT
                    role_id,
                    button_name,
                    emoji,
                    sort_order,
                    min_level,
                    item_group
                FROM react_items
                WHERE guild_id = ?
                AND section = ?
                ORDER BY
                    CASE WHEN min_level <= 1 THEN 0 ELSE 1 END ASC,
                    min_level ASC,
                    button_name COLLATE NOCASE ASC,
                    sort_order ASC
                """,
                (guild.id, db_section),
            )
            rows = await cursor.fetchall()

        entries: list[dict] = []
        missing_role_ids: list[int] = []

        for role_id, button_name, emoji, sort_order, min_level, item_group in rows:
            row_group = (item_group or "roles").lower()
            if section in {"color", "roles"} and row_group != section:
                continue

            role = guild.get_role(role_id)
            if role is None:
                missing_role_ids.append(role_id)
                continue

            entries.append(
                {
                    "role_id": role_id,
                    "button_name": button_name,
                    "emoji": emoji,
                    "sort_order": sort_order,
                    "min_level": max(1, int(min_level or 1)),
                    "group": row_group,
                }
            )

        if missing_role_ids:
            LOGGER.warning(
                "React Roles bevat %s ontbrekende rol(len) in guild %s, sectie %s: %s",
                len(missing_role_ids),
                guild.id,
                section,
                missing_role_ids,
            )

        return entries

    async def get_entry(
        self,
        guild_id: int,
        section: str,
        role_id: int
    ):

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:

            cursor = await db.execute(
                """
                SELECT
                    button_name,
                    emoji,
                    min_level,
                    item_group
                FROM react_items
                WHERE guild_id = ?
                AND section = ?
                AND role_id = ?
                """,
                (
                    guild_id,
                    section,
                    role_id,
                )
            )

            return await cursor.fetchone()

    async def add_or_update_item(
        self,
        guild_id: int,
        section: str,
        role_id: int,
        button_name: str,
        emoji: str,
        min_level: int = 1,
        item_group: str = "roles"
    ):

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:

            cursor = await db.execute(
                """
                SELECT COALESCE(
                    MAX(sort_order),
                    -1
                ) + 1
                FROM react_items
                WHERE guild_id = ?
                AND section = ?
                """,
                (
                    guild_id,
                    section,
                )
            )

            row = await cursor.fetchone()

            sort_order = (
                row[0]
                if row
                else 0
            )

            await db.execute(
                """
                INSERT INTO react_items (
                    guild_id,
                    section,
                    role_id,
                    button_name,
                    emoji,
                    sort_order,
                    min_level,
                    item_group
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    guild_id,
                    section,
                    role_id
                )
                DO UPDATE SET
                    button_name = excluded.button_name,
                    emoji = excluded.emoji,
                    min_level = excluded.min_level,
                    item_group = excluded.item_group
                """,
                (
                    guild_id,
                    section,
                    role_id,
                    button_name,
                    emoji,
                    sort_order,
                    max(1, int(min_level)),
                    item_group,
                )
            )

            await db.commit()

    async def ensure_voted_game(
        self,
        guild: discord.Guild,
        role: discord.Role,
        game_name: str,
    ) -> bool:
        """
        Zorg dat een game die een gamevote heeft gewonnen direct bij
        React Roles -> Games staat.

        Nieuwe games krijgen tijdelijk de algemene Games-emoji. Een eerder
        ingestelde custom emoji wordt nooit overschreven.
        """
        game_name = str(game_name).strip()
        if not game_name:
            return False

        current = await self.get_entry(
            guild.id,
            "game",
            role.id,
        )

        if current is None:
            await self.add_or_update_item(
                guild.id,
                "game",
                role.id,
                game_name[:80],
                GAMES_EMOJI,
                1,
                "roles",
            )
            LOGGER.info(
                "Gamevote '%s' automatisch toegevoegd aan React Roles met standaardemoji %s",
                game_name,
                GAMES_EMOJI,
            )
            return True

        current_name = str(current[0] or game_name).strip()
        current_emoji = str(current[1] or GAMES_EMOJI).strip()

        # Houd een bestaande custom emoji intact, maar zorg dat de naam netjes
        # overeenkomt met de game die daadwerkelijk is aangemaakt.
        if current_name != game_name:
            await self.add_or_update_item(
                guild.id,
                "game",
                role.id,
                game_name[:80],
                current_emoji,
                1,
                "roles",
            )

        return True

    async def find_game_entry_by_name(
        self,
        guild: discord.Guild,
        game_name: str,
    ) -> dict | None:
        """Zoek een React Roles-game op buttonnaam of Discord-rolnaam."""
        wanted = game_name.strip().casefold()
        if not wanted:
            return None

        entries = await self.get_entries(
            guild,
            "game",
        )

        # Eerst exact.
        for entry in entries:
            role = guild.get_role(entry["role_id"])
            role_name = (
                clean_role_name(role).casefold()
                if role is not None
                else ""
            )
            if (
                str(entry["button_name"]).strip().casefold() == wanted
                or role_name == wanted
            ):
                return entry

        # Daarna een unieke gedeeltelijke match.
        matches = []
        for entry in entries:
            role = guild.get_role(entry["role_id"])
            role_name = (
                clean_role_name(role).casefold()
                if role is not None
                else ""
            )
            button_name = str(entry["button_name"]).strip().casefold()

            if wanted in button_name or wanted in role_name:
                matches.append(entry)

        return matches[0] if len(matches) == 1 else None

    async def get_member_level(self, member: discord.Member) -> int:
        """Lees het actuele level uit de Levels-cog."""
        levels_cog = self.bot.get_cog("Levels")
        if levels_cog is None or not hasattr(levels_cog, "get_user"):
            return 1

        try:
            row = await levels_cog.get_user(member.guild.id, member.id)
        except Exception:
            LOGGER.exception(
                "Kon level niet ophalen voor member %s in guild %s",
                member.id,
                member.guild.id,
            )
            return 1

        if not row:
            return 1

        total_xp = max(0, int(row[0]))
        level = 1
        while 100 * (((level + 1) * (level + 2) // 2) - 1) <= total_xp:
            level += 1
        return level

    def build_role_hub_view(self, guild: discord.Guild) -> discord.ui.LayoutView:
        view = discord.ui.LayoutView(timeout=ADMIN_VIEW_TIMEOUT)
        container = make_text_container(
            f"## {ROLES_EMOJI} Rollen\n"
            "> └ Kies welk onderdeel je wilt aanpassen.\n\n"
            f"### {COLOR_EMOJI} Kleuren\n"
            "> └ Kies één vrijgespeelde naamkleur.\n\n"
            f"### {ROLES_EMOJI} Rollen\n"
            "> └ Kies Events, Movienight en andere extra rollen."
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.ActionRow(
                discord.ui.Button(
                    label="Kleuren",
                    emoji=partial_emoji_or_none(COLOR_EMOJI, guild),
                    style=discord.ButtonStyle.primary,
                    custom_id="react_subopen:color",
                ),
                discord.ui.Button(
                    label="Rollen",
                    emoji=partial_emoji_or_none(ROLES_EMOJI, guild),
                    style=discord.ButtonStyle.primary,
                    custom_id="react_subopen:roles",
                ),
            )
        )
        view.add_item(container)
        return view

    async def send_role_hub(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            view=self.build_role_hub_view(interaction.guild),
            ephemeral=True,
        )

    # =====================================================
    # EPHEMERAL SELECTOR
    # =====================================================

    async def build_selector_view(
        self,
        member: discord.Member,
        section: str,
        entries: list[dict],
        page: int,
        content: str,
    ) -> discord.ui.LayoutView:
        view = discord.ui.LayoutView(timeout=ADMIN_VIEW_TIMEOUT)
        container = make_text_container(content)
        member_level = await self.get_member_level(member) if section in {"color", "roles"} else 999

        if section == "color" and member.guild.get_role(ADMIN_ACCESS_ROLE_ID) not in member.roles:
            entries = [
                entry
                for entry in entries
                if entry["button_name"].strip().lower() != "admin kleur"
            ]

        if section == "color":
            entries = [
                {
                    "role_id": 0,
                    "button_name": "Geen kleur",
                    "emoji": NONE_EMOJI,
                    "sort_order": -1,
                    "min_level": 1,
                    "group": "color",
                }
            ] + entries

        total_pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        start = page * ITEMS_PER_PAGE
        page_entries = entries[start:start + ITEMS_PER_PAGE]

        role_buttons: list[discord.ui.Button] = []
        colour_role_ids = {
            int(entry["role_id"])
            for entry in entries
            if entry.get("role_id")
        }
        member_role_ids = {role.id for role in member.roles}

        for entry in page_entries:
            role_id = int(entry["role_id"])
            role = member.guild.get_role(role_id) if role_id else None
            if role_id and role is None:
                continue

            required_level = max(1, int(entry.get("min_level", 1)))
            is_admin_color = entry["button_name"].strip().lower() == "admin kleur"
            locked = (not is_admin_color) and member_level < required_level
            has_role = (
                role_id in member_role_ids
                if role_id
                else not bool(colour_role_ids & member_role_ids)
            )

            label = entry["button_name"]
            if locked:
                label = f"{label} · Lvl {required_level}"

            role_buttons.append(
                discord.ui.Button(
                    label=label[:80],
                    emoji=partial_emoji_or_none(LOCK_EMOJI if locked else entry.get("emoji"), member.guild),
                    style=(
                        discord.ButtonStyle.success
                        if has_role
                        else discord.ButtonStyle.secondary
                    ),
                    disabled=locked,
                    custom_id=f"react_toggle:{section}:{role_id}:{page}",
                )
            )

        if role_buttons:
            container.add_item(discord.ui.Separator())
            add_action_rows(container, role_buttons)

        if total_pages > 1:
            container.add_item(discord.ui.Separator())
            container.add_item(
                discord.ui.ActionRow(
                    discord.ui.Button(
                        label="Vorige",
                        emoji=partial_emoji_or_none(PREVIOUS_EMOJI),
                        style=discord.ButtonStyle.secondary,
                        custom_id=f"react_page:{section}:{page - 1}",
                        disabled=(page <= 0),
                    ),
                    discord.ui.Button(
                        label=f"Pagina {page + 1}/{total_pages}",
                        style=discord.ButtonStyle.secondary,
                        custom_id=f"react_pageinfo:{section}:{page}",
                        disabled=True,
                    ),
                    discord.ui.Button(
                        label="Volgende",
                        emoji=partial_emoji_or_none(NEXT_EMOJI),
                        style=discord.ButtonStyle.secondary,
                        custom_id=f"react_page:{section}:{page + 1}",
                        disabled=(page >= total_pages - 1),
                    ),
                )
            )

        view.add_item(container)
        return view

    async def selector_content(
        self,
        guild: discord.Guild,
        section: str,
        page: int,
    ) -> tuple[str, list[dict], int]:
        entries = await self.get_entries(guild, section)
        title, emoji, description = section_info(section)
        total_pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))

        if entries:
            notes = [
                "> └ Geselecteerde rollen worden groen weergegeven.",
                "> └ Klik een gekozen rol opnieuw aan om hem te verwijderen.",
            ]
            if section in {"color", "roles"}:
                notes.insert(1, f"> └ {LOCK_EMOJI} Vergrendelde opties tonen het vereiste level.")
            if section == "color":
                notes.insert(2, "> └ Je kunt maar één kleur tegelijk kiezen.")

            content = (
                f"## {emoji} {title}\n"
                f"> └ {description}\n\n"
                + "\n".join(notes)
            )
        else:
            content = (
                f"## {emoji} {title}\n"
                "> └ Er zijn voor dit onderdeel nog geen rollen ingesteld."
            )

        return content, entries, page

    async def send_selector(
        self,
        interaction: discord.Interaction,
        section: str,
        page: int = 0,
    ):
        if interaction.guild is None:
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        content, entries, page = await self.selector_content(
            interaction.guild,
            section,
            page,
        )
        view = await self.build_selector_view(
            member,
            section,
            entries,
            page,
            content,
        )
        await interaction.response.send_message(view=view, ephemeral=True)

    async def edit_selector(
        self,
        interaction: discord.Interaction,
        section: str,
        page: int,
    ):
        if interaction.guild is None:
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        try:
            fresh_member = await interaction.guild.fetch_member(member.id)
        except discord.HTTPException:
            fresh_member = member

        content, entries, page = await self.selector_content(
            interaction.guild,
            section,
            page,
        )
        view = await self.build_selector_view(
            fresh_member,
            section,
            entries,
            page,
            content,
        )
        await interaction.response.edit_message(view=view)

    # =====================================================
    # ADMIN HELPERS
    # =====================================================

    async def validate_admin(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.guild is None:
            return False

        member = interaction.user

        if (
            not isinstance(
                member,
                discord.Member
            )
            or
            not management_access(
                member
            )
        ):

            await interaction.response.send_message(
                f"{ERROR_EMOJI} Je hebt geen toegang tot dit command.",
                ephemeral=True
            )

            return False

        return True

    async def add_item_command(
        self,
        interaction: discord.Interaction,
        section: str,
        role: discord.Role,
        buttonnaam: str,
        emoji: str | None,
        min_level: int = 1,
        item_group: str = "roles"
    ):

        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        buttonnaam = buttonnaam.strip()

        if not 1 <= len(
            buttonnaam
        ) <= 80:

            await interaction.response.send_message(
                f"{ERROR_EMOJI} Buttonnaam moet tussen 1 en 80 tekens zijn.",
                ephemeral=True
            )
            return

        if role.is_default():

            await interaction.response.send_message(
                f"{ERROR_EMOJI} @everyone kan niet gebruikt worden.",
                ephemeral=True
            )
            return

        if role.managed:

            await interaction.response.send_message(
                f"{ERROR_EMOJI} Deze rol wordt door Discord of een integratie beheerd.",
                ephemeral=True
            )
            return

        bot_member = interaction.guild.me

        if (
            bot_member is None
            or
            role >= bot_member.top_role
        ):

            await interaction.response.send_message(
                f"{ERROR_EMOJI} Mijn botrol moet boven deze rol staan.",
                ephemeral=True
            )
            return

        _, default_emoji, _ = section_info(
            section
        )

        try:
            chosen_emoji = parse_emoji(
                emoji,
                default_emoji
            )
        except ValueError:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Ongeldige emoji. Gebruik bijvoorbeeld `🎮` "
                "of `<:naam:123456789>`.",
                ephemeral=True
            )
            return

        if section == "role":
            item_group = item_group.strip().lower()
            if item_group not in {"roles", "color"}:
                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Group moet `roles` of `color` zijn.", ephemeral=True
                )
                return
            if min_level < 1 or min_level > 999:
                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Level moet tussen 1 en 999 liggen.", ephemeral=True
                )
                return
        else:
            min_level = 1
            item_group = "roles"

        await self.add_or_update_item(
            interaction.guild.id,
            section,
            role.id,
            buttonnaam,
            chosen_emoji,
            min_level,
            item_group
        )

        await interaction.response.send_message(
            f"{SUCCESS_EMOJI} **{buttonnaam}** toegevoegd.\n"
            f"└ Rol: {role.mention}\n"
            f"└ Emoji: {chosen_emoji}"
            + (f"\n└ Level: **{min_level}**\n└ Group: `{item_group}`" if section == "role" else ""),
            ephemeral=True
        )

    async def edit_item_command(
        self,
        interaction: discord.Interaction,
        section: str,
        role: discord.Role,
        buttonnaam: str | None,
        emoji: str | None,
        min_level: int | None = None,
        item_group: str | None = None
    ):

        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        current = await self.get_entry(
            interaction.guild.id,
            section,
            role.id
        )

        if current is None:

            await interaction.response.send_message(
                f"{ERROR_EMOJI} Deze rol staat niet in dit React Roles-menu.",
                ephemeral=True
            )
            return

        new_name = current[0]
        new_emoji = current[1]
        current_level = int(current[2] or 1)
        current_group = (current[3] or "roles").lower()

        if section == "role":
            if min_level is not None:
                current_level = max(1, int(min_level))
            if item_group is not None:
                candidate_group = item_group.strip().lower()
                if candidate_group not in {"roles", "color"}:
                    await interaction.response.send_message(
                        f"{ERROR_EMOJI} Group moet `roles` of `color` zijn.", ephemeral=True
                    )
                    return
                current_group = candidate_group

        if buttonnaam is not None:

            new_name = buttonnaam.strip()

            if not 1 <= len(
                new_name
            ) <= 80:

                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Buttonnaam moet tussen 1 en 80 tekens zijn.",
                    ephemeral=True
                )
                return

        if emoji is not None:

            try:
                new_emoji = parse_emoji(
                    emoji,
                    current[1]
                )
            except ValueError:
                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Ongeldige emoji.",
                    ephemeral=True
                )
                return

        await self.add_or_update_item(
            interaction.guild.id,
            section,
            role.id,
            new_name,
            new_emoji,
            current_level,
            current_group
        )

        await interaction.response.send_message(
            f"{SUCCESS_EMOJI} **{new_name}** bijgewerkt.",
            ephemeral=True
        )

    async def remove_item_command(
        self,
        interaction: discord.Interaction,
        section: str,
        role: discord.Role
    ):

        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:

            cursor = await db.execute(
                """
                DELETE FROM react_items
                WHERE guild_id = ?
                AND section = ?
                AND role_id = ?
                """,
                (
                    interaction.guild.id,
                    section,
                    role.id,
                )
            )

            removed = (
                cursor.rowcount > 0
            )

            await db.commit()

        if not removed:

            await interaction.response.send_message(
                f"{ERROR_EMOJI} Die rol stond niet in dit menu.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{DELETE_EMOJI} **{clean_role_name(role)}** uit het menu verwijderd.\n"
            "└ De Discord-rol zelf blijft bestaan.",
            ephemeral=True
        )

    async def list_item_command(
        self,
        interaction: discord.Interaction,
        section: str
    ):

        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        entries = await self.get_entries(
            interaction.guild,
            section
        )

        title, emoji, _ = section_info(
            section
        )

        if not entries:

            await interaction.response.send_message(
                f"{emoji} Er staan nog geen **{title.lower()}** in het menu.",
                ephemeral=True
            )
            return

        lines = []

        for index, entry in enumerate(
            entries,
            start=1
        ):

            role = interaction.guild.get_role(
                entry["role_id"]
            )

            if role is None:
                continue

            extra = ""
            if section == "role":
                extra = f" • lvl {entry.get('min_level', 1)} • `{entry.get('group', 'roles')}`"
            lines.append(
                f"`{index:02}` {entry['emoji']} "
                f"**{entry['button_name']}** → {role.mention}{extra}"
            )

        text = "\n".join(
            lines
        )

        if len(text) > 1800:
            text = (
                text[:1750]
                + "\n…"
            )

        await interaction.response.send_message(
            f"{emoji} **{title} React Roles**\n\n{text}",
            ephemeral=True
        )


    # =====================================================
    # FAST ADMIN CONTROL CENTER
    # =====================================================

    async def ensure_manageable_role(
        self,
        guild: discord.Guild,
        role: discord.Role
    ) -> tuple[bool, str | None]:

        if role.is_default():
            return False, "@everyone kan niet gebruikt worden."

        if role.managed:
            return False, f"{role.name} wordt door Discord/integratie beheerd."

        bot_member = guild.me
        if bot_member is None or role >= bot_member.top_role:
            return False, f"Mijn botrol moet boven {role.name} staan."

        return True, None

    async def quick_add_roles(
        self,
        guild: discord.Guild,
        section: str,
        roles: list[discord.Role],
        *,
        min_level: int = 1,
        item_group: str = "roles"
    ) -> tuple[int, list[str]]:

        added = 0
        errors: list[str] = []

        _, default_emoji, _ = section_info(
            "color" if item_group == "color" else section
        )

        for role in roles[:MAX_BULK_ROLES]:
            ok, error = await self.ensure_manageable_role(guild, role)

            if not ok:
                errors.append(f"{role.name}: {error}")
                continue

            name = clean_role_name(role)

            await self.add_or_update_item(
                guild.id,
                section,
                role.id,
                name,
                default_emoji,
                min_level,
                item_group
            )
            added += 1

        return added, errors

    async def create_colour_role(
        self,
        guild: discord.Guild,
        name: str,
        colour_value: int,
        min_level: int,
        *,
        reason: str,
        emoji: str = COLOR_EMOJI,
    ) -> discord.Role:
        name = name.strip()
        if not name:
            raise ValueError("Naam mag niet leeg zijn.")

        role = await guild.create_role(
            name=formatted_colour_role_name(name),
            colour=discord.Colour(colour_value),
            hoist=False,
            mentionable=False,
            reason=reason,
        )

        divider = guild.get_role(DIVIDER_ROLE_ID)
        if divider is not None:
            try:
                await role.edit(
                    position=max(1, divider.position - 1),
                    reason="LEVENLOOS React Roles kleurpositie",
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning(
                    "Kleurrol %s kon niet onder Divider worden geplaatst in guild %s: %s",
                    role.id,
                    guild.id,
                    exc,
                )

        await self.add_or_update_item(
            guild.id,
            "role",
            role.id,
            clean_role_name(role),
            emoji,
            max(1, int(min_level)),
            "color",
        )
        return role

    async def create_gradient_role(
        self,
        guild: discord.Guild,
        name: str,
        start_hex: str,
        end_hex: str,
        min_level: int,
        actor: discord.abc.User,
        emoji: str = COLOR_EMOJI,
    ) -> discord.Role:
        if "ENHANCED_ROLE_COLORS" not in guild.features:
            raise ValueError(
                "Deze server heeft Discord Enhanced Role Styles niet ingeschakeld."
            )

        name = name.strip()
        if not name:
            raise ValueError("Naam mag niet leeg zijn.")

        start_value = normalise_hex(start_hex)
        end_value = normalise_hex(end_hex)
        role = await guild.create_role(
            name=formatted_colour_role_name(name),
            colour=discord.Colour(start_value),
            secondary_colour=discord.Colour(end_value),
            hoist=False,
            mentionable=False,
            reason=f"Gradient kleurrol aangemaakt via React Control door {actor}",
        )

        divider = guild.get_role(DIVIDER_ROLE_ID)
        if divider is not None:
            try:
                await role.edit(
                    position=max(1, divider.position - 1),
                    reason="LEVENLOOS React Roles kleurpositie",
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning(
                    "Gradientrol %s kon niet onder Divider worden geplaatst in guild %s: %s",
                    role.id,
                    guild.id,
                    exc,
                )

        await self.add_or_update_item(
            guild.id,
            "role",
            role.id,
            clean_role_name(role),
            emoji,
            max(1, int(min_level)),
            "color",
        )
        return role

    async def create_colour_batch_from_text(
        self,
        guild: discord.Guild,
        raw_text: str,
        actor: discord.abc.User,
    ) -> tuple[list[discord.Role], list[str]]:
        created: list[discord.Role] = []
        errors: list[str] = []
        source_lines = [
            line.strip()
            for line in raw_text.splitlines()
            if line.strip()
        ]

        if not source_lines:
            return [], ["Geen geldige regels gevonden."]

        if len(source_lines) > 40:
            errors.append("Alleen de eerste 40 regels zijn verwerkt.")
        source_lines = source_lines[:40]

        for index, line in enumerate(source_lines, start=1):
            try:
                parts = [part.strip() for part in line.split("|")]
                if len(parts) < 2 or len(parts) > 4:
                    raise ValueError(
                        "gebruik `Naam | #HEX > #HEX | LEVEL | EMOJI` "
                        "of `Naam | #HEX | LEVEL | EMOJI`"
                    )

                name = parts[0]
                colour_spec = parts[1]
                if not name:
                    raise ValueError("naam ontbreekt")
                if not colour_spec:
                    raise ValueError("kleur ontbreekt")

                level = DEFAULT_COLOR_LEVEL
                if len(parts) >= 3 and parts[2]:
                    level = max(1, min(999, int(parts[2])))

                chosen_emoji = parse_emoji(
                    parts[3] if len(parts) >= 4 and parts[3] else None,
                    COLOR_EMOJI,
                )

                if ">" in colour_spec:
                    start_hex, end_hex = [
                        item.strip()
                        for item in colour_spec.split(">", 1)
                    ]
                    role = await self.create_gradient_role(
                        guild,
                        name,
                        start_hex,
                        end_hex,
                        level,
                        actor,
                        chosen_emoji,
                    )
                else:
                    colour_value = normalise_hex(colour_spec)
                    role = await self.create_colour_role(
                        guild,
                        name,
                        colour_value,
                        level,
                        reason=f"Kleur aangemaakt via bulk paste door {actor}",
                        emoji=chosen_emoji,
                    )

                created.append(role)

            except ValueError as exc:
                errors.append(f"Regel {index}: {line[:70]} → {exc}")
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception(
                    "Kleur uit bulkregel %s kon niet worden aangemaakt in guild %s",
                    index,
                    guild.id,
                )
                errors.append(
                    f"Regel {index}: Discord kon deze kleurrol niet aanmaken."
                )

        return created, errors

    async def format_all_colour_roles(
        self,
        guild: discord.Guild,
        actor: discord.abc.User
    ) -> tuple[int, list[str]]:

        entries = await self.get_entries(
            guild,
            "color"
        )

        changed = 0
        errors: list[str] = []

        for entry in entries:
            role = guild.get_role(
                entry["role_id"]
            )
            if role is None:
                continue

            wanted = formatted_colour_role_name(
                clean_role_name(role)
            )

            if role.name == wanted:
                continue

            try:
                await role.edit(
                    name=wanted,
                    reason=f"Kleurrollen formatteren door {actor}"
                )
                changed += 1
            except (discord.Forbidden, discord.HTTPException) as exc:
                errors.append(
                    f"{role.name}: {type(exc).__name__}"
                )

        return changed, errors

    async def delete_react_entries(
        self,
        guild_id: int,
        section: str,
        role_ids: list[int]
    ) -> int:

        db_section = "role" if section in {"color", "roles"} else section
        item_group = section if section in {"color", "roles"} else None

        async with aiosqlite.connect(
            DATABASE_PATH
        ) as db:

            removed = 0

            for role_id in role_ids:
                if item_group is None:
                    cursor = await db.execute(
                        """
                        DELETE FROM react_items
                        WHERE guild_id = ?
                        AND section = ?
                        AND role_id = ?
                        """,
                        (guild_id, db_section, role_id)
                    )
                else:
                    cursor = await db.execute(
                        """
                        DELETE FROM react_items
                        WHERE guild_id = ?
                        AND section = ?
                        AND role_id = ?
                        AND item_group = ?
                        """,
                        (guild_id, db_section, role_id, item_group)
                    )

                removed += max(0, cursor.rowcount)

            await db.commit()

        return removed

    async def category_admin_content(
        self,
        guild: discord.Guild,
        section: str,
    ) -> str:
        entries = await self.get_entries(guild, section)
        title, emoji, description = section_info(section)

        lines = [
            f"## {emoji} {title}",
            f"> └ {description}",
            "",
            f"> └ **Ingesteld:** `{len(entries)}`",
        ]

        if section == "color":
            lines.extend(
                [
                    "",
                    "### Kleurbeheer",
                    "> └ **Gradient** maakt een echte Discord-gradientrol.",
                    "> └ **Nieuwe kleur** maakt een gewone kleurrol.",
                    "> └ **Bulk plakken** verwerkt meerdere kleuren tegelijk.",
                    "> └ **Format** herstelt de `◆ Naam`-opmaak.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "### Beheer",
                    f"> └ Je kunt maximaal **{MAX_BULK_ROLES}** Discord-rollen tegelijk toevoegen.",
                ]
            )

        preview: list[str] = []
        for entry in entries[:8]:
            role = guild.get_role(entry["role_id"])
            if role is None:
                continue
            extra = (
                f" · lvl {entry['min_level']}"
                if section in {"color", "roles"}
                else ""
            )
            preview.append(f"> └ **{entry['button_name']}**{extra}")

        if preview:
            lines.extend(["", "### Preview", *preview])

        lines.extend(["", "-# LEVENLOOS · React Roles beheer"])
        return "\n".join(lines)

    # =====================================================
    # /REACT SETUP / REFRESH
    # =====================================================


    async def open_admin_control(self, interaction: discord.Interaction):
        """Open hetzelfde React Roles-beheer vanuit slash-command én Admin Panel."""
        if interaction.guild is None:
            message = "Dit werkt alleen in een server."
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        try:
            game_entries, genre_entries, role_entries, color_entries = await asyncio.gather(
                self.get_entries(interaction.guild, "game"),
                self.get_entries(interaction.guild, "genre"),
                self.get_entries(interaction.guild, "roles"),
                self.get_entries(interaction.guild, "color"),
            )
            counts = (
                len(game_entries),
                len(genre_entries),
                len(role_entries),
                len(color_entries),
            )
            await interaction.followup.send(
                view=ReactAdminHomeView(self, interaction.user.id, counts),
                ephemeral=True,
            )
        except Exception:
            LOGGER.exception(
                "React Roles-beheer kon niet worden geopend in guild %s",
                interaction.guild.id,
            )
            await interaction.followup.send(
                f"{ERROR_EMOJI} React Roles-beheer kon niet worden geopend. Controleer de botlogs voor details.",
                ephemeral=True,
            )

    @react.command(
        name="manage",
        description="Open het snelle visuele React Roles-beheer"
    )
    async def react_manage(
        self,
        interaction: discord.Interaction
    ):

        if not await self.validate_admin(interaction):
            return

        await self.open_admin_control(interaction)

    @react.command(
        name="setup",
        description="Kies het kanaal voor het React Roles-menu"
    )
    @app_commands.describe(
        channel="Kanaal waarin het React Roles-bericht moet staan"
    )
    async def react_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):

        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        old_config = await self.get_config(
            interaction.guild.id
        )

        await interaction.response.defer(
            ephemeral=True
        )

        # Verwijder oud hoofdmenu als het naar een ander kanaal verhuist.
        if old_config:
            old_channel_id, old_message_id = old_config

            if (
                old_message_id
                and
                old_channel_id != channel.id
            ):

                old_channel = interaction.guild.get_channel(
                    old_channel_id
                )

                if isinstance(
                    old_channel,
                    discord.TextChannel
                ):

                    try:
                        old_message = await old_channel.fetch_message(
                            old_message_id
                        )
                        await old_message.delete()
                    except discord.HTTPException:
                        pass

        await self.set_config(
            interaction.guild.id,
            channel.id,
            None
        )

        message = await self.refresh_main_message(
            interaction.guild
        )

        await interaction.followup.send(
            f"{SUCCESS_EMOJI} React Roles staat nu in {channel.mention}.\n"
            f"└ Hoofdmenu: {message.jump_url}\n"
            "└ Beheercommands werken vanuit ieder kanaal.",
            ephemeral=True
        )

    @react.command(
        name="refresh",
        description="Herstel of vernieuw het openbare React Roles-menu"
    )
    async def react_refresh(
        self,
        interaction: discord.Interaction
    ):

        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        await interaction.response.defer(
            ephemeral=True
        )

        message = await self.refresh_main_message(
            interaction.guild
        )

        await interaction.followup.send(
            f"{REFRESH_EMOJI} React Roles-menu vernieuwd.\n"
            f"└ {message.jump_url}",
            ephemeral=True
        )

    @react.command(
        name="divider",
        description="Geef de Divider-rol aan iedereen op de server"
    )
    async def react_divider(
        self,
        interaction: discord.Interaction
    ):

        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        role = interaction.guild.get_role(
            DIVIDER_ROLE_ID
        )

        if role is None:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Divider-rol `{DIVIDER_ROLE_ID}` niet gevonden.",
                ephemeral=True
            )
            return

        bot_member = interaction.guild.me

        if (
            bot_member is None
            or role >= bot_member.top_role
        ):
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Mijn botrol moet boven de Divider-rol staan.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        added = 0
        already_had = 0
        failed = 0

        for member in interaction.guild.members:
            if role in member.roles:
                already_had += 1
                continue

            try:
                await member.add_roles(
                    role,
                    reason=f"Divider toegewezen via /react divider door {interaction.user}"
                )
                added += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        await interaction.followup.send(
            f"{SUCCESS_EMOJI} **Divider uitgedeeld.**\n"
            f"└ Toegevoegd: **{added}**\n"
            f"└ Had hem al: **{already_had}**\n"
            f"└ Mislukt: **{failed}**",
            ephemeral=True
        )

    # =====================================================
    # /REACT GAME
    # =====================================================

    @game.command(
        name="emoji",
        description="Geef een automatisch toegevoegde game later een eigen emoji",
    )
    @app_commands.describe(
        game="Game uit React Roles",
        emoji="Unicode emoji of custom Discord-emoji",
    )
    async def game_emoji(
        self,
        interaction: discord.Interaction,
        game: str,
        emoji: str,
    ):
        if not await self.validate_admin(
            interaction
        ):
            return

        assert interaction.guild is not None

        entry = await self.find_game_entry_by_name(
            interaction.guild,
            game,
        )

        if entry is None:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Ik kan die game niet vinden in **React Roles → Games**.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(
            int(entry["role_id"])
        )

        if role is None:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} De Discord-rol van deze game bestaat niet meer.",
                ephemeral=True,
            )
            return

        try:
            chosen_emoji = parse_emoji(
                emoji,
                str(entry.get("emoji") or GAMES_EMOJI),
            )
        except ValueError:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Ongeldige emoji. Gebruik bijvoorbeeld `🎮` "
                "of `<:naam:123456789>`.",
                ephemeral=True,
            )
            return

        await self.add_or_update_item(
            interaction.guild.id,
            "game",
            role.id,
            str(entry["button_name"])[:80],
            chosen_emoji,
            1,
            "roles",
        )

        await interaction.response.send_message(
            f"{SUCCESS_EMOJI} Emoji van **{entry['button_name']}** aangepast naar "
            f"{chosen_emoji}.",
            ephemeral=True,
        )

    @game_emoji.autocomplete("game")
    async def game_emoji_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ):
        if interaction.guild is None:
            return []

        entries = await self.get_entries(
            interaction.guild,
            "game",
        )

        current_fold = current.strip().casefold()
        results = []

        for entry in entries:
            name = str(entry["button_name"]).strip()
            if (
                not current_fold
                or current_fold in name.casefold()
            ):
                results.append(
                    app_commands.Choice(
                        name=name[:100],
                        value=name[:100],
                    )
                )

            if len(results) >= 25:
                break

        return results

    # =====================================================
    # /REACT GENRE
    # =====================================================

    @genre.command(
        name="add",
        description="Voeg een genre-rol toe"
    )
    async def genre_add(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        buttonnaam: str,
        emoji: str | None = None
    ):
        await self.add_item_command(
            interaction,
            "genre",
            role,
            buttonnaam,
            emoji
        )

    @genre.command(
        name="edit",
        description="Pas een genre-rol aan"
    )
    async def genre_edit(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        buttonnaam: str | None = None,
        emoji: str | None = None
    ):
        await self.edit_item_command(
            interaction,
            "genre",
            role,
            buttonnaam,
            emoji
        )

    @genre.command(
        name="remove",
        description="Verwijder een genre-rol uit het menu"
    )
    async def genre_remove(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):
        await self.remove_item_command(
            interaction,
            "genre",
            role
        )

    @genre.command(
        name="list",
        description="Bekijk alle genre-rollen"
    )
    async def genre_list(
        self,
        interaction: discord.Interaction
    ):
        await self.list_item_command(
            interaction,
            "genre"
        )

    # =====================================================
    # /REACT ROLE
    # =====================================================

    @role_group.command(
        name="add",
        description="Voeg een algemene rol toe"
    )
    async def role_add(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        buttonnaam: str,
        emoji: str | None = None,
        level: app_commands.Range[int, 1, 999] = 1,
        group: str = "roles"
    ):
        await self.add_item_command(
            interaction,
            "role",
            role,
            buttonnaam,
            emoji,
            int(level),
            group
        )

    @role_group.command(
        name="edit",
        description="Pas een algemene rol aan"
    )
    async def role_edit(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        buttonnaam: str | None = None,
        emoji: str | None = None,
        level: app_commands.Range[int, 1, 999] | None = None,
        group: str | None = None
    ):
        await self.edit_item_command(
            interaction,
            "role",
            role,
            buttonnaam,
            emoji,
            int(level) if level is not None else None,
            group
        )

    @role_group.command(
        name="remove",
        description="Verwijder een algemene rol uit het menu"
    )
    async def role_remove(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):
        await self.remove_item_command(
            interaction,
            "role",
            role
        )

    @role_group.command(
        name="list",
        description="Bekijk alle algemene rollen"
    )
    async def role_list(
        self,
        interaction: discord.Interaction
    ):
        await self.list_item_command(
            interaction,
            "role"
        )

    # =====================================================
    # COMPONENT INTERACTIONS
    # =====================================================

    @commands.Cog.listener()
    async def on_interaction(
        self,
        interaction: discord.Interaction
    ):

        if (
            interaction.type
            is not discord.InteractionType.component
        ):
            return

        data = interaction.data

        if not isinstance(
            data,
            dict
        ):
            return

        custom_id = str(
            data.get(
                "custom_id",
                ""
            )
        )

        # ---------------------------------------------
        # Open Games / Genres / Roles
        # ---------------------------------------------

        if custom_id.startswith(
            "react_open:"
        ):

            section = custom_id.split(
                ":",
                1
            )[1]

            if section not in {
                "game",
                "genre",
                "role",
            }:
                return

            if section == "role":
                await self.send_role_hub(interaction)
            else:
                await self.send_selector(interaction, section, 0)

            return

        # ---------------------------------------------
        # Open Roles -> Kleuren / Rollen
        # ---------------------------------------------

        if custom_id.startswith("react_subopen:"):
            section = custom_id.split(":", 1)[1]
            if section not in {"color", "roles"}:
                return
            await self.send_selector(interaction, section, 0)
            return

        # ---------------------------------------------
        # Pagination
        # ---------------------------------------------

        if custom_id.startswith(
            "react_page:"
        ):

            try:
                _, section, page = custom_id.split(
                    ":",
                    2
                )

                page = int(
                    page
                )

            except (
                ValueError,
                IndexError
            ):
                return

            if section not in {
                "game",
                "genre",
                "role",
                "color",
                "roles",
            }:
                return

            await self.edit_selector(
                interaction,
                section,
                page
            )

            return

        # ---------------------------------------------
        # Toggle role
        # ---------------------------------------------

        if custom_id.startswith(
            "react_toggle:"
        ):

            try:
                _, section, role_id, page = custom_id.split(
                    ":",
                    3
                )

                role_id = int(
                    role_id
                )

                page = int(
                    page
                )

            except (
                ValueError,
                IndexError
            ):
                return

            if section not in {
                "game",
                "genre",
                "role",
                "color",
                "roles",
            }:
                return

            if interaction.guild is None:
                return

            member = interaction.user

            if not isinstance(
                member,
                discord.Member
            ):
                return

            # Virtuele "Geen kleur"-knop.
            if section == "color" and role_id == 0:
                color_entries = await self.get_entries(interaction.guild, "color")
                removable = []
                for entry in color_entries:
                    color_role = interaction.guild.get_role(entry["role_id"])
                    if color_role is not None and color_role in member.roles:
                        removable.append(color_role)
                if removable:
                    try:
                        await member.remove_roles(*removable, reason="React Roles - Geen kleur")
                    except (discord.Forbidden, discord.HTTPException):
                        await interaction.response.send_message(
                            f"{ERROR_EMOJI} Ik kon je huidige kleur niet verwijderen.", ephemeral=True
                        )
                        return
                await self.edit_selector(interaction, section, page)
                return

            role = interaction.guild.get_role(role_id)
            if role is None:
                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Deze rol bestaat niet meer.", ephemeral=True
                )
                return

            # Lees de ingestelde level/group rechtstreeks uit het menu-item.
            db_section = "role" if section in {"color", "roles"} else section
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cur = await db.execute(
                    "SELECT min_level,item_group,button_name FROM react_items "
                    "WHERE guild_id=? AND section=? AND role_id=?",
                    (interaction.guild.id, db_section, role_id)
                )
                item = await cur.fetchone()
            if item is None:
                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Deze optie staat niet meer in React Roles.", ephemeral=True
                )
                return

            min_level, item_group, button_name = int(item[0] or 1), (item[1] or "roles").lower(), item[2]
            is_admin_color = str(button_name).strip().lower() == "admin kleur"

            if is_admin_color:
                admin_access_role = interaction.guild.get_role(ADMIN_ACCESS_ROLE_ID)
                if admin_access_role is None or admin_access_role not in member.roles:
                    await interaction.response.send_message(
                        f"{ERROR_EMOJI} Admin Kleur is alleen beschikbaar voor admins.", ephemeral=True
                    )
                    return
            elif section in {"color", "roles"}:
                member_level = await self.get_member_level(member)
                if member_level < min_level:
                    await interaction.response.send_message(
                        f"{LOCK_EMOJI} Hiervoor heb je **level {min_level}** nodig. Je bent nu level **{member_level}**.",
                        ephemeral=True
                    )
                    return

            bot_member = interaction.guild.me

            if (
                bot_member is None
                or
                role >= bot_member.top_role
            ):

                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Ik kan deze rol momenteel niet beheren.",
                    ephemeral=True
                )

                return

            try:

                if role in member.roles:

                    await member.remove_roles(
                        role,
                        reason="React Roles"
                    )

                else:
                    # Alle color-items, inclusief Admin Kleur, zijn exclusief.
                    if section == "color" or item_group == "color":
                        color_entries = await self.get_entries(interaction.guild, "color")
                        old_colors = []
                        for entry in color_entries:
                            other = interaction.guild.get_role(entry["role_id"])
                            if other is not None and other != role and other in member.roles:
                                old_colors.append(other)
                        if old_colors:
                            await member.remove_roles(*old_colors, reason="React Roles - kleur wisselen")

                    await member.add_roles(role, reason="React Roles")

            except discord.Forbidden:

                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Ik heb geen toestemming om deze rol te beheren.",
                    ephemeral=True
                )

                return

            except discord.HTTPException:
                LOGGER.exception(
                    "Discord kon React Role %s niet aanpassen voor member %s in guild %s",
                    role.id,
                    member.id,
                    interaction.guild.id,
                )
                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Discord kon deze rol niet aanpassen. Probeer het opnieuw of meld het bij een beheerder.",
                    ephemeral=True,
                )
                return

            # Update direct dezelfde ephemeral pagina.
            await self.edit_selector(
                interaction,
                section,
                page
            )



# =========================================================
# ADMIN UI
# =========================================================

class AdminOwnedView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int,
        *,
        timeout: float = ADMIN_VIEW_TIMEOUT,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                f"{INFO_EMOJI} Dit beheer-menu hoort bij iemand anders.",
                ephemeral=True,
            )
            return False

        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Je hebt geen toegang tot React Roles-beheer.",
                ephemeral=True,
            )
            return False

        return True


class ReactAdminHomeView(AdminOwnedView):
    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int,
        counts: tuple[int, int, int, int],
    ):
        super().__init__(cog, owner_id)
        game_count, genre_count, role_count, color_count = counts

        container = make_text_container(
            "# React Roles beheer\n"
            "> └ Beheer de openbare rolkeuze vanuit één overzicht.\n\n"
            "### Overzicht\n"
            f"> └ **Games:** `{game_count}`\n"
            f"> └ **Genres:** `{genre_count}`\n"
            f"> └ **Rollen:** `{role_count}`\n"
            f"> └ **Kleuren:** `{color_count}`\n\n"
            "-# Wijzigingen aan het openbare menu worden direct uit de database gelezen."
        )

        games = discord.ui.Button(
            label="Games",
            emoji=partial_emoji_or_none(GAMES_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id="react_admin:game",
        )
        genres = discord.ui.Button(
            label="Genres",
            emoji=partial_emoji_or_none(GENRES_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id="react_admin:genre",
        )
        roles = discord.ui.Button(
            label="Rollen",
            emoji=partial_emoji_or_none(ROLES_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id="react_admin:roles",
        )
        colours = discord.ui.Button(
            label="Kleuren",
            emoji=partial_emoji_or_none(COLOR_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id="react_admin:color",
        )
        refresh = discord.ui.Button(
            label="Openbaar menu vernieuwen",
            emoji=partial_emoji_or_none(REFRESH_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id="react_admin:refresh_public",
        )

        games.callback = self.games
        genres.callback = self.genres
        roles.callback = self.roles
        colours.callback = self.colours
        refresh.callback = self.refresh_public

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(games, genres, roles, colours))
        container.add_item(discord.ui.ActionRow(refresh))
        self.add_item(container)

    async def games(self, interaction: discord.Interaction):
        await open_category_control(interaction, self.cog, self.owner_id, "game")

    async def genres(self, interaction: discord.Interaction):
        await open_category_control(interaction, self.cog, self.owner_id, "genre")

    async def roles(self, interaction: discord.Interaction):
        await open_category_control(interaction, self.cog, self.owner_id, "roles")

    async def colours(self, interaction: discord.Interaction):
        await open_category_control(interaction, self.cog, self.owner_id, "color")

    async def refresh_public(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        await interaction.response.defer()

        try:
            message = await self.cog.refresh_main_message(interaction.guild)
            counts = await get_react_counts(self.cog, interaction.guild)
            view = ReactAdminHomeView(self.cog, self.owner_id, counts)
            view.children[0].add_item(
                discord.ui.TextDisplay(
                    f"-# {REFRESH_EMOJI} Openbaar React Roles-menu vernieuwd: {message.jump_url}"
                )
            )
            await interaction.edit_original_response(view=view)
        except Exception:
            LOGGER.exception(
                "Openbaar React Roles-menu vernieuwen mislukt in guild %s",
                interaction.guild.id,
            )
            await interaction.followup.send(
                f"{ERROR_EMOJI} Het openbare React Roles-menu kon niet worden vernieuwd. Controleer de botlogs.",
                ephemeral=True,
            )


async def get_react_counts(
    cog: ReactRoles,
    guild: discord.Guild,
) -> tuple[int, int, int, int]:
    game_entries, genre_entries, role_entries, color_entries = await asyncio.gather(
        cog.get_entries(guild, "game"),
        cog.get_entries(guild, "genre"),
        cog.get_entries(guild, "roles"),
        cog.get_entries(guild, "color"),
    )
    return (
        len(game_entries),
        len(genre_entries),
        len(role_entries),
        len(color_entries),
    )


async def open_category_control(
    interaction: discord.Interaction,
    cog: ReactRoles,
    owner_id: int,
    section: str,
):
    assert interaction.guild is not None
    content = await cog.category_admin_content(interaction.guild, section)
    await interaction.response.edit_message(
        view=CategoryAdminView(cog, owner_id, section, content)
    )


class CategoryAdminView(AdminOwnedView):
    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int,
        section: str,
        content: str,
    ):
        super().__init__(cog, owner_id)
        self.section = section

        container = make_text_container(content)
        container.add_item(discord.ui.Separator())

        if section == "color":
            gradient = GradientButton(cog, owner_id)
            new_colour = NewColourButton(cog, owner_id)
            paste = BulkColourPasteButton(cog, owner_id)
            format_roles = FormatColourRolesButton(cog, owner_id)
            container.add_item(
                discord.ui.ActionRow(
                    gradient,
                    new_colour,
                    paste,
                    format_roles,
                )
            )

        bulk_add = discord.ui.Button(
            label="Bulk toevoegen",
            emoji=partial_emoji_or_none(ADD_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id=f"react_admin:bulk:{section}",
        )
        edit_items = discord.ui.Button(
            label="Bewerken",
            emoji=partial_emoji_or_none(EDIT_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id=f"react_admin:edit:{section}",
        )
        remove_items = discord.ui.Button(
            label="Verwijderen",
            emoji=partial_emoji_or_none(DELETE_EMOJI),
            style=discord.ButtonStyle.danger,
            custom_id=f"react_admin:remove:{section}",
        )
        refresh = discord.ui.Button(
            label="Vernieuwen",
            emoji=partial_emoji_or_none(REFRESH_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id=f"react_admin:refresh:{section}",
        )
        back = discord.ui.Button(
            label="Terug",
            emoji=partial_emoji_or_none(BACK_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id=f"react_admin:back:{section}",
        )

        bulk_add.callback = self.bulk_add
        edit_items.callback = self.edit_items
        remove_items.callback = self.remove_items
        refresh.callback = self.refresh
        back.callback = self.back

        container.add_item(discord.ui.ActionRow(bulk_add, edit_items, remove_items))
        container.add_item(discord.ui.ActionRow(refresh, back))
        self.add_item(container)

    async def bulk_add(self, interaction: discord.Interaction):
        description = (
            f"## Bulk toevoegen\n"
            f"> └ Selecteer maximaal **{MAX_BULK_ROLES}** Discord-rollen.\n"
            "> └ Naam en standaardemoji worden automatisch ingevuld."
        )
        if self.section == "color":
            description += (
                "\n> └ Voor nieuwe kleurrollen zijn Gradient, Nieuwe kleur of Bulk plakken meestal sneller."
            )

        await interaction.response.edit_message(
            view=BulkRolePickerView(
                self.cog,
                self.owner_id,
                self.section,
                description,
            )
        )

    async def edit_items(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        entries = await self.cog.get_entries(interaction.guild, self.section)
        if not entries:
            await interaction.response.send_message(
                f"{INFO_EMOJI} Er zijn nog geen items om te bewerken.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            view=await build_configured_picker_view(
                self.cog,
                self.owner_id,
                self.section,
                "edit",
                interaction.guild,
            )
        )

    async def remove_items(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        entries = await self.cog.get_entries(interaction.guild, self.section)
        if not entries:
            await interaction.response.send_message(
                f"{INFO_EMOJI} Er zijn nog geen items om te verwijderen.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            view=await build_configured_picker_view(
                self.cog,
                self.owner_id,
                self.section,
                "remove",
                interaction.guild,
            )
        )

    async def refresh(self, interaction: discord.Interaction):
        await open_category_control(
            interaction,
            self.cog,
            self.owner_id,
            self.section,
        )

    async def back(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        counts = await get_react_counts(self.cog, interaction.guild)
        await interaction.response.edit_message(
            view=ReactAdminHomeView(self.cog, self.owner_id, counts)
        )


class GradientButton(discord.ui.Button):
    def __init__(self, cog: ReactRoles, owner_id: int):
        super().__init__(
            label="Gradient",
            emoji=partial_emoji_or_none(GRADIENT_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id="react_admin:gradient",
        )
        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GradientModal(self.cog, self.owner_id))


class NewColourButton(discord.ui.Button):
    def __init__(self, cog: ReactRoles, owner_id: int):
        super().__init__(
            label="Nieuwe kleur",
            emoji=partial_emoji_or_none(COLOR_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id="react_admin:new_colour",
        )
        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SingleColourModal(self.cog, self.owner_id))


class BulkColourPasteButton(discord.ui.Button):
    def __init__(self, cog: ReactRoles, owner_id: int):
        super().__init__(
            label="Bulk plakken",
            emoji=partial_emoji_or_none(PASTE_EMOJI),
            style=discord.ButtonStyle.primary,
            custom_id="react_admin:bulk_colours",
        )
        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BulkColourPasteModal(self.cog, self.owner_id))


class FormatColourRolesButton(discord.ui.Button):
    def __init__(self, cog: ReactRoles, owner_id: int):
        super().__init__(
            label="Format",
            emoji=partial_emoji_or_none(FORMAT_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id="react_admin:format_colours",
        )
        self.cog = cog
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        await interaction.response.defer()
        changed, errors = await self.cog.format_all_colour_roles(
            interaction.guild,
            interaction.user,
        )
        content = await self.cog.category_admin_content(interaction.guild, "color")
        content += f"\n\n> └ {SUCCESS_EMOJI} **{changed}** kleurrollen geformatteerd naar `◆ Naam`."
        if errors:
            content += "\n> └ Niet alles kon worden aangepast; details staan in de botlogs."
            LOGGER.warning(
                "Format kleurrollen had %s fout(en) in guild %s: %s",
                len(errors),
                interaction.guild.id,
                errors[:10],
            )
        await interaction.edit_original_response(
            view=CategoryAdminView(self.cog, self.owner_id, "color", content)
        )


class BulkRolePicker(discord.ui.RoleSelect):
    def __init__(self, parent_view: "BulkRolePickerView"):
        super().__init__(
            placeholder=f"Selecteer maximaal {MAX_BULK_ROLES} rollen",
            min_values=1,
            max_values=MAX_BULK_ROLES,
            custom_id=f"react_admin:bulk_select:{parent_view.section}",
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        section = self.parent_view.section
        db_section = "role" if section in {"color", "roles"} else section
        item_group = section if section in {"color", "roles"} else "roles"
        min_level = DEFAULT_COLOR_LEVEL if section == "color" else 1
        roles = [value for value in self.values if isinstance(value, discord.Role)]

        added, errors = await self.parent_view.cog.quick_add_roles(
            interaction.guild,
            db_section,
            roles,
            min_level=min_level,
            item_group=item_group,
        )

        content = await self.parent_view.cog.category_admin_content(
            interaction.guild,
            section,
        )
        content += f"\n\n> └ {SUCCESS_EMOJI} **{added}** rol(len) toegevoegd aan React Roles."
        if section == "color":
            content += f"\n> └ Nieuwe imports krijgen standaard level {DEFAULT_COLOR_LEVEL}."
        if errors:
            content += f"\n> └ {len(errors)} rol(len) zijn overgeslagen; details staan in de botlogs."
            LOGGER.warning(
                "Bulk React Roles had %s fout(en) in guild %s: %s",
                len(errors),
                interaction.guild.id,
                errors[:10],
            )

        await interaction.response.edit_message(
            view=CategoryAdminView(
                self.parent_view.cog,
                self.parent_view.owner_id,
                section,
                content,
            )
        )


class BulkRolePickerView(AdminOwnedView):
    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int,
        section: str,
        content: str,
    ):
        super().__init__(cog, owner_id)
        self.section = section

        container = make_text_container(content)
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(BulkRolePicker(self)))

        back = discord.ui.Button(
            label="Terug",
            emoji=partial_emoji_or_none(BACK_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id=f"react_admin:bulk_back:{section}",
        )
        back.callback = self.back
        container.add_item(discord.ui.ActionRow(back))
        self.add_item(container)

    async def back(self, interaction: discord.Interaction):
        await open_category_control(
            interaction,
            self.cog,
            self.owner_id,
            self.section,
        )


class ConfiguredItemSelect(discord.ui.Select):
    def __init__(
        self,
        parent_view: "ConfiguredItemPickerView",
        options: list[discord.SelectOption],
        max_values: int,
    ):
        super().__init__(
            placeholder=(
                "Kies één item"
                if max_values == 1
                else "Kies één of meer items"
            ),
            min_values=1,
            max_values=max_values,
            options=options,
            custom_id=f"react_admin:configured:{parent_view.mode}:{parent_view.section}",
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        role_ids = [int(value) for value in self.values]

        if self.parent_view.mode == "remove":
            removed = await self.parent_view.cog.delete_react_entries(
                interaction.guild.id,
                self.parent_view.section,
                role_ids,
            )
            content = await self.parent_view.cog.category_admin_content(
                interaction.guild,
                self.parent_view.section,
            )
            content += (
                f"\n\n> └ {DELETE_EMOJI} **{removed}** item(s) uit React Roles verwijderd.\n"
                "> └ De Discord-rollen zelf zijn behouden."
            )
            await interaction.response.edit_message(
                view=CategoryAdminView(
                    self.parent_view.cog,
                    self.parent_view.owner_id,
                    self.parent_view.section,
                    content,
                )
            )
            return

        role_id = role_ids[0]
        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Die Discord-rol bestaat niet meer.",
                ephemeral=True,
            )
            return

        db_section = (
            "role"
            if self.parent_view.section in {"color", "roles"}
            else self.parent_view.section
        )
        current = await self.parent_view.cog.get_entry(
            interaction.guild.id,
            db_section,
            role.id,
        )
        if current is None:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Dit item bestaat niet meer in React Roles.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            EditReactItemModal(
                self.parent_view.cog,
                self.parent_view.owner_id,
                self.parent_view.section,
                role,
                current,
            )
        )


class ConfiguredItemPickerView(AdminOwnedView):
    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int,
        section: str,
        mode: str,
    ):
        super().__init__(cog, owner_id)
        self.section = section
        self.mode = mode
        self._built = False

    async def build(self, guild: discord.Guild):
        if self._built:
            return

        entries = await self.cog.get_entries(guild, self.section)
        options: list[discord.SelectOption] = []
        for entry in entries[:25]:
            role = guild.get_role(entry["role_id"])
            if role is None:
                continue

            options.append(
                discord.SelectOption(
                    label=entry["button_name"][:100],
                    value=str(entry["role_id"]),
                    description=(
                        f"Level {entry['min_level']} · {role.name}"
                        if self.section in {"color", "roles"}
                        else role.name
                    )[:100],
                    emoji=partial_emoji_or_none(entry.get("emoji"), guild),
                )
            )

        title = "Item bewerken" if self.mode == "edit" else "Items verwijderen"
        description = (
            "Kies hieronder welk item je wilt aanpassen."
            if self.mode == "edit"
            else "Selecteer maximaal 10 items. Alleen de React Roles-koppeling wordt verwijderd."
        )
        container = make_text_container(f"## {title}\n> └ {description}")

        if options:
            container.add_item(discord.ui.Separator())
            container.add_item(
                discord.ui.ActionRow(
                    ConfiguredItemSelect(
                        self,
                        options,
                        1 if self.mode == "edit" else min(10, len(options)),
                    )
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay("> └ Er zijn geen geldige items beschikbaar."))

        back = discord.ui.Button(
            label="Terug",
            emoji=partial_emoji_or_none(BACK_EMOJI),
            style=discord.ButtonStyle.secondary,
            custom_id=f"react_admin:configured_back:{self.mode}:{self.section}",
        )
        back.callback = self.back
        container.add_item(discord.ui.ActionRow(back))
        self.add_item(container)
        self._built = True

    async def back(self, interaction: discord.Interaction):
        await open_category_control(
            interaction,
            self.cog,
            self.owner_id,
            self.section,
        )
class EditReactItemModal(discord.ui.Modal):

    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int,
        section: str,
        role: discord.Role,
        current
    ):
        super().__init__(
            title=f"Bewerk {clean_role_name(role)[:30]}"
        )

        self.cog = cog
        self.owner_id = owner_id
        self.section = section
        self.role = role

        self.name_input = discord.ui.TextInput(
            label="Buttonnaam",
            default=str(current[0])[:80],
            max_length=80,
            required=True
        )
        self.emoji_input = discord.ui.TextInput(
            label="Emoji",
            default=str(current[1])[:100],
            max_length=100,
            required=True
        )

        self.add_item(self.name_input)
        self.add_item(self.emoji_input)

        if section in {"color", "roles"}:
            self.level_input = discord.ui.TextInput(
                label="Minimum level",
                default=str(int(current[2] or 1)),
                max_length=3,
                required=True
            )
            self.add_item(self.level_input)
        else:
            self.level_input = None

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        if (
            interaction.user.id != self.owner_id
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Geen toegang.",
                ephemeral=True
            )
            return

        name = self.name_input.value.strip()
        emoji = self.emoji_input.value.strip()

        if not name:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Buttonnaam mag niet leeg zijn.",
                ephemeral=True
            )
            return

        try:
            chosen_emoji = parse_emoji(
                emoji,
                COLOR_EMOJI if self.section == "color" else ROLES_EMOJI
            )
        except ValueError:
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Ongeldige emoji.",
                ephemeral=True
            )
            return

        level = 1
        if self.level_input is not None:
            try:
                level = max(
                    1,
                    min(999, int(self.level_input.value.strip()))
                )
            except ValueError:
                await interaction.response.send_message(
                    f"{ERROR_EMOJI} Level moet een getal zijn.",
                    ephemeral=True
                )
                return

        db_section = (
            "role"
            if self.section in {"color", "roles"}
            else self.section
        )

        group = (
            self.section
            if self.section in {"color", "roles"}
            else "roles"
        )

        await self.cog.add_or_update_item(
            interaction.guild.id,
            db_section,
            self.role.id,
            name,
            chosen_emoji,
            level,
            group
        )

        await interaction.response.send_message(
            f"{SUCCESS_EMOJI} **{name}** bijgewerkt.",
            ephemeral=True
        )


class SingleColourModal(discord.ui.Modal):

    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int
    ):
        super().__init__(
            title="Nieuwe kleurrol"
        )

        self.cog = cog
        self.owner_id = owner_id

        self.name_input = discord.ui.TextInput(
            label="Naam",
            placeholder="Bijv. Royal Purple",
            max_length=90
        )
        self.hex_input = discord.ui.TextInput(
            label="HEX-kleur",
            placeholder="#A93BD6",
            max_length=7
        )
        self.level_input = discord.ui.TextInput(
            label="Minimum level",
            default=str(DEFAULT_COLOR_LEVEL),
            max_length=3
        )

        self.add_item(self.name_input)
        self.add_item(self.hex_input)
        self.add_item(self.level_input)

    async def on_submit(self, interaction: discord.Interaction):
        if (
            interaction.user.id != self.owner_id
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Je hebt geen toegang tot dit beheerformulier.",
                ephemeral=True,
            )
            return

        try:
            colour_value = normalise_hex(self.hex_input.value)
            min_level = max(1, min(999, int(self.level_input.value.strip())))
        except ValueError as exc:
            await interaction.response.send_message(f"{ERROR_EMOJI} {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            role = await self.cog.create_colour_role(
                interaction.guild,
                self.name_input.value,
                colour_value,
                min_level,
                reason=f"Kleur aangemaakt door {interaction.user}",
            )
        except ValueError as exc:
            await interaction.followup.send(f"{ERROR_EMOJI} {exc}", ephemeral=True)
            return
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception(
                "Kleurrol aanmaken mislukt in guild %s",
                interaction.guild.id,
            )
            await interaction.followup.send(
                f"{ERROR_EMOJI} De kleurrol kon niet worden aangemaakt. Controleer de rolrechten en botlogs.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"{SUCCESS_EMOJI} **Kleur aangemaakt en toegevoegd aan React Roles.**\n"
            f"Rol: {role.mention}\n"
            f"Kleur: `{hex_string(colour_value)}`\n"
            f"Vrij vanaf level **{min_level}**",
            ephemeral=True,
        )


class GradientModal(discord.ui.Modal):

    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int
    ):
        super().__init__(
            title="Nieuwe gradient kleurrol"
        )

        self.cog = cog
        self.owner_id = owner_id

        self.name_input = discord.ui.TextInput(
            label="Naam",
            placeholder="Bijv. Kosmisch",
            max_length=90
        )
        self.start_input = discord.ui.TextInput(
            label="Kleur links",
            placeholder="#FF2E93",
            max_length=7
        )
        self.end_input = discord.ui.TextInput(
            label="Kleur rechts",
            placeholder="#00D9FF",
            max_length=7
        )
        self.level_input = discord.ui.TextInput(
            label="Minimum level",
            default=str(DEFAULT_COLOR_LEVEL),
            max_length=3
        )

        self.add_item(self.name_input)
        self.add_item(self.start_input)
        self.add_item(self.end_input)
        self.add_item(self.level_input)

    async def on_submit(self, interaction: discord.Interaction):
        if (
            interaction.user.id != self.owner_id
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Je hebt geen toegang tot dit beheerformulier.",
                ephemeral=True,
            )
            return

        try:
            normalise_hex(self.start_input.value)
            normalise_hex(self.end_input.value)
            min_level = max(1, min(999, int(self.level_input.value.strip())))
        except ValueError as exc:
            await interaction.response.send_message(f"{ERROR_EMOJI} {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            role = await self.cog.create_gradient_role(
                interaction.guild,
                self.name_input.value,
                self.start_input.value,
                self.end_input.value,
                min_level,
                interaction.user,
            )
        except ValueError as exc:
            await interaction.followup.send(f"{ERROR_EMOJI} {exc}", ephemeral=True)
            return
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception(
                "Gradientrol aanmaken mislukt in guild %s",
                interaction.guild.id,
            )
            await interaction.followup.send(
                f"{ERROR_EMOJI} De gradientrol kon niet worden aangemaakt. Controleer de rolrechten en botlogs.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"{SUCCESS_EMOJI} **Gradientkleur aangemaakt en toegevoegd aan React Roles.**\n"
            f"Rol: {role.mention}\n"
            f"Gradient: `{self.start_input.value.upper()}` → `{self.end_input.value.upper()}`\n"
            f"Vrij vanaf level **{min_level}**",
            ephemeral=True,
        )


class BulkColourPasteModal(discord.ui.Modal):

    def __init__(
        self,
        cog: ReactRoles,
        owner_id: int
    ):
        super().__init__(
            title="Kleuren bulk plakken"
        )

        self.cog = cog
        self.owner_id = owner_id

        self.colours_input = discord.ui.TextInput(
            label="Plak je volledige kleurenlijst",
            style=discord.TextStyle.paragraph,
            placeholder=(
                "Roze | #FF4FA3 | 25 | 🎨\n"
                "Kosmisch | #FF2E93 > #00D9FF | 100 | 🌌\n"
                "Emerald | #2ECC71 | 50 | 💚"
            ),
            max_length=4000,
            required=True
        )

        self.add_item(self.colours_input)

    async def on_submit(self, interaction: discord.Interaction):
        if (
            interaction.user.id != self.owner_id
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await interaction.response.send_message(
                f"{ERROR_EMOJI} Je hebt geen toegang tot dit beheerformulier.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        created, errors = await self.cog.create_colour_batch_from_text(
            interaction.guild,
            self.colours_input.value,
            interaction.user,
        )

        result_lines = [
            f"## {SUCCESS_EMOJI} Bulk kleuren verwerkt",
            f"**Aangemaakt:** `{len(created)}`",
        ]

        if created:
            result_lines.extend(["", "### Nieuwe rollen"])
            result_lines.extend(f"- {role.mention}" for role in created[:20])
            if len(created) > 20:
                result_lines.append(f"-# En nog {len(created) - 20} extra rollen.")

        if errors:
            result_lines.extend(["", f"### {WARNING_EMOJI} Overgeslagen ({len(errors)})"])
            result_lines.extend(f"- {error[:180]}" for error in errors[:10])
            if len(errors) > 10:
                result_lines.append(f"-# En nog {len(errors) - 10} meldingen.")

        await interaction.followup.send(
            "\n".join(result_lines),
            ephemeral=True,
        )


# Patch the configured item picker after creation, because entries are async.
async def build_configured_picker_view(
    cog: ReactRoles,
    owner_id: int,
    section: str,
    mode: str,
    guild: discord.Guild
) -> ConfiguredItemPickerView:
    view = ConfiguredItemPickerView(
        cog,
        owner_id,
        section,
        mode
    )
    await view.build(guild)
    return view


# =========================================================
# SETUP
# =========================================================

async def setup(
    bot: commands.Bot
):

    await bot.add_cog(
        ReactRoles(bot)
    )
