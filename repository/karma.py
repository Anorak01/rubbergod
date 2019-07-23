from repository.base_repository import BaseRepository
import mysql.connector
import asyncio
import discord
from emoji import UNICODE_EMOJI
import utils


class Karma(BaseRepository):

    def __init__(self, client):
        super().__init__()
        self.client = client

    def emoji_value(self, emoji_id):
        row = self.get_row("bot_karma_emoji", "emoji_id", emoji_id)
        return row[1] if row else 0

    def update_karma(self, member, giver, emoji_value, remove=False):
        db = mysql.connector.connect(**self.config.connection)
        cursor = db.cursor()

        self.update_karma_get(cursor, member, emoji_value)
        self.update_karma_give(cursor, giver, emoji_value, remove)

        db.commit()
        db.close()

    def update_karma_get(self, cursor, member, emoji_value):
        if self.get_karma_value('bot_karma', member.id) is not None:
            cursor.execute('SELECT karma FROM bot_karma WHERE member_id = %s',
                           (member.id,))
            updated = cursor.fetchone()
            update = int(updated[0]) + emoji_value
            cursor.execute('UPDATE bot_karma SET karma = %s '
                           'WHERE member_id = %s',
                           (update, member.id))
        else:
            cursor.execute('INSERT INTO bot_karma (member_id, karma) '
                           'VALUES (%s, %s)',
                           (member.id, emoji_value))

    def update_karma_give(self, cursor, giver, emoji_value, remove):
        if emoji_value > 0:
            if remove:
                column = 'negative'
            else:
                column = 'positive'
        else:
            if remove:
                column = 'positive'
            else:
                column = 'negative'

        if column == 'negative':
            emoji_value *= -1

        if self.get_karma_value('bot_karma_giving', giver.id) is not None:
            cursor.execute('SELECT {} FROM bot_karma_giving '
                           'WHERE member_id = %s'.format(column),
                           (giver.id,))
            updated = cursor.fetchone()
            update = int(updated[0]) + emoji_value
            cursor.execute('UPDATE bot_karma_giving SET {} = %s '
                           'WHERE member_id = %s'.format(column),
                           (update, giver.id))
        else:
            if column == 'positive':
                cursor.execute('INSERT INTO bot_karma_giving '
                               '(member_id, positive, negative) '
                               'VALUES (%s, %s, %s)',
                               (giver.id, emoji_value, 0))
            else:
                cursor.execute('INSERT INTO bot_karma_giving '
                               '(member_id, positive, negative) '
                               'VALUES (%s, %s, %s)',
                               (giver.id, 0, emoji_value))

    def karma_emoji(self, member, giver, emoji_id):
        emoji_value = int(self.emoji_value(str(emoji_id)))
        if emoji_value:
            self.update_karma(member, giver, emoji_value)

    def karma_emoji_remove(self, member, giver, emoji_id):
        emoji_value = int(self.emoji_value(str(emoji_id)))
        if emoji_value:
            self.update_karma(member, giver, emoji_value * (-1), True)

    def get_karma_value(self, database, member):
        row = self.get_row(database, "member_id", member)
        if database == 'bot_karma':
            return row[1] if row else None
        elif database == 'bot_karma_giving':
            return (row[1], row[2]) if row else None
        else:
            raise Exception('Nespravna databaze v get_karma_value')

    def get_karma_position(self, database, column, karma):
        db = mysql.connector.connect(**self.config.connection)
        cursor = db.cursor()
        cursor.execute("SELECT count(*) "
                       "FROM {} "
                       "WHERE {} > %s"
                       .format(database, column),
                       (str(karma),))
        row = cursor.fetchone()
        db.close()
        return row[0] + 1

    def get_karma(self, member, action):
        if action == 'get':
            database = 'bot_karma'
        elif action == 'give':
            database = 'bot_karma_giving'
        else:
            raise Exception('Action neni get/give')
        karma = self.get_karma_value(database, member)

        if action == 'get':
            if karma is None:
                karma = 0
            order = self.get_karma_position(database, "karma", karma)
            return (self.messages.karma_own
                    .format(user=utils.generate_mention(member),
                            karma=str(karma), pos=str(order)))
        elif action == 'give':
            if karma is None:
                karma = (0, 0)
            order = (self.get_karma_position(database, "positive", karma[0]),
                     self.get_karma_position(database, "negative", karma[1]))
            return (self.messages.karma_given
                    .format(user=utils.generate_mention(member),
                            karma_pos=str(karma[0]),
                            karma_pos_pos=str(order[0]),
                            karma_neg=str(karma[1]),
                            karma_neg_pos=str(order[1])))

    def get_leaderboard(self, database, column, order):
        db = mysql.connector.connect(**self.config.connection)
        cursor = db.cursor()
        cursor.execute('SELECT * FROM {} ORDER BY {} {} LIMIT 10'
                       .format(database, column, order))
        leaderboard = cursor.fetchall()
        db.close()
        return leaderboard

    async def emote_vote(self, channel, emote):
        delay = self.config.vote_minutes * 60
        message = await channel.send(
                 "{}\n{}"
                 .format(self.messages.karma_vote_message.format(
                             emote=str(emote)
                         ),
                         self.messages.karma_vote_info
                         .format(delay=str(delay // 60),
                         minimum=str(self.config.vote_minimum))))
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        await message.add_reaction("0⃣")
        await asyncio.sleep(delay)

        message = await channel.fetch_message(message.id)

        for reaction in message.reactions:
            if reaction.emoji == "✅":
                plus = reaction.count - 1
            elif reaction.emoji == "❌":
                minus = reaction.count - 1
            elif reaction.emoji == "0⃣":
                neutral = reaction.count - 1

        if plus + minus + neutral < self.config.vote_minimum:
            return None

        if plus > minus + neutral:
            return 1
        elif minus > plus + neutral:
            return -1
        else:
            return 0

    async def vote(self, message):
        if len(message.content.split()) != 2:
            await message.channel.send(
                    self.messages.karma_vote_format)
            return
        db = mysql.connector.connect(**self.config.connection)
        cursor = db.cursor()
        cursor.execute('SELECT emoji_id FROM bot_karma_emoji')
        emotes = cursor.fetchall()

        guild = message.channel.guild
        vote_value = 0
        the_emote = None
        id_array = []
        for emote in emotes:
            id_array.append(emote[0])
        for emote in guild.emojis:
            if not emote.animated:
                row = self.get_row("bot_karma_emoji", "emoji_id",
                                   emote.id)
                if row is None:
                    cursor.execute('INSERT INTO bot_karma_emoji '
                                   '(emoji_id, value) '
                                   'VALUES (%s, %s)',
                                   (emote.id, 0))
                    db.commit()
                    vote_value = await self.emote_vote(message.channel,
                                                       emote)
                    the_emote = emote
                    break
        else:
            db.close()
            await message.channel.send(self.messages.karma_vote_allvoted)
            return

        if vote_value is None:
            cursor.execute('DELETE FROM bot_karma_emoji '
                           'WHERE emoji_id = %s',
                           (str(the_emote.id),))

            await message.channel.send(
                    self.messages.karma_vote_notpassed
                    .format(emote=str(the_emote),
                            minimum=str(self.config.vote_minimum)))

            db.commit()
            db.close()
            return
        else:
            cursor.execute('UPDATE bot_karma_emoji SET value = %s '
                           'WHERE emoji_id = %s',
                           (vote_value, str(the_emote.id)))
        db.commit()
        db.close()
        await message.channel.send(
                self.messages.karma_vote_result
                .format(emote=str(the_emote), result=str(vote_value)))
        return

    async def revote(self, message):
        content = message.content.split()
        if len(content) != 3:
            await message.channel.send(self.messages.karma_revote_format)
            return

        emote = content[2]
        if len(emote) != 1 or emote[0] not in UNICODE_EMOJI:
            try:
                emote_id = int(emote.split(':')[2][:-1])
                emote = await message.channel.guild.fetch_emoji(emote_id)
            except (ValueError, IndexError):
                await message.channel.send(
                        self.messages.karma_revote_format)
                return
            except discord.NotFound:
                await message.channel.send(self.messages.karma_emote_not_found)
                return

        vote_value = await self.emote_vote(message.channel, emote)

        if vote_value is not None:
            db = mysql.connector.connect(**self.config.connection)
            cursor = db.cursor()
            cursor.execute('INSERT INTO bot_karma_emoji (emoji_id, value) '
                           'VALUES (%s, %s) ON DUPLICATE KEY '
                           'UPDATE value = %s',
                           (emote if type(emote) is str else emote.id,
                            str(vote_value), str(vote_value)))
            db.commit()
            db.close()
        else:
            await message.channel.send(
                self.messages.karma_vote_notpassed
                    .format(emote=str(emote),
                            minimum=str(self.config.vote_minimum)))
            return

        await message.channel.send(
                self.messages.karma_vote_result
                .format(emote=str(emote), result=str(vote_value)))
        return

    async def get(self, message):
        content = message.content.split()
        if len(content) != 3:
            return await self.get_all(message.channel)

        emote = content[2]
        if len(emote) != 1 or emote[0] not in UNICODE_EMOJI:
            try:
                emote_id = int(emote.split(':')[2][:-1])
                emote = await message.channel.guild.fetch_emoji(emote_id)
            except (ValueError, IndexError):
                await message.channel.send(self.messages.karma_get_format)
                return
            except discord.NotFound:
                await message.channel.send(self.messages.karma_emote_not_found)
                return

        row = self.get_row("bot_karma_emoji", "emoji_id",
                           emote if type(emote) is str else emote.id)
        if row:
            await message.channel.send(
                    self.messages.karma_get
                    .format(emote=str(emote), value=str(row[1])))
        else:
            await message.channel.send(
                    self.messages.karma_get_emote_not_voted
                    .format(emote=str(emote)))

    async def get_all(self, channel):
        errors = ""
        for value in ["1", "-1"]:
            db = mysql.connector.connect(**self.config.connection)
            cursor = db.cursor()
            cursor.execute("SELECT * FROM bot_karma_emoji "
                           "WHERE value = %s", (value,))
            row = cursor.fetchall()
            db.close()
            await channel.send("Hodnota {}:".format(str(value)))

            message = ""
            for cnt, emote in enumerate(row):
                if cnt % 8 == 0 and cnt:
                    await channel.send(message)
                    message = ""
                try:
                    emote = await channel.guild.fetch_emoji(int(emote[0]))
                    message += str(emote)
                except discord.NotFound:
                    errors += str(emote[0]) + ", "
                except ValueError:
                    if type(emote[0]) == bytearray:
                        message += emote[0].decode()
                    else:
                        message += str(emote[0])

            try:
                await channel.send(message)
            except discord.errors.HTTPException:
                continue

        if errors != "":
            await channel.send("{}\n{}".format(self.messages.toaster_pls,
                                               errors))

    async def karma_give(self, message):
        input_string = message.content.split()
        if len(input_string) < 4:
            await message.channel.send(self.messages.karma_give_format)
        else:
            try:
                number = int(input_string[2])
            except ValueError:
                await message.channel.send(
                        self.messages.karma_give_format_number.format(
                            input=input_string[2])
                        )
                return
            for member in message.mentions:
                self.update_karma(member, message.author, number)
            if number >= 0:
                await message.channel.send(self.messages.karma_give_success)
            else:
                await message.channel.send(
                        self.messages.karma_give_negative_success
                        )

    async def leaderboard(self, channel, action, order):
        output = "\u200b\n==================\n "
        if action == 'give':
            database = 'bot_karma_giving'
            if order == "DESC":
                database_index = 1
                column = 'positive'
                output += "KARMA GIVINGBOARD \n"
            else:
                database_index = 2
                order = "DESC"
                column = 'negative'
                output += "KARMA ISHABOARD \n"
        elif action == 'get':
            database_index = 1
            database = 'bot_karma'
            column = 'karma'
            if order == "DESC":
                output += "KARMA LEADERBOARD \n"
            else:
                output += "KARMA BAJKARBOARD \n"
        else:
            raise Exception('Action neni get/give')
        output += "==================\n"

        board = self.get_leaderboard(database, column, order)
        guild = self.client.get_guild(self.config.guild_id)
        for i, user in enumerate(board, 1):
            username = guild.get_member(int(user[0]))
            if username is None:
                continue
            username = str(username.name)
            line = '{} – {}: {} pts\n'.format(i, username,
                                              user[database_index])
            output += line
        # '\n Full leaderboard - TO BE ADDED (SOON*tm*) \n'
        await channel.send(output)
