import sys

from status import *
from cache import get_accounts
from config import get_verbose
from classes.Tts import TTS
from classes.Twitter import Twitter
from classes.YouTube import YouTube
from llm_provider import select_model
from post_bridge_integration import maybe_crosspost_youtube_short


def main():
    if len(sys.argv) < 4:
        error("Usage: python cron.py <twitter|youtube> <account_id> <ollama_model>")
        return 2

    purpose = str(sys.argv[1]).strip().lower()
    account_id = str(sys.argv[2]).strip()
    model = str(sys.argv[3]).strip()

    if purpose not in {"twitter", "youtube"}:
        error("Invalid purpose. Expected 'twitter' or 'youtube'.")
        return 2
    if not account_id or not model:
        error("Account ID and Ollama model are required.")
        return 2

    try:
        select_model(model)
        verbose = get_verbose()

        if purpose == "twitter":
            accounts = get_accounts("twitter")
            account = next((acc for acc in accounts if acc.get("id") == account_id), None)
            if account is None:
                error(f"Twitter account not found: {account_id}")
                return 1
            if verbose:
                info("Initializing Twitter...")
            Twitter(
                account["id"], account["nickname"], account["firefox_profile"], account["topic"]
            ).post()
            if verbose:
                success("Done posting.")
            return 0

        accounts = get_accounts("youtube")
        account = next((acc for acc in accounts if acc.get("id") == account_id), None)
        if account is None:
            error(f"YouTube account not found: {account_id}")
            return 1
        if verbose:
            info("Initializing YouTube...")
        youtube = YouTube(
            account["id"], account["nickname"], account["firefox_profile"], account["niche"], account["language"]
        )
        tts = TTS()
        youtube.generate_video(tts)
        if not youtube.upload_video():
            warning("YouTube upload failed. Skipping Post Bridge cross-post.")
            return 1
        if verbose:
            success("Uploaded Short.")
        maybe_crosspost_youtube_short(
            video_path=youtube.video_path,
            title=youtube.metadata.get("title", ""),
            interactive=False,
        )
        return 0
    except Exception as exc:
        error(f"Scheduled {purpose} job failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
