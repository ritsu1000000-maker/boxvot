import time
from threading import Thread

import discord
from discord import app_commands

import main as app

PROCESS_STARTED_AT = time.monotonic()
BOT_HEALTH = {
    "ever_ready": False,
    "last_ready_at": 0.0,
    "last_disconnect_at": 0.0,
}


def stock_display(product):
    if "stock_limit" in product:
        value = int(product.get("stock_limit", 0))
        return "-" if value == -1 else str(max(0, value))
    return str(len(product.get("stock", [])))


def has_available_stock(product):
    if not product or not product.get("stock"):
        return False
    if "stock_limit" in product:
        value = int(product.get("stock_limit", 0))
        return value == -1 or value > 0
    return len(product.get("stock", [])) > 0


def reserve_stock(product_id):
    products = app.load_json(app.PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == product_id), None)
    if not product or not product.get("stock"):
        return None

    if "stock_limit" in product:
        value = int(product.get("stock_limit", 0))
        if value == 0:
            return None
        item = product["stock"][0]
        if value > 0:
            product["stock_limit"] = value - 1
            app.save_json(app.PRODUCTS_FILE, products)
        return item

    item = product["stock"].pop(0)
    app.save_json(app.PRODUCTS_FILE, products)
    return item


def restore_stock(product_id, item):
    products = app.load_json(app.PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == product_id), None)
    if not product:
        return

    if "stock_limit" in product:
        value = int(product.get("stock_limit", 0))
        if value == -1:
            return
        product["stock_limit"] = max(0, value) + 1
        app.save_json(app.PRODUCTS_FILE, products)
        return

    product.setdefault("stock", []).insert(0, item)
    app.save_json(app.PRODUCTS_FILE, products)


app.stock_display = stock_display
app.has_available_stock = has_available_stock
app.reserve_stock = reserve_stock
app.restore_stock = restore_stock


class ProductView(discord.ui.View):
    def __init__(self, product_id: str):
        super().__init__(timeout=None)
        self.product_id = product_id

        product = app.get_product(product_id)
        is_free = bool(product and int(product.get("price", 0)) == 0)

        button = discord.ui.Button(
            label="無料で受け取る" if is_free else "PayPayで購入する",
            style=(
                discord.ButtonStyle.success
                if is_free
                else discord.ButtonStyle.primary
            ),
            custom_id=f"vending:buy:{product_id}",
        )
        button.callback = self.buy_callback
        self.add_item(button)

    async def buy_callback(self, interaction: discord.Interaction):
        product = app.get_product(self.product_id)
        if not product:
            await interaction.response.send_message(
                "商品が見つかりません。", ephemeral=True
            )
            return

        if not product.get("stock"):
            await interaction.response.send_message(
                "この商品はまだ商品ファイルが登録されていません。",
                ephemeral=True,
            )
            return

        if not has_available_stock(product):
            await interaction.response.send_message(
                "この商品は現在売り切れです。", ephemeral=True
            )
            return

        if int(product.get("price", 0)) > 0:
            await interaction.response.send_modal(app.BuyModal(self.product_id))
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        reserved = reserve_stock(self.product_id)
        if not reserved:
            await interaction.followup.send(
                "この商品は直前に売り切れました。", ephemeral=True
            )
            return

        order_id = app.new_order_id()
        order = {
            "id": order_id,
            "status": "free_order",
            "buyer_id": str(interaction.user.id),
            "buyer_name": str(interaction.user),
            "product_id": product["id"],
            "product_name": product["name"],
            "price": 0,
            "paypay_link": "",
            "passcode": "",
            "paypay_amount": 0,
            "paypay_status_at_submit": None,
            "reserved_item": reserved,
            "created_at": discord.utils.utcnow().isoformat(),
        }

        orders = app.load_json(app.ORDERS_FILE)
        orders.append(order)
        app.save_json(app.ORDERS_FILE, orders)

        try:
            await app.send_product_to_buyer(order)
            order["status"] = "delivered"
            order["delivered_at"] = discord.utils.utcnow().isoformat()
            app.save_json(app.ORDERS_FILE, orders)
        except Exception as exc:
            print("Free delivery error:", repr(exc), flush=True)
            order["status"] = "delivery_failed"
            order["delivery_error"] = str(exc)
            app.save_json(app.ORDERS_FILE, orders)
            restore_stock(product["id"], reserved)
            await interaction.followup.send(
                "❌ 商品のDM送信に失敗しました。管理者に連絡してください。",
                ephemeral=True,
            )
            return

        try:
            target = await app.admin_target()
            embed = discord.Embed(
                title="🎁 0円商品を自動納品しました",
                description=(
                    f"購入者: <@{interaction.user.id}>\n"
                    f"商品: **{product['name']}**\n"
                    "価格: **¥0**\n"
                    f"注文ID: `{order_id}`"
                ),
            )
            await target.send(embed=embed)
        except Exception as exc:
            print("Admin notify error:", repr(exc), flush=True)

        await interaction.followup.send(
            "✅ **0円商品の受け取りが完了しました。**\n"
            "商品をDiscordのDMへ送信しました。",
            ephemeral=True,
        )


