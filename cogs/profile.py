from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks


# =========================================================
# CONFIG
# =========================================================

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DATABASE = ROOT / "profiles.db"
LEVENLOOS_DATABASE = ROOT / "levenloos.db"
LEVELS_DATABASE = ROOT / "levels.db"
BIRTHDAYS_DATABASE = ROOT / "birthdays.db"

BRAND_COLOR = discord.Color.from_rgb(108, 39, 218)
SHOWCASE_SIZE = 6
BADGES_PER_PAGE = 10
COLLECTION_BADGES_PER_PAGE = 8
AUTO_SYNC_MINUTES = 60

PASSPORT_BADGE = (
    "<:p1:1547352413558546543><:p2:1547352411444748460>"
    "<:p3:1547352409062248548><:p4:1547352407217020999>"
    "<:p5:1547352405556076544><:p6:1547352403869827172>"
    "<:p7:1547352402112290976><:p8:1547352400782827560>"
)

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

GAMES_EMOJI = "<:gamesbutton:1547854165097717801>"
BADGES_EMOJI = "<:badges:1547874507635687464>"
GENRES_EMOJI = "<:genres:1546435084897222686>"
ROLES_EMOJI = "<:roll:1546435118455988332>"

VOICE_EMOJI = "<:voice:1547737205429243924>"
TEXT_EMOJI = "<:berichten:1547737207778058250>"
USER_EMOJI = "<:user:1547737210986692679>"
XP_EMOJI = "<:xp:1547737203789144136>"

logger = logging.getLogger(__name__)

RARITY_ORDER = {
    "common": 1,
    "uncommon": 2,
    "rare": 3,
    "epic": 4,
    "legendary": 5,
    "mythic": 6,
    "secret": 7,
}

RARITY_LABELS = {
    "common": "Common",
    "uncommon": "Uncommon",
    "rare": "Rare",
    "epic": "Epic",
    "legendary": "Legendary",
    "mythic": "Mythic",
    "secret": "Secret",
}

BADGE_XP_DEFAULTS = {
    # Badges zijn een bonus op het normale Levels-systeem, niet de hoofdbron van XP.
    "common": 100,
    "uncommon": 250,
    "rare": 500,
    "epic": 1_000,
    "legendary": 2_000,
    "mythic": 4_000,
    "secret": 2_000,
}

# Sommige badge-types stapelen vanzelf op (accountleeftijd, serverduur, levels, enz.).
# Die krijgen bewust een lagere factor zodat "een oud account" geen tientallen levels geeft.
BADGE_XP_CONDITION_MULTIPLIERS = {
    "account_days": 0.20,
    "member_days": 0.35,
    "booster_days": 0.35,
    "birthday_registered": 0.25,
    "booster": 0.25,
    "xp": 0.25,
    "level": 0.25,
    "games": 0.40,
    "genres": 0.40,
    "extra_roles": 0.40,
    "total_roles": 0.40,
    "react_roles_total": 0.40,
    "has_game": 0.40,
    "has_genre": 0.40,
    "has_profile_role": 0.40,
    "waves_given": 0.60,
    "waves_received": 0.60,
    "reactions_given": 0.60,
    "reactions_received": 0.60,
    "invites": 0.60,
    "social_total": 0.60,
    "badges_owned": 0.50,
}

BADGE_REWARD_SCHEME_VERSION = 2

CATEGORY_LABELS = {
    "chat": "Chat",
    "voice": "Voice",
    "xp": "XP",
    "history": "Historie",
    "account": "Account",
    "social": "Social",
    "games": "Games",
    "roles": "Rollen",
    "community": "Community",
    "collector": "Collector",
    "records": "Records",
    "special": "Special",
}

SUPPORTED_CONDITIONS = {
    "messages",
    "voice_hours",
    "xp",
    "member_days",
    "waves_given",
    "waves_received",
    "reactions_given",
    "reactions_received",
    "invites",
    "games",
    "genres",
    "extra_roles",
    "level",
    "account_days",
    "booster_days",
    "total_roles",
    "react_roles_total",
    "social_total",
    "badges_owned",
    "has_game",
    "has_genre",
    "has_profile_role",
    "birthday_registered",
    "booster",
    "rank_messages",
    "rank_voice",
    "rank_xp",
    "join_position",
    "has_role",
    "manual",
}

SUPPORTED_MODES = {
    "permanent",
    "dynamic",
    "manual",
}

CATEGORY_EMOJIS = {
    "all": BADGES_EMOJI,
    "chat": TEXT_EMOJI,
    "voice": VOICE_EMOJI,
    "xp": XP_EMOJI,
    "history": INFO_EMOJI,
    "account": USER_EMOJI,
    "social": USER_EMOJI,
    "games": GAMES_EMOJI,
    "roles": ROLES_EMOJI,
    "community": USER_EMOJI,
    "collector": BADGES_EMOJI,
    "records": XP_EMOJI,
    "special": SUCCESS_EMOJI,
}

COLLECTION_STATUS_LABELS = {
    "locked": "Te behalen",
    "all": "Alles",
    "earned": "Behaald",
    "dynamic": "Dynamisch",
    "manual": "Handmatig",
}


# =========================================================
# HELPERS
# =========================================================


