# PayPayリンク式 Discord 自販機Bot

## 購入者の流れ

1. 商品パネルの **「PayPayで購入する」** を押す
2. PayPay受け取りリンクを入力
3. Botがリンクの金額を確認
4. 商品価格と違えばエラー
5. 一致したら商品を購入者へ自動DM納品
6. 管理者へ注文・自動納品済み通知を送信

購入者はスラッシュコマンドを使いません。

## 管理者コマンド

- `/shopadmin product_add`
- `/shopadmin stock_add`
- `/shopadmin panel`
- `/shopadmin orders`
- `/shopadmin product_delete`

## Render

### Build Command

```text
pip install -r requirements.txt
```

### Start Command

```text
python main.py
```

### Environment Variables

```text
DISCORD_TOKEN
GUILD_ID
ADMIN_USER_ID
ADMIN_CHANNEL_ID
```

`ADMIN_CHANNEL_ID` は省略可能です。
設定した場合、そのチャンネルへ購入通知を送ります。
空欄の場合は `ADMIN_USER_ID` のDMへ送ります。

PayPayの電話番号、パスワード、APIキーは不要です。

## 重要

このBotはPayPaythonの `link_check` を使ってリンクの公開情報から金額を確認します。
PayPayへログインしたり、Botが自動で残高を受け取ったりはしません。

PayPaython WebAPI版は非公式かつDiscontinued扱いのため、PayPay側の仕様変更で
リンク金額チェックが動かなくなる可能性があります。その場合は購入処理を停止して
「リンクの金額を確認できませんでした」と表示する設計です。

## Renderのファイル保存

`data/products.json`
`data/orders.json`
`data/uploads/`

を使用します。Renderの通常の一時ファイルシステムでは再デプロイ等で消えるため、
本番運用する場合はPersistent Disk等の永続ストレージを使用してください。


## 自動納品について

この版は、PayPayリンクから読み取れた金額が商品価格と一致した時点で自動納品します。
PayPay上で管理者が実際に残高を受け取ったことまでは確認しません。
