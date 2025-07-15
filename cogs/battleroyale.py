import asyncio
import base64
import hashlib
import hmac
import math
import os
import time
import urllib.parse as urlparse
from collections import deque
from copy import copy, deepcopy
from random import choice, choices, uniform

import aiohttp
import discord
# import Equirec2Perspec as E2P
import numpy as np
import shapefile
from discord.ext import commands, tasks
from shapely.geometry import Point, shape
from spell import correction
from yarl import URL

# hex values for embed colors
ORANGE = 0xF5A623
RED = 0xD0021B
GREEN = 0x7ED321
BLUE = 0x4A90E2

with open('secrets.txt', 'r') as f:
    secrets = f.read().splitlines()
    SV_API_KEY = secrets[0]
    URL_SIGN_SECRET = secrets[1]
    IMGBB_API_KEY = secrets[3]

MIN_PLAYERS = 2

sf = shapefile.Reader(
    "TM_WORLD_BORDERS-0.3/TM_WORLD_BORDERS-03", encoding="latin1")
shapeRecs = []
COUNTRIES = []
COUNTRY_CODES = {}
for sr in sf.shapeRecords():
    name = sr.record['NAME']
    if name == "Iran (Islamic Republic of)":
        sr.record['NAME'] = "Iran"
    elif name == "Cote distance'Ivoire":
        sr.record['NAME'] = "Ivory Coast"
    elif name == "Korea, Republic of":
        sr.record['NAME'] = "South Korea"
    elif name == "Lao People's Democratic Republic":
        sr.record['NAME'] = "Laos"
    elif name == "Libyan Arab Jamahiriya":
        sr.record['NAME'] = "Libya"
    elif name == "The former Yugoslav Republic of Macedonia":
        sr.record['NAME'] = "North Macedonia"
    elif name == "Viet Nam":
        sr.record['NAME'] = "Vietnam"
    elif name == "United Republic of Tanzania":
        sr.record['NAME'] = "Tanzania"

    if sr.record['POP2005'] > 200000:
        shapeRecs.append(sr)
        COUNTRIES.append(sr.record['NAME'])
        COUNTRY_CODES[sr.record['NAME'].lower()] = sr.record['ISO2'].lower()


