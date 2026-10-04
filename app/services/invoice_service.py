"""Invoices: a database record per successful payment, rendered to a PDF with a verification QR code.

* create_for_payment() runs inside the transaction that marks a payment successful, so a paid
  auction always has exactly one invoice.
* The PDF is built on demand from the stored records (they never change after payment), so there
  are no files to keep in sync.
* The QR code holds a link to a public verification page. The link carries a signed token rather
  than the plain invoice number, so invoices cannot be discovered by counting.
* "Blockchain Verified" appears only on invoices for crypto payments that the server confirmed
  on the chain. Simulated payments never claim it.
"""
import io
from decimal import Decimal
from xml.sax.saxutils import escape

import qrcode
from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer
from reportlab.graphics.shapes import Drawing, PolyLine
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..extensions import db
from ..models import Invoice, utcnow
from .notifications import notify

SALT = "invoice-verify"
BRAND = colors.HexColor("#212529")
ACCENT = colors.HexColor("#0d6efd")
OK_GREEN = colors.HexColor("#198754")
MUTED = colors.HexColor("#6c757d")
LINE = colors.HexColor("#dee2e6")


# ---- records ------------------------------------------------------------------------
def create_for_payment(payment, now=None, announce=True):
    """Return the payment's invoice, creating it (and notifying the buyer) if it does not exist yet."""
    if payment.invoice is not None:
        return payment.invoice
    now = now or utcnow()
    invoice = Invoice(payment_id=payment.id, number=f"TMP-{payment.id}-{now.timestamp()}", created_at=now)
    db.session.add(invoice)
    db.session.flush()  # we need the id to build the number
    invoice.number = f"INV-{now.year}-{invoice.id:06d}"
    db.session.flush()
    if announce:
        notify(payment.buyer_id, "Invoice generated",
               f"Your invoice {invoice.number} for \"{payment.auction.product.title}\" is ready to download.",
               url=f"/invoices/{payment.auction_id}/download")
    return invoice


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def make_token(invoice):
    return _serializer().dumps(invoice.id)


def invoice_from_token(token):
    try:
        invoice_id = _serializer().loads(token)
    except BadSignature:
        return None
    return db.session.get(Invoice, invoice_id) if isinstance(invoice_id, int) else None


def verify_url(invoice):
    return f"{current_app.config['APP_BASE_URL']}/verify/{make_token(invoice)}"


