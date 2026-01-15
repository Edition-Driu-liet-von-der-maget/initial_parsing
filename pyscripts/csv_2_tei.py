from pathlib import Path
from time import sleep
import sys
import select
import re
import logging
from copy import deepcopy
import csv
from lxml import etree

from utils import resolve_path_relative_to_script, clear_tei_folder, excel_to_csv

OUT_DIR = "../tei"
TEMPLATE_PATH = "../templates/tei_template.xml"
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
LOG_FILE = "../logs/markup_errors.log"
EXCEL_PATH = "../testdata/Transkription.xlsx"
csv_path = ""
# check if csv exists, else convert from excel
if not Path(resolve_path_relative_to_script(csv_path)).is_file():
    csv_path = excel_to_csv(EXCEL_PATH)

## utils

def log_markup_issue(log_path: Path, witness_siglum: str, verse: "Vers", message: str):
    logging.error(
        "%s\t%s\t%s\t%s\t%s",
        witness_siglum,
        verse.global_count,
        verse.local_count,
        message,
        verse.text_str,
    )

## TEI element creation helpers
def tei(tag, attributes=None):
    elem = etree.Element(f"{{{NS['tei']}}}{tag}")
    if attributes:
        for key, value in attributes.items():
            elem.set(key, value)
    return elem

def tei_sub(parent, tag):
    return etree.SubElement(parent, f"{{{NS['tei']}}}{tag}")


### Markup resolution

class MarkupResolver:
    tagchars = ["s", "a", "d", "z", "l", "r", "f", "?", "^", "&", ]
    tag_delims = ["#", "+"]

    @staticmethod
    def find_unclosed_markup(markup_str: str):
        # find all opening tags
        open_tags = re.findall(r"#([" + "".join(MarkupResolver.tagchars) + "])", markup_str)
        close_tags = re.findall(r"(\+)", markup_str)
        if len(open_tags) != len(close_tags):
            # replace cases in which a + is used instead of #
            new_markup_str = re.sub(
                r"\+([" + "".join(MarkupResolver.tagchars) + "])",
                r"#\1",
                markup_str,
                count=1
            )
            if new_markup_str != markup_str:
                print(f"Corrected markup string from:\n{markup_str}\nto:\n{new_markup_str}\n")
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
            errors.append("unbalanced markup: number of '#' and '+' does not match")
        return errors
    
    @staticmethod
    def get_element_from_tag(tag: str):
        match tag:
            case "#s" : return tei("sup") # Superskripte
            case "#a" : return tei("abbr") # Abbreviaturen
                #     kombiniert: Nasalstrich, ri, par
                # "  "   tei(""), kombiniert: Nasalstrich, ri, par
                # #     separat: er, ro, us
                # "  "   tei(""), separat: er, ro, us
                # #     Sonderfälle: d(omi)ni, isr(ahe)l, Math(eu)s
                # "  "   tei(""), Sonderfälle: d(omi)ni, isr(ahe)l, Math(eu)s
            case "#d" : return tei("del") # gelöscht
            case "#z" : return tei("add") # Zusatz
            case "#l" : return tei("lig") # de-Ligatur
            case "#r" : return tei("rub") # Rubrizierungen
            case "#f" : return tei("pb") # Seitenwechsel
            case "#?" : return tei("unclear") #unclear
            
            case "#^" : return tei("zirkumflex") #supplied
            case "#&" : return tei("et") #gap
            case _    : return tei("wrong_markup") # unbekanntes Markup

    @staticmethod
    def resolve_markup(container: etree._Element, markup_str: str):
        i = 0
        current_elem = None
        while i < len(markup_str):
            if (markup_str[i] == "#" or (markup_str[i] == "+" and current_elem is None)) and i + 1 < len(markup_str):
                tag = markup_str[i:i+2]
                elem = MarkupResolver.get_element_from_tag(tag)
                if "wrong_markup" in elem.tag:
                    print(f"Warning: Unknown markup tag \n'{tag}' \ndetected in \n{markup_str}\n")
                container.append(elem)
                current_elem = elem
                i += 2
            elif markup_str[i] == "+":
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

class Vers:
    vers_prefix = "v"
    def __init__(self, global_count: int, local_count: int, text_str: str):
        self.global_count = global_count
        self.local_count = local_count
        self.text_str = text_str
    
    def is_empty(self):
        return bool(self.text_str.strip() == "")
    
    def is_book_start(self):
        return False
    
    def to_tei(self):
        vers_elem = tei("l")
        vers_elem.set(f"{{{NS['xml']}}}id", f"{self.vers_prefix}{self.global_count}")
        vers_elem.set("n", f"{self.vers_prefix}{self.local_count}")
        MarkupResolver.resolve_markup(vers_elem, self.text_str)
        return vers_elem

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
        self.global_verse_count = 0

    def make_linegroup(self):
        lg_elem = tei("lg")
        return lg_elem
    
    def parse_verses(self):
        for verse in self.verses:
            # analyze markup and route any problems to the logger
            errors = MarkupResolver.analyze_markup(verse.text_str)
            for err in errors:
                log_markup_issue(Path(LOG_FILE), self.siglum, verse, err)
            vers_elem = verse.to_tei()
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
            text_str=vers
        )
        self.verses.append(vers)
        
    def load_template(self):
        resolved_path = resolve_path_relative_to_script(TEMPLATE_PATH)
        with open(resolved_path, "r", encoding="utf-8") as file:
            self.tree = etree.parse(file)
        self.template = deepcopy(self.tree)
        self.root = self.tree.getroot()
        self.body = self.root.find(".//tei:text/tei:body", namespaces=NS)
        self.container = self.make_linegroup()
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
                file, encoding="utf-8", 
                xml_declaration=True, 
                pretty_print=True
            )

## Main functions

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
        witness.set_filename()
        witness.save_to_file()


if __name__ == "__main__":
    nl3 = '\n' * 3
    hash80 = '#' * 80
    print(f"{nl3}{hash80}{nl3}\nAttention, this will delete all files in the TEI output folder before processing!{nl3}{hash80}")
    sleep_countdown = 5
    print("Press Enter to start immediately, or type anything and press Enter to abort.")

    for i in range(sleep_countdown, 0, -1):
        print(f"Continuing in {i} seconds... (press Enter to continue, any other input to abort)")
        # Wait up to 1 second for user input
        rlist, _, _ = select.select([sys.stdin], [], [], 1)
        if rlist:
            line = sys.stdin.readline()
            if line.strip() == "":
                # Empty line: user pressed Enter only -> skip countdown
                break
            else:
                print("Aborted by user input.")
                sys.exit(0)
    csv_to_tei(csv_path)