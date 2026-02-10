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

OUT_DIR = "../tei"
TEMPLATE_PATH = "../templates/tei_template.xml"
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
LOG_FILE = "../logs/markup_errors.log"
EXCEL_PATH = "../data/Transkription.xlsx"
csv_path = ""
# check if csv exists, else convert from excel
if not Path(resolve_path_relative_to_script(csv_path)).is_file():
    csv_path = excel_to_csv(EXCEL_PATH)


# Mapping from plain text sequences to Unicode ligature glyphs
# Used to populate the <orig> element for generic ligatures when
# no explicit ligature character was provided in the transcription.
LIGATURE_GLYPHS = {
    "ff": "\uFB00",   # ff ligature
    "fi": "\uFB01",   # fi ligature
    "fl": "\uFB02",   # fl ligature
    "ffi": "\uFB03",  # ffi ligature
    "ffl": "\uFB04",  # ffl ligature
    "ft": "\uFB05",   # ft ligature
    "st": "\uFB06",   # st ligature
}


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
    if attributes:
        for key, value in attributes.items():
            elem.set(key, value)
    return elem


def tei_sub(parent, tag, attributes={}):
    return etree.SubElement(parent, f"{{{NS['tei']}}}{tag}", attributes)


# Markup resolution


class MarkupResolver:
    tagchars = [
        "s",
        "a",
        "d",
        "z",
        "l",
        "r",
        "f",
        "?",
        "^",
        "&",
        "i",
    ]
    tag_delims = ["#", "+"]

    @staticmethod
    def find_unclosed_markup(markup_str: str):
        # find all opening tags
        open_tags = re.findall(
            r"#([" + "".join(MarkupResolver.tagchars) + "])", markup_str
        )
        close_tags = re.findall(r"(\+)", markup_str)
        if len(open_tags) != len(close_tags):
            # replace cases in which a + is used instead of #
            new_markup_str = re.sub(
                r"\+([" + "".join(MarkupResolver.tagchars) + "])",
                r"#\1",
                markup_str,
                count=1,
            )
            if new_markup_str != markup_str:
                print(
                    f"Corrected markup string from:\n{markup_str}\nto:\n{new_markup_str}\n"
                )
                return MarkupResolver.find_unclosed_markup(new_markup_str)
        else:
            return MarkupResolver.find_nested_markup(markup_str)
        return False

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
            if depth > 1:
                errors.append("nested markup detected")
            if ch == "#":
                depth += 1
            elif ch == "+":
                if depth == 0:
                    errors.append("closing '+' without matching '#'")
                depth -= 1
        if depth != 0:
            errors.append(
                "unbalanced markup: number of '#' and '+' does not match")
        return set(errors)

    @staticmethod
    def get_element_from_tag(tag: str):
        match tag:
            case "#s":
                return tei("sup")  # Superskripte
            case "#a":
                return tei("abbr")  # abbreviation
            case "#d":
                return tei("del")  # gelöscht
            case "#z":
                return tei("add")  # Zusatz
            case "#l":
                return tei("lig")  # de-Ligatur
            case "#r":
                return tei("rub")  # Rubrizierungen
            case "#f":
                return tei("pb")  # Seitenwechsel
            case "#?":
                return tei("unclear")  # unclear
            case "#I":
                return tei("initial")  # initial
            case "#i":
                return tei("lombard")  # lombard
            case "#^":
                return tei("zirkumflex")  # supplied -> informatives Markup
            case "#&":
                return tei("et")  # et-ligature
            case _:
                return tei("wrong_markup")  # unbekanntes Markup

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
                else:
                    parent.text = parent.text[:-1]
                    return parent.text[-1]
        if previous_elem.tail:
            if len(previous_elem.tail) == 1:
                text = previous_elem.tail
                previous_elem.tail = ""
                return text
            else:
                previous_elem.tail = previous_elem.tail[:-1]
                return previous_elem.tail[-1]
        elif previous_elem.text:
            if len(previous_elem.text) == 1:
                text = previous_elem.text
                previous_elem.text = ""
                return text
            else:
                previous_elem.text = previous_elem.text[:-1]
                return previous_elem.text[-1]
        raise ValueError(
            f"No previous text found to clip: {etree.tostring(element)}")

    @staticmethod
    def translate_to_tei(element: etree._Element, siglum: str):
        macron = "\u0304"
        unterlänge_strich = "\uA751"
        is_end_of_word = bool(element.tail)
        previous_text = ""
        siglum = ""
        if element is None:
            return None
        tag_name = etree.QName(element).localname
        text = element.text
        match tag_name:
            case "sup":
                tei_choice = tei("choice", {"type": "superscript"})
                abbr = tei_sub(tei_choice, "abbr")
                abbr.text = text[0]
                hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                hi.text = text[-1]
                expan = tei_sub(tei_choice, "expan")
                expan.text = text
                return tei_choice
            case "abbr":
                tei_choice = tei("choice", {"type": "abbreviation"})
                abbr = tei_sub(tei_choice, "abbr")
                expan = tei_sub(tei_choice, "expan")
                expan.text = text
                if text in ["en", "em"]:
                    abbr.text = "e" + macron
                elif text in ["men", "nem"]:
                    abbr.text = "m" + macron
                elif text in ["mm,", "nn"]:
                    abbr.text = text[0] + macron
                elif text in ["an", "am", "en", "em", "im", "in", "om", "on", "un", "um"]:
                    if siglum == "A":
                        prev_char = MarkupResolver.clip_previous_text(element)
                        tei_choice = tei("choice", {"type": "superscript"})
                        abbr = tei_sub(tei_choice, "abbr")
                        abbr.text = prev_char
                        hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                        hi.text = "n"
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
                    # superscript, vorrausgehenden buchstaben identifizieren und superscript "i" setzen
                    prev_char = MarkupResolver.clip_previous_text(element)
                    tei_choice = tei("choice", {"type": "superscript"})
                    abbr = tei_sub(tei_choice, "abbr")
                    abbr.text = prev_char
                    hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                    hi.text = "i"
                    expan = tei_sub(tei_choice, "expan")
                    expan.text = text
                    return tei_choice
                elif text in ["per", "par"]:
                    # p mit strich durch die Unterlänge
                    abbr.text = "p" + unterlänge_strich
                elif text == "rum":
                    abbr.text = "r+" + "\uA75B"
                elif text in ["den", "dem", "dan"]:
                    abbr.text = "d" + macron
                elif text in ["ben", "hem", "ham", "len", "lem"]:
                    abbr.text = text[0] + macron
                elif text == "er":
                    # superscript, vorrausgehenden buchstaben identifizieren und superscript "Supermanzeichen"setzen
                    prev_char = MarkupResolver.clip_previous_text(element)
                    tei_choice = tei("choice", {"type": "superscript"})
                    abbr = tei_sub(tei_choice, "abbr")
                    abbr.text = prev_char
                    hi = tei_sub(abbr, "hi", {"rend": "superscript"})
                    hi.text = "s"
                    expan = tei_sub(tei_choice, "expan")
                    expan.text = text
                    return tei_choice
                elif text == "ra":
                    # superscript, vorrausgehenden buchstaben identifizieren und superscript "tilde" setzen
                    prev_char = MarkupResolver.clip_previous_text(element)
                    abbr.text = prev_char + "\u0303"
                elif text == "ra":
                    # superscript, vorrausgehenden buchstaben identifizieren und superscript "°" setzen
                    prev_char = MarkupResolver.clip_previous_text(element)
                    abbr.text = prev_char + "\u030A"
                elif text == "us":
                    # vorrausgehenden buchstaben identifizieren und danach "halbes herz" setzen
                    prev_char = MarkupResolver.clip_previous_text(element)
                    # abbr.text = prev_char + "\ua770"
                    abbr.text = prev_char + "\ua75b"
                elif text == "az":
                    # vorrausgehenden buchstaben identifizieren und danach "c" setzen
                    prev_char = MarkupResolver.clip_previous_text(element)
                    abbr.text = prev_char + " \u1dd1"
                else:
                    abbr.text = text
                return tei_choice
            case "del":
                pass
            case "add":
                pass
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
                tei_hi = tei("hi", {"rend": "rubrication"})
                tei_hi.text = text
                return tei_hi
            case "pb":
                pass
            case "unclear":
                pass
            case "zirkumflex":
                pass
            case "et":
                tei_choice = tei("choice", {"type": "et_ligature"})
                abbr = tei_sub(tei_choice, "orig")
                abbr.text = "&"
                reg = tei_sub(tei_choice, "reg")
                reg.text = "et"
                return tei_choice
            case "initial":
                tei_hi = tei("hi", {"rend": "initial"})
                tei_hi.text = text
                return tei_hi
            case "lombard":
                tei_hi = tei("hi", {"rend": "lombard"})
                tei_hi.text = text
                return tei_hi
            case _:
                pass
        return None

    @staticmethod
    def resolve_markup(container: etree._Element, markup_str: str, siglum: str):
        errors = []
        i = 0
        current_elem = None
        while i < len(markup_str):
            if (
                markup_str[i] == "#" or (
                    markup_str[i] == "+" and current_elem is None)
            ) and i + 1 < len(markup_str):
                tag = markup_str[i: i + 2]
                elem = MarkupResolver.get_element_from_tag(tag)
                if "wrong_markup" in elem.tag:
                    print(
                        f"Warning: Unknown markup tag \n'{tag}' \ndetected in \n{markup_str}\n"
                    )
                    # must log these too!
                    errors.append(
                        f"Unknown markup tag '{tag}' detected in {markup_str}")
                container.append(elem)
                current_elem = elem
                i += 2
            elif markup_str[i] == "+":
                # closes current element, time to convert it to actual TEI
                if current_elem is not None:
                    old_elem = current_elem
                    # get previous char to decide on nasalstrich handling
                    new_shiny_element = MarkupResolver.translate_to_tei(
                        old_elem, siglum)
                    if new_shiny_element is not None and old_elem is not None:
                        new_shiny_element.tail = old_elem.tail
                        parent = old_elem.getparent()
                        if parent is not None:
                            parent.replace(old_elem, new_shiny_element)
                    current_elem = None
                i += 1
            else:
                char = markup_str[i]
                i += 1
                if current_elem is None:
                    if len(container) == 0:
                        container.text = (container.text or "") + char
                    else:
                        last_elem = container[-1]
                        last_elem.tail = (last_elem.tail or "") + char
                else:
                    current_elem.text = (current_elem.text or "") + char
        return errors