def qr_png(data):
    """PNG bytes of a QR code for `data`."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


# ---- text helpers --------------------------------------------------------------------
def _t(value):
    """Make user text safe for the PDF: the built-in fonts are Latin-1 only, and Paragraph reads XML-like markup."""
    text = "" if value is None else str(value)
    return escape(text.encode("latin-1", "replace").decode("latin-1"))


def _inr(amount):
    return f"INR {Decimal(amount):,.2f}"  # the built-in PDF fonts have no rupee sign


def _dt(value):
    return value.strftime("%d %b %Y, %H:%M UTC") if value else "-"


def method_label(payment):
    if payment.payment_method == "crypto":
        net = payment.crypto.blockchain_network if payment.crypto else ""
        return f"Cryptocurrency (ETH, {net})" if net else "Cryptocurrency (ETH)"
    kinds = {"card": "Card", "upi": "UPI", "wallet": "Digital wallet"}
    return f"{kinds.get(payment.method_detail, 'Online')} (simulated)"


def is_blockchain_verified(payment):
    return bool(payment.payment_method == "crypto" and payment.crypto
                and payment.crypto.status == "confirmed" and payment.crypto.transaction_hash)


# ---- the PDF -------------------------------------------------------------------------
def _checkmark(size=13):
    """A vector check mark. (The PDF's built-in symbol fonts are not substituted the same way by every viewer.)"""
    d = Drawing(size, size)
    d.add(PolyLine([1.5, size * 0.5, size * 0.42, 2.0, size - 1, size - 1.5], strokeColor=OK_GREEN, strokeWidth=2.4,
                   strokeLineCap=1, strokeLineJoin=1))
    return d


def _styles():
    base = getSampleStyleSheet()["Normal"]
    mk = lambda name, **kw: ParagraphStyle(name, parent=base, **kw)  # noqa: E731
    return {
        "title": mk("title", fontName="Helvetica-Bold", fontSize=26, leading=30, textColor=BRAND),
        "brand": mk("brand", fontSize=9, textColor=MUTED, leading=12),
        "label": mk("label", fontSize=8, textColor=MUTED, leading=10),
        "value": mk("value", fontSize=10, leading=13),
        "bold": mk("bold", fontName="Helvetica-Bold", fontSize=10, leading=13),
        "right": mk("right", fontSize=10, leading=13, alignment=TA_RIGHT),
        "right_bold": mk("right_bold", fontName="Helvetica-Bold", fontSize=11, leading=14, alignment=TA_RIGHT),
        "mono": mk("mono", fontName="Courier", fontSize=8, leading=10),
        "small": mk("small", fontSize=8, leading=11, textColor=MUTED),
        "verified": mk("verified", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=OK_GREEN),
        "h": mk("h", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=ACCENT),
    }


def render_pdf(invoice):
    """Build the invoice PDF and return its bytes."""
    payment = invoice.payment
    auction = payment.auction
    product = auction.product
    buyer, seller = payment.buyer, product.seller
    crypto = payment.crypto if is_blockchain_verified(payment) else None
    st = _styles()
    width = A4[0] - 36 * mm - 12  # the page frame has 6pt of padding on each side; tables must fit inside it

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Invoice {invoice.number}", author="ChainBid")
    story = []

    qr = Image(io.BytesIO(qr_png(verify_url(invoice))), width=32 * mm, height=32 * mm)
    head_left = [
        Paragraph("INVOICE", st["title"]),
        Paragraph("ChainBid online auctions &middot; academic project", st["brand"]),
        Spacer(1, 4 * mm),
        Paragraph("INVOICE NUMBER", st["label"]), Paragraph(_t(invoice.number), st["bold"]),
        Spacer(1, 1.5 * mm),
        Paragraph("DATE", st["label"]), Paragraph(_dt(invoice.created_at), st["value"]),
    ]
    head_right = [qr, Paragraph("Scan to verify this invoice", ParagraphStyle("c", parent=st["small"], alignment=1))]
    head = Table([[head_left, head_right]], colWidths=[width - 40 * mm, 40 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 6 * mm)]

    parties = Table([[
        [Paragraph("BILLED TO", st["label"]), Paragraph(_t(buyer.name), st["bold"]),
         Paragraph(_t(buyer.email), st["value"]), Paragraph(_t(buyer.address or ""), st["value"])],
        [Paragraph("SOLD BY", st["label"]), Paragraph(_t(seller.name), st["bold"]),
         Paragraph(f"Auction ID: {auction.id}", st["value"])],
    ]], colWidths=[width / 2, width / 2])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [parties, Spacer(1, 6 * mm)]

    items = Table(
        [[Paragraph("DESCRIPTION", st["label"]), Paragraph("AUCTION", st["label"]), Paragraph("AMOUNT", ParagraphStyle("r", parent=st["label"], alignment=TA_RIGHT))],
         [Paragraph(f"{_t(product.title)}<br/><font size=8 color='#6c757d'>{_t(product.category.name)} &middot; winning bid</font>", st["value"]),
          Paragraph(f"#{auction.id}", st["value"]), Paragraph(_inr(payment.amount), st["right"])],
         ["", Paragraph("TOTAL", st["bold"]), Paragraph(_inr(payment.amount), st["right_bold"])]],
        colWidths=[width - 70 * mm, 25 * mm, 45 * mm])
    items.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, BRAND), ("LINEBELOW", (0, 1), (-1, 1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 1), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, -1), 0)]))
    story += [items, Spacer(1, 7 * mm)]

    rows = [("Payment method", method_label(payment)), ("Payment status", "PAID"),
            ("Payment ID", str(payment.id)), ("Payment date", _dt(payment.payment_date))]
    if payment.reference:
        rows.append(("Reference", payment.reference))
    pay = Table([[Paragraph(_t(k), st["label"]), Paragraph(_t(v), st["value"])] for k, v in rows], colWidths=[38 * mm, width - 38 * mm])
    pay.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (0, -1), 0)]))
    story += [Paragraph("PAYMENT DETAILS", st["h"]), Spacer(1, 1.5 * mm), pay, Spacer(1, 6 * mm)]

    if crypto:
        eth = format(Decimal(crypto.amount).normalize(), "f")
        chain_rows = [
            ("Amount paid", f"{eth} ETH"), ("Exchange rate", f"{_inr(crypto.exchange_rate)} per ETH" if crypto.exchange_rate else "-"),
            ("Network", f"{crypto.blockchain_network} (test network)"),
            ("Block / confirmations", f"{crypto.block_number} / {crypto.confirmations}"),
            ("Buyer wallet", crypto.wallet_address), ("Seller wallet", crypto.seller_address or "-"),
        ]
        chain = Table(
            [[Paragraph(_t(k), st["label"]), Paragraph(_t(v), st["mono"])] for k, v in chain_rows]
            + [[Paragraph("Transaction hash", st["label"]), Paragraph(_t(crypto.transaction_hash), st["mono"])]],
            colWidths=[38 * mm, width - 38 * mm - 8 * mm])
        chain.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, -1), 0)]))
        title = Table([[_checkmark(), Paragraph("Blockchain Verified", st["verified"])]], colWidths=[7 * mm, None])
        title.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
        title.hAlign = "LEFT"
        box = Table([[[title, Spacer(1, 2 * mm), chain]]], colWidths=[width])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, OK_GREEN), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1faf4")),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                 ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        story += [KeepTogether([box]), Spacer(1, 6 * mm)]

    notice = ("This invoice was issued by an academic demonstration system. "
              + ("The payment was made on a blockchain TEST network with test ETH that has no monetary value."
                 if payment.payment_method == "crypto" else "The payment was simulated; no real money was transferred.")
              + " Verify it online by scanning the QR code or visiting: " + verify_url(invoice))
    story.append(Paragraph(_t(notice), st["small"]))

    doc.build(story)
    return buf.getvalue()
