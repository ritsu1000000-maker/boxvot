import os
import json
import uuid
import asyncio
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask, jsonify
from PayPaython import PayPay

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PRODUCTS_FILE = DATA_DIR / "products.json"
ORDERS_FILE = DATA_DIR / "orders.json"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

for f in (PRODUCTS_FILE, ORDERS_FILE):
    if not f.exists():
        f.write_text("[]", encoding="utf-8")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = os.getenv("GUILD_ID", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0") or "0")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID", "0") or "0")
PORT = int(os.getenv("PORT", "10000"))

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN が設定されていません。")
if not ADMIN_USER_ID:
    raise RuntimeError("ADMIN_USER_ID が設定されていません。")

# PayPaythonのlink_checkだけを使う。PayPayアカウントへのログインや自動受取はしない。
PAYPAY = PayPay()

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def yen(value):
    return f"¥{int(value):,}"

def is_admin(user_id: int):
    return user_id == ADMIN_USER_ID

def validate_paypay_url(value: str):
    value = value.strip()
    try:
        u = urlparse(value)
    except Exception:
        return None

    if u.scheme != "https":
        return None
    if u.hostname != "pay.paypay.ne.jp":
        return None

    token = u.path.strip("/")
    if not token or "/" in token or len(token) > 100:
        return None
    if not all(ch.isalnum() or ch in "-_" for ch in token):
        return None

    return f"https://pay.paypay.ne.jp/{token}"

def _to_dict(obj):
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "_asdict"):
        try:
            return obj._asdict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return dict(obj.__dict__)
        except Exception:
            pass
    return {}

def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.replace(",", "").replace("¥", "").replace("円", "").strip()
        try:
            return int(float(s))
        except Exception:
            return None
    return None

def extract_link_info(info):
    """
    PayPaythonのバージョン差を吸収する。
    amount / money + money_light / status / has_password を可能な範囲で取得。
    """
    data = _to_dict(info)

    amount = None
    for key in ("amount", "total_amount", "totalAmount", "price"):
        if key in data:
            amount = _number(data.get(key))
            if amount is not None:
                break

    if amount is None:
        for key in ("amount", "total_amount", "totalAmount"):
            if hasattr(info, key):
                amount = _number(getattr(info, key))
                if amount is not None:
                    break

    money = None
    money_light = None
    for key in ("money",):
        if key in data:
            money = _number(data.get(key))
        elif hasattr(info, key):
            money = _number(getattr(info, key))
    for key in ("money_light", "moneyLight"):
        if key in data:
            money_light = _number(data.get(key))
        elif hasattr(info, key):
            money_light = _number(getattr(info, key))

    if amount is None and (money is not None or money_light is not None):
        amount = (money or 0) + (money_light or 0)

    # ライブラリによってはオブジェクト自体が数値的に表示される場合がある。
    if amount is None:
        amount = _number(info)

    status = data.get("status")
    if status is None and hasattr(info, "status"):
        status = getattr(info, "status")
    status = str(status).upper() if status is not None else None

    has_password = data.get("has_password", data.get("hasPassword"))
    if has_password is None and hasattr(info, "has_password"):
        has_password = getattr(info, "has_password")
    if has_password is not None:
        has_password = bool(has_password)

    return {
        "amount": amount,
        "status": status,
        "has_password": has_password,
        "raw": str(info)[:1000],
    }

def check_paypay_link_sync(url: str):
    safe_url = validate_paypay_url(url)
    if not safe_url:
        raise ValueError("PayPayの受け取りリンクではありません。")

    info = PAYPAY.link_check(safe_url)
    parsed = extract_link_info(info)

    if parsed["amount"] is None:
        raise RuntimeError("リンクの金額を取得できませんでした。")

    return parsed

def get_product(product_id):
    return next((p for p in load_json(PRODUCTS_FILE) if p.get("id") == product_id), None)

