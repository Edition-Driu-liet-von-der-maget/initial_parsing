from pathlib import Path
from pydoc import text
import re
import logging
from copy import deepcopy
import csv
from lxml import etree

from utils import (
    resolve_path_relative_to_script,
    clear_tei_folder,
    excel_to_csv,
    user_interaction_loop,
)
from enrich_tei_with_metadata import enrich_tei_files

OUT_DIR = "../tei"
TEMPLATE_PATH = "../templates/tei_template.xml"
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
LOG_FILE = "../logs/markup_errors.log"
EXCEL_PATH = "../data/Transkription.xlsx"
SUPPORTED_TAGS = {
    "s": "sup",  # Superscript
    "a": "abbr",  # Abkürzung
    "d": "del",  # gelöscht
    "z": "add",  # Zusatz
    "l": "lig",  # Ligatur (Platzhalter)
    "r": "rub",  # Rubrizierung
    "f": "pb",  # Seitenwechsel
    "?": "unclear",  # unklar
    "^": "zirkumflex",  # circumflex-Marker
    "&": "et",  # et-Ligatur
    "i": "lombard",  # Lombarde
    "I": "initial",  # Initiale
}
csv_path = ""
# check if csv exists, else convert from excel
if not Path(resolve_path_relative_to_script(csv_path)).is_file():
    csv_path = excel_to_csv(EXCEL_PATH)


# Mapping from plain text sequences to Unicode ligature glyphs
# Used to populate the <orig> element for generic ligatures when
# no explicit ligature character was provided in the transcription.
LIGATURE_GLYPHS = {
    "ff": "\ufb00",  # ff ligature
    "fi": "\ufb01",  # fi ligature
    "fl": "\ufb02",  # fl ligature
    "ffi": "\ufb03",  # ffi ligature
    "ffl": "\ufb04",  # ffl ligature
    "ft": "\ufb05",  # ft ligature
    "st": "\ufb06",  # st ligature
}

# Vowels that already carry a circumflex; #^ does not add another mark.
CIRCUMFLEX_ALREADY = set("âêîôûÂÊÎÔÛ")
COMBINING_CIRCUMFLEX = "\u0302"


def apply_circumflex_display(text: str | None) -> str:
    """Display form for #^…+: add combining circumflex except on â ê î ô û."""
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        out.append(ch)
        if ch not in CIRCUMFLEX_ALREADY and not ch.isspace():
            # Avoid stacking if a combining circumflex is already present next
            # (handled by iterating base chars only from transcription text).
            out.append(COMBINING_CIRCUMFLEX)
    return "".join(out)


def log_markup_issue(log_path: Path, witness_siglum: str, verse: "Vers", message: str):
    logging.error(
        "%s\t%s\t\t%s\t%s",
        witness_siglum,
        f"{verse.local_count}".rjust(6),
        message,
        verse.text_str,
    )


# TEI element creation helpers
def tei(tag, attributes=None):
    elem = etree.Element(f"{{{NS['tei']}}}{tag}")
    # elem.text = ""
    # elem.tail = ""
    if attributes:
        for key, value in attributes.items():
            elem.set(key, value)
    if tag in ["l", "lg", "p"]:
        elem.tail = "\n"
    return elem


def tei_sub(parent, tag, attributes={}):
    subel = tei(tag, attributes)
    parent.append(subel)
    return subel


# Markup resolution


