import asyncio
import datetime
import itertools
import random

import discord
import wavelink

class Track(wavelink.Track):
    __slots__ = ('requester', 'channel', 'message')

    def __init__(self, id_, info, *, ctx=None, requester=None):
        super(Track, self).__init__(id_, info)

        self.requester = requester or ctx.author

    @property
    def is_dead(self):
        return self.dead

class MusicQueue(asyncio.Queue):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._queue = []
        self.index = 0
        self.repeat_start = None

    def reset(self):
        while len(self._queue)-1 > self.index:
            self._queue.pop()
        self.repeat_start = None
        #dont reset the index, keep the history

    def hard_reset(self):
        self._queue.clear()
        self.index = 0
        self.repeat_start = None

    def shuffle(self):
        if self.repeat_start is not None:
            n = self.repeat_start
        else:
            n = self.index
        shuffle = self._queue[n:]
        random.shuffle(shuffle)
        old = self._queue[:n]
        self._queue = old + shuffle

    def repeat(self) -> None:
        if self.repeat_start is not None:
            self.repeat_start = None
        else:
            self.repeat_start = self.index

    def _get(self) -> Track:
        if self.repeat_start is not None:
            if len(self._queue) == 1:
                # it doesnt seem to like it when only one item is in the queue, so dont increase the index
                return self._queue[0]
            diff = self.index - self.repeat_start
            self.index += 1
            if len(self._queue) <= self.index:
                self.index = self.repeat_start
            return self._queue[diff]

        else:
            r = self._queue[self.index]
            self.index += 1
            return r

    def putleft(self, item):
        self._queue.insert(self.index, item)

    def empty(self) -> bool:
        if self.repeat_start is not None:
            if len(self._queue) <= self.index:
                self.index = self.repeat_start

        return len(self._queue) <= self.index

    @property
    def q(self):
        return self._queue[self.index:]

    @property
    def history(self):
        return self._queue[:self.index]

class AutoQueue(asyncio.Queue):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._queue = []
        self.index = 0

    def _get(self):
        item = self._queue[self.index]
        self.index = self.index + 1 if self.index + 1 < len(self._queue) else 0
        return item

    def _put(self, tracks: list):
        random.shuffle(tracks)
        self._queue.extend(tracks)

    def entries(self):
        upnext = self._queue[self.index+1:]
        later = self._queue[:self.index]
        return upnext + later