app.ProductView = ProductView

# Discord側の表示制限を外し、実行時はADMIN_USER_IDで判定する。
try:
    app.admin_group.default_permissions = None
except Exception:
    pass

for command_name in ("product_add", "stock_add", "panel", "stock_set"):
    try:
        app.admin_group.remove_command(command_name)
    except Exception:
        pass


@app.admin_group.command(name="product_add", description="商品を追加")
@app_commands.describe(
    name="商品名",
    price="価格（円・0円可）",
    description="商品説明",
    stock="在庫数（-1で無限）",
)
async def product_add(
    interaction: discord.Interaction,
    name: str,
    price: int,
    description: str,
    stock: int = 1,
):
    if not await app.require_admin(interaction):
        return

    if price < 0:
        await interaction.response.send_message(
            "価格は0円以上にしてください。", ephemeral=True
        )
        return

    if stock < -1:
        await interaction.response.send_message(
            "在庫は `-1`（無限）または0以上で指定してください。",
            ephemeral=True,
        )
        return

    products = app.load_json(app.PRODUCTS_FILE)
    product = {
        "id": app.uuid.uuid4().hex[:6],
        "name": name[:80],
        "price": int(price),
        "description": description[:500],
        "stock": [],
        "stock_limit": int(stock),
        "created_at": discord.utils.utcnow().isoformat(),
    }
    products.append(product)
    app.save_json(app.PRODUCTS_FILE, products)
    app.bot.add_view(ProductView(product["id"]))

    stock_text = "-" if stock == -1 else str(stock)
    await interaction.response.send_message(
        f"✅ 商品を追加しました。\n"
        f"ID: `{product['id']}`\n"
        f"商品: **{product['name']}**\n"
        f"価格: **{app.yen(product['price'])}**\n"
        f"在庫: **{stock_text}**\n\n"
        f"次に `/shopadmin stock_add` で商品ファイルを登録してください。",
        ephemeral=True,
    )


@app.admin_group.command(name="stock_add", description="商品ファイルを登録")
@app_commands.describe(id="商品ID", file="購入後に送る商品ファイル")
async def stock_add(
    interaction: discord.Interaction,
    id: str,
    file: discord.Attachment,
):
    if not await app.require_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    products = app.load_json(app.PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == id.strip()), None)
    if not product:
        await interaction.followup.send(
            "商品IDが見つかりません。", ephemeral=True
        )
        return

    filename = app.Path(file.filename).name
    saved_name = f"{app.uuid.uuid4().hex}_{filename}"
    saved_path = app.UPLOAD_DIR / saved_name

    try:
        await file.save(saved_path)
    except Exception as exc:
        print("Attachment save error:", repr(exc), flush=True)
        await interaction.followup.send(
            "ファイルの保存に失敗しました。", ephemeral=True
        )
        return

    # 指定在庫数で同じ商品ファイルを納品する。
    product["stock"] = [{
        "type": "file",
        "filename": filename,
        "path": str(saved_path.relative_to(app.BASE_DIR)).replace("\\", "/"),
    }]

    if "stock_limit" not in product:
        product["stock_limit"] = 1

    app.save_json(app.PRODUCTS_FILE, products)

    await interaction.followup.send(
        f"✅ **{product['name']}** の商品ファイルを登録しました。\n"
        f"現在庫: **{stock_display(product)}**",
        ephemeral=True,
    )


