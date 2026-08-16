from threading import Thread
import traceback

import discord
from discord import app_commands

import runner_plus

app = runner_plus.app


for name in ("botping", "shopsync"):
    try:
        app.bot.tree.remove_command(name)
    except Exception:
        pass


@app.bot.tree.command(name="botping", description="Botが正常に応答できるか確認します")
async def botping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"✅ Botは応答しています。Ping: **{round(app.bot.latency * 1000)} ms**",
        ephemeral=True,
    )


@app.bot.tree.command(name="shopsync", description="ショップのスラッシュコマンドを強制再同期します")
async def shopsync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)

    if not app.is_admin(interaction.user.id):
        await interaction.followup.send("管理者専用です。", ephemeral=True)
        return

    try:
        scope, subs = await runner_plus.sync_latest_commands(
            app.bot.tree,
            clear_first=True,
        )
        await interaction.followup.send(
            f"✅ 再同期しました。対象: `{scope}` / "
            f"`/shopadmin` **{len(subs)}コマンド**",
            ephemeral=True,
        )
    except Exception as exc:
        print("/shopsync error:", repr(exc), flush=True)
        traceback.print_exc()
        await interaction.followup.send(
            f"❌ 再同期エラー: `{type(exc).__name__}: {str(exc)[:1200]}`",
            ephemeral=True,
        )


@app.bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    original = getattr(error, "original", error)
    print(
        f"[slash-error] command={getattr(interaction.command, 'qualified_name', None)} "
        f"user={interaction.user.id} error={original!r}",
        flush=True,
    )
    traceback.print_exception(type(original), original, original.__traceback__)

    message = (
        "❌ コマンド実行中にエラーが発生しました。\n"
        f"`{type(original).__name__}: {str(original)[:1200]}`"
    )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception as send_exc:
        print("[slash-error] failed to send error response:", repr(send_exc), flush=True)


if __name__ == "__main__":
    print("[diagnostic_runner] ACTIVE", flush=True)
    Thread(target=app.run_web, daemon=True).start()
    app.bot.run(app.DISCORD_TOKEN, reconnect=True)
