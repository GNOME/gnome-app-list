#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 GNOME Foundation, Inc.
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Fetch and cache web app metadata for AppStream generation.

Usage: update_web_apps.py INPUT.json CACHE.json [--no-localize]

Reads the web app list from INPUT.json, fetches metadata from each site
(name, summary, description, icon, localized variants), and writes a
CACHE.json file that the offline generate_web_apps.py script uses to
produce AppStream XML without any network access.

All URLs are re-fetched on every run so that updated server content is
picked up. Run this script whenever INPUT.json changes or when you want
to refresh cached metadata.
"""

import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

MAX_WORKERS = 10
MAX_RETRIES = 3
SUMMARY_MAX_LEN = 80
PROBE_COUNT = 10

_thread_local = threading.local()


def get_session():
    """Return a per-thread requests.Session."""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
    return _thread_local.session


# W3C manifest categories → AppStream categories
# https://github.com/w3c/manifest/wiki/Categories
# https://specifications.freedesktop.org/menu-spec/latest/apa.html
W3C_TO_APPSTREAM = {
    "books": "Literature",
    "business": "Office",
    "education": "Education",
    "finance": "Finance",
    "fitness": "Sports",
    "games": "Game",
    "health": "MedicalSoftware",
    "magazines": "News",
    "medical": "MedicalSoftware",
    "music": "Music",
    "navigation": "Maps",
    "news": "News",
    "photo": "Photography",
    "productivity": "Office",
    "security": "Security",
    "social": "Chat",
    "sports": "Sports",
    "utilities": "Utility",
    "weather": "Utility",
}

# Keyword hints for guessing categories when the manifest doesn't declare them.
KEYWORD_CATEGORY_HINTS = [
    (
        (
            "diagram",
            "draw.io",
            "flowchart",
            "chart",
            "whiteboard",
            "sketch",
            "excalidraw",
        ),
        ["Graphics", "Office"],
    ),
    (
        ("telegram", "chat", "message", "messenger", "discourse", "forum"),
        ["Network", "Chat"],
    ),
    (("file", "share", "transfer", "snapdrop", "drop"), ["Network", "FileTransfer"]),
    (("editor", "markdown", "stackedit", "text editor", "note"), ["Office"]),
    (
        ("doc", "docs", "devdoc", "documentation", "developer", "api reference"),
        ["Development"],
    ),
    (
        ("photo", "image", "picture", "compress", "optimizer"),
        ["Graphics", "Photography"],
    ),
    (("music", "audio", "podcast", "radio"), ["AudioVideo", "Music"]),
    (("video", "stream", "watch"), ["AudioVideo", "Video"]),
    (("news", "magazine", "article", "blog"), ["News"]),
    (("game", "play"), ["Game"]),
    (("finance", "bank", "budget", "money", "invest"), ["Office", "Finance"]),
    (("map", "navigation", "route", "gps"), ["Maps"]),
    (("education", "learn", "course", "study", "school"), ["Education"]),
]


def guess_categories(name, description, url):
    """Return AppStream categories inferred from name/description/URL keywords."""
    haystack = " ".join([name, description, url]).lower()
    for keywords, cats in KEYWORD_CATEGORY_HINTS:
        if any(kw in haystack for kw in keywords):
            return cats
    return []


# Languages used by GNOME Software, ordered so commonly-localized ones come first.
# The first PROBE_COUNT are used as an early-exit heuristic: if none of them yield
# content different from English, the remaining languages are skipped entirely.
GNOME_LANGUAGES = [
    # Probe set — widely supported by web apps
    "de",
    "fr",
    "es",
    "ja",
    "zh-Hans-CN",
    "pt-BR",
    "ru",
    "ko",
    "it",
    "nl",
    # Remainder
    "ab",
    "af",
    "ar",
    "as",
    "be-Cyrl",
    "bg",
    "bn",
    "bs-Latn",
    "ca",
    "ca-valencia",
    "ckb",
    "cs",
    "da",
    "el",
    "en-GB",
    "eo",
    "eu",
    "fa",
    "fi",
    "fil",
    "fur",
    "ga",
    "gd",
    "gl",
    "he",
    "hi",
    "hr",
    "hu",
    "ia",
    "id",
    "ie",
    "is",
    "ka",
    "kab",
    "kk-Cyrl",
    "km",
    "lt",
    "lv",
    "mjw",
    "ml",
    "ms",
    "nb",
    "ne",
    "oc",
    "pa",
    "pl",
    "pt",
    "ro",
    "sk",
    "sl",
    "sr-Cyrl",
    "sr-Latn",
    "sv",
    "te",
    "th",
    "tr",
    "ug",
    "uk",
    "uz-Latn",
    "vi",
    "zh-Hant-HK",
    "zh-Hant-TW",
]


def compute_checksum(path):
    """Return the SHA-256 hex digest of the file at path."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def fetch(url, lang=None, session=None):
    headers = {
        "User-Agent": (
            "gnome-app-list/1.0 (+https://gitlab.gnome.org/GNOME/gnome-app-list)"
        )
    }
    if lang:
        headers["Accept-Language"] = f"{lang}, en;q=0.1"
    s = session or get_session()
    delay = 1.0
    for attempt in range(MAX_RETRIES):
        r = s.get(url, headers=headers, timeout=15)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", delay))
            time.sleep(wait)
            delay *= 2
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def get_manifest_url(page_url, soup, lang=None):
    if page_url.startswith("https://discourse."):
        return urljoin(page_url, "/manifest.webmanifest")
    tag = None
    if soup.head:
        tag = soup.head.find("link", rel="manifest", href=True)
    if not tag:
        tag = soup.find("link", rel="manifest", href=True)
    if not tag:
        return None
    return urljoin(page_url, tag["href"])


