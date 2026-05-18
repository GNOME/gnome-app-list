#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 GNOME Foundation, Inc.
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Generate AppStream metainfo for web applications from a pre-fetched cache.

Usage: generate_web_apps.py INPUT.json CACHE.json OUTPUT.xml

INPUT.json  — web app list (read only to verify CACHE.json is current)
CACHE.json  — pre-fetched metadata written by update_web_apps.py
OUTPUT.xml  — AppStream XML to produce

No network access is performed. If CACHE.json is missing or out of date
with respect to INPUT.json, an error is printed with the command to run.
"""

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET


def app_id_for_url(url):
    return (
        "org.gnome.Software.WebApp_"
        + hashlib.sha1(url.encode()).hexdigest()
        + ".desktop"
    )


def compute_checksum(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_and_verify_cache(input_path, cache_path):
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except FileNotFoundError:
        print(
            f"Error: {cache_path} does not exist.\n"
            f"Run: python3 scripts/update_web_apps.py {input_path} {cache_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    expected = compute_checksum(input_path)
    actual = cache.get("input_checksum", "")

    if actual != expected:
        print(
            f"Error: {cache_path} is out of date"
            f" (checksum mismatch with {input_path}).\n"
            f"Run: python3 scripts/update_web_apps.py {input_path} {cache_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    return cache["apps"]


def build_component(app, input_path):
    """Build an ET.Element for one web-app component from cached data."""
    url = app["url"]
    license_expr = app.get("license", "LicenseRef-unknown")
    oars_ratings = app.get("oars", {})
    categories = app.get("categories", [])
    en_name = app.get("name", "")
    en_summary = app.get("summary", "")
    en_description = app.get("description", "")
    icon = app.get("icon")
    adaptive = app.get("adaptive", True)
    locale = app.get("locale", {})
    screenshots = app.get("screenshots", [])

    if not en_summary:
        print(f"  Warning: no summary for {url}, skipping.", file=sys.stderr)
        return None

    if not categories:
        print(
            f"Error: no categories for {url}. "
            f"Add 'categories' to {input_path} and re-run update_web_apps.py.",
            file=sys.stderr,
        )
        sys.exit(1)

    comp = ET.Element("component")
    comp.set("type", "web-application")

    ET.SubElement(comp, "launchable", type="url").text = url
    ET.SubElement(comp, "url", type="homepage").text = url
    ET.SubElement(comp, "project_license").text = license_expr
    ET.SubElement(comp, "metadata_license").text = "FSFAP"

    ET.SubElement(comp, "name").text = en_name
    for lang, loc in locale.items():
        l_name = loc.get("name")
        if l_name:
            el = ET.SubElement(comp, "name")
            el.set("xml:lang", lang)
            el.text = l_name

    ET.SubElement(comp, "id").text = app_id_for_url(url)

    if icon:
        el = ET.SubElement(comp, "icon")
        el.set("type", "remote")
        el.set("width", str(icon["width"]))
        el.set("height", str(icon["height"]))
        el.text = icon["src"]

    if screenshots:
        shots_el = ET.SubElement(comp, "screenshots")
        for shot in screenshots:
            shot_el = ET.SubElement(shots_el, "screenshot")
            shot_el.set("type", "default")
            img_el = ET.SubElement(shot_el, "image")
            img_el.text = shot["src"]
            if "width" in shot:
                img_el.set("width", shot["width"])
            if "height" in shot:
                img_el.set("height", shot["height"])
            if "label" in shot:
                ET.SubElement(shot_el, "caption").text = shot["label"]

    cats_el = ET.SubElement(comp, "categories")
    for cat in categories:
        ET.SubElement(cats_el, "category").text = cat

    if oars_ratings:
        rating_el = ET.SubElement(comp, "content_rating")
        rating_el.set("type", "oars-1.1")
        for key, val in oars_ratings.items():
            attr_el = ET.SubElement(rating_el, "content_attribute")
            attr_el.set("id", key)
            attr_el.text = val

    rec_el = ET.SubElement(comp, "recommends")
    ET.SubElement(rec_el, "control").text = "pointing"
    ET.SubElement(rec_el, "control").text = "keyboard"
    if adaptive:
        ET.SubElement(rec_el, "control").text = "touch"
    disp_el = ET.SubElement(rec_el, "display_length")
    disp_el.set("compare", "ge")
    disp_el.text = "360" if adaptive else "768"

    ET.SubElement(comp, "summary").text = en_summary
    for lang, loc in locale.items():
        l_summary = loc.get("summary")
        if l_summary:
            el = ET.SubElement(comp, "summary")
            el.set("xml:lang", lang)
            el.text = l_summary

    en_desc_text = en_description if en_description else en_summary
    desc_el = ET.SubElement(comp, "description")
    ET.SubElement(desc_el, "p").text = en_desc_text
    for lang, loc in locale.items():
        l_desc = loc.get("description") or loc.get("summary")
        if l_desc and l_desc != en_desc_text:
            desc_el2 = ET.SubElement(comp, "description")
            desc_el2.set("xml:lang", lang)
            ET.SubElement(desc_el2, "p").text = l_desc

    return comp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Input .json file (to verify cache is current)")
    parser.add_argument("cache", help="Cache .json file with pre-fetched data")
    parser.add_argument("output", help="Output AppStream .xml file")
    args = parser.parse_args()

    apps = load_and_verify_cache(args.input, args.cache)

    components_el = ET.Element("components")
    components_el.set("version", "0.15")

    for app in apps:
        comp = build_component(app, args.input)
        if comp is not None:
            components_el.append(comp)

    tree = ET.ElementTree(components_el)
    ET.indent(tree)
    tree.write(args.output, xml_declaration=True, encoding="utf-8", method="xml")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