class BattleRoyale(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = []
        self.rooms = []
        self.n_rooms = 0

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def test(self, ctx):
        msg = await ctx.send('hi')
        e = ['⬆️', '↗️', '➡️', '↘️', '⬇️', '↙️', '⬅️', '↖️']
        for em in e:
            await msg.add_reaction(em)
        await msg.clear_reactions()
        await asyncio.gather(
            *[msg.add_reaction(emoji) for emoji in e]
        )

    async def _upload(self, session):
        with open("view120.png", 'rb') as pano:
            payload = {"key": IMGBB_API_KEY,
                       "image": pano.read(), 'expiration': '60'}
        async with session.post("https://api.panobb.com/1/upload", data=payload) as r:
            json = await r.json()
        return json['data']['url']

    @commands.command(name='battleroyale', aliases=['br', 'p'])
    async def play(self, ctx):
        """
        Creates a new room for people to join
        """

        if ctx.author in self.players:
            await ctx.send(f"You're already in a Room, {ctx.author.mention}!")
            return

        self.players.append(ctx.author)
        self.n_rooms += 1
        room = Room(self, ctx)
        self.rooms.append(room)
        await room.open()

    @commands.command(aliases=['c'])
    async def close(self, ctx):
        """Close room of which author is the host"""
        for room in self.rooms:
            if ctx.author == room.host:
                await room.close()
                break

    @commands.Cog.listener('on_reaction_add')
    @commands.Cog.listener('on_reaction_remove')
    async def handle_room_traffic(self, reaction, user):
        """Join or leave an existing room"""
        if not user.bot and reaction.emoji == '🚪':
            for room in self.rooms:
                if room.room_msg == reaction.message:
                    channel = reaction.message.channel
                    break
            else:
                return

            # leave room
            if user in room.players:
                await room.remove_player(user)

            elif user in self.players:
                await channel.send(f"You're already in a Room, {user.mention}")
            # join room
            elif room.status == "open":
                self.players.append(user)
                await room.add_player(user)
            else:
                await channel.send(f"Room {room_num} is closed, {ctx.author.mention}")

    @commands.Cog.listener('on_reaction_add')
    async def start(self, reaction, user):
        """
        Start the game in the current room, only usable by host of a Room
        """
        if not user.bot and reaction.emoji == '▶️':
            for room in self.rooms:
                if user == room.host:
                    if len(room.players) >= MIN_PLAYERS:
                        await room.start()
                    else:
                        channel = reaction.message.channel
                        await asyncio.gather(
                            channel.send(
                                f'There are not enough players yet, {user.mention}'),
                            reaction.remove(user)
                        )
                    break

    @commands.Cog.listener('on_message')
    async def guess(self, message):
        """Handle guesses"""
        if (message.channel.type != discord.ChannelType.private or
                message.author not in self.players):
            return

        for room in self.rooms:
            if room.status == 'playing' and message.author in room.guessing:
                country = message.content.lower()
                if country in COUNTRY_CODES:
                    await room.guess(country, message.author)
                break

    @commands.Cog.listener('on_reaction_remove')
    @commands.Cog.listener('on_reaction_add')
    async def handle_streetview_controls(self, reaction, user):
        if (reaction.message.channel.type != discord.ChannelType.private or
                user not in self.players):
            return

        if reaction.emoji in Streetview.pan_controls + Streetview.fov_controls:
            for room in self.rooms:
                if (user in room.players
                        and reaction.message == room.streetviews[user].msg):
                    await room.streetviews[user].change_view(reaction.emoji)

        elif reaction.emoji in Streetview.move_controls:
            for room in self.rooms:
                if (user in room.players
                        and reaction.message == room.streetviews[user].msg):
                    await room.streetviews[user].move(reaction.emoji)

        elif reaction.emoji == '🚩':
            for room in self.rooms:
                if (user in room.players
                        and reaction.message == room.streetviews[user].msg):
                    await room.streetviews[user].to_start()

    @commands.Cog.listener('on_reaction_add')
    async def rematch(self, reaction, user):
        if (reaction.message.channel.type != discord.ChannelType.private or
                user not in self.players):
            return

        if reaction.emoji == '🔄':
            for room in self.rooms:
                if (room.status == 'rematch' and
                        user in room.old_players and
                        user not in room.players and
                        reaction.message in room.game_msgs):
                    room.old_players.remove(user)
                    room.players.append(user)
                    if not room.old_players:
                        room.rematch_timer.cancel()
                break


def setup(bot):
    bot.add_cog(BattleRoyale(bot))


class Room:
    controls = ['🚪', '▶️']

    def __init__(self, cog, ctx):
        self.cog = cog
        self.bot = cog.bot
        self.session = aiohttp.ClientSession()
        self.room_num = cog.n_rooms
        self.ctx = ctx
        self.host = ctx.author
        self.status = "open"
        self.players = [self.host]
        self.panos = {}
        self.pano = False
        self.time = 120
        self.max_guesses = 4

    async def open(self):
        self.room_dict = dict(
            title=f"BattleRoyale Room {self.room_num}",
            description=f"Status: **{self.status}**",
            color=ORANGE,
            fields=[
                {"name": "Players:", "value": f"{self.host.mention} [Host]"},
                {
                    "name": f"Waiting for at least {MIN_PLAYERS - 1} more player...",
                    "value": "🚪Join/leave **|** ▶️ Start"
                }
            ]
        )

        self.room_msg = await self.ctx.send(embed=discord.Embed.from_dict(self.room_dict))
        await asyncio.gather(
            *[self.room_msg.add_reaction(emoji) for emoji in Room.controls]
        )

        # set random streetviews in advance
        self.streetview_task = asyncio.create_task(Streetview.random(self))

    async def close(self):
        if not self.streetview_task.done():
            self.streetview_task.cancel()
            await self.streetview_task
        self.cog.rooms.remove(self)
        self.cog.players = [
            p for p in self.cog.players if p not in self.players]
        await self.room_msg.delete()

        if self.status in ['playing', 'starting', 'rematch']:
            self.game_loop.cancel()
            await self.game_loop

        await self.session.close()

    async def add_player(self, user):
        self.players.append(user)

        if len(self.players) >= MIN_PLAYERS:
            self.room_dict['fields'][1]['name'] = 'Enough players joined, the Host can start the game!'

        self.room_dict['fields'][0]['value'] = '\n'.join(
            [f"{p.mention} [Host]" if p == self.host else p.mention for p in self.players])

        await self.room_msg.edit(embed=discord.Embed.from_dict(self.room_dict))

    async def remove_player(self, user):
        try:
            self.players.remove(user)
        except Exception:
            pass

        self.cog.players.remove(user)

        if len(self.players) == 0:
            await self.close()
            return

        if len(self.players) < MIN_PLAYERS:
            self.room_dict['fields'][1][
                'name'] = f"Waiting for at least {MIN_PLAYERS - 1} more player..."

        if user == self.host:
            self.host = self.players[0]

        self.room_dict['fields'][0]['value'] = '\n'.join(
            [f"{p.mention} [Host]" if p == self.host else p.mention for p in self.players])

        await self.room_msg.edit(embed=discord.Embed.from_dict(self.room_dict))

    async def start(self):
        self.status = 'starting'
        self.room_dict['description'] = f"Status: **{self.status}**"
        self.room_dict['fields'][1][
            'value'] = f"Everyone will receive a DM from {self.bot.user.mention}, good luck!"
        self.guessing = copy(self.players)
        await self.room_msg.edit(embed=discord.Embed.from_dict(self.room_dict))

        self.game_loop = asyncio.create_task(self.play_round(first_round=True))
        try:
            await self.game_loop
        except asyncio.CancelledError:
            pass
        else:
            self.status = 'closing'
            await self.close()

    async def play_round(self, first_round=False):
        self.all_guesses = []
        self.qualified = []
        self.disqualified = []
        self.max_qualified = len(self.guessing) - int(not first_round)

        # Make dict for game_msg embed
        self.game_dict = dict(
            title="Starting in 3!",
            description=(f"Guess where you are! Only {self.max_qualified}"
                         " more player(s) can qualify for the next round!"),
            color=GREEN,
            fields=[
                {
                    'name': 'Guessed correctly',
                    'value': '** **',
                    'inline': True
                },
                {
                    'name': 'Already made guesses',
                    'value': '** **',
                    'inline': True
                },
                {
                    'name': 'Still guessing',
                    'value': '\n'.join([
                        p.mention + ' ♥️' * self.max_guesses
                        for p in self.guessing]),
                    'inline': True
                }
            ]
        )

        if self.max_qualified == 1:
            self.game_dict['description'] = ("Guess where you are! "
                                             "Whoever guesses the right country first wins!")

        # get random streetview and start game countdown
        await asyncio.gather(self._countdown(), self.streetview_task)

        self.streetviews = {player: Streetview(player, self)
                            for player in self.players}
        self.guesses = {player: [] for player in self.guessing}
        # print(self.streetviews[self.host].panos)
        # send streetview, update room_msg, start timer
        self.status = 'playing'
        self.room_dict['description'] = f"Status: **{self.status}**"
        self.timer = asyncio.create_task(self._game_timer())
        *_, timer_result = await asyncio.gather(
            *[sv.send() for sv in self.streetviews.values()],
            self.room_msg.edit(
                embed=discord.Embed.from_dict(self.room_dict)),
            self.timer,
            return_exceptions=True
        )

        self.panos = {}
        # timeout or everyone out of guesses
        if not self.qualified:
            if self.timer.cancelled():
                self.game_dict = {
                    'title': "Almost! Nobody guessed correctly!",
                    'fields': [{
                        'name': f"It was :flag_{self.country_code}: {self.country.capitalize()}!",
                        'value': 'Starting a new round with the same players...'
                    }]
                }
            else:
                self.game_dict = {
                    'title': "Time's up!",
                    'fields': [{
                        'name': f"It was :flag_{self.country_code}: {self.country.capitalize()}!",
                        'value': 'Starting a new round with the same players...'
                    }]
                }

            self.streetview_task = asyncio.create_task(Streetview.random(self))
            await asyncio.gather(
                *[msg.edit(
                    embed=discord.Embed.from_dict(self.game_dict)
                ) for msg in self.game_msgs],
                *[pano.msg.delete() for pano in self.streetviews.values()]
            )
            await asyncio.sleep(5)
            await asyncio.gather(
                *[msg.delete() for msg in self.game_msgs],
                self.play_round()
            )

        # game over, someone won, try rematch
        elif len(self.qualified) == 1:
            self.game_dict = {
                'title': f"{self.qualified[0].name} won the game! GG",
                'fields': [{
                    'name': f"It was :flag_{self.country_code}: {self.country.capitalize()}!",
                    'value': ('Click 🔄 to play again, '
                              'starting in 20s or if everyone joins.')
                }]
            }

            self.old_players = copy(self.players)
            self.players = []
            self.status = 'rematch'
            self.streetview_task = asyncio.create_task(Streetview.random(self))
            self.rematch_timer = asyncio.create_task(asyncio.sleep(20))
            await asyncio.gather(
                *[msg.edit(
                    embed=discord.Embed.from_dict(self.game_dict)
                ) for msg in self.game_msgs],
                *[msg.add_reaction('🔄') for msg in self.game_msgs],
                self.rematch_timer,
                *[pano.msg.delete() for pano in self.streetviews.values()],
                return_exceptions=True
            )

            # start new game if enough players wanted rematch, remove rest
            if len(self.players) >= MIN_PLAYERS:
                for player in self.old_players:
                    self.remove_player(player)
                self.guessing = copy(self.players)
                self.status = 'starting'

                await self.play_round(first_round=True)
            else:
                self.game_dict['fields'][0]['name'] = (
                    "Not enough players for rematch, "
                    "closing the room...")
                self.players += self.old_players
                await asyncio.gather(
                    *[msg.edit(
                        embed=discord.Embed.from_dict(self.game_dict)
                    ) for msg in self.game_msgs]
                )

        # some people qualified, play next round
        else:
            self.game_dict = {
                'title': "Round over!",
                'fields': [{
                    'name': f"It was :flag_{self.country_code}: {self.country.capitalize()}!",
                    'value': 'Starting a new round with the qualified players...'
                }]
            }

            self.streetview_task = asyncio.create_task(Streetview.random(self))
            self.guessing = copy(self.qualified)
            await asyncio.gather(
                *[msg.edit(
                    embed=discord.Embed.from_dict(self.game_dict)
                ) for msg in self.game_msgs],
                *[pano.msg.delete() for pano in self.streetviews.values()],
            )
            await asyncio.sleep(5)
            await asyncio.gather(
                *[msg.delete() for msg in self.game_msgs],
                self.play_round()
            )

    async def guess(self, country, player):
        # when player's already qualified
        if player in self.qualified:
            await player.send(
                embed=discord.Embed(
                    title="You've already qualified!", color=ORANGE),
                delete_after=3
            )

        # when player is out of guesses already
        elif len(self.guesses[player]) == self.max_guesses:
            await player.send(
                embed=discord.Embed(title="You're out of guesses!", color=RED),
                delete_after=3
            )

        else:
            # when guess is correct
            if country == self.country.lower():
                self.guessing.remove(player)
                if not self.qualified:
                    for p in self.guessing:
                        if len(self.guesses[p]) == self.max_guesses:
                            self.disqualified.append(p)
                            self.guessing.remove(p)

                self.qualified.append(player)
                del self.guesses[player]

                self.game_dict['description'] = (
                    f"Guess where you are! Only {self.max_qualified - len(self.qualified)}"
                    " more player(s) can qualify for the next round!"
                )
                self.game_dict['fields'][0]['value'] = ' '.join(
                    [p.mention for p in self.qualified])
                if self.guessing:
                    self.game_dict['fields'][2]['value'] = '\n'.join([
                        f"{p.mention} " +
                        ' '.join([f':flag_{COUNTRY_CODES[c]}:' for c in g]) +
                        ' ♥️' * (self.max_guesses - len(g))
                        for p, g in self.guesses.items()
                    ])
                else:
                    self.game_dict['fields'][2]['value'] = '** **'

                await asyncio.gather(
                    player.send(
                        embed=discord.Embed(
                            title=f"{country.capitalize()} is correct!",
                            color=GREEN
                        ),
                        delete_after=3
                    ),
                    *[msg.edit(
                        embed=discord.Embed.from_dict(self.game_dict)
                    ) for msg in self.game_msgs]
                )
                if len(self.qualified) == self.max_qualified or len(self.guessing) == 0:
                    print('cancelling timer')
                    self.timer.cancel()

        # when guess is incorrect but a valid country
            elif country in self.guesses[player]:
                await player.send(
                    embed=discord.Embed(
                        title="You already guessed that, try a different country!",
                        color=ORANGE
                    ),
                    delete_after=3
                )
            else:
                self.guesses[player].append(country)
                if len(self.guesses[player]) == self.max_guesses:
                    if self.qualified:
                        self.guessing.remove(player)
                        del self.guesses[player]
                        self.disqualified.append(player)

                code = COUNTRY_CODES[country]
                if code not in self.all_guesses:
                    self.all_guesses.append(code)

                self.game_dict['fields'][1]['value'] = ' '.join(
                    [f":flag_{code}:" for code in self.all_guesses]
                )
                self.game_dict['fields'][2]['value'] = '\n'.join([
                    f"{p.mention} " +
                    ' '.join([f':flag_{COUNTRY_CODES[c]}:' for c in g]) +
                    ' ♥️' * (self.max_guesses - len(g))
                    for p, g in self.guesses.items()
                ])

                await asyncio.gather(
                    player.send(
                        embed=discord.Embed(
                            title=f"{country.capitalize()} is incorrect!",
                            color=RED
                        ),
                        delete_after=3
                    ),
                    * [msg.edit(
                        embed=discord.Embed.from_dict(self.game_dict)
                    ) for msg in self.game_msgs]
                )

        # stop round if everyone is out of guesses
        for player in self.guessing:
            if len(self.guesses[player]) < self.max_guesses:
                break
        else:
            self.timer.cancel()
            await self.timer

    async def _game_timer(self):
        for i in range(self.time, 0, -5):
            self.game_dict['title'] = f"Time remaining: {i} seconds"
            if i == 20:
                self.game_dict['color'] = ORANGE
            elif i == 10:
                self.game_dict['color'] = RED

            await asyncio.gather(
                *[msg.edit(
                    embed=discord.Embed.from_dict(self.game_dict)
                ) for msg in self.game_msgs]
            )
            await asyncio.sleep(5)

    async def _countdown(self):
        # send first game_msg to every player

        for i in range(3, 0, -1):
            self.room_dict['fields'][1]['name'] = f"Starting in {i}!"
            self.game_dict['title'] = f"Starting in {i}!"
            if i == 3:
                _, *self.game_msgs = await asyncio.gather(
                    self.room_msg.edit(
                        embed=discord.Embed.from_dict(self.room_dict)),
                    *[player.send(
                        embed=discord.Embed.from_dict(self.game_dict)
                    ) for player in self.players]
                )
            else:
                await asyncio.gather(
                    self.room_msg.edit(
                        embed=discord.Embed.from_dict(self.room_dict)),
                    *[msg.edit(
                        embed=discord.Embed.from_dict(self.game_dict)
                    ) for msg in self.game_msgs]
                )
            await asyncio.sleep(1)

        self.room_dict['fields'][1]['name'] = "Game has started! Go to your DM's!"
        self.game_dict['title'] = 'Loading location...'
        await asyncio.gather(
            self.room_msg.edit(embed=discord.Embed.from_dict(self.room_dict)),
            *[msg.edit(
                embed=discord.Embed.from_dict(self.game_dict)
            ) for msg in self.game_msgs]
        )


class Streetview:
    map_root_url = "https://maps.googleapis.com/maps/api/streetview"
    pan_controls = ['↪️', '↩️']
    fov_controls = ['➕', '➖']
    move_controls = ['⬆️', '↗️', '➡️', '↘️', '⬇️', '↙️', '⬅️', '↖️']

    def __init__(self, user, room):
        self.user = user
        self.room = room
        self.bot = room.bot
        self.panos = room.panos
        self.current_pano = self.start_pano = room.start_pano
        self._headings = deque(range(0, 360, 45))
        self.fov = 90
        self.heading = 0
        self.pitch = 0

    async def send(self):
        url = self.make_url(pano_id=self.current_pano,
                            fov=self.fov,
                            heading=self.heading,
                            pitch=self.pitch,
                            metadata=False)

        self.msg = await self.user.send(url)

        if not self.panos[self.current_pano].get('surround_task'):
            self.panos[self.current_pano]['surround_task'] = asyncio.create_task(
                self._find_surroundings(self.room, self.current_pano)
            )

        self.update_task = asyncio.create_task(self._add_controls(self.msg))

        return self.msg

    async def _update(self, msg, pan=False):
        url = self.make_url(pano_id=self.current_pano,
                            fov=self.fov,
                            heading=self.heading,
                            pitch=self.pitch,
                            metadata=False)

        await msg.edit(content=url)
        if pan:
            await self.panos[self.current_pano]['surround_task']
            move_emojis = [self.move_controls[self._headings.index(int_dir * 45)]
                           for int_dir in self.panos[self.current_pano]['move']]
            move_emojis.sort(
                key=lambda e: self.move_controls.index(e), reverse=True)

            new_emojis = [emoji for emoji in move_emojis
                          if emoji not in self.active_move_controls]
            old_emojis = [emoji for emoji in self.active_move_controls
                          if emoji not in move_emojis]

            for emoji in old_emojis:
                await msg.remove_reaction(emoji, self.bot.user)
                self.active_move_controls.remove(emoji)

            for emoji in new_emojis:
                self.active_move_controls.append(emoji)
                await msg.add_reaction(emoji)

    async def _add_controls(self, msg):
        await asyncio.gather(
            self.panos[self.current_pano]['surround_task'],
            self.msg.add_reaction('🚩'),
            *[self.msg.add_reaction(emoji)
              for emoji in self.pan_controls + self.fov_controls]
        )

        move_emojis = [self.move_controls[self._headings.index(int_dir * 45)]
                       for int_dir in self.panos[self.current_pano]['move']]
        move_emojis.sort(
            key=lambda e: self.move_controls.index(e), reverse=True)

        self.active_move_controls = []
        for emoji in move_emojis:
            self.active_move_controls.append(emoji)
            await msg.add_reaction(emoji)

    async def change_view(self, emoji):
        if emoji in self.pan_controls:
            if emoji == '↪️':
                self._headings.rotate(1)
            else:
                self._headings.rotate(-1)

            self.heading = self._headings[0]

            if not self.update_task.done():
                self.update_task.cancel()

            self.update_task = asyncio.create_task(
                self._update(self.msg, True))

        elif emoji in self.fov_controls:
            if emoji == '➕' and self.fov > 30:
                self.fov -= 30
            elif emoji == '➖' and self.fov < 120:
                self.fov += 30

            self.update_task = asyncio.create_task(self._update(self.msg))

    async def move(self, emoji):
        direction = self._headings[self.move_controls.index(emoji)] / 45
        await self.panos[self.current_pano]['surround_task']
        if pano := self.panos[self.current_pano]['move'].get(direction):
            self.current_pano = pano
            if not self.panos[self.current_pano].get('surround_task'):
                self.panos[self.current_pano]['surround_task'] = asyncio.create_task(
                    self._find_surroundings(self.room, self.current_pano)
                )
            # await asyncio.gather(
            #     self.msg.delete(),
            #     self.send()
            # )
            self.update_task = asyncio.create_task(
                self._update(self.msg, True))

    async def to_start(self):
        self.current_pano = self.start_pano
        await asyncio.gather(
            self.msg.delete(),
            self.send()
        )

    @classmethod
    async def random(cls, room):
        try:
            tasks = [asyncio.create_task(cls._find_rand_pano(room.session))
                     for _ in range(1)]

            while tasks:
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )
                for done_task in done:
                    if result := done_task.result():
                        # cancel remaining tasks
                        for pending_task in pending:
                            pending_task.cancel()
                        if pending:
                            await asyncio.wait(pending)

                        room.country = result[0]
                        room.country_code = result[1]
                        print(f"Using pano from {room.country}")

                        pano_id, coords = result[2:]
                        room.panos[pano_id] = {
                            'coords': coords,
                            'surround_task': asyncio.create_task(
                                cls._find_surroundings(room, pano_id)
                            )
                        }
                        room.start_pano = pano_id
                        return

                tasks = pending

        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.wait(tasks)

    @classmethod
    async def _find_rand_pano(cls, session):
        while True:
            shapeRec = choice(shapeRecs)
            min_lon = shapeRec.shape.bbox[0]
            min_lat = shapeRec.shape.bbox[1]
            max_lon = shapeRec.shape.bbox[2]
            max_lat = shapeRec.shape.bbox[3]
            borders = shapeRec.shape

            lat = uniform(min_lat, max_lat)
            lon = uniform(min_lon, max_lon)
            while not cls._point_inside_poly(lon, lat, borders):
                lat = uniform(min_lat, max_lat)
                lon = uniform(min_lon, max_lon)

            print(f"Searching in {shapeRec.record['NAME']}..")

            json = await cls._get_pano(session, lat, lon, radius=100000)
            if not json:
                print('no response')
                continue

            print(f"Done searching in {shapeRec.record['NAME']}")
            if json['status'] == "OK":
                print(f"{shapeRec.record['NAME']} was useable!")
                pano_id = json['pano_id']
                lat, lon = json['location']['lat'], json['location']['lng']
                return (shapeRec.record['NAME'],
                        shapeRec.record['ISO2'].lower(),
                        pano_id, (lat, lon))

    # find surrounding images and set them to according action
    @classmethod
    async def _find_surroundings(cls, room, pano_id):
        lat, lon = room.panos[pano_id]['coords']
        print('finding surrounding panos of', pano_id, lat, lon)

        room.panos[pano_id]['move'] = {}

        surrounding_coords = []
        distance = 10
        earth_radius = 6371000
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        # get coords 10m in each intercardinal direction from given pano
        for heading in range(0, 360, 45):
            heading = math.radians(heading)

            new_lat = math.asin(
                math.sin(lat_rad) * math.cos(distance / earth_radius) +
                math.cos(lat_rad) * math.sin(distance / earth_radius) *
                math.cos(heading)
            )

            new_lon = lon_rad + math.atan2(
                math.sin(heading) *
                math.sin(distance / earth_radius) *
                math.cos(lat_rad),
                math.cos(distance / earth_radius) -
                math.sin(lat_rad) * math.sin(new_lat)
            )

            new_lat = math.degrees(new_lat)
            new_lon = (math.degrees(new_lon) + 540) % 360 - 180
            surrounding_coords.append((new_lat, new_lon))

        surrounding_panos = await asyncio.gather(*[cls._get_pano(
            room.session, *coords) for coords in surrounding_coords]
        )

        for pano in surrounding_panos:
            if (pano['status'] != 'OK'
                    or (new_pano_id := pano['pano_id']) == pano_id):
                continue

            new_lat, new_lon = pano['location']['lat'], pano['location']['lng']
            new_lat_rad = math.radians(new_lat)
            new_lon_rad = math.radians(new_lon)

            y = math.sin(new_lon_rad - lon_rad) * math.cos(new_lat_rad)
            x = (math.cos(lat_rad) * math.sin(new_lat_rad)
                 - math.sin(lat_rad) * math.cos(new_lat_rad) *
                 math.cos(new_lon_rad - lon_rad))
            theta = math.atan2(y, x)
            direction = (theta * 180 / math.pi + 360) % 360
            # intercardinal direction; 0 is straight forward, 4 is backwards
            intercard_dir = round(direction / 45) % 8

            # add to according direction if there's no image yet
            if not room.panos[pano_id]['move'].get(intercard_dir):
                print('found move in direction:', intercard_dir, new_pano_id)
                room.panos[pano_id]['move'][intercard_dir] = new_pano_id
                room.panos.setdefault(new_pano_id,
                                      {'coords': (new_lat, new_lon)})

    @classmethod
    async def _get_pano(cls, session, lat, lon, radius=10):
        signed_request_url = cls.make_url(lat=lat, lon=lon, radius=radius)
        async with session.get(URL(signed_request_url, encoded=True)) as r:
            if r.status == 200:
                json = await r.json()
            else:
                return None

        return json

    @staticmethod
    def make_url(pano_id=None, lat=None, lon=None, radius=5,
                 heading=0, fov=90, pitch=0, size="640x320",
                 source="outdoor", metadata=True):
        if not pano_id and not (lat and lon):
            raise ValueError("Provide pano_id or lat and lon")

        params_dict = dict(
            key=SV_API_KEY,
            radius=radius,
            heading=heading,
            fov=fov,
            pitch=pitch,
            size=size,
            source=source
        )
        if pano_id:
            params_dict['pano'] = pano_id
        else:
            params_dict['location'] = f"{lat},{lon}"

        params = urlparse.urlencode(params_dict)
        if metadata:
            request_url = Streetview.map_root_url + "/metadata?" + params
        else:
            request_url = Streetview.map_root_url + "?" + params
        url = urlparse.urlparse(request_url)

        # We only need to sign the path+query part of the string
        url_to_sign = url.path + "?" + url.query

        # Decode the private key into its binary format
        # We need to decode the URL-encoded private key
        decoded_key = base64.urlsafe_b64decode(URL_SIGN_SECRET)

        # Create a signature using the private key and the URL-encoded
        # string using HMAC SHA1. This signature will be binary.
        signature = hmac.new(
            decoded_key, str.encode(url_to_sign), hashlib.sha1)

        # Encode the binary signature into base64 for use within a URL
        encoded_signature = base64.urlsafe_b64encode(signature.digest())
        original_url = url.scheme + "://" + url.netloc + url.path + "?" + url.query

        # Return signed URL
        return original_url + "&signature=" + encoded_signature.decode()

    @staticmethod
    def _point_inside_poly(x, y, poly):
        """
        Determine if a point is inside a given polygon or not
        Polygon is a shape object.
        """
        return Point((x, y)).within(shape(poly))
