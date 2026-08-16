from threading import Thread

import discord
from discord import app_commands

import runner
import extra_commands

app = runner.app


# 将来コマンドを追加したとき、Discord上へ手動で強制再同期できる。
try:
    app.admin_group.remove_command("sync")
except Exception:
    pass


@app.admin_group.command(name="sync", description="スラッシュコマンドをDiscordへ強制再同期")
async def sync_commands(interaction: discord.Interaction):
    if not await app.require_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        # 現在の最新GroupをTreeへ積み直す
        try:
            app.bot.tree.remove_command("shopadmin")
        except Exception:
            pass
        app.bot.tree.add_command(app.admin_group)

        if app.GUILD_ID:
            guild_id = int(str(app.GUILD_ID).strip())
            guild = discord.Object(id=guild_id)

            # Discord側の古いGuild Commandを一度削除してから再登録する。
            app.bot.tree.clear_commands(guild=guild)
            await app.bot.tree.sync(guild=guild)

            app.bot.tree.copy_global_to(guild=guild)
            synced = await app.bot.tree.sync(guild=guild)
            scope = f"guild {guild_id}"
        else:
            synced = await app.bot.tree.sync()
            scope = "global"

        subs = ", ".join(command.name for command in app.admin_group.commands)
        await interaction.followup.send(
            f"✅ スラッシュコマンドを強制再同期しました。\n"
            f"対象: `{scope}`\n"
            f"`/shopadmin` サブコマンド: **{len(app.admin_group.commands)}個**\n"
            f"{subs}",
            ephemeral=True,
        )
    except Exception as exc:
        print("Manual slash sync error:", repr(exc), flush=True)
        await interaction.followup.send(
            f"❌ 同期に失敗しました: `{type(exc).__name__}: {exc}`",
            ephemeral=True,
        )


async def force_sync_setup_hook(self):
    # 永続ボタンを復元
    for product in app.load_json(app.PRODUCTS_FILE):
        try:
            self.add_view(app.ProductView(product["id"]))
        except Exception as exc:
            print("Product view restore error:", repr(exc), flush=True)

    # main.py がTreeへ登録した古い /shopadmin を捨て、
    # extra_commands.py 読み込み後の最新Groupを積み直す。
    try:
        self.tree.remove_command("shopadmin")
    except Exception:
        pass
    self.tree.add_command(app.admin_group)

    subcommands = [command.name for command in app.admin_group.commands]
    print(
        f"Preparing /shopadmin with {len(subcommands)} subcommands: "
        + ", ".join(subcommands),
        flush=True,
    )

    if app.GUILD_ID:
        try:
            guild_id = int(str(app.GUILD_ID).strip())
        except ValueError as exc:
            raise RuntimeError(
                "GUILD_ID が数字ではありません。DiscordのサーバーIDを設定してください。"
            ) from exc

        guild = discord.Object(id=guild_id)

        # 古いGuild CommandをDiscord側から完全に削除する。
        self.tree.clear_commands(guild=guild)
        deleted = await self.tree.sync(guild=guild)
        print(
            f"Old guild commands cleared for {guild_id}. "
            f"Remaining after clear: {len(deleted)}",
            flush=True,
        )

        # 最新のグローバル定義をGuildへコピーして即時同期。
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)

        print(
            f"Slash commands FORCE synced to guild {guild_id}: "
            + ", ".join(command.name for command in synced),
            flush=True,
        )
        print(
            f"/shopadmin subcommands synced: {len(subcommands)} -> "
            + ", ".join(subcommands),
            flush=True,
        )
    else:
        synced = await self.tree.sync()
        print(
            "Slash commands synced globally: "
            + ", ".join(command.name for command in synced),
            flush=True,
        )


# bot.run() の前なので、起動時にはこのsetup_hookが使われる。
app.VendingBot.setup_hook = force_sync_setup_hook


if __name__ == "__main__":
    Thread(target=app.run_web, daemon=True).start()
    app.bot.run(app.DISCORD_TOKEN, reconnect=True)
