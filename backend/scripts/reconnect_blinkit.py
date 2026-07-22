"""
Reconnect Blinkit session from terminal.

Usage:
    cd backend
    python -m scripts.reconnect_blinkit

Steps:
  1. Go to brands.blinkit.com → request magic link via email
  2. Copy the magic link from your email
  3. Paste it here — the script saves the session to DB
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TENANT_ID = "a870fd8d-7373-47ec-ad69-5dd08ce35542"


async def main():
    magic_link = input("Paste your Blinkit magic link (from email): ").strip()
    if not magic_link.startswith("http"):
        print("ERROR: That doesn't look like a valid URL.")
        return

    print("\nOpening headless browser and navigating to magic link...")

    from app.core.database import AsyncSessionLocal
    from app.services.ads_service import reconnect_blinkit
    import uuid

    async with AsyncSessionLocal() as db:
        try:
            await reconnect_blinkit(db, uuid.UUID(TENANT_ID), magic_link)
            print("\n✓ Session saved successfully! Backend can now connect to Blinkit.")
        except Exception as e:
            print(f"\nERROR: {e}")


if __name__ == "__main__":
    if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
