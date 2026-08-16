from threading import Thread

import runner
import extra_commands

app = runner.app


if __name__ == "__main__":
    Thread(target=app.run_web, daemon=True).start()
    app.bot.run(app.DISCORD_TOKEN, reconnect=True)
