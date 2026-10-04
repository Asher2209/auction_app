"""Fill the DEV database with several months of auction history so the analytics charts have data.

    python scripts/seed.py                 # base users, categories and live auctions (run first)
    python scripts/seed_demo_activity.py   # then this

Bids, closing, payments, invoices and reviews go through the real services with backdated timestamps, so
every invariant of the app holds (one winner and one payment per closed auction, one invoice per paid
payment, reviews only from paying buyers).

IMPORTANT: crypto payments here are SYNTHETIC. There is no blockchain behind them: their wallet addresses
and transaction hashes are derived from a hash and the network is labelled "Demo (synthetic)". They exist
only to populate the charts in a local development database. Never run this against real data.
"""
import hashlib
import random
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Auction, Category, CryptoPayment, Payment, Product, User, utcnow  # noqa: E402
from app.services import auction_service as svc  # noqa: E402
from app.services import invoice_service, payment_service  # noqa: E402
from app.services import review_service as rs  # noqa: E402

PASSWORD = "Demo@1234"
ITEMS = [
    ("Electronics", ["Gaming Console", "Noise-cancelling Headphones", "4K Monitor", "Smart Watch", "Tablet 10-inch", "Bluetooth Speaker"]),
    ("Fashion", ["Silk Scarf", "Denim Jacket", "Leather Handbag", "Running Shoes", "Wool Coat"]),
    ("Home & Garden", ["Standing Lamp", "Coffee Machine", "Ceramic Vase Set", "Garden Tool Kit"]),
    ("Collectibles", ["Vintage Pocket Watch", "First-day Stamp Album", "Antique Brass Compass", "Signed Cricket Ball"]),
    ("Books", ["Complete Poetry Collection", "Illustrated Atlas", "Rare Science Journal Set"]),
    ("Sports", ["Carbon Road Bike", "Tennis Racket Pro", "Yoga Mat Bundle", "Football Signed Jersey"]),
]
COMMENTS = ["Exactly as described.", "Fast delivery, would buy again.", "Good value.", "Seller was helpful.", None, "Packaging could be better."]


def fake_hex(seed, n):
    return hashlib.sha256(seed.encode()).hexdigest()[:n]


