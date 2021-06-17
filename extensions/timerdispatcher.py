import datetime
from typing import Union, Optional

import asyncpg
import discord
import ujson
from discord.ext import commands
from utils.bot import Bot


def setup(bot):
    bot.add_cog(Timers(bot))


class CurrentTask:
    def __init__(self, r: Union[asyncpg.Record, dict]):
        self.id: int = r["id"]
        self.dispatch_at: datetime.datetime = r["dispatch_at"].replace(tzinfo=datetime.timezone.utc)
        self.data: dict = ujson.loads(r["data"])
        self.event: str = r["event"]

    async def wait(self):
        print(self.dispatch_at - discord.utils.utcnow())
        await discord.utils.sleep_until(self.dispatch_at)


class Timers(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.processor = bot.loop.create_task(self.process_tasks())
        self.current_task: Optional[CurrentTask] = None

    async def pull_next_task(self) -> asyncpg.Record:
        await self.bot.wait_until_ready()
        return await self.bot.db.fetchrow("SELECT * FROM dispatchers ORDER BY dispatch_at LIMIT 1")

    async def process_tasks(self, task: dict = None):
        while not task:
            task = await self.pull_next_task()
            if not task:
                return  # there are no tasks in the queue

        print(task)
        tsk = self.current_task = CurrentTask(task)
        await tsk.wait()
        self.bot.dispatch(tsk.event, *tsk.data["args"], **tsk.data["kwargs"])
        await self.bot.db.execute("DELETE FROM dispatchers WHERE id = $1", tsk.id)
        print("done", task)

        self.current_task = None
        self.processor = self.bot.loop.create_task(self.process_tasks())

    async def schedule_task(
        self, event: str, dispatch_at: datetime.datetime, *args, conn: asyncpg.Connection = None, **kwargs
    ) -> asyncpg.Record:
        query = "INSERT INTO dispatchers (dispatch_at, event, data) VALUES ($1, $2, $3) RETURNING *"
        if conn:
            data = await conn.fetchrow(query, dispatch_at, event, ujson.dumps({"args": list(args), "kwargs": kwargs}))
        else:
            data = await self.bot.db.fetchrow(
                query, dispatch_at, event, ujson.dumps({"args": list(args), "kwargs": kwargs})
            )

        if self.current_task and dispatch_at < self.current_task.dispatch_at:
            self.processor.cancel()
            self.processor = self.bot.loop.create_task(self.process_tasks(data))

        elif not self.current_task:
            self.processor = self.bot.loop.create_task(self.process_tasks(data))

        return data

    async def cancel_task(self, dispatch_id: int, conn: asyncpg.Connection = None) -> Optional[asyncpg.Record]:
        query = "DELETE FROM dispatchers WHERE id = $1 RETURNING *"
        if conn:
            data = await conn.fetchrow(query, dispatch_id)
        else:
            data = await self.bot.db.fetchrow(query, dispatch_id)

        if not data:
            return None

        if self.current_task and data["id"] == self.current_task.id:
            self.current_task = None
            self.processor.cancel()
            self.processor = self.bot.loop.create_task(self.process_tasks())

        return data