class MarkupResolver:
    tagchars = list(SUPPORTED_TAGS.keys())
    tag_delims = ["#", "+"]

    @staticmethod
    def find_unclosed_markup(markup_str: str):
        # find all opening tags; '+' is always a closer (no auto-correction)
        open_tags = re.findall(
            r"#([" + re.escape("".join(MarkupResolver.tagchars)) + "])", markup_str
        )
        close_tags = re.findall(r"(\+)", markup_str)
        if len(open_tags) != len(close_tags):
            return False
        return MarkupResolver.find_nested_markup(markup_str)

    @staticmethod
    def find_nested_markup(markup_str: str):
        depth = 0
        max_depth = 0
        for ch in markup_str:
            if ch == "#":
                depth += 1
                max_depth = max(max_depth, depth)
            elif ch == "+":
                depth = max(depth - 1, 0)
        # nested markup (depth > 1) is not an error for parsing, so we just
        # report whether there was any nesting at all.
        return max_depth > 1

    @staticmethod
    def analyze_markup(markup_str: str):
        errors: list[str] = []
        depth = 0
        for ch in markup_str:
            if ch == "#":
                depth += 1
            elif ch == "+":
                if depth == 0:
                    errors.append("closing '+' without matching '#'")
                else:
                    depth -= 1
        if depth != 0:
            errors.append("unbalanced markup: number of '#' and '+' does not match")
        return set(errors)

    @staticmethod
    def get_element_from_tag(tag: str):
        # erwartet Tag wie "#a"
        if not tag.startswith("#") or len(tag) != 2:
            return tei("wrong_markup")
        key = tag[1]
        tei_tag = SUPPORTED_TAGS.get(key)
        return tei(tei_tag) if tei_tag else tei("wrong_markup")

    @staticmethod
    def clip_previous_text(element: etree._Element):
        previous_elem = element.getprevious()
        if previous_elem is None:
            parent = element.getparent()
            if parent is not None and parent.text:
                if len(parent.text) == 1:
                    text = parent.text
                    parent.text = ""
                    return text
                clipped = parent.text[-1]
                parent.text = parent.text[:-1]
                return clipped
            raise ValueError(
                f"No previous text found to clip: {etree.tostring(element)}"
            )
        if previous_elem.tail:
            if len(previous_elem.tail) == 1:
                text = previous_elem.tail
                previous_elem.tail = ""
                return text
            clipped = previous_elem.tail[-1]
            previous_elem.tail = previous_elem.tail[:-1]
            return clipped
        if previous_elem.text:
            if len(previous_elem.text) == 1:
                text = previous_elem.text
                previous_elem.text = ""
                return text
            clipped = previous_elem.text[-1]
            previous_elem.text = previous_elem.text[:-1]
            return clipped
        elif previous_elem.xpath("local-name() = 'gap' and @reason = 'illegible'"):
            return ""
        else:
            raise ValueError(
                f"No previous text found to clip: {etree.tostring(element)}, found previous element: {etree.tostring(previous_elem)}\n\nParent: {etree.tostring(element.getparent())},\n\n previous_elem tail = |{type(previous_elem.tail)}|, previous_elem text = {type(previous_elem.text)}"
            )

    @staticmethod
    def translate_to_tei(element: etree._Element, siglum: str = ""):
        macron = "\u0304"
        unterlänge_strich = "\ua751"
        if element is None:
            return None
        tag_name = etree.QName(element).localname
        text = element.text
        match tag_name:
            case "sup":
                # Standard TEI choice without custom @type; form is in abbr.
                tei_choice = tei("choice")
                abbr = tei_sub(tei_choice, "abbr")
                abbr.text = text[0]
                hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                hi.text = text[-1]
                expan = tei_sub(tei_choice, "expan")
                expan.text = text
                return tei_choice
            case "abbr":
                tei_choice = tei("choice")
                abbr = tei_sub(tei_choice, "abbr")
                expan = tei_sub(tei_choice, "expan")
                expan.text = text
                if text in ["en", "em"]:
                    abbr.text = "e" + macron
                elif text in ["men", "nem"]:
                    abbr.text = "m" + macron
                elif text in ["mm", "nn"]:
                    abbr.text = text[0] + macron
                elif text in [
                    "an",
                    "am",
                    "en",
                    "em",
                    "im",
                    "in",
                    "om",
                    "omi",
                    "on",
                    "un",
                    "um",
                ]:
                    if siglum == "A":
                        prev_char = MarkupResolver.clip_previous_text(element)
                        tei_choice = tei("choice")
                        abbr = tei_sub(tei_choice, "abbr")
                        hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                        hi.text = "n"
                        abbr.append(hi)
                        abbr.text = prev_char
                        expan = tei_sub(tei_choice, "expan")
                        expan.text = text
                        return tei_choice
                    else:
                        abbr.text = text[0] + macron
                elif text == "vnd":
                    abbr.text = "v" + macron
                elif text == "nd":
                    abbr.text = "n" + macron
                elif text == "ri":
                    # superscript i on the preceding letter
                    prev_char = MarkupResolver.clip_previous_text(element)
                    tei_choice = tei("choice")
                    abbr = tei_sub(tei_choice, "abbr")
                    abbr.text = prev_char
                    hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                    hi.text = "i"
                    expan = tei_sub(tei_choice, "expan")
                    expan.text = text
                    return tei_choice
                elif text in ["per", "par"]:
                    # p with stroke through descender (U+A751)
                    abbr.text = "p" + unterlänge_strich
                elif text == "rum":
                    # r + rotunda r (U+A75B), not a literal '+'
                    abbr.text = "r" + "\ua75b"
                elif text in ["den", "dem", "dan"]:
                    abbr.text = "d" + macron
                elif text in ["ben", "hem", "ham", "len", "lem"]:
                    abbr.text = text[0] + macron
                elif text == "er":
                    # superscript "er" mark shown as raised s on preceding letter
                    prev_char = MarkupResolver.clip_previous_text(element)
                    tei_choice = tei("choice")
                    abbr = tei_sub(tei_choice, "abbr")
                    abbr.text = prev_char
                    hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                    hi.text = "s"
                    expan = tei_sub(tei_choice, "expan")
                    expan.text = text
                    return tei_choice
                elif text == "ra":
                    # preceding letter + combining tilde (U+0303)
                    prev_char = MarkupResolver.clip_previous_text(element)
                    abbr.text = prev_char + "\u0303"
                elif text == "ro":
                    # superscript, vorrausgehenden buchstaben identifizieren und superscript "°" setzen
                    prev_char = MarkupResolver.clip_previous_text(element)
                    abbr.text = prev_char + "\u030a"
                elif text == "us":
                    # preceding letter + rotunda r / us-mark (U+A75B)
                    prev_char = MarkupResolver.clip_previous_text(element)
                    abbr.text = prev_char + "\ua75b"
                elif text == "az":
                    # preceding letter + combining ur above (U+1DD1)
                    prev_char = MarkupResolver.clip_previous_text(element)
                    abbr.text = prev_char + "\u1dd1"
                else:
                    abbr.text = text
                return tei_choice
            case "del":
                tei_del = tei("del")
                tei_del.text = text
                return tei_del
            case "add":
                tei_add = tei("add")
                tei_add.text = text
                return tei_add
            case "lig":
                tei_choice = tei("choice", {"type": "ligature"})
                abbr = tei_sub(tei_choice, "orig")
                # If we know a dedicated ligature glyph for this sequence,
                # put it into <orig>; otherwise fall back to the plain text.
                abbr.text = LIGATURE_GLYPHS.get(text, text)
                reg = tei_sub(tei_choice, "reg")
                reg.text = text
                return tei_choice
            case "rub":
                tei_hi = tei("hi", {"rend": "rubric"})
                tei_hi.text = text
                return tei_hi
            case "pb":
                # erlaubt: #f12r+ -> <pb n="12r"/>
                attrs = {"n": text} if text and text.strip() else {}
                return tei("pb", attrs)
            case "unclear":
                tei_unclear = tei("unclear")
                tei_unclear.text = text
                return tei_unclear
            case "zirkumflex":
                # Keep circumflex presence in markup; display with combining
                # circumflex except on letters that already are â ê î ô û.
                tei_hi = tei("hi", {"rend": "circumflex"})
                tei_hi.text = apply_circumflex_display(text)
                return tei_hi
            case "et":
                tei_choice = tei("choice", {"type": "et_ligature"})
                abbr = tei_sub(tei_choice, "orig")
                abbr.text = "&"
                reg = tei_sub(tei_choice, "reg")
                reg.text = "et"
                return tei_choice
            case "initial":
                tei_c = tei("c", {"type": "initial"})
                tei_c.text = text
                return tei_c
            case "lombard":
                tei_c = tei("c", {"type": "lombard"})
                tei_c.text = text
                return tei_c
            case _:
                pass
        return None

    @staticmethod
    def resolve_markup(container: etree._Element, markup_str: str, siglum: str):
        errors = []
        i = 0
        stack: list[etree._Element] = []

        def emit_text(char: str):
            if not stack:
                if len(container) == 0:
                    container.text = (container.text or "") + char
                else:
                    last_elem = container[-1]
                    last_elem.tail = (last_elem.tail or "") + char
            else:
                current = stack[-1]
                if len(current) == 0:
                    current.text = (current.text or "") + char
                else:
                    last_elem = current[-1]
                    last_elem.tail = (last_elem.tail or "") + char

        def close_current():
            if not stack:
                errors.append("closing '+' without matching '#'")
                return
            old_elem = stack.pop()
            new_shiny_element = MarkupResolver.translate_to_tei(old_elem, siglum)
            if new_shiny_element is not None:
                new_shiny_element.tail = old_elem.tail
                # preserve nested children that were already translated
                for child in list(old_elem):
                    new_shiny_element.append(child)
                parent = old_elem.getparent()
                if parent is not None:
                    parent.replace(old_elem, new_shiny_element)

        while i < len(markup_str):
            if markup_str[i] == "#" and i + 1 < len(markup_str):
                tag = markup_str[i : i + 2]
                elem = MarkupResolver.get_element_from_tag(tag)
                if "wrong_markup" in elem.tag:
                    errors.append(
                        f"Unknown markup tag '{tag}' detected in {markup_str}"
                    )
                if stack:
                    stack[-1].append(elem)
                else:
                    container.append(elem)
                stack.append(elem)
                i += 2
            elif (
                markup_str[i] == "["
                and i + 5 < len(markup_str)
                and markup_str[i : i + 5] == "[...]"
            ):
                elem = tei("gap", {"reason": "illegible", "agent": "damage"})
                if stack:
                    stack[-1].append(elem)
                else:
                    container.append(elem)
                i += 5
            elif (
                markup_str[i] == "["
                and i + 2 < len(markup_str)
                and markup_str[i : i + 3] == "[…]"
            ):
                elem = tei("gap", {"reason": "illegible", "agent": "damage"})
                if stack:
                    stack[-1].append(elem)
                else:
                    container.append(elem)
                i += 3
            elif markup_str[i] == "+":
                close_current()
                i += 1
            else:
                emit_text(markup_str[i])
                i += 1
        if stack:
            errors.append("unclosed markup at end of verse")
            while stack:
                close_current()
        return errors


