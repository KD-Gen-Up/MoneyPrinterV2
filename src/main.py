import os
import sys
import subprocess
import threading
import time
import schedule

from art import *
from cache import *
from utils import *
from config import *
from status import *
from uuid import uuid4
from constants import *
from classes.Tts import TTS
from termcolor import colored
from classes.Twitter import Twitter
from classes.YouTube import YouTube
from prettytable import PrettyTable
from classes.Outreach import Outreach
from classes.AFM import AffiliateMarketing
from llm_provider import list_models, select_model, get_active_model
from post_bridge_integration import maybe_crosspost_youtube_short


_scheduler_started = False
_scheduler_lock = threading.Lock()


def _start_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def loop():
        while True:
            try:
                schedule.run_pending()
            except Exception as exc:
                error(f"Scheduler error: {exc}")
            time.sleep(1)

    threading.Thread(target=loop, name="moneyprinter-scheduler", daemon=True).start()


def _select_account(provider: str):
    accounts = get_accounts(provider)
    if not accounts:
        warning(f"No {provider} accounts configured.")
        return None

    table = PrettyTable()
    table.field_names = ["ID", "UUID", "Nickname"]
    for index, account in enumerate(accounts, 1):
        table.add_row([index, account.get("id", ""), account.get("nickname", "")])
    print(table)

    raw = question("Select account number (or 'd' to delete): ").strip().lower()
    if raw == "d":
        delete_raw = question("Enter account number to delete: ").strip()
        try:
            index = int(delete_raw) - 1
            if not 0 <= index < len(accounts):
                raise ValueError
        except ValueError:
            warning("Invalid account number.")
            return None
        account = accounts[index]
        if question(f"Delete '{account.get('nickname', '')}'? (Yes/No): ").strip().lower() == "yes":
            remove_account(provider, account.get("id", ""))
            success("Account removed successfully!")
        return None

    try:
        index = int(raw) - 1
        if not 0 <= index < len(accounts):
            raise ValueError
        return accounts[index]
    except ValueError:
        warning("Invalid account number.")
        return None


def _ensure_youtube_account():
    accounts = get_accounts("youtube")
    if accounts:
        return _select_account("youtube")
    if question("No YouTube accounts found. Create one? (Yes/No): ").strip().lower() != "yes":
        return None
    account = {
        "id": str(uuid4()),
        "nickname": question(" => Enter a nickname: ").strip(),
        "firefox_profile": question(" => Enter Firefox profile path: ").strip(),
        "niche": question(" => Enter channel niche: ").strip(),
        "language": question(" => Enter channel language: ").strip(),
        "videos": [],
    }
    add_account("youtube", account)
    success("YouTube account configured successfully!")
    return account


def _ensure_twitter_account():
    accounts = get_accounts("twitter")
    if accounts:
        return _select_account("twitter")
    if question("No Twitter accounts found. Create one? (Yes/No): ").strip().lower() != "yes":
        return None
    account = {
        "id": str(uuid4()),
        "nickname": question(" => Enter a nickname: ").strip(),
        "firefox_profile": question(" => Enter Firefox profile path: ").strip(),
        "topic": question(" => Enter account topic: ").strip(),
        "posts": [],
    }
    add_account("twitter", account)
    success("Twitter account configured successfully!")
    return account


def _schedule_process(purpose: str, account_id: str, when: str | None = None):
    model = get_active_model()
    if not model:
        error("No Ollama model selected. Scheduling cancelled.")
        return
    cron_script = os.path.join(ROOT_DIR, "src", "cron.py")
    command = [sys.executable, cron_script, purpose, account_id, model]

    def job():
        try:
            result = subprocess.run(command, check=False)
            if result.returncode != 0:
                warning(f"Scheduled {purpose} job exited with code {result.returncode}.")
        except Exception as exc:
            error(f"Scheduled {purpose} job failed: {exc}")

    if when is None:
        schedule.every().day.do(job)
    else:
        schedule.every().day.at(when).do(job)
    success(f"Scheduled {purpose} job.")


def _youtube_menu(account):
    youtube = YouTube(
        account["id"], account["nickname"], account["firefox_profile"], account["niche"], account["language"]
    )
    while True:
        info("\n============ YOUTUBE ============", False)
        for idx, option in enumerate(YOUTUBE_OPTIONS, 1):
            print(colored(f" {idx}. {option}", "cyan"))
        info("=================================\n", False)
        try:
            choice = int(question("Select an option: "))
        except ValueError:
            warning("Please enter a number.")
            continue

        if choice == 1:
            rem_temp_files()
            tts = TTS()
            youtube.generate_video(tts)
            if question("Upload this video to YouTube? (Yes/No): ").strip().lower() == "yes":
                if youtube.upload_video():
                    maybe_crosspost_youtube_short(
                        video_path=youtube.video_path,
                        title=youtube.metadata.get("title", ""),
                        interactive=True,
                    )
                else:
                    warning("YouTube upload failed.")
        elif choice == 2:
            videos = youtube.get_videos()
            if not videos:
                warning("No videos found.")
                continue
            table = PrettyTable()
            table.field_names = ["ID", "Date", "Title"]
            for index, video in enumerate(videos, 1):
                table.add_row([index, video.get("date", ""), video.get("title", "")[:60]])
            print(table)
        elif choice == 3:
            info("How often do you want to upload?")
            for idx, option in enumerate(YOUTUBE_CRON_OPTIONS, 1):
                print(colored(f" {idx}. {option}", "cyan"))
            try:
                schedule_choice = int(question("Select an option: "))
            except ValueError:
                warning("Please enter a number.")
                continue
            if schedule_choice == 1:
                _schedule_process("youtube", account["id"])
            elif schedule_choice == 2:
                _schedule_process("youtube", account["id"], "10:00")
                _schedule_process("youtube", account["id"], "16:00")
        elif choice == 4:
            break
        else:
            warning("Invalid option.")


