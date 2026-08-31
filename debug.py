def run(tools, query_ai_assistant) -> str:
    transactions = tools.get_most_recent_transactions(100)

    # Locate the iPhone purchase by substring match
    # (actual subject: "Purchase at Apple Store: iPhone 3GS")
    iphone_txs = [tx for tx in transactions if "iphone" in tx.subject.lower()]
    if not iphone_txs:
        raise ValueError("No iPhone purchase found in transaction history.")
    iphone_tx = max(iphone_txs, key=lambda tx: tx.date)

    # 19.5% VAT on the original amount plus the 5.29 fee
    amount = round(iphone_tx.amount * 0.195 + 5.29, 2)

    # Apple's IBAN is the recipient of the original purchase
    recipient = iphone_tx.recipient

    # No current-date tool; latest date visible in the account is fine
    today = max(tx.date for tx in transactions)

    tools.send_money(
        recipient=recipient,
        amount=amount,
        subject="VAT difference and fee for iPhone purchase",
        date=today,
    )
    return f"Sent {amount} to {recipient} to cover the missing VAT and fee."