class Vers:
    vers_prefix = "v_"

    def __init__(
        self, global_count: int, local_count: int, text_str: str, siglum: str = ""
    ):
        self.global_count = global_count
        self.local_count = local_count
        self.text_str = text_str
        self.siglum = siglum

    def is_empty(self):
        return bool(self.text_str.strip() == "")

    def is_book_start(self):
        return False
    
    def tag_long_s(self, text: str) -> list:
        content_list = []
        for substring in re.split(r"(ſ)", text):
            if substring == "ſ":
                elem = tei("choice")
                tei_sub(elem, "orig").text = "ſ"
                tei_sub(elem, "corr").text = "s"
                content_list.append(elem)
            else:
                content_list.append(substring)
        return content_list

    def tag_long_s_in_vers(self, tei_vers: etree._Element):
        """Replace every bare 'ſ' text occurrence with <choice><orig>ſ</orig><corr>s</corr></choice>.

        Important: collect text targets first, then rewrite each as
        leading_text + (element, tail)* so multiple ſ in one node keep order
        and never overwrite earlier tails.
        """
        targets: list[tuple[etree._Element, bool, str]] = []
        for textnode in tei_vers.xpath(".//text()[contains(., 'ſ')]"):
            parent = textnode.getparent()
            if parent is None:
                continue
            # Skip ſ that already live inside a choice/orig|corr markup node.
            parent_name = etree.QName(parent).localname
            if parent_name in ("orig", "corr"):
                continue
            targets.append((parent, bool(textnode.is_text), str(textnode)))

        for parent, is_text, raw in targets:
            parts = self.tag_long_s(raw)
            leading = ""
            chunks: list[tuple[etree._Element, str]] = []
            for part in parts:
                if isinstance(part, str):
                    if not chunks:
                        leading += part
                    else:
                        el, tail = chunks[-1]
                        chunks[-1] = (el, tail + part)
                else:
                    chunks.append((part, ""))

            if is_text:
                parent.text = leading or None
                for i, (el, tail) in enumerate(chunks):
                    el.tail = tail or None
                    # Keep relative order in front of any already existing children.
                    parent.insert(i, el)
            else:
                # `parent` owns the tail being rewritten.
                parent.tail = leading or None
                last = parent
                for el, tail in chunks:
                    el.tail = tail or None
                    last.addnext(el)
                    last = el

    def to_tei(self):
        vers_elem = tei("l")
        if not self.local_count and not self.global_count:
            raise ValueError(
                "At least one of global_count or local_count must be provided"
            )
        if self.local_count != "":
            vers_elem.set(f"{{{NS['xml']}}}id", f"{self.vers_prefix}{self.local_count}")
        vers_elem.set("n", f"{self.vers_prefix}{self.global_count}")
        markup_str = self.text_str
        errors = MarkupResolver.resolve_markup(vers_elem, markup_str, self.siglum)
        self.tag_long_s_in_vers(vers_elem)
        return vers_elem, errors