def management_access(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id:
        return True
    if member.guild_permissions.administrator:
        return True
    role_names = {role.name.lower() for role in member.roles}
    return "admin" in role_names or "owner" in role_names


def fmt_number(value: int | float) -> str:
    return f"{int(value):,}".replace(",", ".")


def fmt_voice(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60

    if days:
        return f"{days}d {hours}u {minutes:02d}m"
    if hours:
        return f"{hours}u {minutes:02d}m"
    return f"{minutes}m"


def level_from_xp(total_xp: int) -> int:
    total_xp = max(0, int(total_xp))
    level = 1
    while True:
        next_level = level + 1
        needed = 100 * (((next_level * (next_level + 1)) // 2) - 1)
        if total_xp < needed:
            return level
        level = next_level


def rank_text(rank: int, total: int) -> str:
    if rank <= 0:
        return "—"
    return f"#{rank} van {total}"


def now_ts() -> int:
    return int(time.time())


def normalise_rarity(value: str) -> str:
    value = value.strip().lower()
    return value if value in RARITY_ORDER else "common"


def normalise_category(value: str) -> str:
    value = value.strip().lower()
    return value or "community"


def normalise_mode(value: str) -> str:
    value = value.strip().lower()
    return value if value in SUPPORTED_MODES else "permanent"


def normalise_lookup(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def default_badge_xp(rarity: str, mode: str) -> int:
    """Basisbeloning; vooral gebruikt als fallback voor custom badges."""
    mode = normalise_mode(mode)
    if mode == "dynamic":
        return 0
    return int(BADGE_XP_DEFAULTS.get(normalise_rarity(rarity), 100))


def calculated_badge_xp(
    rarity: str,
    mode: str,
    condition_type: str,
) -> int:
    """Gebalanceerde reward voor badges die automatisch uit een condition komen."""
    mode = normalise_mode(mode)
    if mode == "dynamic":
        return 0

    base = default_badge_xp(rarity, mode)
    multiplier = float(
        BADGE_XP_CONDITION_MULTIPLIERS.get(
            str(condition_type).strip().lower(),
            1.0,
        )
    )

    # Op 25 XP afronden houdt de rewardlijst netjes en voorspelbaar.
    reward = int(round((base * multiplier) / 25.0) * 25)
    return max(25, reward) if base > 0 else 0


def badge_sort_key(row: dict) -> tuple:
    return (
        -RARITY_ORDER.get(row.get("rarity", "common"), 1),
        int(row.get("sort_order", 0)),
        row.get("name", "").casefold(),
    )



def component_emoji(value: str | None) -> discord.PartialEmoji | None:
    if not value:
        return None
    try:
        emoji = discord.PartialEmoji.from_str(value)
    except Exception:
        return None
    return emoji if emoji.name else None


def truncate_component(value: str, limit: int = 100) -> str:
    value = str(value).strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def feedback_style(kind: str) -> tuple[str, str, discord.Colour]:
    if kind == "success":
        return "Gelukt", SUCCESS_EMOJI, discord.Colour.from_rgb(87, 242, 135)
    if kind == "error":
        return "Fout", ERROR_EMOJI, discord.Colour.from_rgb(237, 66, 69)
    if kind == "warning":
        return "Let op", WARNING_EMOJI, discord.Colour.from_rgb(254, 231, 92)
    return "Informatie", INFO_EMOJI, BRAND_COLOR


@dataclass(slots=True)
class BadgeDefinition:

    badge_id: str
    name: str
    emoji: str
    description: str
    category: str
    rarity: str
    condition_type: str
    condition_value: str
    mode: str
    reward_xp: int = 0
    secret: bool = False
    sort_order: int = 0


# =========================================================
# STARTER BADGES
# =========================================================


def starter_badges() -> list[BadgeDefinition]:
    badges: list[BadgeDefinition] = []

    def add(
        badge_id: str,
        name: str,
        emoji: str,
        description: str,
        category: str,
        rarity: str,
        condition_type: str,
        condition_value: str | int | float,
        mode: str = "permanent",
        *,
        reward_xp: int | None = None,
        secret: bool = False,
        sort_order: int = 0,
    ) -> None:
        if reward_xp is None:
            reward_xp = calculated_badge_xp(
                rarity,
                mode,
                condition_type,
            )
        if normalise_mode(mode) == "dynamic":
            reward_xp = 0

        badges.append(
            BadgeDefinition(
                badge_id=badge_id,
                name=name,
                emoji=emoji,
                description=description,
                category=category,
                rarity=rarity,
                condition_type=condition_type,
                condition_value=str(condition_value),
                mode=mode,
                reward_xp=max(0, int(reward_xp)),
                secret=secret,
                sort_order=sort_order,
            )
        )

    message_badges = [
        (100, "First Words", "💬", "100 berichten verstuurd.", "common"),
        (500, "Chatty", "🗨️", "500 berichten verstuurd.", "common"),
        (1000, "Yapper", "🗣️", "1.000 berichten verstuurd.", "uncommon"),
        (2500, "Certified Yapper", "📢", "2.500 berichten verstuurd.", "uncommon"),
        (5000, "Keyboard Warrior", "⌨️", "5.000 berichten verstuurd.", "rare"),
        (10000, "Chronically Online", "🛰️", "10.000 berichten verstuurd.", "rare"),
        (25000, "Wall of Text", "📜", "25.000 berichten verstuurd.", "epic"),
        (50000, "Chat Legend", "🏆", "50.000 berichten verstuurd.", "legendary"),
    ]
    for index, (amount, name, emoji, description, rarity) in enumerate(message_badges):
        add(f"messages_{amount}", name, emoji, description, "chat", rarity, "messages", amount, sort_order=index)

    voice_badges = [
        (10, "Mic Check", "🎙️", "10 uur in voice doorgebracht.", "common"),
        (25, "Voice Regular", "🎧", "25 uur in voice doorgebracht.", "common"),
        (50, "Open Mic", "🔊", "50 uur in voice doorgebracht.", "uncommon"),
        (100, "Voice Dweller", "🛋️", "100 uur in voice doorgebracht.", "uncommon"),
        (250, "Permanent Resident", "🏠", "250 uur in voice doorgebracht.", "rare"),
        (500, "Voice Addict", "📻", "500 uur in voice doorgebracht.", "rare"),
        (1000, "No Escape", "🕳️", "1.000 uur in voice doorgebracht.", "epic"),
        (2000, "Living in Discord", "🏢", "2.000 uur in voice doorgebracht.", "legendary"),
    ]
    for index, (amount, name, emoji, description, rarity) in enumerate(voice_badges):
        add(f"voice_{amount}", name, emoji, description, "voice", rarity, "voice_hours", amount, sort_order=index)

    xp_badges = [
        (1000, "Getting Started", "✨", "1.000 XP verzameld.", "common"),
        (5000, "XP Collector", "💫", "5.000 XP verzameld.", "common"),
        (10000, "Level Grinder", "⚡", "10.000 XP verzameld.", "uncommon"),
        (25000, "XP Hoarder", "💎", "25.000 XP verzameld.", "rare"),
        (50000, "Power User", "🌟", "50.000 XP verzameld.", "rare"),
        (100000, "Ascended", "🔮", "100.000 XP verzameld.", "epic"),
        (250000, "Levenloos Energy", "☄️", "250.000 XP verzameld.", "legendary"),
    ]
    for index, (amount, name, emoji, description, rarity) in enumerate(xp_badges):
        add(f"xp_{amount}", name, emoji, description, "xp", rarity, "xp", amount, sort_order=index)

    history_badges = [
        (30, "Settling In", "📍", "30 dagen lid van LEVENLOOS.", "common"),
        (90, "Quarterly Resident", "🗓️", "90 dagen lid van LEVENLOOS.", "common"),
        (180, "Halfway Home", "🏡", "180 dagen lid van LEVENLOOS.", "uncommon"),
        (365, "One Year Later", "🎂", "1 jaar lid van LEVENLOOS.", "uncommon"),
        (730, "Veteran II", "🏛️", "2 jaar lid van LEVENLOOS.", "rare"),
        (1095, "Veteran III", "🏛️", "3 jaar lid van LEVENLOOS.", "rare"),
        (1460, "Ancient Member", "🗿", "4 jaar lid van LEVENLOOS.", "epic"),
        (1825, "Five Years Levenloos", "👑", "5 jaar lid van LEVENLOOS.", "legendary"),
    ]
    for index, (days, name, emoji, description, rarity) in enumerate(history_badges):
        add(f"member_{days}d", name, emoji, description, "history", rarity, "member_days", days, sort_order=index)

    social_sets = [
        ("waves_given", "welcome", "👋", [
            (1, "First Wave", "Iemand welkom geheten.", "common"),
            (10, "Friendly Face", "10 nieuwe leden welkom geheten.", "common"),
            (25, "Greeter", "25 nieuwe leden welkom geheten.", "uncommon"),
            (50, "Receptionist", "50 nieuwe leden welkom geheten.", "rare"),
            (100, "Welcome Committee", "100 nieuwe leden welkom geheten.", "epic"),
        ]),
        ("reactions_received", "reacted", "❤️", [
            (10, "Noticed", "10 reacties op je berichten ontvangen.", "common"),
            (50, "Popular", "50 reacties op je berichten ontvangen.", "common"),
            (100, "Crowd Pleaser", "100 reacties op je berichten ontvangen.", "uncommon"),
            (250, "Fanclub", "250 reacties op je berichten ontvangen.", "rare"),
            (500, "Celebrity", "500 reacties op je berichten ontvangen.", "epic"),
            (1000, "Main Character", "1.000 reacties op je berichten ontvangen.", "legendary"),
        ]),
        ("reactions_given", "reactor", "💜", [
            (10, "React Enjoyer", "10 reacties aan anderen gegeven.", "common"),
            (50, "Emoji Dealer", "50 reacties aan anderen gegeven.", "common"),
            (100, "Reaction Machine", "100 reacties aan anderen gegeven.", "uncommon"),
            (250, "Certified Reactor", "250 reacties aan anderen gegeven.", "rare"),
            (500, "Emoji Menace", "500 reacties aan anderen gegeven.", "epic"),
        ]),
        ("invites", "invites", "📨", [
            (1, "Recruiter", "1 lid via jouw invite binnengebracht.", "common"),
            (3, "Bring a Friend", "3 leden via jouw invites binnengebracht.", "common"),
            (5, "Party Starter", "5 leden via jouw invites binnengebracht.", "uncommon"),
            (10, "Community Builder", "10 leden via jouw invites binnengebracht.", "rare"),
            (25, "Cult Leader", "25 leden via jouw invites binnengebracht.", "legendary"),
        ]),
    ]
    for condition, prefix, emoji, values in social_sets:
        for index, (amount, name, description, rarity) in enumerate(values):
            add(f"{prefix}_{amount}", name, emoji, description, "social", rarity, condition, amount, sort_order=index)

    game_badges = [
        (1, "Player One", "🎮", "Minimaal 1 actieve game gekozen.", "common"),
        (5, "Game Shelf", "🕹️", "5 actieve games gekozen.", "common"),
        (10, "Backlog", "📚", "10 actieve games gekozen.", "uncommon"),
        (20, "Game Hoarder", "🎲", "20 actieve games gekozen.", "rare"),
        (30, "Touch Grass", "🌱", "30 actieve games gekozen.", "epic"),
    ]
    for index, (amount, name, emoji, description, rarity) in enumerate(game_badges):
        add(f"games_{amount}", name, emoji, description, "games", rarity, "games", amount, sort_order=index)

    genre_badges = [
        (1, "A Type", "🧠", "Minimaal 1 genre gekozen.", "common"),
        (3, "Genre Hopper", "🗺️", "3 genres gekozen.", "uncommon"),
        (5, "Omnivore", "🍽️", "5 genres gekozen.", "rare"),
    ]
    for index, (amount, name, emoji, description, rarity) in enumerate(genre_badges):
        add(f"genres_{amount}", name, emoji, description, "games", rarity, "genres", amount, sort_order=20 + index)

    add("birthday_registered", "Birthday Registered", "🎂", "Verjaardag geregistreerd bij LEVENLOOS.", "community", "common", "birthday_registered", 1)
    add("server_booster", "Server Booster", "🚀", "Boost LEVENLOOS.", "community", "rare", "booster", 1, mode="dynamic")

    add("rank_messages_3", "Top Yapper", "🥉", "Momenteel top 3 op berichten.", "records", "epic", "rank_messages", 3, mode="dynamic")
    add("rank_messages_1", "Yap King", "👑", "Momenteel #1 op berichten.", "records", "legendary", "rank_messages", 1, mode="dynamic")
    add("rank_voice_3", "Voice Royalty", "🎙️", "Momenteel top 3 op voice-tijd.", "records", "epic", "rank_voice", 3, mode="dynamic")
    add("rank_voice_1", "Voice King", "👑", "Momenteel #1 op voice-tijd.", "records", "legendary", "rank_voice", 1, mode="dynamic")
    add("rank_xp_3", "XP Elite", "💎", "Momenteel top 3 op XP.", "records", "epic", "rank_xp", 3, mode="dynamic")
    add("rank_xp_1", "XP Champion", "🏆", "Momenteel #1 op XP.", "records", "legendary", "rank_xp", 1, mode="dynamic")

    # Handmatige badges: alleen admins bepalen wie deze krijgt.
    add("founding_eight", "Founding Eight", "💜", "Een van de oorspronkelijke acht.", "special", "mythic", "manual", 0, mode="manual")
    add("irl_meetup", "IRL Survivor", "🤝", "Was aanwezig bij een officiële LEVENLOOS IRL-meetup.", "special", "rare", "manual", 0, mode="manual")
    add("community_legend", "Community Legend", "🌌", "Een bijzondere handmatige LEVENLOOS-erkenning.", "special", "mythic", "manual", 0, mode="manual")


    # ---------------------------------------------------------
    # EXTRA BADGES • uitbreiding richting ~300 totaal
    # ---------------------------------------------------------

    extra_sets = [
        ("messages_extra", "chatx", "chat", "messages", [(1, 'First Message', '👋', 'Je eerste geregistreerde bericht op LEVENLOOS.', 'common'), (10, 'Small Talk', '💭', '10 berichten verstuurd.', 'common'), (25, 'Getting Chatty', '🫧', '25 berichten verstuurd.', 'common'), (50, 'Half Century', '📝', '50 berichten verstuurd.', 'common'), (250, 'Scroll Starter', '📱', '250 berichten verstuurd.', 'common'), (750, 'Frequent Poster', '📨', '750 berichten verstuurd.', 'uncommon'), (1500, 'Chat Habit', '🧃', '1.500 berichten verstuurd.', 'uncommon'), (7500, 'Endless Scroll', '🌀', '7.500 berichten verstuurd.', 'rare'), (15000, 'Server Newspaper', '📰', '15.000 berichten verstuurd.', 'rare'), (35000, 'Terminally Typing', '🖥️', '35.000 berichten verstuurd.', 'epic'), (75000, 'Keyboard Fossil', '🦴', '75.000 berichten verstuurd.', 'legendary'), (100000, 'The Chat Is You', '♾️', '100.000 berichten verstuurd.', 'mythic')]),
        ("voice_extra", "voicex", "voice", "voice_hours", [(1, 'Hello? Hello?', '🎤', '1 uur in voice doorgebracht.', 'common'), (5, 'Five Hour Call', '☎️', '5 uur in voice doorgebracht.', 'common'), (15, 'Headset On', '🎧', '15 uur in voice doorgebracht.', 'common'), (40, 'Background Noise', '📡', '40 uur in voice doorgebracht.', 'uncommon'), (75, 'Pull Up a Chair', '🪑', '75 uur in voice doorgebracht.', 'uncommon'), (150, 'Always Connected', '🔌', '150 uur in voice doorgebracht.', 'rare'), (350, 'Second Home', '🏘️', '350 uur in voice doorgebracht.', 'rare'), (750, 'Voice Creature', '👾', '750 uur in voice doorgebracht.', 'epic'), (1250, 'Rent Is Due', '🧾', '1.250 uur in voice doorgebracht.', 'epic'), (1500, 'Mic Permanently On', '🎚️', '1.500 uur in voice doorgebracht.', 'epic'), (2500, 'Discord Tenant', '🛏️', '2.500 uur in voice doorgebracht.', 'legendary'), (3000, 'Voice Fossil', '🦴', '3.000 uur in voice doorgebracht.', 'legendary'), (5000, 'Voice Dimension', '🪐', '5.000 uur in voice doorgebracht.', 'mythic'), (7500, 'Please Disconnect', '🚪', '7.500 uur in voice doorgebracht.', 'mythic')]),
        ("xp_extra", "xpx", "xp", "xp", [(100, 'Spark', '✨', '100 XP verzameld.', 'common'), (2500, 'Pocket XP', '🪙', '2.500 XP verzameld.', 'common'), (7500, 'Grinding Begins', '⚙️', '7.500 XP verzameld.', 'uncommon'), (15000, 'Momentum', '💨', '15.000 XP verzameld.', 'uncommon'), (35000, 'XP Vault', '🔐', '35.000 XP verzameld.', 'rare'), (75000, 'Charged Up', '🔋', '75.000 XP verzameld.', 'rare'), (150000, 'Overclocked', '💻', '150.000 XP verzameld.', 'epic'), (200000, 'XP Reactor', '⚛️', '200.000 XP verzameld.', 'epic'), (350000, 'Purple Power', '🟣', '350.000 XP verzameld.', 'legendary'), (500000, 'Level Century Energy', '💯', '500.000 XP verzameld.', 'legendary'), (750000, 'XP Singularity', '🕳️', '750.000 XP verzameld.', 'legendary'), (1000000, 'Millionaire', '💰', '1.000.000 XP verzameld.', 'mythic'), (1500000, 'Beyond Reason', '🌠', '1.500.000 XP verzameld.', 'mythic'), (2000000, 'XP Is Just a Number', '∞️', '2.000.000 XP verzameld.', 'mythic')]),
        ("history_extra", "historyx", "history", "member_days", [(1, 'Fresh Arrival', '🌱', '1 dag lid van LEVENLOOS.', 'common'), (7, 'One Week In', '📆', '1 week lid van LEVENLOOS.', 'common'), (14, 'Still Here', '🪴', '2 weken lid van LEVENLOOS.', 'common'), (60, 'Two Months Deep', '🗓️', '60 dagen lid van LEVENLOOS.', 'common'), (120, 'Seasoned', '🍂', '120 dagen lid van LEVENLOOS.', 'uncommon'), (270, 'Nine Months Later', '⏳', '270 dagen lid van LEVENLOOS.', 'uncommon'), (545, 'Year and a Half', '🕰️', 'Ongeveer 1,5 jaar lid van LEVENLOOS.', 'rare'), (1278, 'Three and a Half', '🏺', 'Ongeveer 3,5 jaar lid van LEVENLOOS.', 'epic'), (1642, 'Almost Five', '📜', 'Ongeveer 4,5 jaar lid van LEVENLOOS.', 'epic'), (2190, 'Six Years Levenloos', '🛡️', '6 jaar lid van LEVENLOOS.', 'mythic')]),
        ("level_extra", "level", "xp", "level", [(5, 'Level Five', '5️⃣', 'Level 5 bereikt.', 'common'), (10, 'Double Digits', '🔟', 'Level 10 bereikt.', 'common'), (20, 'Getting Somewhere', '🧭', 'Level 20 bereikt.', 'common'), (30, 'Thirty Deep', '📈', 'Level 30 bereikt.', 'uncommon'), (40, 'Levelled Up', '⬆️', 'Level 40 bereikt.', 'uncommon'), (50, 'Halfway to 100', '🎯', 'Level 50 bereikt.', 'rare'), (60, 'No Turning Back', '🚧', 'Level 60 bereikt.', 'rare'), (75, 'Three Quarters', '3️⃣', 'Level 75 bereikt.', 'rare'), (100, 'Century Club', '💯', 'Level 100 bereikt.', 'epic'), (125, 'Beyond Century', '📶', 'Level 125 bereikt.', 'epic'), (150, 'Levenloos Level', '🟣', 'Level 150 bereikt.', 'legendary'), (175, 'Afgeschreven', '📋', 'Level 175 bereikt.', 'legendary'), (200, 'Verloren Zaak', '🫠', 'Level 200 bereikt.', 'legendary'), (225, 'What Now?', '❔', 'Level 225 bereikt.', 'mythic'), (250, 'Final Boss', '🐉', 'Level 250 bereikt.', 'mythic')]),
        ("account_extra", "account", "account", "account_days", [(30, 'Fresh Account', '🪪', 'Discord-account is 30 dagen oud.', 'common'), (180, 'Settled Account', '📇', 'Discord-account is 180 dagen oud.', 'common'), (365, 'One Discord Year', '🎈', 'Discord-account is 1 jaar oud.', 'uncommon'), (730, 'Two Discord Years', '2️⃣', 'Discord-account is 2 jaar oud.', 'uncommon'), (1095, 'Discord Veteran', '🖥️', 'Discord-account is 3 jaar oud.', 'rare'), (1825, 'Old UI Survivor', '🪟', 'Discord-account is 5 jaar oud.', 'rare'), (2555, 'Seven Year Account', '7️⃣', 'Discord-account is 7 jaar oud.', 'epic'), (3650, 'Discord Decade', '🔟', 'Discord-account is 10 jaar oud.', 'legendary'), (4380, 'Ancient Account', '🏺', 'Discord-account is 12 jaar oud.', 'legendary'), (5475, 'Prehistoric Discord', '🦖', 'Discord-account is 15 jaar oud.', 'mythic')]),
        ("booster_extra", "boost", "community", "booster_days", [(7, 'Boost Week', '🚀', '7 dagen achter elkaar booster.', 'common'), (30, 'Boost Month', '💜', '30 dagen achter elkaar booster.', 'uncommon'), (90, 'Boost Quarter', '💎', '90 dagen achter elkaar booster.', 'rare'), (180, 'Boost Half Year', '🌌', '180 dagen achter elkaar booster.', 'rare'), (365, 'Boost Anniversary', '🎆', '1 jaar achter elkaar booster.', 'epic'), (730, 'Purple Patron', '👑', '2 jaar achter elkaar booster.', 'legendary'), (1095, 'Server Sponsor', '🏛️', '3 jaar achter elkaar booster.', 'legendary'), (1825, 'Boost Immortal', '♾️', '5 jaar achter elkaar booster.', 'mythic')]),
        ("waves_given_extra", "wavex", "social", "waves_given", [(3, 'Triple Wave', '👋', '3 nieuwe leden welkom geheten.', 'common'), (5, 'Door Greeter', '🚪', '5 nieuwe leden welkom geheten.', 'common'), (15, 'Friendly Regular', '🙂', '15 nieuwe leden welkom geheten.', 'uncommon'), (35, 'Front Desk', '🛎️', '35 nieuwe leden welkom geheten.', 'rare'), (75, 'Welcome Specialist', '🤝', '75 nieuwe leden welkom geheten.', 'epic'), (150, 'Professional Greeter', '🎩', '150 nieuwe leden welkom geheten.', 'legendary'), (250, 'Everyone Knows You', '🌍', '250 nieuwe leden welkom geheten.', 'mythic')]),
        ("waves_received_extra", "welcomed", "social", "waves_received", [(1, 'Warm Welcome', '🤗', 'Minimaal één keer welkom geheten.', 'common'), (5, 'Five High Fives', '🖐️', '5 welcomes ontvangen.', 'common'), (10, 'Known Arrival', '🎉', '10 welcomes ontvangen.', 'common'), (25, 'Crowd at the Door', '🚪', '25 welcomes ontvangen.', 'uncommon'), (50, 'Popular Entrance', '🎺', '50 welcomes ontvangen.', 'rare'), (75, 'Red Carpet', '🟥', '75 welcomes ontvangen.', 'rare'), (100, 'Big Entrance', '🌟', '100 welcomes ontvangen.', 'epic'), (150, 'Arrival Celebrity', '📸', '150 welcomes ontvangen.', 'epic'), (250, 'Grand Entrance', '🏰', '250 welcomes ontvangen.', 'legendary'), (500, 'The Whole Server Waved', '🌊', '500 welcomes ontvangen.', 'mythic')]),
        ("reactions_received_extra", "reactedx", "social", "reactions_received", [(1, 'First Reaction', '❤️', 'Je eerste geregistreerde reactie ontvangen.', 'common'), (25, 'Getting Reactions', '💟', '25 reacties ontvangen.', 'common'), (75, 'Likeable', '👍', '75 reacties ontvangen.', 'uncommon'), (150, 'Reaction Magnet', '🧲', '150 reacties ontvangen.', 'uncommon'), (350, 'Crowd Favorite', '🎭', '350 reacties ontvangen.', 'rare'), (750, 'Very Reactable', '💥', '750 reacties ontvangen.', 'epic'), (1500, 'Reaction Celebrity', '🌟', '1.500 reacties ontvangen.', 'legendary'), (2500, 'Emoji Economy', '💸', '2.500 reacties ontvangen.', 'mythic')]),
        ("reactions_given_extra", "reactorx", "social", "reactions_given", [(1, 'First React', '☝️', 'Je eerste geregistreerde reactie gegeven.', 'common'), (25, 'Quick React', '⚡', '25 reacties gegeven.', 'common'), (75, 'Emoji Regular', '🙂', '75 reacties gegeven.', 'uncommon'), (150, 'Reaction Supplier', '📦', '150 reacties gegeven.', 'uncommon'), (350, 'Emoji Department', '🏢', '350 reacties gegeven.', 'rare'), (750, 'Reaction Factory', '🏭', '750 reacties gegeven.', 'epic'), (1000, 'One Thousand Reactions', '1️⃣', '1.000 reacties gegeven.', 'legendary'), (2000, 'Emoji Overlord', '👑', '2.000 reacties gegeven.', 'mythic')]),
        ("invites_extra", "invitex", "social", "invites", [(2, 'Plus Two', '➕', '2 leden via jouw invites binnengebracht.', 'common'), (7, 'Friend Group Expansion', '🫂', '7 leden via jouw invites binnengebracht.', 'uncommon'), (15, 'Recruitment Drive', '📣', '15 leden via jouw invites binnengebracht.', 'rare'), (20, 'Growth Department', '📊', '20 leden via jouw invites binnengebracht.', 'epic'), (50, 'Community Architect', '🏗️', '50 leden via jouw invites binnengebracht.', 'legendary'), (100, 'Population Control', '🌆', '100 leden via jouw invites binnengebracht.', 'mythic')]),
        ("games_extra", "gamesx", "games", "games", [(2, 'Two Games', '🕹️', '2 actieve games gekozen.', 'common'), (3, 'Triple Queue', '🎮', '3 actieve games gekozen.', 'common'), (7, 'Lucky Seven Games', '7️⃣', '7 actieve games gekozen.', 'uncommon'), (15, 'Game Cabinet', '🗄️', '15 actieve games gekozen.', 'rare'), (25, 'Library Card', '📚', '25 actieve games gekozen.', 'rare'), (35, 'Do You Play Everything?', '🤨', '35 actieve games gekozen.', 'epic'), (40, 'No Genre Left Behind', '🌐', '40 actieve games gekozen.', 'legendary'), (50, 'Steam Sale Victim', '🛒', '50 actieve games gekozen.', 'mythic')]),
        ("genres_extra", "genresx", "games", "genres", [(2, 'Two Flavours', '🍦', '2 genres gekozen.', 'common'), (4, 'Genre Tourist', '🧳', '4 genres gekozen.', 'uncommon'), (6, 'Genre Collector', '🗂️', '6 genres gekozen.', 'rare'), (8, 'Play Anything', '🎲', '8 genres gekozen.', 'epic'), (10, 'Genre Singularity', '🌌', '10 genres gekozen.', 'legendary')]),
        ("extra_roles_extra", "roles", "roles", "extra_roles", [(1, 'More Than Games', '🎭', '1 algemene React Role gekozen.', 'common'), (2, 'Two Hats', '🎩', '2 algemene React Roles gekozen.', 'common'), (3, 'Community Layers', '🧅', '3 algemene React Roles gekozen.', 'uncommon'), (5, 'Role Enthusiast', '🏷️', '5 algemene React Roles gekozen.', 'rare'), (8, 'Identity Pack', '🎒', '8 algemene React Roles gekozen.', 'epic'), (10, 'Role Cabinet', '🗃️', '10 algemene React Roles gekozen.', 'legendary'), (15, 'Walking Role Menu', '📋', '15 algemene React Roles gekozen.', 'mythic')]),
        ("react_total_extra", "reactroles", "roles", "react_roles_total", [(3, 'React Roles Rookie', '🧩', '3 Games/Genres/Rollen samen gekozen.', 'common'), (5, 'Menu Explorer', '🧭', '5 Games/Genres/Rollen samen gekozen.', 'common'), (10, 'Personalised', '🎨', '10 React Roles samen gekozen.', 'uncommon'), (15, 'Role Loadout', '🛡️', '15 React Roles samen gekozen.', 'uncommon'), (20, 'Fully Equipped', '🎒', '20 React Roles samen gekozen.', 'rare'), (30, 'Role Collection', '🗂️', '30 React Roles samen gekozen.', 'epic'), (40, 'Role Hoarder', '📦', '40 React Roles samen gekozen.', 'legendary'), (50, 'Role Singularity', '🌀', '50 React Roles samen gekozen.', 'mythic')]),
        ("social_total_extra", "social", "social", "social_total", [(10, 'Social Starter', '🙂', '10 geregistreerde sociale interacties.', 'common'), (50, 'Around the Server', '🚶', '50 geregistreerde sociale interacties.', 'common'), (100, 'Social Regular', '🫂', '100 geregistreerde sociale interacties.', 'uncommon'), (250, 'Known Face', '😎', '250 geregistreerde sociale interacties.', 'uncommon'), (500, 'People Person', '🤝', '500 geregistreerde sociale interacties.', 'rare'), (1000, 'Social Butterfly', '🦋', '1.000 geregistreerde sociale interacties.', 'rare'), (2500, 'Community Pulse', '💓', '2.500 geregistreerde sociale interacties.', 'epic'), (5000, 'Server Socialite', '🥂', '5.000 geregistreerde sociale interacties.', 'legendary'), (10000, 'Everybody Knows You', '🌍', '10.000 geregistreerde sociale interacties.', 'legendary'), (25000, 'Social Infrastructure', '🌐', '25.000 geregistreerde sociale interacties.', 'mythic')]),
        ("collector_extra", "badges", "collector", "badges_owned", [(1, 'First Badge', '🏅', 'Je eerste badge verzameld.', 'common'), (5, 'Pocket Collection', '👝', '5 badges verzameld.', 'common'), (10, 'Badge Starter Pack', '🎒', '10 badges verzameld.', 'common'), (25, 'Badge Hunter', '🏹', '25 badges verzameld.', 'uncommon'), (50, 'Badge Shelf', '🗄️', '50 badges verzameld.', 'rare'), (75, 'Collector', '🧳', '75 badges verzameld.', 'rare'), (100, 'Triple Digits', '💯', '100 badges verzameld.', 'epic'), (150, 'Badge Museum', '🏛️', '150 badges verzameld.', 'legendary'), (200, 'Badge Archive', '🗃️', '200 badges verzameld.', 'legendary'), (250, 'Gotta Collect Them All', '🌟', '250 badges verzameld.', 'mythic')]),
    ]

    for set_index, (_, prefix, category, condition, rows) in enumerate(extra_sets, start=1):
        for index, (amount, name, emoji, description, rarity) in enumerate(rows):
            add(
                f"{prefix}_{amount}",
                name,
                emoji,
                description,
                category,
                rarity,
                condition,
                amount,
                sort_order=(set_index * 100) + index,
            )

    for index, (position, name, emoji, description, rarity) in enumerate([(8, 'Original Scale', '8️⃣', 'Momenteel bij de eerste 8 huidige leden op joinvolgorde.', 'mythic'), (10, 'First Ten', '🔟', 'Momenteel bij de eerste 10 huidige leden op joinvolgorde.', 'legendary'), (25, 'Early Twenty-Five', '🕰️', 'Momenteel bij de eerste 25 huidige leden op joinvolgorde.', 'epic'), (50, 'First Fifty', '🏁', 'Momenteel bij de eerste 50 huidige leden op joinvolgorde.', 'rare'), (75, 'Before the Crowd', '🚪', 'Momenteel bij de eerste 75 huidige leden op joinvolgorde.', 'uncommon')]):
        add(
            f"join_top_{position}",
            name,
            emoji,
            description,
            "history",
            rarity,
            "join_position",
            position,
            mode="dynamic",
            sort_order=3000 + index,
        )

    for index, (condition, rank, name, emoji, description, rarity) in enumerate([('rank_messages', 25, 'Top 25 Yapper', '📝', 'Momenteel top 25 op berichten.', 'rare'), ('rank_messages', 10, 'Top 10 Yapper', '🔟', 'Momenteel top 10 op berichten.', 'epic'), ('rank_messages', 5, 'Top 5 Yapper', '5️⃣', 'Momenteel top 5 op berichten.', 'legendary'), ('rank_voice', 25, 'Top 25 Voice', '🎧', 'Momenteel top 25 op voice-tijd.', 'rare'), ('rank_voice', 10, 'Top 10 Voice', '📻', 'Momenteel top 10 op voice-tijd.', 'epic'), ('rank_voice', 5, 'Top 5 Voice', '🎙️', 'Momenteel top 5 op voice-tijd.', 'legendary'), ('rank_xp', 25, 'Top 25 XP', '✨', 'Momenteel top 25 op XP.', 'rare'), ('rank_xp', 10, 'Top 10 XP', '💫', 'Momenteel top 10 op XP.', 'epic'), ('rank_xp', 5, 'Top 5 XP', '💎', 'Momenteel top 5 op XP.', 'legendary')]):
        add(
            f"{condition}_top_{rank}",
            name,
            emoji,
            description,
            "records",
            rarity,
            condition,
            rank,
            mode="dynamic",
            sort_order=3100 + index,
        )

    for index, (game_name, name, emoji, description, rarity) in enumerate([('Minecraft', 'Blockhead', '⛏️', 'Minecraft gekozen als game.', 'uncommon'), ('Project Zomboid', 'Knox County Resident', '🧟', 'Project Zomboid gekozen als game.', 'rare'), ('Valorant', 'Radiant-ish', '🎯', 'Valorant gekozen als game.', 'uncommon'), ('Dead by Daylight', 'Fog Dweller', '🪝', 'Dead by Daylight gekozen als game.', 'rare'), ('Rocket League', 'Calculated.', '🚗', 'Rocket League gekozen als game.', 'uncommon'), ('League of Legends', 'Summoner', '🌀', 'League of Legends gekozen als game.', 'uncommon'), ('Satisfactory', 'The Factory Must Grow', '🏭', 'Satisfactory gekozen als game.', 'rare'), ('Fortnite', 'Victory Royale?', '🪂', 'Fortnite gekozen als game.', 'uncommon'), ('Inazuma Eleven', 'Football Frontier', '⚡', 'Inazuma Eleven gekozen als game.', 'rare'), ('Pokémon', "Gotta Catch 'Em", '🔴', 'Pokémon gekozen als game.', 'rare'), ('Palworld', 'Pal Tamer', '🦊', 'Palworld gekozen als game.', 'uncommon')]):
        badge_id = (
            "game_"
            + "_".join(
                game_name.casefold()
                .replace("é", "e")
                .replace("ë", "e")
                .replace("'", "")
                .replace(".", "")
                .split()
            )
        )
        add(
            badge_id,
            name,
            emoji,
            description,
            "games",
            rarity,
            "has_game",
            game_name,
            sort_order=3200 + index,
        )

    for index, (badge_id, name, emoji, description, rarity, secret) in enumerate([('meetup_crew', 'Meetup Crew', '🤝', 'Aanwezig geweest bij een LEVENLOOS IRL-meetup.', 'rare', False), ('meetup_driver', 'Meetup Driver', '🚗', 'Mensen vervoerd naar een LEVENLOOS-meetup.', 'rare', False), ('meetup_host', 'Meetup Host', '🏠', 'Een LEVENLOOS-meetup gehost.', 'epic', False), ('game_server_host', 'Game Server Host', '🖥️', 'Een officiële LEVENLOOS-gameserver gehost.', 'epic', False), ('server_wizard', 'Dedicated Server Wizard', '🧙', 'Technisch beheer van een LEVENLOOS-gameserver gedaan.', 'legendary', False), ('modpack_architect', 'Modpack Architect', '🧱', 'Een gezamenlijke modpack/modcollectie gebouwd.', 'epic', False), ('bot_tester', 'Bot Tester', '🧪', 'Actief geholpen met het testen van de LEVENLOOS-bot.', 'rare', False), ('bug_hunter', 'Bug Hunter', '🐛', 'Een echte botbug gevonden en gemeld.', 'rare', False), ('bot_breaker', 'Bot Breaker', '🔨', 'De bot op een indrukwekkende manier kapot gekregen.', 'epic', True), ('meme_lord', 'Meme Lord', '😂', 'Officieel erkende meme-chaos veroorzaakt.', 'epic', False), ('meme_month', 'Meme of the Month', '🏆', 'Een Meme of the Month gewonnen.', 'rare', False), ('clip_month', 'Clip of the Month', '🎬', 'Een Clip of the Month gewonnen.', 'rare', False), ('screenshot_historian', 'Screenshot Historian', '📸', 'Iconische LEVENLOOS-momenten vastgelegd.', 'rare', False), ('community_helper', 'Community Helper', '🫶', 'Opvallend veel voor andere leden gedaan.', 'epic', False), ('voice_dj', 'Voice DJ', '🎵', 'De soundtrack van een memorabele voice-avond verzorgd.', 'uncommon', False), ('movie_night_host', 'Movie Night Host', '🍿', 'Een officiële Movie Night gehost.', 'rare', False), ('tournament_champion', 'Tournament Champion', '🏆', 'Een LEVENLOOS-toernooi gewonnen.', 'legendary', False), ('tournament_finalist', 'Tournament Finalist', '🥈', 'Een LEVENLOOS-toernooifinale bereikt.', 'epic', False), ('charity_crew', 'Charity Crew', '💜', 'Meegeholpen aan een LEVENLOOS-charityactie.', 'legendary', False), ('birthday_hero', 'Birthday Hero', '🎂', 'Een legendarische verjaardag op de server veroorzaakt.', 'rare', False), ('night_shift_crew', 'Night Shift Crew', '🌙', 'Onderdeel geweest van een memorabele nachtelijke sessie.', 'rare', False), ('early_adopter', 'Early Adopter', '🚀', 'Een nieuw LEVENLOOS-systeem vroeg getest/gebruikt.', 'uncommon', False), ('returning_legend', 'Returning Legend', '🔙', 'Na lange afwezigheid teruggekeerd alsof er niets gebeurd was.', 'epic', False), ('server_artist', 'Server Artist', '🎨', 'Artwork/design gemaakt voor LEVENLOOS.', 'epic', False), ('photographer', 'Photographer', '📷', "Officiële of iconische IRL-foto's gemaakt.", 'rare', False), ('chef_of_levenloos', 'Chef of LEVENLOOS', '👨\u200d🍳', 'De groep IRL van eten voorzien.', 'rare', False), ('roadtrip_crew', 'Roadtrip Crew', '🛣️', 'Mee geweest op een LEVENLOOS-roadtrip.', 'epic', False), ('lore_keeper', 'Lore Keeper', '📖', 'Kent te veel oude LEVENLOOS-lore.', 'legendary', False), ('chaos_coordinator', 'Chaos Coordinator', '🧨', 'Chaos georganiseerd die achteraf toch een goed idee bleek.', 'legendary', True), ('hall_of_fame', 'LEVENLOOS Hall of Fame', '🌌', 'Een van de meest bijzondere erkenningen binnen LEVENLOOS.', 'mythic', False)]):
        add(
            badge_id,
            name,
            emoji,
            description,
            "special",
            rarity,
            "manual",
            0,
            mode="manual",
            secret=secret,
            sort_order=3300 + index,
        )

    return badges




# =========================================================
# COMPONENTS V2 UI
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
        body = "\n".join(
            f"> └ {line}"
            for line in str(message).splitlines()
            if line.strip()
        )
        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"# {icon} {title or default_title}\n{body}"
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


class SimplePanelView(discord.ui.LayoutView):
    def __init__(
        self,
        body: str,
        *,
        accent: discord.Colour = BRAND_COLOR,
        timeout: float = 180,
    ):
        super().__init__(timeout=timeout)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(body),
                accent_colour=accent,
            )
        )


class BadgeImportModal(discord.ui.Modal):
    def __init__(self, cog: "Profile"):
        super().__init__(
            title="Profile • Badges importeren",
            timeout=600,
        )
        self.cog = cog
        self.lines = discord.ui.TextInput(
            label="Badges",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
            placeholder="1 badge per regel • gebruik het formaat uit /profile badge catalog",
        )
        self.add_item(self.lines)

    async def on_submit(self, interaction: discord.Interaction):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await self.cog.send_feedback(
                interaction,
                "Je hebt geen toegang tot badge-import.",
                kind="error",
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        added, errors = await self.cog.import_badge_text(str(self.lines.value))

        lines = [f"**{added}** badge-definities verwerkt."]
        if errors:
            lines.append(f"**{len(errors)}** regel(s) overgeslagen.")
            lines.extend(errors[:8])
            if len(errors) > 8:
                lines.append(f"… en {len(errors) - 8} meer.")

        await self.cog.send_feedback(
            interaction,
            "\n".join(lines),
            kind="warning" if errors else "success",
            title="Badge import",
        )


class OwnedLayoutView(discord.ui.LayoutView):
    def __init__(self, cog: "Profile", owner_id: int, *, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await self.cog.send_feedback(
            interaction,
            "Dit menu hoort bij iemand anders.",
            kind="error",
        )
        return False


class NavButton(discord.ui.Button):
    def __init__(
        self,
        owner_view,
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
        self.owner_view = owner_view
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.handle_action(interaction, self.action)


class BadgePagesView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Profile",
        owner_id: int,
        target: discord.Member,
        badges: list[dict],
        page: int = 0,
    ):
        super().__init__(cog, owner_id, timeout=600)
        self.target = target
        self.badges = badges
        self.page = page
        self.render()

    def render(self):
        self.clear_items()
        pages = max(1, math.ceil(len(self.badges) / BADGES_PER_PAGE))
        self.page = max(0, min(self.page, pages - 1))
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    self.cog.badges_text(
                        self.target,
                        self.badges,
                        self.page,
                    )
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    NavButton(
                        self,
                        "prev",
                        "Vorige",
                        emoji=PREVIOUS_EMOJI,
                        disabled=self.page <= 0,
                    ),
                    NavButton(
                        self,
                        "next",
                        "Volgende",
                        emoji=NEXT_EMOJI,
                        disabled=self.page >= pages - 1,
                    ),
                ),
                discord.ui.TextDisplay(
                    f"-# Pagina {self.page + 1}/{pages} • LEVENLOOS Badges"
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def handle_action(self, interaction: discord.Interaction, action: str):
        pages = max(1, math.ceil(len(self.badges) / BADGES_PER_PAGE))
        if action == "prev":
            self.page = max(0, self.page - 1)
        elif action == "next":
            self.page = min(pages - 1, self.page + 1)
        self.render()
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=self,
        )


class CollectionCategorySelect(discord.ui.Select):
    def __init__(self, owner_view: "BadgeCollectionView"):
        self.owner_view = owner_view
        available_categories = {
            str(item.get("category", "community"))
            for item in owner_view.entries
        }
        options = [
            discord.SelectOption(
                label="Alle categorieën",
                value="all",
                emoji=component_emoji(CATEGORY_EMOJIS["all"]),
                default=owner_view.category == "all",
            )
        ]
        for category, label in CATEGORY_LABELS.items():
            if category not in available_categories:
                continue
            options.append(
                discord.SelectOption(
                    label=truncate_component(label),
                    value=category,
                    emoji=component_emoji(CATEGORY_EMOJIS.get(category)),
                    default=owner_view.category == category,
                )
            )
        super().__init__(
            placeholder="Filter op categorie",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner_view.category = self.values[0]
        self.owner_view.page = 0
        self.owner_view.render()
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=self.owner_view,
        )


class CollectionStatusSelect(discord.ui.Select):
    def __init__(self, owner_view: "BadgeCollectionView"):
        self.owner_view = owner_view
        options = [
            discord.SelectOption(
                label="Te behalen",
                value="locked",
                description="Badges waar je nog naartoe kunt werken.",
                emoji=component_emoji(LOCK_EMOJI),
                default=owner_view.status == "locked",
            ),
            discord.SelectOption(
                label="Alles",
                value="all",
                description="Behaalde en nog niet behaalde badges.",
                emoji=component_emoji(BADGES_EMOJI),
                default=owner_view.status == "all",
            ),
            discord.SelectOption(
                label="Behaald",
                value="earned",
                description="Alle badges die al zijn vrijgespeeld.",
                emoji=component_emoji(SUCCESS_EMOJI),
                default=owner_view.status == "earned",
            ),
            discord.SelectOption(
                label="Dynamisch",
                value="dynamic",
                description="Rank- en recordbadges die kunnen wisselen.",
                emoji=component_emoji(REFRESH_EMOJI),
                default=owner_view.status == "dynamic",
            ),
            discord.SelectOption(
                label="Handmatig",
                value="manual",
                description="Speciale badges die admins kunnen toekennen.",
                emoji=component_emoji(EDIT_EMOJI),
                default=owner_view.status == "manual",
            ),
        ]
        super().__init__(
            placeholder="Welke badges wil je zien?",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner_view.status = self.values[0]
        self.owner_view.page = 0
        self.owner_view.render()
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=self.owner_view,
        )


class BadgeCollectionView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Profile",
        owner_id: int,
        target: discord.Member,
        entries: list[dict],
        *,
        category: str = "all",
        status: str = "locked",
        page: int = 0,
    ):
        super().__init__(cog, owner_id, timeout=900)
        self.target = target
        self.entries = entries
        self.category = category
        self.status = status
        self.page = page
        self.render()

    def filtered_entries(self) -> list[dict]:
        items = self.entries
        if self.category != "all":
            items = [
                item
                for item in items
                if item.get("category") == self.category
            ]
        if self.status == "locked":
            items = [
                item
                for item in items
                if not item.get("earned", False)
                and item.get("mode") != "manual"
            ]
        elif self.status == "earned":
            items = [item for item in items if item.get("earned", False)]
        elif self.status == "dynamic":
            items = [item for item in items if item.get("mode") == "dynamic"]
        elif self.status == "manual":
            items = [item for item in items if item.get("mode") == "manual"]
        return items

    def render(self):
        self.clear_items()
        filtered = self.filtered_entries()
        pages = max(1, math.ceil(len(filtered) / COLLECTION_BADGES_PER_PAGE))
        self.page = max(0, min(self.page, pages - 1))
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    self.cog.collection_text(
                        self.target,
                        self.entries,
                        self.category,
                        self.status,
                        self.page,
                    )
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(CollectionCategorySelect(self)),
                discord.ui.ActionRow(CollectionStatusSelect(self)),
                discord.ui.ActionRow(
                    NavButton(
                        self,
                        "prev",
                        "Vorige",
                        emoji=PREVIOUS_EMOJI,
                        disabled=self.page <= 0,
                    ),
                    NavButton(
                        self,
                        "refresh",
                        "Vernieuwen",
                        emoji=REFRESH_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    NavButton(
                        self,
                        "next",
                        "Volgende",
                        emoji=NEXT_EMOJI,
                        disabled=self.page >= pages - 1,
                    ),
                ),
                discord.ui.TextDisplay(
                    f"-# Pagina {self.page + 1}/{pages} • filters blijven actief"
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    async def handle_action(self, interaction: discord.Interaction, action: str):
        filtered = self.filtered_entries()
        pages = max(1, math.ceil(len(filtered) / COLLECTION_BADGES_PER_PAGE))
        if action == "prev":
            self.page = max(0, self.page - 1)
        elif action == "next":
            self.page = min(pages - 1, self.page + 1)
        elif action == "refresh":
            await interaction.response.defer()
            await self.cog.sync_member(self.target)
            self.entries = await self.cog.build_collection_entries(self.target)
            self.page = 0
            self.render()
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=self,
            )
            return

        self.render()
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=self,
        )


class ShowcaseSelect(discord.ui.Select):
    def __init__(
        self,
        owner_view: "ShowcaseView",
        badges: list[dict],
        current_ids: set[str],
    ):
        self.owner_view = owner_view
        options = [
            discord.SelectOption(
                label=truncate_component(badge["name"]),
                value=badge["badge_id"],
                description=truncate_component(
                    f"{RARITY_LABELS.get(badge['rarity'], badge['rarity'].title())} • {badge['description']}",
                    100,
                ),
                default=badge["badge_id"] in current_ids,
            )
            for badge in badges[:25]
        ]
        super().__init__(
            placeholder="Kies maximaal 6 showcase badges",
            min_values=0,
            max_values=min(SHOWCASE_SIZE, len(options)) if options else 1,
            options=options or [
                discord.SelectOption(
                    label="Geen badges beschikbaar",
                    value="__none__",
                )
            ],
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        selected = [
            value
            for value in self.values
            if value != "__none__"
        ][:SHOWCASE_SIZE]
        await self.owner_view.cog.set_showcase(
            interaction.guild.id,
            interaction.user.id,
            selected,
        )
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=FeedbackView(
                f"Showcase opgeslagen met **{len(selected)}** badge(s).",
                kind="success",
                title="Badge Case bijgewerkt",
            ),
        )


class ShowcaseView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Profile",
        owner_id: int,
        badges: list[dict],
        current_ids: set[str],
    ):
        super().__init__(cog, owner_id, timeout=300)
        note = (
            "> └ Je hebt meer dan 25 badges; de 25 zeldzaamste opties worden getoond."
            if len(badges) > 25
            else "> └ Kies maximaal 6 badges voor je paspoort."
        )
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {BADGES_EMOJI} Badge Case\n{note}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ShowcaseSelect(
                        self,
                        badges,
                        current_ids,
                    )
                ),
                accent_colour=BRAND_COLOR,
            )
        )


