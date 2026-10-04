import io
import os
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g
from PIL import Image
from pypdf import PdfReader

from app.blueprints.invoices import routes as invoice_routes
from app.extensions import db
from app.models import Category, Invoice, Notification, Payment, Product, utcnow
from app.services import auction_service as svc
from app.services import blockchain_service as bc
from app.services import invoice_service as inv
from app.services import payment_service as ps

from .conftest import login, make_user
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_crypto import ETH, chain, mine, prepare, send, status, submit  # noqa: F401  (chain is a fixture)
from .test_payments import card, client_for, fresh, pay, titles, won


@pytest.fixture(autouse=True)
def clear_check_cache():
    invoice_routes._check_cache.clear()


def pdf_text(data):
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def squash(text):
    return re.sub(r"\s+", "", text)


def paid_card(app, users, cats, amount="500"):  # noqa: F811
    a = won(users, cats, amount=amount)
    c = client_for(app, "buyer@t.test")
    pay(c, a, "card", card())
    return a, c


def paid_crypto(app, users, cats, chain):  # noqa: F811
    users["seller"].wallet_address = chain.seller
    db.session.commit()
    a = won(users, cats, amount="80000")  # 0.25 ETH
    c = client_for(app, "buyer@t.test")
    prep = prepare(c, a, chain).json
    assert submit(c, a, send(chain, prep["tx"])).json["ok"]
    mine(chain)
    assert status(c, a)["status"] == "successful"
    return a, c


def get_invoice(a):
    db.session.expire_all()
    return Invoice.query.join(Payment).filter(Payment.auction_id == a.id).one()


def download(c, a):
    return c.get(f"/invoices/{a.id}/download")