class Witness:
    def __init__(self, siglum: str, file_path: str = ""):
        self.siglum = siglum
        self.verses = []
        self.template = None
        self.file_path = None
        self.root = None
        self.body = None
        self.container = None
        self.local_verses = 0
        self.load_template()
        self.add_title()
        self.add_siglum_to_header()
        self.global_verse_count = 0

    def add_siglum_to_header(self):
        idno_elem = self.root.find(
            ".//tei:msDesc/tei:msIdentifier/tei:idno[@type='siglum']", namespaces=NS
        )
        if idno_elem is not None:
            idno_elem.text = self.siglum
        else:
            print(
                f"Warning: Could not find header element for siglum in witness {self.siglum}"
            )
        # msDesc xml:id="" should be set to siglum as well for better referencing, but since it's not used in the current processing, it's not critical if it's missing. If needed, it can be added similarly to the idno element.
        msdesc_elem = self.root.find(".//tei:msDesc", namespaces=NS)
        if msdesc_elem is not None:
            msdesc_elem.set(f"{{{NS['xml']}}}id", self.siglum)

    def add_structure(self):
        reversed_section_marks = reversed(
            self.root.xpath(
                ".//tei:l[./tei:c[@type='initial' or @type='lombard']]",
                namespaces=NS,
            )
        )
        for mark in reversed_section_marks:
            lg_element = tei("lg", {"type": "sub_group"})
            mark.addprevious(lg_element)
            lg_element.append(mark)
            nex = lg_element.getnext()
            while nex is not None and etree.QName(nex).localname != "lg":
                to_move = nex
                nex = to_move.getnext()
                lg_element.append(to_move)
        initials_groups_reversed = reversed(
            self.container.xpath(
                "tei:lg[@type='sub_group' and ./tei:l[./tei:c[@type='initial']]]",
                namespaces=NS,
            )
        )
        for initial_group in initials_groups_reversed:
            lg_element = tei("lg", {"type": "group"})
            initial_group.addprevious(lg_element)
            lg_element.append(initial_group)
            nex = lg_element.getnext()
            # check if next is not another lg of type initial
            while nex is not None and not (
                etree.QName(nex).localname == "lg" and nex.get("type") == "group"
            ):
                to_move = nex
                nex = to_move.getnext()
                lg_element.append(to_move)

    def add_title(self):
        title_elem = self.root.find(".//tei:title", namespaces=NS)
        title_elem.text = f"{self.siglum} (Zeuge)"

    def parse_verses(self):
        for verse in self.verses:
            verse: Vers
            # analyze markup and route any problems to the logger
            errors = MarkupResolver.analyze_markup(verse.text_str)
            for err in errors:
                log_markup_issue(Path(LOG_FILE), self.siglum, verse, err)
            vers_elem, errors = verse.to_tei()
            for err in errors:
                log_markup_issue(Path(LOG_FILE), self.siglum, verse, err)
            self.container.append(vers_elem)

    def append_vers_str(self, vers: str):
        self.global_verse_count += 1
        empty = False
        if vers.strip() != "":
            self.local_verses += 1
        else:
            empty = True
        vers = Vers(
            global_count=self.global_verse_count,
            local_count=self.local_verses if not empty else "",
            text_str=vers,
            siglum=self.siglum,
        )
        self.verses.append(vers)

    def load_template(self):
        resolved_path = resolve_path_relative_to_script(TEMPLATE_PATH)
        with open(resolved_path, "r", encoding="utf-8") as file:
            self.tree = etree.parse(file)
        self.template = deepcopy(self.tree)
        self.root = self.tree.getroot()
        self.body = self.root.find(".//tei:text/tei:body", namespaces=NS)
        self.container = tei("lg", {"type": "witness", "n": self.siglum})
        self.body.append(self.container)

    def set_filename(self):
        if self.file_path:
            return
        file_name = f"{self.siglum}.xml"
        out_dir_resolved = resolve_path_relative_to_script(OUT_DIR)
        self.file_path = out_dir_resolved / file_name
        return self.file_path

    def save_to_file(self):
        with open(self.file_path, "wb") as file:
            print(f"Saving TEI file for witness {self.siglum} to {self.file_path}")
            self.tree.write(
                file, encoding="utf-8", xml_declaration=True, pretty_print=True
            )