class TitleSelect(discord.ui.Select):
    def __init__(
        self,
        owner_view: "TitleView",
        badges: list[dict],
        current_id: str | None,
    ):
        self.owner_view = owner_view
        options = [
            discord.SelectOption(
                label="Geen titel",
                value="__none__",
                description="Verwijder de titel van je paspoort.",
                emoji=component_emoji(NONE_EMOJI),
                default=current_id is None,
            )
        ]
        for badge in badges[:24]:
            options.append(
                discord.SelectOption(
                    label=truncate_component(badge["name"]),
                    value=badge["badge_id"],
                    description=truncate_component(
                        f"{RARITY_LABELS.get(badge['rarity'], badge['rarity'].title())} • {badge['description']}",
                        100,
                    ),
                    default=badge["badge_id"] == current_id,
                )
            )
        super().__init__(
            placeholder="Kies je paspoorttitel",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        badge_id = None if value == "__none__" else value
        await self.owner_view.cog.set_title_badge(
            interaction.guild.id,
            interaction.user.id,
            badge_id,
        )
        await interaction.response.edit_message(
            content=None,
            embed=None,
            view=FeedbackView(
                "Paspoorttitel bijgewerkt.",
                kind="success",
                title="Titel opgeslagen",
            ),
        )


class TitleView(OwnedLayoutView):
    def __init__(
        self,
        cog: "Profile",
        owner_id: int,
        badges: list[dict],
        current_id: str | None,
    ):
        super().__init__(cog, owner_id, timeout=300)
        note = (
            "> └ Je hebt veel badges; de 24 zeldzaamste opties worden getoond."
            if len(badges) > 24
            else "> └ Kies één verdiende badge als titel onder je naam."
        )
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"# {EDIT_EMOJI} Paspoorttitel\n{note}"
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    TitleSelect(
                        self,
                        badges,
                        current_id,
                    )
                ),
                accent_colour=BRAND_COLOR,
            )
        )