def fetch_manifest(manifest_url, lang=None, session=None):
    try:
        r = fetch(manifest_url, lang=lang, session=session)
        return json.loads(r.text)
    except Exception:
        return None


def extract_page_data(page_url, lang=None, session=None):
    """Return (soup, manifest_url, manifest) for a page fetched with the given lang."""
    s = session or get_session()
    try:
        r = fetch(page_url, lang=lang, session=s)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        print(
            f"  Warning: failed to fetch {page_url} (lang={lang}): {exc}",
            file=sys.stderr,
        )
        return None, None, None

    manifest_url = get_manifest_url(page_url, soup, lang=lang)
    manifest = (
        fetch_manifest(manifest_url, lang=lang, session=s) if manifest_url else None
    )
    return soup, manifest_url, manifest


def get_name(manifest):
    return manifest.get("name") or manifest.get("short_name") or ""


def get_summary(soup, manifest):
    """Return a short summary string (≤ SUMMARY_MAX_LEN chars)."""
    candidates = []
    if soup:
        og = soup.find("meta", property="og:description")
        if og and og.get("content"):
            candidates.append(og["content"].strip())
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            candidates.append(meta["content"].strip())
    if manifest and manifest.get("description"):
        candidates.append(manifest["description"].strip())

    for text in candidates:
        text = text.replace("\n", " ").strip()
        if text.endswith("."):
            text = text[:-1]
        if text:
            return text[:SUMMARY_MAX_LEN]
    return ""


def get_description(soup, manifest, summary):
    """Return a longer description string, or '' if nothing better than summary."""
    if manifest and manifest.get("description"):
        desc = manifest["description"].replace("\n", " ").strip()
        if len(desc) > len(summary) + 20:
            return desc
    return ""