def witnesses_from_csv(file_path: str):
    resolved_path = resolve_path_relative_to_script(file_path)
    if not Path(resolved_path).is_file():
        raise FileNotFoundError(f"CSV file not found: {resolved_path}")
    witnesses: dict[str, Witness] = {}
    with open(resolved_path, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        # gonna ignore the first colum (mastercounter)
        sigla = reader.fieldnames[1:]
        for siglum in sigla:
            witnesses[siglum] = Witness(siglum)
        for row in reader:
            for siglum in sigla:
                vers_str = row[siglum]
                witnesses[siglum].append_vers_str(vers_str)
    return witnesses


def csv_to_tei(csv_file_path: str):
    clear_tei_folder(OUT_DIR)
    witnesses = witnesses_from_csv(csv_file_path)
    # configure logging to write a fresh log file on each run
    logging.basicConfig(
        filename=str(resolve_path_relative_to_script(LOG_FILE)),
        filemode="w",  # overwrite on each run
        level=logging.INFO,
        format="%(levelname)s\t%(message)s",
        encoding="utf-8",
    )
    for witness in witnesses.values():
        witness.parse_verses()
        witness.add_structure()
        witness.set_filename()
        witness.save_to_file()


if __name__ == "__main__":
    user_interaction_loop()
    csv_to_tei(csv_path)
    enrich_tei_files()