def reserve_stock(product_id):
    products = load_json(PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == product_id), None)
    if not product or not product.get("stock"):
        return None
    item = product["stock"].pop(0)
    save_json(PRODUCTS_FILE, products)
    return item

def restore_stock(product_id, item):
    products = load_json(PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == product_id), None)
    if product:
        product.setdefault("stock", []).insert(0, item)
        save_json(PRODUCTS_FILE, products)

def new_order_id():
    return uuid.uuid4().hex[:10]

async def admin_target():
    if ADMIN_CHANNEL_ID:
        channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if channel is None:
            try:
                channel = await bot.fetch_channel(ADMIN_CHANNEL_ID)
            except Exception:
                channel = None
        if channel:
            return channel

    user = bot.get_user(ADMIN_USER_ID)
    if user is None:
        user = await bot.fetch_user(ADMIN_USER_ID)
    return user

async def send_product_to_buyer(order):
    user = bot.get_user(int(order["buyer_id"]))
    if user is None:
        user = await bot.fetch_user(int(order["buyer_id"]))

    item = order["reserved_item"]
    path = BASE_DIR / item["path"]
    if not path.exists():
        raise FileNotFoundError(f"商品ファイルが見つかりません: {path}")

    await user.send(
        f"✅ **購入ありがとうございます**\n"
        f"商品: **{order['product_name']}**\n"
        f"価格: **{yen(order['price'])}**",
        file=discord.File(path, filename=item.get("filename") or path.name)
    )

class BuyModal(discord.ui.Modal, title="PayPayで購入"):
    paypay_link = discord.ui.TextInput(
        label="PayPay受け取りリンク",
        placeholder="https://pay.paypay.ne.jp/...",
        required=True,
        max_length=200,
    )
    passcode = discord.ui.TextInput(
        label="パスコード（設定した場合のみ）",
        placeholder="未設定なら空欄",
        required=False,
        max_length=20,
    )

    def __init__(self, product_id: str):
        super().__init__()
        self.product_id = product_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        product = get_product(self.product_id)
        if not product:
            await interaction.followup.send("商品が見つかりません。", ephemeral=True)
            return
        if not product.get("stock"):
            await interaction.followup.send("この商品は売り切れです。", ephemeral=True)
            return

        safe_url = validate_paypay_url(str(self.paypay_link.value))
        if not safe_url:
            await interaction.followup.send(
                "❌ PayPayの受け取りリンクを入力してください。\n"
                "`https://pay.paypay.ne.jp/...` の形式だけ受け付けます。",
                ephemeral=True
            )
            return

        try:
            link_info = await asyncio.to_thread(check_paypay_link_sync, safe_url)
        except Exception as e:
            print("PayPay link check error:", repr(e))
            await interaction.followup.send(
                "❌ PayPayリンクの金額を確認できませんでした。\n"
                "リンクが有効か確認して、もう一度試してください。",
                ephemeral=True
            )
            return

        expected = int(product["price"])
        actual = int(link_info["amount"])

        if actual != expected:
            await interaction.followup.send(
                f"❌ **金額が違います。**\n"
                f"商品価格: **{yen(expected)}**\n"
                f"リンク金額: **{yen(actual)}**\n\n"
                f"{yen(expected)} の受け取りリンクを作り直してください。",
                ephemeral=True
            )
            return

        status = link_info.get("status")
        if status and status not in ("PENDING",):
            await interaction.followup.send(
                f"❌ このリンクは現在使用できません。（状態: `{status}`）\n"
                "未受け取りの新しいリンクを作成してください。",
                ephemeral=True
            )
            return

        if link_info.get("has_password") is True and not str(self.passcode.value).strip():
            await interaction.followup.send(
                "❌ このリンクにはパスコードが設定されています。\n"
                "パスコードも入力してください。",
                ephemeral=True
            )
            return

        reserved = reserve_stock(self.product_id)
        if not reserved:
            await interaction.followup.send("この商品は直前に売り切れました。", ephemeral=True)
            return

        order_id = new_order_id()
        order = {
            "id": order_id,
            "status": "amount_matched",
            "buyer_id": str(interaction.user.id),
            "buyer_name": str(interaction.user),
            "product_id": product["id"],
            "product_name": product["name"],
            "price": expected,
            "paypay_link": safe_url,
            "passcode": str(self.passcode.value).strip(),
            "paypay_amount": actual,
            "paypay_status_at_submit": status,
            "reserved_item": reserved,
            "created_at": discord.utils.utcnow().isoformat(),
        }

        orders = load_json(ORDERS_FILE)
        orders.append(order)
        save_json(ORDERS_FILE, orders)

        # 金額一致した時点で自動納品
        try:
            await send_product_to_buyer(order)
            order["status"] = "delivered"
            order["delivered_at"] = discord.utils.utcnow().isoformat()
            save_json(ORDERS_FILE, orders)
        except Exception as e:
            print("Auto delivery error:", repr(e))
            order["status"] = "delivery_failed"
            order["delivery_error"] = str(e)
            save_json(ORDERS_FILE, orders)

            await interaction.followup.send(
                "❌ 金額は一致しましたが、商品のDM送信に失敗しました。"
                "管理者に連絡してください。",
                ephemeral=True
            )
            return

        # 管理者には通知だけ送る
        try:
            target = await admin_target()
            embed = discord.Embed(
                title="✅ 自動納品しました",
                description=(
                    f"購入者: <@{interaction.user.id}>\n"
                    f"商品: **{product['name']}**\n"
                    f"商品価格: **{yen(expected)}**\n"
                    f"リンク確認金額: **{yen(actual)}** ✅\n"
                    f"注文ID: `{order_id}`\n"
                    f"PayPayリンク: {safe_url}"
                )
            )
            if order["passcode"]:
                embed.add_field(name="パスコード", value=f"`{order['passcode']}`", inline=False)
            embed.add_field(
                name="注意",
                value="この注文はPayPayリンクの金額一致だけで自動納品されています。"
                      "PayPay上で実際に受け取り完了したことまではBotは確認していません。",
                inline=False
            )
            await target.send(embed=embed)
        except Exception as e:
            print("Admin notify error:", repr(e))

        await interaction.followup.send(
            "✅ **金額が一致しました。**\n"
            "商品をDiscordのDMへ自動送信しました。",
            ephemeral=True
        )

