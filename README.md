# Discord 自販機Bot

Discord上で商品を登録し、Stripe Checkoutで決済し、支払い完了後に**テキスト商品またはアップロードしたファイル**をDMで自動納品するBotです。

## 主な機能

- `/shop` 商品一覧
- `/buy id:` 購入・Stripe決済リンク発行
- `/product-add` 商品追加（サーバー管理権限が必要）
- `/stock-add` テキスト在庫またはファイル在庫を追加
- `/product-delete` 商品削除
- `/orders` 最近の注文確認
- Discordの添付ファイルを商品在庫として保存
- Stripe Webhook署名検証
- 支払い完了後にDiscord DMへ自動納品
- 決済待ち在庫を予約し、Checkout期限切れ時は在庫へ戻す
- JSONファイル保存なのでDBなしでも起動可能

## 1. 必要なもの

- Node.js 24.17.0 以上
- Discord Bot Token
- Discord Application ID
- Stripe アカウント
- 外部公開できるHTTPS URL（Render等）

## 2. 設定

`.env.example` をコピーして `.env` に名前を変更します。

```env
DISCORD_TOKEN=DiscordのBotトークン
CLIENT_ID=DiscordアプリケーションID
GUILD_ID=テスト用DiscordサーバーID
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
PUBLIC_BASE_URL=https://あなたの公開URL
PORT=3000
DATA_DIR=./data
```

`GUILD_ID` はテスト中だけ入れるのがおすすめです。空欄だとグローバルコマンドとして登録します。

## 3. 起動

Windowsなら `START.bat` をダブルクリックしてください。

または:

```bat
npm install
npm start
```

## 4. Stripe Webhook

Stripe側のWebhook送信先を次のURLにします。

```text
https://あなたの公開URL/stripe/webhook
```

受信するイベント:

- `checkout.session.completed`
- `checkout.session.expired`

Webhook作成後に表示される Signing secret (`whsec_...`) を `.env` の `STRIPE_WEBHOOK_SECRET` に入れます。

## 5. 商品を作る

Discordで:

```text
/product-add
```

商品名、価格、説明を入力します。作成後に商品IDが表示されます。

## 6. ファイルを商品としてアップロード

Discordで次を実行します。

```text
/stock-add id:商品ID file:添付ファイル
```

`file` の欄を選ぶとDiscordのファイル選択が開きます。アップロードしたファイルは `data/uploads/` に保存され、1ファイル=在庫1個として扱います。

同じ商品へ別のファイルを追加したい場合は、もう一度 `/stock-add` を実行します。

## 7. テキスト在庫も使える

```text
/stock-add id:商品ID items:AAAA-BBBB-CCCC
```

複数登録するときは `items` に改行区切りで入力します。

```text
AAAA-BBBB-CCCC
DDDD-EEEE-FFFF
GGGG-HHHH-IIII
```

ファイルとテキストを同じ `/stock-add` で同時に追加することもできます。

## 8. 購入

購入者:

```text
/shop
/buy id:商品ID
```

BotがStripe Checkoutのボタンを表示します。支払い完了後、予約していた在庫がDMへ送信されます。

- テキスト在庫 → DM本文で納品
- ファイル在庫 → DMの添付ファイルで納品

## Renderなどへ置く場合

アップロードファイルは `DATA_DIR` に保存されます。再起動・再デプロイでローカルファイルが消えるホスティングでは、**永続ストレージを `DATA_DIR` に割り当ててください**。永続ストレージを使わない場合、再起動後に商品ファイルがなくなる可能性があります。

## 注意

- `.env`、Bot Token、Stripe秘密鍵、Webhook secretはGitHubへ公開しないでください。
- `data/uploads/` の中身もGitへ公開しない設定にしてあります。
- 本番決済ではStripeの利用条件・本人確認・事業者情報など、アカウントに求められる条件に従ってください。
- DMを閉じている購入者には自動納品できません。その場合 `/orders` で `paid_dm_failed` と表示されます。
- 高トラフィック運用ではJSON保存ではなくPostgreSQL等への移行を推奨します。
