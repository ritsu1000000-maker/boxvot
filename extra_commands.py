import io
import json
import time

import discord
from discord import app_commands

import runner as base

app = base.app


def _load_product(product_id: str):
    products = app.load_json(app.PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == product_id.strip()), None)
    return products, product


def _product_status(product):
    if product.get("enabled", True) is False:
        return "停止中"
    if not product.get("stock"):
        return "商品ファイル未登録"
    if not base.has_available_stock(product):
        return "売り切れ"
    return "販売中"


def _stock_text(product):
    return base.stock_display(product)


# 既存の購入ボタンにも販売停止を即時反映する。
_original_buy_callback = base.ProductView.buy_callback


async def _guarded_buy_callback(self, interaction: discord.Interaction):
    product = app.get_product(self.product_id)
    if product and product.get("enabled", True) is False:
        await interaction.response.send_message(
            "⛔ この商品は現在販売停止中です。",
            ephemeral=True,
        )
        return
    return await _original_buy_callback(self, interaction)


base.ProductView.buy_callback = _guarded_buy_callback
app.ProductView = base.ProductView


EXTRA_COMMANDS = (
    "product_list",
    "product_info",
    "product_name",
    "price_set",
    "description_set",
    "sale_on",
    "sale_off",
    "panel_all",
    "stock_info",
    "stock_plus",
    "order_info",
    "buyer_orders",
    "retry_delivery",
    "shop_stats",
    "bot_status",
    "backup",
    "help",
    "test_dm",
)

for _name in EXTRA_COMMANDS:
    try:
        app.admin_group.remove_command(_name)
    except Exception:
        pass