class ProductView(discord.ui.View):
    def __init__(self, product_id: str):
        super().__init__(timeout=None)
        self.product_id = product_id

        button = discord.ui.Button(
            label="PayPayで購入する",
            style=discord.ButtonStyle.primary,
            custom_id=f"vending:buy:{product_id}"
        )
        button.callback = self.buy_callback
        self.add_item(button)

    async def buy_callback(self, interaction: discord.Interaction):
        product = get_product(self.product_id)
        if not product:
            await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
            return
        if not product.get("stock"):
            await interaction.response.send_message("この商品は現在売り切れです。", ephemeral=True)
            return
        await interaction.response.send_modal(BuyModal(self.product_id))

class OrderApprovalView(discord.ui.View):
    def __init__(self, order_id: str):
        super().__init__(timeout=None)
        self.order_id = order_id

        link = discord.ui.Button(
            label="PayPayリンクを開く",
            style=discord.ButtonStyle.link,
            url="https://pay.paypay.ne.jp/"
        )
        self.link_button = link

        accept = discord.ui.Button(
            label="受け取り完了 → 納品",
            style=discord.ButtonStyle.success,
            custom_id=f"vending:accept:{order_id}"
        )
        reject = discord.ui.Button(
            label="拒否",
            style=discord.ButtonStyle.danger,
            custom_id=f"vending:reject:{order_id}"
        )
        accept.callback = self.accept_callback
        reject.callback = self.reject_callback

        self.add_item(link)
        self.add_item(accept)
        self.add_item(reject)

    async def interaction_check(self, interaction: discord.Interaction):
        if not is_admin(interaction.user.id):
            await interaction.response.send_message("この操作は管理者専用です。", ephemeral=True)
            return False
        return True

    async def _get_order(self):
        orders = load_json(ORDERS_FILE)
        order = next((o for o in orders if o.get("id") == self.order_id), None)
        return orders, order

    async def accept_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        orders, order = await self._get_order()

        if not order:
            await interaction.followup.send("注文が見つかりません。", ephemeral=True)
            return
        if order.get("status") != "waiting_admin":
            await interaction.followup.send(
                f"この注文はすでに処理済みです。（{order.get('status')}）",
                ephemeral=True
            )
            return

        try:
            await send_product_to_buyer(order)
        except Exception as e:
            print("Delivery error:", repr(e))
            order["status"] = "delivery_failed"
            order["delivery_error"] = str(e)
            save_json(ORDERS_FILE, orders)
            await interaction.followup.send(
                "❌ 商品のDM送信に失敗しました。注文履歴を確認してください。",
                ephemeral=True
            )
            return

        order["status"] = "delivered"
        order["delivered_at"] = discord.utils.utcnow().isoformat()
        save_json(ORDERS_FILE, orders)

        await interaction.followup.send("✅ 購入者へ商品を納品しました。", ephemeral=True)

    async def reject_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        orders, order = await self._get_order()

        if not order:
            await interaction.followup.send("注文が見つかりません。", ephemeral=True)
            return
        if order.get("status") != "waiting_admin":
            await interaction.followup.send(
                f"この注文はすでに処理済みです。（{order.get('status')}）",
                ephemeral=True
            )
            return

        restore_stock(order["product_id"], order["reserved_item"])
        order["status"] = "rejected"
        order["rejected_at"] = discord.utils.utcnow().isoformat()
        save_json(ORDERS_FILE, orders)

        try:
            user = bot.get_user(int(order["buyer_id"])) or await bot.fetch_user(int(order["buyer_id"]))
            await user.send(
                f"❌ 注文 `{order['id']}` は管理者によって拒否されました。\n"
                "PayPay側で残高が移動している場合は、管理者へ直接確認してください。"
            )
        except Exception:
            pass

        await interaction.followup.send("注文を拒否し、在庫を戻しました。", ephemeral=True)

