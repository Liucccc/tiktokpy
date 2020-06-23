import asyncio
from typing import List

from loguru import logger
from tqdm import tqdm

from tiktokpy.client import Client
from tiktokpy.utils.client import catch_response_and_store, catch_user_info


class User:
    def __init__(self, client: Client):
        self.client = client

    async def feed(self, username: str, amount: int):
        page = await self.client.new_page()
        logger.debug(f"📨 Request {username} feed")

        result: List[dict] = []
        user_info_queue: asyncio.Queue = asyncio.Queue(maxsize=1)

        page.on(
            "response", lambda res: asyncio.create_task(catch_response_and_store(res, result)),
        )

        page.on(
            "response", lambda res: asyncio.create_task(catch_user_info(res, user_info_queue)),
        )
        _ = await self.client.goto(f"/{username}", page=page, options={"waitUntil": "networkidle0"})
        logger.debug(f"📭 Got {username} feed")

        await page.waitForSelector(".video-feed-item", options={"visible": True})

        user_info = await user_info_queue.get()
        user_video_count = user_info["stats"]["videoCount"]

        if user_video_count < amount:
            logger.info(
                f"⚠️  User {username} has only {user_video_count} videos. "
                f"Set amount from {amount} to {user_video_count}",
            )
            amount = user_video_count

        pbar = tqdm(total=amount, desc=f"📈 Getting {username} feed")

        attempts = 0
        last_result = len(result)

        while len(result) < amount:
            logger.debug("🖱 Trying to scroll to last video item")
            await page.evaluate(
                """
                document.querySelector('.video-feed-item:last-child')
                    .scrollIntoView();
            """,
            )
            await page.waitFor(1_000)

            elements = await page.JJ(".video-feed-item")
            logger.debug(f"🔎 Found {len(elements)} items for clear")

            pbar.n = min(len(result), amount)
            pbar.refresh()

            if last_result == len(result):
                attempts += 1
            else:
                attempts = 0

            if attempts > 10:
                pbar.clear()
                pbar.total = len(result)
                logger.info(
                    f"⚠️  After 10 attempts found {len(result)} videos. "
                    f"Probably some videos are private",
                )
                break

            last_result = len(result)

            if len(elements) < 500:
                logger.debug("🔻 Too less for clearing page")
                continue

            await page.JJeval(
                ".video-feed-item:not(:last-child)",
                pageFunction="(elements) => elements.forEach(el => el.remove())",
            )
            logger.debug(f"🎉 Cleaned {len(elements) - 1} items from page")
            await page.waitFor(30_000)

        await page.close()
        pbar.close()
        return result[:amount]