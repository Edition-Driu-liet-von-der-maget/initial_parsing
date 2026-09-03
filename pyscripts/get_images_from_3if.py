import json
import requests
from urllib.parse import urlparse
import requests

MANIFEST_URL = "https://api.onb.ac.at/iiif/presentation/v3/manifest/1003371B"
START_PAGE = 23
END_PAGE = 218

def load_witnesses_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_preferred_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        for language in ("de", "en"):
            if language in value:
                text = get_preferred_text(value[language])
                if text:
                    return text
        for localized_value in value.values():
            text = get_preferred_text(localized_value)
            if text:
                return text
        return ""
    return str(value).strip()


def get_manifest_copyright_text(manifest):
    rights = get_preferred_text(manifest.get("rights"))
    required_statement = manifest.get("requiredStatement") or {}
    label = get_preferred_text(required_statement.get("label"))
    value = get_preferred_text(required_statement.get("value"))

    parts = []
    if rights:
        parts.append(rights)
    if label and value:
        parts.append(f"{label}: {value}")
    elif value:
        parts.append(value)
    elif label:
        parts.append(label)
    return " | ".join(parts)


def get_manifest(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def load_manifest(manifest_source):
    parsed_url = urlparse(manifest_source)
    if parsed_url.scheme and parsed_url.netloc:
        return get_manifest(manifest_source)
    return load_witnesses_json(manifest_source)


def get_info_json_url(canvas):
    service = canvas["items"][0]["items"][0]["body"]["service"][0]
    return service["id"].rstrip("/") + "/info.json"


def get_info_json_urls(manifest, start, end):
    return [
        get_info_json_url(canvas)
        for canvas in manifest["items"][start - 1:end]
    ]


def get_links(manifest_url, start_page, end_page):
    manifest = load_manifest(manifest_url)
    urls = get_info_json_urls(manifest, start_page, end_page)
    for url in urls:
        print(url)

if __name__ == "__main__":
    get_links(MANIFEST_URL, START_PAGE, END_PAGE)