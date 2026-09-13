import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


# =========================================================
# CONFIG
# =========================================================

ACTION_LOG_CHANNEL_ID = 1546623495952269342
PURPLE = discord.Color.from_rgb(108, 39, 218)

AUDIT_DELAY = 1.0
AUDIT_WINDOW_SECONDS = 12
MESSAGE_CACHE_LIMIT = 5000

logger = logging.getLogger(__name__)


# =========================================================
# LEVENLOOS CUSTOM EMOJIS
# =========================================================

SUCCESS_EMOJI = "<:success:1547724072090079313>"
ERROR_EMOJI = "<:error:1547724070252974131>"
WARNING_EMOJI = "<:warning:1547724067568746526>"
INFO_EMOJI = "<:info:1547724036107149413>"

ADD_EMOJI = "<:add:1547724100812931072>"
EDIT_EMOJI = "<:edit:1547724058894934116>"
DELETE_EMOJI = "<:delete:1547724056768286750>"
ROLES_EMOJI = "<:roll:1546435118455988332>"
USER_EMOJI = "<:user:1547737210986692679>"
SETTINGS_EMOJI = "<:instellingen:1547854198698287165>"

# Categorieën waarvan kanaalwijzigingen niet gelogd worden.
IGNORED_CHANNEL_CATEGORY_IDS = {
    1546178592575062196,  # Server Stats
}


# =========================================================
# HELPERS
# =========================================================

def shorten(text: str | None, limit: int = 900, empty: str = "*Geen inhoud*") -> str:
    if text is None:
        return empty

    text = str(text).strip()

    if not text:
        return empty

    if len(text) <= limit:
        return text

    return text[: limit - 1] + "…"


def display_user(user) -> str:
    if user is None:
        return "`Onbekend`"

    mention = getattr(user, "mention", None)

    if mention:
        return mention

    return f"**{user}**"


def display_channel(channel) -> str:
    if channel is None:
        return "`Onbekend`"

    mention = getattr(channel, "mention", None)

    if mention:
        return mention

    return f"**{getattr(channel, 'name', str(channel))}**"


def display_role(role) -> str:
    if role is None:
        return "`Onbekend`"

    mention = getattr(role, "mention", None)

    if mention:
        return mention

    return f"**{getattr(role, 'name', str(role))}**"


def bool_text(value: bool) -> str:
    return "Ja" if value else "Nee"


def colour_text(colour: discord.Colour) -> str:
    return f"#{colour.value:06X}"


def management_access(member: discord.Member) -> bool:
    if (
        member.guild.owner_id == member.id
        or member.guild_permissions.administrator
    ):
        return True

    return any(
        role.name.casefold() in {"admin", "owner"}
        for role in member.roles
    )


def overwrite_summary(overwrite: discord.PermissionOverwrite) -> str:
    allowed, denied = overwrite.pair()

    allowed_names = [
        name.replace("_", " ").title()
        for name, value in allowed
        if value
    ]

    denied_names = [
        name.replace("_", " ").title()
        for name, value in denied
        if value
    ]

    parts = []

    if allowed_names:
        parts.append("✅ " + ", ".join(allowed_names[:10]))

    if denied_names:
        parts.append("❌ " + ", ".join(denied_names[:10]))

    return " • ".join(parts) if parts else "Geen expliciete permissions"


# =========================================================
# COMPONENTS V2
# =========================================================

class ActionLogCard(discord.ui.LayoutView):
    def __init__(
        self,
        title: str,
        *,
        description: str | None = None,
        colour: discord.Colour = PURPLE,
        thumbnail: str | None = None,
    ):
        super().__init__(timeout=None)

        now = datetime.now(timezone.utc)
        timestamp = int(now.timestamp())

        body = description or "*Geen extra informatie beschikbaar.*"

        if thumbnail:
            intro: discord.ui.Item = discord.ui.Section(
                discord.ui.TextDisplay(
                    f"# {title}\n"
                    f"{body}"
                ),
                accessory=discord.ui.Thumbnail(
                    thumbnail,
                    description="Action Log profielfoto",
                ),
            )
        else:
            intro = discord.ui.TextDisplay(
                f"# {title}\n"
                f"{body}"
            )

        self.add_item(
            discord.ui.Container(
                intro,
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    f"-# LEVENLOOS • Action Log • "
                    f"<t:{timestamp}:F> • <t:{timestamp}:R>"
                ),
                accent_colour=colour,
            )
        )