def pick_best_icon(manifest, base_url, manifest_url=None, session=None):
    icons = manifest.get("icons", [])
    if not icons:
        return None

    icons = [i for i in icons if i.get("src", "").strip()]
    if not icons:
        return None

    normal = [i for i in icons if i.get("purpose", "any") in ("any", "")]
    pool = normal if normal else icons

    def icon_size(icon):
        sizes = icon.get("sizes", "0x0").split()[-1]
        try:
            w, h = sizes.split("x")
            return int(w) * int(h)
        except ValueError:
            return 0

    resolve_base = manifest_url if manifest_url else base_url
    candidates_sorted = sorted(pool, key=icon_size, reverse=True)

    def check_icon(candidate):
        src = urljoin(resolve_base, candidate["src"])
        try:
            r = get_session().head(src, timeout=10, allow_redirects=True)
            return candidate, src, r.status_code == 200
        except Exception:
            return candidate, src, False

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        checked = list(ex.map(check_icon, candidates_sorted))

    for candidate, src, ok in checked:
        if not ok:
            continue
        sizes = candidate.get("sizes", "0x0").split()[-1]
        try:
            w, h = sizes.split("x")
        except ValueError:
            w = h = "0"
        return {"src": src, "width": w, "height": h}
    return None


def detect_adaptive(manifest):
    display = manifest.get("display", "standalone")
    return display in ("standalone", "fullscreen", "minimal-ui")


def _fetch_one_lang(url, lang, memo, memo_lock):
    cache_key = f"{url}|{lang}"
    with memo_lock:
        if cache_key in memo:
            return lang, memo[cache_key]
    soup, _, manifest = extract_page_data(url, lang=lang)
    l_name = get_name(manifest) if manifest else ""
    l_summary = get_summary(soup, manifest)
    l_description = get_description(soup, manifest, l_summary)
    entry = {"name": l_name, "summary": l_summary, "description": l_description}
    with memo_lock:
        memo[cache_key] = entry
    return lang, entry


def fetch_locale_data(url, en_name, en_summary):
    """
    Fetch per-language name/summary/description via Accept-Language headers.
    Returns dict: lang → (name, summary, description).
    If the probe set (first PROBE_COUNT langs) yields nothing different from
    English, the remaining languages are skipped entirely.
    """
    memo = {}
    memo_lock = threading.Lock()

    def differs(entry):
        l_name = entry.get("name", "")
        l_summary = entry.get("summary", "")
        return (l_name and l_name != en_name) or (l_summary and l_summary != en_summary)

    def entry_to_tuple(entry):
        return (
            entry.get("name", ""),
            entry.get("summary", ""),
            entry.get("description", ""),
        )

    results = {}

    probe_langs = GNOME_LANGUAGES[:PROBE_COUNT]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_fetch_one_lang, url, lang, memo, memo_lock): lang
            for lang in probe_langs
        }
        for future in as_completed(futures):
            lang, entry = future.result()
            if differs(entry):
                results[lang] = entry_to_tuple(entry)

    if not results:
        print(
            f"    No localized content found in probe languages, "
            f"skipping remaining {len(GNOME_LANGUAGES) - PROBE_COUNT} languages."
        )
        return results

    rest_langs = GNOME_LANGUAGES[PROBE_COUNT:]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_fetch_one_lang, url, lang, memo, memo_lock): lang
            for lang in rest_langs
        }
        for future in as_completed(futures):
            lang, entry = future.result()
            if differs(entry):
                results[lang] = entry_to_tuple(entry)

    return results


def parse_input(path):
    with open(path) as f:
        data = json.load(f)
    entries = []
    for entry in data:
        url = entry["url"]
        license_expr = entry.get("license", "LicenseRef-unknown")
        oars = entry.get("oars", {})
        categories = entry.get("categories", [])
        summary = entry.get("summary", "")
        name = entry.get("name", "")
        entries.append((url, license_expr, oars, categories, summary, name))
    return entries


