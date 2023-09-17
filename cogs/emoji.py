"""
Cog containing information about week (odd/even) and its relation to calendar/academic week.
"""

import io
import zipfile

import disnake
from disnake.ext import commands

from cogs.base import Base
from config import cooldowns
from config.messages import Messages


class Emoji(Base, commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @cooldowns.default_cooldown
    @commands.slash_command(name="emoji", description=Messages.week_brief)
    async def get_emojis(self, inter: disnake.ApplicationCommandInteraction):
        """Get all emojis from server"""
        emojis = await inter.guild.fetch_emojis()
        with zipfile.ZipFile("emojis.zip", "w") as zip_file:
            for emoji in emojis:
                with io.BytesIO() as image_binary:
                    if emoji.animated:
                        emoji_name = f"{emoji.name}.gif"
                    else:
                        emoji_name = f"{emoji.name}.png"
                    await emoji.save(image_binary)
                    zip_file.writestr(emoji_name, image_binary.getvalue())

        await inter.send(file=disnake.File("emojis.zip"))


def setup(bot):
    bot.add_cog(Emoji(bot))
