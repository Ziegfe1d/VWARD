#!/usr/bin/env python3
"""Build VWARD's services catalog from iplist (github.com/rekryt/iplist, MIT).

iplist keeps one JSON per service in config/<category>/<service>.json; only its
"domains" are used.  Keenetic domain lists take a domain with all its
subdomains, so a subdomain whose parent is listed is dropped, and three or more
names under one registrable domain become that domain - except the shared
hosting and CDN domains, which would pull unrelated sites into the VPN.  A
service still over the Keenetic list limit is folded harder, then marked.

Usage: build-services-catalog.py IPLIST_DIR OUTPUT.json
"""

import json
import re
import subprocess
import sys
from pathlib import Path

LIMIT = 300

CATEGORIES = {
    "ai": "Нейросети", "youtube": "YouTube", "video": "Видео", "socials": "Соцсети",
    "messengers": "Мессенджеры", "discord": "Discord", "music": "Музыка", "games": "Игры",
    "anime": "Аниме", "news": "Новости", "education": "Обучение", "tools": "Инструменты",
    "jetbrains": "JetBrains", "hosting": "Хостинг", "shop": "Магазины", "finance": "Финансы",
    "art": "Творчество", "torrent": "Торренты", "casino": "Казино", "porn": "18+",
}

TITLES = {
    "youtube.com": "YouTube", "revanced.app": "ReVanced", "chatgpt.com": "ChatGPT", "claude.ai": "Claude",
    "copilot": "Copilot", "deepseek.com": "DeepSeek", "perplexity.ai": "Perplexity", "grok.com": "Grok",
    "aistudio.google.com": "Google AI Studio", "notebooklm.google": "NotebookLM", "meta.ai": "Meta AI",
    "cursor.com": "Cursor", "deepl.com": "DeepL", "elevenlabs.io": "ElevenLabs", "grammarly.com": "Grammarly",
    "canva.com": "Canva", "instagram.com": "Instagram", "facebook.com": "Facebook", "tiktok.com": "TikTok",
    "x.com": "X (Twitter)", "twitter.com": "X (Twitter)", "linkedin.com": "LinkedIn", "threads.net": "Threads",
    "whatsapp.com": "WhatsApp", "telegram.org": "Telegram", "signal.org": "Signal", "viber.com": "Viber",
    "discord.com": "Discord", "netflix.com": "Netflix", "spotify.com": "Spotify", "deezer.com": "Deezer",
    "tidal.com": "TIDAL", "soundcloud.com": "SoundCloud", "twitch.tv": "Twitch", "medium.com": "Medium",
    "patreon.com": "Patreon", "reddit.com": "Reddit", "pinterest.com": "Pinterest", "anydesk.com": "AnyDesk",
    "capcut.com": "CapCut", "notion.so": "Notion", "figma.com": "Figma", "github.com": "GitHub",
}

TWO_LEVEL = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.ru", "net.ru", "org.ru", "msk.ru", "spb.ru",
             "com.ua", "in.ua", "kiev.ua", "com.kz", "co.jp", "ne.jp", "or.jp", "com.br", "com.au",
             "com.tr", "co.kr", "com.cn", "com.tw", "co.in", "com.mx", "co.za", "com.ar"}

# Hosting, CDN and portal domains many unrelated sites share: never folded to.
SHARED = {"amazonaws.com", "cloudfront.net", "akamaized.net", "akamaihd.net", "akamai.net", "edgekey.net",
          "edgesuite.net", "fastly.net", "fastlylb.net", "cloudflare.com", "cloudflare.net", "azureedge.net",
          "azurefd.net", "windows.net", "googleapis.com", "googleusercontent.com", "gstatic.com", "appspot.com",
          "herokuapp.com", "github.io", "digitaloceanspaces.com", "b-cdn.net", "cdn77.org", "llnwd.net",
          "trafficmanager.net", "cloudapp.net", "azure.com", "edgecastcdn.net", "wpengine.com", "vercel.app",
          "netlify.app", "pages.dev", "workers.dev", "firebaseapp.com", "web.app", "blogspot.com",
          "wordpress.com", "tumblr.com", "yandex.net", "yandex.ru", "vk.com", "mail.ru", "userapi.com",
          "google.com", "microsoft.com", "apple.com", "icloud.com", "live.com", "office.com", "sharepoint.com"}

LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
TLD = re.compile(r"^[a-z]{2,6}$")
# Longer real top-level domains seen in the data; anything else long is a typo.
LONG_TLDS = {"finance", "online", "google", "download", "design", "center", "directory", "supply", "digital",
             "network", "website", "systems", "company", "yandex", "moscow", "science", "support", "software",
             "services", "capital", "gallery", "academy", "agency", "studio", "social", "global", "stream"}
SERVICE_ID = re.compile(r"^[a-z0-9][a-z0-9.@_-]{0,62}$")


def valid(d: str) -> bool:
    parts = d.split(".")
    return 4 <= len(d) <= 253 and len(parts) >= 2 and (bool(TLD.match(parts[-1])) or parts[-1] in LONG_TLDS) and all(LABEL.match(p) for p in parts)


def registrable(d: str) -> str:
    p = d.split(".")
    return ".".join(p[-3:]) if len(p) >= 3 and ".".join(p[-2:]) in TWO_LEVEL else ".".join(p[-2:])


def fold(domains, at_least: int):
    names = sorted({d.strip().lower().rstrip(".") for d in domains if isinstance(d, str)})
    names = [d for d in names if valid(d)]
    have = set(names)
    names = [d for d in names if not any(".".join(d.split(".")[i:]) in have for i in range(1, len(d.split(".")) - 1))]
    by_root = {}
    for d in names:
        by_root.setdefault(registrable(d), []).append(d)
    out = set()
    for root, group in by_root.items():
        if len(group) >= at_least and root not in SHARED and valid(root):
            out.add(root)
        else:
            out.update(group)
    return sorted(out)


def title_of(service_id: str) -> str:
    if service_id in TITLES:
        return TITLES[service_id]
    return service_id


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 64
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    config = src / "config"
    rev = subprocess.run(["git", "-C", str(src), "log", "-1", "--format=%H %cI"], capture_output=True, text=True)
    revision, updated = (rev.stdout.split() + ["", ""])[:2] if rev.returncode == 0 else ("", "")
    services = []
    for path in sorted(config.glob("*/*.json")):
        category, service_id = path.parent.name, path.stem
        if category not in CATEGORIES or not SERVICE_ID.match(service_id):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        domains = fold(data.get("domains") or [], 3)
        if len(domains) > LIMIT:
            domains = fold(data.get("domains") or [], 2)
        if not domains:
            continue
        entry = {"id": service_id, "category": category, "title": title_of(service_id), "domains": domains}
        if len(domains) > LIMIT:
            entry["too_big"] = True
        services.append(entry)
    catalog = {
        "schema": 1,
        "source": "iplist",
        "source_url": "https://github.com/rekryt/iplist",
        "license": "MIT",
        "revision": revision,
        "updated": updated,
        "limit": LIMIT,
        "categories": [{"id": k, "title": v} for k, v in CATEGORIES.items() if any(s["category"] == k for s in services)],
        "services": services,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"SERVICES_CATALOG=OK services={len(services)} domains={sum(len(s['domains']) for s in services)} bytes={out.stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
