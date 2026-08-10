from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from lxml import etree

from utils import resolve_path_relative_to_script


NS_TEI = "http://www.tei-c.org/ns/1.0"
NS_XML = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": NS_TEI, "xml": NS_XML}


def tei(tag: str, attrs: dict[str, str] | None = None) -> etree._Element:
    elem = etree.Element(f"{{{NS_TEI}}}{tag}")
    if attrs:
        for key, value in attrs.items():
            elem.set(key, value)
    return elem


def tei_sub(parent: etree._Element, tag: str, attrs: dict[str, str] | None = None) -> etree._Element:
    child = etree.SubElement(parent, f"{{{NS_TEI}}}{tag}")
    if attrs:
        for key, value in attrs.items():
            child.set(key, value)
    return child


def parse_witness_metadata(metadata_path: Path) -> dict[str, dict]:
    with metadata_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_written_lines(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    numbers = re.findall(r"\d+", text)
    if not numbers:
        return ""
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) >= 2:
        return f"{numbers[0]}-{numbers[1]}"
    return ""


def text_or_empty(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def append_if_text(parent: etree._Element, tag: str, value: object, attrs: dict[str, str] | None = None) -> etree._Element | None:
    text = text_or_empty(value)
    if not text:
        return None
    child = tei_sub(parent, tag, attrs)
    child.text = text
    return child


def build_ms_identifier(parent: etree._Element, siglum: str, witness: dict) -> etree._Element:
    ms_identifier = tei_sub(parent, "msIdentifier")

    append_if_text(ms_identifier, "country", witness.get("country"))
    append_if_text(ms_identifier, "settlement", witness.get("city"))
    append_if_text(ms_identifier, "repository", witness.get("repository"))

    siglum_id = tei_sub(ms_identifier, "idno", {"type": "siglum"})
    siglum_id.text = siglum

    for signature in witness.get("signatures", []):
        append_if_text(ms_identifier, "idno", signature, {"type": "signature"})

    hc_id = witness.get("handschriftencensus_id")
    if hc_id is not None:
        append_if_text(ms_identifier, "idno", hc_id, {"type": "handschriftencensus_id"})

    append_if_text(ms_identifier, "idno", witness.get("handschriftencensus_url"), {"type": "handschriftencensus_url"})
    return ms_identifier


def build_ms_contents(parent: etree._Element, witness: dict) -> etree._Element | None:
    metadata = witness.get("metadata", {})
    content_items = metadata.get("content", [])
    language = metadata.get("language")

    if not content_items and not language:
        return None

    ms_contents = tei_sub(parent, "msContents")

    if content_items:
        summary = tei_sub(ms_contents, "summary")
        summary.text = " ; ".join(str(item) for item in content_items)

    append_if_text(ms_contents, "textLang", language)
    return ms_contents


def build_phys_desc(parent: etree._Element, witness: dict) -> etree._Element | None:
    codicology = witness.get("metadata", {}).get("codicology", {})
    if not codicology:
        return None

    phys_desc = tei_sub(parent, "physDesc")
    object_desc = tei_sub(phys_desc, "objectDesc")
    support_desc = tei_sub(object_desc, "supportDesc")
    support = tei_sub(support_desc, "support")

    material = text_or_empty(codicology.get("material"))
    if material:
        material_el = tei_sub(support, "material")
        material_el.text = material

    append_if_text(support, "p", codicology.get("extent"), {"type": "extent"})
    append_if_text(support, "p", codicology.get("leaf_size"), {"type": "leaf_size"})
    append_if_text(support, "p", codicology.get("writing_area"), {"type": "writing_area"})

    columns = codicology.get("columns")
    lines_raw = codicology.get("lines_per_page")
    verse_layout = codicology.get("verse_layout")
    features = codicology.get("features", [])

    if columns is not None or lines_raw is not None or verse_layout or features:
        layout_desc = tei_sub(object_desc, "layoutDesc")
        layout_attrs: dict[str, str] = {}
        if columns is not None:
            layout_attrs["columns"] = str(columns)
        written_lines = extract_written_lines(lines_raw)
        if written_lines:
            layout_attrs["writtenLines"] = written_lines
        layout = tei_sub(layout_desc, "layout", layout_attrs)
        append_if_text(layout, "p", lines_raw, {"type": "lines_per_page"})
        append_if_text(layout, "p", verse_layout, {"type": "verse_layout"})
        if features:
            append_if_text(layout, "p", "; ".join(str(item) for item in features), {"type": "features"})

    return phys_desc


def build_history(parent: etree._Element, witness: dict) -> etree._Element | None:
    metadata = witness.get("metadata", {})
    date_text = metadata.get("date")
    origin_text = metadata.get("origin")
    former_locations = witness.get("former_locations", [])

    if not date_text and not origin_text and not former_locations:
        return None

    history = tei_sub(parent, "history")
    if date_text or origin_text:
        origin = tei_sub(history, "origin")
        append_if_text(origin, "origDate", date_text)
        append_if_text(origin, "origPlace", origin_text)

    if former_locations:
        provenance = tei_sub(history, "provenance")
        provenance.text = " ; ".join(str(item) for item in former_locations)

    return history


def build_additional_notes(parent: etree._Element, witness: dict) -> None:
    notes = witness.get("notes", [])
    if not notes:
        return
    additional = tei_sub(parent, "additional")
    for note_text in notes:
        append_if_text(additional, "note", note_text, {"type": "editorial"})


def build_parts(parent: etree._Element, witness: dict) -> None:
    parts = witness.get("parts", [])
    for index, part in enumerate(parts, start=1):
        ms_part = tei_sub(parent, "msPart", {"n": str(index)})
        part_identifier = tei_sub(ms_part, "msIdentifier")

        append_if_text(part_identifier, "country", part.get("country"))
        append_if_text(part_identifier, "settlement", part.get("city"))
        append_if_text(part_identifier, "repository", part.get("repository"))
        append_if_text(part_identifier, "idno", part.get("signature"), {"type": "signature"})

        former_locations = part.get("former_locations", [])
        if former_locations:
            part_history = tei_sub(ms_part, "history")
            provenance = tei_sub(part_history, "provenance")
            provenance.text = " ; ".join(str(item) for item in former_locations)

        extent = text_or_empty(part.get("extent"))
        if extent:
            part_phys = tei_sub(ms_part, "physDesc")
            object_desc = tei_sub(part_phys, "objectDesc")
            support_desc = tei_sub(object_desc, "supportDesc")
            support = tei_sub(support_desc, "support")
            extent_el = tei_sub(support, "extent")
            extent_el.text = extent


def replace_ms_desc(root: etree._Element, siglum: str, witness: dict) -> bool:
    source_desc = root.find(".//tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces=NS)
    if source_desc is None:
        return False

    placeholder = source_desc.find("tei:p", namespaces=NS)
    if placeholder is not None:
        source_desc.remove(placeholder)

    for old_ms_desc in source_desc.findall("tei:msDesc", namespaces=NS):
        source_desc.remove(old_ms_desc)

    ms_desc = tei_sub(source_desc, "msDesc", {f"{{{NS_XML}}}id": siglum})
    build_ms_identifier(ms_desc, siglum, witness)
    build_ms_contents(ms_desc, witness)
    build_phys_desc(ms_desc, witness)
    build_history(ms_desc, witness)
    build_additional_notes(ms_desc, witness)
    build_parts(ms_desc, witness)
    return True


def infer_siglum_from_file(tei_path: Path, root: etree._Element) -> str:
    by_idno = root.find(".//tei:sourceDesc/tei:msDesc/tei:msIdentifier/tei:idno[@type='siglum']", namespaces=NS)
    if by_idno is not None and by_idno.text and by_idno.text.strip():
        return by_idno.text.strip()
    return tei_path.stem


def enrich_tei_files(metadata_path: str = "../metadata/witnesses.json", tei_dir: str = "../tei") -> tuple[int, int, list[str]]:
    metadata_file = resolve_path_relative_to_script(metadata_path)
    tei_folder = resolve_path_relative_to_script(tei_dir)

    metadata = parse_witness_metadata(metadata_file)
    processed = 0
    updated = 0
    missing: list[str] = []

    for tei_file in sorted(tei_folder.glob("*.xml")):
        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(str(tei_file), parser)
        root = tree.getroot()

        siglum = infer_siglum_from_file(tei_file, root)
        witness = metadata.get(siglum)
        processed += 1

        if witness is None:
            missing.append(siglum)
            continue

        changed = replace_ms_desc(root, siglum, witness)
        if changed:
            tree.write(
                str(tei_file),
                encoding="utf-8",
                xml_declaration=True,
                pretty_print=True,
            )
            updated += 1

    return processed, updated, missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject witness JSON metadata into generated TEI headers (msDesc)."
    )
    parser.add_argument(
        "--metadata",
        default="../metadata/witnesses.json",
        help="Path to witness metadata JSON (relative to this script or absolute).",
    )
    parser.add_argument(
        "--tei-dir",
        default="../tei",
        help="Directory containing TEI files to enrich.",
    )
    args = parser.parse_args()

    processed, updated, missing = enrich_tei_files(args.metadata, args.tei_dir)
    print(f"Processed TEI files: {processed}")
    print(f"Updated TEI files:   {updated}")
    if missing:
        print("Missing metadata for sigla:", ", ".join(sorted(set(missing))))


if __name__ == "__main__":
    main()