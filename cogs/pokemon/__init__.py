async def setup(bot):
    from .spawn_catch import SpawnCatchCog
    from .box import BoxCog
    from .shop import BallShopCog
    from .leveling import LevelingCog

    await bot.add_cog(SpawnCatchCog(bot))
    await bot.add_cog(BoxCog(bot))
    await bot.add_cog(BallShopCog(bot))
    await bot.add_cog(LevelingCog(bot))