def main():
    app = create_app()
    rng = random.Random(7)
    with app.app_context():
        if User.query.filter_by(email="buyer3@demo.test").first():
            print("Demo activity already present, nothing to do.")
            return
        sellers = User.query.filter_by(role="seller").all()
        if not sellers or not Category.query.count():
            sys.exit("Run scripts/seed.py first.")
        buyers = User.query.filter_by(role="buyer").all()
        for i in range(3, 7):
            u = User(name=f"Demo Buyer {i}", email=f"buyer{i}@demo.test", role="buyer", phone="9000000000", address="Demo Street")
            u.set_password(PASSWORD)
            db.session.add(u)
            buyers.append(u)
        db.session.commit()
        cats = {c.name: c for c in Category.query.all()}

        now = utcnow()
        made = {"closed": 0, "paid": 0, "crypto": 0, "reviews": 0}
        titles = [(c, t) for c, ts in ITEMS for t in ts]
        rng.shuffle(titles)
        for n, (cat, title) in enumerate(titles):
            seller = sellers[n % len(sellers)]
            start = now - timedelta(days=rng.randint(6, 240), hours=rng.randint(0, 23))
            end = start + timedelta(days=rng.randint(2, 7))
            if end > now - timedelta(hours=3):
                end = now - timedelta(hours=3)
            price = Decimal(rng.choice([500, 1200, 2500, 4000, 7500, 12000, 20000, 35000, 60000, 90000]))
            product = Product(seller_id=seller.id, category_id=cats[cat].id, title=title, description=f"{title}. Demo listing.",
                              starting_price=price, auction_start=start, auction_end=end, approval_status="approved", created_at=start)
            db.session.add(product)
            db.session.flush()
            auction = Auction(product_id=product.id, start_time=start, end_time=end, original_end_time=end,
                              current_bid=price, status="active")
            db.session.add(auction)
            db.session.commit()

            amount, t = price, start + timedelta(hours=2)
            for _ in range(rng.choice([0, 1, 2, 3, 3, 4, 5])):
                t += timedelta(hours=rng.randint(1, 20))
                if t >= end - timedelta(minutes=5):
                    break
                amount += Decimal(rng.choice([50, 100, 250, 500, 1000]))
                svc.place_bid(auction.id, rng.choice(buyers), str(amount), now=t)
            info = svc.close_auction(auction.id, now=end + timedelta(seconds=1))
            if info:
                made["closed"] += 1
            payment = Payment.query.filter_by(auction_id=auction.id).first()
            if payment is None:
                continue
            roll, paid_at = rng.random(), end + timedelta(hours=rng.randint(1, 30))
            winner = payment.buyer
            if roll < 0.12:
                continue  # never paid: stays pending
            if roll < 0.17:
                payment_service.pay_simulated(auction.id, winner, "card", {"card_number": "4000000000000002"}, now=paid_at)  # declined
                continue
            if roll < 0.40:  # synthetic crypto payment (see the warning at the top of this file)
                eth = (payment.amount / Decimal(320000)).quantize(Decimal("0.000001"))
                payment.payment_method, payment.method_detail, payment.payment_status = "crypto", "eth", "successful"
                payment.payment_date, payment.attempts, payment.reference = paid_at, 1, "ETH demo"
                db.session.add(CryptoPayment(
                    payment_id=payment.id, wallet_address="0x" + fake_hex(f"b{n}", 40), seller_address="0x" + fake_hex(f"s{n}", 40),
                    contract_address="0x" + fake_hex("contract", 40), cryptocurrency="ETH", expected_wei=int(eth * 10 ** 18),
                    amount=eth, exchange_rate=Decimal(320000), transaction_hash="0x" + fake_hex(f"tx{n}", 64),
                    blockchain_network="Demo (synthetic)", chain_id=0, block_number=1000 + n, confirmations=2,
                    status="confirmed", transaction_date=paid_at))
                db.session.flush()
                invoice_service.create_for_payment(payment, paid_at, announce=False)
                db.session.commit()
                made["crypto"] += 1
            else:
                kind = rng.choice(["card", "card", "upi", "wallet"])
                data = {"card": {"card_number": "4242424242424242"}, "upi": {"upi_id": "demo@bank"},
                        "wallet": {"provider": "Demo Wallet", "mobile": "9876543210"}}[kind]
                payment_service.pay_simulated(auction.id, winner, kind, data, now=paid_at)
            made["paid"] += 1
            if rng.random() < 0.65:
                try:
                    rs.save_review(winner, auction.id, str(rng.choice([3, 4, 4, 5, 5, 5])), rng.choice(COMMENTS), now=paid_at + timedelta(days=1))
                    made["reviews"] += 1
                except rs.ReviewError:
                    pass

        # a few live, upcoming and cancelled auctions so every state appears in the status chart
        for k, (status, hours) in enumerate([("active", 30), ("active", 70), ("scheduled", 120), ("cancelled", 50)]):
            cat, title = titles[k]
            p = Product(seller_id=sellers[k % len(sellers)].id, category_id=cats[cat].id, title=f"{title} (extra {k + 1})",
                        description="Demo listing.", starting_price=Decimal(3000), approval_status="approved",
                        auction_start=now + (timedelta(hours=5) if status == "scheduled" else -timedelta(hours=2)),
                        auction_end=now + timedelta(hours=hours))
            db.session.add(p)
            db.session.flush()
            db.session.add(Auction(product_id=p.id, start_time=p.auction_start, end_time=p.auction_end, original_end_time=p.auction_end,
                                   current_bid=Decimal(3000), status=status))
        db.session.commit()
        print(f"Demo activity added: {made['closed']} closed auctions, {made['paid']} paid "
              f"({made['crypto']} synthetic crypto), {made['reviews']} reviews.")


if __name__ == "__main__":
    main()
