#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""NEWS.md, the changelog of a Haltia repository, in Russian and English,
and the AppStream releases of its metainfo made from it.

    news.py metainfo NEWS.md data/X.metainfo.xml [--check]
        write the <releases> of the metainfo from NEWS.md (--check: only
        say whether they already match; CI runs that)
    news.py bootstrap data/X.metainfo.xml > NEWS.md
        a first NEWS.md from the releases the metainfo has now

NEWS.md, newest first:

    # Что нового · What's new

    ## 2.6.0 (2026-10-20)

    ### Русский

    - Пункт списка; продолжение строки
      с отступом в два пробела.

    Абзац текста.

    ### English

    - A list item.

A release without text is a heading alone. The English text is AppStream's
untranslated one and the Russian its translation (xml:lang="ru"); a release
with Russian only has it untranslated. AppStream's own news-to-metainfo
knows no languages, hence this.
"""
import re
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

RELEASE = re.compile(r"^##\s+(\S+)\s+\((\d{4}-\d\d-\d\d)\)\s*$")
LANGS = {"русский": "ru", "english": "en"}
LANG_ATTR = "{http://www.w3.org/XML/1998/namespace}lang"


def parse(text):
    """[(version, date, {"en": blocks, "ru": blocks})]; a block is
    ("p", text) or ("ul", [items])."""
    releases = []
    lang = None
    para = []

    def flush():
        if para and releases and lang:
            releases[-1][2].setdefault(lang, []).append(("p", " ".join(para)))
        para.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        m = RELEASE.match(line)
        if m:
            flush()
            releases.append((m.group(1), m.group(2), {}))
            lang = None
            continue
        if not releases or line.startswith("# "):
            continue
        h = re.match(r"^###\s+(.+?)\s*$", line)
        if h:
            flush()
            lang = LANGS.get(h.group(1).lower())
            if lang is None:
                raise ValueError("unknown language heading: %s" % line)
            continue
        if lang is None or line.startswith("<!--"):
            continue
        blocks = releases[-1][2].setdefault(lang, [])
        if line.startswith("- "):
            flush()
            if not blocks or blocks[-1][0] != "ul":
                blocks.append(("ul", []))
            blocks[-1][1].append(line[2:].strip())
        elif line.startswith("  ") and blocks and blocks[-1][0] == "ul" and not para:
            blocks[-1][1][-1] += " " + line.strip()
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
    flush()
    return releases


def xml_releases(releases, indent="  "):
    out = [indent + "<releases>"]
    i2, i3, i4, i5 = (indent * n for n in (2, 3, 4, 5))
    for version, date, text in releases:
        if not text:
            out.append('%s<release version="%s" date="%s"/>' % (i2, version, date))
            continue
        out.append('%s<release version="%s" date="%s">' % (i2, version, date))
        out.append(i3 + "<description>")
        # English untranslated, Russian its translation; Russian alone is
        # the untranslated text itself.
        order = [("en", "")] + [("ru", ' xml:lang="ru"' if "en" in text else "")]
        for lang, attr in order:
            for kind, body in text.get(lang, []):
                if kind == "p":
                    out.append("%s<p%s>%s</p>" % (i4, attr, escape(body)))
                else:
                    out.append(i4 + "<ul>")
                    out.extend("%s<li%s>%s</li>" % (i5, attr, escape(item)) for item in body)
                    out.append(i4 + "</ul>")
        out.append(i3 + "</description>")
        out.append(i2 + "</release>")
    out.append(indent + "</releases>")
    return "\n".join(out)


def metainfo(news_path, meta_path, check):
    with open(news_path, encoding="utf-8") as fh:
        releases = parse(fh.read())
    with open(meta_path, encoding="utf-8") as fh:
        meta = fh.read()
    m = re.search(r"^([ \t]*)<releases>.*?</releases>[ \t]*$|^([ \t]*)<releases\s*/>[ \t]*$",
                  meta, re.S | re.M)
    if not m:
        sys.stderr.write("%s: no <releases> to replace\n" % meta_path)
        return 2
    indent = m.group(1) if m.group(1) is not None else m.group(2)
    new = meta[:m.start()] + xml_releases(releases, indent or "  ") + meta[m.end():]
    if check:
        if new != meta:
            sys.stderr.write("%s: its releases are not NEWS.md's; run news.py metainfo %s %s\n"
                             % (meta_path, news_path, meta_path))
            return 1
        return 0
    if new != meta:
        with open(meta_path, "w", encoding="utf-8") as fh:
            fh.write(new)
    return 0


def text_of(el):
    return " ".join("".join(el.itertext()).split())


def bootstrap(meta_path):
    root = ET.parse(meta_path).getroot()
    out = ["# Что нового · What's new", ""]
    for rel in root.iter("release"):
        out.append("## %s (%s)" % (rel.get("version"), rel.get("date", "")))
        out.append("")
        desc = rel.find("description")
        langs = {"ru": [], "en": []}
        if desc is not None:
            for el in desc:
                for item in ([el] if el.tag == "p" else list(el) if el.tag in ("ul", "ol")
                             else []):
                    text = text_of(item)
                    if not text:
                        continue
                    lang = item.get(LANG_ATTR)
                    if lang is None:  # untranslated: English, or Russian alone
                        lang = "ru" if re.search("[А-Яа-яЁё]", text) else "en"
                    if lang not in langs:
                        continue
                    langs[lang].append(("- " + text) if item.tag == "li" else text)
        for lang, title in (("ru", "Русский"), ("en", "English")):
            if langs[lang]:
                out.append("### " + title)
                out.append("")
                for line in langs[lang]:
                    out.append(line)
                    if not line.startswith("- "):
                        out.append("")
                if langs[lang][-1].startswith("- "):
                    out.append("")
    sys.stdout.write("\n".join(out).rstrip("\n") + "\n")
    return 0


def main():
    args = sys.argv[1:]
    if len(args) >= 3 and args[0] == "metainfo":
        return metainfo(args[1], args[2], "--check" in args[3:])
    if len(args) == 2 and args[0] == "bootstrap":
        return bootstrap(args[1])
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