class ActionLogFeedbackView(discord.ui.LayoutView):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
    ):
        super().__init__(timeout=180)

        if kind == "success":
            icon = SUCCESS_EMOJI
            accent = discord.Colour.from_rgb(
                87,
                242,
                135,
            )
            default_title = "Gelukt"
        elif kind == "error":
            icon = ERROR_EMOJI
            accent = discord.Colour.from_rgb(
                237,
                66,
                69,
            )
            default_title = "Fout"
        elif kind == "warning":
            icon = WARNING_EMOJI
            accent = discord.Colour.from_rgb(
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
                    f"# {icon} {title or default_title}\n"
                    + "\n".join(lines)
                ),
                accent_colour=accent,
            )
        )


class ActionLogStatusView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        channel: discord.TextChannel | None,
        bot_member: discord.Member | None,
        cache_size: int,
        cache_limit: int,
        ignored_categories: set[int],
    ):
        super().__init__(timeout=180)

        if channel is None:
            channel_text = "**Niet gevonden**"
            send_text = "**Nee**"
        else:
            channel_text = channel.mention
            send_text = (
                "**Ja**"
                if (
                    bot_member is not None
                    and channel.permissions_for(
                        bot_member
                    ).send_messages
                )
                else "**Nee**"
            )

        audit_text = (
            "**Ja**"
            if (
                bot_member is not None
                and bot_member.guild_permissions.view_audit_log
            )
            else "**Nee**"
        )

        ignored_text = (
            ", ".join(
                f"<#{category_id}>"
                for category_id in sorted(
                    ignored_categories
                )
            )
            if ignored_categories
            else "Geen"
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {INFO_EMOJI} Action Log status\n"
                    "> └ Controle van kanaal, permissies en lokale cache.\n\n"
                    f"## {INFO_EMOJI} Kanaal\n"
                    f"> └ Action Log: {channel_text}\n"
                    f"> └ Kan berichten sturen: {send_text}\n\n"
                    f"## {SETTINGS_EMOJI} Audit Log\n"
                    f"> └ Audit Log bekijken: {audit_text}\n"
                    "> └ Zonder Audit Log-permissie kan **Door:** soms niet worden vastgesteld.\n\n"
                    f"## {INFO_EMOJI} Berichtcache\n"
                    f"> └ In cache: **{cache_size:,}** / **{cache_limit:,}**\n"
                    "> └ De cache bewaart recente inhoud voor verwijderde en aangepaste berichten.\n\n"
                    f"## {SETTINGS_EMOJI} Genegeerd\n"
                    f"> └ Categorieën: {ignored_text}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(
                    "-# Join/leave, voice-status en kanaalvolgorde worden bewust niet gelogd."
                ),
                accent_colour=PURPLE,
            )
        )


# =========================================================
# COG
# =========================================================