@app.admin_group.command(name="product_list", description="商品一覧を表示")
async def product_list(interaction: discord.Interaction):
    if not await app.require_admin(interaction):
        return

    products = app.load_json(app.PRODUCTS_FILE)
    if not products:
        await interaction.response.send_message("商品はまだありません。", ephemeral=True)
        return

    lines = []
    for p in products[:40]:
        mark = "🟢" if p.get("enabled", True) else "⛔"
        lines.append(
            f"{mark} `{p['id']}` **{p['name']}** / "
            f"{app.yen(p['price'])} / 在庫 `{_stock_text(p)}`"
        )

    if len(products) > 40:
        lines.append(f"…ほか {len(products) - 40} 件")

    embed = discord.Embed(
        title=f"商品一覧 ({len(products)}件)",
        description="\n".join(lines)[:3900],
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app.admin_group.command(name="product_info", description="商品の詳細を確認")
@app_commands.describe(id="商品ID")
async def product_info(interaction: discord.Interaction, id: str):
    if not await app.require_admin(interaction):
        return

    product = app.get_product(id.strip())
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"商品詳細: {product['name']}",
        description=product.get("description") or "説明なし",
    )
    embed.add_field(name="商品ID", value=f"`{product['id']}`", inline=True)
    embed.add_field(name="価格", value=app.yen(product["price"]), inline=True)
    embed.add_field(name="在庫", value=_stock_text(product), inline=True)
    embed.add_field(name="状態", value=_product_status(product), inline=True)
    embed.add_field(
        name="商品ファイル",
        value="登録済み" if product.get("stock") else "未登録",
        inline=True,
    )
    embed.add_field(
        name="作成日時",
        value=product.get("created_at", "不明")[:25],
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app.admin_group.command(name="product_name", description="商品名を変更")
@app_commands.describe(id="商品ID", name="新しい商品名")
async def product_name(interaction: discord.Interaction, id: str, name: str):
    if not await app.require_admin(interaction):
        return

    products, product = _load_product(id)
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    old = product["name"]
    product["name"] = name[:80]
    app.save_json(app.PRODUCTS_FILE, products)
    await interaction.response.send_message(
        f"✅ **{old}** → **{product['name']}** に変更しました。\n"
        "既に設置済みのパネル表示を変えたい場合は `/shopadmin panel` をもう一度実行してください。",
        ephemeral=True,
    )


@app.admin_group.command(name="price_set", description="商品の価格を変更")
@app_commands.describe(id="商品ID", price="新しい価格（0円可）")
async def price_set(interaction: discord.Interaction, id: str, price: int):
    if not await app.require_admin(interaction):
        return
    if price < 0:
        await interaction.response.send_message("価格は0円以上にしてください。", ephemeral=True)
        return

    products, product = _load_product(id)
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    old = int(product["price"])
    product["price"] = int(price)
    app.save_json(app.PRODUCTS_FILE, products)
    await interaction.response.send_message(
        f"✅ **{product['name']}** の価格を "
        f"{app.yen(old)} → **{app.yen(price)}** に変更しました。\n"
        "ボタン表示も更新する場合は `/shopadmin panel` を再実行してください。",
        ephemeral=True,
    )


@app.admin_group.command(name="description_set", description="商品説明を変更")
@app_commands.describe(id="商品ID", description="新しい商品説明")
async def description_set(
    interaction: discord.Interaction,
    id: str,
    description: str,
):
    if not await app.require_admin(interaction):
        return

    products, product = _load_product(id)
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    product["description"] = description[:500]
    app.save_json(app.PRODUCTS_FILE, products)
    await interaction.response.send_message(
        f"✅ **{product['name']}** の説明を変更しました。\n"
        "設置済みパネルの文章は自動更新されないため、必要なら `/shopadmin panel` を再実行してください。",
        ephemeral=True,
    )


async def _set_sale(interaction: discord.Interaction, id: str, enabled: bool):
    if not await app.require_admin(interaction):
        return

    products, product = _load_product(id)
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    product["enabled"] = bool(enabled)
    app.save_json(app.PRODUCTS_FILE, products)
    await interaction.response.send_message(
        f"{'✅' if enabled else '⛔'} **{product['name']}** を"
        f"{'販売開始' if enabled else '販売停止'}にしました。",
        ephemeral=True,
    )


@app.admin_group.command(name="sale_on", description="商品の販売を開始")
@app_commands.describe(id="商品ID")
async def sale_on(interaction: discord.Interaction, id: str):
    await _set_sale(interaction, id, True)


@app.admin_group.command(name="sale_off", description="商品の販売を一時停止")
@app_commands.describe(id="商品ID")
async def sale_off(interaction: discord.Interaction, id: str):
    await _set_sale(interaction, id, False)


@app.admin_group.command(name="panel_all", description="販売中の商品パネルを一括設置")
@app_commands.describe(limit="最大設置数（1〜25）")
async def panel_all(interaction: discord.Interaction, limit: int = 20):
    if not await app.require_admin(interaction):
        return
    if limit < 1 or limit > 25:
        await interaction.response.send_message(
            "limit は1〜25で指定してください。",
            ephemeral=True,
        )
        return

    products = [
        p for p in app.load_json(app.PRODUCTS_FILE)
        if p.get("enabled", True)
    ][:limit]

    if not products:
        await interaction.response.send_message(
            "販売中の商品がありません。",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)

    for product in products:
        embed = discord.Embed(
            title=f"🛒 {product['name']}",
            description=product.get("description") or "説明なし",
        )
        embed.add_field(name="価格", value=app.yen(product["price"]), inline=True)
        embed.add_field(name="在庫", value=_stock_text(product), inline=True)
        embed.set_footer(text=f"商品ID: {product['id']}")
        await interaction.followup.send(
            embed=embed,
            view=base.ProductView(product["id"]),
        )


@app.admin_group.command(name="stock_info", description="商品の在庫状態を確認")
@app_commands.describe(id="商品ID")
async def stock_info(interaction: discord.Interaction, id: str):
    if not await app.require_admin(interaction):
        return

    product = app.get_product(id.strip())
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    file_name = "未登録"
    if product.get("stock"):
        file_name = product["stock"][0].get("filename", "登録済み")

    await interaction.response.send_message(
        f"📦 **{product['name']}**\n"
        f"在庫: **{_stock_text(product)}**\n"
        f"ファイル: `{file_name}`\n"
        f"状態: **{_product_status(product)}**",
        ephemeral=True,
    )


@app.admin_group.command(name="stock_plus", description="在庫数を追加")
@app_commands.describe(id="商品ID", amount="追加する個数")
async def stock_plus(interaction: discord.Interaction, id: str, amount: int = 1):
    if not await app.require_admin(interaction):
        return
    if amount < 1 or amount > 100000:
        await interaction.response.send_message(
            "amount は1〜100000で指定してください。",
            ephemeral=True,
        )
        return

    products, product = _load_product(id)
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    current = int(product.get("stock_limit", len(product.get("stock", []))))
    if current == -1:
        await interaction.response.send_message(
            "この商品は無限在庫です。在庫追加は不要です。",
            ephemeral=True,
        )
        return

    product["stock_limit"] = max(0, current) + amount
    app.save_json(app.PRODUCTS_FILE, products)
    await interaction.response.send_message(
        f"✅ **{product['name']}** の在庫を **+{amount}** しました。\n"
        f"現在庫: **{product['stock_limit']}**",
        ephemeral=True,
    )


@app.admin_group.command(name="order_info", description="注文IDから詳細を確認")
@app_commands.describe(id="注文ID")
async def order_info(interaction: discord.Interaction, id: str):
    if not await app.require_admin(interaction):
        return

    order = next(
        (o for o in app.load_json(app.ORDERS_FILE) if o.get("id") == id.strip()),
        None,
    )
    if not order:
        await interaction.response.send_message("注文IDが見つかりません。", ephemeral=True)
        return

    embed = discord.Embed(title=f"注文 `{order['id']}`")
    embed.add_field(name="状態", value=order.get("status", "不明"), inline=True)
    embed.add_field(name="商品", value=order.get("product_name", "不明"), inline=True)
    embed.add_field(name="価格", value=app.yen(order.get("price", 0)), inline=True)
    embed.add_field(
        name="購入者",
        value=f"<@{order.get('buyer_id', '0')}>",
        inline=True,
    )
    embed.add_field(
        name="作成日時",
        value=order.get("created_at", "不明")[:25],
        inline=False,
    )
    if order.get("delivered_at"):
        embed.add_field(
            name="納品日時",
            value=order["delivered_at"][:25],
            inline=False,
        )
    if order.get("delivery_error"):
        embed.add_field(
            name="納品エラー",
            value=str(order["delivery_error"])[:1000],
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app.admin_group.command(name="buyer_orders", description="ユーザーの注文履歴を確認")
@app_commands.describe(user="確認するユーザー")
async def buyer_orders(
    interaction: discord.Interaction,
    user: discord.User,
):
    if not await app.require_admin(interaction):
        return

    orders = [
        o for o in app.load_json(app.ORDERS_FILE)
        if str(o.get("buyer_id")) == str(user.id)
    ][-20:][::-1]

    if not orders:
        await interaction.response.send_message(
            f"{user.mention} の注文はありません。",
            ephemeral=True,
        )
        return

    lines = [
        f"`{o.get('id')}` `{o.get('status')}` "
        f"{o.get('product_name')} / {app.yen(o.get('price', 0))}"
        for o in orders
    ]
    embed = discord.Embed(
        title=f"{user} の注文履歴",
        description="\n".join(lines)[:3900],
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app.admin_group.command(name="retry_delivery", description="納品失敗した注文を再納品")
@app_commands.describe(id="注文ID")
async def retry_delivery(interaction: discord.Interaction, id: str):
    if not await app.require_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    orders = app.load_json(app.ORDERS_FILE)
    order = next((o for o in orders if o.get("id") == id.strip()), None)

    if not order:
        await interaction.followup.send("注文IDが見つかりません。", ephemeral=True)
        return
    if order.get("status") != "delivery_failed":
        await interaction.followup.send(
            f"この注文は再納品対象ではありません。（状態: `{order.get('status')}`）",
            ephemeral=True,
        )
        return

    reserved_again = None
    if int(order.get("price", 0)) == 0:
        reserved_again = app.reserve_stock(order["product_id"])
        if not reserved_again:
            await interaction.followup.send(
                "再納品用の在庫がありません。",
                ephemeral=True,
            )
            return
        order["reserved_item"] = reserved_again

    try:
        await app.send_product_to_buyer(order)
    except Exception as exc:
        if reserved_again is not None:
            app.restore_stock(order["product_id"], reserved_again)
        order["delivery_error"] = str(exc)
        app.save_json(app.ORDERS_FILE, orders)
        await interaction.followup.send(
            f"❌ 再納品にも失敗しました: `{str(exc)[:500]}`",
            ephemeral=True,
        )
        return

    order["status"] = "delivered"
    order["delivered_at"] = discord.utils.utcnow().isoformat()
    order.pop("delivery_error", None)
    app.save_json(app.ORDERS_FILE, orders)

    await interaction.followup.send(
        f"✅ 注文 `{order['id']}` を再納品しました。",
        ephemeral=True,
    )


@app.admin_group.command(name="shop_stats", description="ショップの統計を表示")
async def shop_stats(interaction: discord.Interaction):
    if not await app.require_admin(interaction):
        return

    products = app.load_json(app.PRODUCTS_FILE)
    orders = app.load_json(app.ORDERS_FILE)

    active = sum(1 for p in products if p.get("enabled", True))
    infinite = sum(
        1 for p in products
        if int(p.get("stock_limit", 0)) == -1
    )
    sold_out = sum(
        1 for p in products
        if p.get("enabled", True) and not base.has_available_stock(p)
    )
    delivered = [o for o in orders if o.get("status") == "delivered"]
    failures = sum(1 for o in orders if o.get("status") == "delivery_failed")
    delivered_total = sum(int(o.get("price", 0)) for o in delivered)

    embed = discord.Embed(title="ショップ統計")
    embed.add_field(name="商品数", value=str(len(products)), inline=True)
    embed.add_field(name="販売中", value=str(active), inline=True)
    embed.add_field(name="売り切れ", value=str(sold_out), inline=True)
    embed.add_field(name="無限在庫", value=str(infinite), inline=True)
    embed.add_field(name="注文数", value=str(len(orders)), inline=True)
    embed.add_field(name="納品済み", value=str(len(delivered)), inline=True)
    embed.add_field(name="納品失敗", value=str(failures), inline=True)
    embed.add_field(
        name="納品価格合計",
        value=app.yen(delivered_total),
        inline=True,
    )
    embed.set_footer(
        text="納品価格合計はPayPayの実受取額を保証するものではありません。"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app.admin_group.command(name="bot_status", description="Botの稼働状態を確認")
async def bot_status(interaction: discord.Interaction):
    if not await app.require_admin(interaction):
        return

    uptime = max(0, int(time.monotonic() - base.PROCESS_STARTED_AT))
    hours, rem = divmod(uptime, 3600)
    minutes, seconds = divmod(rem, 60)

    embed = discord.Embed(title="Botステータス")
    embed.add_field(
        name="Discord",
        value="接続中" if app.bot.is_ready() else "再接続中",
        inline=True,
    )
    embed.add_field(
        name="Ping",
        value=f"{round(app.bot.latency * 1000)} ms",
        inline=True,
    )
    embed.add_field(
        name="稼働時間",
        value=f"{hours}時間 {minutes}分 {seconds}秒",
        inline=True,
    )
    embed.add_field(
        name="参加サーバー",
        value=str(len(app.bot.guilds)),
        inline=True,
    )
    embed.add_field(
        name="商品数",
        value=str(len(app.load_json(app.PRODUCTS_FILE))),
        inline=True,
    )
    embed.add_field(
        name="注文数",
        value=str(len(app.load_json(app.ORDERS_FILE))),
        inline=True,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app.admin_group.command(name="backup", description="商品・注文データをバックアップ")
async def backup(interaction: discord.Interaction):
    if not await app.require_admin(interaction):
        return

    products = json.dumps(
        app.load_json(app.PRODUCTS_FILE),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    orders = json.dumps(
        app.load_json(app.ORDERS_FILE),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")

    files = [
        discord.File(io.BytesIO(products), filename="products-backup.json"),
        discord.File(io.BytesIO(orders), filename="orders-backup.json"),
    ]
    await interaction.response.send_message(
        "✅ バックアップを作成しました。",
        files=files,
        ephemeral=True,
    )


@app.admin_group.command(name="help", description="管理コマンド一覧を表示")
async def help_cmd(interaction: discord.Interaction):
    if not await app.require_admin(interaction):
        return

    text = (
        "**商品**\n"
        "`product_add` `product_list` `product_info` `product_name` "
        "`price_set` `description_set` `product_delete`\n\n"
        "**販売**\n"
        "`sale_on` `sale_off` `panel` `panel_all`\n\n"
        "**在庫**\n"
        "`stock_add` `stock_set` `stock_plus` `stock_info`\n\n"
        "**注文**\n"
        "`orders` `order_info` `buyer_orders` `retry_delivery`\n\n"
        "**運用**\n"
        "`shop_stats` `bot_status` `backup` `test_dm`"
    )
    embed = discord.Embed(
        title="/shopadmin コマンド一覧",
        description=text,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app.admin_group.command(name="test_dm", description="管理者DMへの送信テスト")
async def test_dm(interaction: discord.Interaction):
    if not await app.require_admin(interaction):
        return

    try:
        await interaction.user.send(
            "✅ 自販機BotのDM送信テストです。DMは正常に受信できます。"
        )
    except Exception as exc:
        await interaction.response.send_message(
            f"❌ DM送信に失敗しました: `{str(exc)[:500]}`",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "✅ あなたのDMへテストメッセージを送りました。",
        ephemeral=True,
    )
