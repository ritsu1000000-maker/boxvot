import "dotenv/config";
import express from "express";
import Stripe from "stripe";
import {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  Client,
  EmbedBuilder,
  GatewayIntentBits,
  MessageFlags,
  PermissionFlagsBits,
  REST,
  Routes,
  SlashCommandBuilder,
} from "discord.js";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { createWriteStream } from "node:fs";
import { pipeline } from "node:stream/promises";

const required = [
  "DISCORD_TOKEN",
  "CLIENT_ID",
  "STRIPE_SECRET_KEY",
  "STRIPE_WEBHOOK_SECRET",
  "PUBLIC_BASE_URL",
];

for (const key of required) {
  if (!process.env[key]) {
    console.error(`[設定エラー] ${key} が .env にありません。`);
    process.exit(1);
  }
}

const PORT = Number(process.env.PORT || 3000);
const DATA_DIR = path.resolve(process.env.DATA_DIR || "data");
const PRODUCTS_FILE = path.join(DATA_DIR, "products.json");
const ORDERS_FILE = path.join(DATA_DIR, "orders.json");
const UPLOADS_DIR = path.join(DATA_DIR, "uploads");

fs.mkdirSync(DATA_DIR, { recursive: true });
fs.mkdirSync(UPLOADS_DIR, { recursive: true });
if (!fs.existsSync(PRODUCTS_FILE)) fs.writeFileSync(PRODUCTS_FILE, "[]\n", "utf8");
if (!fs.existsSync(ORDERS_FILE)) fs.writeFileSync(ORDERS_FILE, "[]\n", "utf8");

function readJson(file, fallback = []) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJson(file, data) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), "utf8");
  fs.renameSync(tmp, file);
}

function getProducts() {
  return readJson(PRODUCTS_FILE, []);
}

function saveProducts(products) {
  writeJson(PRODUCTS_FILE, products);
}

function getOrders() {
  return readJson(ORDERS_FILE, []);
}

function saveOrders(orders) {
  writeJson(ORDERS_FILE, orders);
}

function makeProductId() {
  return crypto.randomBytes(3).toString("hex");
}

function safeFileName(name = "file.bin") {
  const base = path.basename(name).replace(/[^a-zA-Z0-9._()\-\u3040-\u30ff\u3400-\u9fff]/g, "_");
  return base.slice(0, 120) || "file.bin";
}

async function saveDiscordAttachment(attachment) {
  const fileName = `${Date.now()}_${crypto.randomBytes(5).toString("hex")}_${safeFileName(attachment.name)}`;
  const absolutePath = path.join(UPLOADS_DIR, fileName);

  const response = await fetch(attachment.url);
  if (!response.ok || !response.body) {
    throw new Error(`attachment download failed: ${response.status}`);
  }

  await pipeline(response.body, createWriteStream(absolutePath));

  return {
    type: "file",
    name: attachment.name || fileName,
    path: path.relative(process.cwd(), absolutePath),
    size: attachment.size ?? null,
    contentType: attachment.contentType ?? null,
  };
}

function normalizeStockItem(item) {
  if (typeof item === "string") return { type: "text", value: item };
  if (item && typeof item === "object") return item;
  return { type: "text", value: String(item ?? "") };
}

function stockTypeLabel(item) {
  const normalized = normalizeStockItem(item);
  return normalized.type === "file" ? `ファイル: ${normalized.name || "添付ファイル"}` : "テキスト";
}

async function sendOrderItem(user, order) {
  const item = normalizeStockItem(order.reservedItem);

  if (item.type === "file") {
    const filePath = path.resolve(item.path);
    if (!fs.existsSync(filePath)) {
      throw new Error(`商品ファイルが見つかりません: ${item.path}`);
    }

    await user.send({
      content:
        `✅ **購入ありがとうございます**\n` +
        `商品: **${order.productName}**\n\n` +
        `商品ファイルを添付しました。`,
      files: [{ attachment: filePath, name: item.name || path.basename(filePath) }],
    });
    return;
  }

  await user.send(
    `✅ **購入ありがとうございます**\n` +
    `商品: **${order.productName}**\n\n` +
    `**商品データ**\n\`\`\`\n${item.value}\n\`\`\``
  );
}

function yen(value) {
  return new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    maximumFractionDigits: 0,
  }).format(value);
}

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);

const client = new Client({
  intents: [GatewayIntentBits.Guilds],
});

