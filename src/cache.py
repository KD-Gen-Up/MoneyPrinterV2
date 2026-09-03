import json
import os
import tempfile
from pathlib import Path
from typing import List

from config import ROOT_DIR


def get_cache_path() -> str:
    return os.path.join(ROOT_DIR, ".mp")


def get_afm_cache_path() -> str:
    return os.path.join(get_cache_path(), "afm.json")


def get_twitter_cache_path() -> str:
    return os.path.join(get_cache_path(), "twitter.json")


def get_youtube_cache_path() -> str:
    return os.path.join(get_cache_path(), "youtube.json")


def get_provider_cache_path(provider: str) -> str:
    if provider == "twitter":
        return get_twitter_cache_path()
    if provider == "youtube":
        return get_youtube_cache_path()
    raise ValueError(f"Unsupported provider '{provider}'. Expected 'twitter' or 'youtube'.")


def _load_json(path: str, default: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as file:
            parsed = json.load(file)
        return parsed if isinstance(parsed, dict) else default
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, target)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def get_accounts(provider: str) -> List[dict]:
    cache_path = get_provider_cache_path(provider)
    parsed = _load_json(cache_path, {"accounts": []})
    accounts = parsed.get("accounts", [])
    return accounts if isinstance(accounts, list) else []


def add_account(provider: str, account: dict) -> None:
    accounts = get_accounts(provider)
    accounts.append(account)
    _atomic_write_json(get_provider_cache_path(provider), {"accounts": accounts})


def remove_account(provider: str, account_id: str) -> None:
    accounts = [account for account in get_accounts(provider) if account.get("id") != account_id]
    _atomic_write_json(get_provider_cache_path(provider), {"accounts": accounts})


def get_products() -> List[dict]:
    parsed = _load_json(get_afm_cache_path(), {"products": []})
    products = parsed.get("products", [])
    return products if isinstance(products, list) else []


def add_product(product: dict) -> None:
    products = get_products()
    products.append(product)
    _atomic_write_json(get_afm_cache_path(), {"products": products})


def get_results_cache_path() -> str:
    return os.path.join(get_cache_path(), "scraper_results.csv")