class Actionlog(commands.Cog):

    actionlog_group = app_commands.Group(
        name="actionlog",
        description="Beheer de LEVENLOOS action log.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Eigen kleine berichtcache. Daardoor kunnen we verwijderde/gewijzigde
        # inhoud loggen, ook wanneer discord.py het bericht niet meer cached heeft.
        self.message_cache: OrderedDict[int, dict] = OrderedDict()

    async def cog_load(self):
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Actionlog vereist Discord Components V2."
            )

        logger.info("Actionlog-module geladen.")

    async def send_feedback(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        kind: str = "info",
        title: str | None = None,
    ) -> None:
        view = ActionLogFeedbackView(
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

    # =====================================================
    # MESSAGE CACHE
    # =====================================================

    def cache_message(self, message: discord.Message):
        if message.guild is None:
            return

        if message.channel.id == ACTION_LOG_CHANNEL_ID:
            return

        data = {
            "guild_id": message.guild.id,
            "channel_id": message.channel.id,
            "author_id": message.author.id,
            "author_name": str(message.author),
            "author_display_name": getattr(message.author, "display_name", str(message.author)),
            "author_avatar": message.author.display_avatar.url,
            "content": message.content or "",
            "attachments": [a.url for a in message.attachments[:5]],
        }

        self.message_cache[message.id] = data
        self.message_cache.move_to_end(message.id)

        while len(self.message_cache) > MESSAGE_CACHE_LIMIT:
            self.message_cache.popitem(last=False)

    def pop_cached_message(self, message_id: int):
        return self.message_cache.pop(message_id, None)

    def get_cached_message(self, message_id: int):
        return self.message_cache.get(message_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        self.cache_message(message)

    # =====================================================
    # OUTPUT
    # =====================================================

    async def send_log(
        self,
        guild: discord.Guild,
        title: str,
        *,
        description: str | None = None,
        colour: discord.Colour = PURPLE,
        thumbnail: str | None = None,
    ) -> bool:
        channel = guild.get_channel(
            ACTION_LOG_CHANNEL_ID
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            logger.warning(
                "Action Log-kanaal %s niet gevonden in guild %s.",
                ACTION_LOG_CHANNEL_ID,
                guild.id,
            )
            return False

        me = guild.me

        if (
            me is None
            or not channel.permissions_for(
                me
            ).send_messages
        ):
            logger.warning(
                "Geen toestemming om te sturen in Action Log-kanaal %s.",
                channel.id,
            )
            return False

        try:
            await channel.send(
                view=ActionLogCard(
                    title,
                    description=description,
                    colour=colour,
                    thumbnail=thumbnail,
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
                silent=True,
            )
        except (
            discord.Forbidden,
            discord.HTTPException,
        ):
            logger.exception(
                "Action Log-bericht versturen mislukt "
                "in guild %s.",
                guild.id,
            )
            return False

        return True

    # =====================================================
    # AUDIT LOG
    # =====================================================

    async def find_audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        *,
        target_id: int | None = None,
        extra_check=None,
    ):
        # Audit-log entries kunnen iets later binnenkomen dan het event zelf.
        # Daarom een paar keer opnieuw proberen.
        for delay in (AUDIT_DELAY * 0.8, AUDIT_DELAY * 1.2, AUDIT_DELAY * 1.8):
            await asyncio.sleep(delay)

            now = datetime.now(timezone.utc)

            try:
                async for entry in guild.audit_logs(limit=12, action=action):
                    age = abs((now - entry.created_at).total_seconds())

                    if age > AUDIT_WINDOW_SECONDS:
                        continue

                    if target_id is not None:
                        if getattr(entry.target, "id", None) != target_id:
                            continue

                    if extra_check is not None:
                        try:
                            if not extra_check(entry):
                                continue
                        except Exception:
                            continue

                    return entry

            except (discord.Forbidden, discord.HTTPException):
                return None

        return None

    def executor_text(self, entry) -> str:
        if entry is None or entry.user is None:
            return "`Onbekend`"

        return display_user(entry.user)

    def message_delete_executor_text(
        self,
        guild: discord.Guild,
        entry,
        author,
    ) -> str:
        if entry is not None and entry.user is not None:
            return display_user(entry.user)

        me = guild.me

        # Als de bot Audit Log mag bekijken en er na meerdere pogingen
        # géén delete-entry bestaat, is het vrijwel zeker een self-delete.
        if (
            author is not None
            and me is not None
            and me.guild_permissions.view_audit_log
        ):
            return f"{display_user(author)} *(zelf verwijderd)*"

        return "`Onbekend`"

    # =====================================================
    # MESSAGE DELETE
    # =====================================================

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return

        if payload.channel_id == ACTION_LOG_CHANNEL_ID:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = guild.get_channel_or_thread(payload.channel_id)
        if channel is None:
            return

        cached = self.pop_cached_message(payload.message_id)
        discord_cached = payload.cached_message

        if discord_cached is not None:
            author = discord_cached.author
            author_id = author.id
            author_text = display_user(author)
            avatar = author.display_avatar.url
            content = discord_cached.content or ""
            attachments = [a.url for a in discord_cached.attachments[:5]]
        elif cached is not None:
            author = guild.get_member(cached["author_id"])
            author_id = cached["author_id"]
            author_text = (
                display_user(author)
                if author is not None
                else f"**{cached['author_display_name']}**"
            )
            avatar = cached["author_avatar"]
            content = cached["content"]
            attachments = cached["attachments"]
        else:
            # Berichten die al bestonden vóór de botstart kunnen niet na verwijdering
            # alsnog bij Discord worden opgehaald.
            author = None
            author_id = None
            author_text = "`Onbekend`"
            avatar = None
            content = ""
            attachments = []

        entry = None

        if author_id is not None:
            entry = await self.find_audit_entry(
                guild,
                discord.AuditLogAction.message_delete,
                target_id=author_id,
                extra_check=lambda item: (
                    getattr(item.extra, "channel", None) is not None
                    and item.extra.channel.id == payload.channel_id
                ),
            )

        delete_executor = self.message_delete_executor_text(
            guild,
            entry,
            author,
        )

        description = (
            f"{author_text} • {display_channel(channel)}\n"
            f"**Door:** {delete_executor}\n\n"
            f"**Bericht:**\n"
        )

        if content:
            description += shorten(content, 1000)
        else:
            description += "*Inhoud niet beschikbaar*"

        if attachments:
            description += "\n\n**Bijlagen:**\n" + "\n".join(attachments)

        await self.send_log(
            guild,
            f"{DELETE_EMOJI} Bericht verwijderd",
            description=description,
            colour=discord.Color.red(),
            thumbnail=avatar,
        )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(
        self,
        payload: discord.RawBulkMessageDeleteEvent,
    ):
        if payload.guild_id is None:
            return

        if payload.channel_id == ACTION_LOG_CHANNEL_ID:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = guild.get_channel_or_thread(payload.channel_id)
        if channel is None:
            return

        previews = []

        for message_id in list(payload.message_ids)[:10]:
            cached = self.pop_cached_message(message_id)

            if cached is None:
                continue

            previews.append(
                f"**{cached['author_display_name']}:** "
                f"{shorten(cached['content'], 120, '*geen tekst*')}"
            )

        entry = await self.find_audit_entry(
            guild,
            discord.AuditLogAction.message_bulk_delete,
        )

        description = (
            f"{display_channel(channel)} • **{len(payload.message_ids)} berichten**\n"
            f"**Door:** {self.executor_text(entry)}"
        )

        if previews:
            description += "\n\n" + "\n".join(previews)

        await self.send_log(
            guild,
            f"{DELETE_EMOJI} Berichten gepurged",
            description=description,
            colour=discord.Color.red(),
        )

    # =====================================================
    # MESSAGE EDIT
    # =====================================================

    @commands.Cog.listener()
    async def on_raw_message_edit(
        self,
        payload: discord.RawMessageUpdateEvent,
    ):
        if payload.guild_id is None:
            return

        if payload.channel_id == ACTION_LOG_CHANNEL_ID:
            return

        # Discord stuurt ook update-events voor embeds/previews.
        if "content" not in payload.data:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = guild.get_channel_or_thread(payload.channel_id)
        if channel is None:
            return

        cached = self.get_cached_message(payload.message_id)
        discord_cached = payload.cached_message

        before_content = None
        author = None
        avatar = None

        if discord_cached is not None:
            before_content = discord_cached.content
            author = discord_cached.author
            avatar = author.display_avatar.url
        elif cached is not None:
            before_content = cached["content"]
            author = guild.get_member(cached["author_id"])
            avatar = cached["author_avatar"]

        after_content = payload.data.get("content", "")

        if before_content == after_content:
            return

        after_message = None

        try:
            after_message = await channel.fetch_message(payload.message_id)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
            AttributeError,
        ):
            pass

        if after_message is not None:
            author = after_message.author
            avatar = author.display_avatar.url
            self.cache_message(after_message)

        if author is not None:
            author_text = display_user(author)
        elif cached is not None:
            author_text = (
                f"**{cached['author_display_name']}**"
            )
        else:
            author_text = "`Onbekend`"

        jump_url = (
            after_message.jump_url
            if after_message is not None
            else f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        )

        old_text = (
            shorten(before_content, 700)
            if before_content is not None
            else "*Oude inhoud niet beschikbaar*"
        )

        new_text = shorten(after_content, 700)

        await self.send_log(
            guild,
            f"{EDIT_EMOJI} Bericht aangepast",
            description=(
                f"{author_text} • {display_channel(channel)} • "
                f"[Bericht]({jump_url})\n\n"
                f"**Voor:** {old_text}\n"
                f"**Na:** {new_text}"
            ),
            colour=discord.Color.orange(),
            thumbnail=avatar,
        )

    # =====================================================
    # BANS
    # =====================================================

    @commands.Cog.listener()
    async def on_member_ban(
        self,
        guild: discord.Guild,
        user: discord.User | discord.Member,
    ):
        entry = await self.find_audit_entry(
            guild,
            discord.AuditLogAction.ban,
            target_id=user.id,
        )

        reason = (
            entry.reason
            if entry is not None and entry.reason
            else "Geen reden opgegeven"
        )

        await self.send_log(
            guild,
            f"{ERROR_EMOJI} Gebruiker gebanned",
            description=(
                f"{display_user(user)}\n"
                f"**Door:** {self.executor_text(entry)}\n"
                f"**Reden:** {shorten(reason, 700)}"
            ),
            colour=discord.Color.red(),
            thumbnail=user.display_avatar.url,
        )

    @commands.Cog.listener()
    async def on_member_unban(
        self,
        guild: discord.Guild,
        user: discord.User,
    ):
        entry = await self.find_audit_entry(
            guild,
            discord.AuditLogAction.unban,
            target_id=user.id,
        )

        await self.send_log(
            guild,
            f"{SUCCESS_EMOJI} Ban opgeheven",
            description=(
                f"{display_user(user)}\n"
                f"**Door:** {self.executor_text(entry)}"
            ),
            colour=discord.Color.green(),
            thumbnail=user.display_avatar.url,
        )

    # =====================================================
    # MEMBER UPDATES
    # Geen join/leave of voice logging.
    # =====================================================

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ):
        if before.nick != after.nick:
            entry = await self.find_audit_entry(
                after.guild,
                discord.AuditLogAction.member_update,
                target_id=after.id,
            )

            await self.send_log(
                after.guild,
                f"{EDIT_EMOJI} Nickname gewijzigd",
                description=(
                    f"{display_user(after)}\n"
                    f"`{before.nick or before.name}` → `{after.nick or after.name}`\n"
                    f"**Door:** {self.executor_text(entry)}"
                ),
                colour=discord.Color.orange(),
                thumbnail=after.display_avatar.url,
            )

        before_roles = {
            role.id: role
            for role in before.roles
            if not role.is_default()
        }

        after_roles = {
            role.id: role
            for role in after.roles
            if not role.is_default()
        }

        added_ids = set(after_roles) - set(before_roles)
        removed_ids = set(before_roles) - set(after_roles)

        if added_ids or removed_ids:
            entry = await self.find_audit_entry(
                after.guild,
                discord.AuditLogAction.member_role_update,
                target_id=after.id,
            )

            lines = [
                display_user(after),
                f"**Door:** {self.executor_text(entry)}",
            ]

            if added_ids:
                lines.append(
                    "**+ Toegevoegd:** "
                    + ", ".join(
                        display_role(after_roles[role_id])
                        for role_id in added_ids
                    )
                )

            if removed_ids:
                lines.append(
                    "**− Verwijderd:** "
                    + ", ".join(
                        display_role(before_roles[role_id])
                        for role_id in removed_ids
                    )
                )

            await self.send_log(
                after.guild,
                f"{ROLES_EMOJI} Rollen gewijzigd",
                description="\n".join(lines),
                colour=discord.Color.orange(),
                thumbnail=after.display_avatar.url,
            )

        if before.timed_out_until != after.timed_out_until:
            entry = await self.find_audit_entry(
                after.guild,
                discord.AuditLogAction.member_update,
                target_id=after.id,
            )

            if after.timed_out_until is None:
                title = "✅ TIMEOUT VERWIJDERD"
                timeout_text = "Verwijderd"
                colour = discord.Color.green()
            else:
                title = "⏱️ TIMEOUT GEWIJZIGD"
                timeout_text = discord.utils.format_dt(
                    after.timed_out_until,
                    style="F",
                )
                colour = discord.Color.orange()

            await self.send_log(
                after.guild,
                title,
                description=(
                    f"{display_user(after)} • **{timeout_text}**\n"
                    f"**Door:** {self.executor_text(entry)}"
                ),
                colour=colour,
                thumbnail=after.display_avatar.url,
            )

    # =====================================================
    # CHANNELS / CATEGORIES
    # Positie/re-order wordt bewust NIET gelogd.
    # Server Stats categorie wordt volledig genegeerd.
    # =====================================================

    def ignore_channel_log(
        self,
        channel: discord.abc.GuildChannel,
    ) -> bool:
        if channel.id == ACTION_LOG_CHANNEL_ID:
            return True

        if channel.id in IGNORED_CHANNEL_CATEGORY_IDS:
            return True

        if channel.category_id in IGNORED_CHANNEL_CATEGORY_IDS:
            return True

        return False


    @commands.Cog.listener()
    async def on_guild_channel_create(
        self,
        channel: discord.abc.GuildChannel,
    ):
        if self.ignore_channel_log(channel):
            return

        entry = await self.find_audit_entry(
            channel.guild,
            discord.AuditLogAction.channel_create,
            target_id=channel.id,
        )

        extra = (
            f"\n**Categorie:** {display_channel(channel.category)}"
            if channel.category is not None
            else ""
        )

        await self.send_log(
            channel.guild,
            f"{ADD_EMOJI} Kanaal aangemaakt",
            description=(
                f"{display_channel(channel)} • `{channel.type}`\n"
                f"**Door:** {self.executor_text(entry)}"
                f"{extra}"
            ),
            colour=discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self,
        channel: discord.abc.GuildChannel,
    ):
        if self.ignore_channel_log(channel):
            return

        entry = await self.find_audit_entry(
            channel.guild,
            discord.AuditLogAction.channel_delete,
            target_id=channel.id,
        )

        extra = (
            f"\n**Categorie:** {display_channel(channel.category)}"
            if channel.category is not None
            else ""
        )

        await self.send_log(
            channel.guild,
            f"{DELETE_EMOJI} Kanaal verwijderd",
            description=(
                f"**{channel.name}** • `{channel.type}`\n"
                f"**Door:** {self.executor_text(entry)}"
                f"{extra}"
            ),
            colour=discord.Color.red(),
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ):
        if (
            self.ignore_channel_log(before)
            or self.ignore_channel_log(after)
        ):
            return

        changes = []

        if before.name != after.name:
            changes.append(
                f"**Naam:** `{before.name}` → `{after.name}`"
            )

        if before.category_id != after.category_id:
            changes.append(
                f"**Categorie:** {display_channel(before.category)} → "
                f"{display_channel(after.category)}"
            )

        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            old_topic = (before.topic or "").strip()
            new_topic = (after.topic or "").strip()

            # Leeg -> leeg nooit loggen.
            if old_topic != new_topic and (old_topic or new_topic):
                changes.append(
                    f"**Topic:** `{shorten(old_topic, 220, 'Geen topic')}` → "
                    f"`{shorten(new_topic, 220, 'Geen topic')}`"
                )

            if before.slowmode_delay != after.slowmode_delay:
                changes.append(
                    f"**Slowmode:** `{before.slowmode_delay}s` → "
                    f"`{after.slowmode_delay}s`"
                )

            if before.nsfw != after.nsfw:
                changes.append(
                    f"**NSFW:** `{bool_text(before.nsfw)}` → "
                    f"`{bool_text(after.nsfw)}`"
                )

        if isinstance(before, discord.VoiceChannel) and isinstance(after, discord.VoiceChannel):
            if before.bitrate != after.bitrate:
                changes.append(
                    f"**Bitrate:** `{before.bitrate}` → `{after.bitrate}`"
                )

            if before.user_limit != after.user_limit:
                changes.append(
                    f"**User limit:** `{before.user_limit}` → `{after.user_limit}`"
                )

        before_overwrites = before.overwrites
        after_overwrites = after.overwrites

        overwrite_targets = set(before_overwrites) | set(after_overwrites)
        overwrite_changes = []

        for target in overwrite_targets:
            old = before_overwrites.get(
                target,
                discord.PermissionOverwrite(),
            )

            new = after_overwrites.get(
                target,
                discord.PermissionOverwrite(),
            )

            if old == new:
                continue

            target_name = (
                target.mention
                if hasattr(target, "mention")
                else str(target)
            )

            overwrite_changes.append(
                f"**Permissions {target_name}:** "
                f"{overwrite_summary(old)} → {overwrite_summary(new)}"
            )

        if overwrite_changes:
            changes.extend(overwrite_changes[:5])

        # Belangrijk: position wordt NIET bekeken.
        if not changes:
            return

        entry = await self.find_audit_entry(
            after.guild,
            discord.AuditLogAction.channel_update,
            target_id=after.id,
        )

        await self.send_log(
            after.guild,
            f"{EDIT_EMOJI} Kanaal gewijzigd",
            description=(
                f"{display_channel(after)}\n"
                + "\n".join(changes)
                + f"\n**Door:** {self.executor_text(entry)}"
            ),
            colour=discord.Color.orange(),
        )

    # =====================================================
    # ROLES
    # Positie/re-order wordt bewust NIET gelogd.
    # =====================================================

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        entry = await self.find_audit_entry(
            role.guild,
            discord.AuditLogAction.role_create,
            target_id=role.id,
        )

        await self.send_log(
            role.guild,
            f"{ADD_EMOJI} Rol aangemaakt",
            description=(
                f"{display_role(role)} • `{colour_text(role.colour)}`\n"
                f"**Door:** {self.executor_text(entry)}"
            ),
            colour=discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        entry = await self.find_audit_entry(
            role.guild,
            discord.AuditLogAction.role_delete,
            target_id=role.id,
        )

        await self.send_log(
            role.guild,
            f"{DELETE_EMOJI} Rol verwijderd",
            description=(
                f"**{role.name}**\n"
                f"**Door:** {self.executor_text(entry)}"
            ),
            colour=discord.Color.red(),
        )

    @commands.Cog.listener()
    async def on_guild_role_update(
        self,
        before: discord.Role,
        after: discord.Role,
    ):
        changes = []

        if before.name != after.name:
            changes.append(
                f"**Naam:** `{before.name}` → `{after.name}`"
            )

        if before.colour != after.colour:
            changes.append(
                f"**Kleur:** `{colour_text(before.colour)}` → "
                f"`{colour_text(after.colour)}`"
            )

        if before.hoist != after.hoist:
            changes.append(
                f"**Apart tonen:** `{bool_text(before.hoist)}` → "
                f"`{bool_text(after.hoist)}`"
            )

        if before.mentionable != after.mentionable:
            changes.append(
                f"**Mentionable:** `{bool_text(before.mentionable)}` → "
                f"`{bool_text(after.mentionable)}`"
            )

        if before.permissions != after.permissions:
            before_allowed = {
                name
                for name, value in before.permissions
                if value
            }

            after_allowed = {
                name
                for name, value in after.permissions
                if value
            }

            added = after_allowed - before_allowed
            removed = before_allowed - after_allowed

            if added:
                changes.append(
                    "**Permissions +:** "
                    + ", ".join(
                        sorted(
                            name.replace("_", " ").title()
                            for name in added
                        )[:15]
                    )
                )

            if removed:
                changes.append(
                    "**Permissions −:** "
                    + ", ".join(
                        sorted(
                            name.replace("_", " ").title()
                            for name in removed
                        )[:15]
                    )
                )

        # position wordt bewust genegeerd
        if not changes:
            return

        entry = await self.find_audit_entry(
            after.guild,
            discord.AuditLogAction.role_update,
            target_id=after.id,
        )

        await self.send_log(
            after.guild,
            f"{EDIT_EMOJI} Rol gewijzigd",
            description=(
                f"{display_role(after)}\n"
                + "\n".join(changes)
                + f"\n**Door:** {self.executor_text(entry)}"
            ),
            colour=discord.Color.orange(),
        )

    # =====================================================
    # SERVER SETTINGS
    # =====================================================

    @commands.Cog.listener()
    async def on_guild_update(
        self,
        before: discord.Guild,
        after: discord.Guild,
    ):
        changes = []

        if before.name != after.name:
            changes.append(
                f"**Naam:** `{before.name}` → `{after.name}`"
            )

        if before.verification_level != after.verification_level:
            changes.append(
                f"**Verificatie:** `{before.verification_level}` → "
                f"`{after.verification_level}`"
            )

        if before.default_notifications != after.default_notifications:
            changes.append(
                f"**Notificaties:** `{before.default_notifications}` → "
                f"`{after.default_notifications}`"
            )

        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(
                f"**Contentfilter:** `{before.explicit_content_filter}` → "
                f"`{after.explicit_content_filter}`"
            )

        if before.afk_channel != after.afk_channel:
            changes.append(
                f"**AFK-kanaal:** {display_channel(before.afk_channel)} → "
                f"{display_channel(after.afk_channel)}"
            )

        if before.afk_timeout != after.afk_timeout:
            changes.append(
                f"**AFK-timeout:** `{before.afk_timeout}s` → "
                f"`{after.afk_timeout}s`"
            )

        if not changes:
            return

        entry = await self.find_audit_entry(
            after,
            discord.AuditLogAction.guild_update,
            target_id=after.id,
        )

        await self.send_log(
            after,
            f"{SETTINGS_EMOJI} Serverinstellingen gewijzigd",
            description=(
                "\n".join(changes)
                + f"\n**Door:** {self.executor_text(entry)}"
            ),
            colour=discord.Color.orange(),
        )

    # =====================================================
    # TEST COMMAND
    # =====================================================

    @actionlog_group.command(
        name="test",
        description="Stuur een testbericht naar de Action Log.",
    )
    async def test_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
        ):
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        if not management_access(
            interaction.user
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        channel = interaction.guild.get_channel(
            ACTION_LOG_CHANNEL_ID
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            await self.send_feedback(
                interaction,
                "Het Action Log-kanaal kon niet worden gevonden.",
                kind="error",
            )
            return

        sent = await self.send_log(
            interaction.guild,
            f"{INFO_EMOJI} Action Log test",
            description=(
                f"{display_user(interaction.user)}\n"
                "> └ Components V2 logging werkt."
            ),
            colour=PURPLE,
            thumbnail=interaction.user.display_avatar.url,
        )

        await self.send_feedback(
            interaction,
            (
                f"Test verstuurd naar {channel.mention}."
                if sent
                else "De test kon niet worden verstuurd."
            ),
            kind="success" if sent else "error",
        )

    @actionlog_group.command(
        name="status",
        description="Controleer de Action Log en benodigde permissies.",
    )
    async def status_command(
        self,
        interaction: discord.Interaction,
    ):
        if (
            interaction.guild is None
            or not isinstance(
                interaction.user,
                discord.Member,
            )
        ):
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        if not management_access(
            interaction.user
        ):
            await self.send_feedback(
                interaction,
                "Je hebt geen toegang tot dit command.",
                kind="error",
                title="Geen toegang",
            )
            return

        channel = interaction.guild.get_channel(
            ACTION_LOG_CHANNEL_ID
        )

        await interaction.response.send_message(
            view=ActionLogStatusView(
                channel=(
                    channel
                    if isinstance(
                        channel,
                        discord.TextChannel,
                    )
                    else None
                ),
                bot_member=interaction.guild.me,
                cache_size=len(self.message_cache),
                cache_limit=MESSAGE_CACHE_LIMIT,
                ignored_categories=IGNORED_CHANNEL_CATEGORY_IDS,
            ),
            ephemeral=True,
        )

    @actionlog_group.command(
        name="info",
        description="Bekijk wat de Action Log wel en niet registreert.",
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

        body = (
            "## Berichten\n"
            "> └ Verwijderen, bulk verwijderen en inhoudswijzigingen.\n\n"
            "## Leden & moderatie\n"
            "> └ Bans, unbans, nicknames, rollen en time-outs.\n\n"
            "## Serverbeheer\n"
            "> └ Kanalen, categorieën, rollen en serverinstellingen.\n\n"
            "## Bewust niet gelogd\n"
            "> └ Join/leave, voice-status en alleen kanaal/rol-volgorde.\n"
            "> └ Server Stats-kanaalwijzigingen worden genegeerd om ruis te voorkomen."
        )

        await interaction.response.send_message(
            view=ActionLogFeedbackView(
                body,
                kind="info",
                title="Action Log",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Actionlog(bot))
