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

def get_manifest(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def get_info_json_url(canvas):
    service = canvas["items"][0]["items"][0]["body"]["service"][0]
    return service["id"].rstrip("/") + "/info.json"


def get_info_json_urls(manifest, start, end):
    return [
        get_info_json_url(canvas)
        for canvas in manifest["items"][start - 1:end]
    ]


def get_links(manifest_url, start_page, end_page):
    # check if manifest_url is a URL
    parsed_url = urlparse(manifest_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        # assume it's a local file path
        manifest = load_witnesses_json(manifest_url)
    else:
        manifest = get_manifest(manifest_url)
    urls = get_info_json_urls(manifest, start_page, end_page)
    for url in urls:
        print(url)

if __name__ == "__main__":
    get_links(MANIFEST_URL, START_PAGE, END_PAGE)