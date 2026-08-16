from threading import Thread

import discord
from discord import app_commands

import runner
import extra_commands

app = runner.app
POST_READY_SYNC_DONE = False


async def sync_latest_commands(tree, *, clear_first=False):
    """現在の /shopadmin をDiscordへ確実に同期します。"""
    try:
        tree.remove_command("shopadmin")
    except Exception:
        pass
    tree.add_command(app.admin_group)

    subcommands = [command.name for command in app.admin_group.commands]

    if app.GUILD_ID:
        guild_id = int(str(app.GUILD_ID).strip())
        guild = discord.Object(id=guild_id)

        if clear_first:
            tree.clear_commands(guild=guild)
            await tree.sync(guild=guild)

        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)
        scope = f"guild {guild_id}"
    else:
        synced = await tree.sync()
        scope = "global"

    print(
        f"[slash-sync] scope={scope} root={', '.join(c.name for c in synced)}",
        flush=True,
    )
    print(
        f"[slash-sync] /shopadmin {len(subcommands)} subcommands: "
        + ", ".join(subcommands),
        flush=True,
    )
    return scope, subcommands


# 将来コマンドを追加したとき手動でも再同期できます。
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
        scope, subs = await sync_latest_commands(app.bot.tree, clear_first=True)
        await interaction.followup.send(
            f"✅ スラッシュコマンドを再同期しました。\n"
            f"対象: `{scope}`\n"
            f"`/shopadmin` サブコマンド: **{len(subs)}個**",
            ephemeral=True,
        )
    except Exception as exc:
        print("Manual slash sync error:", repr(exc), flush=True)
        await interaction.followup.send(
            f"❌ 同期に失敗しました: `{type(exc).__name__}: {exc}`",
            ephemeral=True,
        )


async def force_sync_setup_hook(self):
    print("[runner_plus] ACTIVE - latest command loader enabled", flush=True)

    for product in app.load_json(app.PRODUCTS_FILE):
        try:
            self.add_view(app.ProductView(product["id"]))
        except Exception as exc:
            print("Product view restore error:", repr(exc), flush=True)

    try:
        await sync_latest_commands(self.tree, clear_first=True)
    except Exception as exc:
        print("Startup slash sync error:", repr(exc), flush=True)
        raise


app.VendingBot.setup_hook = force_sync_setup_hook


@app.bot.event
async def on_ready():
    global POST_READY_SYNC_DONE

    print(f"Discord login: {app.bot.user}", flush=True)

    # setup_hookの同期に加えて、Gateway接続完了後にも一度だけ同期します。
    if POST_READY_SYNC_DONE:
        return

    POST_READY_SYNC_DONE = True
    try:
        scope, subs = await sync_latest_commands(app.bot.tree, clear_first=False)
        print(
            f"[post-ready-sync] OK {scope} /shopadmin={len(subs)}",
            flush=True,
        )
    except Exception as exc:
        POST_READY_SYNC_DONE = False
        print("Post-ready slash sync error:", repr(exc), flush=True)


if __name__ == "__main__":
    Thread(target=app.run_web, daemon=True).start()
    app.bot.run(app.DISCORD_TOKEN, reconnect=True)