const commands = [
  new SlashCommandBuilder()
    .setName("shop")
    .setDescription("販売中の商品一覧を表示します"),

  new SlashCommandBuilder()
    .setName("buy")
    .setDescription("商品を購入します")
    .addStringOption((o) =>
      o.setName("id").setDescription("商品ID").setRequired(true)
    ),

  new SlashCommandBuilder()
    .setName("product-add")
    .setDescription("商品を追加します")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addStringOption((o) =>
      o.setName("name").setDescription("商品名").setRequired(true).setMaxLength(80)
    )
    .addIntegerOption((o) =>
      o.setName("price").setDescription("価格（円）").setRequired(true).setMinValue(50)
    )
    .addStringOption((o) =>
      o.setName("description").setDescription("商品説明").setRequired(true).setMaxLength(500)
    ),

  new SlashCommandBuilder()
    .setName("stock-add")
    .setDescription("商品在庫を追加します（テキストまたはファイル）")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addStringOption((o) =>
      o.setName("id").setDescription("商品ID").setRequired(true)
    )
    .addStringOption((o) =>
      o.setName("items")
        .setDescription("テキスト在庫。複数は改行区切り")
        .setRequired(false)
        .setMaxLength(4000)
    )
    .addAttachmentOption((o) =>
      o.setName("file")
        .setDescription("販売するファイルをアップロード")
        .setRequired(false)
    ),

  new SlashCommandBuilder()
    .setName("product-delete")
    .setDescription("商品を削除します")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addStringOption((o) =>
      o.setName("id").setDescription("商品ID").setRequired(true)
    ),

  new SlashCommandBuilder()
    .setName("orders")
    .setDescription("最近の注文を表示します")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),
].map((c) => c.toJSON());

async function registerCommands() {
  const rest = new REST({ version: "10" }).setToken(process.env.DISCORD_TOKEN);

  if (process.env.GUILD_ID) {
    await rest.put(
      Routes.applicationGuildCommands(process.env.CLIENT_ID, process.env.GUILD_ID),
      { body: commands }
    );
    console.log(`Slash Commands: guild ${process.env.GUILD_ID} に登録しました`);
  } else {
    await rest.put(
      Routes.applicationCommands(process.env.CLIENT_ID),
      { body: commands }
    );
    console.log("Slash Commands: global に登録しました");
  }
}

async function handleShop(interaction) {
  const products = getProducts();

  if (!products.length) {
    return interaction.reply({
      content: "現在、販売中の商品はありません。",
      flags: MessageFlags.Ephemeral,
    });
  }

  const lines = products.map((p) => {
    const stockItems = Array.isArray(p.stock) ? p.stock : [];
    const stock = stockItems.length;
    const fileCount = stockItems.filter((x) => normalizeStockItem(x).type === "file").length;
    const textCount = stock - fileCount;
    const kind = fileCount && textCount ? ` / ファイル ${fileCount}・テキスト ${textCount}` : fileCount ? ` / ファイル ${fileCount}` : "";
    return `**${p.name}**\nID: \`${p.id}\` / ${yen(p.price)} / 在庫: ${stock}${kind}\n${p.description}`;
  });

  const embed = new EmbedBuilder()
    .setTitle("🛒 自販機")
    .setDescription(lines.join("\n\n").slice(0, 4000))
    .setFooter({ text: "/buy id:<商品ID> で購入" });

  return interaction.reply({ embeds: [embed] });
}

async function handleBuy(interaction) {
  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  const id = interaction.options.getString("id", true).trim();
  const products = getProducts();
  const product = products.find((p) => p.id === id);

  if (!product) {
    return interaction.editReply("その商品IDは見つかりません。");
  }

  if (!Array.isArray(product.stock) || product.stock.length === 0) {
    return interaction.editReply("この商品は現在売り切れです。");
  }

  // 決済待ちの間に他の人へ同じ在庫を売らないため、1個を先に予約する。
  const reservedItem = product.stock.shift();
  saveProducts(products);

  let session;
  try {
    session = await stripe.checkout.sessions.create({
      mode: "payment",
      line_items: [
        {
          price_data: {
            currency: "jpy",
            product_data: {
              name: product.name,
              description: product.description.slice(0, 500),
            },
            unit_amount: product.price,
          },
          quantity: 1,
        },
      ],
      success_url: `${process.env.PUBLIC_BASE_URL}/success`,
      cancel_url: `${process.env.PUBLIC_BASE_URL}/cancel`,
      metadata: {
        discord_user_id: interaction.user.id,
        discord_guild_id: interaction.guildId || "",
        product_id: product.id,
      },
    });
  } catch (err) {
    // Checkout Session作成に失敗した場合は在庫を戻す。
    const current = getProducts();
    const p = current.find((x) => x.id === product.id);
    if (p) {
      p.stock.unshift(reservedItem);
      saveProducts(current);
    }
    console.error(err);
    return interaction.editReply("決済ページの作成に失敗しました。設定を確認してください。");
  }

  const orders = getOrders();
  orders.push({
    stripeSessionId: session.id,
    userId: interaction.user.id,
    guildId: interaction.guildId || null,
    productId: product.id,
    productName: product.name,
    amount: product.price,
    status: "pending",
    reservedItem,
    createdAt: new Date().toISOString(),
    deliveredAt: null,
  });
  saveOrders(orders);

  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setLabel(`${yen(product.price)} を支払う`)
      .setStyle(ButtonStyle.Link)
      .setURL(session.url)
  );

  return interaction.editReply({
    content:
      `**${product.name}** を購入します。\n` +
      `支払いはStripeの決済ページで行います。\n` +
      `支払い完了後、商品はDiscordのDMに自動送信されます。`,
    components: [row],
  });
}