class Vers:
    vers_prefix = "v"

    def __init__(self, global_count: int, local_count: int, text_str: str, siglum: str = ""):
        self.global_count = global_count
        self.local_count = local_count
        self.text_str = text_str
        self.siglum = siglum

    def is_empty(self):
        return bool(self.text_str.strip() == "")

    def is_book_start(self):
        return False

    def to_tei(self):
        vers_elem = tei("l")
        if not self.local_count and not self.global_count:
            raise ValueError("At least one of global_count or local_count must be provided")
        if self.local_count != "":
            vers_elem.set(f"{{{NS['xml']}}}id", f"{self.vers_prefix}{self.local_count}")
        vers_elem.set("n", f"{self.vers_prefix}{self.global_count}")
        errors = MarkupResolver.resolve_markup(vers_elem, self.text_str, self.siglum)
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
        self.global_verse_count = 0


    def add_structure(self):
        reversed_section_marks = reversed(
            self.root.xpath(
                ".//tei:l[./tei:hi[@rend='initial' or @rend='lombard']]",
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
        initials_groups_reversed = reversed(self.root.xpath("tei:lg[@type='sub_group' and ./tei:l[./tei:hi[@rend='initial']]]", namespaces=NS))
        for initial_group in initials_groups_reversed:
            lg_element = tei("lg", {"type": "group"})
            initial_group.addprevious(lg_element)
            lg_element.append(initial_group)
            nex = lg_element.getnext()
            # check if next is not another lg of type initial
            while nex is not None and not (etree.QName(nex).localname == "lg" and nex.get("type") == "group"):
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
            siglum=self.siglum
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
