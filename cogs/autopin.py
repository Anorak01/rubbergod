"""
Cog controlling auto pinning of messages. Create priority pinned messages in channels.
"""

import datetime
from typing import List

import disnake
from disnake.ext import commands

import utils
from cogs.base import Base
from config.app_config import config
from config.messages import Messages
from permissions import permission_check
from repository import pin_repo
from repository.database.pin_map import PinMap


class AutoPin(Base, commands.Cog):
    def __init__(self, bot):
        self.warning_time = datetime.datetime.utcnow() - datetime.timedelta(
            minutes=config.autopin_warning_cooldown
        )
        self.bot = bot
        self.repo = pin_repo.PinRepository()

    @commands.guild_only()
    @commands.check(permission_check.helper_plus)
    @commands.slash_command(name="pin")
    async def pin(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @pin.sub_command(name="add", description=Messages.autopin_add_brief)
    async def add(self, inter: disnake.ApplicationCommandInteraction, message_url: str):
        try:
            converter = commands.MessageConverter()
            message: disnake.Message = await converter.convert(inter, message_url)

            if message.is_system():
                return await inter.send(Messages.autopin_system_message)

            if len(await message.channel.pins()) == 50:
                return await inter.send(Messages.autopin_max_pins_error)

            self.repo.add_or_update_channel(str(message.channel.id), str(message.id))

            if not message.pinned:
                await message.pin()

            await inter.send(Messages.autopin_add_done)
        except commands.MessageNotFound:
            return await inter.send(Messages.autopin_add_unknown_message)

    @pin.sub_command(name="remove", description=Messages.autopin_remove_brief)
    async def remove(
        self,
        inter: disnake.ApplicationCommandInteraction,
        channel: disnake.TextChannel = None
    ):
        if channel is None:
            channel = inter.channel

        if self.repo.find_channel_by_id(str(channel.id)) is None:
            await inter.send(utils.fill_message("autopin_remove_not_exists", channel_name=channel.mention))
            return

        self.repo.remove_channel(str(channel.id))
        await inter.send(Messages.autopin_remove_done)

    @pin.sub_command(name="list", description=Messages.autopin_list_brief)
    async def get_list(self, inter: disnake.ApplicationCommandInteraction):
        mappings: List[PinMap] = self.repo.get_mappings()

        if not mappings:
            return await inter.send(Messages.autopin_no_messages)

        lines: List[str] = []
        for item in mappings:
            try:
                channel: disnake.TextChannel = await self.bot.get_or_fetch_channel(int(item.channel_id))
            except disnake.NotFound:
                lines.append(utils.fill_message("autopin_list_unknown_channel", channel_id=item.channel_id))
                self.repo.remove_channel(str(item.channel_id))
                continue

            try:
                message: disnake.Message = await channel.fetch_message(int(item.message_id))
                jump_url: str = message.jump_url
                msg: str = utils.fill_message("autopin_list_item", channel=channel.mention, url=jump_url)
            except disnake.NotFound:
                msg: str = utils.fill_message("autopin_list_unknown_message", channel=channel.mention)
            finally:
                lines.append(msg)

        for part in utils.split_to_parts(lines, 10):
            await inter.send("\n".join(part))

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel: disnake.TextChannel, _):
        """
        repin priority pin if new pin is added
        """
        pin_map: PinMap = self.repo.find_channel_by_id(str(channel.id))

        # This channel is not used to check priority pins.
        if pin_map is None:
            return

        pins: List[int] = [message.id for message in await channel.pins()]

        # Mapped pin was removed. Remove from map.
        if not int(pin_map.message_id) in pins:
            self.repo.remove_channel(str(channel.id))

        # check priority pin is first
        elif pins[0] != int(pin_map.message_id):
            message: disnake.Message = await channel.fetch_message(int(pin_map.message_id))

            # Message doesn't exist. Remove from map.
            if message is None:
                self.repo.remove_channel(str(channel.id))
                return

            await message.unpin()
            await message.pin()

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: disnake.RawMessageDeleteEvent):
        """
        if the priority pin is deleted remove it from the map
        """
        pin_map: PinMap = self.repo.find_channel_by_id(str(payload.channel_id))

        if pin_map is None or pin_map.message_id != str(payload.message_id):
            return

        self.repo.remove_channel(str(payload.channel_id))

    async def handle_reaction(self, ctx):
        """
        if the message has X or more 'pushpin' emojis pin the message
        """
        message = ctx.message
        channel = ctx.channel
        if ctx.emoji == "📌" and ctx.member.id in config.autopin_banned_users:
            await message.remove_reaction("📌", ctx.member)
            return
        for reaction in message.reactions:
            if (
                reaction.emoji == "📌"
                and reaction.count >= config.autopin_count
                and not message.pinned
                and not message.is_system()
                and message.channel.id not in config.autopin_banned_channels
            ):
                # prevent spamming max_pins_error message in channel
                pin_count = await channel.pins()
                if len(pin_count) == 50:
                    now = datetime.datetime.utcnow()
                    if self.warning_time + datetime.timedelta(minutes=config.autopin_warning_cooldown) < now:
                        await channel.send(
                            f"{ctx.member.mention} {Messages.autopin_max_pins_error}\n{ctx.message.jump_url}"
                        )
                        self.warning_time = now
                    return

                users = await reaction.users().flatten()
                await self.log(message, users)
                await message.pin()
                await message.clear_reaction("📌")
                break

    async def log(self, message, users):
        """
        Logging message link and users that pinned message
        """
        embed = disnake.Embed(title="📌 Auto pin message log", color=disnake.Colour.yellow())
        user_names = ", ".join([f"{user.mention}({user.name})" for user in users])
        embed.add_field(name="Users", value=user_names if len(user_names) > 0 else "**Missing users**")
        embed.add_field(
            name="Message in channel",
            value=f"[#{message.channel.name}]({message.jump_url})",
            inline=False
        )
        embed.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
        channel = self.bot.get_channel(config.log_channel)
        await channel.send(embed=embed)


def setup(bot):
    bot.add_cog(AutoPin(bot))