class Player(wavelink.Player):
    def __init__(self, bot, guild_id: int, node: wavelink.Node):
        super(Player, self).__init__(bot, guild_id, node)

        self.queue = MusicQueue()
        self.next_event = asyncio.Event()
        self.controller_channel_id = None
        self.last_np = None

        self.volume = 30
        self.dj = None
        self.controller_message = None
        self.reaction_task = None
        self.update = False
        self.updating = False
        self.inactive = False
        self.repeating = False

        self.controls = {'⏯': 'rp',
                         '⏹': 'stop',
                         '⏭': 'skip',
                         '🔀': 'shuffle',
                         '🔂': 'repeat'}

        self.pauses = set()
        self.resumes = set()
        self.stops = set()
        self.shuffles = set()
        self.skips = set()
        self.repeats = set()

        self._task = bot.loop.create_task(self.player_loop())

    @property
    def is_playing(self):
        return self.is_connected and self.current is not None

    @property
    def entries(self):
        return self.queue.q

    def repeat(self):
        self.queue.repeat()

    def shuffle(self):
        self.queue.shuffle()

    async def player_loop(self):
        await self.bot.wait_until_ready()

        await self.set_eq(wavelink.Equalizer.flat())
        # We can do any pre loop prep here...
        await self.set_volume(self.volume)

        while True:
            self.next_event.clear()

            self.inactive = False
            try:
                song = await asyncio.wait_for(self.queue.get(), timeout=180)
            except asyncio.TimeoutError:
                if self.controller_channel_id is not None:
                    await self.bot.get_channel(self.controller_channel_id).send(embed=discord.Embed(description="Leaving due to inactivity!", color=0x36393E), delete_after=7)
                return await self.destroy()
            if not song:
                continue

            self.current = song
            self.paused = False

            # Invoke our controller if we aren't already...
            await self.now_playing()

            await self.play(song)

            if not self.is_connected:
                return

            # Wait for TrackEnd event to set our event...
            await self.next_event.wait()

            # Clear votes...
            try:
                self.pauses.clear()
                self.resumes.clear()
                self.stops.clear()
                self.shuffles.clear()
                self.skips.clear()
                self.repeats.clear()
            except:
                pass

    async def now_playing(self, channel: discord.TextChannel=None):
        if self.last_np is not None:
            try:
                await self.last_np.delete()
            except:
                pass
        channel = channel or self.bot.get_channel(self.controller_channel_id)
        if channel is None:
            return
        track = self.current #type: Track
        embed = discord.Embed(color=3553598, title="Now Playing")
        embed.description = f"[{track.title}]({track.uri} \"{track.title}\")\nby {track.author}"
        embed.set_author(name=f"Requested by {track.requester}", icon_url=track.requester.avatar_url)
        embed.timestamp = datetime.datetime.utcnow()
        self.last_np = await channel.send(embed=embed)

    async def invoke_controller(self, track: wavelink.Track = None, channel: discord.TextChannel=None):
        """Invoke our controller message, and spawn a reaction controller if one isn't alive."""
        streaming = "\U0001f534 streaming"
        if not track:
            track = self.current
        if not channel:
            channel = self.bot.get_channel(self.controller_channel_id)
        else:
            self.controller_channel_id = channel.id

        if self.updating:
            return

        self.updating = True
        stuff = f'Now Playing:```ini\n{track.title}\n\n' \
                f'[EQ]: {self.eq}\n' \
                f'[Presets]: Flat/Boost/Piano/Metal\n' \
                f'[Duration]: {datetime.timedelta(milliseconds=int(track.length)) if not track.is_stream else streaming}\n' \
                f'[Volume]: {self.volume}\n'
        embed = discord.Embed(title='Music Controller',
                              colour=0xffb347)
        embed.set_thumbnail(url=track.thumb)
        embed.add_field(name='Video URL', value=f'[Click Here!]({track.uri})')
        embed.add_field(name='Requested By', value=track.requester.mention)
        embed.add_field(name='Current DJ', value=self.dj.mention)

        if len(self.entries) > 0:
            data = '\n'.join(f'- {t.title[0:45]}{"..." if len(t.title) > 45 else ""}\n{"-"*10}'
                             for t in itertools.islice([e for e in self.entries if not e.is_dead], 0, 3, None))
            stuff += data
        embed.description = stuff + "```"
        if self.controller_channel_id is None:
            self.controller_channel_id = track.channel.id
        if self.controller_message and channel.id != self.controller_message.id:
            try:
                await self.controller_message.delete()
            except discord.HTTPException:
                pass

            self.controller_message = await channel.send(embed=embed)
        elif not await self.is_current_fresh(channel) and self.controller_message:
            try:
                await self.controller_message.delete()
            except discord.HTTPException:
                pass

            self.controller_message = await channel.send(embed=embed)
        elif not self.controller_message:
            self.controller_message = await channel.send(embed=embed)
        else:
            self.updating = False
            return await self.controller_message.edit(embed=embed, content=None)

        try:
            self.reaction_task.cancel()
        except Exception:
            pass

        self.reaction_task = self.bot.loop.create_task(self.reaction_controller())
        self.updating = False

    async def add_reactions(self):
        """Add reactions to our controller."""
        for reaction in self.controls:
            try:
                await self.controller_message.add_reaction(str(reaction))
            except discord.HTTPException:
                return

    async def reaction_controller(self):
        """Our reaction controller, attached to our controller.
        This handles the reaction buttons and it's controls.
        """
        self.bot.loop.create_task(self.add_reactions())

        def check(r, u):
            if not self.controller_message:
                return False
            elif str(r) not in self.controls.keys():
                return False
            elif u.id == self.bot.user.id or r.message.id != self.controller_message.id:
                return False
            elif u not in self.bot.get_channel(int(self.channel_id)).members:
                return False
            return True

        while self.controller_message:
            if self.channel_id is None:
                return self.reaction_task.cancel()

            react, user = await self.bot.wait_for('reaction_add', check=check)
            control = self.controls.get(str(react))

            if control == 'rp':
                if self.paused:
                    control = 'resume'
                else:
                    control = 'pause'

            try:
                await self.controller_message.remove_reaction(react, user)
            except discord.HTTPException:
                pass
            cmd = self.bot.get_command(control)

            ctx = await self.bot.get_context(react.message)
            ctx.author = user

            try:
                if cmd.is_on_cooldown(ctx):
                    pass
                if not await self.invoke_react(cmd, ctx):
                    pass
                else:
                    self.bot.loop.create_task(ctx.invoke(cmd))
            except Exception as e:
                ctx.command = self.bot.get_command('reactcontrol')
                await cmd.dispatch_error(ctx=ctx, error=e)

        await self.destroy_controller()

    async def destroy_controller(self):
        """Destroy both the main controller and it's reaction controller."""
        try:
            await self.controller_message.delete()
            self.controller_message = None
        except (AttributeError, discord.HTTPException):
            pass

        try:
            self.reaction_task.cancel()
        except Exception:
            pass

    async def destroy(self) -> None:
        self._task.cancel()
        await self.destroy_controller()
        await wavelink.Player.destroy(self)

    @staticmethod
    async def invoke_react(cmd, ctx):
        if not cmd._buckets.valid:
            return True

        if not (await cmd.can_run(ctx)):
            return False

        bucket = cmd._buckets.get_bucket(ctx)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            return False
        return True

    async def is_current_fresh(self, chan):
        """Check whether our controller is fresh in message history."""
        try:
            async for m in chan.history(limit=8):
                if m.id == self.controller_message.id:
                    return True
        except (discord.HTTPException, AttributeError):
            return False
        return False

class AutoPlayer(wavelink.Player):
    def __init__(self, bot, guild_id, node, tc_id=None):
        super().__init__(bot, guild_id, node)
        self.queue = AutoQueue()
        self.controller_channel_id = tc_id
        self.last_np = None
        self.next_event = asyncio.Event()
        self.volume = 30
        self.dj = None

        self._task = self.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        await Player.player_loop(self) # noqa

    def assign_playlist(self, tracks: list, info: wavelink.TrackPlaylist):
        self.queue.put_nowait(tracks)
        self.trackinfo = info.data

    async def now_playing(self, channel: discord.TextChannel=None):
        if self.last_np is not None:
            try:
                await self.last_np.delete()
            except:
                pass
        channel = channel or self.bot.get_channel(self.controller_channel_id)
        if channel is None:
            return
        track = self.current #type: Track
        embed = discord.Embed(color=3553598, title="Now Playing")
        embed.description = f"[{track.title}]({track.uri} \"{track.title}\")\nby {track.author}"
        embed.timestamp = datetime.datetime.utcnow()
        self.last_np = await channel.send(embed=embed)

    @property
    def entries(self):
        return self.queue.entries()

    async def destroy(self) -> None:
        self._task.cancel()
        await wavelink.Player.destroy(self)