def fetch_app(
    url,
    input_categories,
    input_summary,
    input_name,
    en_manifest_url,
    en_manifest,
    en_soup,
    session,
    no_localize,
    input_path,
):
    """Fetch all metadata for one app. Returns a dict suitable for the cache."""
    manifest_name = get_name(en_manifest)
    en_name = input_name or manifest_name
    en_summary = get_summary(en_soup, en_manifest) or input_summary
    en_description = get_description(en_soup, en_manifest, en_summary)

    if not en_summary:
        print(f"  Warning: no summary for {url}, skipping.", file=sys.stderr)
        return None

    icon = pick_best_icon(
        en_manifest, url, manifest_url=en_manifest_url, session=session
    )
    adaptive = detect_adaptive(en_manifest)

    if input_categories:
        categories = input_categories
    else:
        manifest_cats = []
        for cat in en_manifest.get("categories", []):
            mapped = W3C_TO_APPSTREAM.get(cat.lower())
            if mapped:
                manifest_cats.append(mapped)
        categories = manifest_cats or guess_categories(en_name, en_description, url)

    if not categories:
        print(
            f"Error: no categories for {url}; add 'categories' to {input_path}.",
            file=sys.stderr,
        )
        sys.exit(1)

    screenshots = []
    for shot in en_manifest.get("screenshots", []):
        if "src" not in shot:
            continue
        src = urljoin(url, shot["src"])
        s_entry = {"src": src}
        sizes_str = shot.get("sizes", "")
        if sizes_str:
            last = sizes_str.split()[-1]
            if "x" in last:
                w, h = last.split("x", 1)
                s_entry["width"] = w
                s_entry["height"] = h
        if shot.get("label"):
            s_entry["label"] = shot["label"]
        screenshots.append(s_entry)

    locale = {}
    if not no_localize:
        print(f"  Fetching locale data ({len(GNOME_LANGUAGES)} languages)…")
        locale_data = fetch_locale_data(url, manifest_name, en_summary)
        for lang, (l_name, l_summary, l_description) in locale_data.items():
            loc_entry = {}
            if l_name and l_name != manifest_name:
                loc_entry["name"] = l_name
            if l_summary and l_summary != en_summary:
                loc_entry["summary"] = l_summary
            if l_description and l_description != en_description:
                loc_entry["description"] = l_description
            if loc_entry:
                locale[lang] = loc_entry
        if locale:
            print(f"  Found localized content for {len(locale)} language(s).")

    app_entry = {
        "name": en_name,
        "summary": en_summary,
        "adaptive": adaptive,
        "categories": categories,
        "locale": dict(sorted(locale.items())),
    }
    if en_description:
        app_entry["description"] = en_description
    if icon:
        app_entry["icon"] = icon
    if screenshots:
        app_entry["screenshots"] = screenshots
    return app_entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Input .json file (e.g. data/web-apps.json)")
    parser.add_argument(
        "cache", help="Cache .json file to write (e.g. data/web-apps-cache.json)"
    )
    parser.add_argument(
        "--no-localize",
        action="store_true",
        help="Skip per-language fetching (English-only cache)",
    )
    args = parser.parse_args()

    checksum = compute_checksum(args.input)
    entries = parse_input(args.input)
    session = requests.Session()
    new_apps = []

    for url, license_expr, oars, input_categories, input_summary, input_name in entries:
        print(f"Processing {url}")
        en_soup, en_manifest_url, en_manifest = extract_page_data(url, session=session)
        if en_manifest is None:
            print(f"  Warning: skipping {url} (no manifest).", file=sys.stderr)
            continue

        app_entry = fetch_app(
            url,
            input_categories,
            input_summary,
            input_name,
            en_manifest_url,
            en_manifest,
            en_soup,
            session,
            args.no_localize,
            args.input,
        )
        if app_entry is None:
            continue

        app_entry["url"] = url
        app_entry["license"] = license_expr
        app_entry["oars"] = oars
        new_apps.append(app_entry)

    cache_data = {
        "input_checksum": checksum,
        "apps": new_apps,
    }

    with open(args.cache, "w") as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {args.cache}")


if __name__ == "__main__":
    main()
