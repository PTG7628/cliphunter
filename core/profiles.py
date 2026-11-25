"""Game profiles: what a highlight looks like per genre, which signals matter, and what to reject.

Add a new game by copying a profile below. `keywords` are matched against the video/stream title
when the profile is set to "auto".
"""
import re

# signal weights: chat (viewer reaction), voice (streamer mic intensity), contrast (quiet then loud),
# onset (sudden sounds), motion (big visual change), flash (explosions / fades), desat (screen goes grey)
PROFILES = {
    "open_world": {
        "name": "Open world / GTA",
        "keywords": ["gta", "grand theft auto", "red dead", "rdr", "cyberpunk", "watch dogs", "saints row",
                     "roleplay", " rp ", "nopixel", "mafia", "sleeping dogs", "leonida", "vice city"],
        "categories": {
            "funny fail": "a death, crash or plan going wrong in a funny way",
            "chaotic chase": "police chase, escape or getaway with real tension",
            "crazy stunt": "jump, driving or flying stunt that actually lands (or spectacularly fails)",
            "physics glitch": "ragdoll, physics or bug moment that looks absurd",
            "npc/player interaction": "unexpected or funny interaction with an NPC or another player",
            "skill play": "impressive driving, shooting or escape",
            "big reaction": "streamer reacts strongly to something clearly visible or audible",
        },
        "focus": "Chaos, comedy and spectacle. In GTA a 'Wasted'/'Busted' screen (grey, slowed-down screen) "
                 "often marks a death; it is only interesting if the lead-up was funny or dramatic.",
        "reject": "plain driving, walking around, shopping/menus/phone, loading, mission dialogue with no "
                  "reaction, story spoilers (big plot reveals or the ending)",
        "weights": {"chat": 1.0, "voice": 0.8, "contrast": 0.5, "onset": 0.3, "motion": 0.35, "flash": 0.4,
                    "desat": 0.7},
        "context": (55, 35),
        "layout": "auto",
    },
    "fps": {
        "name": "FPS / shooter",
        "keywords": ["valorant", "cs2", "counter-strike", "csgo", "call of duty", "cod", "overwatch", "rainbow six",
                     "r6", "battlefield", "halo", "the finals", "deadlock"],
        "categories": {
            "clutch": "winning a round while outnumbered",
            "multikill": "several kills in quick succession",
            "precision shot": "flick, wallbang or very hard shot",
            "comeback": "turning a lost situation around",
            "funny fail": "embarrassing death or whiff",
            "big reaction": "streamer reacts strongly to a clear event",
        },
        "focus": "Skill and tension. A routine single kill is not a highlight. Clutches need enough setup to "
                 "show the odds (e.g. 1v3).",
        "reject": "routine kills, buy phase, walking to site, waiting for respawn, menu and lobby time",
        "weights": {"chat": 1.0, "voice": 0.8, "contrast": 0.6, "onset": 0.4, "motion": 0.3, "flash": 0.2,
                    "desat": 0.2},
        "context": (50, 30),
        "layout": "auto",
    },
    "battle_royale": {
        "name": "Battle royale",
        "keywords": ["fortnite", "apex", "warzone", "pubg", "battlegrounds", "fall guys", "free fire"],
        "categories": {
            "final circle": "tense final-circle fight",
            "squad wipe": "eliminating a whole squad",
            "escape": "surviving against the odds",
            "unusual elimination": "weird or hilarious kill",
            "funny fail": "embarrassing death",
            "victory": "winning the match with a strong reaction",
        },
        "focus": "End-game tension, wipes and wild eliminations.",
        "reject": "looting, dropping, rotating with nothing happening, lobby",
        "weights": {"chat": 1.0, "voice": 0.8, "contrast": 0.5, "onset": 0.4, "motion": 0.35, "flash": 0.3,
                    "desat": 0.2},
        "context": (50, 30),
        "layout": "auto",
    },
    "sandbox": {
        "name": "Sandbox / survival",
        "keywords": ["minecraft", "rust", "ark", "terraria", "valheim", "dayz", "palworld", "lethal company",
                     "roblox", "garry", "among us"],
        "categories": {
            "funny accident": "something goes hilariously wrong",
            "discovery": "unexpected find or reveal",
            "betrayal": "a player betrays another",
            "survival emergency": "close call, panic, last-second save",
            "big reaction": "streamer reacts strongly to a clear event",
        },
        "focus": "Stories between players, accidents and close calls.",
        "reject": "farming, building, crafting and inventory management with nothing happening",
        "weights": {"chat": 1.0, "voice": 0.9, "contrast": 0.6, "onset": 0.3, "motion": 0.25, "flash": 0.2,
                    "desat": 0.2},
        "context": (55, 35),
        "layout": "auto",
    },
    "horror": {
        "name": "Horror",
        "keywords": ["horror", "resident evil", "outlast", "fnaf", "five nights", "phasmophobia", "silent hill",
                     "dead by daylight", "amnesia", "scary"],
        "categories": {
            "jump scare": "a scare with a genuine reaction",
            "panic": "panicked escape or chase",
            "tense encounter": "slow-building suspense with a payoff",
            "funny fear": "the streamer's fear is funny",
        },
        "focus": "Suspense then payoff. Silence before a scare is part of the clip, keep it short.",
        "reject": "exploring with no tension, reading notes, menus",
        "weights": {"chat": 1.0, "voice": 1.0, "contrast": 1.0, "onset": 0.5, "motion": 0.25, "flash": 0.2,
                    "desat": 0.1},
        "context": (35, 25),
        "layout": "auto",
    },
    "sports_racing": {
        "name": "Sports / racing",
        "keywords": ["fifa", "fc 2", "ea fc", "nba 2k", "rocket league", "forza", "gran turismo", "f1 2",
                     "mario kart", "efootball", "madden", "cricket"],
        "categories": {
            "last-second win": "winning at the very end",
            "dramatic save": "goalkeeper/defensive save",
            "comeback": "coming back from behind",
            "crash": "unexpected crash",
            "close finish": "photo finish or last-lap overtake",
        },
        "focus": "Late drama and big swings.",
        "reject": "menus, replays without reaction, uneventful play",
        "weights": {"chat": 1.0, "voice": 0.9, "contrast": 0.5, "onset": 0.4, "motion": 0.3, "flash": 0.15,
                    "desat": 0.1},
        "context": (45, 30),
        "layout": "auto",
    },
    "just_chatting": {
        "name": "Just chatting / IRL",
        "keywords": ["just chatting", "irl", "podcast", "q&a", "qna", "react", "reaction", "talk", "vlog",
                     "roast", "live chat"],
        "categories": {
            "funny exchange": "a joke or banter that lands",
            "surprising statement": "something unexpected is said",
            "story": "a short memorable story with a punchline",
            "strong reaction": "a strong reaction to something shown",
        },
        "focus": "Words matter most: a clear setup and punchline that works without context.",
        "reject": "small talk, reading chat names, technical issues, long unrelated rambling",
        "weights": {"chat": 1.0, "voice": 0.9, "contrast": 0.5, "onset": 0.2, "motion": 0.1, "flash": 0.05,
                    "desat": 0.05},
        "context": (60, 35),
        "layout": "auto",
    },
    "general": {
        "name": "General gaming",
        "keywords": [],
        "categories": {
            "skill play": "impressive play",
            "funny fail": "funny mistake or death",
            "surprise": "unexpected event",
            "big reaction": "strong reaction to a clear event",
            "story": "short story with setup and payoff",
        },
        "focus": "Impressive, surprising, funny or emotional moments that make sense without context.",
        "reject": "ordinary gameplay, menus, loading, waiting",
        "weights": {"chat": 1.0, "voice": 0.8, "contrast": 0.6, "onset": 0.35, "motion": 0.3, "flash": 0.3,
                    "desat": 0.3},
        "context": (50, 35),
        "layout": "auto",
    },
}


def get(profile_id):
    return PROFILES.get(profile_id) or PROFILES["general"]


def detect(title, game_context=""):
    """Guess the profile from a title (and the game name in settings). Returns a profile id."""
    text = f" {title or ''} ".lower()
    best, best_hits = None, 0
    for pid, p in PROFILES.items():
        hits = sum(1 for k in p["keywords"] if k in text)
        if hits > best_hits:
            best, best_hits = pid, hits
    if best:
        return best
    gc = f" {game_context or ''} ".lower()
    for pid, p in PROFILES.items():
        if any(k in gc for k in p["keywords"]):
            return pid
    return "general"


def resolve(profile_setting, title, game_context=""):
    if profile_setting and profile_setting != "auto" and profile_setting in PROFILES:
        return profile_setting
    return detect(title, game_context)


def category_names(profile_id):
    return list(get(profile_id)["categories"].keys())


def public_list():
    return [{"id": pid, "name": p["name"], "categories": list(p["categories"].keys())} for pid, p in PROFILES.items()]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