async function handleProductAdd(interaction) {
  const name = interaction.options.getString("name", true).trim();
  const price = interaction.options.getInteger("price", true);
  const description = interaction.options.getString("description", true).trim();

  const products = getProducts();
  const product = {
    id: makeProductId(),
    name,
    price,
    description,
    stock: [],
    createdAt: new Date().toISOString(),
  };
  products.push(product);
  saveProducts(products);

  return interaction.reply({
    content:
      `商品を追加しました。\n` +
      `商品ID: \`${product.id}\`\n` +
      `商品名: **${product.name}**\n` +
      `価格: **${yen(product.price)}**\n` +
      `次に \`/stock-add\` でテキスト在庫またはファイルを登録してください。`,
    flags: MessageFlags.Ephemeral,
  });
}

async function handleStockAdd(interaction) {
  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  const id = interaction.options.getString("id", true).trim();
  const raw = interaction.options.getString("items", false);
  const attachment = interaction.options.getAttachment("file", false);

  if (!raw && !attachment) {
    return interaction.editReply("`items` か `file` のどちらかを指定してください。");
  }

  const products = getProducts();
  const product = products.find((p) => p.id === id);

  if (!product) {
    return interaction.editReply("その商品IDは見つかりません。");
  }

  product.stock ??= [];
  let addedText = 0;
  let addedFile = 0;

  if (raw) {
    const items = raw
      .split(/\r?\n/)
      .map((x) => x.trim())
      .filter(Boolean);

    for (const item of items) {
      product.stock.push(item);
      addedText += 1;
    }
  }

  if (attachment) {
    try {
      const storedFile = await saveDiscordAttachment(attachment);
      product.stock.push(storedFile);
      addedFile += 1;
    } catch (err) {
      console.error("ファイル保存エラー:", err);
      return interaction.editReply("ファイルの保存に失敗しました。もう一度アップロードしてください。");
    }
  }

  saveProducts(products);

  const added = [
    addedText ? `テキスト ${addedText}個` : null,
    addedFile ? `ファイル ${addedFile}個` : null,
  ].filter(Boolean).join(" / ");

  return interaction.editReply(
    `**${product.name}** に ${added} を追加しました。現在庫: ${product.stock.length}`
  );
}


async function handleProductDelete(interaction) {
  const id = interaction.options.getString("id", true).trim();
  const products = getProducts();
  const index = products.findIndex((p) => p.id === id);

  if (index === -1) {
    return interaction.reply({
      content: "その商品IDは見つかりません。",
      flags: MessageFlags.Ephemeral,
    });
  }

  const [removed] = products.splice(index, 1);
  saveProducts(products);

  for (const item of removed.stock || []) {
    const normalized = normalizeStockItem(item);
    if (normalized.type === "file" && normalized.path) {
      const filePath = path.resolve(normalized.path);
      fs.rmSync(filePath, { force: true });
    }
  }

  return interaction.reply({
    content: `**${removed.name}** を削除しました。`,
    flags: MessageFlags.Ephemeral,
  });
}

async function handleOrders(interaction) {
  const orders = getOrders().slice(-10).reverse();

  if (!orders.length) {
    return interaction.reply({
      content: "注文履歴はまだありません。",
      flags: MessageFlags.Ephemeral,
    });
  }

  const body = orders
    .map(
      (o) =>
        `\`${o.status}\` ${o.productName} / ${yen(o.amount)} / ${stockTypeLabel(o.reservedItem)} / <@${o.userId}> / ${o.stripeSessionId}`
    )
    .join("\n")
    .slice(0, 3900);

  const embed = new EmbedBuilder()
    .setTitle("最近の注文")
    .setDescription(body);

  return interaction.reply({
    embeds: [embed],
    flags: MessageFlags.Ephemeral,
  });
}