class VendingBot(commands.Bot):
    async def setup_hook(self):
        # 再起動後も既存の販売ボタンを使えるようにする
        for product in load_json(PRODUCTS_FILE):
            try:
                self.add_view(ProductView(product["id"]))
            except Exception as e:
                print("Product view restore error:", e)

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Commands synced to guild {GUILD_ID}")
        else:
            await self.tree.sync()
            print("Commands synced globally")

intents = discord.Intents.default()
bot = VendingBot(command_prefix="!", intents=intents)

admin_group = app_commands.Group(
    name="shopadmin",
    description="自販機Bot管理",
    default_permissions=discord.Permissions(manage_guild=True)
)

async def require_admin(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        if interaction.response.is_done():
            await interaction.followup.send("管理者専用です。", ephemeral=True)
        else:
            await interaction.response.send_message("管理者専用です。", ephemeral=True)
        return False
    return True

@admin_group.command(name="product_add", description="商品を追加")
@app_commands.describe(name="商品名", price="価格（円）", description="商品説明")
async def product_add(interaction: discord.Interaction, name: str, price: int, description: str):
    if not await require_admin(interaction):
        return
    if price <= 0:
        await interaction.response.send_message("価格は1円以上にしてください。", ephemeral=True)
        return

    products = load_json(PRODUCTS_FILE)
    product = {
        "id": uuid.uuid4().hex[:6],
        "name": name[:80],
        "price": int(price),
        "description": description[:500],
        "stock": [],
        "created_at": discord.utils.utcnow().isoformat()
    }
    products.append(product)
    save_json(PRODUCTS_FILE, products)
    bot.add_view(ProductView(product["id"]))

    await interaction.response.send_message(
        f"✅ 商品を追加しました。\n"
        f"ID: `{product['id']}`\n"
        f"商品: **{product['name']}**\n"
        f"価格: **{yen(product['price'])}**\n\n"
        f"次に `/shopadmin stock_add` で商品ファイルを追加してください。",
        ephemeral=True
    )

@admin_group.command(name="stock_add", description="商品ファイルを在庫に追加")
@app_commands.describe(id="商品ID", file="購入後に送る商品ファイル")
async def stock_add(interaction: discord.Interaction, id: str, file: discord.Attachment):
    if not await require_admin(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    products = load_json(PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == id.strip()), None)
    if not product:
        await interaction.followup.send("商品IDが見つかりません。", ephemeral=True)
        return

    filename = Path(file.filename).name
    saved_name = f"{uuid.uuid4().hex}_{filename}"
    saved_path = UPLOAD_DIR / saved_name

    try:
        await file.save(saved_path)
    except Exception as e:
        print("Attachment save error:", repr(e))
        await interaction.followup.send("ファイルの保存に失敗しました。", ephemeral=True)
        return

    product.setdefault("stock", []).append({
        "type": "file",
        "filename": filename,
        "path": str(saved_path.relative_to(BASE_DIR)).replace("\\", "/"),
    })
    save_json(PRODUCTS_FILE, products)

    await interaction.followup.send(
        f"✅ **{product['name']}** に在庫を1個追加しました。\n"
        f"現在庫: **{len(product['stock'])}個**",
        ephemeral=True
    )

@admin_group.command(name="panel", description="購入者向け商品パネルを設置")
@app_commands.describe(id="商品ID")
async def panel(interaction: discord.Interaction, id: str):
    if not await require_admin(interaction):
        return

    product = get_product(id.strip())
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"🛒 {product['name']}",
        description=product["description"]
    )
    embed.add_field(name="価格", value=yen(product["price"]), inline=True)
    embed.add_field(name="在庫", value=f"{len(product.get('stock', []))}個", inline=True)
    embed.set_footer(text=f"商品ID: {product['id']}")

    await interaction.response.send_message(
        embed=embed,
        view=ProductView(product["id"])
    )