@app.admin_group.command(name="stock_set", description="商品の在庫数を変更")
@app_commands.describe(id="商品ID", amount="在庫数（-1で無限）")
async def stock_set(
    interaction: discord.Interaction,
    id: str,
    amount: int,
):
    if not await app.require_admin(interaction):
        return

    if amount < -1:
        await interaction.response.send_message(
            "在庫は `-1`（無限）または0以上で指定してください。",
            ephemeral=True,
        )
        return

    products = app.load_json(app.PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == id.strip()), None)
    if not product:
        await interaction.response.send_message(
            "商品IDが見つかりません。", ephemeral=True
        )
        return

    product["stock_limit"] = int(amount)
    app.save_json(app.PRODUCTS_FILE, products)

    shown = "-" if amount == -1 else str(amount)
    await interaction.response.send_message(
        f"✅ **{product['name']}** の在庫を **{shown}** に変更しました。",
        ephemeral=True,
    )


@app.admin_group.command(name="panel", description="購入者向け商品パネルを設置")
@app_commands.describe(id="商品ID")
async def panel(interaction: discord.Interaction, id: str):
    if not await app.require_admin(interaction):
        return

    product = app.get_product(id.strip())
    if not product:
        await interaction.response.send_message(
            "商品IDが見つかりません。", ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"🛒 {product['name']}",
        description=product["description"],
    )
    embed.add_field(
        name="価格",
        value=app.yen(product["price"]),
        inline=True,
    )
    embed.add_field(
        name="在庫",
        value=stock_display(product),
        inline=True,
    )
    embed.set_footer(text=f"商品ID: {product['id']}")

    await interaction.response.send_message(
        embed=embed,
        view=ProductView(product["id"]),
    )


async def patched_setup_hook(self):
    for product in app.load_json(app.PRODUCTS_FILE):
        try:
            self.add_view(ProductView(product["id"]))
        except Exception as exc:
            print("Product view restore error:", repr(exc), flush=True)

    if app.GUILD_ID:
        try:
            guild_id = int(str(app.GUILD_ID).strip())
        except ValueError as exc:
            raise RuntimeError(
                "GUILD_ID が数字ではありません。DiscordのサーバーIDを設定してください。"
            ) from exc

        guild = discord.Object(id=guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        print(
            f"Slash commands synced to guild {guild_id}: "
            + ", ".join(command.name for command in synced),
            flush=True,
        )
    else:
        synced = await self.tree.sync()
        print(
            "Slash commands synced globally: "
            + ", ".join(command.name for command in synced),
            flush=True,
        )


app.VendingBot.setup_hook = patched_setup_hook


@app.bot.event
async def on_ready():
    BOT_HEALTH["ever_ready"] = True
    BOT_HEALTH["last_ready_at"] = time.monotonic()
    print(f"Discord login: {app.bot.user}", flush=True)


@app.bot.event
async def on_disconnect():
    BOT_HEALTH["last_disconnect_at"] = time.monotonic()
    print("Discord disconnected. reconnecting...", flush=True)


@app.bot.event
async def on_resumed():
    BOT_HEALTH["last_ready_at"] = time.monotonic()
    print("Discord session resumed.", flush=True)


def patched_health():
    now = time.monotonic()
    uptime = now - PROCESS_STARTED_AT
    ready = bool(app.bot.is_ready() and not app.bot.is_closed())

    if ready:
        BOT_HEALTH["ever_ready"] = True
        BOT_HEALTH["last_ready_at"] = now
        return app.jsonify({
            "ok": True,
            "discord_ready": True,
            "bot": str(app.bot.user) if app.bot.user else None,
            "uptime_seconds": int(uptime),
        }), 200

    if uptime < 180:
        return app.jsonify({
            "ok": True,
            "discord_ready": False,
            "state": "starting",
            "uptime_seconds": int(uptime),
        }), 200

    last_ready = float(BOT_HEALTH.get("last_ready_at", 0.0) or 0.0)
    if BOT_HEALTH.get("ever_ready") and last_ready and (now - last_ready) < 180:
        return app.jsonify({
            "ok": True,
            "discord_ready": False,
            "state": "reconnecting",
            "seconds_since_ready": int(now - last_ready),
        }), 200

    return app.jsonify({
        "ok": False,
        "discord_ready": False,
        "state": "unhealthy",
        "uptime_seconds": int(uptime),
    }), 503


app.web.view_functions["health"] = patched_health


if __name__ == "__main__":
    Thread(target=app.run_web, daemon=True).start()
    app.bot.run(app.DISCORD_TOKEN, reconnect=True)