client.on("interactionCreate", async (interaction) => {
  if (!interaction.isChatInputCommand()) return;

  try {
    if (interaction.commandName === "shop") return await handleShop(interaction);
    if (interaction.commandName === "buy") return await handleBuy(interaction);
    if (interaction.commandName === "product-add") return await handleProductAdd(interaction);
    if (interaction.commandName === "stock-add") return await handleStockAdd(interaction);
    if (interaction.commandName === "product-delete") return await handleProductDelete(interaction);
    if (interaction.commandName === "orders") return await handleOrders(interaction);
  } catch (err) {
    console.error("interaction error:", err);
    const message = "処理中にエラーが発生しました。コンソールを確認してください。";
    if (interaction.deferred || interaction.replied) {
      await interaction.editReply({ content: message, components: [] }).catch(() => {});
    } else {
      await interaction.reply({ content: message, flags: MessageFlags.Ephemeral }).catch(() => {});
    }
  }
});

// --------------------
// Web server / Stripe webhook
// --------------------
const app = express();

app.post(
  "/stripe/webhook",
  express.raw({ type: "application/json" }),
  async (req, res) => {
    let event;

    try {
      const signature = req.headers["stripe-signature"];
      event = stripe.webhooks.constructEvent(
        req.body,
        signature,
        process.env.STRIPE_WEBHOOK_SECRET
      );
    } catch (err) {
      console.error("Webhook署名検証エラー:", err.message);
      return res.status(400).send("Invalid webhook signature");
    }

    try {
      if (event.type === "checkout.session.completed") {
        const session = event.data.object;
        const orders = getOrders();
        const order = orders.find((o) => o.stripeSessionId === session.id);

        if (order && order.status !== "delivered" && session.payment_status === "paid") {
          const user = await client.users.fetch(order.userId);

          try {
            await sendOrderItem(user, order);

            order.status = "delivered";
            order.deliveredAt = new Date().toISOString();
          } catch (dmErr) {
            // DMが閉じている場合も商品は予約済みのまま保持し、管理者が再送できるようにする。
            order.status = "paid_dm_failed";
            order.dmError = String(dmErr?.message || dmErr);
          }

          saveOrders(orders);
        }
      }

      if (event.type === "checkout.session.expired") {
        const session = event.data.object;
        const orders = getOrders();
        const order = orders.find((o) => o.stripeSessionId === session.id);

        if (order && order.status === "pending") {
          const products = getProducts();
          const product = products.find((p) => p.id === order.productId);

          if (product && order.reservedItem) {
            product.stock ??= [];
            product.stock.unshift(order.reservedItem);
            saveProducts(products);
          }

          order.status = "expired";
          saveOrders(orders);
        }
      }

      return res.json({ received: true });
    } catch (err) {
      console.error("Webhook処理エラー:", err);
      return res.status(500).json({ error: "webhook handler failed" });
    }
  }
);

app.get("/", (_req, res) => {
  res.type("html").send(`
    <!doctype html>
    <meta charset="utf-8">
    <title>Discord Vending Bot</title>
    <style>
      body{font-family:system-ui;background:#111827;color:#fff;display:grid;place-items:center;min-height:100vh;margin:0}
      main{max-width:700px;padding:40px}
      code{background:#1f2937;padding:4px 8px;border-radius:8px}
    </style>
    <main>
      <h1>Discord Vending Bot</h1>
      <p>Bot / Webhook server is running.</p>
      <p>Webhook: <code>/stripe/webhook</code></p>
    </main>
  `);
});

app.get("/success", (_req, res) => {
  res.type("html").send(`
    <!doctype html><meta charset="utf-8">
    <title>決済完了</title>
    <style>body{font-family:system-ui;text-align:center;padding:70px;background:#111827;color:white}</style>
    <h1>決済が完了しました</h1>
    <p>DiscordのDMを確認してください。</p>
  `);
});

app.get("/cancel", (_req, res) => {
  res.type("html").send(`
    <!doctype html><meta charset="utf-8">
    <title>決済キャンセル</title>
    <style>body{font-family:system-ui;text-align:center;padding:70px;background:#111827;color:white}</style>
    <h1>決済をキャンセルしました</h1>
    <p>購入は完了していません。</p>
  `);
});

app.get("/health", (_req, res) => {
  res.json({ ok: true, bot: client.user?.tag || null });
});

app.listen(PORT, () => {
  console.log(`Web server: http://localhost:${PORT}`);
  console.log(`Webhook path: /stripe/webhook`);
});

client.once("ready", () => {
  console.log(`Discord: ${client.user.tag} としてログインしました`);
});

await registerCommands();
await client.login(process.env.DISCORD_TOKEN);