class ProfileActionButton(discord.ui.Button):
    def __init__(
        self,
        owner_view: "ProfileView",
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

    async def callback(self, interaction: discord.Interaction):
        await self.owner_view.handle_action(interaction, self.action)


class ProfileView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Profile",
        target: discord.Member,
        requester_id: int,
        body: str,
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.target_id = target.id
        self.requester_id = requester_id

        header, details = body.split("\n---PROFILE_SPLIT---\n", 1)

        self.add_item(
            discord.ui.Container(
                discord.ui.Section(
                    discord.ui.TextDisplay(header),
                    accessory=discord.ui.Thumbnail(
                        str(target.display_avatar.url),
                        description=f"Profielfoto van {target.display_name}",
                    ),
                ),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(details),
                discord.ui.Separator(
                    visible=True,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.ActionRow(
                    ProfileActionButton(
                        self,
                        "earned",
                        "Behaald",
                        emoji=SUCCESS_EMOJI,
                        style=discord.ButtonStyle.primary,
                    ),
                    ProfileActionButton(
                        self,
                        "collection",
                        "Te behalen",
                        emoji=LOCK_EMOJI,
                        style=discord.ButtonStyle.success,
                    ),
                    ProfileActionButton(
                        self,
                        "showcase",
                        "Showcase",
                        emoji=BADGES_EMOJI,
                    ),
                    ProfileActionButton(
                        self,
                        "title",
                        "Titel",
                        emoji=EDIT_EMOJI,
                    ),
                    ProfileActionButton(
                        self,
                        "refresh",
                        "Vernieuwen",
                        emoji=REFRESH_EMOJI,
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# LEVENLOOS • Paspoort • badges kunnen eenmalig XP opleveren"
                ),
                accent_colour=BRAND_COLOR,
            )
        )

    @classmethod
    async def create(
        cls,
        cog: "Profile",
        target: discord.Member,
        requester_id: int,
    ):
        return cls(
            cog,
            target,
            requester_id,
            await cog.build_profile_text(target),
        )

    async def handle_action(self, interaction: discord.Interaction, action: str):
        if interaction.guild is None:
            return
        member = interaction.guild.get_member(self.target_id)
        if member is None:
            await self.cog.send_feedback(
                interaction,
                "Dit lid is niet meer beschikbaar.",
                kind="error",
            )
            return

        if action == "earned":
            badges = await self.cog.get_member_badges(
                interaction.guild.id,
                member.id,
            )
            await interaction.response.send_message(
                view=BadgePagesView(
                    self.cog,
                    interaction.user.id,
                    member,
                    badges,
                ),
                ephemeral=True,
            )
            return

        if action == "collection":
            await interaction.response.defer(ephemeral=True, thinking=True)
            await self.cog.sync_member(member)
            entries = await self.cog.build_collection_entries(member)
            await interaction.followup.send(
                view=BadgeCollectionView(
                    self.cog,
                    interaction.user.id,
                    member,
                    entries,
                    status="locked",
                ),
                ephemeral=True,
            )
            return

        if action == "showcase":
            if interaction.user.id != self.target_id:
                await self.cog.send_feedback(
                    interaction,
                    "Alleen de eigenaar van dit paspoort kan de showcase aanpassen.",
                    kind="error",
                )
                return
            await self.cog.open_showcase(interaction)
            return

        if action == "title":
            if interaction.user.id != self.target_id:
                await self.cog.send_feedback(
                    interaction,
                    "Alleen de eigenaar van dit paspoort kan de titel aanpassen.",
                    kind="error",
                )
                return
            await self.cog.open_title(interaction)
            return

        if action == "refresh":
            await interaction.response.defer()
            await self.cog.sync_member(member)
            new_view = await ProfileView.create(
                self.cog,
                member,
                self.requester_id,
            )
            await interaction.edit_original_response(
                content=None,
                embed=None,
                view=new_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )


# =========================================================
# PROFILE COG
# =========================================================


class Profile(commands.Cog):
    profile = app_commands.Group(
        name="profile",
        description="Bekijk LEVENLOOS-paspoorten en badges.",
    )

    badge = app_commands.Group(
        name="badge",
        description="Beheer profielbadges.",
        parent=profile,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sync_lock = asyncio.Lock()
        self._started = False
        self._badge_reward_migration = False
        self._reward_recalc_task: asyncio.Task | None = None

    async def cog_load(self):
        if not hasattr(discord.ui, "LayoutView"):
            raise RuntimeError(
                "Profile vereist discord.py 2.6+ voor Components V2."
            )

        await self.init_db()
        migration_pending = await self.seed_badges()

        if migration_pending:
            # Wacht op ready voordat we rollen herstellen na eventuele level-daling.
            self._reward_recalc_task = asyncio.create_task(
                self._run_pending_reward_recalculation()
            )

        if not self.auto_sync_loop.is_running():
            self.auto_sync_loop.start()
        logger.info("Profile-module geladen.")

    def cog_unload(self):
        if self.auto_sync_loop.is_running():
            self.auto_sync_loop.cancel()
        if self._reward_recalc_task is not None:
            self._reward_recalc_task.cancel()

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

    # =====================================================
    # DATABASE
    # =====================================================

    async def init_db(self):
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS profile_badge_definitions (
                    badge_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    emoji TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    rarity TEXT NOT NULL,
                    condition_type TEXT NOT NULL,
                    condition_value TEXT NOT NULL DEFAULT '0',
                    mode TEXT NOT NULL DEFAULT 'permanent',
                    reward_xp INTEGER NOT NULL DEFAULT 0,
                    secret INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_badges (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    badge_id TEXT NOT NULL,
                    awarded_at INTEGER NOT NULL,
                    manual INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, badge_id),
                    FOREIGN KEY (badge_id) REFERENCES profile_badge_definitions(badge_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS profile_showcase (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    badge_id TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, position)
                );

                CREATE TABLE IF NOT EXISTS profile_title (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    badge_id TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS profile_badge_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    badge_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_profile_badges_user
                    ON profile_badges(guild_id, user_id);

                CREATE INDEX IF NOT EXISTS idx_profile_history_time
                    ON profile_badge_history(guild_id, created_at);
                """
            )

            columns = {
                str(row[1])
                for row in await (
                    await db.execute("PRAGMA table_info(profile_badge_definitions)")
                ).fetchall()
            }
            if "reward_xp" not in columns:
                await db.execute(
                    "ALTER TABLE profile_badge_definitions "
                    "ADD COLUMN reward_xp INTEGER NOT NULL DEFAULT 0"
                )
                self._badge_reward_migration = True

            await db.commit()

    async def get_meta(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            row = await (
                await db.execute(
                    "SELECT value FROM profile_meta WHERE key=?",
                    (key,),
                )
            ).fetchone()
        return str(row[0]) if row else default

    async def set_meta(self, key: str, value: str) -> None:
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            await db.execute(
                """
                INSERT INTO profile_meta(key,value)
                VALUES (?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, str(value)),
            )
            await db.commit()

    async def seed_badges(self) -> bool:
        """
        Seed starterbadges en voer reward-schema-migraties uit.

        Returns True wanneer bestaande badge-XP opnieuw berekend moet worden.
        """
        starter = starter_badges()

        for definition in starter:
            await self.upsert_badge_definition(
                definition,
                overwrite=False,
            )

        try:
            current_version = int(
                await self.get_meta(
                    "badge_reward_scheme_version",
                    "0",
                )
                or 0
            )
        except ValueError:
            current_version = 0

        migration_pending = (
            self._badge_reward_migration
            or current_version < BADGE_REWARD_SCHEME_VERSION
        )

        if migration_pending:
            # Alleen de ingebouwde starterbadges krijgen automatisch de nieuwe
            # gebalanceerde reward. Eigen geïmporteerde badges blijven intact.
            async with aiosqlite.connect(PROFILE_DATABASE) as db:
                for definition in starter:
                    await db.execute(
                        """
                        UPDATE profile_badge_definitions
                        SET reward_xp=?, updated_at=?
                        WHERE badge_id=?
                        """,
                        (
                            max(0, int(definition.reward_xp)),
                            now_ts(),
                            definition.badge_id,
                        ),
                    )
                await db.commit()

            await self.set_meta(
                "badge_reward_recalc_pending",
                "1",
            )
            await self.set_meta(
                "badge_reward_scheme_version",
                str(BADGE_REWARD_SCHEME_VERSION),
            )

        pending = await self.get_meta(
            "badge_reward_recalc_pending",
            "0",
        )
        return pending == "1"

    async def import_badge_text(
        self,
        raw_text: str,
    ) -> tuple[int, list[str]]:
        """Importeer pipe-delimited badge-regels uit modal of tekstbestand."""
        added = 0
        errors: list[str] = []

        for line_number, raw in enumerate(
            str(raw_text).splitlines(),
            start=1,
        ):
            raw = raw.strip()

            if not raw or raw.startswith("#"):
                continue

            # Een meegeplakte kolomkop stil overslaan.
            if normalise_lookup(raw).startswith(
                "id | naam | emoji |"
            ):
                continue

            parts = [
                part.strip()
                for part in raw.split("|")
            ]

            if len(parts) not in {10, 11}:
                errors.append(
                    f"Regel {line_number}: verwacht 10 of 11 velden."
                )
                continue

            if len(parts) == 10:
                (
                    badge_id,
                    name,
                    emoji,
                    category,
                    rarity,
                    condition,
                    value,
                    mode,
                    secret_raw,
                    description,
                ) = parts
                reward_raw = ""
            else:
                (
                    badge_id,
                    name,
                    emoji,
                    category,
                    rarity,
                    condition,
                    value,
                    mode,
                    secret_raw,
                    reward_raw,
                    description,
                ) = parts

            badge_id = (
                badge_id
                .strip()
                .lower()
                .replace(" ", "_")[:64]
            )
            condition = condition.strip().lower()
            mode = normalise_mode(mode)
            rarity = normalise_rarity(rarity)
            secret = secret_raw.lower() in {
                "1",
                "yes",
                "ja",
                "true",
                "secret",
            }

            if (
                not badge_id
                or not name
                or condition not in SUPPORTED_CONDITIONS
            ):
                errors.append(
                    f"Regel {line_number}: ongeldige id/naam/condition."
                )
                continue

            if mode == "manual" or condition == "manual":
                mode = "manual"
                condition = "manual"

            try:
                reward_xp = (
                    calculated_badge_xp(
                        rarity,
                        mode,
                        condition,
                    )
                    if not reward_raw
                    else max(
                        0,
                        int(
                            reward_raw
                            .replace(".", "")
                            .replace(",", "")
                        ),
                    )
                )
            except ValueError:
                errors.append(
                    f"Regel {line_number}: XP moet een heel getal zijn."
                )
                continue

            if mode == "dynamic":
                reward_xp = 0

            try:
                await self.upsert_badge_definition(
                    BadgeDefinition(
                        badge_id=badge_id,
                        name=name[:80],
                        emoji=emoji[:100] or "🏅",
                        description=description[:300],
                        category=normalise_category(category),
                        rarity=rarity,
                        condition_type=condition,
                        condition_value=value[:100],
                        mode=mode,
                        reward_xp=reward_xp,
                        secret=secret,
                    ),
                    overwrite=True,
                )
                added += 1
            except Exception as exc:
                errors.append(
                    f"Regel {line_number}: "
                    f"{type(exc).__name__}: {exc}"
                )

        return added, errors

    async def upsert_badge_definition(self, definition: BadgeDefinition, *, overwrite: bool):
        timestamp = now_ts()
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            if overwrite:
                await db.execute(
                    """
                    INSERT INTO profile_badge_definitions (
                        badge_id,name,emoji,description,category,rarity,
                        condition_type,condition_value,mode,reward_xp,secret,sort_order,
                        enabled,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
                    ON CONFLICT(badge_id) DO UPDATE SET
                        name=excluded.name,
                        emoji=excluded.emoji,
                        description=excluded.description,
                        category=excluded.category,
                        rarity=excluded.rarity,
                        condition_type=excluded.condition_type,
                        condition_value=excluded.condition_value,
                        mode=excluded.mode,
                        reward_xp=excluded.reward_xp,
                        secret=excluded.secret,
                        sort_order=excluded.sort_order,
                        enabled=1,
                        updated_at=excluded.updated_at
                    """,
                    (
                        definition.badge_id,
                        definition.name,
                        definition.emoji,
                        definition.description,
                        definition.category,
                        definition.rarity,
                        definition.condition_type,
                        definition.condition_value,
                        definition.mode,
                        max(0, int(definition.reward_xp)),
                        int(definition.secret),
                        definition.sort_order,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO profile_badge_definitions (
                        badge_id,name,emoji,description,category,rarity,
                        condition_type,condition_value,mode,reward_xp,secret,sort_order,
                        enabled,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
                    """,
                    (
                        definition.badge_id,
                        definition.name,
                        definition.emoji,
                        definition.description,
                        definition.category,
                        definition.rarity,
                        definition.condition_type,
                        definition.condition_value,
                        definition.mode,
                        max(0, int(definition.reward_xp)),
                        int(definition.secret),
                        definition.sort_order,
                        timestamp,
                        timestamp,
                    ),
                )
            await db.commit()

    async def get_definitions(self, *, include_disabled: bool = False) -> list[dict]:
        query = "SELECT badge_id,name,emoji,description,category,rarity,condition_type,condition_value,mode,reward_xp,secret,sort_order,enabled FROM profile_badge_definitions"
        if not include_disabled:
            query += " WHERE enabled = 1"
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(query)).fetchall()
        return [dict(row) for row in rows]

    async def get_member_badges(self, guild_id: int, user_id: int) -> list[dict]:
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            db.row_factory = aiosqlite.Row
            rows = await (
                await db.execute(
                    """
                    SELECT d.*, b.awarded_at, b.manual
                    FROM profile_badges b
                    JOIN profile_badge_definitions d ON d.badge_id = b.badge_id
                    WHERE b.guild_id = ? AND b.user_id = ? AND d.enabled = 1
                    """,
                    (guild_id, user_id),
                )
            ).fetchall()
        result = [dict(row) for row in rows]
        result.sort(key=badge_sort_key)
        return result

    async def get_showcase(self, guild_id: int, user_id: int) -> list[str]:
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            rows = await (
                await db.execute(
                    "SELECT badge_id FROM profile_showcase WHERE guild_id=? AND user_id=? ORDER BY position ASC",
                    (guild_id, user_id),
                )
            ).fetchall()
        return [row[0] for row in rows]

    async def set_showcase(self, guild_id: int, user_id: int, badge_ids: list[str]):
        owned = {badge["badge_id"] for badge in await self.get_member_badges(guild_id, user_id)}
        badge_ids = [badge_id for badge_id in badge_ids if badge_id in owned][:SHOWCASE_SIZE]
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            await db.execute("DELETE FROM profile_showcase WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            for position, badge_id in enumerate(badge_ids, start=1):
                await db.execute(
                    "INSERT INTO profile_showcase(guild_id,user_id,position,badge_id) VALUES (?,?,?,?)",
                    (guild_id, user_id, position, badge_id),
                )
            await db.commit()

    async def get_title_badge_id(self, guild_id: int, user_id: int) -> str | None:
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            row = await (
                await db.execute(
                    "SELECT badge_id FROM profile_title WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
            ).fetchone()
        return str(row[0]) if row else None

    async def set_title_badge(self, guild_id: int, user_id: int, badge_id: str | None):
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            if badge_id is None:
                await db.execute(
                    "DELETE FROM profile_title WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
            else:
                owned = await db.execute(
                    "SELECT 1 FROM profile_badges WHERE guild_id=? AND user_id=? AND badge_id=?",
                    (guild_id, user_id, badge_id),
                )
                if await owned.fetchone() is None:
                    raise ValueError("Badge is niet in bezit")
                await db.execute(
                    """
                    INSERT INTO profile_title(guild_id,user_id,badge_id) VALUES (?,?,?)
                    ON CONFLICT(guild_id,user_id) DO UPDATE SET badge_id=excluded.badge_id
                    """,
                    (guild_id, user_id, badge_id),
                )
            await db.commit()

    async def grant_badge(self, guild_id: int, user_id: int, badge_id: str, *, manual: bool = False) -> bool:
        timestamp = now_ts()
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO profile_badges(guild_id,user_id,badge_id,awarded_at,manual) VALUES (?,?,?,?,?)",
                (guild_id, user_id, badge_id, timestamp, int(manual)),
            )
            added = cursor.rowcount > 0
            if added:
                await db.execute(
                    "INSERT INTO profile_badge_history(guild_id,user_id,badge_id,action,created_at) VALUES (?,?,?,?,?)",
                    (guild_id, user_id, badge_id, "earned", timestamp),
                )
            await db.commit()
        return added

    async def recalculate_awarded_badge_xp(
        self,
        *,
        guild_id: int | None = None,
        user_id: int | None = None,
        repair_progress_badges: bool = True,
    ) -> dict:
        """
        Maak bestaande `source=badge` XP exact gelijk aan de huidige badge-reward.

        Dit corrigeert dus ook XP die al met de oude, veel te hoge schaal is
        uitgedeeld. Custom badges worden alleen aangepast als hun huidige
        definitie een andere reward heeft dan wat in levels_xp_log staat.
        """
        result = {
            "logs_checked": 0,
            "logs_changed": 0,
            "users_changed": 0,
            "xp_removed": 0,
            "xp_added": 0,
            "progress_badges_removed": 0,
        }

        if not LEVELS_DATABASE.exists():
            return result

        definitions = {
            row["badge_id"]: row
            for row in await self.get_definitions(
                include_disabled=True
            )
        }

        query = """
            SELECT id,guild_id,user_id,xp,reference_id
            FROM levels_xp_log
            WHERE source='badge'
        """
        params: list[int] = []

        if guild_id is not None:
            query += " AND guild_id=?"
            params.append(int(guild_id))

        if user_id is not None:
            query += " AND user_id=?"
            params.append(int(user_id))

        changed_users: dict[tuple[int, int], int] = {}

        async with aiosqlite.connect(LEVELS_DATABASE) as db:
            rows = await (
                await db.execute(
                    query,
                    tuple(params),
                )
            ).fetchall()

            for (
                log_id,
                row_guild_id,
                row_user_id,
                old_xp,
                reference_id,
            ) in rows:
                result["logs_checked"] += 1

                reference = str(reference_id or "")
                prefix = f"badge:{int(row_user_id)}:"

                if not reference.startswith(prefix):
                    continue

                badge_id = reference[len(prefix):]
                definition = definitions.get(badge_id)

                # Een verwijderde/onbekende custom badge laten we ongemoeid.
                if definition is None:
                    continue

                desired = max(
                    0,
                    int(definition.get("reward_xp", 0) or 0),
                )
                if definition.get("mode") == "dynamic":
                    desired = 0

                old_xp = int(old_xp or 0)
                delta = desired - old_xp

                if delta == 0:
                    continue

                await db.execute(
                    "UPDATE levels_xp_log SET xp=? WHERE id=?",
                    (desired, int(log_id)),
                )

                key = (
                    int(row_guild_id),
                    int(row_user_id),
                )
                changed_users[key] = (
                    changed_users.get(key, 0)
                    + delta
                )
                result["logs_changed"] += 1

                if delta < 0:
                    result["xp_removed"] += -delta
                else:
                    result["xp_added"] += delta

            for (
                row_guild_id,
                row_user_id,
            ), delta in changed_users.items():
                row = await (
                    await db.execute(
                        """
                        SELECT total_xp
                        FROM levels_users
                        WHERE guild_id=? AND user_id=?
                        """,
                        (
                            row_guild_id,
                            row_user_id,
                        ),
                    )
                ).fetchone()

                if row is None:
                    continue

                new_total = max(
                    0,
                    int(row[0] or 0) + int(delta),
                )

                await db.execute(
                    """
                    UPDATE levels_users
                    SET total_xp=?, updated_at=?
                    WHERE guild_id=? AND user_id=?
                    """,
                    (
                        new_total,
                        now_ts(),
                        row_guild_id,
                        row_user_id,
                    ),
                )

            await db.commit()

        result["users_changed"] = len(changed_users)

        if repair_progress_badges and changed_users:
            repaired = await self.repair_progress_badges(
                set(changed_users),
                definitions,
            )
            result["progress_badges_removed"] = repaired[
                "badges_removed"
            ]
            result["xp_removed"] += repaired["xp_removed"]

            changed_users.update(
                {
                    key: changed_users.get(key, 0)
                    for key in repaired["affected_users"]
                }
            )
            result["users_changed"] = len(changed_users)

        # Als levels omlaag zijn gegaan kunnen oude levelrollen nog staan.
        levels = self.bot.get_cog("Levels")
        if levels is not None and hasattr(levels, "apply_level_roles"):
            for changed_guild_id, changed_user_id in changed_users:
                guild = self.bot.get_guild(changed_guild_id)
                member = (
                    guild.get_member(changed_user_id)
                    if guild is not None
                    else None
                )
                if member is None:
                    continue
                try:
                    await levels.apply_level_roles(member)
                except Exception as exc:
                    logger.exception(
                        "Levelrol herstellen mislukt voor %s/%s: %s",
                        changed_guild_id,
                        changed_user_id,
                        exc,
                    )

        return result

    async def repair_progress_badges(
        self,
        affected_users: set[tuple[int, int]],
        definitions: dict[str, dict],
    ) -> dict:
        """
        Verwijder XP/level/collector-badges die uitsluitend door de oude
        overbetaling haalbaar waren geworden.

        De bijbehorende XP-log wordt verwijderd zodat de badge later opnieuw
        normaal verdiend kan worden.
        """
        result = {
            "badges_removed": 0,
            "xp_removed": 0,
            "affected_users": set(),
        }

        repair_conditions = {
            "xp",
            "level",
            "badges_owned",
        }

        for guild_id, user_id in affected_users:
            guild = self.bot.get_guild(guild_id)
            member = (
                guild.get_member(user_id)
                if guild is not None
                else None
            )

            # Alleen actuele serverleden kunnen we betrouwbaar tegen hun
            # huidige profielconditions toetsen.
            if member is None:
                continue

            # Maximaal enkele passes, omdat het verwijderen van een progress-
            # badge weer een collector-badge ongeldig kan maken.
            for _ in range(10):
                cache = await self.build_guild_cache(guild)
                metrics = self.metrics_for_member(
                    member,
                    cache,
                )
                owned = {
                    badge["badge_id"]: badge
                    for badge in await self.get_member_badges(
                        guild_id,
                        user_id,
                    )
                }
                metrics["badges_owned"] = len(owned)

                invalid: list[dict] = []
                for badge_id, owned_badge in owned.items():
                    definition = definitions.get(
                        badge_id,
                        owned_badge,
                    )

                    if bool(owned_badge.get("manual", 0)):
                        continue
                    if definition.get("mode") != "permanent":
                        continue
                    if (
                        definition.get("condition_type")
                        not in repair_conditions
                    ):
                        continue
                    if self.qualifies(definition, metrics):
                        continue

                    invalid.append(definition)

                if not invalid:
                    break

                removed_in_pass = 0

                for definition in invalid:
                    badge_id = definition["badge_id"]
                    reference_id = (
                        f"badge:{user_id}:{badge_id}"
                    )

                    logged_xp = 0
                    async with aiosqlite.connect(
                        LEVELS_DATABASE
                    ) as levels_db:
                        row = await (
                            await levels_db.execute(
                                """
                                SELECT id,xp
                                FROM levels_xp_log
                                WHERE guild_id=?
                                  AND user_id=?
                                  AND source='badge'
                                  AND reference_id=?
                                """,
                                (
                                    guild_id,
                                    user_id,
                                    reference_id,
                                ),
                            )
                        ).fetchone()

                        if row is not None:
                            log_id, logged_xp = row
                            logged_xp = max(
                                0,
                                int(logged_xp or 0),
                            )

                            await levels_db.execute(
                                "DELETE FROM levels_xp_log WHERE id=?",
                                (int(log_id),),
                            )

                            current = await (
                                await levels_db.execute(
                                    """
                                    SELECT total_xp
                                    FROM levels_users
                                    WHERE guild_id=? AND user_id=?
                                    """,
                                    (
                                        guild_id,
                                        user_id,
                                    ),
                                )
                            ).fetchone()

                            if current is not None and logged_xp:
                                await levels_db.execute(
                                    """
                                    UPDATE levels_users
                                    SET total_xp=?, updated_at=?
                                    WHERE guild_id=? AND user_id=?
                                    """,
                                    (
                                        max(
                                            0,
                                            int(current[0] or 0)
                                            - logged_xp,
                                        ),
                                        now_ts(),
                                        guild_id,
                                        user_id,
                                    ),
                                )

                            await levels_db.commit()

                    removed = await self.revoke_badge(
                        guild_id,
                        user_id,
                        badge_id,
                        allow_manual=False,
                    )

                    if removed:
                        removed_in_pass += 1
                        result["badges_removed"] += 1
                        result["xp_removed"] += logged_xp
                        result["affected_users"].add(
                            (guild_id, user_id)
                        )

                if removed_in_pass == 0:
                    break

        return result

    async def _run_pending_reward_recalculation(self) -> None:
        try:
            await self.bot.wait_until_ready()
            result = await self.recalculate_awarded_badge_xp()
            await self.set_meta(
                "badge_reward_recalc_pending",
                "0",
            )
            logger.info(
                "Profile XP migratie: %s users • -%s XP • +%s XP • %s progress badges repaired",
                result["users_changed"],
                result["xp_removed"],
                result["xp_added"],
                result["progress_badges_removed"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Pending blijft 1 zodat een volgende restart opnieuw kan proberen.
            logger.exception(
                "Profile XP migratie mislukt: %s",
                exc,
            )

    async def reward_badge_xp(
        self,
        guild: discord.Guild,
        user_id: int,
        definition: dict,
    ) -> int:
        """Geef badge-XP exact één keer via Levels."""
        if str(definition.get("mode", "permanent")) == "dynamic":
            return 0

        try:
            amount = max(0, int(definition.get("reward_xp", 0) or 0))
        except (TypeError, ValueError):
            return 0

        if amount <= 0:
            return 0

        levels = self.bot.get_cog("Levels")
        if levels is None or not hasattr(levels, "award_xp"):
            return 0

        reference_id = f"badge:{user_id}:{definition['badge_id']}"

        try:
            return int(
                await levels.award_xp(
                    guild,
                    user_id,
                    amount,
                    "badge",
                    reference_id,
                    None,
                )
                or 0
            )
        except Exception as exc:
            logger.exception(
                "Badge XP uitbetalen mislukt voor %s/%s/%s: %s",
                guild.id,
                user_id,
                definition.get("badge_id"),
                exc,
            )
            return 0

    async def revoke_badge(self, guild_id: int, user_id: int, badge_id: str, *, allow_manual: bool = False) -> bool:
        timestamp = now_ts()
        async with aiosqlite.connect(PROFILE_DATABASE) as db:
            if allow_manual:
                cursor = await db.execute(
                    "DELETE FROM profile_badges WHERE guild_id=? AND user_id=? AND badge_id=?",
                    (guild_id, user_id, badge_id),
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM profile_badges WHERE guild_id=? AND user_id=? AND badge_id=? AND manual=0",
                    (guild_id, user_id, badge_id),
                )
            removed = cursor.rowcount > 0
            if removed:
                await db.execute(
                    "DELETE FROM profile_showcase WHERE guild_id=? AND user_id=? AND badge_id=?",
                    (guild_id, user_id, badge_id),
                )
                await db.execute(
                    "DELETE FROM profile_title WHERE guild_id=? AND user_id=? AND badge_id=?",
                    (guild_id, user_id, badge_id),
                )
                await db.execute(
                    "INSERT INTO profile_badge_history(guild_id,user_id,badge_id,action,created_at) VALUES (?,?,?,?,?)",
                    (guild_id, user_id, badge_id, "lost", timestamp),
                )
            await db.commit()
        return removed

    # =====================================================
    # DATA COLLECTION
    # =====================================================

    async def build_guild_cache(self, guild: discord.Guild) -> dict:
        cache = {
            "levels": {},
            "rank_xp": {},
            "rank_messages": {},
            "rank_voice": {},
            "ranked_members": 0,
            "waves_given": {},
            "waves_received": {},
            "reactions_given": {},
            "reactions_received": {},
            "invites": {},
            "birthday_users": set(),
            "react_roles": {"game": set(), "genre": set(), "role": set()},
            "react_role_names": {"game": {}, "genre": {}, "role": {}},
            "join_position": {},
        }

        human_members = [member for member in guild.members if not member.bot]
        joined_members = sorted(
            [member for member in human_members if member.joined_at is not None],
            key=lambda member: member.joined_at,
        )
        cache["join_position"] = {member.id: index for index, member in enumerate(joined_members, start=1)}

        if LEVELS_DATABASE.exists():
            async with aiosqlite.connect(LEVELS_DATABASE) as db:
                rows = await (
                    await db.execute(
                        "SELECT user_id,total_xp,text_messages,voice_seconds FROM levels_users WHERE guild_id=?",
                        (guild.id,),
                    )
                ).fetchall()
                for user_id, xp, messages, voice_seconds in rows:
                    cache["levels"][int(user_id)] = {
                        "xp": int(xp or 0),
                        "messages": int(messages or 0),
                        "voice_seconds": int(voice_seconds or 0),
                    }

                for key, column in (("rank_xp", "total_xp"), ("rank_messages", "text_messages"), ("rank_voice", "voice_seconds")):
                    ranked_rows = await (
                        await db.execute(
                            f"SELECT user_id FROM levels_users WHERE guild_id=? ORDER BY {column} DESC,total_xp DESC,user_id ASC",
                            (guild.id,),
                        )
                    ).fetchall()
                    current_ids = {member.id for member in human_members}
                    filtered = [int(row[0]) for row in ranked_rows if int(row[0]) in current_ids]
                    cache[key] = {user_id: index for index, user_id in enumerate(filtered, start=1)}
                    cache["ranked_members"] = max(cache["ranked_members"], len(filtered))

                try:
                    rows = await (
                        await db.execute(
                            "SELECT reactor_id,COUNT(*) FROM levels_reaction_awards WHERE guild_id=? GROUP BY reactor_id",
                            (guild.id,),
                        )
                    ).fetchall()
                    cache["reactions_given"] = {int(uid): int(amount) for uid, amount in rows}

                    rows = await (
                        await db.execute(
                            "SELECT author_id,COUNT(*) FROM levels_reaction_awards WHERE guild_id=? GROUP BY author_id",
                            (guild.id,),
                        )
                    ).fetchall()
                    cache["reactions_received"] = {int(uid): int(amount) for uid, amount in rows}
                except aiosqlite.OperationalError:
                    pass

                try:
                    rows = await (
                        await db.execute(
                            "SELECT user_id,COUNT(*) FROM levels_xp_log WHERE guild_id=? AND source='invite' AND xp>0 GROUP BY user_id",
                            (guild.id,),
                        )
                    ).fetchall()
                    cache["invites"] = {int(uid): int(amount) for uid, amount in rows}
                except aiosqlite.OperationalError:
                    pass

        if LEVENLOOS_DATABASE.exists():
            async with aiosqlite.connect(LEVENLOOS_DATABASE) as db:
                try:
                    rows = await (
                        await db.execute(
                            "SELECT waving_user_id,COUNT(*) FROM welcome_waves WHERE guild_id=? GROUP BY waving_user_id",
                            (guild.id,),
                        )
                    ).fetchall()
                    cache["waves_given"] = {int(uid): int(amount) for uid, amount in rows}
                    rows = await (
                        await db.execute(
                            "SELECT welcomed_member_id,COUNT(*) FROM welcome_waves WHERE guild_id=? GROUP BY welcomed_member_id",
                            (guild.id,),
                        )
                    ).fetchall()
                    cache["waves_received"] = {int(uid): int(amount) for uid, amount in rows}
                except aiosqlite.OperationalError:
                    pass

                try:
                    rows = await (
                        await db.execute(
                            "SELECT section,role_id,item_group,button_name FROM react_items WHERE guild_id=?",
                            (guild.id,),
                        )
                    ).fetchall()
                    for section, role_id, item_group, button_name in rows:
                        section = str(section)
                        role_id = int(role_id)
                        lookup_name = normalise_lookup(button_name)
                        if section == "game":
                            cache["react_roles"]["game"].add(role_id)
                            cache["react_role_names"]["game"][role_id] = lookup_name
                        elif section == "genre":
                            cache["react_roles"]["genre"].add(role_id)
                            cache["react_role_names"]["genre"][role_id] = lookup_name
                        elif section == "role" and str(item_group) == "roles":
                            cache["react_roles"]["role"].add(role_id)
                            cache["react_role_names"]["role"][role_id] = lookup_name
                except aiosqlite.OperationalError:
                    pass

        if BIRTHDAYS_DATABASE.exists():
            async with aiosqlite.connect(BIRTHDAYS_DATABASE) as db:
                try:
                    rows = await (
                        await db.execute("SELECT user_id FROM birthdays WHERE guild_id=?", (guild.id,))
                    ).fetchall()
                    cache["birthday_users"] = {int(row[0]) for row in rows}
                except aiosqlite.OperationalError:
                    pass

        return cache

    def metrics_for_member(self, member: discord.Member, cache: dict) -> dict:
        levels = cache["levels"].get(member.id, {})
        role_ids = {role.id for role in member.roles}
        joined_at = member.joined_at
        member_days = 0
        if joined_at is not None:
            member_days = max(0, int((datetime.now(timezone.utc) - joined_at).total_seconds() // 86400))

        xp = int(levels.get("xp", 0))
        waves_given = int(cache["waves_given"].get(member.id, 0))
        waves_received = int(cache["waves_received"].get(member.id, 0))
        reactions_given = int(cache["reactions_given"].get(member.id, 0))
        reactions_received = int(cache["reactions_received"].get(member.id, 0))
        invites = int(cache["invites"].get(member.id, 0))

        game_ids = role_ids & cache["react_roles"]["game"]
        genre_ids = role_ids & cache["react_roles"]["genre"]
        profile_role_ids = role_ids & cache["react_roles"]["role"]

        account_days = max(
            0,
            int(
                (
                    datetime.now(timezone.utc)
                    - member.created_at
                ).total_seconds()
                // 86400
            ),
        )

        booster_days = 0
        if member.premium_since is not None:
            booster_days = max(
                0,
                int(
                    (
                        datetime.now(timezone.utc)
                        - member.premium_since
                    ).total_seconds()
                    // 86400
                ),
            )

        games = len(game_ids)
        genres = len(genre_ids)
        extra_roles = len(profile_role_ids)

        return {
            "messages": int(levels.get("messages", 0)),
            "voice_hours": float(levels.get("voice_seconds", 0)) / 3600,
            "voice_seconds": int(levels.get("voice_seconds", 0)),
            "xp": xp,
            "level": level_from_xp(xp),
            "member_days": member_days,
            "account_days": account_days,
            "booster_days": booster_days,
            "waves_given": waves_given,
            "waves_received": waves_received,
            "reactions_given": reactions_given,
            "reactions_received": reactions_received,
            "invites": invites,
            "games": games,
            "genres": genres,
            "extra_roles": extra_roles,
            "total_roles": max(0, len(member.roles) - 1),
            "react_roles_total": games + genres + extra_roles,
            "social_total": (
                waves_given
                + waves_received
                + reactions_given
                + reactions_received
                + invites
            ),
            "birthday_registered": 1 if member.id in cache["birthday_users"] else 0,
            "booster": 1 if member.premium_since is not None else 0,
            "rank_messages": int(cache["rank_messages"].get(member.id, 0)),
            "rank_voice": int(cache["rank_voice"].get(member.id, 0)),
            "rank_xp": int(cache["rank_xp"].get(member.id, 0)),
            "join_position": int(cache["join_position"].get(member.id, 0)),
            "role_ids": role_ids,
            "game_names": {
                cache["react_role_names"]["game"].get(role_id, "")
                for role_id in game_ids
            },
            "genre_names": {
                cache["react_role_names"]["genre"].get(role_id, "")
                for role_id in genre_ids
            },
            "profile_role_names": {
                cache["react_role_names"]["role"].get(role_id, "")
                for role_id in profile_role_ids
            },
            "badges_owned": 0,
            "ranked_members": int(cache["ranked_members"]),
        }

    def qualifies(self, definition: dict, metrics: dict) -> bool:
        condition = definition["condition_type"]
        raw_value = str(definition.get("condition_value", "0"))

        if condition == "manual":
            return False

        if condition == "has_role":
            try:
                return int(raw_value) in metrics["role_ids"]
            except ValueError:
                return False

        named_role_conditions = {
            "has_game": "game_names",
            "has_genre": "genre_names",
            "has_profile_role": "profile_role_names",
        }
        if condition in named_role_conditions:
            wanted = normalise_lookup(raw_value)
            return wanted in metrics.get(
                named_role_conditions[condition],
                set(),
            )

        if condition in {"birthday_registered", "booster"}:
            try:
                threshold = float(raw_value or 1)
            except ValueError:
                threshold = 1
            return float(metrics.get(condition, 0)) >= threshold

        if condition in {"rank_messages", "rank_voice", "rank_xp", "join_position"}:
            try:
                threshold = int(float(raw_value))
            except ValueError:
                return False
            current = int(metrics.get(condition, 0))
            return current > 0 and current <= threshold

        try:
            threshold = float(raw_value)
            current = float(metrics.get(condition, 0))
        except (ValueError, TypeError):
            return False
        return current >= threshold

    def _collection_number(
        self,
        value: int | float,
        *,
        decimals: int = 0,
    ) -> str:
        if decimals:
            text = f"{float(value):,.{decimals}f}"
            return (
                text
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
        return fmt_number(int(value))

    def collection_progress(
        self,
        definition: dict,
        metrics: dict,
        *,
        earned: bool,
    ) -> dict:
        condition = str(
            definition.get("condition_type", "")
        )
        raw_value = str(
            definition.get("condition_value", "0")
        )

        if bool(definition.get("secret")) and not earned:
            return {
                "text": "Voorwaarde verborgen.",
                "ratio": None,
                "goal": None,
            }

        if condition == "manual":
            return {
                "text": "Speciale badge • wordt handmatig door een admin toegekend.",
                "ratio": None,
                "goal": "Handmatig",
            }

        named_conditions = {
            "has_game": (
                "game_names",
                "Kies **{value}** bij Games in React Roles.",
            ),
            "has_genre": (
                "genre_names",
                "Kies **{value}** bij Genres in React Roles.",
            ),
            "has_profile_role": (
                "profile_role_names",
                "Kies **{value}** bij Rollen in React Roles.",
            ),
        }

        if condition in named_conditions:
            metric_key, message = named_conditions[condition]
            wanted = normalise_lookup(raw_value)
            has_it = wanted in metrics.get(metric_key, set())
            return {
                "text": (
                    "Vereiste React Role gekozen."
                    if has_it
                    else message.format(value=raw_value)
                ),
                "ratio": 1.0 if has_it else 0.0,
                "goal": raw_value,
            }

        if condition == "has_role":
            try:
                role_id = int(raw_value)
            except ValueError:
                role_id = 0

            has_it = (
                role_id > 0
                and role_id in metrics.get("role_ids", set())
            )
            return {
                "text": (
                    "Vereiste serverrol aanwezig."
                    if has_it
                    else "Verkrijg de vereiste serverrol."
                ),
                "ratio": 1.0 if has_it else 0.0,
                "goal": "Serverrol",
            }

        if condition == "birthday_registered":
            current = int(
                metrics.get("birthday_registered", 0)
            )
            return {
                "text": (
                    "Verjaardag geregistreerd."
                    if current
                    else "Registreer je verjaardag bij LEVENLOOS."
                ),
                "ratio": 1.0 if current else 0.0,
                "goal": "Verjaardag",
            }

        if condition == "booster":
            current = int(metrics.get("booster", 0))
            return {
                "text": (
                    "Je boost LEVENLOOS."
                    if current
                    else "Boost de LEVENLOOS-server."
                ),
                "ratio": 1.0 if current else 0.0,
                "goal": "Server Booster",
            }

        rank_labels = {
            "rank_messages": "berichten",
            "rank_voice": "voice",
            "rank_xp": "XP",
            "join_position": "joinvolgorde",
        }
        if condition in rank_labels:
            try:
                target = max(1, int(float(raw_value)))
            except ValueError:
                target = 1

            current = int(metrics.get(condition, 0) or 0)
            if current <= 0:
                progress_text = (
                    f"Nog geen ranking • doel **Top {target}** "
                    f"op {rank_labels[condition]}."
                )
                ratio = 0.0
            elif current <= target:
                progress_text = (
                    f"Momenteel **#{current}** • doel **Top {target}** behaald."
                )
                ratio = 1.0
            else:
                progress_text = (
                    f"Momenteel **#{current}** • werk naar **Top {target}** "
                    f"op {rank_labels[condition]}."
                )
                ratio = min(0.99, target / current)

            return {
                "text": progress_text,
                "ratio": ratio,
                "goal": f"Top {target}",
            }

        labels = {
            "messages": ("berichten", 0),
            "voice_hours": ("voice-uren", 1),
            "xp": ("XP", 0),
            "member_days": ("dagen lid", 0),
            "account_days": ("dagen Discord-account", 0),
            "booster_days": ("dagen booster", 0),
            "waves_given": ("welcomes gegeven", 0),
            "waves_received": ("welcomes ontvangen", 0),
            "reactions_given": ("reacties gegeven", 0),
            "reactions_received": ("reacties ontvangen", 0),
            "invites": ("uitnodigingen", 0),
            "games": ("games", 0),
            "genres": ("genres", 0),
            "extra_roles": ("rollen", 0),
            "level": ("level", 0),
            "total_roles": ("serverrollen", 0),
            "react_roles_total": ("React Roles", 0),
            "social_total": ("sociale interacties", 0),
            "badges_owned": ("badges", 0),
        }

        if condition in labels:
            try:
                target = float(raw_value)
            except (ValueError, TypeError):
                target = 0.0

            current = float(metrics.get(condition, 0) or 0)
            ratio = (
                1.0
                if target <= 0 and earned
                else (
                    max(0.0, min(1.0, current / target))
                    if target > 0
                    else 0.0
                )
            )

            label, decimals = labels[condition]

            if condition == "xp":
                current_text = self._collection_number(current)
                target_text = self._collection_number(target)
                text = (
                    f"**{current_text} / {target_text} XP**"
                )
            elif condition == "level":
                text = (
                    f"**Level {int(current)} / {int(target)}**"
                )
            elif condition == "voice_hours":
                current_text = self._collection_number(
                    current,
                    decimals=1,
                )
                target_text = self._collection_number(
                    target,
                    decimals=1
                    if not float(target).is_integer()
                    else 0,
                )
                text = (
                    f"**{current_text} / {target_text} uur** in voice"
                )
            else:
                current_text = self._collection_number(
                    current,
                    decimals=decimals,
                )
                target_text = self._collection_number(
                    target,
                    decimals=decimals,
                )
                text = (
                    f"**{current_text} / {target_text}** {label}"
                )

            return {
                "text": text,
                "ratio": ratio,
                "goal": target,
            }

        return {
            "text": definition.get(
                "description",
                "Bekijk de badgevoorwaarden.",
            ),
            "ratio": None,
            "goal": None,
        }

    def collection_progress_bar(
        self,
        ratio: float | None,
        *,
        width: int = 8,
    ) -> str:
        if ratio is None:
            return ""

        ratio = max(0.0, min(1.0, float(ratio)))
        filled = round(ratio * width)
        filled = max(0, min(width, filled))
        percent = round(ratio * 100)

        return (
            f"`{'█' * filled}{'░' * (width - filled)}` "
            f"**{percent}%**"
        )

    async def build_collection_entries(
        self,
        member: discord.Member,
    ) -> list[dict]:
        definitions = await self.get_definitions()
        owned_badges = await self.get_member_badges(
            member.guild.id,
            member.id,
        )
        owned_ids = {
            badge["badge_id"]
            for badge in owned_badges
        }

        cache = await self.build_guild_cache(member.guild)
        metrics = self.metrics_for_member(member, cache)
        metrics["badges_owned"] = len(owned_ids)

        category_order = {
            category: index
            for index, category in enumerate(
                CATEGORY_LABELS.keys()
            )
        }

        entries: list[dict] = []

        for definition in definitions:
            entry = dict(definition)
            entry["earned"] = (
                definition["badge_id"] in owned_ids
            )

            progress = self.collection_progress(
                entry,
                metrics,
                earned=entry["earned"],
            )
            entry["progress_text"] = progress["text"]
            entry["progress_ratio"] = progress["ratio"]
            entry["progress_goal"] = progress["goal"]
            entries.append(entry)

        def sort_key(item: dict):
            # Binnen elke categorie: eerst de meest nabije nog te behalen
            # badges, daarna behaald. Secrets/handmatig blijven onderaan.
            ratio = item.get("progress_ratio")
            ratio_sort = (
                -float(ratio)
                if ratio is not None
                else 1.0
            )
            return (
                category_order.get(
                    item.get("category", "community"),
                    999,
                ),
                1 if item.get("earned") else 0,
                1 if item.get("mode") == "manual" else 0,
                1 if item.get("secret") and not item.get("earned") else 0,
                ratio_sort,
                int(item.get("sort_order", 0)),
                item.get("name", "").casefold(),
            )

        entries.sort(key=sort_key)
        return entries


    # =====================================================
    # SYNC
    # =====================================================



    def collection_text(
        self,
        member: discord.Member,
        entries: list[dict],
        category: str,
        status: str,
        page: int,
    ) -> str:
        filtered = entries

        if category != "all":
            filtered = [
                item
                for item in filtered
                if item.get("category") == category
            ]

        if status == "locked":
            filtered = [
                item
                for item in filtered
                if not item.get("earned", False)
                and item.get("mode") != "manual"
            ]
        elif status == "earned":
            filtered = [
                item
                for item in filtered
                if item.get("earned", False)
            ]
        elif status == "dynamic":
            filtered = [
                item
                for item in filtered
                if item.get("mode") == "dynamic"
            ]
        elif status == "manual":
            filtered = [
                item
                for item in filtered
                if item.get("mode") == "manual"
            ]

        pages = max(
            1,
            math.ceil(len(filtered) / COLLECTION_BADGES_PER_PAGE),
        )
        page = max(0, min(page, pages - 1))
        start = page * COLLECTION_BADGES_PER_PAGE
        current = filtered[start:start + COLLECTION_BADGES_PER_PAGE]

        earned_total = sum(
            1
            for item in entries
            if item.get("earned", False)
        )
        achievable_total = sum(
            1
            for item in entries
            if item.get("mode") != "manual"
        )

        category_label = (
            "Alle categorieën"
            if category == "all"
            else CATEGORY_LABELS.get(category, category.title())
        )
        status_name = COLLECTION_STATUS_LABELS.get(
            status,
            status.title(),
        )

        lines = [
            f"# {BADGES_EMOJI} Badge Collection",
            f"## {USER_EMOJI} {discord.utils.escape_markdown(member.display_name)}",
            f"> └ **{earned_total}/{len(entries)}** verzameld • **{achievable_total}** haalbaar",
            f"> └ **{category_label}** • **{status_name}** • {len(filtered)} badge(s)",
            "",
        ]

        if not current:
            lines.append("> └ Geen badges binnen deze filters.")
            return "\n".join(lines)

        for badge in current:
            earned = bool(badge.get("earned", False))
            secret_locked = bool(badge.get("secret")) and not earned
            mode = badge.get("mode", "permanent")

            if secret_locked:
                lines.extend(
                    [
                        f"### {LOCK_EMOJI} Secret Badge",
                        "> └ Voorwaarde verborgen.",
                        "",
                    ]
                )
                continue

            rarity = RARITY_LABELS.get(
                badge.get("rarity", "common"),
                str(badge.get("rarity", "common")).title(),
            )
            reward = max(0, int(badge.get("reward_xp", 0) or 0))
            status_icon = (
                SUCCESS_EMOJI
                if earned
                else (
                    REFRESH_EMOJI
                    if mode == "dynamic"
                    else (
                        EDIT_EMOJI
                        if mode == "manual"
                        else LOCK_EMOJI
                    )
                )
            )

            lines.append(
                f"### {status_icon} {badge['emoji']} {badge['name']}"
            )
            reward_text = (
                f" • {XP_EMOJI} +{fmt_number(reward)} XP"
                if reward > 0 and mode != "dynamic"
                else ""
            )
            lines.append(f"> └ *{rarity}*{reward_text}")

            progress_text = badge.get(
                "progress_text",
                badge.get("description", "Geen voortgang beschikbaar."),
            )
            lines.append(f"> └ {progress_text}")

            bar = self.collection_progress_bar(
                badge.get("progress_ratio")
            )
            if bar and mode != "manual":
                lines.append(f"> └ {bar}")

            description = str(badge.get("description", "")).strip()
            if description and description != progress_text:
                lines.append(f"> └ {description}")

            lines.append("")

        return "\n".join(lines)

    async def sync_member(self, member: discord.Member, *, cache: dict | None = None) -> tuple[int, int]:
        if member.bot:
            return 0, 0

        cache = cache or await self.build_guild_cache(member.guild)
        metrics = self.metrics_for_member(member, cache)
        definitions = await self.get_definitions()
        definition_map = {
            definition["badge_id"]: definition
            for definition in definitions
        }

        current_badges = {
            badge["badge_id"]: badge
            for badge in await self.get_member_badges(
                member.guild.id,
                member.id,
            )
        }

        added = 0
        removed = 0
        metrics["badges_owned"] = len(current_badges)

        # Bestaande badges krijgen bij de eerste sync na deze update ook hun
        # eenmalige reward. levels_xp_log blokkeert dubbele uitbetalingen.
        for badge_id, owned_badge in list(current_badges.items()):
            definition = definition_map.get(badge_id, owned_badge)
            reward = await self.reward_badge_xp(
                member.guild,
                member.id,
                definition,
            )
            if reward:
                metrics["xp"] = int(metrics.get("xp", 0)) + reward

        # Badge-XP kan een nieuwe XP-badge vrijspelen. Daarom maximaal 10 passes.
        for pass_index in range(10):
            new_in_pass = 0

            for definition in definitions:
                mode = definition["mode"]
                badge_id = definition["badge_id"]
                owns = badge_id in current_badges

                if mode == "manual":
                    continue

                qualifies = self.qualifies(
                    definition,
                    metrics,
                )

                if qualifies and not owns:
                    if await self.grant_badge(
                        member.guild.id,
                        member.id,
                        badge_id,
                        manual=False,
                    ):
                        added += 1
                        new_in_pass += 1
                        current_badges[badge_id] = {
                            **definition,
                            "manual": 0,
                        }
                        metrics["badges_owned"] = len(current_badges)

                        reward = await self.reward_badge_xp(
                            member.guild,
                            member.id,
                            definition,
                        )
                        if reward:
                            metrics["xp"] = int(
                                metrics.get("xp", 0)
                            ) + reward

                elif (
                    pass_index == 0
                    and not qualifies
                    and owns
                    and mode == "dynamic"
                    and not bool(
                        current_badges[badge_id].get(
                            "manual",
                            0,
                        )
                    )
                ):
                    if await self.revoke_badge(
                        member.guild.id,
                        member.id,
                        badge_id,
                        allow_manual=False,
                    ):
                        removed += 1
                        current_badges.pop(
                            badge_id,
                            None,
                        )
                        metrics["badges_owned"] = len(current_badges)

            if new_in_pass == 0:
                break

        return added, removed

    async def sync_guild(self, guild: discord.Guild) -> dict:
        async with self._sync_lock:
            cache = await self.build_guild_cache(guild)
            checked = 0
            added = 0
            removed = 0
            failed = 0
            for member in guild.members:
                if member.bot:
                    continue
                try:
                    new_count, removed_count = await self.sync_member(member, cache=cache)
                    checked += 1
                    added += new_count
                    removed += removed_count
                except Exception as exc:
                    failed += 1
                    logger.exception(
                        "Profile sync mislukt voor member %s: %s",
                        member.id,
                        exc,
                    )
            return {
                "checked": checked,
                "added": added,
                "removed": removed,
                "failed": failed,
            }

    @tasks.loop(minutes=AUTO_SYNC_MINUTES)
    async def auto_sync_loop(self):
        for guild in self.bot.guilds:
            try:
                await self.sync_guild(guild)
            except Exception as exc:
                logger.exception(
                    "Profile auto-sync mislukt voor guild %s: %s",
                    guild.id,
                    exc,
                )

    @auto_sync_loop.before_loop
    async def before_auto_sync(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(30)

    # =====================================================
    # PROFILE RENDERING
    # =====================================================

    async def birthday_text(self, guild_id: int, user_id: int) -> str | None:
        if not BIRTHDAYS_DATABASE.exists():
            return None
        async with aiosqlite.connect(BIRTHDAYS_DATABASE) as db:
            try:
                row = await (
                    await db.execute(
                        "SELECT day,month FROM birthdays WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                ).fetchone()
            except aiosqlite.OperationalError:
                return None
        if not row:
            return None
        months = ["", "januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"]
        return f"{int(row[0])} {months[int(row[1])]}"

    async def biggest_fan(self, guild_id: int, user_id: int) -> tuple[int | None, int]:
        if not LEVELS_DATABASE.exists():
            return None, 0
        async with aiosqlite.connect(LEVELS_DATABASE) as db:
            try:
                row = await (
                    await db.execute(
                        """
                        SELECT reactor_id,COUNT(*) AS amount
                        FROM levels_reaction_awards
                        WHERE guild_id=? AND author_id=?
                        GROUP BY reactor_id
                        ORDER BY amount DESC,reactor_id ASC
                        LIMIT 1
                        """,
                        (guild_id, user_id),
                    )
                ).fetchone()
            except aiosqlite.OperationalError:
                return None, 0
        if not row:
            return None, 0
        return int(row[0]), int(row[1])

    async def get_profile_data(self, member: discord.Member) -> dict:
        cache = await self.build_guild_cache(member.guild)
        metrics = self.metrics_for_member(member, cache)

        active_seconds = 0
        levels_cog = self.bot.get_cog("Levels")
        if levels_cog is not None:
            session = getattr(levels_cog, "voice_sessions", {}).get((member.guild.id, member.id))
            if session:
                _, started = session
                active_seconds = max(0, int(time.monotonic() - started))

        metrics["voice_seconds_live"] = metrics["voice_seconds"] + active_seconds
        metrics["active_voice_seconds"] = active_seconds
        metrics["birthday"] = await self.birthday_text(member.guild.id, member.id)
        fan_id, fan_count = await self.biggest_fan(member.guild.id, member.id)
        metrics["fan_id"] = fan_id
        metrics["fan_count"] = fan_count
        return metrics

    async def showcase_badges(self, member: discord.Member, all_badges: list[dict]) -> list[dict]:
        showcase_ids = await self.get_showcase(member.guild.id, member.id)
        badge_map = {badge["badge_id"]: badge for badge in all_badges}
        selected = [badge_map[badge_id] for badge_id in showcase_ids if badge_id in badge_map]
        if selected:
            return selected[:SHOWCASE_SIZE]
        return all_badges[:SHOWCASE_SIZE]



    # =====================================================
    # PROFILE RENDERING
    # =====================================================

    async def build_profile_text(self, member: discord.Member) -> str:
        data = await self.get_profile_data(member)
        all_badges = await self.get_member_badges(member.guild.id, member.id)
        definitions = await self.get_definitions()
        showcase = await self.showcase_badges(member, all_badges)

        display_name = discord.utils.escape_markdown(member.display_name)
        level = level_from_xp(data["xp"])
        joined = member.joined_at
        created = member.created_at

        title_badge_id = await self.get_title_badge_id(member.guild.id, member.id)
        badge_map = {
            badge["badge_id"]: badge
            for badge in all_badges
        }
        title_badge = (
            badge_map.get(title_badge_id)
            if title_badge_id
            else None
        )

        header = [
            f"# {PASSPORT_BADGE}",
            f"## {USER_EMOJI} {display_name}",
        ]

        if title_badge is not None:
            header.append(
                f"> └ {title_badge['emoji']} **{title_badge['name']}**"
            )

        header.append(
            f"> └ {member.mention} • Level **{level}** • "
            f"{XP_EMOJI} **{fmt_number(data['xp'])} XP**"
        )

        if joined is not None:
            header.append(
                f"> └ Lid sinds {discord.utils.format_dt(joined, 'D')} • "
                f"{discord.utils.format_dt(joined, 'R')}"
            )
        if data["birthday"]:
            header.append(f"> └ Verjaardag: **{data['birthday']}**")
        if member.premium_since is not None:
            header.append(
                f"> └ Booster sinds {discord.utils.format_dt(member.premium_since, 'D')}"
            )

        details = [
            f"## {XP_EMOJI} Activiteit",
            f"> └ {TEXT_EMOJI} Berichten: **{fmt_number(data['messages'])}** • "
            f"{rank_text(data['rank_messages'], data['ranked_members'])}",
            f"> └ {VOICE_EMOJI} Voice: **{fmt_voice(data['voice_seconds_live'])}** • "
            f"{rank_text(data['rank_voice'], data['ranked_members'])}",
            f"> └ {XP_EMOJI} XP: **{fmt_number(data['xp'])}** • "
            f"{rank_text(data['rank_xp'], data['ranked_members'])}",
        ]

        if data["active_voice_seconds"] > 0 and member.voice and member.voice.channel:
            details.append(
                f"> └ Nu in voice: {member.voice.channel.mention} • "
                f"**{fmt_voice(data['active_voice_seconds'])}**"
            )

        details.extend(
            [
                "",
                f"## {GAMES_EMOJI} LEVENLOOS",
                f"> └ Games: **{data['games']}** • Genres: **{data['genres']}** • "
                f"Extra rollen: **{data['extra_roles']}**",
                f"> └ Welkom geheten: **{fmt_number(data['waves_given'])}** • "
                f"Uitgenodigd: **{fmt_number(data['invites'])}**",
                f"> └ Reacties gekregen: **{fmt_number(data['reactions_received'])}** • "
                f"Gegeven: **{fmt_number(data['reactions_given'])}**",
            ]
        )

        if data["fan_id"] and data["fan_count"]:
            fan = member.guild.get_member(data["fan_id"])
            fan_text = fan.mention if fan else f"<@{data['fan_id']}>"
            details.append(
                f"> └ Grootste fan: {fan_text} • "
                f"**{fmt_number(data['fan_count'])} reacties**"
            )

        details.extend(
            [
                "",
                f"## {USER_EMOJI} Paspoort",
                f"> └ Discord sinds {discord.utils.format_dt(created, 'D')}",
                (
                    f"> └ Joinvolgorde: **#{data['join_position']}**"
                    if data["join_position"]
                    else "> └ Joinvolgorde: **—**"
                ),
                f"> └ Voice-equivalent: **{fmt_voice(data['voice_seconds_live'])}**",
                "",
                f"## {BADGES_EMOJI} Badge Case",
            ]
        )

        if showcase:
            for badge in showcase:
                rarity = RARITY_LABELS.get(
                    badge["rarity"],
                    badge["rarity"].title(),
                )
                details.append(
                    f"> └ {badge['emoji']} **{badge['name']}** • *{rarity}*"
                )
        else:
            details.append("> └ Nog geen badges verzameld.")

        details.append(
            f"> └ **{len(all_badges)}/{len(definitions)} badges verzameld**"
        )

        return (
            "\n".join(header)
            + "\n---PROFILE_SPLIT---\n"
            + "\n".join(details)
        )

    def badges_text(
        self,
        member: discord.Member,
        badges: list[dict],
        page: int,
    ) -> str:
        pages = max(1, math.ceil(len(badges) / BADGES_PER_PAGE))
        page = max(0, min(page, pages - 1))
        start = page * BADGES_PER_PAGE
        current = badges[start:start + BADGES_PER_PAGE]

        lines = [
            f"# {BADGES_EMOJI} Badges",
            f"## {USER_EMOJI} {discord.utils.escape_markdown(member.display_name)}",
            f"> └ **{len(badges)} badges verzameld**",
            "",
        ]

        if not current:
            lines.append("> └ Nog geen badges verdiend.")
            return "\n".join(lines)

        for badge in current:
            rarity = RARITY_LABELS.get(
                badge["rarity"],
                badge["rarity"].title(),
            )
            description = (
                "Voorwaarde verborgen."
                if badge.get("secret")
                else badge["description"]
            )
            reward = int(badge.get("reward_xp", 0) or 0)
            reward_text = (
                f" • {XP_EMOJI} +{fmt_number(reward)} XP"
                if reward > 0 and badge.get("mode") != "dynamic"
                else ""
            )
            lines.extend(
                [
                    f"### {badge['emoji']} {badge['name']}",
                    f"> └ *{rarity}*{reward_text}",
                    f"> └ {description}",
                    "",
                ]
            )

        return "\n".join(lines)

    async def open_showcase(self, interaction: discord.Interaction):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            return

        badges = await self.get_member_badges(
            interaction.guild.id,
            interaction.user.id,
        )
        current = set(
            await self.get_showcase(
                interaction.guild.id,
                interaction.user.id,
            )
        )

        if not badges:
            await self.send_feedback(
                interaction,
                "Je hebt nog geen badges om te showcasen.",
                kind="info",
            )
            return

        await interaction.response.send_message(
            view=ShowcaseView(
                self,
                interaction.user.id,
                badges,
                current,
            ),
            ephemeral=True,
        )

    async def open_title(self, interaction: discord.Interaction):
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            return

        badges = await self.get_member_badges(
            interaction.guild.id,
            interaction.user.id,
        )
        current_id = await self.get_title_badge_id(
            interaction.guild.id,
            interaction.user.id,
        )

        if not badges:
            await self.send_feedback(
                interaction,
                "Je hebt nog geen badges die als titel kunnen dienen.",
                kind="info",
            )
            return

        await interaction.response.send_message(
            view=TitleView(
                self,
                interaction.user.id,
                badges,
                current_id,
            ),
            ephemeral=True,
        )

    # =====================================================
    # PUBLIC COMMANDS
    # =====================================================

    @profile.command(
        name="view",
        description="Bekijk het openbare LEVENLOOS-paspoort van een lid",
    )
    @app_commands.describe(
        lid="Lid waarvan je het paspoort wilt bekijken",
    )
    async def profile_view(
        self,
        interaction: discord.Interaction,
        lid: discord.Member | None = None,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        member = lid or interaction.user
        if not isinstance(member, discord.Member) or member.bot:
            await self.send_feedback(
                interaction,
                "Voor dit account is geen paspoort beschikbaar.",
                kind="error",
            )
            return

        await interaction.response.defer(thinking=True)
        await self.sync_member(member)
        await interaction.followup.send(
            view=await ProfileView.create(
                self,
                member,
                interaction.user.id,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @profile.command(
        name="badges",
        description="Bekijk alle verdiende badges van een lid",
    )
    @app_commands.describe(
        lid="Lid waarvan je de badges wilt bekijken",
    )
    async def profile_badges(
        self,
        interaction: discord.Interaction,
        lid: discord.Member | None = None,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        member = lid or interaction.user
        if not isinstance(member, discord.Member) or member.bot:
            await self.send_feedback(
                interaction,
                "Geen badgeprofiel beschikbaar.",
                kind="error",
            )
            return

        await interaction.response.defer(thinking=True)
        await self.sync_member(member)
        badges = await self.get_member_badges(
            interaction.guild.id,
            member.id,
        )
        await interaction.followup.send(
            view=BadgePagesView(
                self,
                interaction.user.id,
                member,
                badges,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @profile.command(
        name="collection",
        description="Bekijk alle badges en zie waar je naartoe kunt werken",
    )
    @app_commands.describe(
        lid="Optioneel: bekijk de badge-roadmap van een ander lid",
    )
    async def profile_collection(
        self,
        interaction: discord.Interaction,
        lid: discord.Member | None = None,
    ):
        if interaction.guild is None:
            await self.send_feedback(
                interaction,
                "Dit werkt alleen in een server.",
                kind="error",
            )
            return

        member = lid or interaction.user
        if not isinstance(member, discord.Member) or member.bot:
            await self.send_feedback(
                interaction,
                "Geen badgeprofiel beschikbaar.",
                kind="error",
            )
            return

        await interaction.response.defer(thinking=True)
        await self.sync_member(member)
        entries = await self.build_collection_entries(member)
        await interaction.followup.send(
            view=BadgeCollectionView(
                self,
                interaction.user.id,
                member,
                entries,
                status="locked",
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @profile.command(
        name="showcase",
        description="Kies welke badges op jouw paspoort staan",
    )
    async def profile_showcase(self, interaction: discord.Interaction):
        await self.open_showcase(interaction)

    @profile.command(
        name="title",
        description="Kies een verdiende badge als titel op je paspoort",
    )
    async def profile_title(self, interaction: discord.Interaction):
        await self.open_title(interaction)

    # =====================================================
    # ADMIN COMMANDS
    # =====================================================

    async def require_admin(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not management_access(interaction.user)
        ):
            await self.send_feedback(
                interaction,
                "Alleen Admins en de Owner kunnen dit gebruiken.",
                kind="error",
                title="Geen toegang",
            )
            return False
        return True

    @profile.command(
        name="sync",
        description="Synchroniseer alle paspoorten en badges",
    )
    @app_commands.describe(
        lid="Optioneel: synchroniseer alleen dit lid",
    )
    async def profile_sync(
        self,
        interaction: discord.Interaction,
        lid: discord.Member | None = None,
    ):
        if not await self.require_admin(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        if lid is not None:
            added, removed = await self.sync_member(lid)
            await self.send_feedback(
                interaction,
                (
                    f"**{lid.display_name}** gesynchroniseerd.\n"
                    f"Nieuwe badges: **{added}**\n"
                    f"Dynamische badges verwijderd: **{removed}**"
                ),
                kind="success",
                title="Profiel gesynchroniseerd",
            )
            return

        result = await self.sync_guild(interaction.guild)
        await self.send_feedback(
            interaction,
            (
                f"Gecontroleerd: **{result['checked']}**\n"
                f"Nieuwe badges: **{result['added']}**\n"
                f"Dynamisch verwijderd: **{result['removed']}**\n"
                f"Fouten: **{result['failed']}**"
            ),
            kind="warning" if result["failed"] else "success",
            title="Profile Sync",
        )

    @badge.command(
        name="recalculatexp",
        description="Herbereken reeds uitgedeelde badge-XP met de huidige rewards",
    )
    @app_commands.describe(
        lid="Optioneel: corrigeer alleen dit lid",
    )
    async def badge_recalculate_xp(
        self,
        interaction: discord.Interaction,
        lid: discord.Member | None = None,
    ):
        if not await self.require_admin(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.recalculate_awarded_badge_xp(
            guild_id=interaction.guild.id,
            user_id=lid.id if lid is not None else None,
        )
        target = (
            f"**{lid.display_name}**"
            if lid is not None
            else "**alle leden**"
        )
        await self.send_feedback(
            interaction,
            (
                f"Doel: {target}\n"
                f"Badge-logs gecontroleerd: **{result['logs_checked']}**\n"
                f"Rewards aangepast: **{result['logs_changed']}**\n"
                f"XP teruggedraaid: **{fmt_number(result['xp_removed'])}**\n"
                f"XP toegevoegd: **{fmt_number(result['xp_added'])}**\n"
                f"Progress-badges verwijderd: **{result['progress_badges_removed']}**\n"
                f"Leden aangepast: **{result['users_changed']}**"
            ),
            kind="success",
            title="Badge XP herberekend",
        )

    @badge.command(
        name="import",
        description="Voeg één of meerdere badge-definities toe via bulk paste",
    )
    async def badge_import(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        await interaction.response.send_modal(BadgeImportModal(self))

    @badge.command(
        name="importfile",
        description="Importeer veel badges tegelijk uit een tekstbestand",
    )
    @app_commands.describe(
        bestand="UTF-8 .txt/.csv/.md met één badge per regel",
    )
    async def badge_importfile(
        self,
        interaction: discord.Interaction,
        bestand: discord.Attachment,
    ):
        if not await self.require_admin(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        if bestand.size > 512_000:
            await self.send_feedback(
                interaction,
                "Bestand is te groot. Maximaal **500 KB**.",
                kind="error",
            )
            return

        try:
            payload = await bestand.read()
            raw_text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            await self.send_feedback(
                interaction,
                "Ik kan dit bestand niet als UTF-8 tekst lezen.",
                kind="error",
            )
            return
        except discord.HTTPException:
            logger.exception("Badge importbestand lezen mislukt.")
            await self.send_feedback(
                interaction,
                "Het bestand kon niet worden gelezen.",
                kind="error",
            )
            return

        added, errors = await self.import_badge_text(raw_text)
        lines = [
            f"Bestand: `{bestand.filename}`",
            f"Verwerkt: **{added}**",
            f"Overgeslagen: **{len(errors)}**",
        ]
        lines.extend(errors[:10])
        if len(errors) > 10:
            lines.append(f"… en {len(errors) - 10} meer.")

        await self.send_feedback(
            interaction,
            "\n".join(lines),
            kind="warning" if errors else "success",
            title="Badge file import",
        )

    @badge.command(
        name="give",
        description="Geef een handmatige badge aan een lid",
    )
    @app_commands.describe(
        lid="Lid dat de badge krijgt",
        badge_id="ID van de badge",
    )
    async def badge_give(
        self,
        interaction: discord.Interaction,
        lid: discord.Member,
        badge_id: str,
    ):
        if not await self.require_admin(interaction):
            return

        badge_id = badge_id.strip().lower()
        definitions = {
            item["badge_id"]: item
            for item in await self.get_definitions()
        }
        definition = definitions.get(badge_id)

        if definition is None:
            await self.send_feedback(
                interaction,
                "Deze badge bestaat niet.",
                kind="error",
            )
            return

        if definition["mode"] != "manual":
            await self.send_feedback(
                interaction,
                "Gebruik `give` alleen voor handmatige badges.",
                kind="error",
            )
            return

        added = await self.grant_badge(
            interaction.guild.id,
            lid.id,
            badge_id,
            manual=True,
        )
        reward = await self.reward_badge_xp(
            interaction.guild,
            lid.id,
            definition,
        )

        message = (
            f"{definition['emoji']} **{definition['name']}** "
            f"{'gegeven aan' if added else 'was al van'} {lid.mention}."
        )
        if reward:
            message += f"\n{XP_EMOJI} **+{fmt_number(reward)} XP**"

        await self.send_feedback(
            interaction,
            message,
            kind="success" if added else "info",
            title="Handmatige badge",
        )

    @badge.command(
        name="take",
        description="Neem een handmatige badge af van een lid",
    )
    @app_commands.describe(
        lid="Lid waarvan de badge wordt verwijderd",
        badge_id="ID van de badge",
    )
    async def badge_take(
        self,
        interaction: discord.Interaction,
        lid: discord.Member,
        badge_id: str,
    ):
        if not await self.require_admin(interaction):
            return

        removed = await self.revoke_badge(
            interaction.guild.id,
            lid.id,
            badge_id.strip().lower(),
            allow_manual=True,
        )
        await self.send_feedback(
            interaction,
            (
                "Badge verwijderd."
                if removed
                else "Dit lid had die badge niet."
            ),
            kind="success" if removed else "info",
            title="Badge verwijderen",
        )

    @badge.command(
        name="catalog",
        description="Bekijk de badge-engine en beschikbare badge-definities",
    )
    async def badge_catalog(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return

        definitions = await self.get_definitions()
        automatic = sum(
            1
            for item in definitions
            if item["mode"] == "permanent"
        )
        dynamic = sum(
            1
            for item in definitions
            if item["mode"] == "dynamic"
        )
        manual = sum(
            1
            for item in definitions
            if item["mode"] == "manual"
        )

        body = (
            f"# {BADGES_EMOJI} Badge Engine\n"
            f"> └ Totaal: **{len(definitions)}**\n"
            f"> └ Permanent: **{automatic}**\n"
            f"> └ Dynamisch: **{dynamic}**\n"
            f"> └ Handmatig: **{manual}**\n\n"
            f"## {ADD_EMOJI} Nieuwe badges\n"
            "> └ Kleine batch: `/profile badge import`\n"
            "> └ Grote batch: `/profile badge importfile`\n"
            "> └ Formaat: `id | Naam | Emoji | categorie | rarity | condition | waarde | mode | secret | xp | beschrijving`\n\n"
            f"## {INFO_EMOJI} Conditions\n"
            "> └ `" + "`, `".join(sorted(SUPPORTED_CONDITIONS)) + "`"
        )

        await interaction.response.send_message(
            view=SimplePanelView(body),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
