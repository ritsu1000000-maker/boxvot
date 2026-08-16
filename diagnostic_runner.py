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
    # 最小処理で即時応答します。これも失敗する場合はコマンド処理ではなく
    # Bot自体がDiscordに接続されていない可能性が高いです。
    await interaction.response.send_message(
        f"✅ Botは応答しています。Ping: **{round(app.bot.latency * 1000)} ms**",
        ephemeral=True,
    )


@app.bot.tree.command(name="shopsync", description="ショップのスラッシュコマンドを強制再同期します")
async def shopsync(interaction: discord.Interaction):
    # Discordの3秒制限より先にACKします。
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
    command_name = getattr(interaction.command, "qualified_name", None)

    print(
        f"[slash-error] command={command_name} "
        f"user={interaction.user.id} error={original!r}",
        flush=True,
    )
    traceback.print_exception(type(original), original, original.__traceback__)

    # Discord側に古いコマンドが残っている場合は、その場で最新定義を再同期します。
    # 実行中のInteraction自体を別コマンドとして再実行することはしません。
    if isinstance(error, app_commands.CommandNotFound):
        try:
            scope, subs = await runner_plus.sync_latest_commands(
                app.bot.tree,
                clear_first=True,
            )
            message = (
                "🔄 Discord側に古いコマンド情報が残っていたため再同期しました。\n"
                f"対象: `{scope}` / `/shopadmin` **{len(subs)}コマンド**\n"
                "数秒後に同じコマンドをもう一度実行してください。"
            )
        except Exception as sync_exc:
            print("[slash-error] auto-resync failed:", repr(sync_exc), flush=True)
            message = (
                "❌ コマンド定義が一致しておらず、自動再同期にも失敗しました。\n"
                f"`{type(sync_exc).__name__}: {str(sync_exc)[:900]}`"
            )
    else:
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
    print("[diagnostic_runner] ACTIVE - timeout protection enabled", flush=True)
    Thread(target=app.run_web, daemon=True).start()
    app.bot.run(app.DISCORD_TOKEN, reconnect=True)