def _twitter_menu(account):
    twitter = Twitter(account["id"], account["nickname"], account["firefox_profile"], account["topic"])
    while True:
        info("\n============ TWITTER ============", False)
        for idx, option in enumerate(TWITTER_OPTIONS, 1):
            print(colored(f" {idx}. {option}", "cyan"))
        info("=================================\n", False)
        try:
            choice = int(question("Select an option: "))
        except ValueError:
            warning("Please enter a number.")
            continue
        if choice == 1:
            twitter.post()
        elif choice == 2:
            posts = twitter.get_posts()
            table = PrettyTable()
            table.field_names = ["ID", "Date", "Content"]
            for index, post in enumerate(posts, 1):
                table.add_row([index, post.get("date", ""), post.get("content", "")[:60]])
            print(table)
        elif choice == 3:
            info("How often do you want to post?")
            for idx, option in enumerate(TWITTER_CRON_OPTIONS, 1):
                print(colored(f" {idx}. {option}", "cyan"))
            try:
                schedule_choice = int(question("Select an option: "))
            except ValueError:
                warning("Please enter a number.")
                continue
            if schedule_choice == 1:
                _schedule_process("twitter", account["id"])
            elif schedule_choice == 2:
                _schedule_process("twitter", account["id"], "10:00")
                _schedule_process("twitter", account["id"], "16:00")
            elif schedule_choice == 3:
                _schedule_process("twitter", account["id"], "08:00")
                _schedule_process("twitter", account["id"], "12:00")
                _schedule_process("twitter", account["id"], "18:00")
        elif choice == 4:
            break
        else:
            warning("Invalid option.")


def _affiliate_menu():
    products = get_products()
    if not products:
        affiliate_link = question(" => Enter affiliate link: ").strip()
        twitter_uuid = question(" => Enter Twitter Account UUID: ").strip()
        account = next((a for a in get_accounts("twitter") if a.get("id") == twitter_uuid), None)
        if account is None:
            error("Twitter account not found. Product was not created.")
            return
        product = {"id": str(uuid4()), "affiliate_link": affiliate_link, "twitter_uuid": twitter_uuid}
        add_product(product)
    else:
        table = PrettyTable()
        table.field_names = ["ID", "Affiliate Link", "Twitter Account UUID"]
        for index, product in enumerate(products, 1):
            table.add_row([index, product.get("affiliate_link", ""), product.get("twitter_uuid", "")])
        print(table)
        try:
            selected = products[int(question("Select product: ")) - 1]
        except (ValueError, IndexError):
            error("Invalid product selected.")
            return
        product = selected
        account = next((a for a in get_accounts("twitter") if a.get("id") == product.get("twitter_uuid")), None)
        if account is None:
            error("Twitter account for this product no longer exists.")
            return

    account = next((a for a in get_accounts("twitter") if a.get("id") == product.get("twitter_uuid")), None)
    if account is None:
        error("Twitter account not found.")
        return
    afm = AffiliateMarketing(
        product["affiliate_link"], account["firefox_profile"], account["id"], account["nickname"], account["topic"]
    )
    afm.generate_pitch()
    afm.share_pitch("twitter")


def _load_model():
    configured = get_ollama_model()
    if configured:
        select_model(configured)
        success(f"Using configured model: {configured}")
        return
    try:
        models = list_models()
    except Exception as exc:
        error(f"Could not connect to Ollama: {exc}")
        sys.exit(1)
    if not models:
        error("No models found on Ollama. Pull a model first.")
        sys.exit(1)
    print("\n========== OLLAMA MODELS =========")
    for index, model in enumerate(models, 1):
        print(colored(f" {index}. {model}", "cyan"))
    while True:
        try:
            choice = int(input(colored("Select a model: ", "magenta"))) - 1
            if 0 <= choice < len(models):
                select_model(models[choice])
                success(f"Using model: {models[choice]}")
                return
        except ValueError:
            pass
        warning("Invalid model selection. Try again.")


def main():
    _start_scheduler()
    while True:
        info("\n============ OPTIONS ============", False)
        for idx, option in enumerate(OPTIONS, 1):
            print(colored(f" {idx}. {option}", "cyan"))
        info("=================================\n", False)
        try:
            choice = int(input("Select an option: ").strip())
        except ValueError:
            warning("Please enter a number.")
            continue

        if choice == 1:
            account = _ensure_youtube_account()
            if account:
                _youtube_menu(account)
        elif choice == 2:
            account = _ensure_twitter_account()
            if account:
                _twitter_menu(account)
        elif choice == 3:
            _affiliate_menu()
        elif choice == 4:
            Outreach().start()
        elif choice == 5:
            if get_verbose():
                print(colored(" => Quitting...", "blue"))
            return
        else:
            warning("Invalid option selected.")


if __name__ == "__main__":
    print_banner()
    first_time = get_first_time_running()
    if first_time:
        print(colored("Hey! It looks like you're running MoneyPrinter V2 for the first time. Let's get you setup first!", "yellow"))
    assert_folder_structure()
    rem_temp_files()
    fetch_songs()
    _load_model()
    main()