# ---- creation --------------------------------------------------------------------------
def test_invoice_is_created_with_a_successful_card_payment(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    i = get_invoice(a)
    assert re.fullmatch(r"INV-\d{4}-\d{6}", i.number) and i.number == f"INV-{utcnow().year}-{i.id:06d}"
    assert i.payment_id == a.payment.id and i.created_at
    n = Notification.query.filter_by(user_id=users["buyer"].id, title="Invoice generated").one()
    assert i.number in n.message and n.url == f"/invoices/{a.id}/download" and not n.is_read
    assert titles(users["seller"]).count("Invoice generated") == 0  # the seller hears "Payment received" only


def test_no_invoice_for_unpaid_failed_or_processing_payments(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    assert Invoice.query.count() == 0
    pay(c, a, "card", card("4000000000000002"))   # declined
    assert Invoice.query.count() == 0
    pay(c, a, "card", card("4000000000003220"))   # pending
    assert Invoice.query.count() == 0 and download(c, a).status_code == 404


def test_invoice_is_created_when_a_pending_payment_settles(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    pay(c, a, "upi", {"upi_id": "pending@okbank"})
    assert Invoice.query.count() == 0
    ps.settle_due(now=utcnow() + timedelta(minutes=5))
    assert Invoice.query.count() == 1 and titles(users["buyer"]).count("Invoice generated") == 1


def test_invoice_is_created_for_a_confirmed_crypto_payment(app, users, cats, chain):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    assert get_invoice(a).payment.payment_method == "crypto"
    assert titles(users["buyer"]).count("Invoice generated") == 1


def test_creating_twice_gives_one_invoice_and_one_notification(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    p = fresh(a)
    again = inv.create_for_payment(p)
    db.session.commit()
    assert again.id == get_invoice(a).id and Invoice.query.count() == 1
    for _ in range(3):
        ps.settle_due(now=utcnow() + timedelta(hours=1))
        client_for(app, "buyer@t.test").get(f"/payments/{a.id}/status")
    assert titles(users["buyer"]).count("Invoice generated") == 1


def test_invoice_numbers_are_unique_and_follow_the_id(app, users, cats):  # noqa: F811
    nums = []
    for i in range(3):
        buyer_pay = won(users, cats, amount=str(100 + i))
        pay(client_for(app, "buyer@t.test"), buyer_pay, "card", card())
        nums.append(get_invoice(buyer_pay).number)
    assert len(set(nums)) == 3 and nums == sorted(nums)


# ---- the PDF ------------------------------------------------------------------------------
def test_pdf_for_a_simulated_payment(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats, amount="1234.50")
    i = get_invoice(a)
    data = inv.render_pdf(i)
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF") and len(PdfReader(io.BytesIO(data)).pages) == 1
    text = pdf_text(data)
    for expected in (i.number, "BILLED TO", "buyer", "buyer@t.test", "SOLD BY", "seller", "Red Lamp", f"Auction ID: {a.id}",
                     "INR 1,234.50", "PAID", "Card (simulated)", "Card **** 4242", "Scan to verify",
                     "no real money was transferred"):
        assert expected in text, expected
    assert "Blockchain Verified" not in text and "Transaction hash" not in text  # never claimed for simulated payments
    assert PdfReader(io.BytesIO(data)).metadata.title == f"Invoice {i.number}"


def test_pdf_for_a_crypto_payment_shows_blockchain_proof(app, users, cats, chain):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    i = get_invoice(a)
    text = pdf_text(inv.render_pdf(i))
    flat = squash(text)
    row = i.payment.crypto
    assert "Blockchain Verified" in text
    assert squash(row.transaction_hash) in flat and squash(chain.buyer) in flat and squash(chain.seller) in flat
    for expected in ("0.25ETH", "Testchain(testnetwork)", "INR80,000.00", "INR320,000.00perETH", "Cryptocurrency(ETH,Testchain)",
                     f"{row.block_number}/{row.confirmations}", "TESTnetwork", "nomonetaryvalue", i.number):
        assert expected in flat, expected
    assert "Card" not in text.split("PAYMENT DETAILS")[1].split("Blockchain")[0]


def test_unconfirmed_or_failed_crypto_never_shows_verified(app, users, cats, chain):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    i = get_invoice(a)
    i.payment.crypto.status = "pending"  # (not something the app does; proves the badge is tied to the status)
    db.session.commit()
    assert "Blockchain Verified" not in pdf_text(inv.render_pdf(get_invoice(a)))
    assert inv.is_blockchain_verified(get_invoice(a).payment) is False


@pytest.mark.parametrize("title", [
    "<b>Bold</b> & <i>italic</i> </para><br/>", 'Quote " and \' and &amp; &lt;x&gt;', "Café Über ₹ 日本語 \U0001F600",
    "x" * 300, "word " * 80, "\x00\x01 control",
])
def test_pdf_survives_hostile_text(app, users, cats, title):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], title[:190], 100)
    svc.place_bid(a.id, users["buyer"], "150")
    svc.close_auction(a.id, now=a.end_time + timedelta(seconds=1))
    users["buyer"].name = "<script>alert(1)</script> & Co"
    users["buyer"].address = "1 <Main> St & Sons"
    db.session.commit()
    pay(client_for(app, "buyer@t.test"), a, "card", card())
    r = download(client_for(app, "buyer@t.test"), a)
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    text = pdf_text(r.data)
    assert "<script>alert(1)</script> & Co" in text  # shown literally, never interpreted as markup


def test_markup_in_titles_is_shown_literally(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "<b>Rare</b> Lamp", 100)
    svc.place_bid(a.id, users["buyer"], "150")
    svc.close_auction(a.id, now=a.end_time + timedelta(seconds=1))
    pay(client_for(app, "buyer@t.test"), a, "card", card())
    assert "<b>Rare</b> Lamp" in pdf_text(inv.render_pdf(get_invoice(a)))


# ---- the QR code and verification token --------------------------------------------------------
def test_qr_encodes_the_verification_link(app, users, cats, monkeypatch):  # noqa: F811
    a, c = paid_card(app, users, cats)
    i = get_invoice(a)
    seen = []
    real = inv.qrcode.QRCode.add_data
    monkeypatch.setattr(inv.qrcode.QRCode, "add_data", lambda self, data, *x, **k: (seen.append(data), real(self, data, *x, **k))[1])
    inv.render_pdf(i)
    assert seen == [f"http://127.0.0.1:5000/verify/{inv.make_token(i)}"]


def test_qr_png_is_a_real_scannable_sized_image(app):
    png = inv.qr_png("http://127.0.0.1:5000/verify/abc")
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width == img.height >= 100
    assert set(img.convert("L").tobytes()) == {0, 255}  # strictly black and white modules


def test_the_pdf_embeds_the_qr_image(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    images = [im for page in PdfReader(io.BytesIO(inv.render_pdf(get_invoice(a)))).pages for im in page.images]
    assert len(images) == 1 and images[0].image.width >= 100


def test_the_printed_qr_code_scans_to_the_working_verification_page(app, users, cats, chain):  # noqa: F811
    """Render the real PDF page, scan the QR with an independent decoder, and open what it says."""
    pdfium = pytest.importorskip("pypdfium2")
    zxingcpp = pytest.importorskip("zxingcpp")
    for make in (lambda: paid_card(app, users, cats), lambda: paid_crypto(app, users, cats, chain)):
        a, _ = make()
        i = get_invoice(a)
        page = pdfium.PdfDocument(inv.render_pdf(i))[0].render(scale=2).to_pil()
        codes = zxingcpp.read_barcodes(page)
        assert [c.text for c in codes] == [inv.verify_url(i)]
        path = codes[0].text.removeprefix("http://127.0.0.1:5000")
        g.pop("_login_user", None)
        r = app.test_client().get(path)
        assert r.status_code == 200 and i.number in r.data.decode()


def test_token_round_trip_and_tampering(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    i = get_invoice(a)
    token = inv.make_token(i)
    assert inv.invoice_from_token(token).id == i.id
    for bad in ("", "garbage", token[:-2] + "xx", token + "A", "1", "eyJ9." + token):
        assert inv.invoice_from_token(bad) is None
    app.config["SECRET_KEY"] = "a-different-secret"
    assert inv.invoice_from_token(token) is None  # tokens do not survive a key change / cannot be forged without the key


def test_token_does_not_reveal_or_allow_guessing_ids(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    anon = app.test_client()
    g.pop("_login_user", None)
    for guess in (str(get_invoice(a).id), get_invoice(a).number, f"{get_invoice(a).id:06d}"):
        assert anon.get(f"/verify/{guess}").status_code == 404


# ---- downloading -------------------------------------------------------------------------------
def test_buyer_seller_and_admin_can_download(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    number = get_invoice(a).number
    for who in ("buyer", "seller", "admin"):
        r = download(client_for(app, f"{who}@t.test"), a)
        assert r.status_code == 200, who
        assert r.mimetype == "application/pdf" and r.headers["Content-Disposition"] == f'attachment; filename="{number}.pdf"'
        assert "no-store" in r.headers["Cache-Control"] and r.data.startswith(b"%PDF")


def test_nobody_else_can_download_or_probe(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    make_user("other@t.test")
    make_user("otherseller@t.test", "seller")
    for email in ("other@t.test", "otherseller@t.test"):
        assert download(client_for(app, email), a).status_code == 404
    g.pop("_login_user", None)
    assert download(app.test_client(), a).status_code == 302  # anonymous: sent to log in
    assert download(client_for(app, "buyer@t.test"), type("A", (), {"id": 99999})).status_code == 404


def test_old_payments_get_an_invoice_on_first_download(app, users, cats):  # noqa: F811
    """A payment that succeeded before invoices existed gets one, quietly (no new notification)."""
    a, c = paid_card(app, users, cats)
    Notification.query.delete()
    Invoice.query.delete()
    db.session.commit()
    r = download(client_for(app, "buyer@t.test"), a)
    assert r.status_code == 200 and Invoice.query.count() == 1 and Notification.query.count() == 0


def test_download_links_appear_where_they_should(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    assert "Download invoice" not in c.get(f"/payments/{a.id}").data.decode()
    assert "Invoice</a>" not in c.get("/buyer/won").data.decode()
    pay(c, a, "card", card())
    link = f"/invoices/{a.id}/download"
    assert link in c.get(f"/payments/{a.id}").data.decode() and "Download invoice (PDF)" in c.get(f"/payments/{a.id}").data.decode()
    assert link in c.get("/buyer/won").data.decode()
    assert link in client_for(app, "seller@t.test").get(f"/seller/products/{a.product_id}").data.decode()


def test_invoice_notification_link_downloads_the_pdf(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats)
    n = Notification.query.filter_by(title="Invoice generated").one()
    r = c.get(f"/notifications/{n.id}/go")
    assert r.location.endswith(f"/invoices/{a.id}/download") and download(c, a).status_code == 200


# ---- the public verification page --------------------------------------------------------------
def verify_page(app, i, query=""):
    g.pop("_login_user", None)
    return app.test_client().get(f"/verify/{inv.make_token(i)}{query}")


def test_verify_page_is_public_and_private(app, users, cats):  # noqa: F811
    a, c = paid_card(app, users, cats, amount="777")
    i = get_invoice(a)
    r = verify_page(app, i)
    html = r.data.decode()
    assert r.status_code == 200 and i.number in html and "Red Lamp" in html and "₹777.00" in html and "Genuine invoice" in html
    assert f"<dd class=\"col-sm-8\">{a.id}</dd>" in html and f"<dd class=\"col-sm-8\">{i.payment_id}</dd>" in html
    assert "b***" in html and "s***" in html  # masked names
    for secret in ("buyer@t.test", "seller@t.test", "Bella", "Sarah", "Somewhere", "9000000000", "4242"):
        assert secret not in html, secret
    assert "simulated payment" in html and "Blockchain verified" not in html and "Re-check" not in html


def test_verify_page_unknown_token_is_404(app, users, cats):  # noqa: F811
    paid_card(app, users, cats)
    g.pop("_login_user", None)
    c = app.test_client()
    for t in ("nope", "x" * 200, "..%2F..%2Fetc", "1"):
        assert c.get(f"/verify/{t}").status_code == 404


def test_verify_page_for_crypto_shows_chain_details(app, users, cats, chain):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    i = get_invoice(a)
    html = verify_page(app, i).data.decode()
    row = i.payment.crypto
    assert "Blockchain verified when the payment was made" in html and row.transaction_hash in html
    assert "Test chain (test network)" in html and "0.25 ETH" in html and "Re-check on the blockchain now" in html
    assert "https://scan.test/tx/" + row.transaction_hash in html
    assert chain.buyer not in html and chain.seller not in html and "buyer@t.test" not in html


def test_verify_page_can_recheck_the_chain(app, users, cats, chain):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    html = verify_page(app, get_invoice(a), "?check=1").data.decode()
    assert "Checked just now" in html and "pays this auction" in html and "alert-success" in html


def test_verify_recheck_reports_a_chain_that_no_longer_agrees(app, users, cats, chain, monkeypatch):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    monkeypatch.setattr(bc, "check_transaction", lambda *a, **k: bc.Check("failed", "The payment went to a different seller address."))
    html = verify_page(app, get_invoice(a), "?check=1").data.decode()
    assert "alert-danger" in html and "different seller address" in html


def test_verify_recheck_handles_an_unreachable_chain(app, users, cats, chain, monkeypatch):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)

    def down(*x, **k):
        raise ConnectionError("node unreachable")

    monkeypatch.setattr(chain.w3.eth, "get_transaction", down)
    html = verify_page(app, get_invoice(a), "?check=1").data.decode()
    assert "could not be reached" in html and verify_page(app, get_invoice(a)).status_code == 200


def test_verify_recheck_is_cached_so_the_public_page_cannot_hammer_the_node(app, users, cats, chain, monkeypatch):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    calls = []
    real = bc.check_transaction
    monkeypatch.setattr(bc, "check_transaction", lambda *x, **k: (calls.append(1), real(*x, **k))[1])
    i = get_invoice(a)
    for _ in range(5):
        verify_page(app, i, "?check=1")
    assert len(calls) == 1
    invoice_routes._check_cache[i.id] = (0, None)  # expired entry
    verify_page(app, i, "?check=1")
    assert len(calls) == 2


def test_recheck_never_runs_for_simulated_payments_or_without_the_flag(app, users, cats, chain, monkeypatch):  # noqa: F811
    a, c = paid_card(app, users, cats)
    boom = lambda *x, **k: pytest.fail("must not query the chain")  # noqa: E731
    monkeypatch.setattr(bc, "recheck", boom)
    assert verify_page(app, get_invoice(a), "?check=1").status_code == 200
    b, _ = paid_crypto(app, users, cats, chain)
    assert verify_page(app, get_invoice(b)).status_code == 200  # no ?check=1: no chain call


def test_recheck_does_not_write_to_the_database(app, users, cats, chain):  # noqa: F811
    a, c = paid_crypto(app, users, cats, chain)
    before = (Payment.query.count(), Notification.query.count(), Invoice.query.count())
    result = bc.recheck(fresh(a))
    assert result.status == "confirmed" and (Payment.query.count(), Notification.query.count(), Invoice.query.count()) == before


# ---- optional: dump the PDFs for a visual check (set INVOICE_DUMP_DIR) ------------------------------
@pytest.mark.skipif(not os.environ.get("INVOICE_DUMP_DIR"), reason="visual check only")
def test_dump_sample_pdfs(app, users, cats, chain):  # noqa: F811
    out = os.environ["INVOICE_DUMP_DIR"]
    a, _ = paid_card(app, users, cats, amount="45250")
    with open(os.path.join(out, "simulated.pdf"), "wb") as f:
        f.write(inv.render_pdf(get_invoice(a)))
    b, _ = paid_crypto(app, users, cats, chain)
    with open(os.path.join(out, "crypto.pdf"), "wb") as f:
        f.write(inv.render_pdf(get_invoice(b)))
