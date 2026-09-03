import csv
import glob
import io
import ipaddress
import os
import re
import socket
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yagmail

from cache import *
from status import *
from config import *

MAX_SCRAPER_ZIP_BYTES = 100 * 1024 * 1024
MAX_SCRAPER_EXTRACTED_BYTES = 300 * 1024 * 1024
HTTP_TIMEOUT = (10, 30)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _validate_public_http_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP(S) URLs are allowed")
    host = parsed.hostname
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError(f"Refusing non-public URL target: {host}")
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve URL host: {host}") from exc
    return str(url).strip()


def _safe_get(url: str, *, max_bytes: int = 20 * 1024 * 1024) -> requests.Response:
    current = _validate_public_http_url(url)
    for _ in range(5):
        response = requests.get(current, stream=True, timeout=HTTP_TIMEOUT, allow_redirects=False)
        if 300 <= response.status_code < 400 and response.headers.get("Location"):
            location = urljoin(current, response.headers["Location"])
            response.close()
            current = _validate_public_http_url(location)
            continue
        response.raise_for_status()
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            response.close()
            raise ValueError("Response exceeds configured size limit")
        chunks = []
        total = 0
        for chunk in response.iter_content(1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                response.close()
                raise ValueError("Response exceeds configured size limit")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        response.close()
        return response
    raise ValueError("Too many redirects")


class Outreach:
    """Methods used to find businesses and send configured outreach emails."""

    def __init__(self) -> None:
        self.go_installed = self.is_go_installed()
        self.niche = get_google_maps_scraper_niche()
        self.email_creds = get_email_credentials()

    def _find_scraper_dir(self) -> str:
        candidates = sorted(glob.glob("google-maps-scraper-*"))
        for candidate in candidates:
            if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "go.mod")):
                return candidate
        return ""

    def is_go_installed(self) -> bool:
        try:
            return subprocess.run(["go", "version"], check=False, capture_output=True).returncode == 0
        except OSError:
            return False

    def unzip_file(self, zip_link: str) -> None:
        if self._find_scraper_dir():
            info("=> Scraper already unzipped. Skipping unzip.")
            return

        response = _safe_get(zip_link, max_bytes=MAX_SCRAPER_ZIP_BYTES)
        if not response.content.startswith(b"PK"):
            raise ValueError("Configured scraper URL did not return a ZIP archive")

        total_extracted = 0
        destination = Path.cwd().resolve()
        with zipfile.ZipFile(io.BytesIO(response.content), "r") as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = member.filename.replace("\\", "/")
                target = (destination / name).resolve()
                try:
                    target.relative_to(destination)
                except ValueError:
                    warning(f"Skipping suspicious archive path: {member.filename}")
                    continue
                total_extracted += member.file_size
                if total_extracted > MAX_SCRAPER_EXTRACTED_BYTES:
                    raise ValueError("Scraper archive expands beyond the configured size limit")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, open(target, "wb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)

    def build_scraper(self) -> None:
        binary_name = "google-maps-scraper.exe" if os.name == "nt" else "google-maps-scraper"
        if os.path.exists(binary_name):
            print(colored("=> Scraper already built. Skipping build.", "blue"))
            return
        scraper_dir = self._find_scraper_dir()
        if not scraper_dir:
            raise FileNotFoundError("Could not locate extracted google-maps-scraper directory.")
        subprocess.run(["go", "mod", "download"], cwd=scraper_dir, check=True)
        subprocess.run(["go", "build"], cwd=scraper_dir, check=True)
        built_binary = os.path.join(scraper_dir, binary_name)
        if not os.path.isfile(built_binary):
            raise FileNotFoundError(f"Expected built scraper binary at: {built_binary}")
        os.replace(built_binary, binary_name)

    def run_scraper_with_args_for_30_seconds(self, args: str, timeout=300) -> None:
        info(" => Running scraper...")
        binary_name = "google-maps-scraper.exe" if os.name == "nt" else "google-maps-scraper"
        command = [os.path.join(os.getcwd(), binary_name)] + shlex.split(args)
        try:
            result = subprocess.run(command, timeout=float(timeout), check=False)
            if result.returncode == 0:
                print(colored("=> Scraper finished successfully.", "green"))
            else:
                print(colored("=> Scraper finished with an error.", "red"))
        except subprocess.TimeoutExpired:
            print(colored("=> Scraper timed out.", "red"))
        except Exception as e:
            print(colored(f"An error occurred while running the scraper: {e}", "red"))

    def get_items_from_file(self, file_name: str) -> list:
        with open(file_name, "r", errors="ignore", newline="") as f:
            return [item.strip() for item in f.readlines()[1:] if item.strip()]

    def set_email_for_website(self, index: int, website: str, output_file: str):
        response = _safe_get(website)
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}\b"
        addresses = re.findall(email_pattern, response.text)
        if not addresses:
            return
        email = addresses[0]
        with open(output_file, "r", newline="", errors="ignore") as csvfile:
            items = list(csv.reader(csvfile))
        if 0 <= index < len(items):
            items[index].append(email)
        with open(output_file, "w", newline="", errors="ignore") as csvfile:
            csv.writer(csvfile).writerows(items)

    def _message_body_path(self) -> str:
        configured = Path(get_outreach_message_body_file())
        path = (Path(ROOT_DIR) / configured).resolve() if not configured.is_absolute() else configured.resolve()
        root = Path(ROOT_DIR).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError("Outreach message body must be inside the project directory")
        if not path.is_file():
            raise FileNotFoundError(f"Outreach message body not found: {path}")
        return str(path)

    def start(self) -> None:
        if not self.is_go_installed():
            error("Go is not installed. Please install go and try again.")
            return
        self.unzip_file(get_google_maps_scraper_zip_url())
        self.build_scraper()

        niche_path = Path(ROOT_DIR) / "niche.txt"
        output_path = get_results_cache_path()
        message_subject = get_outreach_message_subject()
        message_body_path = self._message_body_path()

        try:
            niche_path.write_text(self.niche, encoding="utf-8")
            self.run_scraper_with_args_for_30_seconds(
                f'-input "{niche_path}" -results "{output_path}"',
                timeout=get_scraper_timeout(),
            )
            if not os.path.exists(output_path):
                error(f" => Scraper output not found at {output_path}.")
                return

            items = self.get_items_from_file(output_path)
            success(f" => Scraped {len(items)} items.")

            yag = yagmail.SMTP(
                user=self.email_creds["username"],
                password=self.email_creds["password"],
                host=self.email_creds["smtp_server"],
                port=int(self.email_creds["smtp_port"]),
            )
            for index, item in enumerate(items, start=1):
                try:
                    fields = next(csv.reader([item]))
                    website = next((w for w in fields if w.startswith(("http://", "https://"))), "")
                    if not website:
                        continue
                    response = _safe_get(website)
                    email_addresses = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}\b", response.text)
                    if not email_addresses:
                        continue
                    receiver_email = fields[-1].strip()
                    if not EMAIL_RE.fullmatch(receiver_email):
                        warning(" => Invalid recipient email. Skipping...")
                        continue
                    company_name = fields[0].strip()
                    subject = message_subject.replace("{{COMPANY_NAME}}", company_name)
                    body = Path(message_body_path).read_text(encoding="utf-8").replace("{{COMPANY_NAME}}", company_name)
                    yag.send(to=receiver_email, subject=subject, contents=body)
                    success(f" => Sent email to {receiver_email}")
                except Exception as err:
                    error(f" => Error: {err}...")
        finally:
            try:
                niche_path.unlink()
            except FileNotFoundError:
                pass
