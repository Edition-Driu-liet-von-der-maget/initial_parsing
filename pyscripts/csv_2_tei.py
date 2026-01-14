from pathlib import Path
import re
from copy import deepcopy
import csv
from lxml import etree

out_dir = "../tei"
template_path = "../templates/tei_template.xml"
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}

def tei(tag, attributes=None):
    elem = etree.Element(f"{{{NS['tei']}}}{tag}")
    if attributes:
        for key, value in attributes.items():
            elem.set(key, value)
    return elem

def tei_sub(parent, tag):
    return etree.SubElement(parent, f"{{{NS['tei']}}}{tag}")

class MarkupResolver:
    tagchars = ["s", "a", "d", "z", "l", "r", "f", "?"]
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
    
    def find_nested_markup(markup_str: str):
        depth = 0
        max_depth = 1
        i = 0
        while i < len(markup_str):
            if markup_str[i] == "#":
                depth += 1
                max_depth = max(max_depth, depth)
                i += 2
            elif markup_str[i] == "+":
                depth -= 1
                i += 1
            else:
                i += 1
        if depth > max_depth:
            input(f"markup is nested to depth {max_depth} in string:\n{markup_str}\n")
    
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
        self.load_template(template_path)
        self.global_verse_count = 0

    def make_linegroup(self):
        lg_elem = tei("lg")
        return lg_elem
    
    def parse_verses(self):
        for verse in self.verses:
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
        
    def load_template(self, template_path: str):
        resolved_path = resolve_path_relative_to_script(template_path)
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
        out_dir_resolved = resolve_path_relative_to_script(out_dir)
        self.file_path = out_dir_resolved / file_name
        return self.file_path

    def save_to_file(self):
        with open(self.file_path, "wb") as file:
            self.tree.write(
                file, encoding="utf-8", 
                xml_declaration=True, 
                pretty_print=True
            )


def resolve_path_relative_to_script(file_path: str) -> Path:
    # check if path is absolute
    if Path(file_path).is_absolute():
        return Path(file_path)
    # else resolve relative to this script's directory
    script_dir = Path(__file__).resolve().parent
    return script_dir / file_path


# open an xml file, if none is provided open the one in ./templates/tei_template.xml
def get_tei_template(file_path: str):
    resolved_path = resolve_path_relative_to_script(file_path)
    with open(resolved_path, "r", encoding="utf-8") as file:
        tree = etree.parse(file)
    return deepcopy(tree)


def witnesses_from_csv(file_path: str):
    resolved_path = resolve_path_relative_to_script(file_path)
    if not Path(resolved_path).is_file():
        raise FileNotFoundError(f"CSV file not found: {resolved_path}")
    witnesses: dict[str, Witness] = {}
    with open(resolved_path, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for siglum in reader.fieldnames:
            witnesses[siglum] = Witness(siglum)
        for row in reader:
            for siglum, vers_str in row.items():
                witnesses[siglum].append_vers_str(vers_str)
    return witnesses


def csv_to_tei(csv_file_path: str):
    witnesses = witnesses_from_csv(csv_file_path)
    for witness in witnesses.values():
        witness.parse_verses()
        witness.set_filename()
        witness.save_to_file()
        


def test(csv_file_path: str):
    witnesses = witnesses_from_csv(csv_file_path)
    for witness in witnesses.values():
        print(f"Witness: {witness.siglum}")
        for verse in witness.verses:
            print(f"  Verse {verse.local_count} (global {verse.global_count}): '{verse.text_str}'")
            if MarkupResolver.find_unclosed_markup(verse.text_str):
                input("Warning: Unclosed markup detected!")
                

if __name__ == "__main__":
    csv_to_tei("../testdata/Probeseiten_Wernher.csv")
    test("../testdata/Probeseiten_Wernher.csv")