@admin_group.command(name="orders", description="最近の注文を確認")
async def orders_cmd(interaction: discord.Interaction):
    if not await require_admin(interaction):
        return

    orders = load_json(ORDERS_FILE)[-15:][::-1]
    if not orders:
        await interaction.response.send_message("注文はまだありません。", ephemeral=True)
        return

    lines = []
    for o in orders:
        lines.append(
            f"`{o['status']}` `{o['id']}` "
            f"{o['product_name']} / {yen(o['price'])} / <@{o['buyer_id']}>"
        )

    embed = discord.Embed(
        title="注文履歴",
        description="\n".join(lines)[:3900]
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@admin_group.command(name="product_delete", description="商品を削除")
@app_commands.describe(id="商品ID")
async def product_delete(interaction: discord.Interaction, id: str):
    if not await require_admin(interaction):
        return

    products = load_json(PRODUCTS_FILE)
    product = next((p for p in products if p.get("id") == id.strip()), None)
    if not product:
        await interaction.response.send_message("商品IDが見つかりません。", ephemeral=True)
        return

    products = [p for p in products if p.get("id") != id.strip()]
    save_json(PRODUCTS_FILE, products)
    await interaction.response.send_message(
        f"✅ **{product['name']}** を削除しました。",
        ephemeral=True
    )

bot.tree.add_command(admin_group)

@bot.event
async def on_ready():
    print(f"Discord login: {bot.user}")

# Render用Webサーバー
web = Flask(__name__)

@web.get("/")
def home():
    return "PayPay Vending Bot is running."

@web.get("/health")
def health():
    return jsonify({"ok": True, "bot": str(bot.user) if bot.user else None})

def run_web():
    web.run(host="0.0.0.0", port=PORT, threaded=True)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    bot.run(DISCORD_TOKEN)
