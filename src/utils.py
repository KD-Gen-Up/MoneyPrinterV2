import os
import random
import zipfile
import requests
import platform
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from status import *
from config import *

DEFAULT_SONG_ARCHIVE_URLS = []
SAFE_AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024


def _validate_https_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Only HTTPS download URLs are allowed")
    return url.strip()


def _safe_extract_audio_archive(archive_path: str, destination: str) -> None:
    destination_path = Path(destination).resolve()
    extracted_bytes = 0
    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            name = member.filename.replace("\\", "/")
            basename = Path(name).name
            if not basename or not basename.lower().endswith(SAFE_AUDIO_EXTENSIONS):
                warning(f"Skipping non-audio file in archive: {member.filename}")
                continue
            target = (destination_path / name).resolve()
            try:
                target.relative_to(destination_path)
            except ValueError:
                warning(f"Skipping path outside Songs directory: {member.filename}")
                continue
            extracted_bytes += member.file_size
            if extracted_bytes > MAX_EXTRACTED_BYTES:
                raise ValueError("Archive expands beyond the configured size limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as source, open(target, "wb") as output:
                remaining = member.file_size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    output.write(chunk)
                    remaining -= len(chunk)
                if remaining:
                    raise ValueError(f"Truncated archive member: {member.filename}")


def close_running_selenium_instances() -> None:
    """Close running Firefox instances without invoking a shell."""
    try:
        info(" => Closing running Selenium instances...")
        command = ["taskkill", "/f", "/im", "firefox.exe"] if platform.system() == "Windows" else ["pkill", "firefox"]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode in (0, 1):
            success(" => Closed running Selenium instances.")
        else:
            warning(" => Could not close all Selenium instances.")
    except Exception as e:
        error(f"Error occurred while closing running Selenium instances: {str(e)}")


def build_url(youtube_video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={youtube_video_id}"


def rem_temp_files() -> None:
    """Remove generated files from `.mp` while preserving JSON cache files."""
    mp_dir = Path(ROOT_DIR) / ".mp"
    if not mp_dir.exists():
        return
    for path in mp_dir.iterdir():
        if path.is_file() and path.suffix.lower() != ".json":
            try:
                path.unlink()
            except OSError as exc:
                warning(f"Could not remove temporary file {path}: {exc}")


def fetch_songs() -> None:
    """Download and safely extract configured audio archives."""
    try:
        info(" => Fetching songs...")
        files_dir = Path(ROOT_DIR) / "Songs"
        files_dir.mkdir(parents=True, exist_ok=True)
        if any(p.is_file() and p.suffix.lower() in SAFE_AUDIO_EXTENSIONS for p in files_dir.iterdir()):
            return

        configured_url = get_zip_url().strip()
        download_urls = [configured_url] if configured_url else []
        download_urls.extend(DEFAULT_SONG_ARCHIVE_URLS)
        if not download_urls:
            raise RuntimeError("No songs archive URL is configured")

        downloaded = False
        for download_url in download_urls:
            archive_path = None
            try:
                download_url = _validate_https_url(download_url)
                with requests.get(download_url, stream=True, timeout=(10, 60), allow_redirects=True) as response:
                    response.raise_for_status()
                    final_url = _validate_https_url(response.url)
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_ARCHIVE_BYTES:
                        raise ValueError("Songs archive exceeds the configured download limit")
                    fd, archive_path = tempfile.mkstemp(prefix="songs-", suffix=".zip", dir=str(files_dir))
                    os.close(fd)
                    total = 0
                    with open(archive_path, "wb") as output:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > MAX_ARCHIVE_BYTES:
                                raise ValueError("Songs archive exceeds the configured download limit")
                            output.write(chunk)

                with open(archive_path, "rb") as archive_file:
                    if archive_file.read(4) != b"PK\x03\x04":
                        raise ValueError("Downloaded songs file is not a ZIP archive")
                _safe_extract_audio_archive(archive_path, str(files_dir))
                downloaded = True
                success(f" => Downloaded Songs from {final_url}.")
                break
            except Exception as err:
                warning(f"Failed to fetch songs from {download_url}: {err}")
            finally:
                if archive_path and os.path.exists(archive_path):
                    try:
                        os.remove(archive_path)
                    except OSError:
                        pass
        if not downloaded:
            raise RuntimeError("Could not download a valid songs archive from any configured URL")
    except Exception as e:
        error(f"Error occurred while fetching songs: {str(e)}")


def choose_random_song() -> str:
    try:
        songs_dir = Path(ROOT_DIR) / "Songs"
        songs = [p for p in songs_dir.iterdir() if p.is_file() and p.suffix.lower() in SAFE_AUDIO_EXTENSIONS]
        if not songs:
            raise RuntimeError("No audio files found in Songs directory")
        song = random.choice(songs)
        success(f" => Chose song: {song.name}")
        return str(song)
    except Exception as e:
        error(f"Error occurred while choosing random song: {str(e)}")
        raise
